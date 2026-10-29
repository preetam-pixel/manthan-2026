from datetime import datetime, timezone

from src.contracts import Signal
from src.portfolio.state import PortfolioState
from src.risk.manager import RiskManager

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def sig(action="BUY", qty=10, ticker="AAA"):
    return Signal(ticker, action, qty, NOW, "t")


def pf(held=None, cash=1_000_000.0):
    p = PortfolioState()
    p.sync({"holdings": [{"ticker": t, "quantity": q} for t, q in (held or {}).items()], "cash": cash})
    return p


def check(signal=None, price=100.0, age=0.1, date="d1", universe={"AAA"}, portfolio=None, running=True):
    return RiskManager().evaluate(signal or sig(), price, age, date, universe,
                                  portfolio or pf(), running)


def test_valid_buy_and_sell():
    assert check().approved
    assert check(sig("SELL", 5), portfolio=pf({"AAA": 10})).approved


def test_simulation_not_running_blocks():
    assert "not running" in check(running=False).reason


def test_short_and_cover_rejected():
    for a in ("SHORT", "COVER"):
        assert not check(Signal("AAA", a, 1, NOW, "t")).approved


def test_bad_quantity():
    for q in (0, -1, 1.5, True, 2_000_000):
        assert not check(Signal("AAA", "BUY", q, NOW, "t")).approved


def test_ticker_not_in_universe_or_universe_unknown():
    assert not check(universe={"BBB"}).approved
    assert not check(universe=None).approved


def test_missing_or_invalid_price_never_zero_filled():
    for p in (None, 0, -5, float("nan"), float("inf")):
        assert not check(price=p).approved


def test_stale_data_blocks():
    assert "stale" in check(age=10).reason


def test_unsynced_portfolio_blocks():
    assert not check(portfolio=PortfolioState()).approved


def test_insufficient_cash_and_unknown_cash():
    assert "cash" in check(portfolio=pf(cash=500)).reason
    p = pf()
    p.cash = None                      # unknown cash is not treated as zero
    assert check(portfolio=p).approved


def test_position_cap():
    assert "cap" in check(sig("BUY", 10), price=100.0, portfolio=pf({"AAA": 995})).reason


def test_no_accidental_short_or_oversell():
    assert not check(sig("SELL", 1), portfolio=pf({})).approved
    assert not check(sig("SELL", 11), portfolio=pf({"AAA": 10})).approved


def test_short_holdings_map_to_zero():
    p = PortfolioState()
    p.sync({"holdings": [{"ticker": "AAA", "quantity": 50, "is_short": True}]})
    assert p.quantity("AAA") == 0


def test_duplicate_and_uncertain_block():
    p = pf()
    p.record_submitted(("AAA", "BUY", "d1"))
    assert "duplicate" in check(portfolio=p).reason
    assert check(date="d2", portfolio=p).approved
    p.mark_uncertain("AAA")
    assert "unresolved" in check(date="d2", portfolio=p).reason


def test_apply_fill_updates_holdings_and_cash():
    p = pf(cash=10_000)
    p.apply_fill("AAA", "BUY", 10, 100.0)
    assert p.quantity("AAA") == 10 and p.cash == 10_000 - 1000 - 20
    p.apply_fill("AAA", "SELL", 10, 110.0)
    assert p.quantity("AAA") == 0
