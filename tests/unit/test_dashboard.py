import http.client
import json
import os

import pytest

from src.app import Bot
from src.dashboard.server import DashboardServer
from src.dashboard.state import DashboardState
from src.execution.client import OrderResult

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend")


class FakeAPI:
    def __init__(self):
        self.orders = []
        self.portfolio = {"holdings": [], "cash": 1_000_000.0}

    def acknowledge_preflight(self, seq):
        pass

    def get_stocks(self):
        return ["AAA", "BBB"]

    def get_stage(self):
        return {"stage": "simulation", "status": "running", "current_date": "2021-02-01",
                "days_completed": 5, "total_days": 100, "interval_seconds": 10}

    def get_portfolio(self):
        return self.portfolio

    def get_history(self, ticker, days):
        return {"prices": [{"date": f"2021-01-{i:02d}", "open": 100.0, "high": 101.0, "low": 99.0,
                            "close": 100.0, "volume": 1000.0} for i in range(1, 26)]}

    def submit_order(self, ticker, action, qty, date=None):
        self.orders.append((ticker, action, qty, date))
        return OrderResult("FILLED", body={"execution_price": 103.0})


def tick(ticker, close, date):
    return {"event_type": "price_tick", "timestamp": "2026-10-19T10:00:00.000Z", "simulated_date": date,
            "data": {"ticker": ticker, "open": close, "high": close + 1, "low": close - 1,
                     "close": close, "volume": 5000}}


@pytest.fixture
def rig():
    api = FakeAPI()
    dash = DashboardState("sma_band")
    bot = Bot(api, dash=dash, trading_enabled=False, log=lambda *a: None, clock=lambda: 0.0)
    bot.startup()
    server = DashboardServer(bot, dash, FRONTEND, port=0).start()
    yield bot, dash, api, server
    server.stop()


