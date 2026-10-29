def normalize_tick(event: dict) -> dict:
    data = event.get("data") or {}
    return {
        "event_type": event.get("event_type") or event.get("event"),
        "timestamp": event.get("timestamp"),
        "simulated_date": event.get("simulated_date"),
        "ticker": data.get("ticker"),
        "close": data.get("close"),
        "open": data.get("open"),
        "high": data.get("high"),
        "low": data.get("low"),
        "volume": data.get("volume"),
    }
