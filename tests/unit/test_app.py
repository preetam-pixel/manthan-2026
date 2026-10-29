from src.execution.client import APIError, OrderResult
from src.app import Bot


class FakeAPI:
    def __init__(self, stage=("simulation", "RUNNING"), order=None):
        self.stage = stage
        self.order = order or OrderResult("FILLED", body={"execution_price": 102.0})
        self.heartbeats, self.orders, self.history_calls = [], [], []
        self.portfolio = {"holdings": [], "cash": 1_000_000.0}
        self.fail_heartbeat = False
        self.fail_portfolio = False

    def acknowledge_preflight(self, seq):
        if self.fail_heartbeat:
            raise APIError("bad seq")
        self.heartbeats.append(seq)

    def get_stocks(self):
        return ["AAA", "BBB"]

    def get_stage(self):
        return {"stage": self.stage[0], "status": self.stage[1]}

    def get_portfolio(self):
        if self.fail_portfolio:
            raise APIError("down")
        return self.portfolio

    def get_history(self, ticker, days):
        self.history_calls.append(ticker)
        return {"prices": [{"date": f"2021-01-{i:02d}", "close": 100.0} for i in range(1, 11)]}

    def submit_order(self, ticker, action, qty, date=None):
        self.orders.append((ticker, action, qty, date))
        return self.order


def tick(ticker, close, date):
    return {"event_type": "price_tick", "timestamp": "2026-10-19T10:00:00.000Z",
            "simulated_date": date, "data": {"ticker": ticker, "close": close}}


def make_bot(api=None, **kw):
    api = api or FakeAPI()
    logs = []
    bot = Bot(api, log=lambda *a: logs.append(" ".join(map(str, a))), clock=lambda: 0.0, **kw)
    bot.api_logs = logs
    return bot, api


def started(api=None, **kw):
    bot, api = make_bot(api, **kw)
    bot.handle_message("market.ticks", {"event_type": "preflight_tick", "seq": 1, "data": {"seq": 1}})
    return bot, api


def test_preflight_acks_exact_seq_loads_universe_and_syncs():
    bot, api = started()
    assert api.heartbeats == [1]
    assert bot.universe == {"AAA", "BBB"} and bot.portfolio.synced


def test_heartbeat_error_does_not_crash_and_still_loads_universe():
    api = FakeAPI()
    api.fail_heartbeat = True
    bot, _ = started(api)
    assert api.heartbeats == [] and bot.universe


def test_preflight_without_seq_is_ignored_safely():
    bot, api = make_bot()
    bot.handle_message("market.ticks", {"event_type": "preflight_tick"})
    assert api.heartbeats == []


def test_warm_start_allows_first_signal_without_eight_live_ticks():
    bot, api = started()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders and api.orders[0][:2] == ("AAA", "BUY")
    assert api.orders[0][3] == "2021-02-01"       # date passed for latency measurement
    assert bot.portfolio.quantity("AAA") == int(50_000 // 103.0)


def test_cold_start_needs_eight_ticks():
    bot, api = started(warm_start=False)
    for i in range(8):
        bot.handle_message("market.ticks", tick("AAA", 100.0, f"2021-01-{i + 1:02d}"))
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert len(api.orders) == 1


def test_sell_after_buy_closes_whole_position():
    bot, api = started()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    bot.handle_message("market.ticks", tick("AAA", 80.0, "2021-02-02"))
    assert api.orders[-1][1] == "SELL" and bot.portfolio.quantity("AAA") == 0


def test_duplicate_tick_delivery_ignored():
    bot, api = started()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert len(api.orders) == 1


def test_simulation_paused_or_completed_blocks_orders():
    for status in ("PAUSED", "COMPLETED", "IDLE"):
        bot, api = started(FakeAPI(stage=("simulation", status)))
        bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
        assert api.orders == [], status


def test_not_simulation_stage_blocks_orders():
    bot, api = started(FakeAPI(stage=("preflight", "RUNNING")))
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders == []


def test_stage_error_blocks_orders():
    api = FakeAPI()
    api.get_stage = lambda: (_ for _ in ()).throw(APIError("down"))
    bot, _ = started(api)
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders == []


def test_stale_tick_blocks_order():
    now = [0.0]
    api = FakeAPI()
    bot = Bot(api, log=lambda *a: None, clock=lambda: now[0])
    bot.handle_message("market.ticks", {"event_type": "preflight_tick", "seq": 1})
    now[0] = 10.0
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"), received_at=0.0)
    assert api.orders == []


def test_unsynced_portfolio_blocks_orders():
    api = FakeAPI()
    api.fail_portfolio = True
    bot, _ = started(api)
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders == []


def test_timeout_is_reconciled_and_not_retried_same_day():
    api = FakeAPI(order=OrderResult("UNCERTAIN", detail="timeout"))
    bot, _ = started(api)
    api.portfolio = {"holdings": [{"ticker": "AAA", "quantity": 485}], "cash": 1.0}
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert len(api.orders) == 1
    assert bot.portfolio.quantity("AAA") == 485          # exchange state adopted
    assert not bot.portfolio.uncertain
    bot.handle_message("market.ticks", tick("AAA", 103.5, "2021-02-01"))
    assert len(api.orders) == 1


def test_uncertain_stays_blocked_until_reconcile_succeeds():
    api = FakeAPI(order=OrderResult("UNCERTAIN"))
    bot, _ = started(api)
    api.fail_portfolio = True
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert "AAA" in bot.portfolio.uncertain
    bot.handle_message("market.ticks", tick("AAA", 110.0, "2021-02-02"))
    assert len(api.orders) == 1                          # still blocked
    api.fail_portfolio = False
    bot.handle_message("market.ticks", tick("AAA", 115.0, "2021-02-03"))
    assert not bot.portfolio.uncertain


def test_rejection_does_not_change_holdings():
    api = FakeAPI(order=OrderResult("REJECTED", code="INSUFFICIENT_CAPITAL"))
    bot, _ = started(api)
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert bot.portfolio.quantity("AAA") == 0


def test_simulation_not_running_rejection_halts():
    api = FakeAPI(order=OrderResult("REJECTED", code="SIMULATION_NOT_RUNNING"))
    bot, _ = started(api)
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert bot.sim_running is False


def test_malformed_events_do_not_crash():
    bot, api = started()
    for ev in (None, [], "x", {}, {"event_type": "price_tick"},
               tick("AAA", None, "d"), tick(None, 1, "d"), tick("AAA", "abc", "d")):
        bot.handle_message("market.ticks", ev)
    assert api.orders == []


def test_news_is_logged_never_traded():
    bot, api = started()
    bot.handle_message("market.news", {"event_type": "news_flash", "data": {
        "ticker": "AAA", "headline": "Record profit surge", "description": "strong growth"}})
    assert api.orders == []
    assert any("NEWS AAA" in line for line in bot.api_logs)


def test_date_going_backwards_resets_ticker_history():
    bot, api = started()
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2021-06-01"))
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2021-01-01"))   # sandbox looped
    assert len(bot.strategy.closes["AAA"]) == 1
