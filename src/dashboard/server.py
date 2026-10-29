"""Local dashboard server: serves frontend/ and a small JSON API from the bot's state.

Safety:
  * binds to 127.0.0.1 only; requests whose Host header is not that origin are refused
    (stops DNS-rebinding), and POSTs must be same-origin ``application/json``;
  * the only write actions are bot Start/Stop and strategy selection;
  * it never touches the exchange gateway and never exposes the API token.
"""
import json
import mimetypes
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from src.strategy.registry import STRATEGIES
from src.tax.engine import fy_of, to_date

STARTING_CAPITAL = 1_000_000.0
MAX_BODY = 2048

STRATEGY_INFO = {
    "sma_pro": ("SMA8 band PRO (recommended)", "SMA8 +/-1.5% rule at 1.5x size (Rs 75k per trade, Rs 1.5L cap) with year-end "
                "tax-loss harvesting. 500-day replay: +28.8%, 10.5% max drawdown, +25.4% after tax.", True),
    "sma_band": ("SMA8 band (original)", "Original rule: buy 1.5% above the 8-day average, sell 1.5% below. "
                 "500-day replay: +17.9%, 7.1% max drawdown.", True),
    "ensemble": ("Ensemble (disciplined)", "Buys only when two rules agree. Failed out of sample (-0.04%).", False),
    "ensemble_scaled": ("Ensemble, scaled", "Same rules with 2x size and 8 positions.", True),
    "mean_reversion": ("Mean reversion", "Buys oversold dips in a non-falling trend; exits at the 10-day mean.", True),
    "trend_pullback": ("Trend pullback", "Buys short dips inside an uptrend.", True),
    "laggard_reversion": ("Laggard reversion", "Buys the weakest names by 10-day return; 5-bar time stop.", True),
    "breakout": ("Breakout (not recommended)", "Lost money on real history.", False),
    "relative_strength": ("Relative strength (not recommended)", "Lost money on real history.", False),
    "adaptive": ("Adaptive band (not recommended)", "Lost money on real history.", False),
}


def bot_view(bot, dash) -> dict:
    pending = getattr(bot, "_pending_strategy", None)
    return {
        "state": "RUNNING" if bot.trading_enabled else "STOPPED",
        "kafka_connected": dash.kafka_connected,
        "last_heartbeat_seq": dash.last_heartbeat_seq,
        "last_heartbeat_at": dash.last_heartbeat_at,
        "strategy": pending or bot.strategy_name,
        "uptime_s": int(time.time() - dash.started_at),
    }


def _num(value) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def account_view(bot, dash) -> dict:
    """Account figures as the exchange portal shows them.

    The exchange's own numbers from the last /portfolio answer, unchanged, with its time: the bot
    re-reads it every RESYNC_S and FILL_RESYNC_S after a fill, so they are seconds old. Only if
    the exchange gives no totals are they computed from our cash and holdings, priced at the
    latest close (falling back to the exchange's price, never to zero).
    """
    pf = bot.portfolio
    ex = pf.exchange or {}
    initial = _num(ex.get("initial_capital")) or STARTING_CAPITAL
    common = {"initial_capital": initial, "realized_pnl": _num(ex.get("realized_pnl")),
              "charges": _num(ex.get("total_charges")), "taxes": _num(ex.get("total_taxes")),
              "as_of": pf.synced_at}
    if _num(ex.get("total_wealth")) is not None:
        total = _num(ex["total_wealth"])
        pnl = _num(ex.get("total_pnl"))
        pnl = total - initial if pnl is None else pnl
        return {**common, "source": "exchange", "total_wealth": total,
                "cash": _num(ex.get("available_cash")) if _num(ex.get("available_cash")) is not None else pf.cash,
                "invested": _num(ex.get("portfolio_market_value")),
                "unrealized_pnl": _num(ex.get("unrealized_pnl")),
                "net_pnl": pnl, "net_pnl_pct": pnl / initial * 100}
    invested = 0.0
    for ticker, qty in dict(pf.held).items():
        if qty > 0:
            price = (dash.last_close.get(ticker) or _num(pf.exchange_holding(ticker).get("current_price"))
                     or pf.avg_price.get(ticker))
            invested += qty * (price or 0.0)
    cash = pf.cash
    total = None if cash is None else cash + invested
    return {**common, "source": "bot", "cash": cash, "invested": invested, "total_wealth": total,
            "unrealized_pnl": None,
            "net_pnl": None if total is None else total - initial,
            "net_pnl_pct": None if total is None else (total / initial - 1) * 100}


