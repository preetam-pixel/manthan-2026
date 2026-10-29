from src.features.build import sma
from src.market_data.consumer import (is_preflight, is_price_tick, normalize_tick,
                                      preflight_seq)
from src.news.consumer import format_news, keyword_counts

TICK = {"event_type": "price_tick", "timestamp": "t", "simulated_date": "2026-01-01",
        "data": {"ticker": "ABC", "open": 1, "high": 3, "low": 1, "close": 2, "volume": 9}}


def test_normalize_tick():
    n = normalize_tick(TICK)
    assert n["ticker"] == "ABC" and n["close"] == 2 and n["simulated_date"] == "2026-01-01"


def test_normalize_tick_legacy_event_key_and_missing_data():
    n = normalize_tick({"event": "price_tick"})
    assert n["event_type"] == "price_tick" and n["ticker"] is None and n["close"] is None


def test_event_routing():
    assert is_price_tick("market.ticks", TICK)
    assert not is_price_tick("market.news", TICK)
    assert is_preflight({"event_type": "preflight_tick", "seq": 3})


def test_preflight_seq_fallback():
    assert preflight_seq({"seq": 4}) == 4
    assert preflight_seq({"data": {"status": "STANDBY", "seq": 5}}) == 5
    assert preflight_seq({}) is None


def test_keyword_counts_and_none_fields():
    assert keyword_counts({"headline": "Record profit", "description": "strong growth"}) == (4, 0)
    assert keyword_counts({"headline": "Fraud probe", "description": None}) == (0, 2)
    assert keyword_counts({}) == (0, 0)


def test_format_news():
    ev = {"data": {"ticker": "ABC", "headline": "Profit surge", "description": ""}}
    assert format_news(ev) == "NEWS ABC Profit surge (+2/-0)"


def test_features_sma_warmup_and_window():
    assert sma([1, 2, 3], 8) is None
    assert sma(list(range(1, 11)), 8) == sum(range(3, 11)) / 8
