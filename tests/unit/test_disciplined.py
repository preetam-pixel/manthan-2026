from datetime import datetime, timezone

import pytest

from src.news.filter import NewsFilter, score_text
from src.strategy import disciplined as D
from src.strategy.backtest import replay
from src.strategy.registry import STRATEGIES, create

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def mk(date, close, high=None, low=None, volume=1000.0):
    return {"date": date, "open": close, "high": high or close + 1, "low": low or close - 1,
            "close": close, "volume": volume}


def day(i):
    return f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"


def warmed(strategy, n=45, price=100.0, tickers=("T",)):
    for t in tickers:
        strategy.warm_start_bars(t, [mk(day(i), price) for i in range(n)])
    return strategy


def history_rows(closes_by_ticker):
    rows = []
    for t, closes in closes_by_ticker.items():
        for i, c in enumerate(closes):
            rows.append({"ticker": t, **mk(day(i), c)})
    return sorted(rows, key=lambda r: (r["date"], r["ticker"]))


# ---- news filter ----------------------------------------------------
def test_news_scoring_severity_and_negation():
    assert score_text("Company faces fraud probe") <= -3
    assert score_text("Record profit and strong growth") >= 3
    assert score_text("Company denies fraud") > 0          # negator flips the severe term
    assert score_text("A lovely day out") == 0


def test_news_filter_vetoes_only_recent_negative_same_ticker():
    nf = NewsFilter()
    nf.update({"simulated_date": "2026-03-10", "data": {"ticker": "A", "headline": "Fraud probe opened",
                                                         "description": "lawsuit follows"}})
    assert nf.veto_buy("A", "2026-03-11")
    assert not nf.veto_buy("B", "2026-03-11")               # other ticker unaffected
    assert not nf.veto_buy("A", "2026-03-20")               # old news expires
    assert nf.update({"data": {}}) is None                  # unusable events ignored


def test_news_veto_blocks_a_buy_the_strategy_would_make():
    nf = NewsFilter()
    s = warmed(D.laggard_reversion(nf), tickers=("A", "B", "C", "D", "E", "F", "G", "H"))
    # make A the clear laggard
    s.warm_start_bars("A", [mk(day(i), 100.0 if i < 33 else 100.0 - (i - 33)) for i in range(45)])
    assert s.on_bar("A", mk(day(45), 85.0), 0, NOW) is not None
    s2 = warmed(D.laggard_reversion(nf), tickers=("A", "B", "C", "D", "E", "F", "G", "H"))
    s2.warm_start_bars("A", [mk(day(i), 100.0 if i < 33 else 100.0 - (i - 33)) for i in range(45)])
    nf.update({"simulated_date": day(45), "data": {"ticker": "A", "headline": "Fraud probe",
                                                    "description": "bankruptcy fears"}})
    assert s2.on_bar("A", mk(day(45), 85.0), 0, NOW) is None


# ---- discipline layer -------------------------------------------------
def test_no_signal_during_warmup():
    s = D.mean_reversion()
    s.warm_start_bars("T", [mk(day(i), 100.0) for i in range(D.MIN_BARS - 1)])
    assert s.on_bar("T", mk(day(41), 80.0), 0, NOW) is None


def test_hard_stop_exits_even_before_min_hold():
    s = warmed(D.trend_pullback())
    s.entry_t["T"] = s.t["T"]                                # just entered
    s.peak["T"] = 100.0
    sig = s.on_bar("T", mk(day(45), 80.0, high=81.0, low=79.0), 300, NOW)
    assert sig.action == "SELL" and sig.quantity == 300 and "trailing stop" in sig.reason


def test_never_emits_a_sell_when_flat():
    for name in ("trend_pullback", "mean_reversion", "laggard_reversion", "ensemble", "breakout", "relative_strength"):
        sig = create(name).on_bar("T", mk(day(45), 90.0), 0, NOW)
        assert sig is None or sig.action == "BUY", name


def test_max_positions_blocks_new_entry():
    s = warmed(D.mean_reversion(), tickers=("A", "B", "C", "D", "E", "F"))
    s.held_seen.update({"A": 10, "B": 10, "C": 10, "D": 10})
    s.warm_start_bars("E", [mk(day(i), 100.0 if i < 41 else 100.0 - 4 * (i - 40)) for i in range(45)])
    assert s.on_bar("E", mk(day(45), 78.0), 0, NOW) is None


def test_cooldown_blocks_immediate_reentry():
    s = warmed(D.mean_reversion())
    s.exit_t["T"] = s.t["T"] - 1
    s.warm_start_bars("T", [mk(day(i), 100.0 if i < 41 else 100.0 - 4 * (i - 40)) for i in range(45)])
    s.exit_t["T"] = s.t["T"] - 1
    assert s.on_bar("T", mk(day(45), 78.0), 0, NOW) is None


def test_chaotic_volatility_blocks_entries():
    s = D.mean_reversion()
    s.warm_start_bars("T", [mk(day(i), 100.0, high=115.0, low=85.0) for i in range(45)])
    assert s.on_bar("T", mk(day(45), 60.0, high=115.0, low=55.0), 0, NOW) is None


def test_mean_reversion_buys_oversold_dip_and_explains():
    s = D.mean_reversion()
    closes = [100.0] * 40 + [99.0, 98.0, 97.0, 95.0, 92.0]
    s.warm_start_bars("T", [mk(day(i), c) for i, c in enumerate(closes)])
    sig = s.on_bar("T", mk(day(45), 88.0), 0, NOW)
    assert sig is not None and sig.action == "BUY" and "oversold" in sig.reason
    assert 1 <= sig.quantity * 88.0 <= 100_000


def test_ensemble_needs_two_votes():
    s = D.ensemble()
    assert s.min_entry_votes == 2


def test_context_uses_only_prior_bars_no_lookahead():
    a, b = warmed(D.mean_reversion()), warmed(D.mean_reversion())
    sig_a = a.on_bar("T", mk(day(45), 100.0), 0, NOW)
    sig_b = b.on_bar("T", mk(day(45), 100.0), 0, NOW)
    assert sig_a == sig_b                                    # deterministic


def test_registry_lists_all_and_creates_each():
    for name in STRATEGIES:
        assert create(name) is not None
    assert {"mean_reversion", "trend_pullback", "laggard_reversion", "ensemble", "sma_band"} <= set(STRATEGIES)


def test_backtest_runs_every_strategy_deterministically():
    closes = {t: [100 + 5 * ((i * (k + 3)) % 7) - 2 * (i % 5) for i in range(90)] for k, t in enumerate("ABCDEFGHIJ")}
    rows = history_rows(closes)
    for name, f in STRATEGIES.items():
        r1 = replay(rows, strategy_factory=f)
        assert r1 == replay(rows, strategy_factory=f), name
        assert r1["final_equity"] > 0
