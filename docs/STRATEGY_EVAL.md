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
- Reproduce: `py -m scripts.evaluate_strategies history.json`.

## Leaderboard comparison (test run) and what it implies
Top-10 teams in the test run reported total wealth Rs 11.5L - 18.2L (+15% to +88%), 82-98% cash utilization for the leaders, 0 errors, 0.5-3.7 s decision time, taxes up to Rs 63k. Our bot was not on that list.
- We cannot see their strategies. Part of their result may come from the **repeating test dataset** (the sandbox loops, so a bot can learn it); that does not transfer to the confidential live period, and the jury explicitly penalises "lucky price swings".
- On our real-history replay, **trends do not persist** (uptrends -0.5% over the next 5 days, downtrends +0.3% to +0.9%), so trend-following and trend-shorting both lose; no tradable edge was found.
- Our disciplined rules deploy very little capital (ensemble: ~1-4% average utilization), so returns are small by construction and the cash-utilization pillar scores low.
- `ensemble_scaled` (100k notional, 8 positions): +1.80%, max drawdown 0.60%, avg utilization 2.5% on the same 275 bars (vs +0.82% / 0.31% / 1.2% for `ensemble`). Utilization is still low.
- Not done / not validated: tax-loss harvesting (needs verified tax/portfolio fields), shorting (not approved in CONTRACTS.md; no edge found on the short side), any claim of beating the leaderboard.

## 500-day study (full Kafka recording, 2024-10-25 .. 2026-10-23) — current conclusions
Data: `scripts/record_stream` captured all 500 days for 10 stocks and 8,125 headlines; loops were identical (0 conflicting bars) and the bars match `/stocks/:ticker/history` exactly on every shared date. Rebuild everything with `py -m scripts.build_evidence data/stream_<t>.jsonl` (writes `docs/evidence.json`, shown in the dashboard).

| strategy | return | after tax | max DD | quarters (market +15.6 / +30.2 / -13.1 / +9.5) |
|---|---|---|---|---|
| **sma_pro** (chosen) | **+28.8%** | **+25.4%** | 10.5% | +7.6 / +12.0 / -2.2 / +7.5 |
| sma_band (original) | +17.9% | +15.9% | 7.1% | +5.3 / +8.4 / -0.1 / +4.5 |
| ensemble | +1.1% | +0.8% | 0.7% | out-of-sample (days 1-208): -0.04% |
| buy & hold, equal weight | +44.9% | — | Q3 -13.1% | — |

- **Out-of-sample check.** Days 1-208 were never used to design anything. The ensemble that looked best on days 212-490 earned -0.04% there; the SMA band earned +13.5%.
- **Robustness.** SMA band windows 5/8/12 x bands 1%/1.5%/2.5%: all positive (+9% to +18%); 20-day windows fail. We kept the original 8/1.5% rather than the best cell.
- **Sizing.** 1.5x (Rs 75k per trade, Rs 1.5L cap) -> +28.2% / DD 10.2%; 2x -> +31.7% / DD 12.5%. 1.5x chosen as the moderate option.
- **Tax-loss harvesting** before 31 March: +0.6 pp; small because positions are short-lived.
- **Rejected:** regime allocator (+0.4%, DD 10.8%, robust failure across SMA30-80), drawdown brake (locks the bot out: +2.5%), news trading/veto (no predictive power: corr -0.018, all |t| < 2), shorting (downtrends rebounded).
- Earlier sections of this file reflect the 275-day study and are kept for the record; where they differ, this section supersedes them.

## Stress test of rule changes (2026-10-30)
Goal: find a change to the SMA8 ±1.5% rule that beats it on every check, not just on the full 500 days.
Checks: both 250-day halves, five separate 100-day windows, the whole run without PLNX (the +338% stock),
leave-one-stock-out (worst case of the 10), Sharpe ratio per half, and neighbouring parameter values.

**The rule does not depend on one lucky stock.** Without PLNX, sma_band still makes +12.2% (DD 6.2%) and
sma_pro +19.5% (DD 9.0%); removing any other single stock hurts less. All five 100-day windows are positive.

| change tested (on top of SMA8 ±1.5%) | result | verdict |
|---|---|---|
| Trailing stop 5-12% from the best close (with and without re-arm) | ±0.5 pp; 8% and wider never trigger | no effect |
| Volatility-scaled size | lower DD only when second buys are allowed; one-buy version loses return | not robust |
| Buy only after 2 closes above the band | DD 7.1% → 5.1% at SMA8 ±1.5%, but worse at SMA5 ±2%, SMA8 ±2%, all SMA12; 3 closes collapses | fragile, rejected |
| Exit at the SMA instead of 1.5% below | DD 7.1% → 5.2%, Sharpe first half 1.72 → 1.96, **second half 0.44 → 0.21**; exit 0.5% below brings DD back to 10% | not robust, rejected |
| Wider exit band (2.5%, 3.5%) | lower return, larger worst trade | rejected |
| Long-term trend filter (SMA20 / SMA50) | fewer trades, lower return, second half negative with SMA50 | rejected |
| Cooldown after a losing exit (3/5/10 days) | lower return | rejected |
| Adding to winners only (+3% / +6%) | higher return with higher DD; return/DD worse | rejected |

