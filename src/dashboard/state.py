"""Thread-safe, read-only view of what the bot is doing, for the dashboard.

The bot thread writes through the ``record_*`` methods; the HTTP thread reads
copies via the ``*_view`` methods. Nothing here can place an order.
"""
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

STARTING_CAPITAL = 1_000_000.0
BAND = 0.015
SMA_WINDOW = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DashboardState:
    def __init__(self, strategy: str = "sma_band", max_events: int = 500, max_points: int = 400):
        self._lock = threading.RLock()
        self.strategy = strategy
        self.kafka_connected = False
        self.started_at = time.time()
        self.last_heartbeat_seq: Optional[int] = None
        self.last_heartbeat_at: Optional[str] = None
        self.orders_sent = 0
        self.orders_rejected = 0
        self._events: deque = deque(maxlen=max_events)       # trading activity (signals, orders, blocks...)
        self._news_events: deque = deque(maxlen=150)         # news is frequent; it must not evict trades
        self._next_id = 1
        self._orders: deque = deque(maxlen=300)
        self._series: dict[str, deque] = {}
        self._max_points = max_points
        self._equity: dict[str, dict] = {}
        self._news: deque = deque(maxlen=100)
        self._lots: dict[str, dict] = {}          # ticker -> {qty, avg, since}
        self.last_close: dict[str, float] = {}

    # ---- writers (bot thread) -----------------------------------------
    def record_event(self, type_: str, message: str, ticker: Optional[str] = None,
                     reason: Optional[str] = None, simulated_date: Optional[str] = None,
                     data: Optional[dict] = None) -> None:
        with self._lock:
            bucket = self._news_events if type_ == "NEWS" else self._events
            bucket.append({
                "id": self._next_id, "time": _now_iso(), "simulated_date": simulated_date,
                "type": type_, "ticker": ticker, "message": message, "reason": reason, "data": data})
            self._next_id += 1

    def record_heartbeat(self, seq: int) -> None:
        with self._lock:
            self.last_heartbeat_seq, self.last_heartbeat_at = seq, _now_iso()

    def record_tick(self, ticker: str, date: Optional[str], bar: dict) -> None:
        close = bar.get("close")
        if not ticker or isinstance(close, bool) or not isinstance(close, (int, float)) or close <= 0:
            return
        with self._lock:
            self.last_close[ticker] = float(close)
            points = self._series.setdefault(ticker, deque(maxlen=self._max_points))
            if points and points[-1]["date"] == date:
                points.pop()                                  # redelivery of the same day
            closes = [p["close"] for p in points][-(SMA_WINDOW - 1):] + [float(close)]
            sma = sum(closes) / len(closes) if len(closes) == SMA_WINDOW else None
            points.append({
                "date": date, "open": bar.get("open"), "high": bar.get("high"), "low": bar.get("low"),
                "close": float(close), "volume": bar.get("volume"),
                "sma8": sma, "sma": sma,
                "upper": sma * (1 + BAND) if sma else None, "lower": sma * (1 - BAND) if sma else None})

    def reset_ticker(self, ticker: str) -> None:
        with self._lock:
            self._series.pop(ticker, None)

    def record_news(self, ticker: str, date: Optional[str], headline: Optional[str],
                    keyword_score: int) -> None:
        with self._lock:
            self._news.appendleft({"ticker": ticker, "simulated_date": date, "headline": headline,
                                   "keyword_score": keyword_score})

    def record_order(self, ticker: str, action: str, quantity: int, price: float, status: str,
                     code: Optional[str], latency_s: Optional[float], fees: Optional[float] = None) -> None:
        with self._lock:
            self.orders_sent += 1
            if status == "REJECTED":
                self.orders_rejected += 1
            self._orders.appendleft({"time": _now_iso(), "ticker": ticker, "action": action,
                                     "quantity": quantity, "price": price, "status": status,
                                     "code": code, "fees": fees, "latency_s": latency_s})

    def record_fill(self, ticker: str, action: str, quantity: int, price: float,
                    date: Optional[str]) -> None:
        with self._lock:
            lot = self._lots.get(ticker, {"qty": 0, "avg": 0.0, "since": None})
            if action == "BUY":
                total = lot["qty"] + quantity
                lot["avg"] = (lot["avg"] * lot["qty"] + price * quantity) / total if total else 0.0
                lot["since"] = lot["since"] or date
                lot["qty"] = total
            else:
                lot["qty"] = max(lot["qty"] - quantity, 0)
                if lot["qty"] == 0:
                    lot = {"qty": 0, "avg": 0.0, "since": None}
            self._lots[ticker] = lot

    def record_equity(self, date: Optional[str], total_wealth: Optional[float],
                      cash: Optional[float], invested: float) -> None:
        if not date or total_wealth is None:
            return
        with self._lock:
            self._equity[date] = {"date": date, "total_wealth": total_wealth, "cash": cash,
                                  "invested": invested}
            while len(self._equity) > self._max_points:
                self._equity.pop(next(iter(self._equity)))

    # ---- readers (HTTP thread) ------------------------------------------
    def events_since(self, since: int) -> list[dict]:
        with self._lock:
            merged = [e for e in (*self._events, *self._news_events) if e["id"] > since]
            return [dict(e) for e in sorted(merged, key=lambda e: e["id"], reverse=True)]   # newest first

    def orders_view(self) -> list[dict]:
        with self._lock:
            return [dict(o) for o in self._orders]

    def news_view(self) -> list[dict]:
        with self._lock:
            return [dict(n) for n in self._news]

    def series_view(self) -> dict:
        with self._lock:
            return {t: {"ticker": t, "points": [dict(p) for p in pts]} for t, pts in self._series.items()}

    def equity_view(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._equity.values()]

    def positions_view(self, held: dict, max_pos_value: float = 100_000.0) -> list[dict]:
        out = []
        with self._lock:
            for ticker, qty in sorted(held.items()):
                if qty <= 0:
                    continue
                last = self.last_close.get(ticker)
                lot = self._lots.get(ticker) or {}
                avg = lot.get("avg") or None
                value = qty * last if last else None
                out.append({
                    "ticker": ticker, "quantity": qty, "last_close": last, "avg_price": avg,
                    "value": value,
                    "unrealized_pnl": (last - avg) * qty if last and avg else None,
                    "cap_used_pct": value / max_pos_value * 100 if value else None,
                    "held_since": lot.get("since")})
        return out

    def stats_view(self, latencies: list) -> dict:
        with self._lock:
            ordered = sorted(latencies)
            p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))] if ordered else None
            return {"orders_sent": self.orders_sent, "orders_rejected": self.orders_rejected,
                    "latency_avg_s": sum(ordered) / len(ordered) if ordered else None,
                    "latency_p95_s": p95, "latency_max_s": ordered[-1] if ordered else None}
