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
        self.initial = cash
        self.avg: dict[str, float] = {}               # avg buy price, brokerage excluded (as the exchange reports)
        self.charges = self.realized = 0.0
        self.orders = self.rejected = 0
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
        """Same fields as the real /api/v1/portfolio (docs/API_VERIFIED.md)."""
        holdings = []
        for t, q in self.holdings.items():
            if q:
                price = self.last.get(t, self.avg[t])
                holdings.append({"ticker": t, "quantity": q, "avg_buy_price": round(self.avg[t], 2),
                                 "current_price": price, "market_value": q * price,
                                 "unrealized_pnl": q * (price - self.avg[t]), "is_short": False})
        market = sum(h["market_value"] for h in holdings)
        unrealized = sum(h["unrealized_pnl"] for h in holdings)
        total = self.cash + market
        return {"initial_capital": self.initial, "available_cash": self.cash, "cash_balance": self.cash,
                "portfolio_market_value": market, "total_wealth": total,
                "realized_pnl": self.realized, "unrealized_pnl": unrealized,
                "total_pnl": total - self.initial, "total_pnl_pct": round((total / self.initial - 1) * 100, 2),
                "total_charges": self.charges, "total_taxes": 0.0,
                "total_orders": self.orders, "rejected_orders_count": self.rejected,
                "simulated_date": self.date, "holdings": holdings}

    def get_history(self, ticker, days):
        return {"prices": list(self.bars.get(ticker, []))}

    def submit_order(self, ticker, action, quantity, date=None):
        self.orders += 1
        price = self.last.get(ticker)
        if not price:
            self.rejected += 1
            return OrderResult("REJECTED", code="INVALID_TICKER")
        held = self.holdings.get(ticker, 0)
        if action == "BUY":
            cost = quantity * price + BROKERAGE
            if cost > self.cash:
                self.rejected += 1
                return OrderResult("REJECTED", code="INSUFFICIENT_CAPITAL")
            self.cash -= cost
            self.charges += BROKERAGE
            self.avg[ticker] = (self.avg.get(ticker, 0.0) * held + price * quantity) / (held + quantity)
            self.holdings[ticker] = held + quantity
        else:
            if held < quantity:
                self.rejected += 1
                return OrderResult("REJECTED", code="NO_POSITION")
            self.cash += quantity * price - BROKERAGE - DP_CHARGE
            self.charges += BROKERAGE + DP_CHARGE
            self.realized += quantity * (price - self.avg[ticker]) - BROKERAGE - DP_CHARGE
            self.holdings[ticker] = held - quantity
            if not self.holdings[ticker]:
                self.avg.pop(ticker, None)
        return OrderResult("FILLED", body={"execution_price": price})

    # ---- replay support ----------------------------------------------
    def observe(self, ticker: str, date: str, bar: dict) -> None:
        self.last[ticker] = bar["close"]
        self._seen_dates = getattr(self, "_seen_dates", set())
        self._seen_dates.add(date)                     # ticks of adjacent days can interleave
        self.days_done = len(self._seen_dates)
        self.date = max(self.date or date, date)
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
