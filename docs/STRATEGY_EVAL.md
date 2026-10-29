# Strategy evaluation (Member 2)

## Status
- **Measured on real data: nothing.** The historical OHLCV schema (`GET /api/v1/stocks/history`) has not been verified, so no real-data metrics exist and no profitability is claimed.
- **Built:** `src/strategy/backtest.py` — chronological replay (`replay`) and non-overlapping windows (`walk_forward`) of the unchanged SMA8 +/-1.5% strategy.
- **Tests:** `tests/unit/test_backtest.py` use hand-built series that exercise mechanics only (determinism, brokerage, no look-ahead ordering, invalid prices skipped).

## Method
- Input rows: `{date, ticker, close}` in chronological order; out-of-order input raises.
- The strategy sees only data up to and including the current row; the signal uses the prior 8 closes, then the current close is appended.
- Fills at tick close, flat Rs 20 brokerage per order (observed in simulator, per API_VERIFIED.md). Long-only, no shorting.
- Metrics: final equity, return %, max drawdown %, trade count, open positions.
- Parameters are fixed (nothing is fitted), so walk-forward windows are independent out-of-sample replays with fresh warm-up.

## Limitations
- No slippage, taxes/charges beyond brokerage, or cash-margin rules of the real simulator.
- Results on a short or single-regime window must not be presented as evidence of edge.

## To finish once history schema is known
Write a small loader mapping the verified history response to `{date, ticker, close}`, run `walk_forward`, and record the numbers here.

## Update: adaptive strategy and comparison
- `src/strategy/adaptive.py` adds an opt-in strategy; baseline remains default (CONTRACTS.md requires team approval before changing live behaviour).
- `backtest.compare(rows, {"sma_band": ..., "adaptive": ...})` replays identical rows through several strategies. Fees now include the Rs 15.34 DP charge on sells; **taxes are still not modelled**.
- Still **no real-data results**: run the comparison on `/stocks/:ticker/history` bars (walk-forward) and record numbers here before choosing `adaptive` for the live run.

## Real-data evaluation (10 stocks, 275 daily bars, 2025-08-27 .. 2026-10-01)
Source: `GET /stocks/:ticker/history` from the test simulation. Costs: Rs 20 brokerage + Rs 15.34 DP on sells; **taxes not modelled**. Three overlapping windows (W1/W2/W3), parameters fixed in advance, long-only, Rs 10,00,000 start. Equal-weight buy-and-hold over the same period: **-6.4%** (6 of 10 stocks fell; ORCX -42%).

| strategy | ALL ret% | max DD% | trades | W1 / W2 / W3 ret% | avg net %/round-trip | win% |
|---|---|---|---|---|---|---|
| sma_band (default) | +0.26 | 4.52 | 315 | +1.53 / -0.66 / +0.18 | -0.20 | 31 |
| adaptive | -6.88 | 8.68 | 200 | -1.48 / -3.37 / -1.67 | -6.22 | 20 |
| breakout | -1.60 | 2.56 | 44 | +0.69 / -1.46 / -0.89 | -4.74 | 14 |
| relative_strength | -1.65 | 3.32 | 111 | +1.39 / -0.91 / -2.21 | -3.08 | 27 |
| trend_pullback | -0.38 | 1.65 | 88 | +0.17 / -0.34 / -0.33 | -0.72 | 47 |
| mean_reversion | +0.27 | 0.63 | 67 | +0.12 / -0.12 / +0.02 | -0.77 | 44 |
| laggard_reversion | +0.72 | 2.32 | 254 | -1.44 / +0.30 / +1.56 | -0.04 | 47 |
| **ensemble** | **+0.82** | **0.31** | 58 | +0.16 / +0.28 / +0.35 | +1.00 | 61 |

### What the data shows (and does not)
- Daily returns have ~zero autocorrelation. The 20-day trend tends to **reverse** (8/10 stocks; top-3 20-day winners trail the bottom-3 by ~0.23%/day), which is why momentum rules (breakout, relative_strength, adaptive) lose here.
- The reversal effect is **not statistically significant** (t ~0.3-1.0, need ~2) and not stable across sub-periods. Laggards' average 5-day gain (~+0.14%) is about the cost of a round trip (~0.11%).
- **ensemble** was profitable in all three windows, but: it was assembled *after* looking at this data, has only 33 round trips, and the live run uses a different period. Treat as promising, **not proven**. Expect modest results; its main value is low drawdown and low turnover.
- The news filter (entry veto only) cannot be backtested: no historical news is available from the API. It is unit-tested only.
- Reproduce: `py scripts/evaluate_strategies.py history.json`.

## Leaderboard comparison (test run) and what it implies
Top-10 teams in the test run reported total wealth Rs 11.5L - 18.2L (+15% to +88%), 82-98% cash utilization for the leaders, 0 errors, 0.5-3.7 s decision time, taxes up to Rs 63k. Our bot was not on that list.
- We cannot see their strategies. Part of their result may come from the **repeating test dataset** (the sandbox loops, so a bot can learn it); that does not transfer to the confidential live period, and the jury explicitly penalises "lucky price swings".
- On our real-history replay, **trends do not persist** (uptrends -0.5% over the next 5 days, downtrends +0.3% to +0.9%), so trend-following and trend-shorting both lose; no tradable edge was found.
- Our disciplined rules deploy very little capital (ensemble: ~1-4% average utilization), so returns are small by construction and the cash-utilization pillar scores low.
- `ensemble_scaled` (100k notional, 8 positions): +1.80%, max drawdown 0.60%, avg utilization 2.5% on the same 275 bars (vs +0.82% / 0.31% / 1.2% for `ensemble`). Utilization is still low.
- Not done / not validated: tax-loss harvesting (needs verified tax/portfolio fields), shorting (not approved in CONTRACTS.md; no edge found on the short side), any claim of beating the leaderboard.
