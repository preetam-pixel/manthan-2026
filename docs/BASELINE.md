# Baseline before the improvement roadmap (Step 1)

Recorded 2026-10-30. Nothing in the strategy was changed for this step.

## Backup

| What | Where | Restore with |
|---|---|---|
| Exact code snapshot | git tag `baseline-step1` (commit `2398c1a`) | `git checkout baseline-step1 -- src frontend scripts` |
| Full folder copy (code, data, docs, `.env`, git history) | `C:\Users\beast\OneDrive\Desktop\Qubix_backup_original` | copy the folder back; do not edit it |

The copy was checked against the original: 2,352 files, same commit, identical code, data, docs and `.env`.
Only `logs/` can differ, because the running bot keeps writing to it.

## Where things live

| Roadmap name | Actual file | Role |
|---|---|---|
| `bot.py` | `src/app.py` | Orchestration: Kafka loop, heartbeat, stage, sync, decisions, dashboard hooks |
| `src/strategy/sma.py` | same | SMA band rule; `sma_pro()` = live configuration |
| `src/contracts.py` | same | `Signal(ticker, action, quantity, timestamp, reason)` |
| `src/news/consumer.py` | same, plus `src/news/filter.py` | Headline formatting; negation-aware keyword score (explanations only) |
| `src/market_data/consumer.py` | same | Tick / pre-flight parsing |
| `src/portfolio/state.py` | same | Holdings and cash, synced from the exchange |
| `src/features/build.py` | same | SMA/ATR/RSI helpers; used only by research strategies, not by the live bot |
| — | `src/risk/manager.py` | Risk gate every order passes |
| — | `src/execution/client.py` | The only module that calls the REST gateway |
| — | `src/strategy/backtest.py` | Offline 500-day replay, used for every comparison |
| `tests/` | `tests/unit/` | 179 tests, no network needed (`py -m pytest`) |

## Current settings

| Setting | Value |
|---|---|
| Strategy | `sma_pro` (`STRATEGY=sma_pro` in `.env`) |
| SMA window | 8 daily closes |
| Entry / exit band | buy > SMA8 × 1.015, sell all < SMA8 × 0.985 |
| Order size | Rs 75,000 per buy |
| Max position per stock | Rs 1,50,000 (at most two buys) |
| Mode | Long-only |
| Tax-loss harvesting | On (sells losing lots before 31 March when it saves tax) |
| News | Logged and shown with each decision; does not trigger or block trades |

## Baseline 1: 500-day replay (the yardstick for Step 5)

Same recording (10 stocks, 2024-10-25 to 2026-10-23), fills at the close, Rs 20 brokerage, Rs 15.34 DP charge.
Every later change is run through exactly this replay and compared with these numbers.

| | `sma_pro` (live) | `sma_band` (original) |
|---|---|---|
| Final total wealth | Rs 12,87,836 | Rs 11,79,243 |
| Return / after tax | +28.8% / +25.4% | +17.9% / +15.9% |
| Realized P&L (before charges) | Rs 2,39,656 | Rs 1,52,056 |
| Unrealized P&L at the end | Rs 62,622 | Rs 41,694 |
| Total charges | Rs 14,442 | Rs 14,507 |
| Orders / rejected | 548 / 0 | 552 / 0 |
| Max drawdown | 10.5% | 7.1% |
| Estimated tax | Rs 33,806 | Rs 20,703 |

Robustness of `sma_pro` (docs/STRATEGY_EVAL.md): positive in both halves and all five 100-day windows;
+19.5% even with the best stock (PLNX) removed.

## Baseline 2: live sandbox account (exchange figures, 2026-10-30 03:33)

| | Value |
|---|---|
| Simulated date | 2025-11-11 (day 262 of 500) |
| Total wealth | Rs 12,21,725.83 |
| Total P&L (exchange, before charges) | Rs 2,43,171.91 (+24.32%) |
| Realized / unrealized P&L | Rs 2,42,673.71 / Rs 498.20 |
| Total charges | Rs 21,420.26 |
| Orders / rejected / errors | 811 / 0 / 1 |
| Cash / invested | Rs 9,96,256.50 / Rs 2,25,469.33 (3 positions) |

Caveat: this account mixes several bot sessions and strategies run tonight (and resets when the sandbox loop
restarts), so it is a health check, not a clean comparison. Use Baseline 1 to compare strategies.

## Results against this baseline

| Step | Change | 500-day replay (real bot code) | Rule |
|---|---|---|---|
| 2 | `sma_news`: skip a BUY when the stock's last 3 days of news score <= -2 | +34.4% vs +28.8%, DD 10.0% vs 10.3%, better in both halves, all windows positive, +25.3% without PLNX | pass |
| 3 | 14 entry/exit ideas on top of `sma_news` (confirmation, earlier exits, trailing stops, trend, volume, up day, cooldown, second-buy rules) | none beats +34.4% robustly; a 6% trailing stop passed but failed at 5% and 7% | no change |
| 4 | stop-loss, exposure caps, position and daily-buy limits, drawdown brake | stops never trigger (the SMA exit fires first); limits cost return in one half; brake at 6% locks the bot out. Live audit: 1,153 orders, 0 rejected, 0 duplicates | no change |
| 5 | original vs `sma_pro` vs `sma_news`, identical conditions (docs/STEP5_COMPARISON.md) | `sma_news` +34.4% vs +28.8% / +17.9%; Sharpe 1.39 vs 1.15 / 1.06; beats `sma_pro` in 33 of 40 random 100-day periods | `sma_news` stays live |

## Rule for Steps 2-4

A change goes live only if, on the replay above, it beats `sma_pro` on return per unit of drawdown in
both halves, keeps all five 100-day windows positive, and still holds with PLNX removed.
Earlier results to keep in mind (docs/STRATEGY_EVAL.md):

- **News:** on its own, sentiment does not predict returns (correlation about -0.01 to -0.03 at 1-10 days).
  Used as a veto on breakout buys with the day's own headlines, it passes (Step 2 above).
- **Confirmation:** waiting for 2 closes above the band helped at SMA8 ±1.5% but hurt at neighbouring settings.
- **Risk controls already in place:** per-stock cap, cash check, no duplicate or in-flight orders, sell ≤ holdings,
  fresh-data check, trading only while the simulation runs, uncertain orders frozen until reconciled.
