# Frontend requirements — MANTHAN 2026 trading bot dashboard

Owner: Member 1. Folder: `frontend/`.

## 0. Status of the backend (read first)
- **The bot has no HTTP server yet.** It only prints log lines. Everything below the "Data contract" is a *proposed* interface; build against the fixtures in section 6 first, then we add a matching `GET /status` etc. to the bot.
- The UI is **read-only for trading**: it must never submit orders, never hold or display the API token, and never call the exchange gateway (port 3002) directly.
- The only write actions are the bot **Start/Stop** switch and the **strategy selector** (section 3.8). Both go to the bot's local control endpoint, not the exchange.

## 1. Goals
1. Let a teammate, on stage, see in seconds: is the bot healthy, is it trading, what did it just do and why.
2. Give the jury evidence for the pillars: reliability, strategy depth, latency, costs/taxes, explainability.
3. Never mislead: simulated results are labeled as simulation; no profit claims without data.

## 2. Tech constraints
- Runs on a laptop with no internet needed at demo time (vendor any chart library locally).
- Plain HTML/CSS/JS or Vite + React/Vue are both fine. No build step is preferred for the demo fallback.
- Dark theme, desktop-first (1366x768 minimum), usable at 1920x1080 on a projector. Large fonts: readable from 3 m.
- Polls every 2 s (configurable). No WebSocket needed.
- Must keep working if any field is missing (show "—", never crash).

## 3. Screens / components

### 3.1 Header status bar (always visible)
| Item | Source | Notes |
|---|---|---|
| Bot state | `bot.state` | RUNNING / STOPPED (trading paused) / OFFLINE (no data for >6 s) |
| Kafka | `bot.kafka_connected` | green/red dot |
| Last heartbeat ACK | `bot.last_heartbeat_seq`, `bot.last_heartbeat_at` | red if >15 s old during preflight |
| Simulation | `sim.stage`, `sim.status` | e.g. `simulation / running` |
| Day progress | `sim.days_completed` / `sim.total_days`, `sim.current_date` | progress bar |
| Mode badge | `sim.is_sandbox` | "SANDBOX" vs "LIVE RUN" — must be unmistakable |

### 3.2 KPI cards
Total wealth, cash, invested value, net P&L (absolute and %), orders sent, orders rejected, rejection rate, average decision latency. Show change since the run started. Colour P&L green/red, never rely on colour alone (add +/- sign).

### 3.3 Positions table
Columns: ticker, quantity, last close, market value, avg buy price, unrealized P&L, % of ₹1,00,000 per-ticker cap (bar), held-since date, holding class (short-term/long-term). Sortable by every column. Empty state: "No open positions".

### 3.4 Live activity feed (newest first, max ~200 rows, pause-on-hover)
Row types with distinct icon/colour: `TICK`, `SIGNAL`, `ORDER`, `RISK_BLOCK`, `NEWS`, `ERROR`, `SYSTEM`. Each row: time, simulated date, ticker, one-line message, and a **reason** (e.g. "close above SMA8 by 1.5%", "blocked: stale data"). Filter chips by type and ticker. Click a row to expand the raw JSON.

### 3.5 Charts
1. **Price + indicators per ticker** (ticker dropdown): close line, SMA8, ±1.5% band shading, BUY/SELL markers with tooltip (qty, price, reason). Optional candlesticks + volume bars.
2. **Equity curve**: total wealth over simulated days.
3. **Exposure**: stacked bar of cash vs each ticker's value; line at the ₹1,00,000 cap.
4. **Decision latency**: scatter/line per order with the 3–4 s window shaded; show avg, p95, max.
5. **Distance-from-trigger heat strip**: one cell per ticker showing (close/SMA8 − 1) with ±1.5% marked — tells the audience how close each stock is to a trade.
6. **Risk blocks**: bar chart counting blocks by reason.

### 3.6 Orders table
Time, ticker, action, quantity, fill price, status (FILLED / REJECTED / UNCERTAIN), reject code, brokerage + DP charge, latency. Totals row: fees paid. Rejected rows highlighted.

### 3.7 News panel
Latest headlines per ticker with simulated date; display the keyword score (+n/−n) as informational only, labeled "not used for trading" unless that changes.

### 3.8 Controls (the only write actions)
- **Start / Stop trading**: Stop pauses new orders only; Kafka connection and heartbeats keep running (never kill the process — preflight Ready status would be lost). Bot **boots in STOPPED**. Start asks for confirmation. Stop is one click. Both show the resulting state returned by the bot, not an optimistic guess.
- **Strategy selector** (dropdown): options come from `GET /strategies`. Default `sma_band` (baseline). Selecting is only allowed while STOPPED; show a banner "Strategy changed — open positions keep their exits under the new strategy". Show a short description and the parameters of the selected strategy (read-only).
- Disable both controls and show a reason when the bot is OFFLINE.

