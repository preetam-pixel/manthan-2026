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
