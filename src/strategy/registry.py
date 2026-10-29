"""Named strategies. `sma_pro` (SMA8 band, 1.5x size, tax-loss harvesting) is the default."""
from src.strategy import disciplined
from src.strategy.adaptive import AdaptiveStrategy
from src.strategy.sma import SMAStrategy, sma_news, sma_pro

DEFAULT = "sma_pro"     # chosen from the 500-day study; see docs/STRATEGY_EVAL.md
STRATEGIES = {
    "sma_pro": sma_pro,
    "sma_news": sma_news,
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