### 3.9 Tax & costs panel
Fees paid, estimated STCG/LTCG liability if the API/bot provides it, tax-loss credits. If data is absent, show "not available" rather than zeros.

### 3.10 States
Loading skeletons, "Bot offline / last seen N s ago" banner, per-widget error states, and a clear "Using fixture data" banner when running on mocks.

## 4. Data contract (proposed; bot to implement)
All JSON, times ISO-8601 UTC, `simulated_date` as `YYYY-MM-DD`, money as numbers in INR.

`GET /status`
```json
{
  "bot": {"state": "STOPPED", "kafka_connected": true, "last_heartbeat_seq": 14,
          "last_heartbeat_at": "2026-10-29T13:08:55Z", "strategy": "sma_band", "uptime_s": 812},
  "sim": {"stage": "development", "status": "running", "is_sandbox": true,
          "current_date": "2024-12-06", "days_completed": 30, "total_days": 500,
          "interval_seconds": 10},
  "account": {"cash": 912340.5, "invested": 87659.5, "total_wealth": 1000000.0,
              "net_pnl": 0.0, "fees_paid": 40.0},
  "stats": {"orders_sent": 4, "orders_rejected": 1, "latency_avg_s": 0.42,
            "latency_p95_s": 0.9, "latency_max_s": 1.3}
}
```
`GET /positions` → `[{"ticker":"HAVN","quantity":300,"last_close":136.92,"avg_price":131.1,"value":41076,"unrealized_pnl":1746,"cap_used_pct":41.1,"held_since":"2024-11-20"}]`

`GET /events?since=<id>` → `[{"id":1021,"time":"...","simulated_date":"2024-12-06","type":"ORDER","ticker":"HAVN","message":"BUY 300 FILLED","reason":"close above SMA8 by 1.5%","data":{...}}]`

`GET /series/<ticker>` → `{"ticker":"HAVN","points":[{"date":"2024-12-05","open":..,"high":..,"low":..,"close":..,"volume":..,"sma8":..,"upper":..,"lower":..}],"markers":[{"date":"...","action":"BUY","qty":300,"price":136.92,"reason":"..."}]}`

`GET /equity` → `[{"date":"2024-12-05","total_wealth":1000000.0,"cash":..,"invested":..}]`

`GET /orders` → list with `time, ticker, action, quantity, price, status, code, fees, latency_s`.

`GET /strategies` → `[{"id":"sma_band","name":"SMA8 ±1.5%","description":"...","params":{"window":8,"band":0.015},"default":true}]`

`POST /control/start`, `POST /control/stop`, `POST /control/strategy` with `{"id":"sma_band"}` → each returns the new `bot` object, or `{"error":"..."}` with a non-2xx status.

CORS: the bot serves `Access-Control-Allow-Origin` for the dashboard origin; listens on `127.0.0.1` only.

## 5. Non-functional
- First paint < 1 s on fixtures; polling must not freeze the UI with 200+ feed rows.
- Accessible contrast (WCAG AA), keyboard-focusable buttons, tabular numbers (monospace digits) for money.
- Number formats: Indian grouping (₹10,00,000.00). Percent to 2 dp.
- No secrets in the repo, console, URL query strings, or localStorage.

## 6. Fixtures (build first)
Create `frontend/fixtures/*.json` mirroring each endpoint above; ship a tiny `mock` toggle (`?mock=1`) that serves them. Include edge cases: empty positions, a REJECTED order, an UNCERTAIN order, bot OFFLINE, a missing field, 500 events, and a stage of `paused`/`completed`.

## 7. Acceptance checklist
- [ ] Runs from fixtures with no backend; `?mock=1` banner visible.
- [ ] Every number on screen traces to one endpoint field.
- [ ] No code path can submit an order or reach port 3002.
- [ ] Stop never disconnects Kafka or stops heartbeats (verified with the bot).
- [ ] OFFLINE, paused, completed and error states look different and clear.
- [ ] Sandbox vs live-run badge is obvious from the back of the room.
- [ ] Results are labeled simulated; no profitability claims.
- [ ] Works on the demo laptop without internet.

## 8. Known open points
- Backend `/status` etc. and the control endpoints are **not implemented yet** — they need a small change in `src/app.py` (Member 3 reviews).
- Alternative strategies in the selector do not exist yet; only `sma_band` is real. Show other entries as "coming soon" until they are built.
- Portfolio/tax field names from the exchange are unverified, so tax panel values may be absent.
