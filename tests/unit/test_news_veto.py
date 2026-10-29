"""sma_news: BUYs wait for the day's headlines and are skipped on bad news; sells never wait."""
from src.app import Bot
from src.execution.client import OrderResult
from src.strategy.registry import create
from src.strategy.sma import NEWS_WAIT_S


class FakeAPI:
    def __init__(self, holdings=None):
        self.orders = []
        self.portfolio = {"holdings": holdings or [], "available_cash": 1_000_000.0}

    def acknowledge_preflight(self, seq):
        pass

    def get_stocks(self):
        return ["AAA", "BBB"]

    def get_stage(self):
        return {"stage": "development", "status": "running"}

    def get_portfolio(self):
        return self.portfolio

    def get_history(self, ticker, days):
        return {"prices": [{"date": f"2026-01-{i:02d}", "close": 100.0} for i in range(1, 11)]}

    def submit_order(self, ticker, action, qty, date=None):
        self.orders.append((ticker, action, qty, date))
        return OrderResult("FILLED", body={"execution_price": None})


def tick(ticker, close, date):
    return {"event_type": "price_tick", "timestamp": f"{date}T10:00:00Z", "simulated_date": date,
            "data": {"ticker": ticker, "close": close}}


def headline(ticker, date, text):
    return {"event_type": "news_flash", "simulated_date": date,
            "data": {"ticker": ticker, "headline": text, "description": ""}}


def rig(strategy="sma_news", holdings=None):
    now = [0.0]
    api = FakeAPI(holdings)
    bot = Bot(api, strategy=create(strategy), log=lambda *a: None, clock=lambda: now[0], strategy_name=strategy)
    bot.startup()
    return bot, api, now


def test_sma_news_is_sma_pro_plus_a_news_veto():
    pro, news = create("sma_pro"), create("sma_news")
    assert (news.n, news.band, news.notional, news.max_position_value, news.tax_harvest) == \
           (pro.n, pro.band, pro.notional, pro.max_position_value, pro.tax_harvest)
    assert news.wait_for_news_s == NEWS_WAIT_S and 0 < NEWS_WAIT_S < 1.5
    assert (news.news.lookback_days, news.news.veto_threshold) == (3, -2.0)
    assert getattr(pro, "news", None) is None and not getattr(pro, "wait_for_news_s", 0)


def test_buy_waits_for_the_days_headlines_then_goes_out_at_that_days_date():
    bot, api, now = rig()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    assert api.orders == []                                         # waiting for headlines
    now[0] = NEWS_WAIT_S / 2
    bot.on_timer()
    assert api.orders == []
    now[0] = NEWS_WAIT_S
    bot.on_timer()
    assert api.orders[0][:2] == ("AAA", "BUY") and api.orders[0][3] == "2026-01-11"
    assert bot.latencies[-1] == NEWS_WAIT_S                           # latency includes the wait


def test_bad_news_arriving_after_the_prices_vetoes_the_buy():
    bot, api, now = rig()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    now[0] = 0.15                                                   # headlines land ~150 ms later
    bot.handle_message("market.news", headline("AAA", "2026-01-11", "Fraud probe widens as lawsuit filed"))
    now[0] = NEWS_WAIT_S
    bot.on_timer()
    assert api.orders == []
    entry = bot.journal.recent()[0]
    assert entry["action"] == "BUY" and entry["risk_approved"] is False
    assert entry["risk_reason"].startswith("news veto") and entry["news_score"] <= -2


def test_bad_news_from_the_last_three_days_also_counts_but_older_news_does_not():
    bot, api, now = rig()
    bot.handle_message("market.news", headline("AAA", "2026-01-08", "Fraud probe widens"))
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    now[0] = NEWS_WAIT_S
    bot.on_timer()
    assert api.orders == []                                         # 3 days before: vetoed
    bot2, api2, now2 = rig()
    bot2.handle_message("market.news", headline("AAA", "2026-01-07", "Fraud probe widens"))
    bot2.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    now2[0] = NEWS_WAIT_S
    bot2.on_timer()
    assert api2.orders and api2.orders[0][1] == "BUY"              # 4 days before: ignored


def test_mild_or_good_news_does_not_block():
    bot, api, now = rig()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    bot.handle_message("market.news", headline("AAA", "2026-01-11", "Shares slump on weak outlook but record profit"))
    now[0] = NEWS_WAIT_S
    bot.on_timer()
    assert api.orders and api.orders[0][1] == "BUY"


def test_sells_are_never_delayed_or_blocked_by_news():
    bot, api, now = rig(holdings=[{"ticker": "AAA", "quantity": 500}])
    bot.handle_message("market.news", headline("AAA", "2026-01-11", "Fraud probe widens as lawsuit filed"))
    bot.handle_message("market.ticks", tick("AAA", 90.0, "2026-01-11"))
    assert api.orders == [("AAA", "SELL", 500, "2026-01-11")]       # immediately, no timer needed


def test_a_waiting_buy_is_dropped_if_the_next_day_starts_first():
    bot, api, now = rig()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    bot.handle_message("market.ticks", tick("AAA", 99.0, "2026-01-12"))   # next day, no new BUY
    now[0] = 10.0
    bot.on_timer()
    assert api.orders == []                                         # never bought at a stale close


def test_any_later_message_also_sends_a_buy_whose_wait_is_over():
    bot, api, now = rig()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    now[0] = NEWS_WAIT_S + 0.01
    bot.handle_message("market.news", headline("BBB", "2026-01-11", "Quarterly results due"))
    assert api.orders and api.orders[0][:2] == ("AAA", "BUY")


def test_sma_pro_still_buys_immediately():
    bot, api, now = rig("sma_pro")
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2026-01-11"))
    assert api.orders and api.orders[0][1] == "BUY"


def test_replay_runs_the_real_bot_with_news_timing():
    from scripts.replay_bot import run
    dates = [f"2026-02-{d:02d}" for d in range(1, 21)]
    closes = [100.0] * 9 + [104.0, 105.0, 106.0, 107.0, 100.0, 95.0, 94.0, 93.0, 92.0, 91.0, 90.0]
    history = {"AAA": [{"date": d, "open": c, "high": c, "low": c, "close": c, "volume": 1} for d, c in zip(dates, closes)]}
    plain = run(history, [], "sma_news")
    assert plain["orders"] >= 2 and plain["news_vetoes"] == 0
    bad = [headline("AAA", dates[9], "Fraud probe widens as lawsuit filed")]
    vetoed = run(history, bad, "sma_news")
    assert vetoed["news_vetoes"] >= 1 and vetoed["orders"] < plain["orders"]
