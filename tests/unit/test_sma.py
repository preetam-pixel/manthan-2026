from datetime import datetime, timezone
from src.strategy.sma import SMAStrategy

def test_sma_warmup_and_flat_series():
    strat = SMAStrategy()
    now = datetime.now(timezone.utc)
    for _ in range(8):
        assert strat.on_close("TEST", 100.0, 0, now) is None
    assert strat.on_close("TEST", 100.0, 0, now) is None
