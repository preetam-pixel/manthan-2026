"""Decision-time-safe features: only data available before the current tick."""
from typing import Optional, Sequence


def sma(prior_closes: Sequence[float], window: int) -> Optional[float]:
    """Mean of the last ``window`` closes, or None during warm-up."""
    if len(prior_closes) < window:
        return None
    return sum(prior_closes[-window:]) / window
