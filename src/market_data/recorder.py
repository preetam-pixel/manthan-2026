"""Record the Kafka market stream to JSONL, and load it back for backtests.

Read-only: it never calls the order API. Each line is one event:
  {"recv_at": ISO-UTC, "topic": ..., "partition": n, "offset": n, "event": {...raw...}}
Preflight pings and empty news filler are counted but not stored.
"""
import json
from datetime import datetime, timezone
from typing import Iterable, Optional

from src.market_data.consumer import TOPIC_NEWS, TOPIC_TICKS, event_type

PRICE_EVENT = "price_tick"
NEWS_EVENT = "news_flash"


def to_record(topic: str, partition: int, offset: int, event, now: Optional[datetime] = None) -> Optional[dict]:
    """Storable record for a price tick or real news item; None for anything else."""
    if not isinstance(event, dict):
        return None
    kind = event_type(event)
    data = event.get("data") or {}
    keep = (topic == TOPIC_TICKS and kind == PRICE_EVENT and data.get("ticker")) or \
           (topic == TOPIC_NEWS and kind == NEWS_EVENT and data.get("ticker"))
    if not keep:
        return None
    return {"recv_at": (now or datetime.now(timezone.utc)).isoformat(),
            "topic": topic, "partition": partition, "offset": offset, "event": event}


def read_records(path: str) -> Iterable[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue                      # a half-written last line must not break loading
            if isinstance(rec, dict) and isinstance(rec.get("event"), dict):
                yield rec


def load_stream(path: str, loop: Optional[int] = None):
    """(history, news) from a recording.

    history: {ticker: [bar, ...]} oldest first, one bar per (ticker, date).
    news:    [news_flash event, ...] in arrival order.
    The sandbox replays the same days in loops; ``loop`` selects one loop_count
    (default: the first loop seen) so repeated dates are not mixed together.
    """
    history: dict[str, dict[str, dict]] = {}
    news = []
    chosen = loop
    for rec in read_records(path):
        ev = rec["event"]
        sandbox = ev.get("sandbox") or {}
        loop_no = sandbox.get("loop_count")
        if chosen is None and loop_no is not None:
            chosen = loop_no
        if loop_no is not None and chosen is not None and loop_no != chosen:
            continue
        data = ev.get("data") or {}
        if rec.get("topic") == TOPIC_TICKS and event_type(ev) == PRICE_EVENT:
            date, close = ev.get("simulated_date") or data.get("date"), data.get("close")
            if date and isinstance(close, (int, float)) and not isinstance(close, bool) and close > 0:
                history.setdefault(data["ticker"], {})[date] = {
                    "date": date, "open": data.get("open"), "high": data.get("high"),
                    "low": data.get("low"), "close": close, "volume": data.get("volume")}
        elif rec.get("topic") == TOPIC_NEWS and event_type(ev) == NEWS_EVENT:
            news.append(ev)
    ordered = {t: [bars[d] for d in sorted(bars)] for t, bars in history.items()}
    return ordered, news
