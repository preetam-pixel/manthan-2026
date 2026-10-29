"""Disciplined long-only strategies: few, selective, risk-sized trades.

One shared discipline layer wraps several entry/exit rule sets:
  * trade only stocks in an uptrend (SMA30 rising, close above it), or oversold
    dips inside a non-falling trend for the mean-reversion rule;
  * market-breadth gate, chaos-volatility gate, news veto (entries only);
  * at most MAX_POSITIONS open names, per-ticker cap, volatility-scaled size;
  * minimum holding period, re-entry cooldown, ATR trailing hard stop;
  * friction check (brokerage + DP) before every entry.
Everything uses only bars known at decision time. Never shorts.
"""
from collections import defaultdict, deque
from datetime import datetime
from statistics import mean
from types import SimpleNamespace
from typing import Callable, Optional

from src.contracts import Signal
from src.features.build import atr, rsi, volume_ratio
from src.news.filter import NewsFilter
from src.strategy.sma import MAX_POS_VALUE, NOTIONAL

MIN_BARS = 41                  # SMA30 and its 10-bar-old value need 40 closes
MAX_BARS = 80
HISTORY_DAYS = 90              # calendar days of history to warm-start from (~60 bars)

MAX_POSITIONS = 4
MIN_HOLD_BARS = 3              # strategy exits wait this long; the hard stop never waits
COOLDOWN_BARS = 3              # no re-entry right after an exit
STOP_ATR = 2.5                 # trailing hard stop distance
CHAOS_ATR_PCT = 0.06
MIN_BREADTH = 0.20             # share of tracked stocks trading above their SMA30
RISK_PER_TRADE_INR = 2_500     # ~0.25% of capital at the stop distance
BROKERAGE_INR = 20.0
DP_CHARGE_INR = 15.34
ROUND_TRIP_COST_INR = 2 * BROKERAGE_INR + DP_CHARGE_INR
FRICTION_MULT = 3.0


def _clean_bar(bar: dict) -> Optional[dict]:
    close = bar.get("close")
    if isinstance(close, bool) or not isinstance(close, (int, float)) or close <= 0:
        return None

    def num(key, default):
        v = bar.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else default

    return {"date": bar.get("date") or bar.get("simulated_date"),
            "open": num("open", float(close)), "high": num("high", float(close)),
            "low": num("low", float(close)), "close": float(close), "volume": num("volume", None)}


# ---- rule sets: each returns a human-readable reason, or None --------------
def _uptrend(x) -> bool:
    return x.c > x.sma30 and x.sma10 > x.sma30 and x.sma30 >= x.sma30_prev


def pullback_entry(x):
    if _uptrend(x) and x.rsi5 is not None and x.rsi5 <= 40:
        return f"pullback in uptrend (RSI5 {x.rsi5:.0f}, close {x.c / x.sma30 - 1:+.1%} vs SMA30)"


def pullback_exit(x):
    if x.c < x.sma30 - 0.5 * x.atr:
        return "lost uptrend (close below SMA30)"
    if x.rsi5 is not None and x.rsi5 >= 75:
        return f"overbought take-profit (RSI5 {x.rsi5:.0f})"


def breakout_entry(x):
    if x.c > x.high20 and x.vr is not None and x.vr >= 1.2 and x.c > x.sma30 and x.sma30 >= x.sma30_prev:
        return f"20-day high breakout on volume x{x.vr:.1f}"


def breakout_exit(x):
    if x.c < x.low10:
        return "broke below 10-day low"


def meanrev_entry(x):
    if (x.sma30 >= x.sma30_prev * 0.99 and x.rsi5 is not None and x.rsi5 < 30
            and x.c < x.sma10 - 1.5 * x.atr):
        return f"oversold dip (RSI5 {x.rsi5:.0f}) in non-falling trend"


def meanrev_exit(x):
    if x.c >= x.sma10:
        return "reverted to 10-day mean"
    if x.bars_held >= 8:
        return "time stop (8 bars)"


def rs_entry(x):
    if x.rank is not None and x.rank <= 3 and x.mom20 is not None and x.mom20 > 0 and x.c > x.sma30:
        return f"relative strength rank {x.rank}/{x.ranked} (20d {x.mom20:+.1%})"


def rs_exit(x):
    if x.rank is None or x.rank > 5:
        return "fell out of top-5 relative strength"
    if x.c < x.sma30:
        return "lost uptrend (close below SMA30)"


