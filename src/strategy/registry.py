"""Named strategies. SMA8 band is the default; others are opt-in."""
from src.strategy.adaptive import AdaptiveStrategy
from src.strategy.sma import SMAStrategy

DEFAULT = "sma_band"
STRATEGIES = {
    "sma_band": SMAStrategy,
    "adaptive": AdaptiveStrategy,
}


def create(name: str = DEFAULT):
    try:
        return STRATEGIES[name]()
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose one of {sorted(STRATEGIES)}") from None
