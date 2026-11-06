import json

from src.market_data.recorder import load_stream, read_records, to_record

TICK = {"event_type": "price_tick", "simulated_date": "2024-12-06",
        "data": {"ticker": "HAVN", "open": 1, "high": 3, "low": 1, "close": 2, "volume": 9},
        "sandbox": {"loop_count": 2}}
NEWS = {"event_type": "news_flash", "simulated_date": "2024-12-06",
        "data": {"ticker": "DSNY", "headline": "h", "description": "d"}, "sandbox": {"loop_count": 2}}


def test_to_record_keeps_ticks_and_real_news_only():
    assert to_record("market.ticks", 1, 5, TICK)["event"] == TICK
    assert to_record("market.news", 1, 5, NEWS)["offset"] == 5
    assert to_record("market.ticks", 0, 0, {"event_type": "preflight_tick", "seq": 3}) is None
    assert to_record("market.news", 0, 0, {"event_type": "news_flash", "data": {}}) is None
    assert to_record("market.ticks", 0, 0, None) is None
    assert to_record("market.news", 0, 0, TICK) is None            # wrong topic


def _tick_line(loop, date, close, ticker="AAA"):
    ev = {"event_type": "price_tick", "simulated_date": date, "sandbox": {"loop_count": loop},
          "data": {"ticker": ticker, "close": close}}
    return json.dumps(to_record("market.ticks", 0, 0, ev))


def test_loops_are_merged_so_a_mid_loop_start_still_covers_all_days(tmp_path):
    f = tmp_path / "s.jsonl"
    lines = [_tick_line(1, "2024-01-03", 11.0), _tick_line(1, "2024-01-04", 12.0),   # started mid-loop
             _tick_line(2, "2024-01-02", 10.0), _tick_line(2, "2024-01-03", 11.0)]  # wrapped to day 1
    lines.append(json.dumps(to_record("market.news", 0, 0, {**NEWS, "sandbox": {"loop_count": 1}})))
    lines.append(json.dumps(to_record("market.news", 0, 1, {**NEWS, "sandbox": {"loop_count": 2}})))  # repeat
    lines.append('{"half written')                                  # truncated last line is tolerated
    f.write_text(chr(10).join(lines), encoding="utf-8")
    report = {}
    history, news = load_stream(str(f), report=report)
    assert [b["date"] for b in history["AAA"]] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert report["conflicts"] == 0
    assert len(news) == 1                                            # same headline/date not duplicated
    assert len(list(read_records(str(f)))) == 6


def test_conflicting_loops_are_reported_and_single_loop_selectable(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(chr(10).join([_tick_line(1, "2024-01-02", 10.0), _tick_line(2, "2024-01-02", 99.0)]),
                 encoding="utf-8")
    report = {}
    history, _ = load_stream(str(f), report=report)
    assert report["conflicts"] == 1 and history["AAA"][0]["close"] == 10.0   # first value wins
    assert load_stream(str(f), loop=2)[0]["AAA"][0]["close"] == 99.0


def test_invalid_close_is_dropped(tmp_path):
    f = tmp_path / "s.jsonl"
    ev = {"event_type": "price_tick", "simulated_date": "2024-01-02", "data": {"ticker": "AAA", "close": None}}
    f.write_text(json.dumps(to_record("market.ticks", 0, 0, ev)), encoding="utf-8")
    assert load_stream(str(f))[0] == {}
