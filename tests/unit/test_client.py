import pytest
import requests

from src.execution.client import (APIError, RateLimitedError, SimulationAPIClient)


class FakeResp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text or str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def make_client(responder, clock=None):
    c = SimulationAPIClient(base_url="http://x", team_token="t", clock=clock or (lambda: 0.0))
    calls = []

    def request(method, url, **kw):
        calls.append((method, url, kw))
        r = responder(method, url, kw)
        if isinstance(r, Exception):
            raise r
        return r

    c.session.request = request
    c.calls = calls
    return c


def test_token_required(monkeypatch):
    monkeypatch.delenv("TEAM_JWT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError):
        SimulationAPIClient(base_url="http://x")


def test_heartbeat_success():
    c = make_client(lambda *a: FakeResp(200, {"status": "ok", "seq": 5}))
    assert c.acknowledge_preflight(5)["seq"] == 5
    assert c.calls[0][2]["json"] == {"seq": 5}


def test_heartbeat_invalid_seq_and_unauthorized():
    with pytest.raises(APIError):
        make_client(lambda *a: FakeResp(400, {}, "INVALID_SEQ")).acknowledge_preflight(5)
    with pytest.raises(APIError):
        make_client(lambda *a: FakeResp(401, {})).acknowledge_preflight(5)


def test_heartbeat_seq_mismatch_and_bad_input():
    with pytest.raises(APIError):
        make_client(lambda *a: FakeResp(200, {"status": "ok", "seq": 6})).acknowledge_preflight(5)
    c = make_client(lambda *a: FakeResp(200, {}))
    for bad in (True, "5", -1):
        with pytest.raises(ValueError):
            c.acknowledge_preflight(bad)


def test_order_filled_payload_includes_date():
    c = make_client(lambda *a: FakeResp(200, {"order_id": "o1", "status": "FILLED"}))
    r = c.submit_order("AAA", "BUY", 10, "2021-01-04")
    assert r.outcome == "FILLED"
    assert c.calls[0][2]["json"] == {"ticker": "AAA", "action": "BUY", "quantity": 10,
                                     "date": "2021-01-04"}


def test_order_rejection_code_parsed():
    c = make_client(lambda *a: FakeResp(400, {"error": "INSUFFICIENT_CAPITAL"}))
    r = c.submit_order("AAA", "BUY", 10)
    assert r.outcome == "REJECTED" and r.code == "INSUFFICIENT_CAPITAL"


def test_order_timeout_is_uncertain_not_rejected():
    c = make_client(lambda *a: requests.Timeout("slow"))
    assert c.submit_order("AAA", "BUY", 10).outcome == "UNCERTAIN"


def test_order_malformed_or_5xx_is_uncertain():
    assert make_client(lambda *a: FakeResp(200, None)).submit_order("A", "BUY", 1).outcome == "UNCERTAIN"
    assert make_client(lambda *a: FakeResp(502, {})).submit_order("A", "BUY", 1).outcome == "UNCERTAIN"


def test_order_input_validation():
    c = make_client(lambda *a: FakeResp(200, {}))
    for args in (("A", "HOLD", 1), ("A", "BUY", 0), ("A", "BUY", 1.5), ("A", "BUY", 1_000_001), ("", "BUY", 1)):
        with pytest.raises(ValueError):
            c.submit_order(*args)
    assert c.calls == []


def test_429_enters_penalty_box():
    now = [0.0]
    c = make_client(lambda *a: FakeResp(429, {}), clock=lambda: now[0])
    r = c.submit_order("A", "BUY", 1)
    assert r.outcome == "REJECTED" and r.code == "RATE_LIMITED"
    n = len(c.calls)
    assert c.submit_order("A", "BUY", 1).code == "RATE_LIMITED"
    assert len(c.calls) == n            # nothing sent during the penalty
    now[0] = 31.0
    c.session.request = lambda *a, **k: FakeResp(200, {})
    assert c.submit_order("A", "BUY", 1).outcome == "FILLED"


def test_local_budget_blocks_before_120_per_minute():
    c = make_client(lambda *a: FakeResp(200, {"stocks": []}))
    for _ in range(100):
        c.get_stocks()
    with pytest.raises(RateLimitedError):
        c.get_stocks()


def test_get_stocks_and_stage():
    c = make_client(lambda m, u, k: FakeResp(200, {"stocks": [{"ticker": "A"}, {"ticker": "B"}, {}]}))
    assert c.get_stocks() == ["A", "B"]
    with pytest.raises(APIError):
        make_client(lambda *a: FakeResp(200, {"status": "ok"})).get_stocks()