| sizing (same rule) | return | max DD | Sharpe | Sharpe H1 / H2 |
|---|---|---|---|---|
| 50k per buy, 1L cap (`sma_band`) | +17.9% | 7.1% | 1.06 | 1.72 / 0.44 |
| 75k, one buy | +21.0% | 8.6% | 1.12 | 1.88 / 0.35 |
| 75k per buy, 1.5L cap (`sma_pro`) | +28.2% | 10.2% | 1.13 | 1.69 / 0.37 |
| 1L, one buy | +28.4% | 11.0% | 1.15 | 1.90 / 0.36 |

**Conclusion.** No rule change beat the original SMA8 ±1.5% band on every check; each one that helped in one
half hurt in the other. Size is the only reliable dial, and it moves return and drawdown together (Sharpe ≈ 1.1
at every size). We keep the rule and choose size by the drawdown we accept.

## Step 2: news in trading decisions (2026-10-30)
Question: can headlines improve `sma_pro`? Exchange timing (problem statement): prices at T, headlines at
T+150 ms, orders until the next day ~3 s later, all filled at that day's close. So a decision can use the
day's own headlines and still trade at the day's close. 95% of recorded headlines arrive just after the
day's prices.

**News alone predicts nothing.** Daily news score vs the stock's return over the next 1/3/5/10 days, net of
the market: correlation -0.012 / -0.006 / -0.017 / -0.025 over ~2,900 stock-days; no sentiment bucket is
consistent across horizons and halves.

**But bad news on a breakout day predicts the breakout failing.** Replay of `sma_pro` + one news rule each:

| rule (on top of sma_pro) | 500 days | max DD | ret/DD H1 / H2 | no PLNX | Step 1 rule |
|---|---|---|---|---|---|
| none (sma_pro) | +28.2% | 10.0% | 2.38 / 0.47 | +19.5% | — |
| skip BUY if last 3 days of news <= -2 | **+34.3%** | 9.7% | 2.69 / 1.34 | +25.2% | pass |
| skip BUY if last 3 days <= -1 | +31.7% | 8.9% | 2.60 / 1.40 | +22.1% | pass |
| skip BUY if last 5 days <= -2 | +33.4% | 9.5% | 2.68 / 1.30 | +24.3% | pass |
| skip BUY on busy news days (4+ headlines) | +28.3% | 9.8% | 2.49 / 0.95 | +19.5% | pass (no gain) |
| sell on bad news today (<= -2 / <= -1) | +26.8% / +25.0% | 10.0% | worse H1 | lower | fail |
| 1.5x size on good news (+1 / +2) | +29.3% / +28.5% | 10.8% | worse H2 / H1 | lower | fail |
| enter early (above SMA, below band) on good news | +27.6% / +27.4% | 10.4% | worse | lower | fail |

Checks on the veto (threshold -2, 3 days):
- **Needs the day's own headlines:** +34.3% vs +29.3% using only news up to the day before. Live, a BUY waits
  0.5 s for the headlines; sells never wait.
- **Not one lucky trade:** 38 skipped buys across 9 stocks; 5 days later the median one was down 2.5%
  (63% negative).
- **Placebo:** the same headlines moved to a random stock (20 runs) or a shifted date (20 runs) give
  +21% to +31% (median +28%, i.e. no effect); the real veto beat all 40.

**Same result through the real bot code** (`py -m scripts.replay_bot data/stream_<t>.jsonl`: `src.app.Bot`,
simulated clock, prices at T, headlines at T+150 ms, 0.1 s timer, offline exchange):

| | return | max DD | ret/DD | H1 / H2 ret/DD | 100-day windows | no PLNX | orders | slowest order |
|---|---|---|---|---|---|---|---|---|
| `sma_pro` | +28.8% | 10.3% | 2.78 | 2.28 / 0.47 | +7.0 +15.7 +1.1 +1.5 +5.6 | +20.4% | 548 | at once |
| `sma_news` | **+34.4%** | 10.0% | **3.44** | 2.58 / **1.94** | +7.9 +16.8 +1.7 +3.7 +6.5 | **+25.3%** | 508 | 0.55 s |

This corrects the earlier note that a news veto lowered returns: that version only saw headlines from before
the day's prices, used a different strategy, and ran on the 275-day sample.

