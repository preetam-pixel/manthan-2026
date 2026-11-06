# Qubix — MANTHAN 2026 Autonomous Trading Bot

**Team Qubix finished in the top 20 of 80 teams at MANTHAN 2026.**

A disciplined, explainable, tax-aware trading bot for the MANTHAN 2026 simulated exchange
(Kafka market stream + REST order gateway), with a live dashboard.

**Evidence, not hope.** Every design choice was tested on a full 500-day recording of the
competition stream (10 stocks, 8,126 news headlines), replayed with the same code that trades live:

| Chosen strategy `sma_news` (500 days, real bot code) | Result |
|---|---|
| Return | **+34.4%** (vs +28.8% for the same rule without news) |
| Max drawdown | **10.0%** |
| News | a BUY waits 0.5 s for the day's headlines; skipped if the last 3 days score ≤ −2 (beats 40/40 placebo runs) |
| Captures of rising quarters / falling quarters | **54% / −23%** (negative: the bot gained while the market fell; Q3 crash: market −13.1%, bot +3.1%) |
| Orders rejected in replay | **0** (risk gate catches cash/cap problems first) |
| Buying all 10 stocks and holding, same days | +44.9%, with a 22% fall from its peak (weekly values) |

These results are in-sample: the rule was tuned on these same 500 days, and the exchange's sandbox replays them in a loop.

On that practice sandbox the account grew from ₹10 lakh to ₹23.3 lakh after charges (+133%), with 2,059 orders and
1 order error (portal, 30 Oct 2026). That total covers several passes over the same period, so it is not a single-run return.

We also report what failed (8 rejected ideas) — see [docs/STRATEGY_EVAL.md](docs/STRATEGY_EVAL.md).

## Quick start

```bash
py -m pip install -r requirements.txt
py -m src.app --live --dashboard         # dashboard at http://127.0.0.1:8080/  (bot boots STOPPED: press Start)
py -m pytest                             # 189 unit tests, no network needed
```

The dashboard has eight pages (Overview, Market, Portfolio, Activity, Journal, Tax & Costs, Evidence,
Strategy & Controls): use the side menu or press keys 1–8. Each page has its own link, e.g. `#portfolio`.
The Journal page explains every trade step by step (signal, size, news check, risk gate, exchange answer, result),
including buys the news check skipped. If the exchange account is reset under the bot, the log and the dashboard warn about it.

`.env` (gitignored) needs `GATEWAY`, `BROKER`, `HACKATHON_USERNAME`, `BOT_ACCESS_TOKEN`.
Optional: `STRATEGY` (default `sma_news`), `START_TRADING=1`, `DASHBOARD_PORT`, `WARM_START=0`.

**Position size** (rupees, optional): `TRADE_SIZE_INR` per buy and `MAX_POSITION_INR` per stock. Setting both
equal means one buy per stock (no second buy). 500-day replay of the default `sma_news`, real bot code:

