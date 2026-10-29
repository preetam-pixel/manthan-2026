"""Bot lifecycle: Kafka events -> strategy -> risk -> execution -> reconciliation.

All message handling lives in ``Bot.handle_message`` so it can be tested with
fake events and a fake API; Kafka is only touched in ``run``.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from src.contracts import Signal
from src.journal import DecisionJournal
from src.news.filter import NewsFilter
from src.tax.engine import TaxBook
from src.execution.client import APIError, OrderResult, SimulationAPIClient
from src.market_data.consumer import (TOPIC_NEWS, TOPIC_TICKS, is_preflight,
                                      is_price_tick, normalize_tick,
                                      parse_history, parse_history_bars,
                                      preflight_seq)
from src.news.consumer import format_news, keyword_counts
from src.portfolio.state import PortfolioState
from src.risk.manager import RiskManager
from src.strategy.registry import DEFAULT as DEFAULT_STRATEGY, create as create_strategy
from src.strategy.sma import BAND, MAX_POS_VALUE, SMA_N, SMAStrategy

STAGE_CACHE_S = 2.5          # /stage is polled at most this often
WARM_START_PER_PREFLIGHT = 5  # history fetches per preflight tick (keeps ACKs prompt)
HEARTBEAT_RETRY_INTERVAL_S = 1.0  # minimum wait before retrying a failed ACK
HEARTBEAT_MIN_INTERVAL_S = 2.0  # one ACK per 15 s is required; bursts of preflight ticks must not flood the API
HISTORY_DAYS = 30            # calendar days; comfortably covers 8 trading closes
TRADING_STAGES = ("simulation", "development")   # stages in which orders may be sent
RESYNC_S = 60.0               # re-read the exchange portfolio this often (exchange is the source of truth)
UNWIND_DAYS = 1              # in the live run, close longs when this many days remain


def _log(*a):
    line = " ".join(str(x) for x in (time.strftime("%H:%M:%S"), *a))
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        # Headlines can hold characters a Windows console cannot encode (e.g. zero-width space);
        # logging must never raise, or the rest of the event would be skipped.
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)


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
                 warm_start: bool = True, dash=None, trading_enabled: bool = True,
                 strategy_name: Optional[str] = None, journal: Optional[DecisionJournal] = None):
        self.api = api
        self.strategy = strategy or SMAStrategy()
        self._own_risk = risk is None
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

        self.dash = dash                          # optional read-only DashboardState
        self.trading_enabled = trading_enabled    # Start/Stop switch; False = log only, send nothing
        self.strategy_name = strategy_name or getattr(self.strategy, "name", "sma_band")
        self._pending_strategy: Optional[str] = None
        self._control_lock = threading.Lock()
        self.tax = TaxBook()                      # FIFO lots -> STCG/LTCG estimate, harvesting
        self.journal = journal or DecisionJournal()
        self.news_context = NewsFilter()          # recent headline risk per ticker, for explanations
        self._last_sync_at: Optional[float] = None
        self._sync_risk_cap()

    def _sync_risk_cap(self) -> None:
        """The per-ticker cap follows the active strategy unless a custom RiskManager was injected."""
        if self._own_risk:
            self.risk.max_pos_value = getattr(self.strategy, "max_position_value", MAX_POS_VALUE)

    def _d(self, method: str, *args, **kwargs) -> None:
        """Call a dashboard hook; the dashboard must never be able to break trading."""
        if self.dash is None:
            return
        try:
            getattr(self.dash, method)(*args, **kwargs)
        except Exception:
            pass

    # ---- dashboard controls (called from the HTTP thread) -----------
    def set_trading(self, enabled: bool) -> None:
        with self._control_lock:
            self.trading_enabled = bool(enabled)
        self.log("TRADING", "ENABLED" if enabled else "STOPPED (heartbeats and data continue)")
        self._d("record_event", "SYSTEM", "Trading started" if enabled else "Trading stopped",
                reason="dashboard control")

    def request_strategy(self, name: str) -> Optional[str]:
        """Queue a strategy switch; applied by the bot thread between messages. Returns an error or None."""
        with self._control_lock:
            if self.trading_enabled:
                return "Stop trading before changing strategy"
            try:
                create_strategy(name)               # validate the name only
            except ValueError as exc:
                return str(exc)
            self._pending_strategy = name
        return None

    def _apply_pending_strategy(self) -> None:
        with self._control_lock:
            name, self._pending_strategy = self._pending_strategy, None
        if not name or name == self.strategy_name:
            return
        self.strategy = create_strategy(name)
        self.strategy_name = name
        self._sync_risk_cap()
        self._last_date.clear()
        self.strategy.news = getattr(self.strategy, "news", None)  # keep attribute present
        if hasattr(self.strategy, "sync_holdings"):
            self.strategy.sync_holdings(dict(self.portfolio.held))
        for ticker in sorted(self.universe or ()):
            if self.warm_start:
                self._warm_ticker(ticker)
        self.log("STRATEGY switched to", name)
        self._d("record_event", "SYSTEM", f"Strategy switched to {name}", reason="dashboard control")
        if self.dash is not None:
            self.dash.strategy = name

    # ---- startup ----------------------------------------------------
    def sync_portfolio(self) -> bool:
        try:
            self.portfolio.sync(self.api.get_portfolio())
            self._last_sync_at = self.clock()
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
        self.refresh_stage(force=True)               # so the dashboard has simulation info immediately

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
            self._warm_ticker(ticker)

    def _warm_ticker(self, ticker: str) -> None:
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
            # Orders are accepted while the stream is running in the live "simulation" stage and in the
            # "development" sandbox (the brief says the sandbox is for testing API orders). Never in
            # "preflight", "ready", paused or completed.
            self.sim_running = (str(stage.get("stage") or "").lower() in TRADING_STAGES
                                and status == "RUNNING")
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
        if (self._last_sync_at is not None and not self.portfolio.uncertain
                and self.clock() - self._last_sync_at >= RESYNC_S):
            self.sync_portfolio()                    # periodic exchange-truth reconciliation
        if self._pending_strategy:
            try:
                self._apply_pending_strategy()
            except Exception as exc:
                self.log("strategy switch failed", exc)
        try:
            if is_preflight(event):
                self._on_preflight(event)
            elif is_price_tick(topic, event):
                self._on_price_tick(event, received_at)
            elif topic == TOPIC_NEWS:
                if (event.get("data") or {}).get("ticker"):      # skip empty filler events
                    self.log(format_news(event))   # informational only; never trades
                    data = event.get("data") or {}
                    pos, neg = keyword_counts(data)
                    self._d("record_news", data.get("ticker"), event.get("simulated_date"),
                            data.get("headline"), pos - neg)
                    self._d("record_event", "NEWS", data.get("headline") or "news", ticker=data.get("ticker"),
                            simulated_date=event.get("simulated_date"),
                            reason="informational only; can only veto entries")
                    self.news_context.update(event)
                    news = getattr(self.strategy, "news", None)
                    if news is not None:                         # entry veto only, never a trade trigger
                        score = news.update(event)
                        if score is not None:
                            self.log(f"  news risk score {score:+.0f} (entries vetoed at <= {news.veto_threshold:g})")
        except Exception as exc:               # a bad event must not kill the loop
            self.log("event error", exc)
            self._d("record_event", "ERROR", f"event error: {exc}")

    def _on_preflight(self, event: dict) -> None:
        seq = preflight_seq(event)
        if isinstance(seq, int) and not isinstance(seq, bool):
            now = self.clock()
            if now >= self._next_ack_after:
                try:
                    self.api.acknowledge_preflight(seq)
                    self._next_ack_after = now + HEARTBEAT_MIN_INTERVAL_S
                    self.log("heartbeat ack", seq)
                    self._d("record_heartbeat", seq)
                except Exception as exc:
                    self._next_ack_after = now + HEARTBEAT_RETRY_INTERVAL_S
                    self.log("heartbeat error", exc)
        else:
            self.log("preflight without usable seq", event)
        self._load_universe()
        self._warm_some()
        if not self.portfolio.synced:
            self.sync_portfolio()
        if self.dash is not None:
            self.refresh_stage()                     # cached; keeps the dashboard's stage current in pre-flight

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
        self._d("record_tick", ticker, date, tick)
        if self.dash is not None:
            self.refresh_stage()                     # keep the dashboard's simulation panel current

        self._reconcile_uncertain()
        if self.universe is None:
            self._load_universe()
        if not self.portfolio.synced:
            self.sync_portfolio()
        ts = _event_time(event)
        held = self.portfolio.quantity(ticker)
        if self.tax.quantity(ticker) != held:
            self.tax.sync_quantity(ticker, held, float(close), date)   # positions we did not open here
        if hasattr(self.strategy, "on_bar"):
            signal = self.strategy.on_bar(ticker, tick, held, ts)
        else:
            n = getattr(self.strategy, "n", SMA_N)
            band = getattr(self.strategy, "band", BAND)
            history = self.strategy.closes.get(ticker)
            if history is not None and len(history) == n:
                sma = sum(history) / n
                self.log(f"  {ticker} vs SMA{n}: {(float(close) / sma - 1):+.2%} (trigger +/-{band:.1%})")
            else:
                self.log(f"  {ticker} warming up {len(history) if history is not None else 0}/{n}")
            signal = self.strategy.on_close(ticker, float(close), held, ts)
        if signal is None and held > 0 and getattr(self.strategy, "tax_harvest", False):
            for t, qty, loss, saved in self.tax.harvest_candidates(date, {ticker: float(close)}):
                if t == ticker:
                    signal = Signal(ticker, "SELL", min(qty, held), ts,
                                    f"tax-loss harvest before 31 March: realise Rs {loss:,.0f} loss, "
                                    f"saves ~Rs {saved:,.0f} tax")
        if signal is None and held > 0 and self._unwind_due():
            signal = Signal(ticker, "SELL", held, ts, "end-of-run unwind")
        self._record_equity(date)
        if signal is None:
            return
        self._d("record_event", "SIGNAL", f"{signal.action} {signal.quantity} {ticker} @ {close}",
                ticker=ticker, reason=signal.reason, simulated_date=date)
        self.refresh_stage()
        self._execute(signal, float(close), date, received_at)

    def _record_equity(self, date: Optional[str]) -> None:
        if self.dash is None:
            return
        invested = sum(q * self.dash.last_close.get(t, 0.0) for t, q in self.portfolio.held.items() if q > 0)
        cash = self.portfolio.cash
        self._d("record_equity", date, None if cash is None else cash + invested, cash, invested)

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
        self._d("reset_ticker", ticker)
        self.portfolio.submitted = {k for k in self.portfolio.submitted if k[0] != ticker}
        self.sync_portfolio()

    # ---- execution --------------------------------------------------
    def _execute(self, signal: Signal, price: float, date: Optional[str], received_at: float) -> None:
        entry = {"simulated_date": date, "ticker": signal.ticker, "strategy": self.strategy_name,
                 "action": signal.action, "quantity": signal.quantity, "price": price,
                 "reason": signal.reason, "news_score": self.news_context.recent_score(signal.ticker, date)}
        try:
            self._send(signal, price, date, received_at, entry)
        finally:
            self.journal.record(entry)

    def _send(self, signal: Signal, price: float, date: Optional[str], received_at: float, entry: dict) -> None:
        if not self.trading_enabled:
            entry.update(risk_approved=False, risk_reason="trading stopped from dashboard")
            self.log("TRADING STOPPED - not sending", signal.action, signal.quantity, signal.ticker,
                     f"({signal.reason})")
            self._d("record_event", "RISK_BLOCK", f"{signal.action} {signal.quantity} {signal.ticker} not sent",
                    ticker=signal.ticker, reason="trading stopped from dashboard", simulated_date=date)
            return
        decision = self.risk.evaluate(
            signal, price, self.clock() - received_at, date, self.universe,
            self.portfolio, self.sim_running)
        entry.update(risk_approved=decision.approved, risk_reason=decision.reason)
        if not decision.approved:
            self.log("RISK BLOCK", signal.action, signal.quantity, signal.ticker, decision.reason)
            self._d("record_event", "RISK_BLOCK", f"{signal.action} {signal.quantity} {signal.ticker} blocked",
                    ticker=signal.ticker, reason=decision.reason, simulated_date=date)
            return

        key = (signal.ticker, signal.action, date)
        self.portfolio.record_submitted(key)         # in-flight marker before sending
        result: OrderResult = self.api.submit_order(
            signal.ticker, signal.action, signal.quantity, date)
        self.latencies.append(self.clock() - received_at)
        self.log("ORDER", signal.action, signal.quantity, signal.ticker, result.outcome,
                 result.code or "", f"({signal.reason})")
        fees = 20.0 + (15.34 if signal.action == "SELL" else 0.0)
        entry.update(outcome=result.outcome, code=result.code, latency_s=self.latencies[-1],
                     fees=fees if result.outcome == "FILLED" else None)
        self._d("record_order", signal.ticker, signal.action, signal.quantity, price, result.outcome,
                result.code, self.latencies[-1], fees if result.outcome == "FILLED" else None)
        self._d("record_event", "ORDER", f"{signal.action} {signal.quantity} {signal.ticker}: {result.outcome}",
                ticker=signal.ticker, reason=result.code or signal.reason, simulated_date=date)
        self._reconcile_result(signal, price, key, result, entry)

    def _reconcile_result(self, signal: Signal, price: float, key: tuple, result: OrderResult,
                          entry: Optional[dict] = None) -> None:
        if result.outcome == "FILLED":
            fill = result.body.get("execution_price")
            fill = fill if isinstance(fill, (int, float)) and not isinstance(fill, bool) else price
            self.portfolio.apply_fill(signal.ticker, signal.action, signal.quantity, fill)
            if signal.action == "BUY":
                self.tax.buy(signal.ticker, signal.quantity, fill, key[2])
            else:
                realised = self.tax.sell(signal.ticker, signal.quantity, fill, key[2])
                if entry is not None and realised:
                    entry.update(realized_gain=round(sum(r.gain for r in realised), 2),
                                 tax_term="/".join(sorted({r.term for r in realised})))
            if entry is not None:
                entry["fill_price"] = fill
            self._d("record_fill", signal.ticker, signal.action, signal.quantity, fill,
                    key[2])
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


def run(dashboard: bool = False) -> None:
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

    def make_consumer():
        return KafkaConsumer(
            TOPIC_TICKS, TOPIC_NEWS,
            bootstrap_servers=[broker],
            group_id=f"group-{username}",
            auto_offset_reset="latest",
            enable_auto_commit=False,
            value_deserializer=_safe_json,
        )

    journal_path = os.path.join("logs", f"decisions_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
    dash = server = None
    trading = True
    if dashboard:
        from src.dashboard.server import DashboardServer
        from src.dashboard.state import DashboardState
        dash = DashboardState(strategy_name)
        # With the dashboard on, the bot boots STOPPED: press Start (or set START_TRADING=1).
        trading = os.environ.get("START_TRADING", "0") == "1"
    bot = Bot(api, strategy=strategy, warm_start=os.environ.get("WARM_START", "1") != "0",
              dash=dash, trading_enabled=trading, strategy_name=strategy_name,
              journal=DecisionJournal(journal_path))
    if dash is not None:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
        server = DashboardServer(bot, dash, static_dir, int(os.environ.get("DASHBOARD_PORT", "8080"))).start()
        _log(f"Dashboard: {server.url}  (trading is {'ON' if trading else 'STOPPED - press Start in the dashboard'})")
    bot.startup()
    _log(f"Strategy: {strategy_name}  |  decision journal: {journal_path}")
    try:
        consume_forever(bot, make_consumer, dash)
    except KeyboardInterrupt:
        pass
    finally:
        _log("Decision latency:", bot.latency_summary())
        _log("Tax estimate:", {k: v for k, v in bot.tax.summary().items() if k != "years"})
        if server is not None:
            server.stop()


def consume_forever(bot: "Bot", make_consumer: Callable, dash=None, sleep: Callable = time.sleep,
                    max_backoff: float = 15.0, stop: Callable[[], bool] = lambda: False) -> None:
    """Feed Kafka messages to the bot; on any broker/network error, reconnect with backoff.

    A dropped Wi-Fi link or broker restart must not end the run: the bot keeps its state
    (positions, tax lots, journal) and resumes as soon as Kafka is reachable again.
    """
    backoff = 1.0
    while not stop():
        consumer = None
        try:
            consumer = make_consumer()
            if dash is not None:
                dash.kafka_connected = True
            _log("Connected to Kafka. Listening...")
            backoff = 1.0
            for message in consumer:
                bot.handle_message(message.topic, message.value)
                if stop():
                    return
        except KeyboardInterrupt:
            raise
        except Exception as exc:                      # broker down, network lost, rebalance failure...
            if dash is not None:
                dash.kafka_connected = False
            bot.log(f"Kafka connection problem: {exc!r}; reconnecting in {backoff:.0f}s")
            sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        finally:
            if consumer is not None:
                try:
                    consumer.close()
                except Exception:
                    pass


def main() -> None:
    if "--live" not in sys.argv:
        print("Dry start. Run `python -m src.app --live` to connect to Kafka and the simulator "
              "(requires TEAM_JWT_TOKEN or BOT_ACCESS_TOKEN).")
        return
    run(dashboard="--dashboard" in sys.argv)


if __name__ == "__main__":
    main()
