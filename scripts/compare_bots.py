"""Step 5: the old and new bots under identical conditions.

Same recording, same exchange timing (prices at T, headlines at T+150 ms, ~3.5 s per day), same offline
exchange (fills at the close, Rs 20 brokerage, Rs 15.34 DP), same real bot code (src.app.Bot); only the
strategy differs. Reports the full run, both halves, five 100-day windows, the run without PLNX and 40
random 100-day periods. Writes docs/comparison.json.

Usage: py -m scripts.compare_bots data/stream_<t>.jsonl
"""
import argparse
import json
import random
from datetime import datetime, timezone

from scripts.replay_bot import run
from src.market_data.recorder import load_stream

BOTS = [("sma_band", "original bot (Rs 50k per buy)"),
        ("sma_pro", "Step 1 baseline (Rs 75k per buy, tax harvesting)"),
        ("sma_news", "improved bot (sma_pro + news veto)")]
RANDOM_PERIODS, PERIOD_DAYS, SEED = 40, 100, 2026


def compare(history, news):
    dates = sorted({b["date"] for bars in history.values() for b in bars})
    n = len(dates)
    halves = [(0, n // 2), (n // 2, n)]
    windows = [(i * n // 5, (i + 1) * n // 5) for i in range(5)]
    rng = random.Random(SEED)
    starts = sorted(rng.randrange(0, n - PERIOD_DAYS) for _ in range(RANDOM_PERIODS))
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "days": n,
           "first_date": dates[0], "last_date": dates[-1], "headlines": len(news), "bots": {}}
    for name, label in BOTS:
        full = run(history, news, name)
        curve = full.pop("equity_by_date")
        out["bots"][name] = {
            "label": label, **full,
            "halves": [run(history, news, name, days=h) for h in halves],
            "windows_return": [run(history, news, name, days=w)["return_pct"] for w in windows],
            "without_PLNX": run(history, news, name, drop="PLNX"),
            "random_periods": [run(history, news, name, days=(s, s + PERIOD_DAYS)) for s in starts],
            "equity_curve": {d: curve[d] for d in dates[::5] + [dates[-1]] if d in curve},
        }
        for part in out["bots"][name]["halves"] + out["bots"][name]["random_periods"] + [out["bots"][name]["without_PLNX"]]:
            part.pop("equity_by_date", None)
    out["random_period_starts"] = [dates[s] for s in starts]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Step 5: old vs new bot under identical conditions")
    ap.add_argument("recording")
    ap.add_argument("--out", default="docs/comparison.json")
    args = ap.parse_args()
    history, news = load_stream(args.recording)
    res = compare(history, news)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, default=str)

    bots = res["bots"]
    print(f"{res['days']} days {res['first_date']} .. {res['last_date']}, {res['headlines']} headlines\n")
    rows = [("final wealth (Rs)", lambda b: f"{b['final_wealth']:,.0f}"),
            ("return", lambda b: f"{b['return_pct']:+.1f}%"),
            ("after tax (estimate)", lambda b: f"{b['after_tax_return_pct']:+.1f}%"),
            ("max drawdown", lambda b: f"{b['max_dd_pct']:.1f}%"),
            ("return / drawdown", lambda b: f"{b['return_pct'] / b['max_dd_pct']:.2f}"),
            ("Sharpe (daily, annualised)", lambda b: f"{b['sharpe']:.2f}"),
            ("realized / unrealized P&L (Rs)", lambda b: f"{b['realized_pnl']:,.0f} / {b['unrealized_pnl']:,.0f}"),
            ("charges (Rs)", lambda b: f"{b['charges']:,.0f}"),
            ("orders / rejected", lambda b: f"{b['orders']} / {b['rejected']}"),
            ("win rate / worst trade (Rs)", lambda b: f"{b['win_rate']:.0%} / {b['worst_trade']:,.0f}"),
            ("news vetoes", lambda b: f"{b['news_vetoes']}"),
            ("slowest order after prices", lambda b: f"{b['max_latency_s'] or 0:.2f} s"),
            ("H1 / H2 return", lambda b: " / ".join(f"{h['return_pct']:+.1f}%" for h in b["halves"])),
            ("H1 / H2 max drawdown", lambda b: " / ".join(f"{h['max_dd_pct']:.1f}%" for h in b["halves"])),
            ("100-day windows", lambda b: " ".join(f"{w:+.1f}" for w in b["windows_return"])),
            ("without PLNX", lambda b: f"{b['without_PLNX']['return_pct']:+.1f}%")]
    print(f"{'':32}" + "".join(f"{name:>26}" for name, _ in BOTS))
    for label, fmt in rows:
        print(f"{label:32}" + "".join(f"{fmt(bots[name]):>26}" for name, _ in BOTS))

    new = bots["sma_news"]["random_periods"]
    print(f"\n{RANDOM_PERIODS} random {PERIOD_DAYS}-day periods (same periods for every bot):")
    for name, _ in BOTS:
        rets = sorted(p["return_pct"] for p in bots[name]["random_periods"])
        print(f"  {name:9} median {rets[len(rets) // 2]:+5.1f}%  worst {rets[0]:+5.1f}%  best {rets[-1]:+5.1f}%  "
              f"losing periods {sum(r < 0 for r in rets)}/{len(rets)}")
    for old in ("sma_pro", "sma_band"):
        ref = bots[old]["random_periods"]
        more = sum(a["return_pct"] > b["return_pct"] for a, b in zip(new, ref))
        safer = sum(a["max_dd_pct"] <= b["max_dd_pct"] for a, b in zip(new, ref))
        diffs = sorted(a["return_pct"] - b["return_pct"] for a, b in zip(new, ref))
        print(f"  sma_news vs {old:8}: higher return in {more}/{len(ref)}, drawdown no worse in {safer}/{len(ref)}, "
              f"median difference {diffs[len(diffs) // 2]:+.1f} pp")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
