"""Named strategies. SMA8 band is the default; others are opt-in."""
from src.strategy import disciplined
from src.strategy.adaptive import AdaptiveStrategy
from src.strategy.sma import SMAStrategy

DEFAULT = "sma_band"
STRATEGIES = {
    "sma_band": SMAStrategy,
    "adaptive": AdaptiveStrategy,
    "trend_pullback": disciplined.trend_pullback,
    "breakout": disciplined.breakout,
    "mean_reversion": disciplined.mean_reversion,
    "relative_strength": disciplined.relative_strength,
    "laggard_reversion": disciplined.laggard_reversion,
    "ensemble": disciplined.ensemble,
    "ensemble_scaled": disciplined.ensemble_scaled,
}


def create(name: str = DEFAULT):
    try:
        factory = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy {name!r}; choose one of {sorted(STRATEGIES)}") from None
    return factory()
