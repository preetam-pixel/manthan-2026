"""Local portfolio view, synced from /api/v1/portfolio and updated on accepted orders.

Long-only: short holdings map to zero, as in the original bot. The portfolio
endpoint's full schema is not independently verified; fields are read
defensively and unknown cash stays None (callers must not treat it as zero).
"""
from datetime import datetime, timezone
from typing import Optional


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class PortfolioState:
    def __init__(self):
        self.held: dict[str, int] = {}
        self.avg_price: dict[str, float] = {}       # exchange cost basis (avg_buy_price), when provided
        self.cash: Optional[float] = None
        self.synced = False
        self.exchange: dict = {}                    # last raw /portfolio answer (what the portal shows)
        self.synced_at: Optional[str] = None        # wall-clock time of that answer (UTC ISO)
        self.account_reset: Optional[dict] = None   # last time the exchange's order count went down
        self.uncertain: set[str] = set()      # tickers with an unresolved order
        self.submitted: set[tuple] = set()    # (ticker, action, simulated_date)

    def quantity(self, ticker: str) -> int:
        return self.held.get(ticker, 0)

    def sync(self, portfolio: dict) -> bool:
        """Replace local state with the exchange's view (authoritative).

        Returns True when the account was reset on the exchange since the last answer: its
        order count only grows, so a drop means earlier orders are no longer on the account."""
        before, after = _number(self.exchange.get("total_orders")), _number(portfolio.get("total_orders"))
        holdings = {}
        for h in portfolio.get("holdings") or []:
            ticker, qty = h.get("ticker"), h.get("quantity")
            if not ticker or isinstance(qty, bool) or not isinstance(qty, int):
                continue
            holdings[ticker] = 0 if h.get("is_short") else max(qty, 0)
        self.held = holdings
        self.avg_price = {}
        for h in portfolio.get("holdings") or []:
            price = _number(h.get("avg_buy_price", h.get("average_buy_price")))
            if h.get("ticker") and price and not h.get("is_short"):
                self.avg_price[h["ticker"]] = price
        for key in ("cash", "available_cash", "cash_balance"):
            cash = _number(portfolio.get(key))
            if cash is not None:
                self.cash = cash
                break
        self.exchange = dict(portfolio)
        self.synced_at = datetime.now(timezone.utc).isoformat()
        self.synced = True
        reset = before is not None and after is not None and after < before
        if reset:
            self.account_reset = {"at": self.synced_at, "orders_before": int(before), "orders_after": int(after)}
        return reset

    def exchange_holding(self, ticker: str) -> dict:
        for h in self.exchange.get("holdings") or []:
            if h.get("ticker") == ticker and not h.get("is_short"):
                return h
        return {}

    def apply_fill(self, ticker: str, action: str, quantity: int,
                   price: Optional[float] = None, brokerage: float = 20.0,
                   dp_charge: float = 15.34) -> None:
        """Update after an accepted order; cash only when the price is known.
        Sells also pay the DP charge, as the exchange deducts it."""
        if action == "BUY":
            self.held[ticker] = self.quantity(ticker) + quantity
            if self.cash is not None and price:
                self.cash -= quantity * price + brokerage
        elif action == "SELL":
            self.held[ticker] = max(self.quantity(ticker) - quantity, 0)
            if self.cash is not None and price:
                self.cash += quantity * price - brokerage - dp_charge

    # ---- uncertain-order handling ----------------------------------
    def mark_uncertain(self, ticker: str) -> None:
        self.uncertain.add(ticker)

    def resolve_uncertain(self, portfolio: dict) -> bool:
        """Re-sync from the exchange; only then may the ticker trade again."""
        reset = self.sync(portfolio)
        self.uncertain.clear()
        return reset

    def has_submitted(self, key: tuple) -> bool:
        return key in self.submitted

    def record_submitted(self, key: tuple) -> None:
        self.submitted.add(key)
