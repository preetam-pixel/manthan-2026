"""News risk filter: can only VETO new entries. It never creates a trade.

Headlines in this simulation are real-world articles with masked company names,
so most carry no financial signal; the filter is deliberately conservative and
acts only on clearly negative recent news for the same ticker.
"""
import re
from collections import defaultdict, deque
from datetime import date as date_cls
from typing import Optional

NEGATIVE = {
    # severe
    "fraud": 2, "bankruptcy": 2, "bankrupt": 2, "default": 2, "scandal": 2, "probe": 2,
    "investigation": 2, "lawsuit": 2, "sued": 2, "recall": 2, "breach": 2, "hack": 2,
    "plunge": 2, "plunges": 2, "crash": 2, "halt": 2, "ban": 2, "banned": 2, "delisted": 2,
    # mild
    "downgrade": 1, "downgrades": 1, "miss": 1, "misses": 1, "loss": 1, "losses": 1,
    "weak": 1, "cuts": 1, "cut": 1, "layoffs": 1, "slump": 1, "decline": 1, "declines": 1,
    "warns": 1, "warning": 1, "fine": 1, "fined": 1, "outage": 1, "delay": 1, "delays": 1,
    "shortage": 1, "strike": 1, "falls": 1, "tumble": 1, "tumbles": 1,
}
POSITIVE = {
    "record": 1, "surge": 1, "surges": 1, "soar": 1, "soars": 1, "upgrade": 1, "upgrades": 1,
    "beat": 1, "beats": 1, "profit": 1, "wins": 1, "expands": 1, "raises": 1, "strong": 1,
    "growth": 1, "approval": 1, "approved": 1,
}
NEGATORS = {"no", "not", "never", "without", "denies", "denied", "avoids", "avoid", "fails", "despite"}
_WORD = re.compile(r"[a-z']+")


def score_text(text: str) -> float:
    """Signed score in [-4, +4]; a negator within 3 words before a term flips it."""
    words = _WORD.findall((text or "").lower())
    total = 0.0
    for i, w in enumerate(words):
        weight = NEGATIVE.get(w, 0) * -1 or POSITIVE.get(w, 0)
        if not weight:
            continue
        if any(p in NEGATORS for p in words[max(0, i - 3):i]):
            weight = -weight
        total += weight
    return max(-4.0, min(4.0, total))


def _day(value) -> Optional[date_cls]:
    try:
        return date_cls.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class NewsFilter:
    def __init__(self, lookback_days: int = 3, veto_threshold: float = -2.0):
        self.lookback_days = lookback_days
        self.veto_threshold = veto_threshold
        self._items: dict[str, deque] = defaultdict(lambda: deque(maxlen=50))

    def update(self, event: dict) -> Optional[float]:
        """Record one news_flash event; returns its score (None if unusable)."""
        data = (event or {}).get("data") or {}
        ticker = data.get("ticker")
        day = _day(event.get("simulated_date") or data.get("date"))
        if not ticker or day is None:
            return None
        score = score_text(f"{data.get('headline') or ''}. {data.get('description') or ''}")
        self._items[ticker].append((day, score))
        return score

    def recent_score(self, ticker: str, on_date) -> float:
        day = _day(on_date)
        if day is None:
            return 0.0
        return sum(s for d, s in self._items.get(ticker, ())
                   if 0 <= (day - d).days <= self.lookback_days)

    def veto_buy(self, ticker: str, on_date) -> bool:
        return self.recent_score(ticker, on_date) <= self.veto_threshold

    def reset(self, ticker: str) -> None:
        self._items.pop(ticker, None)
