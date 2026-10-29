"""Kafka event parsing for market.ticks / market.news (no I/O here)."""
from typing import Optional

TOPIC_TICKS = "market.ticks"
TOPIC_NEWS = "market.news"
EVENT_PREFLIGHT = "preflight_tick"
EVENT_PRICE = "price_tick"


def event_type(event: dict) -> Optional[str]:
    return event.get("event_type") or event.get("event")


def is_preflight(event: dict) -> bool:
    return event_type(event) == EVENT_PREFLIGHT


def is_price_tick(topic: str, event: dict) -> bool:
    return topic == TOPIC_TICKS and event_type(event) == EVENT_PRICE


def preflight_seq(event: dict) -> Optional[int]:
    """Heartbeat sequence number: top-level ``seq``, else ``data.seq``."""
    seq = event.get("seq")
    if seq is None:
        seq = (event.get("data") or {}).get("seq")
    return seq


def parse_history(response: dict) -> list[tuple[str, float]]:
    """(date, close) pairs, oldest first, from GET /stocks/:ticker/history.

    Bars with a missing or non-positive close are dropped, never zero-filled.
    """
    out = []
    for bar in (response or {}).get("prices") or []:
        date, close = bar.get("date"), bar.get("close")
        if date and isinstance(close, (int, float)) and not isinstance(close, bool) and close > 0:
            out.append((date, float(close)))
    out.sort(key=lambda p: p[0])
    return out


def normalize_tick(event: dict) -> dict:
    data = event.get("data") or {}
    return {
        "event_type": event_type(event),
        "timestamp": event.get("timestamp"),
        "simulated_date": event.get("simulated_date"),
        "ticker": data.get("ticker"),
        "close": data.get("close"),
        "open": data.get("open"),
        "high": data.get("high"),
        "low": data.get("low"),
        "volume": data.get("volume"),
    }
