# Qubix — MANTHAN 2026 Autonomous Trading Bot

A disciplined, explainable, tax-aware trading bot for the MANTHAN 2026 simulated exchange
(Kafka market stream + REST order gateway), with a live dashboard.

**Evidence, not hope.** Every design choice was tested on a full 500-day recording of the
competition stream (10 stocks, 8,125 news headlines), replayed with the same code that trades live:

| Chosen strategy `sma_pro` (500 days) | Result |
|---|---|
| Return / after tax | **+28.8% / +25.4%** |
| Max drawdown | **10.5%** |
| Captures of rising quarters / falling quarters | **49% / 17%** (Q3 crash: market −13.1%, bot −2.2%) |
| Orders rejected in replay | **0** (risk gate catches cash/cap problems first) |

We also report what failed (6 rejected ideas) — see [docs/STRATEGY_EVAL.md](docs/STRATEGY_EVAL.md).

## Quick start

```bash
py -m pip install -r requirements.txt
py -m src.app --live --dashboard         # dashboard at http://127.0.0.1:8080/  (bot boots STOPPED: press Start)
py -m pytest                             # 160+ unit tests, no network needed
```

`.env` (gitignored) needs `GATEWAY`, `BROKER`, `HACKATHON_USERNAME`, `BOT_ACCESS_TOKEN`.
Optional: `STRATEGY` (default `sma_pro`), `START_TRADING=1`, `DASHBOARD_PORT`, `WARM_START=0`.

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
| Latency 3–4 s window | Decision path is pure Python in-process (sub-millisecond in replay); latency avg/p95/max shown and logged |

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

```text
Kafka ──> Bot.handle_message ──> strategy (sma_pro) ──> risk gate ──> execution client ──> REST gateway
  │             │                     │                     │                │
  │             ├── heartbeat ACK     └── tax-loss harvest  └── journal      └── reconcile (FILLED/REJECTED/UNCERTAIN)
  │             └── news context (explanations only)                              │
  └── reconnect loop                                       tax book (FIFO) <───────┘
Dashboard (127.0.0.1): status, positions, orders, journal, tax, evidence, Start/Stop, strategy
```

## Strategies (`STRATEGY=`)

| id | status | summary |
|---|---|---|
| `sma_pro` | **default, chosen** | SMA8 ±1.5% band, ₹75k per trade, ₹1.5L per-ticker cap, year-end tax-loss harvesting |
| `sma_band` | baseline | the original bot's rule exactly (₹50k per trade, ₹1L cap) |
| `ensemble`, `mean_reversion`, `trend_pullback`, `laggard_reversion` | too weak | +0–1% over 500 days |
| `breakout`, `relative_strength`, `adaptive` | rejected | lost money or near zero; trends reverse in this data |

## Tools

```bash
py -m scripts.record_stream                                   # record the live stream (read-only, no consumer group)
py -m scripts.build_evidence data/stream_<t>.jsonl            # rebuild docs/evidence.json (dashboard "Evidence" panel)
py -m scripts.evaluate_strategies history.json                # quick windowed comparison
py -m scripts.demo_dashboard data/stream_<t>.jsonl --strategy sma_pro --speed 40 --start   # offline demo / fallback
```

## Documentation

- [docs/JURY_DEFENSE.md](docs/JURY_DEFENSE.md) — the five evaluation pillars, our numbers, likely questions
- [docs/STRATEGY_EVAL.md](docs/STRATEGY_EVAL.md) — full research log, including failures
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, data flow, safety design
- [docs/demo_runbook.md](docs/demo_runbook.md) — live-run checklist and demo script
- [docs/API_VERIFIED.md](docs/API_VERIFIED.md) — API facts, verified vs assumed
- [CONTRACTS.md](CONTRACTS.md) — shared interfaces between team modules
