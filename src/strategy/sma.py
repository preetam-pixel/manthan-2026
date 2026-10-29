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
    appended afterwards.
    """

    def __init__(self):
        self.closes = defaultdict(lambda: deque(maxlen=SMA_N))

    def reset(self, ticker: str) -> None:
        self.closes.pop(ticker, None)

    def warm_start(self, ticker: str, prior_closes) -> None:
        """Seed history from bars strictly before the current simulation date.

        Only the last SMA_N closes are kept. No signals are produced.
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
        if len(history) == SMA_N and close > 0:
            sma = sum(history) / SMA_N
            qty = max(1, int(NOTIONAL // close))
            if close > sma * (1 + BAND) and (held_quantity + qty) * close <= MAX_POS_VALUE:
                signal = Signal(ticker, "BUY", qty, timestamp, f"close above SMA{SMA_N} by {BAND:.1%}")
            elif close < sma * (1 - BAND) and held_quantity > 0:
                signal = Signal(ticker, "SELL", held_quantity, timestamp, f"close below SMA{SMA_N} by {BAND:.1%}")
        # Preserve original ordering: signal calculation precedes append.
        history.append(close)
        return signal
