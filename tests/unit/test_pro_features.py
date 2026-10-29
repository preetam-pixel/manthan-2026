import os

import pytest

from src.app import Bot, consume_forever
from src.execution.client import OrderResult
from src.journal import DecisionJournal
from src.strategy.registry import DEFAULT, create
from src.strategy.sma import SMAStrategy, sma_pro


class FakeAPI:
    def __init__(self, stage=("development", "running"), order=None, holdings=None):
        self.stage = stage
        self.order = order
        self.orders, self.portfolio_calls = [], 0
        self.portfolio = {"holdings": holdings or [], "available_cash": 1_000_000.0}

    def acknowledge_preflight(self, seq):
        pass

    def get_stocks(self):
        return ["AAA", "BBB"]

    def get_stage(self):
        return {"stage": self.stage[0], "status": self.stage[1]}

    def get_portfolio(self):
        self.portfolio_calls += 1
        return self.portfolio

    def get_history(self, ticker, days):
        return {"prices": [{"date": f"2026-01-{i:02d}", "close": 100.0} for i in range(1, 11)]}

    def submit_order(self, ticker, action, qty, date=None):
        self.orders.append((ticker, action, qty, date))
        return self.order or OrderResult("FILLED", body={"execution_price": None})


def tick(ticker, close, date):
    return {"event_type": "price_tick", "timestamp": "2026-10-19T10:00:00.000Z", "simulated_date": date,
            "data": {"ticker": ticker, "close": close}}


def bot_with(strategy=None, api=None, clock=lambda: 0.0, **kw):
    api = api or FakeAPI()
    bot = Bot(api, strategy=strategy, log=lambda *a: None, clock=clock, **kw)
    bot.startup()
    return bot, api


# ---- strategy defaults and risk cap ------------------------------------------
def test_default_strategy_is_sma_pro_and_original_is_unchanged():
    assert DEFAULT == "sma_pro"
    pro, base = create("sma_pro"), create("sma_band")
    assert (pro.notional, pro.max_position_value, pro.tax_harvest) == (75_000, 150_000, True)
    assert (base.n, base.band, base.notional, base.max_position_value) == (8, 0.015, 50_000, 100_000)
    assert not getattr(base, "tax_harvest", False)


def test_risk_cap_follows_the_active_strategy():
    bot, _ = bot_with(sma_pro())
    assert bot.risk.max_pos_value == 150_000
    bot2, _ = bot_with(SMAStrategy())
    assert bot2.risk.max_pos_value == 100_000


def test_sma_pro_buys_bigger_and_cap_is_enforced():
    bot, api = bot_with(sma_pro())
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    assert api.orders[0][:3] == ("AAA", "BUY", int(75_000 // 103.0))


# ---- tax book and journal -------------------------------------------------------
def test_fills_feed_tax_book_and_journal_explains_each_trade():
    bot, api = bot_with(SMAStrategy())
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))      # BUY
    qty = api.orders[0][2]
    assert bot.tax.quantity("AAA") == qty
    bot.handle_message("market.ticks", tick("AAA", 90.0, "2026-01-12"))       # SELL below band
    assert api.orders[-1][1] == "SELL" and bot.tax.quantity("AAA") == 0
    entries = bot.journal.recent()
    sell, buy = entries[0], entries[1]
    assert buy["action"] == "BUY" and buy["risk_approved"] is True and buy["outcome"] == "FILLED"
    assert "SMA8" in buy["reason"] and buy["fill_price"] == 103.0
    assert sell["realized_gain"] < 0 and sell["tax_term"] == "ST"
    assert bot.tax.summary()["realized_gain"] == pytest.approx(sell["realized_gain"])


def test_journal_records_blocked_decisions_too():
    bot, api = bot_with(SMAStrategy(), api=FakeAPI(stage=("preflight", "running")))
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    e = bot.journal.recent()[0]
    assert e["risk_approved"] is False and "not running" in e["risk_reason"] and e["outcome"] is None
    assert api.orders == []


def test_journal_file_and_csv(tmp_path):
    path = os.path.join(str(tmp_path), "logs", "d.jsonl")
    j = DecisionJournal(path)
    j.record({"ticker": "AAA", "action": "BUY", "outcome": "FILLED", "risk_approved": True})
    j.record({"ticker": "AAA", "action": "SELL", "outcome": "REJECTED", "risk_approved": True})
    assert open(path, encoding="utf-8").read().count("\n") == 2
    csv = j.to_csv()
    assert csv.splitlines()[0].startswith("time,simulated_date,ticker") and "BUY" in csv.splitlines()[1]
    assert j.stats() == {"decisions": 2, "orders": 2, "filled": 1, "rejected": 1, "blocked": 0}


def test_news_context_recorded_with_decision():
    bot, api = bot_with(SMAStrategy())
    bot.handle_message("market.news", {"event_type": "news_flash", "simulated_date": "2026-01-11",
                                       "data": {"ticker": "AAA", "headline": "Fraud probe widens",
                                                "description": "lawsuit filed"}})
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    assert bot.journal.recent()[0]["news_score"] <= -2           # context only: the order still went out
    assert api.orders


