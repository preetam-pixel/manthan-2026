"""Risk gate: every order path goes through RiskManager.evaluate."""
import math
from dataclasses import dataclass
from typing import Optional

from src.contracts import Signal
from src.portfolio.state import PortfolioState
from src.strategy.sma import MAX_POS_VALUE

BROKERAGE_INR = 20.0
MAX_QUANTITY = 1_000_000
MAX_TICK_AGE_S = 3.0          # decision window is ~3-4s per simulated day


@dataclass(frozen=True)
class Decision:
    approved: bool
    reason: str


def _reject(reason: str) -> Decision:
    return Decision(False, reason)


class RiskManager:
    def __init__(self, max_pos_value: float = MAX_POS_VALUE,
                 max_tick_age_s: float = MAX_TICK_AGE_S):
        self.max_pos_value = max_pos_value
        self.max_tick_age_s = max_tick_age_s

    def evaluate(self, signal: Signal, price: Optional[float], tick_age_s: float,
                 simulated_date: Optional[str], universe: Optional[set],
                 portfolio: PortfolioState, sim_running: bool) -> Decision:
        if not sim_running:
            return _reject("simulation not running")
        if signal.action not in ("BUY", "SELL"):
            return _reject(f"action {signal.action!r} not allowed (long-only)")
        if (isinstance(signal.quantity, bool) or not isinstance(signal.quantity, int)
                or not 1 <= signal.quantity <= MAX_QUANTITY):
            return _reject("quantity must be a positive whole number")
        if not universe:
            return _reject("tradable universe unknown")
        if signal.ticker not in universe:
            return _reject("ticker not tradable")
        if price is None or not math.isfinite(price) or price <= 0:
            return _reject("missing or invalid price")
        if tick_age_s > self.max_tick_age_s:
            return _reject("stale market data")
        if not portfolio.synced:
            return _reject("portfolio not synced")
        if signal.ticker in portfolio.uncertain:
            return _reject("unresolved order outcome for ticker")
        if portfolio.has_submitted((signal.ticker, signal.action, simulated_date)):
            return _reject("duplicate order for ticker/action/date")

        held = portfolio.quantity(signal.ticker)
        if signal.action == "SELL":
            if held <= 0:
                return _reject("no long position to sell")
            if signal.quantity > held:
                return _reject("sell quantity exceeds holdings")
        else:
            if (held + signal.quantity) * price > self.max_pos_value:
                return _reject("per-ticker position cap")
            if portfolio.cash is not None and \
                    signal.quantity * price + BROKERAGE_INR > portfolio.cash:
                return _reject("insufficient cash")
        return Decision(True, "ok")
