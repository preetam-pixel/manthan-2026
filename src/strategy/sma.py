from collections import deque
from datetime import datetime
from src.contracts import Signal

SMA_N = 8
BAND = 0.015
NOTIONAL = 50_000
MAX_POS_VALUE = 100_000

class SMAStrategy:
    def __init__(self):
        self.closes = deque(maxlen=SMA_N)

    def on_close(self, ticker: str, close: float, held_quantity: int, timestamp: datetime):
        if close is None:
            return None
        signal = None
        if len(self.closes) == SMA_N:
            sma = sum(self.closes) / SMA_N
            qty = max(1, int(NOTIONAL // close))
            if close > sma * (1 + BAND) and (held_quantity + qty) * close <= MAX_POS_VALUE:
                signal = Signal(ticker, "BUY", qty, timestamp, f"close above SMA{SMA_N} by {BAND:.1%}")
            elif close < sma * (1 - BAND) and held_quantity > 0:
                signal = Signal(ticker, "SELL", held_quantity, timestamp, f"close below SMA{SMA_N} by {BAND:.1%}")
        # Preserve original ordering: signal calculation precedes append.
        self.closes.append(close)
        return signal
