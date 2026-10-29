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
