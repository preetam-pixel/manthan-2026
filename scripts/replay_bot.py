"""Replay a recording through the REAL bot (src.app.Bot) with a simulated clock.

Each simulated day follows the exchange's timing: prices at T, headlines at T+150 ms, then the
bot's timer runs every 0.1 s until the next day starts (DAY_S later). Orders go to the offline
exchange (src.dashboard.demo.SimulatedAPI), which fills at that day's close. So this measures
the exact code that trades live, including the news-gated BUY wait.

Usage:
  py -m scripts.replay_bot data/stream_<t>.jsonl --strategies sma_pro sma_news
"""
import argparse
from collections import defaultdict

from src.app import Bot
from src.dashboard.demo import SimulatedAPI
from src.journal import DecisionJournal
from src.market_data.recorder import load_stream
from src.strategy.registry import create

DAY_S = 3.5            # live run: one simulated day every ~3-4 s
NEWS_AT_S = 0.15       # headlines arrive ~150 ms after the prices
TIMER_S = 0.1


def run(history: dict, news: list, strategy, days: tuple = None, drop: str = None, risk=None) -> dict:
    """``strategy``: a registered name, or a factory returning a strategy object (for research).
    ``risk``: optional factory returning a RiskManager to use instead of the default one."""
    dates = sorted({b["date"] for bars in history.values() for b in bars})
    if days:
        dates = dates[days[0]:days[1]]
    tickers = sorted(t for t in history if t != drop)
    bars = {t: {b["date"]: b for b in history[t]} for t in tickers}
    headlines = defaultdict(list)
    for ev in news:
        if (ev.get("data") or {}).get("ticker") in bars:
            headlines[ev.get("simulated_date")].append(ev)

    now = [0.0]
    api = SimulatedAPI(tickers, total_days=len(dates), interval_seconds=DAY_S)
    strat = create(strategy) if isinstance(strategy, str) else strategy()
    bot = Bot(api, strategy=strat, risk=risk() if risk else None, log=lambda *a: None, clock=lambda: now[0],
              warm_start=False, strategy_name=getattr(strat, "name", str(strategy)), journal=DecisionJournal())
    bot.startup()
    peak, max_dd, wealth = api.cash, 0.0, api.cash
    for i, d in enumerate(dates):
        start = i * DAY_S
        now[0] = start
        for t in tickers:
            bar = bars[t].get(d)
            if bar is None:
                continue
            ohlcv = {k: bar.get(k) for k in ("open", "high", "low", "close", "volume")}
            api.observe(t, d, ohlcv)
            bot.handle_message("market.ticks", {"event_type": "price_tick", "simulated_date": d,
                                                "timestamp": f"{d}T10:00:00Z", "data": {"ticker": t, **ohlcv}})
        now[0] = start + NEWS_AT_S
        for ev in headlines.get(d, ()):
            bot.handle_message("market.news", ev)
        step = 1
        while NEWS_AT_S + step * TIMER_S < DAY_S - TIMER_S:
            now[0] = start + NEWS_AT_S + step * TIMER_S
            bot.on_timer()
            step += 1
        p = api.get_portfolio()
        wealth = p["total_wealth"]
        peak = max(peak, wealth)
        max_dd = max(max_dd, (peak - wealth) / peak)
    stats = bot.journal.stats()
    vetoed = sum(1 for e in bot.journal.recent(2000) if str(e.get("risk_reason") or "").startswith("news veto"))
    return {"return_pct": (wealth / 1_000_000 - 1) * 100, "max_dd_pct": max_dd * 100,
            "orders": api.orders, "rejected": api.rejected, "charges": api.charges,
            "news_vetoes": vetoed, "decisions": stats["decisions"],
            "max_latency_s": max(bot.latencies) if bot.latencies else None}


def compare(history: dict, news: list, strategies: list) -> list:
    """Full run, both halves, five 100-day windows and the run without PLNX, per strategy."""
    n = len({b["date"] for bars in history.values() for b in bars})
    halves = [(0, n // 2), (n // 2, n)]
    windows = [(i * n // 5, (i + 1) * n // 5) for i in range(5)]
    out = []
    for s in strategies:
        full = run(history, news, s)
        hs = [run(history, news, s, days=h) for h in halves]
        out.append({"strategy": s if isinstance(s, str) else getattr(s, "__name__", "custom"), "full": full,
                    "halves_return_per_dd": [h["return_pct"] / h["max_dd_pct"] if h["max_dd_pct"] else None for h in hs],
                    "windows_return": [run(history, news, s, days=w)["return_pct"] for w in windows],
                    "without_PLNX_return": run(history, news, s, drop="PLNX")["return_pct"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recording")
    ap.add_argument("--strategies", nargs="+", default=["sma_pro", "sma_news"])
    args = ap.parse_args()
    history, news = load_stream(args.recording)
    print(f"{'strategy':10}{'return':>8}{'max DD':>8}{'ret/DD':>8}{'orders':>8}{'vetoes':>8}{'max lat':>9}"
          f"{'H1 r/DD':>9}{'H2 r/DD':>9}   100-day windows                  no PLNX")
    for r in compare(history, news, args.strategies):
        f = r["full"]
        print(f"{r['strategy']:10}{f['return_pct']:>+7.1f}%{f['max_dd_pct']:>7.1f}%{f['return_pct'] / f['max_dd_pct']:>8.2f}"
              f"{f['orders']:>8}{f['news_vetoes']:>8}{f['max_latency_s'] or 0:>8.2f}s"
              f"{r['halves_return_per_dd'][0]:>9.2f}{r['halves_return_per_dd'][1]:>9.2f}   "
              + " ".join(f"{w:+5.1f}" for w in r["windows_return"]) + f"   {r['without_PLNX_return']:+5.1f}")


if __name__ == "__main__":
    main()