## Step 3: entry and exit rules on top of sma_news (2026-10-30)
Every idea run through the real bot code (`py -m scripts.entry_exit_study data/stream_<t>.jsonl`), news veto
and 0.5 s wait included, judged by the Step 1 rule against `sma_news` (+34.4%, DD 10.0%, ret/DD 2.58 / 1.94).

| change | 500 days | max DD | ret/DD H1 / H2 | worst 100-day window | no PLNX | rule |
|---|---|---|---|---|---|---|
| buy only after 2 closes above the band | +26.1% | 6.9% | 2.80 / 1.39 | +0.4% | +18.2% | fail (H2) |
| sell at the SMA (not 1.5% below) | +32.5% | 8.0% | 3.28 / 1.32 | +2.8% | +25.5% | fail (H2) |
| sell 0.75% below the SMA | +32.6% | 9.7% | 2.74 / 0.92 | +1.6% | +23.9% | fail (H2) |
| trailing stop 6% | +35.1% | 9.6% | 2.71 / 2.01 | +2.7% | +26.5% | pass, **but** |
| trailing stop 4% / 5% / 7% / 8% / 10% | +32.0 / +34.1 / +32.4 / +34.7 / +34.1% | 9.6-10.1% | each worse in a half | | | fail |
| trailing stop 5-7% without instant re-buy | +33.9 / +33.2 / +32.2% | 9.7-10.0% | worse H1 | | | fail |
| buy only above SMA20 / SMA50 | +24.6% / +15.4% | 7.6% / 8.1% | worse H2 | -2.4% / -1.5% | lower | fail |
| buy only on volume >= 1x / 1.5x the 20-day average | +22.8% / +8.3% | 7.3% / 4.8% | worse H2 | -0.7% | lower | fail |
| buy only on an up day | +30.7% | 10.1% | 2.30 / 1.72 | -0.2% | +23.1% | fail |
| no new buys 3 / 5 days after a losing exit | +29.9% / +27.4% | 10.5% | worse | | lower | fail |
| second buy only if +2% in profit (= one buy per stock) | +26.1% | 8.1% | 2.50 / 1.34 | +1.5% | +18.2% | fail |

**Decision: no change.** The only pass, a 6% trailing stop (+0.7 pp), fails at 5% and 7% and with the
re-buy fixed, so it is luck at one setting, not an edge. Filters that wait for more confirmation (2 closes,
trend, volume, up day) cut drawdown but cut return more and weaken the second half. `sma_news` stays live.

## Step 4: risk management on top of sma_news (2026-10-30)
Profile of `sma_news` over 500 days (real bot code): charges Rs 13,397 = 3.9% of profit; invested share of
wealth median 43%, 90th percentile 75%, max 97%; open positions median 5, max 10.

New rules tested (`py -m scripts.risk_study data/stream_<t>.jsonl`), same rule as Steps 2-3:

| rule (on top of sma_news) | 500 days | max DD | ret/DD H1 / H2 | worst 100-day window | no PLNX | verdict |
|---|---|---|---|---|---|---|
| none (`sma_news`, live) | +34.4% | 10.0% | 2.58 / 1.94 | +1.7% | +25.3% | — |
| stop-loss 5% below entry | +34.6% | 10.0% | 2.59 / 2.00 | +1.7% | +25.5% | triggers once; no effect |
| stop-loss 8% / 12% below entry | identical | | | | | never triggers: the SMA exit always fires first |
| max exposure 60% / 75% / 90% of wealth | +31.7 / +35.1 / +34.1% | 9.6-10.0% | H2 0.19 / 1.00 / 1.89 | -1.4% / +1.5% / +1.2% | lower | fail |
| max 6 / 8 open positions | +28.9 / +35.6% | 10.3 / 9.9% | 2.38 / 1.28, 2.68 / 2.09 | +1.8% / +1.6% | +18.5 / +24.9% | fail |
| max 2 / 3 new buys per day | +30.4 / +31.5% | 9.8-10.0% | worse H1 | +1.8% / +1.7% | lower | fail |
| drawdown brake 6% / 8% | +3.7% / identical | 8.7% | 0.42 / 1.94 | | | 6% locks the bot out; 8% never triggers |

Live audit, 15 sessions on 2026-10-30 (1,153 orders): all filled, 0 exchange rejections, 0 duplicate
orders (same stock, side and day), 9 unaffordable buys stopped by our own cash check before reaching the
exchange, 6 blocked while the simulation was not running, 1 on stale data. Decision-to-answer latency:
median 0.12 s, 95th percentile 0.95 s; 4 orders over 3 s, all in early sessions while the exchange answered
slowly (the risk gate never sends on prices older than 3 s).

**Decision: no new risk rule.** The existing controls (per-stock cap, cash check, duplicate and in-flight
guards, uncertain-order freeze, fresh-data and stage checks, rate limit) do the work; the added limits either
never trigger or cost return in one half.
