"""Decision journal: one record per trading decision, so every trade can be explained.

Each entry captures what the bot saw (price, strategy reason, recent news context),
what the risk gate decided, what the exchange answered, latency, fees and the tax
consequence. Entries are kept in memory for the dashboard and, when a path is given,
appended to a JSONL file that survives restarts (for the jury defence).
"""
import csv
import io
import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

FIELDS = ["time", "simulated_date", "ticker", "strategy", "action", "quantity", "price", "reason",
          "news_score", "risk_approved", "risk_reason", "outcome", "code", "fill_price",
          "latency_s", "fees", "realized_gain", "tax_term"]


class DecisionJournal:
    def __init__(self, path: Optional[str] = None, keep: int = 2000):
        self.path = path
        self._lock = threading.Lock()
        self._entries: deque = deque(maxlen=keep)
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def record(self, entry: dict) -> None:
        row = {k: entry.get(k) for k in FIELDS}
        row["time"] = row["time"] or datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._entries.appendleft(row)
            if self.path:
                try:
                    with open(self.path, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(row, default=str) + "\n")
                except OSError:
                    pass                         # the journal must never stop trading

    def recent(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [dict(e) for e in list(self._entries)[:limit]]

    def to_csv(self) -> str:
        with self._lock:
            rows = list(reversed(self._entries))
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    def stats(self) -> dict:
        with self._lock:
            rows = list(self._entries)
        sent = [r for r in rows if r["outcome"]]
        return {"decisions": len(rows), "orders": len(sent),
                "filled": sum(r["outcome"] == "FILLED" for r in sent),
                "rejected": sum(r["outcome"] == "REJECTED" for r in sent),
                "blocked": sum(r["risk_approved"] is False for r in rows)}
