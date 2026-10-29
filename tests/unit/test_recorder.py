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


def test_load_stream_dedupes_dates_and_selects_first_loop(tmp_path):
    f = tmp_path / "s.jsonl"
    lines = []
    for loop, date, close in ((1, "2024-01-02", 10.0), (1, "2024-01-03", 11.0), (1, "2024-01-03", 11.5),
                              (2, "2024-01-02", 99.0)):
        ev = {"event_type": "price_tick", "simulated_date": date, "sandbox": {"loop_count": loop},
              "data": {"ticker": "AAA", "close": close}}
        lines.append(json.dumps(to_record("market.ticks", 0, 0, ev)))
    lines.append(json.dumps(to_record("market.news", 0, 0, {**NEWS, "sandbox": {"loop_count": 1}})))
    lines.append('{"half written')                                  # truncated last line is tolerated
    f.write_text("\n".join(lines), encoding="utf-8")
    history, news = load_stream(str(f))
    assert [b["date"] for b in history["AAA"]] == ["2024-01-02", "2024-01-03"]
    assert history["AAA"][1]["close"] == 11.5 and history["AAA"][0]["close"] == 10.0
    assert len(news) == 1
    assert load_stream(str(f), loop=2)[0]["AAA"][0]["close"] == 99.0
    assert len(list(read_records(str(f)))) == 5


def test_invalid_close_is_dropped(tmp_path):
    f = tmp_path / "s.jsonl"
    ev = {"event_type": "price_tick", "simulated_date": "2024-01-02", "data": {"ticker": "AAA", "close": None}}
    f.write_text(json.dumps(to_record("market.ticks", 0, 0, ev)), encoding="utf-8")
    assert load_stream(str(f))[0] == {}
