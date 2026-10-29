"""Record market.ticks / market.news to a JSONL file (read-only, no consumer group).

Usage:
  py -m scripts.record_stream                      # record until Ctrl+C
  py -m scripts.record_stream --seconds 600        # record for 10 minutes
  py -m scripts.record_stream --export recording.jsonl history.json news.json

Safe to run next to the bot: it uses group_id=None, so it never takes partitions
from your `group-<username>` consumers and never commits offsets.
"""
import json
import os
import sys
import time
from datetime import datetime

from src.app import _load_dotenv
from src.market_data.consumer import TOPIC_NEWS, TOPIC_TICKS
from src.market_data.recorder import load_stream, to_record


def export(src: str, history_out: str, news_out: str) -> None:
    history, news = load_stream(src)
    json.dump(history, open(history_out, "w", encoding="utf-8"))
    json.dump(news, open(news_out, "w", encoding="utf-8"))
    days = max((len(v) for v in history.values()), default=0)
    print(f"exported {len(history)} tickers x up to {days} days, {len(news)} news items")


def record(path: str, seconds: float) -> None:
    from kafka import KafkaConsumer  # imported lazily

    _load_dotenv()
    broker = os.environ.get("BROKER", "192.168.65.157:9094")
    consumer = KafkaConsumer(
        TOPIC_TICKS, TOPIC_NEWS, bootstrap_servers=[broker], group_id=None,
        auto_offset_reset="latest", enable_auto_commit=False,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")) if m else None,
        consumer_timeout_ms=15000)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    stored = skipped = 0
    end = time.time() + seconds if seconds else None
    print(f"recording to {path} (Ctrl+C to stop)", flush=True)
    try:
        with open(path, "a", encoding="utf-8") as out:
            while end is None or time.time() < end:
                for message in consumer:
                    try:
                        rec = to_record(message.topic, message.partition, message.offset, message.value)
                    except Exception:
                        rec = None
                    if rec is None:
                        skipped += 1
                    else:
                        out.write(json.dumps(rec) + "\n")
                        out.flush()
                        stored += 1
                    if stored and stored % 200 == 0:
                        print(time.strftime("%H:%M:%S"), f"stored {stored}", flush=True)
                    if end is not None and time.time() >= end:
                        break
    except KeyboardInterrupt:
        pass
    finally:
        consumer.close()
        print(f"done: stored {stored}, skipped {skipped} (preflight pings / empty filler)")


def main(argv: list[str]) -> None:
    if argv[:1] == ["--export"] and len(argv) == 4:
        export(*argv[1:])
        return
    seconds = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 0
    path = os.path.join("data", f"stream_{datetime.now():%Y%m%d_%H%M%S}.jsonl")
    record(path, seconds)


if __name__ == "__main__":
    main(sys.argv[1:])
