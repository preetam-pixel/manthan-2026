"""News handling. Keyword scores are informational only; they never drive trades."""
POS_WORDS = ("beat", "record", "growth", "surge", "upgrade", "profit", "wins", "expands", "raises", "strong")
NEG_WORDS = ("miss", "loss", "plunge", "downgrade", "probe", "lawsuit", "recall", "cuts", "weak", "fraud", "bankruptcy")


def keyword_counts(event_data: dict) -> tuple[int, int]:
    text = f"{event_data.get('headline') or ''} {event_data.get('description') or ''}".lower()
    return sum(w in text for w in POS_WORDS), sum(w in text for w in NEG_WORDS)


def format_news(event: dict) -> str:
    """Log line matching the original bot's NEWS output."""
    data = event.get("data") or {}
    pos, neg = keyword_counts(data)
    return f"NEWS {data.get('ticker')} {data.get('headline')} (+{pos}/-{neg})"
