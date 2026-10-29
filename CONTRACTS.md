# Shared Contracts — based on uploaded bot + handoff

## Facts from supplied HANDOFF.md
- REST gateway: `http://192.168.65.157:3002`
- Kafka broker: `192.168.65.157:9094`
- Topics: `market.ticks`, `market.news`
- Consumer group convention: `group-{HACKATHON_USERNAME}`
- Event names: `preflight_tick`, `price_tick`; news topic is described as `news_flash`
- Routes used: `GET /api/v1/stocks`, `POST /api/v1/bot/heartbeat`, `POST /api/v1/orders`, `GET /api/v1/portfolio`, `GET /api/v1/orders`
- Order body: `{ticker, action, quantity}`; actions BUY, SELL, SHORT, COVER; quantity positive whole number.
- Preflight heartbeat ACKs `seq` within 15 seconds.
- Current bot does not short; it buys and sells long holdings.

## Signal contract
```python
@dataclass(frozen=True)
class Signal:
    ticker: str
    action: Literal["BUY", "SELL"]
    quantity: int
    timestamp: datetime
    reason: str
```

This starter models the current long-only SMA bot. Do not add SHORT/COVER to strategy behavior unless explicitly approved.

## Existing behavior to preserve initially
- `SMA_N = 8`; `BAND = 0.015`
- `NOTIONAL = 50000`; `MAX_POS_VALUE = 100000`
- SMA uses the prior eight closes before appending the current close.
- Buy above SMA by 1.5%, subject to per-ticker cap.
- Sell entire long position below SMA by 1.5%.
- Startup sync from `/api/v1/portfolio`; current bot maps short holdings to zero.
- News keyword scoring is logging only; no news-driven trades.

Do not change parameters without identifying a strategy change.
