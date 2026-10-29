POS_WORDS = ("beat", "record", "growth", "surge", "upgrade", "profit", "wins", "expands", "raises", "strong")
NEG_WORDS = ("miss", "loss", "plunge", "downgrade", "probe", "lawsuit", "recall", "cuts", "weak", "fraud", "bankruptcy")

def keyword_counts(event_data: dict) -> tuple[int, int]:
    text = f"{event_data.get('headline', '')} {event_data.get('description', '')}".lower()
    return sum(w in text for w in POS_WORDS), sum(w in text for w in NEG_WORDS)
