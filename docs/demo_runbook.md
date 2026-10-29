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

Healthy startup log: `Dashboard: http://127.0.0.1:8080/`, `Synced holdings`, `Universe: [...]`, `Strategy: sma_pro`, `Connected to Kafka`.
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
3. **Evidence panel (90 s):** equity vs buy-and-hold, quarter chart (Q3: market −13.1%, bot −2.2%), robustness grid, news study, rejected ideas.
4. **Decision journal (60 s):** pick one trade; read the reason, risk verdict, exchange answer, tax term. Download CSV.
5. **Tax panel (45 s):** FIFO, STCG/LTCG, set-off, harvesting window before 31 March.
6. **Reliability (45 s):** uncertain-order reconciliation, Kafka reconnect, local-only dashboard.

## Fallback (no network)

```bash
py -m scripts.demo_dashboard data/stream_20261029_215617.jsonl --strategy sma_pro --speed 40 --start
```

Same bot code with a simulated exchange that fills at the close; clearly say it is a replay.
