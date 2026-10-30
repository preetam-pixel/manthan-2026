import pytest

from src.strategy.backtest import replay


def make_rows(closes, ticker="TEST"):
    return [{"date": f"2026-01-{i + 1:02d}", "ticker": ticker, "close": c}
            for i, c in enumerate(closes)]


FLAT_THEN_JUMP_THEN_DROP = [100.0] * 8 + [102.0] + [100.0] * 7 + [95.0]


def test_replay_is_deterministic():
    rows = make_rows(FLAT_THEN_JUMP_THEN_DROP)
    assert replay(rows) == replay(rows)


def test_replay_buys_then_sells_with_brokerage():
    res = replay(make_rows(FLAT_THEN_JUMP_THEN_DROP))
    actions = [t[2] for t in res["trade_log"]]
    assert actions[0] == "BUY" and "SELL" in actions
    assert res["open_positions"] == {}
    # round trip: bought at 102, sold at 95, two brokerage charges + DP charge on the sell
    qty = res["trade_log"][0][3]
    assert res["final_equity"] == pytest.approx(1_000_000 + qty * (95 - 102) - 40 - 15.34)


def test_no_trades_on_flat_series():
    res = replay(make_rows([100.0] * 20))
    assert res["trades"] == 0 and res["return_pct"] == 0


def test_invalid_prices_skipped_not_zeroed():
    rows = make_rows([100.0] * 8) + [{"date": "2026-01-09", "ticker": "TEST", "close": None},
                                     {"date": "2026-01-10", "ticker": "TEST", "close": 0}]
    assert replay(rows)["trades"] == 0


def test_out_of_order_rows_rejected():
    rows = make_rows([100.0, 101.0])[::-1]
    with pytest.raises(ValueError):
        replay(rows)


def test_utilization_reported():
    res = replay(make_rows(FLAT_THEN_JUMP_THEN_DROP))
    assert 0 < res["avg_utilization_pct"] < 20
    assert replay(make_rows([100.0] * 20))["avg_utilization_pct"] == 0