def status_view(bot, dash) -> dict:
    info = dict(bot.stage_info or {})
    stage = str(info.get("stage") or "").lower()
    stats = dash.stats_view(list(bot.latencies))
    ex = bot.portfolio.exchange or {}
    # Session counts restart with every bot run; the exchange counts the whole account (as the portal).
    stats["account_orders"] = _num(ex.get("total_orders"))
    stats["account_rejected"] = _num(ex.get("rejected_orders_count"))
    return {
        "bot": bot_view(bot, dash),
        "sim": {"stage": info.get("stage"), "status": info.get("status"),
                "current_date": info.get("current_date"), "days_completed": info.get("days_completed"),
                "total_days": info.get("total_days"), "interval_seconds": info.get("interval_seconds"),
                "is_sandbox": bool(info.get("is_sandbox_stream")) or stage == "development"},
        "account": account_view(bot, dash),
        "stats": stats,
    }


def current_date(bot, dash) -> Optional[str]:
    return (bot.stage_info or {}).get("current_date") or dash.latest_date()


def positions_view(bot, dash) -> list[dict]:
    """Positions. When the exchange's last answer holds the same quantity, its own avg buy price,
    price, value and unrealized P&L are shown (as on the portal); otherwise our tax book's cost
    basis (FIFO lots, fees included). Holding date always comes from the tax book."""
    pf = bot.portfolio
    out = dash.positions_view(dict(pf.held), bot.risk.max_pos_value)
    for p in out:
        ticker = p["ticker"]
        ex = pf.exchange_holding(ticker)
        since = bot.tax.held_since(ticker)
        if ex and ex.get("quantity") == p["quantity"] and _num(ex.get("avg_buy_price")) is not None:
            price = _num(ex.get("current_price")) or p["last_close"]
            value = _num(ex.get("market_value")) or (price * p["quantity"] if price else None)
            p.update({"avg_price": _num(ex["avg_buy_price"]), "last_close": price, "value": value,
                      "unrealized_pnl": _num(ex.get("unrealized_pnl")),
                      "cap_used_pct": value / bot.risk.max_pos_value * 100 if value else None,
                      "source": "exchange"})
        else:
            avg = bot.tax.avg_cost(ticker)
            if avg:
                p["avg_price"] = avg
                p["unrealized_pnl"] = (p["last_close"] - avg) * p["quantity"] if p["last_close"] else None
            p["source"] = "bot"
        if since:
            p["held_since"] = since.isoformat()
    return out


def tax_view(bot, dash) -> dict:
    book = bot.tax
    today = current_date(bot, dash)
    summary = book.summary()
    unrealized = []
    for ticker, qty in sorted(dict(bot.portfolio.held).items()):
        price = dash.last_close.get(ticker)
        if qty > 0 and price:
            u = book.unrealized(ticker, price, today)
            unrealized.append({"ticker": ticker, "quantity": qty, "short_term": u["st"], "long_term": u["lt"]})
    d = to_date(today)
    harvest = book.harvest_candidates(today, dict(dash.last_close), window_days=366) if d else []
    return {
        "as_of": today, "financial_year": fy_of(d) if d else None,
        "rates": {"stcg": 0.15, "ltcg": 0.10, "ltcg_exemption": 100_000, "long_term_after_days": 365},
        "years": summary["years"], "total_tax_estimate": summary["total_tax"],
        "realized_gain": summary["realized_gain"], "fees_paid": summary["fees_paid"],
        "exchange_charges": _num((bot.portfolio.exchange or {}).get("total_charges")),
        "exchange_taxes": _num((bot.portfolio.exchange or {}).get("total_taxes")),
        "unrealized": unrealized,
        "harvest_candidates": [{"ticker": t, "quantity": q, "unrealized_loss": loss, "tax_saved": saved}
                               for t, q, loss, saved in harvest],
        "auto_harvest": bool(getattr(bot.strategy, "tax_harvest", False)),
        "note": "Estimate from our own FIFO lots; the exchange's tax report is authoritative.",
    }


