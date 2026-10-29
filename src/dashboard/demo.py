"""Offline demo: replay a recorded stream through the real bot and dashboard.

A simulated exchange fills orders at the day's close (like the real one). No network,
no token, no real orders - safe for rehearsals and as a fallback if the venue network fails.
"""
import time
from typing import Iterable

from src.execution.client import OrderResult

BROKERAGE = 20.0
DP_CHARGE = 15.34


class SimulatedAPI:
    def __init__(self, tickers: Iterable[str], total_days: int, interval_seconds: float = 10.0,
                 cash: float = 1_000_000.0):
        self.tickers = sorted(tickers)
        self.total_days, self.interval = total_days, interval_seconds
        self.cash, self.holdings = cash, {}
        self.last: dict[str, float] = {}
        self.date, self.days_done = None, 0
        self.bars: dict[str, list] = {}

    def acknowledge_preflight(self, seq):
        return {"status": "ok", "seq": seq}

    def get_stocks(self):
        return list(self.tickers)

    def get_stage(self):
        return {"stage": "development", "status": "running", "current_date": self.date,
                "days_completed": self.days_done, "total_days": self.total_days,
                "interval_seconds": self.interval, "is_sandbox_stream": True}

    def get_portfolio(self):
        return {"cash": self.cash,
                "holdings": [{"ticker": t, "quantity": q} for t, q in self.holdings.items() if q]}

    def get_history(self, ticker, days):
        return {"prices": list(self.bars.get(ticker, []))}

    def submit_order(self, ticker, action, quantity, date=None):
        price = self.last.get(ticker)
        if not price:
            return OrderResult("REJECTED", code="INVALID_TICKER")
        if action == "BUY":
            cost = quantity * price + BROKERAGE
            if cost > self.cash:
                return OrderResult("REJECTED", code="INSUFFICIENT_CAPITAL")
            self.cash -= cost
            self.holdings[ticker] = self.holdings.get(ticker, 0) + quantity
        else:
            if self.holdings.get(ticker, 0) < quantity:
                return OrderResult("REJECTED", code="NO_POSITION")
            self.cash += quantity * price - BROKERAGE - DP_CHARGE
            self.holdings[ticker] -= quantity
        return OrderResult("FILLED", body={"execution_price": price})

    # ---- replay support ----------------------------------------------
    def observe(self, ticker: str, date: str, bar: dict) -> None:
        self.last[ticker] = bar["close"]
        if date != self.date:
            self.date, self.days_done = date, self.days_done + 1
        self.bars.setdefault(ticker, []).append({"date": date, **bar})


def replay(bot, api: SimulatedAPI, records, seconds_per_day: float, stop=lambda: False) -> int:
    """Feed recorded events to the bot, pausing ``seconds_per_day`` between simulated days."""
    days, current = 0, None
    for rec in records:
        if stop():
            break
        ev = rec["event"]
        data = ev.get("data") or {}
        if rec["topic"] == "market.ticks" and ev.get("event_type") == "price_tick":
            date = ev.get("simulated_date")
            if date != current:
                if current is not None:
                    time.sleep(seconds_per_day)
                current, days = date, days + 1
            api.observe(data["ticker"], date, {k: data.get(k) for k in ("open", "high", "low", "close", "volume")})
        bot.handle_message(rec["topic"], ev)
    return days
