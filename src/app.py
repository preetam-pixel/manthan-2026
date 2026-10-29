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
                                      parse_history, parse_history_bars,
                                      preflight_seq)
from src.news.consumer import format_news
from src.portfolio.state import PortfolioState
from src.risk.manager import RiskManager
from src.strategy.registry import DEFAULT as DEFAULT_STRATEGY, create as create_strategy
from src.strategy.sma import BAND, SMA_N, SMAStrategy

STAGE_CACHE_S = 2.5          # /stage is polled at most this often
WARM_START_PER_PREFLIGHT = 5  # history fetches per preflight tick (keeps ACKs prompt)
HEARTBEAT_RETRY_INTERVAL_S = 1.0  # minimum wait before retrying a failed ACK
HEARTBEAT_MIN_INTERVAL_S = 2.0  # one ACK per 15 s is required; bursts of preflight ticks must not flood the API
HISTORY_DAYS = 30            # calendar days; comfortably covers 8 trading closes
UNWIND_DAYS = 1              # in the live run, close longs when this many days remain


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
        self.stage_info: dict = {}
        self._stage_at: Optional[float] = None
        self._warm_pending: list[str] = []
        self._last_date: dict[str, str] = {}
        self._next_ack_after: float = 0.0
        self.latencies: list[float] = []

    # ---- startup ----------------------------------------------------
    def sync_portfolio(self) -> bool:
        try:
            self.portfolio.sync(self.api.get_portfolio())
            if hasattr(self.strategy, "sync_holdings"):
                self.strategy.sync_holdings(dict(self.portfolio.held))
            self.log("Synced holdings:", dict(self.portfolio.held), "cash:", self.portfolio.cash)
            return True
        except Exception as exc:  # network / schema problems: stay un-synced, risk blocks orders
            self.log("portfolio sync failed", exc)
            return False

    def startup(self) -> None:
        """Sync portfolio, discover the universe and warm-start every ticker.

        Preflight ticks only exist before the live run; the development
        sandbox never sends them, so this must not depend on one.
        """
        self.sync_portfolio()
        self._load_universe()
        while self._warm_pending:
            self._warm_some()

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
                response = self.api.get_history(
                    ticker, getattr(self.strategy, "history_days", HISTORY_DAYS))
                if hasattr(self.strategy, "warm_start_bars"):
                    self.strategy.warm_start_bars(ticker, parse_history_bars(response))
                else:
                    closes = [c for _, c in parse_history(response)]
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
            self.stage_info = stage if isinstance(stage, dict) else {}
            # live /stage reports lowercase status ("running"); the PDF shows uppercase
            status = str(stage.get("status") or "").upper()
            self.sim_running = str(stage.get("stage") or "").lower() == "simulation" and status == "RUNNING"
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
                if (event.get("data") or {}).get("ticker"):      # skip empty filler events
                    self.log(format_news(event))   # informational only; never trades
                    news = getattr(self.strategy, "news", None)
                    if news is not None:                         # entry veto only, never a trade trigger
                        score = news.update(event)
                        if score is not None:
                            self.log(f"  news risk score {score:+.0f} (entries vetoed at <= {news.veto_threshold:g})")
        except Exception as exc:               # a bad event must not kill the loop
            self.log("event error", exc)

    def _on_preflight(self, event: dict) -> None:
        seq = preflight_seq(event)
        if isinstance(seq, int) and not isinstance(seq, bool):
            now = self.clock()
            if now >= self._next_ack_after:
                try:
                    self.api.acknowledge_preflight(seq)
                    self._next_ack_after = now + HEARTBEAT_MIN_INTERVAL_S
                    self.log("heartbeat ack", seq)
                except Exception as exc:
                    self._next_ack_after = now + HEARTBEAT_RETRY_INTERVAL_S
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
        if self.universe is None:
            self._load_universe()
        if not self.portfolio.synced:
            self.sync_portfolio()
        ts = _event_time(event)
        held = self.portfolio.quantity(ticker)
        if hasattr(self.strategy, "on_bar"):
            signal = self.strategy.on_bar(ticker, tick, held, ts)
        else:
            history = self.strategy.closes.get(ticker)
            if history is not None and len(history) == SMA_N:
                sma = sum(history) / SMA_N
                self.log(f"  {ticker} vs SMA{SMA_N}: {(float(close) / sma - 1):+.2%} (trigger +/-{BAND:.1%})")
            else:
                self.log(f"  {ticker} warming up {len(history) if history is not None else 0}/{SMA_N}")
            signal = self.strategy.on_close(ticker, float(close), held, ts)
        if signal is None and held > 0 and self._unwind_due():
            signal = Signal(ticker, "SELL", held, ts, "end-of-run unwind")
        if signal is None:
            return
        self.refresh_stage()
        self._execute(signal, float(close), date, received_at)

    def _unwind_due(self) -> bool:
        """True in the live run's last UNWIND_DAYS days (never in the looping sandbox)."""
        if not self.refresh_stage():
            return False
        info = self.stage_info
        if str(info.get("stage") or "").lower() != "simulation":
            return False
        done, total = info.get("days_completed"), info.get("total_days")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (done, total)) or total <= 0:
            return False
        return done >= total - UNWIND_DAYS

    def latency_summary(self) -> dict:
        """Decision latency (tick received -> order response) over sent orders."""
        if not self.latencies:
            return {"orders": 0}
        ordered = sorted(self.latencies)
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        return {"orders": len(ordered), "avg_s": sum(ordered) / len(ordered),
                "p95_s": p95, "max_s": ordered[-1]}

    def _reset_ticker(self, ticker: str) -> None:
        self.log("simulated date went backwards; resetting", ticker)
        self.strategy.reset(ticker)
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
                k = k.strip().removeprefix("export ").strip()
                v = v.strip().strip('"').strip("'")   # tolerate "KEY= value" and quoted values
                if v:
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
    strategy_name = os.environ.get("STRATEGY", DEFAULT_STRATEGY)
    try:
        strategy = create_strategy(strategy_name)   # validate before touching the network
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
    bot = Bot(api, strategy=strategy, warm_start=os.environ.get("WARM_START", "1") != "0")
    bot.startup()
    _log(f"Strategy: {strategy_name}")
    _log("Connected to Kafka. Listening...")
    try:
        for message in consumer:
            bot.handle_message(message.topic, message.value)
    finally:
        _log("Decision latency:", bot.latency_summary())


def main() -> None:
    if "--live" not in sys.argv:
        print("Dry start. Run `python -m src.app --live` to connect to Kafka and the simulator "
              "(requires TEAM_JWT_TOKEN or BOT_ACCESS_TOKEN).")
        return
    run()


if __name__ == "__main__":
    main()