def strategies_view(bot=None) -> list[dict]:
    out = []
    active = getattr(bot, "strategy_name", None)
    for sid in STRATEGIES:
        name, desc, recommended = STRATEGY_INFO.get(sid, (sid, "", True))
        strat = getattr(bot, "strategy", None)
        if sid == active and hasattr(strat, "notional"):
            one_buy = strat.max_position_value <= strat.notional
            desc = (f"{desc} Active sizing: Rs {strat.notional:,.0f} per buy, Rs {strat.max_position_value:,.0f} "
                    f"max per stock{' (one buy per stock)' if one_buy else ''}.")
        out.append({"id": sid, "name": name, "description": desc, "available": True,
                    "recommended": recommended})
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "MANTHANDash/1.0"

    # ---- plumbing ---------------------------------------------------
    @property
    def ctx(self):
        return self.server.ctx

    def log_message(self, fmt, *args):          # keep the bot's console readable
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload) -> None:
        self._send(code, json.dumps(payload, default=str).encode("utf-8"))

    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.ctx["hosts"]

    # ---- GET --------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        url = urlparse(self.path)
        route, query = url.path, parse_qs(url.query)
        bot, dash = self.ctx["bot"], self.ctx["dash"]
        try:
            if route == "/status":
                return self._json(200, status_view(bot, dash))
            if route == "/positions":
                return self._json(200, positions_view(bot, dash))
            if route == "/tax":
                return self._json(200, tax_view(bot, dash))
            if route == "/journal":
                return self._json(200, {"stats": bot.journal.stats(), "entries": bot.journal.recent(200)})
            if route == "/journal.csv":
                return self._send(200, bot.journal.to_csv().encode("utf-8"), "text/csv; charset=utf-8")
            if route == "/evidence":
                path = self.ctx.get("evidence_path")
                if path and os.path.isfile(path):
                    with open(path, "rb") as fh:
                        return self._send(200, fh.read())
                return self._json(200, {})
            if route == "/events":
                since = int((query.get("since") or ["0"])[0] or 0)
                return self._json(200, dash.events_since(since))
            if route == "/equity":
                return self._json(200, dash.equity_view())
            if route == "/orders":
                return self._json(200, dash.orders_view())
            if route == "/strategies":
                return self._json(200, strategies_view(bot))
            if route == "/series":
                return self._json(200, dash.series_view())
            if route == "/news":
                return self._json(200, dash.news_view())
        except ValueError:
            return self._json(400, {"error": "bad request"})
        return self._static(route)

    def _static(self, route: str) -> None:
        root = os.path.realpath(self.ctx["static_dir"])
        rel = "index.html" if route in ("", "/") else route.lstrip("/")
        path = os.path.realpath(os.path.join(root, rel))
        inside = path == root or path.startswith(root + os.sep)
        hidden = any(part.startswith(".") for part in rel.replace("\\", "/").split("/"))
        if not inside or hidden or not os.path.isfile(path):
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # ---- POST (the only write actions) ----------------------------------
    def do_POST(self):
        # Always consume the (bounded) request body first: replying and closing with unread
        # data can reset the connection under the client on Windows.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        raw = self.rfile.read(min(max(length, 0), MAX_BODY * 8))
        if not self._host_ok():
            return self._json(403, {"error": "bad host"})
        origin = self.headers.get("Origin")
        if origin and origin not in self.ctx["origins"]:
            return self._json(403, {"error": "cross-origin request refused"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"error": "application/json required"})
        if length < 0:
            return self._json(400, {"error": "bad length"})
        if length > MAX_BODY:
            return self._json(413, {"error": "body too large"})
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._json(400, {"error": "invalid JSON"})
        bot, dash = self.ctx["bot"], self.ctx["dash"]
        route = urlparse(self.path).path
        if route == "/control/start":
            bot.set_trading(True)
        elif route == "/control/stop":
            bot.set_trading(False)
        elif route == "/control/strategy":
            error = bot.request_strategy(str(body.get("id") or "") if isinstance(body, dict) else "")
            if error:
                return self._json(409, {"error": error})
        else:
            return self._json(404, {"error": "not found"})
        self._json(200, {"bot": bot_view(bot, dash)})


class _ExclusiveServer(ThreadingHTTPServer):
    """Refuse to share the port: on Windows, SO_REUSEADDR would let two dashboards bind it."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class DashboardServer:
    def __init__(self, bot, dash, static_dir: str, port: int = 8080, host: str = "127.0.0.1",
                 evidence_path: Optional[str] = None):
        self.httpd = _ExclusiveServer((host, port), _Handler)
        self.port = self.httpd.server_address[1]
        names = (f"127.0.0.1:{self.port}", f"localhost:{self.port}")
        if evidence_path is None:
            evidence_path = os.path.join(os.path.dirname(os.path.abspath(static_dir)), "docs", "evidence.json")
        self.httpd.ctx = {"bot": bot, "dash": dash, "static_dir": static_dir, "hosts": set(names),
                          "origins": {f"http://{n}" for n in names}, "evidence_path": evidence_path}
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> "DashboardServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, name="dashboard", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