def call(server, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.putrequest(method, path, skip_host=True)
    conn.putheader("Host", host or f"127.0.0.1:{server.port}")
    data = json.dumps(body).encode() if body is not None else None
    for k, v in (headers or {}).items():
        conn.putheader(k, v)
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw


JSON = {"Content-Type": "application/json"}


def test_status_shape_and_initial_stopped_state(rig):
    bot, dash, api, server = rig
    code, st = call(server, "GET", "/status")
    assert code == 200
    assert st["bot"]["state"] == "STOPPED" and st["bot"]["strategy"] == "sma_band"
    assert st["sim"]["stage"] == "simulation" and st["sim"]["total_days"] == 100
    assert st["account"]["cash"] == 1_000_000.0 and st["account"]["net_pnl"] == 0.0
    assert set(st["stats"]) >= {"orders_sent", "orders_rejected", "latency_avg_s", "latency_p95_s"}


def test_all_read_endpoints_return_json(rig):
    _, _, _, server = rig
    for path, kind in (("/positions", list), ("/events?since=0", list), ("/equity", list), ("/orders", list),
                       ("/strategies", list), ("/series", dict), ("/news", list)):
        code, body = call(server, "GET", path)
        assert code == 200 and isinstance(body, kind), path


def test_stopped_bot_sends_no_orders_but_shows_why(rig):
    bot, dash, api, server = rig
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders == []
    events = call(server, "GET", "/events?since=0")[1]
    assert any(e["type"] == "RISK_BLOCK" and "stopped" in e["reason"] for e in events)
    assert any(e["type"] == "SIGNAL" for e in events)


def test_start_enables_orders_and_records_fill_and_position(rig):
    bot, dash, api, server = rig
    code, res = call(server, "POST", "/control/start", {}, JSON)
    assert code == 200 and res["bot"]["state"] == "RUNNING"
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders and api.orders[0][:2] == ("AAA", "BUY")
    pos = call(server, "GET", "/positions")[1]
    assert pos[0]["ticker"] == "AAA" and pos[0]["avg_price"] == pytest.approx(103.0 + 20.0 / pos[0]["quantity"]) and pos[0]["quantity"] > 0
    orders = call(server, "GET", "/orders")[1]
    assert orders[0]["status"] == "FILLED" and orders[0]["fees"] == 20.0
    stats = call(server, "GET", "/status")[1]["stats"]
    assert stats["orders_sent"] == 1 and stats["orders_rejected"] == 0
    assert call(server, "POST", "/control/stop", {}, JSON)[1]["bot"]["state"] == "STOPPED"


def test_events_since_returns_only_newer_newest_first(rig):
    bot, dash, api, server = rig
    for i in range(3):
        dash.record_event("SYSTEM", f"m{i}")
    all_events = call(server, "GET", "/events?since=0")[1]
    ids = [e["id"] for e in all_events]
    assert ids == sorted(ids, reverse=True)
    newer = call(server, "GET", f"/events?since={ids[1]}")[1]
    assert [e["id"] for e in newer] == [ids[0]]


def test_strategy_switch_refused_while_running_allowed_when_stopped(rig):
    bot, dash, api, server = rig
    call(server, "POST", "/control/start", {}, JSON)
    code, res = call(server, "POST", "/control/strategy", {"id": "ensemble"}, JSON)
    assert code == 409 and "Stop trading" in res["error"]
    call(server, "POST", "/control/stop", {}, JSON)
    assert call(server, "POST", "/control/strategy", {"id": "nope"}, JSON)[0] == 409
    code, res = call(server, "POST", "/control/strategy", {"id": "ensemble"}, JSON)
    assert code == 200 and res["bot"]["strategy"] == "ensemble"
    bot.handle_message("market.ticks", tick("AAA", 100.0, "2021-02-01"))     # applied between messages
    assert bot.strategy_name == "ensemble" and bot.strategy.name == "ensemble"
    assert call(server, "GET", "/status")[1]["bot"]["strategy"] == "ensemble"


def test_post_security_checks(rig):
    bot, dash, api, server = rig
    assert call(server, "POST", "/control/start", {}, {"Content-Type": "text/plain"})[0] == 415
    assert call(server, "POST", "/control/start", {}, {**JSON, "Origin": "http://evil.example"})[0] == 403
    assert call(server, "POST", "/control/start", {"x": "y" * 5000}, JSON)[0] == 413
    assert bot.trading_enabled is False                                    # none of the above took effect
    ok = {**JSON, "Origin": f"http://127.0.0.1:{server.port}"}
    assert call(server, "POST", "/control/start", {}, ok)[0] == 200
    assert call(server, "POST", "/control/unknown", {}, JSON)[0] == 404


def test_bad_host_header_refused_dns_rebinding(rig):
    _, _, _, server = rig
    assert call(server, "GET", "/status", host="evil.example")[0] == 403
    assert call(server, "POST", "/control/start", {}, JSON, host="evil.example")[0] == 403
    assert call(server, "GET", "/status", host=f"localhost:{server.port}")[0] == 200


def test_static_files_served_and_traversal_blocked(rig):
    _, _, _, server = rig
    code, body = call(server, "GET", "/")
    assert code == 200 and b"<html" in body.lower()
    assert call(server, "GET", "/app.js")[0] == 200
    for bad in ("/../src/app.py", "/..%2fsrc%2fapp.py", "/%2e%2e/.env", "/.env", "/nope.txt"):
        assert call(server, "GET", bad)[0] == 404, bad


def test_series_has_sma_and_band_fields(rig):
    bot, dash, api, server = rig
    for i in range(10):
        bot.handle_message("market.ticks", tick("AAA", 100.0 + i, f"2021-03-{i + 1:02d}"))
    pts = call(server, "GET", "/series")[1]["AAA"]["points"]
    last = pts[-1]
    assert len(pts) == 10 and last["sma8"] is not None and last["upper"] > last["sma8"] > last["lower"]
    assert pts[0]["sma8"] is None                                          # not enough history yet


def test_news_recorded_with_score_and_never_trades(rig):
    bot, dash, api, server = rig
    call(server, "POST", "/control/start", {}, JSON)
    bot.handle_message("market.news", {"event_type": "news_flash", "simulated_date": "2021-02-01",
                                       "data": {"ticker": "AAA", "headline": "Record profit surge",
                                                "description": "strong growth"}})
    news = call(server, "GET", "/news")[1]
    assert news[0]["ticker"] == "AAA" and news[0]["keyword_score"] == 5
    assert api.orders == []


def test_dashboard_failure_cannot_break_trading():
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("dashboard exploded")

    api = FakeAPI()
    bot = Bot(api, dash=Boom(), trading_enabled=True, log=lambda *a: None, clock=lambda: 0.0)
    bot.startup()
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))
    assert api.orders and api.orders[0][:2] == ("AAA", "BUY")


