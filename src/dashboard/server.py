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


def status_view(bot, dash) -> dict:
    info = dict(bot.stage_info or {})
    stage = str(info.get("stage") or "").lower()
    invested = sum(q * dash.last_close.get(t, 0.0) for t, q in dict(bot.portfolio.held).items() if q > 0)
    cash = bot.portfolio.cash
    total = None if cash is None else cash + invested
    return {
        "bot": bot_view(bot, dash),
        "sim": {"stage": info.get("stage"), "status": info.get("status"),
                "current_date": info.get("current_date"), "days_completed": info.get("days_completed"),
                "total_days": info.get("total_days"), "interval_seconds": info.get("interval_seconds"),
                "is_sandbox": bool(info.get("is_sandbox_stream")) or stage == "development"},
        "account": {"cash": cash, "invested": invested, "total_wealth": total,
                    "net_pnl": None if total is None else total - STARTING_CAPITAL,
                    "net_pnl_pct": None if total is None else (total / STARTING_CAPITAL - 1) * 100},
        "stats": dash.stats_view(list(bot.latencies)),
    }


def current_date(bot, dash) -> Optional[str]:
    return (bot.stage_info or {}).get("current_date") or dash.latest_date()


def positions_view(bot, dash) -> list[dict]:
    """Positions with cost basis and holding date from the tax book (FIFO lots, fees included)."""
    out = dash.positions_view(dict(bot.portfolio.held), bot.risk.max_pos_value)
    for p in out:
        avg = bot.tax.avg_cost(p["ticker"])
        since = bot.tax.held_since(p["ticker"])
        if avg:
            p["avg_price"] = avg
            p["unrealized_pnl"] = (p["last_close"] - avg) * p["quantity"] if p["last_close"] else None
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
        "unrealized": unrealized,
        "harvest_candidates": [{"ticker": t, "quantity": q, "unrealized_loss": loss, "tax_saved": saved}
                               for t, q, loss, saved in harvest],
        "auto_harvest": bool(getattr(bot.strategy, "tax_harvest", False)),
        "note": "Estimate from our own FIFO lots; the exchange's tax report is authoritative.",
    }


def strategies_view() -> list[dict]:
    out = []
    for sid in STRATEGIES:
        name, desc, recommended = STRATEGY_INFO.get(sid, (sid, "", True))
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
                return self._json(200, strategies_view())
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


class DashboardServer:
    def __init__(self, bot, dash, static_dir: str, port: int = 8080, host: str = "127.0.0.1",
                 evidence_path: Optional[str] = None):
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
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
