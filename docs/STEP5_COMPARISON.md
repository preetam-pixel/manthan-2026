# Step 5: old vs new bot under identical conditions

Recorded 2026-10-30. Reproduce with `py -m scripts.compare_bots data/stream_<t>.jsonl` (writes `docs/comparison.json`).

## Identical conditions

Each bot is the real `src.app.Bot` code; only the strategy changes.

| Condition | Value |
|---|---|
| Data | Kafka recording: 500 days, 10 stocks, 8,126 headlines (2024-10-25 to 2026-10-23) |
| Timing | Exchange timing from the problem statement: prices at T, headlines at T+150 ms, next day ~3.5 s later |
| Exchange | Offline exchange: fills at the day's close, Rs 20 brokerage, Rs 15.34 DP charge on sells |
| Start | Rs 10,00,000 cash, no positions |

## The three bots

| Bot | What it is |
|---|---|
| `sma_band` (original) | SMA8 ±1.5% band, Rs 50,000 per buy, Rs 1,00,000 per stock |
| `sma_pro` (Step 1 baseline) | Same rule at Rs 75,000 per buy / Rs 1,50,000 per stock, plus tax-loss harvesting before 31 March |
| `sma_news` (improved, live) | `sma_pro` plus a news veto: each BUY waits 0.5 s for the day's headlines and is skipped if the stock's last 3 days of news score -2 or worse |

## Results

| | `sma_band` | `sma_pro` | **`sma_news`** |
|---|---|---|---|
| Final total wealth | Rs 11,79,243 | Rs 12,87,836 | **Rs 13,43,785** |
| Return | +17.9% | +28.8% | **+34.4%** |
| After tax (estimate) | +15.9% | +25.4% | **+30.0%** |
| Max drawdown | **7.0%** | 10.3% | 10.0% |
| Return / drawdown | 2.57 | 2.78 | **3.44** |
| Sharpe (daily, annualised) | 1.06 | 1.15 | **1.39** |
| Realized / unrealized P&L | Rs 1,44,069 / 41,694 | Rs 2,31,634 / 62,622 | **Rs 2,95,959** / 53,765 |
| Charges | Rs 14,507 | Rs 14,442 | **Rs 13,397** |
| Orders / rejected | 552 / 0 | 548 / 0 | 508 / 0 |
| Win rate / worst trade | 37% / -Rs 10,323 | 37% / -Rs 15,450 | 39% / -Rs 15,450 |
| Buys skipped on bad news | — | — | 52 |
| Slowest order after the prices | at once | at once | 0.55 s (window ~3 s) |

### Robustness

| | `sma_band` | `sma_pro` | **`sma_news`** |
|---|---|---|---|
| First half / second half | +16.3% / +3.2% | +23.5% / +3.6% | **+25.8% / +11.0%** |
| Five 100-day windows | +4.7 +10.1 +0.9 +0.8 +3.4 | +7.0 +15.7 +1.1 +1.5 +5.6 | **+7.9 +16.8 +1.7 +3.7 +6.5** |
| Without PLNX (the +338% stock) | +12.2% | +20.4% | **+25.3%** |
| Quarters (market +15.6 / +30.2 / **-13.1** / +9.5) | +5.3 / +8.4 / -0.1 / +4.5 | +7.6 / +12.0 / -2.2 / +7.5 | +8.9 / +11.3 / **+3.1** / +9.6 |

### 40 random 100-day periods (the same periods for every bot)

| | `sma_band` | `sma_pro` | **`sma_news`** |
|---|---|---|---|
| Median / worst / best | +1.8% / -3.2% / +11.1% | +3.2% / -4.4% / +17.0% | **+4.8% / -2.1% / +18.2%** |
| Losing periods | 7 of 40 | 13 of 40 | **4 of 40** |

- `sma_news` vs `sma_pro`: higher return in **33 of 40** periods, drawdown no worse in 33 of 40, median +1.7 points.
- `sma_news` vs the original `sma_band`: higher return in **40 of 40** periods (median +2.5 points). Drawdown is deeper
  in all of them, because positions are 1.5x larger.

## What made the difference

1. **Size (Step 1, `sma_band` → `sma_pro`):** 1.5x the capital at work. More return, deeper drawdown, similar
   return per unit of drawdown.
2. **News veto (Step 2, `sma_pro` → `sma_news`):** skips breakout buys after bad news. News on its own predicts
   nothing here, but a breakout on bad news tends to fail. This turned the weak second half (+3.6%) into +11.0%,
   gained in the Q3 sell-off, and beat 40 of 40 placebo runs with the headlines on the wrong stock or date.
3. **Steps 3 and 4 changed nothing:** 14 entry/exit ideas and 13 risk rules were tested; none beat `sma_news` on
   every check (docs/STRATEGY_EVAL.md).

## Limits

- One 500-day dataset. The live run uses a different, unseen period. The news gain rests on about 40-50 skipped
  trades, so +6 points is an estimate, not a promise; the random-period results (33 of 40) are the fairer guide.
- `sma_news` takes more risk than the original bot (10.0% vs 7.0% max drawdown) in exchange for about twice the return.
- The tax figure is our FIFO estimate (STCG 15%, LTCG 10% above Rs 1 lakh); the exchange's report is authoritative.

## Live status

`sma_news` is live since 2026-10-30 03:45 (`STRATEGY=sma_news`, dashboard at http://127.0.0.1:8080/). Live audit
of 1,153 orders that night: all filled, 0 rejected, 0 duplicates; buys go out about 0.5-0.7 s after the prices.