def test_news_flood_cannot_evict_trading_events(rig):
    bot, dash, api, server = rig
    dash.record_event("ORDER", "BUY 10 AAA: FILLED", ticker="AAA")
    for i in range(2000):
        dash.record_event("NEWS", f"headline {i}", ticker="AAA")
    events = call(server, "GET", "/events?since=0")[1]
    assert any(e["type"] == "ORDER" for e in events)
    ids = [e["id"] for e in events]
    assert ids == sorted(ids, reverse=True)                                # merged, newest first
    assert sum(e["type"] == "NEWS" for e in events) <= 150


def test_tax_journal_csv_and_markers_endpoints(rig):
    bot, dash, api, server = rig
    call(server, "POST", "/control/start", {}, JSON)
    bot.handle_message("market.ticks", tick("AAA", 103.0, "2021-02-01"))           # BUY
    bot.handle_message("market.ticks", tick("AAA", 90.0, "2021-02-02"))            # SELL at a loss
    tax = call(server, "GET", "/tax")[1]
    assert tax["rates"]["stcg"] == 0.15 and tax["years"] and tax["years"][0]["fy"] == "FY2020-21"
    assert tax["realized_gain"] < 0 and tax["total_tax_estimate"] == 0 and tax["fees_paid"] > 0
    j = call(server, "GET", "/journal")[1]
    assert j["stats"]["filled"] == 2 and j["entries"][0]["action"] == "SELL"
    assert j["entries"][0]["tax_term"] == "ST" and j["entries"][1]["reason"]
    code, csv = call(server, "GET", "/journal.csv")
    assert code == 200 and csv.decode().startswith("time,simulated_date,ticker")
    markers = call(server, "GET", "/series")[1]["AAA"]["markers"]
    assert [m["action"] for m in markers] == ["BUY", "SELL"]


def test_evidence_endpoint_serves_file_or_empty(rig, tmp_path):
    bot, dash, api, server = rig
    path = tmp_path / "evidence.json"
    server.httpd.ctx["evidence_path"] = str(path)
    assert call(server, "GET", "/evidence")[1] == {}
    path.write_text('{"headline": "ok"}', encoding="utf-8")
    assert call(server, "GET", "/evidence")[1] == {"headline": "ok"}


def test_demo_exchange_counts_days_once_even_when_ticks_interleave():
    from src.dashboard.demo import SimulatedAPI
    api = SimulatedAPI(["A", "B"], total_days=2)
    for t, d in (("A", "2024-01-01"), ("B", "2024-01-02"), ("A", "2024-01-02"), ("B", "2024-01-01")):
        api.observe(t, d, {"close": 10.0})
    assert api.days_done == 2 and api.get_stage()["current_date"] == "2024-01-02"
    assert api.submit_order("A", "BUY", 5).outcome == "FILLED" and api.holdings["A"] == 5
    assert api.submit_order("A", "SELL", 9).code == "NO_POSITION"


def test_strategy_list_shows_the_active_sizing(rig):
    bot, dash, api, server = rig
    bot.strategy.notional, bot.strategy.max_position_value = 75_000, 75_000
    items = {s["id"]: s for s in call(server, "GET", "/strategies")[1]}
    assert "Rs 75,000 per buy" in items["sma_band"]["description"]
    assert "one buy per stock" in items["sma_band"]["description"]
    assert "Active sizing" not in items["sma_pro"]["description"]
