import pytest

from src.tax.engine import TaxBook, fy_end, fy_of, to_date


def test_financial_year_boundaries():
    assert fy_of(to_date("2025-03-31")) == "FY2024-25"
    assert fy_of(to_date("2025-04-01")) == "FY2025-26"
    assert fy_end(to_date("2025-04-01")).isoformat() == "2026-03-31"
    assert fy_end(to_date("2026-02-10")).isoformat() == "2026-03-31"


def test_short_term_gain_includes_fees_and_fifo():
    b = TaxBook()
    b.buy("A", 100, 100.0, "2025-05-01")
    b.buy("A", 100, 110.0, "2025-05-10")
    r = b.sell("A", 150, 120.0, "2025-06-01")
    assert [x.qty for x in r] == [100, 50]                      # FIFO
    sell_fee = (20 + 15.34) / 150
    expected = 100 * (120 - sell_fee - (100 + 0.2)) + 50 * (120 - sell_fee - (110 + 0.2))
    assert sum(x.gain for x in r) == pytest.approx(expected)
    assert all(x.term == "ST" for x in r)
    assert b.quantity("A") == 50
    assert b.fy_summary("FY2025-26")["tax"] == pytest.approx(0.15 * expected)


def test_long_term_exemption_and_rate():
    b = TaxBook(brokerage=0, dp_charge=0)
    b.buy("A", 1000, 100.0, "2024-04-01")
    b.sell("A", 1000, 400.0, "2025-06-01")                    # 426 days -> LT, gain 3,00,000
    y = b.fy_summary("FY2025-26")
    assert y["ltcg"] == pytest.approx(300_000) and y["ltcg_exemption_used"] == pytest.approx(100_000)
    assert y["tax"] == pytest.approx(0.10 * 200_000)


def test_short_term_loss_offsets_stcg_then_ltcg():
    b = TaxBook(brokerage=0, dp_charge=0)
    b.buy("L", 100, 100.0, "2024-01-01"); b.sell("L", 100, 1600.0, "2025-05-01")   # LT gain 1,50,000
    b.buy("S", 100, 100.0, "2025-05-01"); b.sell("S", 100, 150.0, "2025-06-01")    # ST gain 5,000
    b.buy("X", 100, 1000.0, "2025-05-01"); b.sell("X", 100, 300.0, "2025-07-01")   # ST loss 70,000
    y = b.fy_summary("FY2025-26")
    assert y["taxable_st"] == 0
    assert y["taxable_lt"] == pytest.approx(150_000 - 65_000 - 85_000)            # exemption absorbs the rest
    assert y["tax"] == pytest.approx(0.0)


def test_long_term_loss_cannot_offset_short_term_gain():
    b = TaxBook(brokerage=0, dp_charge=0)
    b.buy("L", 100, 1000.0, "2024-01-01"); b.sell("L", 100, 500.0, "2025-05-01")   # LT loss 50,000
    b.buy("S", 100, 100.0, "2025-05-01"); b.sell("S", 100, 300.0, "2025-06-01")    # ST gain 20,000
    assert b.fy_summary("FY2025-26")["tax"] == pytest.approx(0.15 * 20_000)


def test_years_are_taxed_separately():
    b = TaxBook(brokerage=0, dp_charge=0)
    b.buy("A", 10, 100.0, "2025-03-01"); b.sell("A", 10, 200.0, "2025-03-20")      # FY24-25 gain 1,000
    b.buy("B", 10, 200.0, "2025-04-02"); b.sell("B", 10, 100.0, "2025-04-20")      # FY25-26 loss 1,000
    assert b.fy_summary("FY2024-25")["tax"] == pytest.approx(150.0)
    assert b.total_tax() == pytest.approx(150.0)                                    # no carry back


def test_harvest_candidates_only_near_year_end_with_gains_to_offset():
    b = TaxBook()
    b.buy("WIN", 100, 100.0, "2025-04-10"); b.sell("WIN", 100, 400.0, "2025-12-01")   # big ST gain
    b.buy("LOSE", 200, 500.0, "2026-01-05")
    prices = {"LOSE": 420.0}
    assert b.harvest_candidates("2026-02-01", prices) == []                          # too early
    c = b.harvest_candidates("2026-03-25", prices)
    assert c and c[0][0] == "LOSE" and c[0][1] == 200 and c[0][3] > 0
    empty = TaxBook()
    empty.buy("LOSE", 200, 500.0, "2026-01-05")
    assert empty.harvest_candidates("2026-03-25", prices) == []                      # nothing to offset


def test_sync_quantity_adds_unknown_lots_and_trims():
    b = TaxBook()
    b.sync_quantity("A", 50, 100.0, "2025-05-01")
    assert b.quantity("A") == 50 and b.avg_cost("A") == pytest.approx(100.0)
    b.sync_quantity("A", 20, 100.0, "2025-05-02")
    assert b.quantity("A") == 20


def test_invalid_inputs_ignored():
    b = TaxBook()
    b.buy("A", 0, 100.0, "2025-05-01"); b.buy("A", 10, -1, "2025-05-01"); b.buy("A", 10, 1, "bad")
    assert b.quantity("A") == 0
    assert b.sell("A", 10, 100, "2025-05-01") == []           # nothing held: no realization
    assert b.sell("A", 0, 100, "2025-05-01") == [] and b.realized == []
