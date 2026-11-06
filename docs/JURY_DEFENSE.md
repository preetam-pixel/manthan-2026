# Jury defence — Qubix

One line: **we built a bot that knows what it does not know.** Every rule is backed by a replay of
the full 500-day competition stream; every trade is explained in a journal; every rupee of fees and
tax is accounted for.

## Pillar 1 — Technical implementation & reliability

- Single path to the exchange (`execution/client.py`), guarded by one risk gate (`risk/manager.py`).
- Order outcomes are three-valued: `FILLED`, `REJECTED`, `UNCERTAIN`. A timeout is never assumed to be a rejection; the ticker is frozen until the exchange portfolio is re-read, so we never double-buy.
- Kafka `consume_forever`: reconnects with 1→2→4→8→15 s backoff; positions, tax lots and the journal survive. Tested with a broker that fails mid-stream.
- Exchange is the source of truth: portfolio re-synced every 15 s, 2 s after each fill and after any uncertain/cash rejection; the dashboard shows the exchange's own figures, so it matches the portal.
- Heartbeat: throttled to one ACK per 2 s (pre-flight bursts reached ~20 messages/s), exempt from our local rate budget, retried after 1 s. Verified live in the organisers' pre-flight test.
- Client-side validation mirrors every documented rejection code (quantity 1..1,000,000, tradable ticker, cash, running stage), so the exchange should never have to reject us.
- 160+ unit tests, all offline (fake API, fake Kafka, real HTTP server for the dashboard). Bugs found by testing against real data and fixed: sandbox orders blocked by a stage check, dashboard freeze when P&L is exactly 0, console crash on a zero-width space in a headline, news flooding the event feed.

## Pillar 2 — Strategy innovation & analytical depth

We recorded the whole stream (500 days × 10 stocks, 8,125 headlines) and replayed it through the real code.

| What we tested | Finding | Decision |
|---|---|---|
| Momentum (breakout, relative strength, adaptive bands) | 20-day trends reverse; all near zero or negative | Rejected |
| Dip/laggard ensemble | Best on the first 275 days, −0.04% on the 208 days it never saw | Rejected (overfit) |
| Market-regime allocator | +0.4% with 10.8% drawdown at every setting | Rejected |
| News sentiment alone (8,124 headlines) | Correlation with 1-10 day returns −0.01 to −0.03 | Not a trade trigger |
| News veto on breakout buys (same-day headlines) | +34.4% vs +28.8%, better in both halves, beats 40/40 placebo runs | **Live (`sma_news`)** |
| Account drawdown brake | Locks the bot out of recoveries (+2.5% vs +28.8%) | Rejected |
| SMA band family (windows 5–12, bands 1–2.5%) | Positive in every cell; 20-day fails | **Core rule** |

The chosen core is the short-term SMA band. Its behaviour is asymmetric: per quarter, `sma_pro` made
+7.6%, +12.0%, **−2.2%**, +7.5% while the market made +15.6%, +30.2%, **−13.1%**, +9.5% — it keeps
roughly half of rallies and a sixth of sell-offs. We deliberately did not tune the window/band to the
single best cell; the whole neighbourhood works, which is what makes it credible on unseen data.

## Pillar 3 — Execution speed & capital efficiency

- The decision path is in-process Python: sub-millisecond per tick in replay; the measured value is shown live (avg / p95 / max) and printed on shutdown. Orders carry the simulated `date` so the platform can score reaction speed.
- `sma_pro` deploys 1.5× the original size (₹75k per trade, ₹1.5L per-stock cap): average utilisation ~45% vs ~33%, return +28.8% vs +17.9%, drawdown 10.5% vs 7.1%. We chose moderate, not maximal, deployment: 2× gave +31.7% but 12.5% drawdown.
- The risk gate checks cash before sending, so capital shortfalls show up as logged blocks, not exchange rejections (0 rejected orders in the 500-day replay).

## Pillar 4 — Market frictions & tax optimisation

- Every backtest charges ₹20 brokerage per order and ₹15.34 DP per sell, and estimates Indian capital-gains tax with a FIFO tax book: STCG 15%, LTCG 10% after 365 days with ₹1,00,000 exempt per financial year, set-off per Sections 70/71 (short-term losses against STCG then LTCG; long-term losses only against LTCG).
- Live, the same tax book follows real fills and shows tax per financial year in the dashboard.
- Year-end tax-loss harvesting: in the last 10 days before 31 March, if the year has taxable gains, positions with losses bigger than fees are sold when the tax saved beats the round-trip cost. Effect in replay: +0.6 pp return (small, because positions are short-lived; we say so).
- Turnover is a cost: we rejected variants whose extra trades did not pay for their fees.

## Pillar 5 — Coordination & explainability

- Decision journal: for every decision — trigger and numbers, recent news context, risk verdict, exchange answer, fill, latency, realised gain and tax term. Saved to `logs/decisions_*.jsonl`, downloadable as CSV from the dashboard.
- Dashboard "Evidence" panel shows the research above, including what we rejected.
- Module ownership (CONTRACTS.md): data & strategy, execution & risk, dashboard, QA & demo.

## Questions we expect

**Why not just buy and hold? It made +44.9%.** It also fell 13% in one quarter. The jury asked for
moderate, steady gains with downside protection; our bot lost 2.2% in that quarter. Buy-and-hold is a
bet on the market going up — on a confidential period we cannot know that.

**Isn't SMA8 too simple?** Simplicity is a feature when the data has little signal. We tested twelve
more complex ideas; none beat it out of sample. The innovation is in the evidence, sizing, tax and
risk engineering around it.

**How do you know you did not overfit?** The core rule existed before we saw the data (the original
bot). We validated a whole neighbourhood of parameters, not one cell, and we report the ensemble that
looked great in-sample and failed out-of-sample.

**What happens if the network drops?** Kafka reconnects with backoff, the portfolio is re-read from the
exchange, uncertain orders are reconciled before any retry, and the dashboard shows "Kafka disconnected".

**Why no shorting?** Downtrends in this data were followed by rebounds (+0.3% to +0.9% over 5–10 days),
short positions lock 100% margin and are force-closed every 10 trading days. No edge, more risk.

**Why did your team not appear on the test leaderboard?** We were running an earlier build. Its log shows
heartbeat bursts (~20 ACKs per second) exhausting our own request budget, which most likely starved the
stage checks and order requests too; it also blocked sandbox orders with a stage check. Both are fixed and
tested: heartbeats are throttled and exempt from the budget, and the sandbox stage is allowed.

## Honest limits

- Results are from the sandbox dataset; the live period is confidential and will differ.
- Tax is our estimate; the exchange's tax report is authoritative. Loss carry-forward across years is not modelled.
- Order and portfolio response fields are read defensively; the first live order should be checked against the portal.