| TRADE_SIZE_INR / MAX_POSITION_INR | return | max drawdown | worst trade |
|---|---|---|---|
| 75000 / 150000 (default) | +34.4% | 10.0% | −₹15,450 |
| 75000 / 75000 (one buy per stock) | +26.1% | 8.1% | −₹8,417 |
| 50000 / 100000 (original bot's size) | +21.5% | 7.0% | −₹10,323 |
| 25000 / 50000 | +13.1% | 3.8% | −₹5,195 |

Smaller size shrinks gains and losses together; return per unit of drawdown is similar (3.1–3.4) at every size.

## What it does (mapped to the problem statement)

| Requirement | Implementation |
|---|---|
| Kafka `market.ticks` + `market.news`, group `group-<username>`, latest, no auto-commit | `src/app.py` `run()` / `consume_forever()` — **auto-reconnect with backoff**; state survives network drops |
| Pre-flight heartbeat ACK of exact `seq` within 15 s | Throttled ACK (≤1 per 2 s, retries after 1 s); bypasses the request budget so it is never starved |
| Dynamic universe `/stocks`, history warm-start | Startup: portfolio sync, universe, history warm-start (works with or without pre-flight ticks) |
| Stage `/stage`: trade only when running | Orders only in `simulation`/`development` with status running; never in pre-flight, paused, completed |
| Orders `BUY/SELL`, whole quantity 1..1,000,000, optional `date` | `src/execution/client.py` — the only module that talks to the gateway; sends `date` for latency scoring |
| Rate limit 120/min, 429 penalty box | Self-limits to 100/min; 30 s penalty respected; heartbeats exempt from the local budget |
| Confirmations / rejections / uncertain outcomes | Timeouts are **UNCERTAIN**, never assumed rejected; reconciled from the exchange portfolio before that ticker trades again |
| Risk & portfolio | `src/risk/manager.py`: running stage, long-only, valid qty/price, tradable ticker, fresh data, synced portfolio, no duplicate/in-flight, sell ≤ holdings, per-ticker cap, cash check |
| Brokerage ₹20, DP ₹15.34, STCG 15% / LTCG 10% (₹1L exempt), Sections 70/71 | `src/tax/engine.py` FIFO tax book; **year-end tax-loss harvesting** overlay; live tax panel |
| Explain every trade | `src/journal.py` decision journal (JSONL + CSV): reason, news context, risk verdict, exchange answer, latency, tax term |
| Latency 3–4 s window | Sells go out at once; a BUY waits 0.5 s for the day's headlines (0.55 s at most in replay); latency avg/p95/max shown and logged |

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
Kafka ──> Bot.handle_message ──> strategy (sma_news) ──> risk gate ──> execution client ──> REST gateway
  │             │                     │                     │                │
  │             ├── heartbeat ACK     └── tax-loss harvest  └── journal      └── reconcile (FILLED/REJECTED/UNCERTAIN)
  │             └── news: veto on breakout BUYs + explanations                     │
  └── reconnect loop                                       tax book (FIFO) <───────┘
Dashboard (127.0.0.1): status, positions, orders, journal, tax, evidence, Start/Stop, strategy
```

## Strategies (`STRATEGY=`)

| id | status | summary |
|---|---|---|
| `sma_news` | **default, chosen** | `sma_pro` + news veto: a BUY waits 0.5 s for the day's headlines and is skipped if the last 3 days score ≤ −2. 500 days: +34.4% vs +28.8% |
| `sma_pro` | previous default | SMA8 ±1.5% band, ₹75k per trade, ₹1.5L per-ticker cap, year-end tax-loss harvesting (no news) |
| `sma_band` | baseline | the original bot's rule exactly (₹50k per trade, ₹1L cap) |
| `ensemble`, `mean_reversion`, `trend_pullback`, `laggard_reversion` | too weak | +0–1% over 500 days |
| `breakout`, `relative_strength`, `adaptive` | rejected | lost money or near zero; trends reverse in this data |

## Tools

```bash
py -m scripts.record_stream                                   # record the live stream (read-only, no consumer group)
py -m scripts.build_evidence data/stream_<t>.jsonl            # rebuild docs/evidence.json (dashboard "Evidence" panel)
py -m scripts.evaluate_strategies history.json                # quick windowed comparison
py -m scripts.replay_bot data/stream_<t>.jsonl                # replay a recording through the real bot
py -m scripts.compare_bots data/stream_<t>.jsonl              # old vs new bot, real bot code, identical conditions
py -m scripts.entry_exit_study data/stream_<t>.jsonl          # Step 3 study: entry/exit variants on top of sma_news
py -m scripts.risk_study data/stream_<t>.jsonl                # Step 4 study: extra risk rules on top of sma_news
py -m scripts.demo_dashboard data/stream_<t>.jsonl --strategy sma_news --speed 40 --start   # offline demo / fallback
```

`data/` is gitignored, so record a stream first or get a recording from a teammate.

## Documentation

- [docs/Qubix_Beginners_Guide.pdf](docs/Qubix_Beginners_Guide.pdf) — the whole project explained for beginners; start here
- [docs/JURY_DEFENSE.md](docs/JURY_DEFENSE.md) — the five evaluation pillars, our numbers, likely questions
- [docs/BASELINE.md](docs/BASELINE.md) — the baseline recorded before the improvement roadmap
- [docs/STEP5_COMPARISON.md](docs/STEP5_COMPARISON.md) — original vs baseline vs improved bot under identical conditions
- [docs/STRATEGY_EVAL.md](docs/STRATEGY_EVAL.md) — full research log, including failures
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data flow, safety design
- [docs/demo_runbook.md](docs/demo_runbook.md) — live-run checklist and demo script
- [docs/TESTING.md](docs/TESTING.md) — testing checklist
- [docs/API_VERIFIED.md](docs/API_VERIFIED.md) — API facts, verified vs assumed
- [CONTRACTS.md](CONTRACTS.md) — shared interfaces between team modules
