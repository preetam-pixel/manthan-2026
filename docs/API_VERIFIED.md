# API and event facts from supplied HANDOFF.md

Transcribed from user-provided handoff; not independently tested here.

- Gateway: `http://192.168.65.157:3002`
- Broker: `192.168.65.157:9094`
- Topics: `market.ticks`, `market.news`
- `GET /api/v1/stocks`: universe (ticker, name, description)
- `POST /api/v1/bot/heartbeat`: `{"seq": n}`
- `POST /api/v1/orders`: `{ticker, action, quantity}`; BUY/SELL/SHORT/COVER
- `GET /api/v1/portfolio`: cash, holdings, PnL, charges/taxes, simulated_date
- `GET /api/v1/orders`: order history
- Tick: `{event_type, timestamp, simulated_date, data:{ticker, open, high, low, close, volume}, sig}`
- News: `{data:{ticker, headline, description, date}}`; handoff says no sentiment field
- Preflight: `{seq, data:{status:"STANDBY", seq}}`; ACK within 15 seconds
- Observed brokerage: flat ₹20/order; observed fills at tick close
- Rejections noted: simulation not live/paused, inactive ticker, unverified team, bad quantity, insufficient cash/margin

Recheck organizer docs if changed.

## Added from the official problem statement PDF (Hackathon_Problem_Statement.pdf)
Source: organizer PDF, not independently tested against the live gateway.

- News event type is `news_flash` (topic `market.news`), with `simulated_date` and `data:{ticker, headline, description, date}`.
- `GET /api/v1/stage` is public: `{stage: development|ready|preflight|simulation, status: IDLE|RUNNING|PAUSED|COMPLETED, days_completed, total_days, current_date}`. Orders only when `stage=="simulation"` and `status=="RUNNING"`.
- `GET /api/v1/stocks/:ticker/history?days=N` -> `{prices:[{date, open, high, low, close, volume}]}`; only bars strictly before the current simulation date (anti-lookahead).
- Order quantity: whole number 1..1,000,000. Optional `date` = current simulated date (used to measure reaction speed). All orders fill at the day's close.
- Rejection codes: ACCOUNT_NOT_VERIFIED, SIMULATION_NOT_RUNNING, INSUFFICIENT_CAPITAL, INSUFFICIENT_MARGIN, ACCOUNT_BLOCKED, NO_SHORT_POSITION, INVALID_TICKER, INVALID_QUANTITY, RATE_LIMITED.
- Rate limit 120 requests/min; HTTP 429 puts the token in a 30 s penalty box. Client self-limits to 100/min.
- Costs: flat Rs 20 brokerage per order, Rs 15.34 DP charge on delivery sells, STCG 15% / LTCG 10%.
- Decision window ~3-4 s per simulated day. Sandbox loops back to Day 1 at dataset end; the live run is a single pass.
- Starting capital Rs 10,00,000.

## Not verified (code reads these defensively)
- `GET /api/v1/portfolio` and `/portfolio/cash` exact field names (cash read from `cash`/`available_cash`/`cash_balance`; unknown cash is never treated as zero).
- `GET /api/v1/orders` schema (not used; uncertain orders are reconciled from the portfolio instead).
- Exact order error body shape (code read from `error` or `code`).

## Verified against the live gateway (2026-10-30, sandbox)
- `GET /api/v1/portfolio` top-level fields include: `available_cash`, `cash_balance`, `margin_locked`, `initial_capital`,
  `portfolio_market_value`, `total_wealth`, `realized_pnl`, `unrealized_pnl`, `total_pnl`, `total_pnl_pct`, `total_charges`,
  `total_taxes`, `stcg_gains`, `stcg_losses`, `ltcg_gains`, `ltcg_losses`, `taxable_stcg`, `taxable_ltcg`, `simulated_date`,
  `is_verified`, `is_blocked`, `total_orders`, `rejected_orders_count`, `error_count`, `cash_utilization_pct`.
- `holdings[]`: `ticker`, `quantity`, `avg_buy_price` (also `average_buy_price`), `current_price`, `market_value`,
  `unrealized_pnl`, `unrealized_pnl_pct`, `is_short`. The bot uses `avg_buy_price` as the tax cost basis after a restart.
- `GET /api/v1/orders`: `{orders: [...], total, page, limit, totalPages, summary: {total, filled, rejected, totalRealizedPnl, totalCharges}}`;
  each order has `order_id`, `ticker`, `action`, `quantity`, `execution_price`, `total_value`, `brokerage`, `realized_pnl`.
- Real fills observed: brokerage Rs 20 per order, filled at the day's close; 5/5 orders filled, 0 rejected.