def test_existing_holdings_are_aligned_into_tax_lots():
    api = FakeAPI(holdings=[{"ticker": "BBB", "quantity": 40}])
    bot, _ = bot_with(SMAStrategy(), api=api)
    bot.handle_message("market.ticks", tick("BBB", 100.0, "2026-01-11"))
    assert bot.tax.quantity("BBB") == 40


# ---- tax-loss harvesting in the live bot ------------------------------------------
def test_live_bot_harvests_a_loss_before_31_march_when_it_saves_tax():
    bot, api = bot_with(sma_pro())
    bot.tax.buy("WIN", 100, 100.0, "2025-05-01"); bot.tax.sell("WIN", 100, 900.0, "2025-12-01")
    api.portfolio = {"holdings": [{"ticker": "AAA", "quantity": 500}], "available_cash": 900_000.0}
    bot.sync_portfolio()
    bot.tax.buy("AAA", 500, 120.0, "2026-01-05")
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-03-25"))    # strategy is silent
    sells = [o for o in api.orders if o[1] == "SELL"]
    assert sells and sells[0][:3] == ("AAA", "SELL", 500)
    assert "tax-loss harvest" in bot.journal.recent()[0]["reason"]


def test_original_strategy_never_harvests():
    bot, api = bot_with(SMAStrategy())
    bot.tax.buy("WIN", 100, 100.0, "2025-05-01"); bot.tax.sell("WIN", 100, 900.0, "2025-12-01")
    api.portfolio = {"holdings": [{"ticker": "AAA", "quantity": 500}], "available_cash": 900_000.0}
    bot.sync_portfolio()
    bot.tax.buy("AAA", 500, 120.0, "2026-01-05")
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-03-25"))
    assert [o for o in api.orders if o[1] == "SELL"] == []


# ---- exchange-truth resync and Kafka resilience -------------------------------------
def test_portfolio_resynced_from_exchange_periodically():
    from src.app import RESYNC_S
    now = [0.0]
    bot, api = bot_with(SMAStrategy(), clock=lambda: now[0])
    calls = api.portfolio_calls
    now[0] = RESYNC_S / 2
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-01-11"))
    assert api.portfolio_calls == calls
    now[0] = RESYNC_S + 1
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-01-12"))
    assert api.portfolio_calls == calls + 1
    assert RESYNC_S <= 15                     # dashboard stays within 15 s of the portal


def test_portfolio_reread_shortly_after_a_fill():
    from src.app import SETTLE_RESYNC_S, RESYNC_S
    now = [0.0]
    bot, api = bot_with(SMAStrategy(), clock=lambda: now[0])
    now[0] = 1.0
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))      # BUY fills
    calls = api.portfolio_calls
    now[0] = 1.0 + SETTLE_RESYNC_S / 2
    bot.handle_message("market.news", {"event_type": "news_flash", "data": {}})
    assert api.portfolio_calls == calls                                        # rest of the burst first
    now[0] = 1.0 + SETTLE_RESYNC_S
    bot.handle_message("market.news", {"event_type": "news_flash", "data": {}})
    assert api.portfolio_calls == calls + 1
    now[0] = 1.0 + SETTLE_RESYNC_S + 1
    bot.handle_message("market.news", {"event_type": "news_flash", "data": {}})
    assert api.portfolio_calls == calls + 1 and SETTLE_RESYNC_S < RESYNC_S      # once per fill burst


def test_idle_timer_rereads_the_exchange_after_fills_without_waiting_for_a_message():
    from src.app import SETTLE_RESYNC_S
    now = [0.0]
    bot, api = bot_with(SMAStrategy(), clock=lambda: now[0])
    now[0] = 1.0
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))      # BUY fills
    calls = api.portfolio_calls
    bot.resync_if_due()
    assert api.portfolio_calls == calls                                        # too soon
    now[0] = 1.0 + SETTLE_RESYNC_S
    bot.resync_if_due()                                                        # quiet gap: no message needed
    assert api.portfolio_calls == calls + 1
    bot.resync_if_due()
    assert api.portfolio_calls == calls + 1


class Msg:
    def __init__(self, topic, value):
        self.topic, self.value = topic, value


class FlakyConsumer:
    """First connection fails mid-stream, second delivers the rest."""
    def __init__(self, items, fail_after=None):
        self.items, self.fail_after, self.closed = items, fail_after, False

    def __iter__(self):
        for i, item in enumerate(self.items):
            if self.fail_after is not None and i == self.fail_after:
                raise ConnectionError("broker went away")
            yield item

    def close(self):
        self.closed = True


