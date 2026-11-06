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


def load_stream(path: str, loop: Optional[int] = None, report: Optional[dict] = None):
    """(history, news) from a recording.

    history: {ticker: [bar, ...]} oldest first, one bar per (ticker, date).
    news:    [news_flash event, ...] in arrival order, one per (ticker, date, headline).
    The sandbox replays the same days in loops. By default every loop is merged
    (first value wins) so a recording that starts mid-loop still covers all days;
    pass ``loop`` to use a single loop_count instead. If ``report`` is given it is
    filled with ``conflicts``: how many bars reappeared with a different close
    (non-zero means the loops are NOT identical and merging is unsafe).
    """
    history: dict[str, dict[str, dict]] = {}
    news, seen_news = [], set()
    conflicts = 0
    for rec in read_records(path):
        ev = rec["event"]
        loop_no = (ev.get("sandbox") or {}).get("loop_count")
        if loop is not None and loop_no != loop:
            continue
        data = ev.get("data") or {}
        if rec.get("topic") == TOPIC_TICKS and event_type(ev) == PRICE_EVENT:
            date, close = ev.get("simulated_date") or data.get("date"), data.get("close")
            if date and isinstance(close, (int, float)) and not isinstance(close, bool) and close > 0:
                bars = history.setdefault(data["ticker"], {})
                if date in bars:
                    conflicts += bars[date]["close"] != close
                    continue
                bars[date] = {"date": date, "open": data.get("open"), "high": data.get("high"),
                              "low": data.get("low"), "close": close, "volume": data.get("volume")}
        elif rec.get("topic") == TOPIC_NEWS and event_type(ev) == NEWS_EVENT:
            key = (data.get("ticker"), ev.get("simulated_date"), data.get("headline"))
            if key not in seen_news:
                seen_news.add(key)
                news.append(ev)
    if report is not None:
        report["conflicts"] = conflicts
    ordered = {t: [bars[d] for d in sorted(bars)] for t, bars in history.items()}
    return ordered, news
