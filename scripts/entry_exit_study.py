"""Step 3 study: entry/exit variants on top of sma_news, run through the real bot (scripts.replay_bot).

Each variant is judged by the Step 1 rule against sma_news: better return per unit of drawdown in
both halves, all five 100-day windows positive, and at least as good without PLNX. A change that
passes must also pass at neighbouring settings. Results: docs/STRATEGY_EVAL.md.

Usage: py -m scripts.entry_exit_study data/stream_<t>.jsonl [name filter ...]
"""
import argparse
from collections import defaultdict

from scripts.replay_bot import compare
from src.contracts import Signal
from src.market_data.recorder import load_stream
from src.news.filter import NewsFilter
from src.strategy.sma import NEWS_LOOKBACK_DAYS, NEWS_VETO_SCORE, NEWS_WAIT_S, SMAStrategy


class Variant(SMAStrategy):
    """sma_news's SMA8 +/-1.5% rule with optional entry filters and exits.

    confirm        buy only after this many consecutive closes above the band
    exit_band      sell this far below the SMA (default: the entry band)
    trail          also sell when the close falls this far below the best close since entry
    trend_n        buy only above the SMA of this many closes
    vol_confirm    buy only when volume >= this multiple of the 20-day average
    up_day         buy only on a close above the previous close
    cooldown       days without new buys after a losing exit
    add_if_profit  second buy only when the open position is up this much
    one_buy        never add to an open position
    """

    def __init__(self, confirm=1, exit_band=None, trail=None, trend_n=None, vol_confirm=None,
                 up_day=False, cooldown=0, add_if_profit=None, one_buy=False):
        super().__init__(notional=75_000, max_position_value=150_000, name="variant")
        self.confirm, self.trail, self.trend_n = confirm, trail, trend_n
        self.vol_confirm, self.up_day, self.cooldown = vol_confirm, up_day, cooldown
        self.add_if_profit, self.one_buy = add_if_profit, one_buy
        self.exit_band = self.band if exit_band is None else exit_band
        self.hist = defaultdict(list)                     # ticker -> [(close, volume)]
        self.entry, self.peak, self.pending_entry = {}, {}, {}
        self.cool, self.streak = defaultdict(int), defaultdict(int)

    def reset(self, ticker):
        super().reset(ticker)
        self.hist.pop(ticker, None)

    def on_bar(self, t, bar, held, ts):
        c, v = bar.get("close"), bar.get("volume")
        if not c or c <= 0:
            return None
        h, sig = self.hist[t], None
        if held == 0:
            self.entry.pop(t, None)
            self.peak.pop(t, None)
        else:
            self.entry.setdefault(t, self.pending_entry.get(t, c))
            self.peak[t] = max(self.peak.get(t, c), c)
        self.pending_entry.pop(t, None)
        if self.cool[t] > 0:
            self.cool[t] -= 1
        if len(h) >= self.n:
            closes = [x[0] for x in h]
            sma = sum(closes[-self.n:]) / self.n
            above = c > sma * (1 + self.band)
            self.streak[t] = self.streak[t] + 1 if above else 0
            if held > 0:
                stopped = self.trail is not None and c < self.peak[t] * (1 - self.trail)
                if c < sma * (1 - self.exit_band) or stopped:
                    sig = Signal(t, "SELL", held, ts, "exit")
                    if c < self.entry.get(t, c):
                        self.cool[t] = self.cooldown
            if sig is None and above and self.streak[t] >= self.confirm and self.cool[t] == 0:
                ok = not (held > 0 and self.one_buy)
                if self.trend_n:
                    ok = ok and len(closes) >= self.trend_n and c > sum(closes[-self.trend_n:]) / self.trend_n
                if self.vol_confirm:
                    vols = [x[1] for x in h[-20:] if x[1]]
                    ok = ok and bool(v) and bool(vols) and v >= self.vol_confirm * sum(vols) / len(vols)
                if self.up_day:
                    ok = ok and c > closes[-1]
                if held > 0 and self.add_if_profit is not None:
                    ok = ok and c >= self.entry.get(t, c) * (1 + self.add_if_profit)
                qty = max(1, int(self.notional // c))
                if ok and (held + qty) * c <= self.max_position_value:
                    sig = Signal(t, "BUY", qty, ts, "entry")
                    if held == 0:
                        self.pending_entry[t] = c
        h.append((c, v))
        del h[:-60]
        return sig


class Rearm(Variant):
    """After a trailing-stop exit, buy again only once the close has been back at/below the SMA."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.blocked = set()

    def on_bar(self, t, bar, held, ts):
        h, c = self.hist[t], bar.get("close")
        if len(h) >= self.n and c and c <= sum(x[0] for x in h[-self.n:]) / self.n:
            self.blocked.discard(t)
        stopped = held > 0 and self.trail is not None and c and c < self.peak.get(t, c) * (1 - self.trail)
        sig = super().on_bar(t, bar, held, ts)
        if sig and sig.action == "SELL" and stopped:
            self.blocked.add(t)
        if sig and sig.action == "BUY" and t in self.blocked:
            self.streak[t] = 0
            return None
        return sig


def make(label, cls=Variant, **kw):
    """Factory for scripts.replay_bot: the variant plus sma_news's tax harvesting and news veto."""
    def factory():
        s = cls(**kw)
        s.tax_harvest = True
        s.news = NewsFilter(lookback_days=NEWS_LOOKBACK_DAYS, veto_threshold=NEWS_VETO_SCORE)
        s.wait_for_news_s = NEWS_WAIT_S
        s.name = label
        return s
    factory.__name__ = label
    return factory


VARIANTS = [
    make("sma_news (reproduced)"),
    make("confirm 2 closes", confirm=2),
    make("exit at SMA (0%)", exit_band=0.0),
    make("exit 0.75% below SMA", exit_band=0.0075),
    *[make(f"trailing stop {p}%", trail=p / 100) for p in (4, 5, 6, 7, 8, 10)],
    *[make(f"trail {p}% + no instant re-buy", Rearm, trail=p / 100) for p in (5, 6, 7)],
    make("trend: above SMA20", trend_n=20),
    make("trend: above SMA50", trend_n=50),
    make("volume >= 20d avg", vol_confirm=1.0),
    make("volume >= 1.5x 20d avg", vol_confirm=1.5),
    make("up-day confirmation", up_day=True),
    make("cooldown 3 days after loss", cooldown=3),
    make("cooldown 5 days after loss", cooldown=5),
    make("2nd buy only if +2% in profit", add_if_profit=0.02),
    make("one buy per stock (no 2nd)", one_buy=True),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 3 entry/exit study")
    ap.add_argument("recording")
    ap.add_argument("only", nargs="*", help="run only variants whose name contains one of these")
    args = ap.parse_args()
    history, news = load_stream(args.recording)
    variants = [VARIANTS[0]] + [v for v in VARIANTS[1:] if not args.only or any(o in v.__name__ for o in args.only)]
    print(f"{'variant':32}{'ret':>7}{'DD':>6}{'r/DD':>6}{'ord':>5}{'veto':>5} {'H1 r/DD':>8}{'H2 r/DD':>8}"
          f"  100-day windows               noPLNX  rule")
    base = None
    for r in compare(history, news, variants):
        f = r["full"]
        row = (r["halves_return_per_dd"], r["windows_return"], r["without_PLNX_return"])
        if base is None:
            base, verdict = row, "baseline"
        else:
            ok = all(x > y for x, y in zip(row[0], base[0])) and min(row[1]) > 0 and row[2] >= base[2]
            verdict = "PASS" if ok else "fail"
        print(f"{r['strategy']:32}{f['return_pct']:>+6.1f}%{f['max_dd_pct']:>5.1f}%{f['return_pct'] / f['max_dd_pct']:>6.2f}"
              f"{f['orders']:>5}{f['news_vetoes']:>5} {row[0][0]:>8.2f}{row[0][1]:>8.2f}  "
              + " ".join(f"{w:+5.1f}" for w in row[1]) + f"   {row[2]:+5.1f}  {verdict}", flush=True)


if __name__ == "__main__":
    main()
