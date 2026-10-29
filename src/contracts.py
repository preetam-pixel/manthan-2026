from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Action = Literal["BUY", "SELL"]

@dataclass(frozen=True)
class Signal:
    ticker: str
    action: Action
    quantity: int
    timestamp: datetime
    reason: str
