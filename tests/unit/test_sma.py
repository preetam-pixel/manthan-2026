from datetime import datetime, timezone

from src.strategy.sma import SMAStrategy, SMA_N

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def warm(strat, ticker="TEST", price=100.0):
    for _ in range(SMA_N):
        assert strat.on_close(ticker, price, 0, NOW) is None


def test_sma_warmup_and_flat_series():
    strat = SMAStrategy()
    warm(strat)
    assert strat.on_close("TEST", 100.0, 0, NOW) is None


def test_buy_above_band():
    strat = SMAStrategy()
    warm(strat)
    sig = strat.on_close("TEST", 102.0, 0, NOW)
    assert sig.action == "BUY" and sig.quantity == int(50_000 // 102.0)


def test_no_buy_inside_band():
    strat = SMAStrategy()
    warm(strat)
    assert strat.on_close("TEST", 101.4, 0, NOW) is None


def test_sell_entire_position_below_band():
    strat = SMAStrategy()
    warm(strat)
    sig = strat.on_close("TEST", 98.0, 300, NOW)
    assert sig.action == "SELL" and sig.quantity == 300


def test_no_short_when_flat():
    strat = SMAStrategy()
    warm(strat)
    assert strat.on_close("TEST", 90.0, 0, NOW) is None


def test_position_cap_blocks_buy():
    strat = SMAStrategy()
    warm(strat)
    # qty=490 at 102 -> (600+490)*102 > 100000
    assert strat.on_close("TEST", 102.0, 600, NOW) is None


def test_signal_uses_prior_closes_then_appends_current():
    strat = SMAStrategy()
    warm(strat)
    strat.on_close("TEST", 102.0, 10_000, NOW)  # capped, no signal, but appended
    assert list(strat.closes["TEST"])[-1] == 102.0
    assert len(strat.closes["TEST"]) == SMA_N


def test_tickers_are_independent():
    strat = SMAStrategy()
    warm(strat, "AAA")
    assert strat.on_close("BBB", 150.0, 0, NOW) is None  # BBB still warming up
    assert strat.on_close("AAA", 102.0, 0, NOW).ticker == "AAA"


def test_missing_close_or_ticker_ignored():
    strat = SMAStrategy()
    assert strat.on_close("TEST", None, 0, NOW) is None
    assert strat.on_close(None, 100.0, 0, NOW) is None
    assert len(strat.closes) == 0


def test_expensive_stock_quantity_floor_of_one_respects_cap():
    strat = SMAStrategy()
    warm(strat, price=100_000.0)
    # qty floors to 1 -> 110000 > MAX_POS_VALUE, so no BUY
    assert strat.on_close("TEST", 110_000.0, 0, NOW) is None
