"""Decision-time-safe features: only data available before the current tick.

Every function takes already-observed bars/closes. Callers must pass prior bars
(not the bar being decided on) wherever a signal is computed from them.
"""
from typing import Optional, Sequence


def sma(prior_closes: Sequence[float], window: int) -> Optional[float]:
    """Mean of the last ``window`` closes, or None during warm-up."""
    if len(prior_closes) < window:
        return None
    return sum(prior_closes[-window:]) / window


def atr(bars: Sequence[dict], window: int = 14) -> Optional[float]:
    """Average true range over the last ``window`` bars (needs window + 1 bars)."""
    if len(bars) < window + 1:
        return None
    recent = bars[-(window + 1):]
    total = 0.0
    for prev, cur in zip(recent, recent[1:]):
        total += max(cur["high"] - cur["low"],
                     abs(cur["high"] - prev["close"]),
                     abs(cur["low"] - prev["close"]))
    return total / window


def rsi(closes: Sequence[float], window: int = 14) -> Optional[float]:
    """RSI from simple average gains/losses; None during warm-up."""
    if len(closes) < window + 1:
        return None
    recent = closes[-(window + 1):]
    gains = losses = 0.0
    for a, b in zip(recent, recent[1:]):
        change = b - a
        if change > 0:
            gains += change
        else:
            losses -= change
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = (gains / window) / (losses / window)
    return 100.0 - 100.0 / (1.0 + rs)


def volume_ratio(prior_volumes: Sequence[Optional[float]], current: Optional[float],
                 window: int = 20) -> Optional[float]:
    """Current volume divided by the mean of the prior ``window`` volumes."""
    vols = [v for v in prior_volumes[-window:] if isinstance(v, (int, float)) and v > 0]
    if current is None or current <= 0 or len(vols) < max(3, window // 2):
        return None
    return current / (sum(vols) / len(vols))
