"""Build docs/evidence.json: the research behind every strategy decision, from a recording.

Usage: py -m scripts.build_evidence data/stream_<time>.jsonl [--out docs/evidence.json]

Everything is replayed offline with the same code the live bot runs (fills at close,
Rs 20 brokerage, Rs 15.34 DP on sells, Indian capital-gains tax estimate). The
dashboard's "Evidence" panel renders this file.
"""
import argparse
import json
import math
import os
import statistics as st
from collections import defaultdict
from datetime import datetime, timezone

from scripts.replay_bot import run as run_bot
from src.market_data.recorder import load_stream
from src.news.filter import score_text
from src.strategy.backtest import replay
from src.strategy.registry import STRATEGIES
from src.strategy.sma import SMAStrategy

SHOWN = ["sma_news", "sma_pro", "sma_band", "ensemble", "mean_reversion", "trend_pullback",
         "laggard_reversion", "breakout", "relative_strength", "adaptive"]


def _rows(history):
    return sorted(({"ticker": t, **b} for t, bars in history.items() for b in bars),
                  key=lambda r: (r["date"], r["ticker"]))


def _subset(rows, dates, a, b):
    keep = set(dates[a:b])
    return [r for r in rows if r["date"] in keep]


def _buy_hold(rows):
    first, last = {}, {}
    for r in rows:
        first.setdefault(r["ticker"], r["close"])
        last[r["ticker"]] = r["close"]
    return sum(last[t] / first[t] - 1 for t in first) / len(first) * 100 if first else 0.0


def _buy_hold_curve(rows, start=1_000_000.0):
    first, last, curve = {}, {}, {}
    for r in rows:
        first.setdefault(r["ticker"], r["close"])
        last[r["ticker"]] = r["close"]
        curve[r["date"]] = start * sum(last[t] / first[t] for t in first) / len(first)
    return curve


def _tstat(xs):
    if len(xs) < 3:
        return None
    sd = st.pstdev(xs)
    return st.mean(xs) / (sd / math.sqrt(len(xs))) if sd else None


def news_study(history, news):
    px = {t: {b["date"]: b["close"] for b in bars} for t, bars in history.items()}
    order = {t: sorted(v) for t, v in px.items()}
    pos = {t: {d: i for i, d in enumerate(ds)} for t, ds in order.items()}
    buckets = {"strongly negative (<= -2)": [], "negative (-1)": [], "neutral (0)": [],
               "positive (+1)": [], "strongly positive (>= +2)": []}
    for ev in news:
        data = ev.get("data") or {}
        t, d = data.get("ticker"), ev.get("simulated_date")
        if t not in pos or d not in pos[t] or pos[t][d] + 1 >= len(order[t]):
            continue
        i = pos[t][d]
        nxt = px[t][order[t][i + 1]] / px[t][order[t][i]] - 1
        s = score_text(f"{data.get('headline') or ''}. {data.get('description') or ''}")
        key = ("strongly negative (<= -2)" if s <= -2 else "negative (-1)" if s == -1 else
               "neutral (0)" if s == 0 else "positive (+1)" if s == 1 else "strongly positive (>= +2)")
        buckets[key].append(nxt * 100)
    rows = [{"bucket": k, "headlines": len(v), "next_day_return_pct": st.mean(v) if v else None,
             "t_stat": _tstat(v)} for k, v in buckets.items()]
    all_s, all_r = [], []
    daily = defaultdict(float)
    for ev in news:
        data = ev.get("data") or {}
        daily[(data.get("ticker"), ev.get("simulated_date"))] += score_text(
            f"{data.get('headline') or ''}. {data.get('description') or ''}")
    for (t, d), s in daily.items():
        if t in pos and d in pos[t] and pos[t][d] + 1 < len(order[t]):
            i = pos[t][d]
            all_s.append(s)
            all_r.append(px[t][order[t][i + 1]] / px[t][order[t][i]] - 1)
    ms, mr = st.mean(all_s), st.mean(all_r)
    num = sum((a - ms) * (b - mr) for a, b in zip(all_s, all_r))
    den = math.sqrt(sum((a - ms) ** 2 for a in all_s) * sum((b - mr) ** 2 for b in all_r))
    return {"buckets": rows, "headlines": sum(len(v) for v in buckets.values()),
            "ticker_days": len(all_s), "correlation_next_day": num / den if den else None,
            "conclusion": "On its own, sentiment does not predict next-day returns (correlation ~0). But a "
                          "breakout on bad news tends to fail: skipping BUYs when the last 3 days of headlines "
                          "score -2 or worse adds ~6 points over 500 days and beats 40/40 placebo runs. News "
                          "never triggers a trade; it can only veto a buy."}


