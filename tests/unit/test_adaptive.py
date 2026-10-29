from datetime import datetime, timezone

import pytest

from src.features.build import atr, pct_change, rsi, volume_ratio
from src.strategy.adaptive import MIN_BARS, AdaptiveStrategy
from src.strategy.backtest import compare, replay
from src.strategy.registry import create
from src.strategy.sma import SMAStrategy

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def bar(close=100.0, high=None, low=None, volume=1000.0):
    return {"open": close, "high": high if high is not None else close + 1,
            "low": low if low is not None else close - 1, "close": close, "volume": volume}


def warmed(n=MIN_BARS + 5, ticker="T", **kw):
    s = AdaptiveStrategy()
    s.warm_start_bars(ticker, [bar(**kw) for _ in range(n)])
    return s


# ---- features -----------------------------------------------------
def test_atr_constant_range_and_warmup():
    bars = [bar() for _ in range(15)]
    assert atr(bars, 14) == pytest.approx(2.0)
    assert atr(bars[:10], 14) is None


def test_atr_uses_gap_from_previous_close():
    bars = [bar(100.0), {"open": 110, "high": 111, "low": 110, "close": 110.5, "volume": 1}]
    assert atr(bars, 1) == pytest.approx(11.0)       # |high - prev close| = 11


def test_rsi_extremes_and_warmup():
    assert rsi(list(range(1, 20)), 14) == 100.0
    assert rsi(list(range(20, 1, -1)), 14) == pytest.approx(0.0)
    assert rsi([1, 2], 14) is None


def test_volume_ratio_and_missing():
    assert volume_ratio([100] * 20, 200) == pytest.approx(2.0)
    assert volume_ratio([100] * 2, 200) is None
    assert volume_ratio([100] * 20, None) is None


def test_pct_change():
    assert pct_change([100, 110], 1) == pytest.approx(0.10)
    assert pct_change([100], 1) is None


# ---- strategy -----------------------------------------------------
def test_buy_on_volume_confirmed_breakout_with_explainable_reason():
    s = warmed()
    sig = s.on_bar("T", bar(105.0, high=105.5, low=100.0, volume=2000.0), 0, NOW)
    assert sig.action == "BUY" and sig.quantity == int(50_000 // 105.0)
    assert "vol x2.0" in sig.reason and "SMA8" in sig.reason


def test_no_buy_without_volume_confirmation():
    s = warmed()
    assert s.on_bar("T", bar(105.0, volume=500.0), 0, NOW) is None


def test_no_signal_during_warmup():
    s = AdaptiveStrategy()
    s.warm_start_bars("T", [bar() for _ in range(MIN_BARS - 1)])
    assert s.on_bar("T", bar(110.0, volume=5000.0), 0, NOW) is None


def test_chaotic_regime_abstains():
    s = AdaptiveStrategy()
    s.warm_start_bars("T", [bar(100.0, high=112.0, low=88.0) for _ in range(MIN_BARS + 5)])  # ATR% ~ 24%
    assert s.on_bar("T", bar(140.0, volume=9000.0), 0, NOW) is None


def test_weak_breadth_vetoes_buy():
    s = warmed()
    s.state = {"A": (90.0, 100.0), "B": (90.0, 100.0), "C": (90.0, 100.0)}
    assert s.on_bar("T", bar(105.0, volume=2000.0), 0, NOW) is None


def test_position_cap_blocks_buy():
    s = warmed()
    assert s.on_bar("T", bar(105.0, volume=2000.0), 900, NOW) is None


def test_sell_entire_position_below_band_and_never_short():
    s = warmed()
    sig = s.on_bar("T", bar(95.0, volume=1000.0), 300, NOW)
    assert sig.action == "SELL" and sig.quantity == 300
    s2 = warmed()
    assert s2.on_bar("T", bar(80.0), 0, NOW) is None


def test_trailing_stop_exits_before_band_break():
    s = warmed()
    s.on_bar("T", bar(104.0, high=104.5, low=103.0, volume=1000.0), 500, NOW)   # capped, tracks peak
    s.on_bar("T", bar(105.0, high=105.5, low=104.0, volume=1000.0), 500, NOW)
    sig = s.on_bar("T", bar(100.5, high=102.0, low=100.0, volume=1000.0), 500, NOW)
    assert sig is not None and sig.action == "SELL" and "trailing" in sig.reason


def test_higher_volatility_means_smaller_size():
    calm = warmed()
    wild = AdaptiveStrategy()
    wild.warm_start_bars("T", [bar(100.0, high=102.5, low=97.5) for _ in range(MIN_BARS + 5)])
    a = calm.on_bar("T", bar(105.0, volume=2000.0), 0, NOW)
    b = wild.on_bar("T", bar(112.0, high=113.0, low=105.0, volume=2000.0), 0, NOW)
    assert a is not None and b is not None and b.quantity * 112.0 < a.quantity * 105.0


def test_invalid_bars_ignored_and_decision_precedes_append():
    s = warmed()
    assert s.on_bar("T", {"close": None}, 0, NOW) is None
    n = len(s.bars["T"])
    s.on_bar("T", bar(100.0), 0, NOW)
    assert len(s.bars["T"]) == n + 1


def test_reset_clears_ticker():
    s = warmed()
    s.reset("T")
    assert "T" not in s.bars and "T" not in s.state


def test_registry():
    assert isinstance(create(), SMAStrategy) and isinstance(create("adaptive"), AdaptiveStrategy)
    with pytest.raises(ValueError):
        create("nope")


# ---- backtest comparison -------------------------------------------
def rows_series():
    rows = []
    for i in range(25):
        rows.append({"date": f"2026-01-{i + 1:02d}", "ticker": "T", "open": 100.0, "high": 101.0,
                     "low": 99.0, "close": 100.0, "volume": 1000.0})
    rows.append({"date": "2026-01-26", "ticker": "T", "open": 100.0, "high": 106.0, "low": 100.0,
                 "close": 105.0, "volume": 3000.0})
    rows.append({"date": "2026-01-27", "ticker": "T", "open": 105.0, "high": 105.0, "low": 94.0,
                 "close": 95.0, "volume": 3000.0})
    return rows


def test_compare_runs_both_strategies_with_fees():
    res = compare(rows_series(), {"sma_band": SMAStrategy, "adaptive": AdaptiveStrategy})
    assert set(res) == {"sma_band", "adaptive"}
    for r in res.values():
        assert r["trades"] >= 2 and r["fees_paid"] == pytest.approx(55.34)
    assert replay(rows_series(), strategy_factory=AdaptiveStrategy) == \
        replay(rows_series(), strategy_factory=AdaptiveStrategy)