LAGGARD_N = 3          # buy only the weakest N names by 10-day return (fixed a priori, not tuned)
LAGGARD_EXIT_N = 5     # leave once a name is no longer among the weakest 5
LAGGARD_MAX_BARS = 5   # time stop


def laggard_entry(x):
    if x.rank10 is not None and x.ranked10 >= 8 and x.rank10 > x.ranked10 - LAGGARD_N:
        return f"10-day laggard {x.rank10}/{x.ranked10} ({x.mom10:+.1%}) - reversion candidate"


def laggard_exit(x):
    if x.rank10 is None or x.rank10 <= x.ranked10 - LAGGARD_EXIT_N:
        return "recovered from laggard group"
    if x.bars_held >= LAGGARD_MAX_BARS:
        return f"time stop ({LAGGARD_MAX_BARS} bars)"


Rule = Callable[[SimpleNamespace], Optional[str]]


class DisciplinedStrategy:
    history_days = HISTORY_DAYS

    def __init__(self, name: str, entries: list[Rule], exits: list[Rule],
                 min_entry_votes: int = 1, news: Optional[NewsFilter] = None,
                 notional: Optional[float] = None, risk_per_trade: Optional[float] = None,
                 max_positions: Optional[int] = None):
        self.name = name
        self.notional = NOTIONAL if notional is None else notional
        self.risk_per_trade = RISK_PER_TRADE_INR if risk_per_trade is None else risk_per_trade
        self.max_positions = MAX_POSITIONS if max_positions is None else max_positions
        self.entries, self.exits, self.min_entry_votes = entries, exits, min_entry_votes
        self.news = news or NewsFilter()
        self.bars = defaultdict(lambda: deque(maxlen=MAX_BARS))
        self.held_seen: dict[str, int] = {}
        self.entry_t: dict[str, int] = {}
        self.exit_t: dict[str, int] = {}
        self.peak: dict[str, float] = {}
        self.trend_up: dict[str, bool] = {}
        self.t: dict[str, int] = defaultdict(int)

    # ---- lifecycle (same hooks the bot already uses) ----------------
    def warm_start_bars(self, ticker: str, prior_bars) -> None:
        history = self.bars[ticker]
        history.clear()
        for bar in prior_bars:
            cleaned = _clean_bar(bar)
            if cleaned:
                history.append(cleaned)
        self.t[ticker] = len(history)

    def sync_holdings(self, held: dict) -> None:
        self.held_seen.update(held)

    def reset(self, ticker: str) -> None:
        for d in (self.bars, self.held_seen, self.entry_t, self.exit_t, self.peak, self.trend_up, self.t):
            d.pop(ticker, None)
        self.news.reset(ticker)

    def breadth(self) -> Optional[float]:
        if len(self.trend_up) < 3:
            return None
        return sum(self.trend_up.values()) / len(self.trend_up)

    # ---- context ----------------------------------------------------
    def _rank(self, ticker: str, before: Optional[str], look: int = 20):
        """``look``-bar momentum rank (1 = strongest) from bars dated before ``before``,
        so every ticker is ranked on the same completed days."""
        moms = {}
        for tk, bars in self.bars.items():
            closes = [b["close"] for b in bars if before is None or (b["date"] and b["date"] < before)]
            if len(closes) >= look + 1 and closes[-look - 1] > 0:
                moms[tk] = closes[-1] / closes[-look - 1] - 1
        if ticker not in moms:
            return None, None, len(moms)
        order = sorted(moms, key=lambda k: -moms[k])
        return order.index(ticker) + 1, moms[ticker], len(moms)

    def _context(self, ticker, prior, cur) -> SimpleNamespace:
        closes = [b["close"] for b in prior]
        c = cur["close"]
        atr_v = atr(prior, 14) or 0.0
        rank, mom20, ranked = self._rank(ticker, cur["date"])
        rank10, mom10, ranked10 = self._rank(ticker, cur["date"], 10)
        return SimpleNamespace(
            rank10=rank10, mom10=mom10, ranked10=ranked10,
            c=c, sma10=mean(closes[-10:]), sma30=mean(closes[-30:]), sma30_prev=mean(closes[-40:-10]),
            atr=atr_v, atr_pct=atr_v / c, rsi5=rsi(closes + [c], 5),
            high20=max(closes[-20:]), low10=min(b["low"] for b in prior[-10:]),
            vr=volume_ratio([b["volume"] for b in prior], cur["volume"]),
            rank=rank, mom20=mom20, ranked=ranked,
            bars_held=self.t[ticker] - self.entry_t.get(ticker, self.t[ticker]))

    # ---- decision ---------------------------------------------------
    def on_bar(self, ticker: str, bar: dict, held_quantity: int,
               timestamp: datetime) -> Optional[Signal]:
        cur = _clean_bar(bar or {})
        if ticker is None or cur is None:
            return None
        self.held_seen[ticker] = held_quantity
        if held_quantity == 0:
            self.entry_t.pop(ticker, None)
            self.peak.pop(ticker, None)
        elif ticker not in self.entry_t:
            self.entry_t[ticker] = self.t[ticker]            # holding we did not open this session
        history = self.bars[ticker]
        prior = list(history)
        signal = None
        if len(prior) >= MIN_BARS:
            x = self._context(ticker, prior, cur)
            self.trend_up[ticker] = x.c > x.sma30 and x.sma30 >= x.sma30_prev
            signal = self._exit(ticker, x, held_quantity, timestamp) if held_quantity > 0 \
                else self._entry(ticker, x, cur, timestamp)
        history.append(cur)
        self.t[ticker] += 1
        return signal

    def _exit(self, ticker, x, held, ts) -> Optional[Signal]:
        peak = max(self.peak.get(ticker, x.c), x.c)
        stop_level = self.peak.get(ticker, x.c) - STOP_ATR * x.atr
        self.peak[ticker] = peak
        reason = None
        if x.atr > 0 and x.c < stop_level:
            reason = f"trailing stop ({STOP_ATR:g} ATR below peak {self.peak.get(ticker):.2f})"
        elif x.bars_held >= MIN_HOLD_BARS:
            for rule in self.exits:
                reason = rule(x)
                if reason:
                    break
        if not reason:
            return None
        self.exit_t[ticker] = self.t[ticker]
        return Signal(ticker, "SELL", held, ts, reason)

    def _entry(self, ticker, x, cur, ts) -> Optional[Signal]:
        if x.atr <= 0 or x.atr_pct >= CHAOS_ATR_PCT:
            return None
        if self.t[ticker] - self.exit_t.get(ticker, -10**9) < COOLDOWN_BARS:
            return None
        if sum(1 for v in self.held_seen.values() if v > 0) >= self.max_positions:
            return None
        breadth = self.breadth()
        if breadth is not None and breadth < MIN_BREADTH:
            return None
        if self.news.veto_buy(ticker, cur["date"]):
            return None
        reasons = [r for r in (rule(x) for rule in self.entries) if r]
        if len(reasons) < self.min_entry_votes:
            return None
        notional = min(self.notional, self.risk_per_trade / (STOP_ATR * x.atr_pct))
        qty = max(1, int(notional // x.c))
        if qty * x.c > MAX_POS_VALUE:
            return None
        if qty * x.c * 2 * x.atr_pct < FRICTION_MULT * ROUND_TRIP_COST_INR:
            return None
        self.entry_t[ticker] = self.t[ticker]
        self.peak[ticker] = x.c
        return Signal(ticker, "BUY", qty, ts, "; ".join(reasons))


# ---- the five strategies ---------------------------------------------------
def trend_pullback(news=None):
    return DisciplinedStrategy("trend_pullback", [pullback_entry], [pullback_exit], news=news)


def breakout(news=None):
    return DisciplinedStrategy("breakout", [breakout_entry], [breakout_exit], news=news)


def mean_reversion(news=None):
    return DisciplinedStrategy("mean_reversion", [meanrev_entry], [meanrev_exit], news=news)


def relative_strength(news=None):
    return DisciplinedStrategy("relative_strength", [rs_entry], [rs_exit], news=news)


def laggard_reversion(news=None):
    return DisciplinedStrategy("laggard_reversion", [laggard_entry], [laggard_exit], news=news)


def ensemble(news=None):
    """Enter when at least two of pullback / oversold-dip / laggard agree; exit on any of them."""
    return DisciplinedStrategy("ensemble", [pullback_entry, meanrev_entry, laggard_entry],
                               [pullback_exit, meanrev_exit, laggard_exit], min_entry_votes=2, news=news)


def ensemble_scaled(news=None):
    """Same rules as ``ensemble`` with 2x notional/risk and 8 positions (moderate capital deployment)."""
    strat = ensemble(news)
    strat.name = "ensemble_scaled"
    strat.notional, strat.risk_per_trade, strat.max_positions = 100_000, 5_000, 8
    return strat