def build(recording):
    history, news = load_stream(recording)
    rows = _rows(history)
    dates = sorted({r["date"] for r in rows})
    n = len(dates)
    quarters = [(0, n // 4), (n // 4, n // 2), (n // 2, 3 * n // 4), (3 * n // 4, n)]
    q_labels = [f"{dates[a]} .. {dates[b - 1]}" for a, b in quarters]
    market_q = [_buy_hold(_subset(rows, dates, a, b)) for a, b in quarters]

    strategies = []
    curves = {"buy_and_hold": _buy_hold_curve(rows)}
    for name in SHOWN:
        f = STRATEGIES[name]
        probe = f()
        if getattr(probe, "wait_for_news_s", 0):
            # needs the exchange's news timing: run the real bot (scripts/replay_bot.py)
            bot = run_bot(history, news, name)
            full = {"return_pct": bot["return_pct"], "after_tax_return_pct": bot["after_tax_return_pct"],
                    "max_drawdown_pct": bot["max_dd_pct"], "trades": bot["orders"], "fees_paid": bot["charges"],
                    "tax_estimate": bot["tax_estimate"], "avg_utilization_pct": None, "harvest_sells": None,
                    "equity_by_date": bot["equity_by_date"]}
            qs = [run_bot(history, news, name, days=(a, b))["return_pct"] for a, b in quarters]
        else:
            harvest = bool(getattr(probe, "tax_harvest", False))
            full = replay(rows, strategy_factory=f, tax_harvest=harvest)
            qs = [replay(_subset(rows, dates, a, b), strategy_factory=f, tax_harvest=harvest)["return_pct"]
                  for a, b in quarters]
        up_m = sum(m for m in market_q if m > 0)
        dn_m = sum(m for m in market_q if m < 0)
        strategies.append({
            "id": name, "return_pct": full["return_pct"], "after_tax_return_pct": full["after_tax_return_pct"],
            "max_drawdown_pct": full["max_drawdown_pct"], "trades": full["trades"],
            "fees_paid": full["fees_paid"], "tax_estimate": full["tax_estimate"],
            "avg_utilization_pct": full["avg_utilization_pct"], "quarters_pct": qs,
            "upside_capture": sum(q for q, m in zip(qs, market_q) if m > 0) / up_m if up_m else None,
            "downside_capture": sum(q for q, m in zip(qs, market_q) if m < 0) / dn_m if dn_m else None,
            "harvest_sells": full["harvest_sells"],
        })
        if name in ("sma_news", "sma_pro", "sma_band"):
            curves[name] = full["equity_by_date"]

    grid = []
    for w in (5, 8, 12, 20):
        for band in (0.01, 0.015, 0.025):
            r = replay(rows, strategy_factory=lambda w=w, band=band: SMAStrategy(n=w, band=band))
            grid.append({"window": w, "band": band, "return_pct": r["return_pct"],
                         "max_drawdown_pct": r["max_drawdown_pct"], "trades": r["trades"]})

    brake = replay(rows, strategy_factory=STRATEGIES["sma_pro"], tax_harvest=True, drawdown_brake=0.06)
    step = max(1, n // 120)                         # keep the chart light
    curve_dates = dates[::step] + ([dates[-1]] if dates[-1] not in dates[::step] else [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {"source": "Kafka recording of the sandbox stream", "tickers": sorted(history),
                    "days": n, "first_date": dates[0], "last_date": dates[-1], "news_items": len(news),
                    "buy_and_hold_pct": _buy_hold(rows)},
        "costs": {"brokerage_inr": 20.0, "dp_charge_inr": 15.34, "stcg": 0.15, "ltcg": 0.10,
                  "ltcg_exemption_inr": 100_000},
        "quarters": {"labels": q_labels, "market_pct": market_q},
        "strategies": strategies,
        "robustness_grid": grid,
        "news": news_study(history, news),
        "equity_curves": {"dates": curve_dates,
                          "series": {k: [v.get(d) for d in curve_dates] for k, v in curves.items()}},
        "rejected": [
            {"idea": "Ensemble of dip/laggard rules", "why": "Looked best on 275 days, then -0.04% out of sample."},
            {"idea": "Regime allocator (breadth on SMA50)", "why": "+0.4% over 500 days with 10.8% drawdown at every setting tested."},
            {"idea": "Momentum: breakout / relative strength / adaptive", "why": "Trends reverse in this data; all lost money."},
            {"idea": "Account drawdown brake (6%)", "why": f"Locks the bot out of recoveries: {brake['return_pct']:+.1f}% vs "
                                                          f"{strategies[0]['return_pct']:+.1f}% without it."},
            {"idea": "News-driven trades: sell on bad news, buy bigger or earlier on good news",
             "why": "Each lowered return or failed in one half (Step 2). Only the veto on breakout buys survived."},
            {"idea": "Entry/exit tweaks: 2-close confirmation, earlier exits, trailing stops, trend and volume filters",
             "why": "None beat sma_news in both halves; a 6% trailing stop passed but failed at 5% and 7% (Step 3)."},
            {"idea": "Extra risk limits: stop-loss, exposure cap, max positions, max buys per day",
             "why": "Stops never trigger before the SMA exit; the limits cost return in one half (Step 4)."},
            {"idea": "Short selling", "why": "Downtrends were followed by rebounds; margin lock and 10-day square-off add risk."},
        ],
        "chosen": {"id": "sma_news", "why": _chosen_why()},
    }


def _chosen_why(path="docs/comparison.json"):
    why = ("The SMA8 +/-1.5% band (robust across every 5-12 day window and band tested) at 1.5x size with "
           "year-end tax-loss harvesting, plus a news veto: each BUY waits 0.5 s for the day's headlines and is "
           "skipped after bad news.")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            bots = json.load(fh).get("bots", {})
        new, old = bots.get("sma_news", {}).get("random_periods"), bots.get("sma_pro", {}).get("random_periods")
        if new and old:
            more = sum(a["return_pct"] > b["return_pct"] for a, b in zip(new, old))
            why += (f" Under identical conditions it beat the version without news in {more} of {len(new)} "
                    f"random 100-day periods (scripts/compare_bots.py).")
    return why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--out", default="docs/evidence.json")
    args = ap.parse_args()
    ev = build(args.recording)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, indent=1, default=str)
    best = ev["strategies"][0]
    print(f"wrote {args.out}: {ev['dataset']['days']} days, {ev['dataset']['news_items']} news; "
          f"{best['id']} {best['return_pct']:+.1f}% (after tax {best['after_tax_return_pct']:+.1f}%), "
          f"max DD {best['max_drawdown_pct']:.1f}%; buy&hold {ev['dataset']['buy_and_hold_pct']:+.1f}%")


if __name__ == "__main__":
    main()
