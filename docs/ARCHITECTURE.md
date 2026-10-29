# Architecture

## Data flow

```text
                         ┌──────────────────────── src/app.py : Bot ─────────────────────────┐
Kafka market.ticks ──┐   │                                                                    │
Kafka market.news ───┴─► │ handle_message ─┬─ preflight_tick ─► heartbeat ACK (throttled)     │
 (consume_forever:       │                 ├─ price_tick ─► strategy.on_close / on_bar        │
  reconnect + backoff)   │                 │                 └─► tax-loss harvest overlay     │
                         │                 │                 └─► end-of-run unwind            │
                         │                 │            Signal ─► RiskManager.evaluate        │
                         │                 │                        │ approved                │
                         │                 │                        ▼                         │
                         │                 │         SimulationAPIClient.submit_order ───────────► REST /api/v1/orders
                         │                 │                        │ FILLED / REJECTED / UNCERTAIN
                         │                 │                        ▼                         │
                         │                 │      PortfolioState + TaxBook (FIFO) + Journal   │
                         │                 └─ news_flash ─► news context (explanations only)  │
                         │  every 60 s: portfolio resync from the exchange (source of truth)  │
                         └────────────────────────────────────────────────────────────────────┘
                                         │ read-only views (thread-safe)
                                         ▼
                 src/dashboard/server.py (127.0.0.1) ─► frontend/ (index.html, app.js, insights.js)
```

## Modules

| Module | Responsibility |
|---|---|
| `src/app.py` | Lifecycle: startup sync, universe, warm start, message routing, heartbeat, stage gating, execution, reconciliation, Kafka reconnect |
| `src/market_data/consumer.py` | Event parsing (ticks, preflight seq, history bars) — no I/O |
| `src/market_data/recorder.py` | Record the stream to JSONL and load it back (loop-aware) |
| `src/news/consumer.py`, `src/news/filter.py` | Keyword scores and a negation-aware news risk score (context only) |
| `src/strategy/` | `sma.py` (`sma_band`, `sma_pro`), research strategies, `backtest.py` (fees + tax), `registry.py` |
| `src/risk/manager.py` | Single gate every order passes through |
| `src/execution/client.py` | The only code that calls the gateway: pacing, 429 penalty, outcome classification |
| `src/portfolio/state.py` | Holdings/cash from the exchange, in-flight and uncertain tracking |
| `src/tax/engine.py` | FIFO lots, STCG/LTCG, set-off, ₹1L exemption, harvesting candidates |
| `src/journal.py` | Decision journal (JSONL file + memory + CSV) |
| `src/dashboard/` | Thread-safe state, local HTTP server, offline demo exchange |
| `scripts/` | Stream recorder, evidence builder, evaluation, offline demo |

## Safety design

- **One door to the exchange.** Only `execution/client.py` sends orders; only after `RiskManager.evaluate` approves.
- **Unknown is not "no".** A timeout or unreadable reply is `UNCERTAIN`; the ticker is frozen until the exchange portfolio is re-read.
- **Exchange is the source of truth.** Portfolio re-synced at startup, every 60 s, after uncertain outcomes and after cash/margin rejections.
- **Stop is not disconnect.** The dashboard Stop switch pauses new orders only; Kafka and heartbeats continue (pre-flight readiness is never lost).
- **The dashboard cannot break trading.** All dashboard hooks are wrapped; tested with a dashboard that throws on every call.
- **Local only.** The dashboard binds to 127.0.0.1, refuses foreign `Host` headers (DNS rebinding) and cross-origin POSTs, never sees the token.
- **Logging never throws.** Headlines with characters a Windows console cannot encode are logged with replacements instead of aborting the event.

## Threads

The bot runs on the main thread (single writer). The dashboard server runs in a daemon thread and only reads copies under locks. Strategy switches requested from the dashboard are queued and applied by the bot thread between messages.
