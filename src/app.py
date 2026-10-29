"""Bot lifecycle: Kafka events -> strategy -> risk -> execution -> reconciliation.

All message handling lives in ``Bot.handle_message`` so it can be tested with
fake events and a fake API; Kafka is only touched in ``run``.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from src.contracts import Signal
from src.execution.client import APIError, OrderResult, SimulationAPIClient
from src.market_data.consumer import (TOPIC_NEWS, TOPIC_TICKS, is_preflight,
                                      is_price_tick, normalize_tick,
                                      parse_history, preflight_seq)
from src.news.consumer import format_news
from src.portfolio.state import PortfolioState
from src.risk.manager import RiskManager
from src.strategy.sma import SMA_N, SMAStrategy

STAGE_CACHE_S = 2.5          # /stage is polled at most this often
WARM_START_PER_PREFLIGHT = 5  # history fetches per preflight tick (keeps ACKs prompt)
HISTORY_DAYS = 30            # calendar days; comfortably covers 8 trading closes


def _log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _event_time(event: dict) -> datetime:
    raw = event.get("timestamp")
    if isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class Bot:
    def __init__(self, api, strategy: Optional[SMAStrategy] = None,
                 risk: Optional[RiskManager] = None,
                 portfolio: Optional[PortfolioState] = None,
                 log: Callable = _log, clock: Callable[[], float] = time.monotonic,
                 warm_start: bool = True):
        self.api = api
        self.strategy = strategy or SMAStrategy()
        self.risk = risk or RiskManager()
        self.portfolio = portfolio or PortfolioState()
        self.log = log
        self.clock = clock
        self.warm_start = warm_start

        self.universe: Optional[set] = None
        self.sim_running = False
        self._stage_at: Optional[float] = None
        self._warm_pending: list[str] = []
        self._last_date: dict[str, str] = {}
        self.latencies: list[float] = []

    # ---- startup ----------------------------------------------------
    def sync_portfolio(self) -> bool:
        try:
            self.portfolio.sync(self.api.get_portfolio())
            self.log("Synced holdings:", dict(self.portfolio.held), "cash:", self.portfolio.cash)
            return True
        except Exception as exc:  # network / schema problems: stay un-synced, risk blocks orders
            self.log("portfolio sync failed", exc)
            return False

    def _load_universe(self) -> None:
        if self.universe is not None:
            return
        try:
            self.universe = set(self.api.get_stocks())
            self._warm_pending = sorted(self.universe) if self.warm_start else []
            self.log("Universe:", sorted(self.universe))
        except Exception as exc:
            self.log("stocks error", exc)

    def _warm_some(self) -> None:
        for _ in range(min(WARM_START_PER_PREFLIGHT, len(self._warm_pending))):
            ticker = self._warm_pending.pop(0)
            if ticker in self._last_date:
                continue  # live ticks already seen
            try:
                closes = [c for _, c in parse_history(self.api.get_history(ticker, HISTORY_DAYS))]
                self.strategy.warm_start(ticker, closes[-SMA_N:])
            except Exception as exc:
                self.log("warm-start failed (cold start)", ticker, exc)

    # ---- simulator state -------------------------------------------
    def refresh_stage(self, force: bool = False) -> bool:
        now = self.clock()
        if not force and self._stage_at is not None and now - self._stage_at < STAGE_CACHE_S:
            return self.sim_running
        try:
            stage = self.api.get_stage()
            self.sim_running = stage.get("stage") == "simulation" and stage.get("status") == "RUNNING"
        except Exception as exc:
            self.sim_running = False   # uncertain state: do not trade
            self.log("stage error", exc)
        self._stage_at = now
        return self.sim_running

    # ---- events -----------------------------------------------------
    def handle_message(self, topic: str, event: dict, received_at: Optional[float] = None) -> None:
        if not isinstance(event, dict):
            return
        received_at = self.clock() if received_at is None else received_at
        try:
            if is_preflight(event):
                self._on_preflight(event)
            elif is_price_tick(topic, event):
                self._on_price_tick(event, received_at)
            elif topic == TOPIC_NEWS:
                self.log(format_news(event))   # informational only; never trades
        except Exception as exc:               # a bad event must not kill the loop
            self.log("event error", exc)

    def _on_preflight(self, event: dict) -> None:
        seq = preflight_seq(event)
        if isinstance(seq, int) and not isinstance(seq, bool):
            try:
                self.api.acknowledge_preflight(seq)
                self.log("heartbeat ack", seq)
            except Exception as exc:
                self.log("heartbeat error", exc)
        else:
            self.log("preflight without usable seq", event)
        self._load_universe()
        self._warm_some()
        if not self.portfolio.synced:
            self.sync_portfolio()

    def _on_price_tick(self, event: dict, received_at: float) -> None:
        tick = normalize_tick(event)
        ticker, close, date = tick["ticker"], tick["close"], tick["simulated_date"]
        if not ticker or isinstance(close, bool) or not isinstance(close, (int, float)):
            self.log("ignored malformed tick", ticker, close)
            return
        self.log("TICK", date, ticker, close)

        prev = self._last_date.get(ticker)
        if date is not None and prev == date:
            return                                   # duplicate delivery
        if date is not None and prev is not None and date < prev:
            self._reset_ticker(ticker)               # sandbox loop restarted at Day 1
        if date is not None:
            self._last_date[ticker] = date

        self._reconcile_uncertain()
        ts = _event_time(event)
        signal = self.strategy.on_close(ticker, float(close), self.portfolio.quantity(ticker), ts)
        if signal is None:
            return
        self.refresh_stage()
        self._execute(signal, float(close), date, received_at)

    def _reset_ticker(self, ticker: str) -> None:
        self.log("simulated date went backwards; resetting", ticker)
        self.strategy.closes.pop(ticker, None)
        self.portfolio.submitted = {k for k in self.portfolio.submitted if k[0] != ticker}
        self.sync_portfolio()

    # ---- execution --------------------------------------------------
    def _execute(self, signal: Signal, price: float, date: Optional[str], received_at: float) -> None:
        decision = self.risk.evaluate(
            signal, price, self.clock() - received_at, date, self.universe,
            self.portfolio, self.sim_running)
        if not decision.approved:
            self.log("RISK BLOCK", signal.action, signal.quantity, signal.ticker, decision.reason)
            return

        key = (signal.ticker, signal.action, date)
        self.portfolio.record_submitted(key)         # in-flight marker before sending
        result: OrderResult = self.api.submit_order(
            signal.ticker, signal.action, signal.quantity, date)
        self.latencies.append(self.clock() - received_at)
        self.log("ORDER", signal.action, signal.quantity, signal.ticker, result.outcome,
                 result.code or "", f"({signal.reason})")
        self._reconcile_result(signal, price, key, result)

    def _reconcile_result(self, signal: Signal, price: float, key: tuple, result: OrderResult) -> None:
        if result.outcome == "FILLED":
            fill = result.body.get("execution_price")
            fill = fill if isinstance(fill, (int, float)) and not isinstance(fill, bool) else price
            self.portfolio.apply_fill(signal.ticker, signal.action, signal.quantity, fill)
        elif result.outcome == "UNCERTAIN":
            self.portfolio.mark_uncertain(signal.ticker)   # never assume rejected
            self._reconcile_uncertain()
        else:  # REJECTED
            if result.code == "RATE_LIMITED":
                self.portfolio.submitted.discard(key)      # nothing reached the exchange
            if result.code == "SIMULATION_NOT_RUNNING":
                self.sim_running = False
            if result.code in ("INSUFFICIENT_CAPITAL", "INSUFFICIENT_MARGIN", "ACCOUNT_BLOCKED"):
                self.sync_portfolio()

    def _reconcile_uncertain(self) -> None:
        """Resolve unknown order outcomes from the exchange portfolio before trading again."""
        if not self.portfolio.uncertain:
            return
        try:
            self.portfolio.resolve_uncertain(self.api.get_portfolio())
            self.log("reconciled uncertain orders from portfolio")
        except Exception as exc:
            self.log("reconcile failed; ticker stays blocked", exc)


def _load_dotenv(path: str = ".env") -> None:
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


def _safe_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None   # malformed event: handle_message ignores non-dicts


def run() -> None:
    _load_dotenv()
    try:
        api = SimulationAPIClient()
    except ValueError as exc:
        raise SystemExit(str(exc))
    from kafka import KafkaConsumer  # imported lazily so tests need no broker

    broker = os.environ.get("BROKER", "192.168.65.157:9094")
    username = os.environ.get("HACKATHON_USERNAME", "mn2631")
    consumer = KafkaConsumer(
        TOPIC_TICKS, TOPIC_NEWS,
        bootstrap_servers=[broker],
        group_id=f"group-{username}",
        auto_offset_reset="latest",
        enable_auto_commit=False,
        value_deserializer=_safe_json,
    )
    bot = Bot(api, warm_start=os.environ.get("WARM_START", "1") != "0")
    bot.sync_portfolio()
    _log("Connected to Kafka. Listening...")
    for message in consumer:
        bot.handle_message(message.topic, message.value)


def main() -> None:
    if "--live" not in sys.argv:
        print("Dry start. Run `python -m src.app --live` to connect to Kafka and the simulator "
              "(requires TEAM_JWT_TOKEN or BOT_ACCESS_TOKEN).")
        return
    run()


if __name__ == "__main__":
    main()
