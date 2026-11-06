"""Run the dashboard on a recorded stream with a simulated exchange (offline, no token).

Usage:
  py -m scripts.demo_dashboard data/stream_X.jsonl [--strategy ensemble] [--speed 20] [--port 8080]
Open the printed URL. The bot starts STOPPED; press Start to let the simulated exchange fill orders.
"""
import argparse
import os
import threading
import time

from src.app import Bot
from src.dashboard.demo import SimulatedAPI, replay
from src.dashboard.server import DashboardServer
from src.dashboard.state import DashboardState
from src.market_data.recorder import read_records
from src.strategy.registry import create


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("--strategy", default="sma_band")
    ap.add_argument("--speed", type=float, default=20.0, help="how many times faster than 10 s/day")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--start", action="store_true", help="begin with trading ON (default: STOPPED)")
    args = ap.parse_args()

    records = [r for r in read_records(args.recording) if r["topic"] in ("market.ticks", "market.news")]
    ticks = [r for r in records if r["topic"] == "market.ticks"]
    tickers = {r["event"]["data"]["ticker"] for r in ticks}
    total_days = len({r["event"].get("simulated_date") for r in ticks})
    api = SimulatedAPI(tickers, total_days)
    dash = DashboardState(args.strategy)
    bot = Bot(api, strategy=create(args.strategy), dash=dash, trading_enabled=args.start,
              strategy_name=args.strategy, warm_start=False)
    dash.kafka_connected = True
    bot.startup()
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
    server = DashboardServer(bot, dash, static, args.port).start()
    print(f"DEMO dashboard: {server.url}  ({total_days} days, {len(tickers)} stocks, "
          f"strategy {args.strategy}, {args.speed:g}x) - press Start in the page to trade", flush=True)
    stop = threading.Event()
    try:
        days = replay(bot, api, records, 10.0 / args.speed, stop.is_set)
        print(f"replay finished ({days} days). Dashboard stays up; Ctrl+C to exit.", flush=True)
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
    finally:
        server.stop()


if __name__ == "__main__":
    main()
