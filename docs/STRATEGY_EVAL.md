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
