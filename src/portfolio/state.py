"""Local portfolio view, synced from /api/v1/portfolio and updated on accepted orders.

Long-only: short holdings map to zero, as in the original bot. The portfolio
endpoint's full schema is not independently verified; fields are read
defensively and unknown cash stays None (callers must not treat it as zero).
"""
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
        self.uncertain: set[str] = set()      # tickers with an unresolved order
        self.submitted: set[tuple] = set()    # (ticker, action, simulated_date)

    def quantity(self, ticker: str) -> int:
        return self.held.get(ticker, 0)

    def sync(self, portfolio: dict) -> None:
        """Replace local state with the exchange's view (authoritative)."""
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
        self.synced = True

    def apply_fill(self, ticker: str, action: str, quantity: int,
                   price: Optional[float] = None, brokerage: float = 20.0) -> None:
        """Update after an accepted order; cash only when the price is known."""
        if action == "BUY":
            self.held[ticker] = self.quantity(ticker) + quantity
            if self.cash is not None and price:
                self.cash -= quantity * price + brokerage
        elif action == "SELL":
            self.held[ticker] = max(self.quantity(ticker) - quantity, 0)
            if self.cash is not None and price:
                self.cash += quantity * price - brokerage

    # ---- uncertain-order handling ----------------------------------
    def mark_uncertain(self, ticker: str) -> None:
        self.uncertain.add(ticker)

    def resolve_uncertain(self, portfolio: dict) -> None:
        """Re-sync from the exchange; only then may the ticker trade again."""
        self.sync(portfolio)
        self.uncertain.clear()

    def has_submitted(self, key: tuple) -> bool:
        return key in self.submitted

    def record_submitted(self, key: tuple) -> None:
        self.submitted.add(key)
