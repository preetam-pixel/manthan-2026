from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from src.contracts import Signal

SMA_N = 8
BAND = 0.015
NOTIONAL = 50_000
MAX_POS_VALUE = 100_000


class SMAStrategy:
    """Long-only SMA8 +/-1.5% band strategy, ported from the original bot.

    Close history is kept per ticker (as in the original ``closes`` defaultdict).
    The signal is computed from the prior SMA_N closes; the current close is
    appended afterwards. Defaults reproduce the original bot exactly; the
    parameters exist so variants (e.g. ``sma_pro``) can be tested and run.
    """

    def __init__(self, n: int = SMA_N, band: float = BAND, notional: float = NOTIONAL,
                 max_position_value: float = MAX_POS_VALUE, name: str = "sma_band"):
        self.n, self.band, self.notional = n, band, notional
        self.max_position_value = max_position_value
        self.name = name
        self.closes = defaultdict(lambda: deque(maxlen=self.n))

    def reset(self, ticker: str) -> None:
        self.closes.pop(ticker, None)

    def warm_start(self, ticker: str, prior_closes) -> None:
        """Seed history from bars strictly before the current simulation date.

        Only the last ``n`` closes are kept. No signals are produced.
        """
        history = self.closes[ticker]
        history.clear()
        history.extend(c for c in prior_closes if c is not None and c > 0)

    def on_close(self, ticker: str, close: Optional[float], held_quantity: int,
                 timestamp: datetime) -> Optional[Signal]:
        if ticker is None or close is None:
            return None
        history = self.closes[ticker]
        signal = None
        if len(history) == self.n and close > 0:
            sma = sum(history) / self.n
            qty = max(1, int(self.notional // close))
            dev = close / sma - 1
            if close > sma * (1 + self.band) and (held_quantity + qty) * close <= self.max_position_value:
                signal = Signal(ticker, "BUY", qty, timestamp,
                                f"close above SMA{self.n} by {self.band:.1%} ({dev:+.2%})")
            elif close < sma * (1 - self.band) and held_quantity > 0:
                signal = Signal(ticker, "SELL", held_quantity, timestamp,
                                f"close below SMA{self.n} by {self.band:.1%} ({dev:+.2%})")
        # Preserve original ordering: signal calculation precedes append.
        history.append(close)
        return signal


def sma_pro():
    """Same robust SMA8 +/-1.5% rule with 1.5x capital deployment (Rs 75k per trade, Rs 1.5L cap)
    plus the year-end tax-loss harvesting overlay. Chosen from the 500-day study: +28% with a 10%
    max drawdown vs +18% / 7% for the original sizing (docs/STRATEGY_EVAL.md)."""
    strat = SMAStrategy(notional=75_000, max_position_value=150_000, name="sma_pro")
    strat.tax_harvest = True
    return strat
