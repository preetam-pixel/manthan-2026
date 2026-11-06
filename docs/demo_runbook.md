# Live-run runbook and demo script

## Before the live simulation (T − 60 min)

1. Laptop on the **venue Wi-Fi** (not a hotspot), power connected, sleep disabled.
2. `git log --oneline -1` — confirm you are on the latest local commit.
3. `py -m pytest -q` — all tests pass.
4. Reachability:
   ```powershell
   Test-NetConnection 192.168.65.157 -Port 9094
   Test-NetConnection 192.168.65.157 -Port 3002
   ```
5. Token check (should print 200):
   ```powershell
   (Invoke-WebRequest -Uri "http://192.168.65.157:3002/api/v1/portfolio/cash" -Headers @{Authorization="Bearer $env:BOT_ACCESS_TOKEN"} -UseBasicParsing).StatusCode
   ```
   (Or rely on `.env`: the bot prints `Synced holdings` at startup if the token works.)
6. Stop any old bot process; only one `src.app` may run (Ctrl+C in its window).

## Start (T − 30 min, during pre-flight)

```bash
py -m src.app --live --dashboard
```

Healthy startup log: `Dashboard: http://127.0.0.1:8080/`, `Synced holdings`, `Universe: [...]`, `Strategy: sma_news`, `Connected to Kafka`.
During pre-flight: `heartbeat ack <seq>` every 2–3 s; the portal shows **Ready**.

Open http://127.0.0.1:8080/ and press **Start** (the bot boots stopped). Orders are sent only when the stage is
`simulation` and running, so pressing Start early is safe.

## During the run — what to watch

| Signal | Meaning | Action |
|---|---|---|
| `ORDER ... FILLED` | normal | none |
| `RISK BLOCK ... insufficient cash` | gate prevented a rejection | none |
| `ORDER ... REJECTED <code>` | exchange refused | read the code in the journal; tell the backend owner |
| `Kafka connection problem ... reconnecting` | network blip | wait; it reconnects by itself |
| `heartbeat error` repeated during pre-flight | token or network | check Wi-Fi / token |
| Dashboard "OFFLINE" | browser can't reach the bot | the bot keeps trading; refresh the page |

Never restart mid-run unless the process died. Do not press Stop unless something is clearly wrong; Stop pauses
new orders only (heartbeats and data continue).

## After the run

- Ctrl+C prints the decision-latency summary and the tax estimate.
- Keep `logs/decisions_*.jsonl` (and download the journal CSV) for the jury.

## Jury demo (5 minutes)

1. **Problem → approach (30 s):** "Disciplined, explainable, tax-aware. Evidence first."
2. **Dashboard header (30 s):** stage, heartbeat, Kafka, Start/Stop — explain Stop ≠ disconnect.
3. **Evidence panel (90 s):** equity vs buy-and-hold, quarter chart (Q3: market −13.1%, bot +3.1%), robustness grid, news study, rejected ideas.
4. **Decision journal (60 s):** pick one trade; read the reason, risk verdict, exchange answer, tax term. Download CSV.
5. **Tax panel (45 s):** FIFO, STCG/LTCG, set-off, harvesting window before 31 March.
6. **Reliability (45 s):** uncertain-order reconciliation, Kafka reconnect, local-only dashboard.

## Fallback (no network)

```bash
py -m scripts.demo_dashboard data/stream_20261029_215617.jsonl --strategy sma_news --speed 40 --start
```

Same bot code with a simulated exchange that fills at the close; clearly say it is a replay.

---

## MANTHAN 2026 — MarketPulse Demo Runbook (Member 4 QA)

> Written by Member 4 before PR 3 merged. The test counts and live-integration status below are as recorded then. The suite now has 189 tests, and the bot has since traded on the exchange sandbox (see the README).

### 1. Purpose

Demonstrate the simulated stock-trading system, its strategy decisions, risk controls, portfolio reconciliation, and QA evidence.

### 2. Current QA Status

- Unit tests collected: 116
- Unit tests passed: 116
- Test failures in the recorded run: 0
- Live simulator and Kafka integration: Not yet verified according to README.md.

Passing unit tests do not establish that the complete live system is operational.

### 3. Pre-Demo Checklist

- [ ] Run from the project root.
- [ ] Confirm dependencies are installed using `python -m pip install -r requirements.txt`.
- [ ] Run `python -m pytest -q`.
- [ ] Confirm the expected test results.
- [ ] Review `CONTRACTS.md` and `docs/API_VERIFIED.md`.
- [ ] Confirm the simulator environment and permitted operating mode with the backend owner.
- [ ] Never expose authentication tokens or other secrets.
- [ ] Keep a fallback using test output and prepared screenshots.

### 4. Demo Flow

1. Introduce MarketPulse and explain that it is a simulated trading system.
2. Explain the market-data input and supported ticker universe.
3. Explain the SMA8 strategy and its documented entry/exit thresholds.
4. Show how a signal passes through the risk manager.
5. Explain how an approved order is submitted through the execution adapter.
6. Show portfolio reconciliation and resulting holdings/cash when verified evidence is available.
7. Explain that news is informational and is not itself a trade trigger.
8. Present QA results and discuss limitations.

Only demonstrate live order submission after the environment and integration have been explicitly verified.

### 5. Important QA Scenarios

- Normal market snapshot and valid signal.
- Stale or missing market data.
- Duplicate tick or signal.
- Insufficient cash or position limit.
- API timeout, malformed response, or uncertain order status.
- Paused or completed simulation.
- News timestamp after the trading decision.
- Portfolio reconciliation and rejected orders.

For each scenario, record the test name, expected behavior, actual result, and pass/fail status.

### 6. Fallback Plan

If the live simulator, Kafka, or API is unavailable:

1. Do not repeatedly retry uncertain orders.
2. Use recorded pytest output as evidence of unit-test results.
3. Use prepared screenshots or mock fixtures to explain the expected workflow.
4. Clearly label mocked behavior and previously recorded results.
5. Do not present simulated screenshots as proof of live integration.

### 7. Limitations

- Unit tests use fakes; live integration is not yet confirmed.
- Historical backtest results do not guarantee future performance.
- Strategy evaluation and market-data limitations should be explained using `docs/STRATEGY_EVAL.md`.
- Any remaining integration failures must be disclosed.

### 8. Final Sign-Off

- [ ] QA results recorded.
- [ ] Demo steps rehearsed.
- [ ] Fallback evidence prepared.
- [ ] Live integration status accurately disclosed.
- [ ] Final presentation reviewed by the team.
