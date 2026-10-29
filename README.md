# MANTHAN 2026 — Bot-Integrated Scaffold

Based on the uploaded `bot.py` and `HANDOFF.md`, not a generic trading-bot template.

- Original bot preserved at `src/legacy/bot_original.py`.
- Current SMA settings and behavior captured in `CONTRACTS.md` and `config/strategy.yaml`.
- Kafka topics, event names, REST routes, and order actions transcribed from the handoff.
- Modules split into market data, news, strategy, risk, execution, portfolio, app lifecycle, and frontend.

This is a migration scaffold; the new modules are not fully wired into a runnable trading system. Verify and test before enabling orders.

Run checks:
```bash
pip install -r requirements.txt
pytest
```

`python -m src.app` is a safe stub. Do not point it at the simulator until reviewed.

## Update: wired runtime
`python -m src.app --live` runs the full loop (Kafka -> SMA strategy -> risk gate -> execution -> reconciliation). Without `--live` it only prints a hint. Tokens come from `BOT_ACCESS_TOKEN` or `TEAM_JWT_TOKEN`.
Status: unit-tested with fakes only (`pytest`); **not yet run against the live simulator or Kafka**. Do a sandbox run during the development stage before relying on it.

## Strategies
Select with the `STRATEGY` env var (default `sma_band`, the original SMA8 +/-1.5% rule).
- `sma_band` — baseline, unchanged.
- `adaptive` — volatility-scaled band (ATR), volume confirmation, market-breadth filter, chaos-regime filter, friction (brokerage + DP) check, risk-based sizing, ATR trailing stop. Long-only. **Not validated on real data yet**; compare with `src.strategy.backtest.compare` before using it live.

All strategies pass through the same risk gate. In the live run (stage `simulation`) open longs are closed on the last day (`UNWIND_DAYS`); this never triggers in the looping sandbox. On exit the bot prints a decision-latency summary.

### Disciplined strategies (opt-in via `STRATEGY=`)
`ensemble` (recommended candidate), `mean_reversion`, `trend_pullback`, `laggard_reversion`; plus `breakout`, `relative_strength` and `adaptive`, which **lost money on the real history and are not recommended**. All share a discipline layer: max 4 open names, volatility-scaled size, 3-bar minimum hold, 3-bar re-entry cooldown, ATR trailing hard stop, breadth and chaos-volatility gates, friction check, and a news veto on entries (never a trade trigger). They need ~41 daily bars of history (warm-started from `/stocks/:ticker/history`, 90 calendar days); if the live run offers no pre-run history they wait ~41 days before trading. See `docs/STRATEGY_EVAL.md` for results and limits.

## Recording the stream (for better backtests)
Read-only, safe next to the bot (no consumer group, never commits offsets):
```bash
py -m scripts.record_stream                 # record until Ctrl+C  -> data/stream_<time>.jsonl
py -m scripts.record_stream --seconds 600   # or for a fixed time
py -m scripts.record_stream --export data/stream_X.jsonl history.json news.json
py -m scripts.evaluate_strategies history.json
```
Recordings are gitignored (`data/`). The sandbox loops the same days, so about 83 minutes captures a full 500-day loop; the loader keeps one loop (`loop_count`) so repeated dates are never mixed.
