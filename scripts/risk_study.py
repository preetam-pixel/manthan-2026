"""Step 4 study: extra risk rules on top of sma_news, run through the real bot (scripts.replay_bot).

Same Step 1 rule as the other studies: better return per unit of drawdown in both halves, all five
100-day windows positive, at least as good without PLNX, and the neighbouring settings must agree.
Results: docs/STRATEGY_EVAL.md.

Usage: py -m scripts.risk_study data/stream_<t>.jsonl [name filter ...]
"""
import argparse
from collections import defaultdict

from scripts.entry_exit_study import Variant, make
from scripts.replay_bot import run
from src.contracts import Signal
from src.market_data.recorder import load_stream
from src.risk.manager import Decision, RiskManager

CAP = 150_000


class PortfolioRisk(RiskManager):
    """The live risk gate plus portfolio-level limits on new BUYs (sells are never limited).

    max_exposure      invested value after the buy <= this share of total wealth
    max_positions     no new stock once this many are held
    max_buys_per_day  at most this many BUY orders per simulated day
    dd_brake          no BUYs while wealth is more than this fraction below its peak
    Wealth comes from the exchange's last /portfolio answer (re-read 2 s after each day).
    """

    def __init__(self, max_exposure=None, max_positions=None, max_buys_per_day=None, dd_brake=None):
        super().__init__(max_pos_value=CAP)
        self.max_exposure, self.max_positions = max_exposure, max_positions
        self.max_buys_per_day, self.dd_brake = max_buys_per_day, dd_brake
        self.buys = defaultdict(int)
        self.peak = None

    def evaluate(self, signal, price, tick_age_s, simulated_date, universe, portfolio, sim_running):
        d = super().evaluate(signal, price, tick_age_s, simulated_date, universe, portfolio, sim_running)
        if not d.approved or signal.action != "BUY":
            return d
        wealth = (portfolio.exchange or {}).get("total_wealth")
        held = {t for t, q in portfolio.held.items() if q > 0}
        if self.max_positions and signal.ticker not in held and len(held) >= self.max_positions:
            return Decision(False, "max open positions")
        if self.max_exposure and wealth and portfolio.cash is not None:
            invested = wealth - portfolio.cash + signal.quantity * price
            if invested > self.max_exposure * wealth:
                return Decision(False, "max portfolio exposure")
        if self.max_buys_per_day and self.buys[simulated_date] >= self.max_buys_per_day:
            return Decision(False, "max new buys per day")
        if self.dd_brake and wealth:
            self.peak = max(self.peak or wealth, wealth)
            if (self.peak - wealth) / self.peak > self.dd_brake:
                return Decision(False, "drawdown brake")
        self.buys[simulated_date] += 1
        return d


class StopLoss(Variant):
    """Also sell a position that closes more than ``stop_loss`` below its first entry price."""

    def __init__(self, stop_loss=0.08, **kw):
        super().__init__(**kw)
        self.stop_loss = stop_loss

    def on_bar(self, t, bar, held, ts):
        c = bar.get("close")
        entry = self.entry.get(t) or self.pending_entry.get(t)
        sig = super().on_bar(t, bar, held, ts)
        if held > 0 and entry and c and c < entry * (1 - self.stop_loss) and (sig is None or sig.action != "SELL"):
            return Signal(t, "SELL", held, ts, f"stop-loss {self.stop_loss:.0%} below entry")
        return sig


def risk(**kw):
    return lambda: PortfolioRisk(**kw)


BASE = make("sma_news")
CASES = [
    ("sma_news (live)", BASE, None),
    *[(f"stop-loss {p}% below entry", make(f"stop{p}", StopLoss, stop_loss=p / 100), None) for p in (5, 8, 12)],
    *[(f"max exposure {p}% of wealth", BASE, risk(max_exposure=p / 100)) for p in (60, 75, 90)],
    *[(f"max {n} open positions", BASE, risk(max_positions=n)) for n in (6, 8)],
    *[(f"max {n} new buys per day", BASE, risk(max_buys_per_day=n)) for n in (2, 3)],
    *[(f"drawdown brake {p}%", BASE, risk(dd_brake=p / 100)) for p in (6, 8)],
]


def evaluate(history, news, strategy, risk_factory):
    n = len({b["date"] for bars in history.values() for b in bars})
    full = run(history, news, strategy, risk=risk_factory)
    halves = [run(history, news, strategy, days=h, risk=risk_factory) for h in ((0, n // 2), (n // 2, n))]
    windows = [run(history, news, strategy, days=(i * n // 5, (i + 1) * n // 5), risk=risk_factory)["return_pct"]
               for i in range(5)]
    no_plnx = run(history, news, strategy, drop="PLNX", risk=risk_factory)["return_pct"]
    return full, [h["return_pct"] / h["max_dd_pct"] if h["max_dd_pct"] else 0.0 for h in halves], windows, no_plnx


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 4 risk study")
    ap.add_argument("recording")
    ap.add_argument("only", nargs="*")
    args = ap.parse_args()
    history, news = load_stream(args.recording)
    cases = [CASES[0]] + [c for c in CASES[1:] if not args.only or any(o in c[0] for o in args.only)]
    print(f"{'rule (on top of sma_news)':30}{'ret':>7}{'DD':>6}{'r/DD':>6}{'ord':>5} {'H1 r/DD':>8}{'H2 r/DD':>8}"
          f"  100-day windows               noPLNX  rule")
    base = None
    for name, strategy, risk_factory in cases:
        f, halves, windows, no_plnx = evaluate(history, news, strategy, risk_factory)
        if base is None:
            base, verdict = (halves, no_plnx), "baseline"
        else:
            ok = all(x > y for x, y in zip(halves, base[0])) and min(windows) > 0 and no_plnx >= base[1]
            verdict = "PASS" if ok else "fail"
        print(f"{name:30}{f['return_pct']:>+6.1f}%{f['max_dd_pct']:>5.1f}%{f['return_pct'] / f['max_dd_pct']:>6.2f}"
              f"{f['orders']:>5} {halves[0]:>8.2f}{halves[1]:>8.2f}  "
              + " ".join(f"{w:+5.1f}" for w in windows) + f"   {no_plnx:+5.1f}  {verdict}", flush=True)


if __name__ == "__main__":
    main()
