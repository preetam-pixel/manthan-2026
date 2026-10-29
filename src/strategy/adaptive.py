"""Adaptive, volatility-aware long-only strategy (optional; SMA8 band stays the default).

Rules (all inputs are known at decision time; no look-ahead):
  * SMA8 of the prior eight closes, like the baseline.
  * Band = clamp(BAND_ATR_MULT * ATR14 / close, BAND_MIN, BAND_MAX) instead of fixed 1.5%.
  * BUY needs: close above the band, volume confirmation, healthy market breadth,
    not a chaotic regime, an expected move that clears trading frictions,
    and the per-ticker position cap.
  * Size is risk-based: smaller notional for more volatile stocks, never above NOTIONAL.
  * SELL entire long position when close falls below the band, or on an ATR trailing stop.
Never shorts.
"""
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from src.contracts import Signal
from src.features.build import atr, volume_ratio
from src.strategy.sma import MAX_POS_VALUE, NOTIONAL, SMA_N

ATR_WINDOW = 14
MIN_BARS = ATR_WINDOW + 1          # prior bars needed before any signal
MAX_BARS = 40

BAND_ATR_MULT = 1.0
BAND_MIN = 0.010
BAND_MAX = 0.040
MIN_VOLUME_RATIO = 1.0
MIN_BREADTH = 0.40                 # share of tracked stocks above their own SMA8
MIN_TRACKED_FOR_BREADTH = 3
CHAOS_ATR_PCT = 0.06               # no new buys when ATR% is this high
TRAIL_ATR_MULT = 2.0
RISK_PER_TRADE_INR = 2_500         # ~0.25% of Rs 10,00,000 at a 2*ATR stop

BROKERAGE_INR = 20.0
DP_CHARGE_INR = 15.34
ROUND_TRIP_COST_INR = 2 * BROKERAGE_INR + DP_CHARGE_INR
FRICTION_MULT = 3.0                # expected move must be >= 3x round-trip cost


def _clean_bar(bar: dict) -> Optional[dict]:
    close = bar.get("close")
    if isinstance(close, bool) or not isinstance(close, (int, float)) or close <= 0:
        return None

    def num(key, default):
        v = bar.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else default

    return {"open": num("open", float(close)), "high": num("high", float(close)),
            "low": num("low", float(close)), "close": float(close),
            "volume": num("volume", None)}


class AdaptiveStrategy:
    name = "adaptive"

    def __init__(self):
        self.bars = defaultdict(lambda: deque(maxlen=MAX_BARS))
        self.peak: dict[str, float] = {}
        self.state: dict[str, tuple[float, float]] = {}   # ticker -> (close, sma8)

    # ---- lifecycle --------------------------------------------------
    def warm_start_bars(self, ticker: str, prior_bars) -> None:
        """Seed from bars strictly before the current simulation date."""
        history = self.bars[ticker]
        history.clear()
        for bar in prior_bars:
            cleaned = _clean_bar(bar)
            if cleaned:
                history.append(cleaned)
        self.peak.pop(ticker, None)

    def reset(self, ticker: str) -> None:
        self.bars.pop(ticker, None)
        self.peak.pop(ticker, None)
        self.state.pop(ticker, None)

    def breadth(self) -> Optional[float]:
        if len(self.state) < MIN_TRACKED_FOR_BREADTH:
            return None
        return sum(c > s for c, s in self.state.values()) / len(self.state)

    # ---- decision ---------------------------------------------------
    def on_bar(self, ticker: str, bar: dict, held_quantity: int,
               timestamp: datetime) -> Optional[Signal]:
        cur = _clean_bar(bar or {})
        if ticker is None or cur is None:
            return None
        history = self.bars[ticker]
        prior = list(history)
        signal = None
        if len(prior) >= MIN_BARS:
            signal = self._decide(ticker, cur, prior, held_quantity, timestamp)
        history.append(cur)                      # append only after the decision
        return signal

    def _decide(self, ticker, cur, prior, held, ts) -> Optional[Signal]:
        closes = [b["close"] for b in prior]
        close = cur["close"]
        sma = sum(closes[-SMA_N:]) / SMA_N
        atr_v = atr(prior, ATR_WINDOW)
        if not atr_v or atr_v <= 0:
            self.state[ticker] = (close, sma)
            return None
        atr_pct = atr_v / close
        band = min(max(BAND_ATR_MULT * atr_pct, BAND_MIN), BAND_MAX)
        dev = close / sma - 1.0
        self.state[ticker] = (close, sma)

        if held > 0:
            prev_peak = self.peak.get(ticker, closes[-1])
            self.peak[ticker] = max(prev_peak, close)
            if close < sma * (1 - band):
                return Signal(ticker, "SELL", held, ts,
                              f"close {dev:+.2%} below SMA{SMA_N}, band {band:.2%} (ATR {atr_pct:.2%})")
            if close < prev_peak - TRAIL_ATR_MULT * atr_v:
                return Signal(ticker, "SELL", held, ts,
                              f"trailing stop: {TRAIL_ATR_MULT:g} ATR below peak {prev_peak:.2f}")
        else:
            self.peak.pop(ticker, None)

        if close <= sma * (1 + band):
            return None
        if atr_pct >= CHAOS_ATR_PCT:
            return None                                       # chaotic regime: abstain
        vr = volume_ratio([b["volume"] for b in prior], cur["volume"])
        if vr is None or vr < MIN_VOLUME_RATIO:
            return None                                       # breakout without volume
        breadth = self.breadth()
        if breadth is not None and breadth < MIN_BREADTH:
            return None                                       # weak market
        notional = min(NOTIONAL, RISK_PER_TRADE_INR / (2 * atr_pct))
        qty = max(1, int(notional // close))
        if (held + qty) * close > MAX_POS_VALUE:
            return None
        if qty * close * atr_pct < FRICTION_MULT * ROUND_TRIP_COST_INR:
            return None                                       # edge too small after costs
        breadth_txt = "n/a" if breadth is None else f"{breadth:.0%}"
        return Signal(ticker, "BUY", qty, ts,
                      f"close {dev:+.2%} above SMA{SMA_N} (band {band:.2%}, ATR {atr_pct:.2%}, "
                      f"vol x{vr:.1f}, breadth {breadth_txt})")