def test_consume_forever_reconnects_after_broker_failure_and_keeps_state():
    bot, api = bot_with(SMAStrategy())
    made, sleeps = [], []
    batches = [
        FlakyConsumer([Msg("market.ticks", tick("AAA", 103.0, "2026-01-11"))] * 2, fail_after=1),
        FlakyConsumer([Msg("market.ticks", tick("AAA", 90.0, "2026-01-12"))]),
    ]

    def make():
        if not batches:
            raise KeyboardInterrupt                          # end of test
        c = batches.pop(0)
        made.append(c)
        return c

    with pytest.raises(KeyboardInterrupt):
        consume_forever(bot, make, sleep=sleeps.append)
    assert len(made) == 2 and all(c.closed for c in made)
    assert sleeps == [1.0]                                  # backed off once, then reconnected
    assert [o[1] for o in api.orders] == ["BUY", "SELL"]    # position state survived the reconnect


def test_consume_forever_backoff_is_capped():
    bot, _ = bot_with(SMAStrategy())
    sleeps = []
    attempts = iter(range(10))

    def make():
        if next(attempts) >= 8:
            raise KeyboardInterrupt
        raise OSError("network unreachable")

    with pytest.raises(KeyboardInterrupt):
        consume_forever(bot, make, sleep=sleeps.append, max_backoff=15.0)
    assert sleeps[:5] == [1.0, 2.0, 4.0, 8.0, 15.0] and max(sleeps) == 15.0


# ---- one bot per computer ---------------------------------------------------------------
def test_second_instance_is_refused_until_the_first_exits():
    from src.app import acquire_single_instance
    first = acquire_single_instance(port=47999)
    assert first is not None
    try:
        assert acquire_single_instance(port=47999) is None
    finally:
        first.close()
    again = acquire_single_instance(port=47999)
    assert again is not None
    again.close()


def test_dashboard_port_cannot_be_shared():
    from src.dashboard.server import DashboardServer
    from src.dashboard.state import DashboardState
    bot, _ = bot_with(SMAStrategy())
    a = DashboardServer(bot, DashboardState(), ".", port=0).start()
    try:
        with pytest.raises(OSError):
            DashboardServer(bot, DashboardState(), ".", port=a.port)
    finally:
        a.stop()


def test_exchange_cost_basis_used_for_existing_holdings():
    api = FakeAPI(holdings=[{"ticker": "BBB", "quantity": 40, "avg_buy_price": 90.0, "is_short": False}])
    bot, _ = bot_with(SMAStrategy(), api=api)
    assert bot.portfolio.avg_price == {"BBB": 90.0}
    bot.handle_message("market.ticks", tick("BBB", 100.0, "2026-01-11"))
    assert bot.tax.avg_cost("BBB") == pytest.approx(90.0)


# ---- configurable position size ----------------------------------------------------------
def test_sizing_overrides_from_environment():
    from src.app import apply_sizing
    s = sma_pro()
    apply_sizing(s, {"TRADE_SIZE_INR": "75000", "MAX_POSITION_INR": "75000"})   # one buy per stock
    assert (s.notional, s.max_position_value) == (75_000, 75_000)
    bot, api = bot_with(s)
    assert bot.risk.max_pos_value == 75_000
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    bot.handle_message("market.ticks", tick("AAA", 104.0, "2026-01-12"))        # still above band
    assert [o[1] for o in api.orders] == ["BUY"]                                   # no second buy


def test_sizing_defaults_untouched_and_bad_values_rejected():
    from src.app import apply_sizing
    s = sma_pro()
    apply_sizing(s, {})
    assert (s.notional, s.max_position_value) == (75_000, 150_000)
    for bad in ({"TRADE_SIZE_INR": "abc"}, {"TRADE_SIZE_INR": "0"},
                {"TRADE_SIZE_INR": "80000", "MAX_POSITION_INR": "50000"}):
        with pytest.raises(ValueError):
            apply_sizing(sma_pro(), bad)


def test_exchange_reread_after_each_days_ticks_even_without_trades():
    from src.app import SETTLE_RESYNC_S
    now = [0.0]
    bot, api = bot_with(SMAStrategy(), clock=lambda: now[0], trading_enabled=False)
    now[0] = 1.0
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-01-11"))      # no trade: prices moved
    calls = api.portfolio_calls
    now[0] = 1.0 + SETTLE_RESYNC_S
    bot.resync_if_due()
    assert api.orders == [] and api.portfolio_calls == calls + 1


def test_failed_resync_backs_off_instead_of_retrying_every_second():
    from src.app import SYNC_RETRY_S
    now = [0.0]
    bot, api = bot_with(SMAStrategy(), clock=lambda: now[0], trading_enabled=False)

    def down():
        api.portfolio_calls += 1
        raise ConnectionError("host unreachable")
    api.get_portfolio = down
    now[0] = 1.0
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2026-01-11"))
    now[0] = 4.0
    bot.resync_if_due()                                    # attempt 1 fails
    calls = api.portfolio_calls
    for step in range(1, int(SYNC_RETRY_S)):
        now[0] = 4.0 + step
        bot.resync_if_due()
    assert api.portfolio_calls == calls                    # no retries while backing off
    now[0] = 4.0 + SYNC_RETRY_S
    bot.resync_if_due()
    assert api.portfolio_calls == calls + 1
