# Four-member implementation plan — aligned to uploaded bot

## Member 1 — Frontend / dashboard
Owns `frontend/`. Build a read-only view of bot/simulation status, cash/portfolio, positions, latest signals/orders, and logs. Start with fixtures. UI must not submit orders.

## Member 2 — Data & strategy
Owns `src/market_data/`, `src/news/`, `src/features/`, `src/strategy/`.
- Preserve Kafka topic/event handling as documented.
- Port the SMA8 ±1.5% strategy.
- Keep news keyword counts informational only unless approved.
- Add deterministic tests; append current close after signal calculation, matching the original.

## Member 3 — Backend / execution integration
Owns `src/app.py`, `src/execution/`, `src/risk/`, `src/portfolio/`.
- Implement env config, Kafka lifecycle, portfolio startup sync, universe discovery, preflight heartbeat.
- Isolate HTTP order calls in execution adapter.
- Guard tradable ticker, positive integer quantity, position cap, no accidental short, simulator status.
- Reconcile uncertain order outcomes before retrying.

## Member 4 — QA, demo & presentation
Owns `tests/` and `docs/demo_runbook.md`.
- Test SMA warm-up, entry/exit thresholds, position cap, no accidental short.
- Test heartbeat, API errors, portfolio sync, stale ticks, duplicate/in-flight orders.
- Prepare demo and fallback, distinguishing measured results from planned work.

## Phases
1. Agree on contracts and inspect original bot.
2. Port strategy + tests; build backend adapter/lifecycle stubs.
3. Frontend uses fixtures; QA prepares scenarios.
4. Integrate through shared signal/order intent.
5. Test, harden, freeze interfaces, rehearse.
