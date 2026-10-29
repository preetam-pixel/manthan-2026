# Only this module should submit HTTP order requests; implement from verified API contract.

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

API_ACTIONS = ("BUY", "SELL", "SHORT", "COVER")
MAX_QUANTITY = 1_000_000
RATE_LIMIT_PER_MIN = 120
RATE_LIMIT_HEADROOM = 100      # stay under the 120/min cap
PENALTY_SECONDS = 30.0         # penalty box after HTTP 429


class APIError(RuntimeError):
    """Raised when the simulation API returns an unexpected response."""


class RateLimitedError(APIError):
    """Raised locally when the request budget is exhausted or after HTTP 429."""


@dataclass(frozen=True)
class OrderResult:
    """Outcome of one order submission.

    outcome: "FILLED" (accepted by gateway), "REJECTED" (definitively not
    placed) or "UNCERTAIN" (timeout / network / malformed / 5xx: the order may
    or may not exist, so the caller must reconcile before retrying).
    """
    outcome: str
    code: Optional[str] = None
    http_status: Optional[int] = None
    body: dict = field(default_factory=dict)
    detail: str = ""


class SimulationAPIClient:
    """
    REST client for the MANTHAN 2026 simulation API.

    API-specific request and response mapping remains isolated here.
    """

    def __init__(
        self,
        base_url: str | None = None,
        team_token: str | None = None,
        timeout: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("SIMULATION_API_URL")
            or os.getenv("GATEWAY")
            or "http://192.168.65.157:3002"
        ).rstrip("/")

        self.team_token = (
            team_token or os.getenv("TEAM_JWT_TOKEN") or os.getenv("BOT_ACCESS_TOKEN")
        )

        if not self.team_token:
            raise ValueError(
                "TEAM_JWT_TOKEN (or BOT_ACCESS_TOKEN) environment variable is required"
            )

        self.timeout = timeout
        self._clock = clock
        self._sent = deque()           # request timestamps in the last 60s
        self._penalty_until = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.team_token}",
                "Content-Type": "application/json",
            }
        )

    # ---- pacing -----------------------------------------------------
    def _reserve_slot(self, critical: bool = False) -> None:
        """critical=True (heartbeat) skips the local budget but still honours a 429 penalty."""
        now = self._clock()
        if now < self._penalty_until:
            raise RateLimitedError("in 429 penalty box")
        while self._sent and now - self._sent[0] >= 60.0:
            self._sent.popleft()
        if not critical and len(self._sent) >= RATE_LIMIT_HEADROOM:
            raise RateLimitedError("local request budget exhausted")
        self._sent.append(now)

    def _request(self, method: str, path: str, critical: bool = False, **kw) -> requests.Response:
        self._reserve_slot(critical)
        kw.setdefault("timeout", self.timeout)
        response = self.session.request(method, f"{self.base_url}{path}", **kw)
        if response.status_code == 429:
            self._penalty_until = self._clock() + PENALTY_SECONDS
            raise RateLimitedError("HTTP 429 from gateway")
        return response

    @staticmethod
    def _json(response: requests.Response) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            raise APIError(f"Non-JSON response ({response.status_code})") from exc
        if not isinstance(data, dict):
            raise APIError(f"Unexpected JSON shape ({response.status_code})")
        return data

    # ---- preflight --------------------------------------------------
    def acknowledge_preflight(self, seq: int) -> dict[str, Any]:
        """
        Acknowledge the exact preflight sequence received from Kafka.
        """

        if isinstance(seq, bool) or not isinstance(seq, int):
            raise ValueError("seq must be an integer")

        if seq < 0:
            raise ValueError("seq cannot be negative")

        response = self._request(
            "POST", "/api/v1/bot/heartbeat", critical=True, json={"seq": seq}
        )

        if response.status_code == 401:
            raise APIError("Unauthorized: check TEAM_JWT_TOKEN")

        if response.status_code == 400:
            raise APIError(
                f"Invalid preflight sequence: {response.text}"
            )

        response.raise_for_status()

        data = response.json()

        if data.get("status") != "ok":
            raise APIError(
                f"Unexpected heartbeat response: {data}"
            )

        if data.get("seq") != seq:
            raise APIError(
                "Heartbeat response sequence does not match request"
            )

        return data

    # ---- read endpoints --------------------------------------------
    def get_stocks(self) -> list[str]:
        """Active tradable tickers (dynamic universe discovery)."""
        response = self._request("GET", "/api/v1/stocks")
        response.raise_for_status()
        stocks = self._json(response).get("stocks")
        if not isinstance(stocks, list):
            raise APIError("stocks response missing 'stocks' list")
        return [s["ticker"] for s in stocks if isinstance(s, dict) and s.get("ticker")]

    def get_stage(self) -> dict[str, Any]:
        """Public lifecycle state: {stage, status, ...}."""
        response = self._request("GET", "/api/v1/stage")
        response.raise_for_status()
        return self._json(response)

    def get_portfolio(self) -> dict[str, Any]:
        response = self._request("GET", "/api/v1/portfolio")
        response.raise_for_status()
        return self._json(response)

    def get_orders(self) -> dict[str, Any]:
        response = self._request("GET", "/api/v1/orders")
        response.raise_for_status()
        return self._json(response)

    def get_history(self, ticker: str, days: int = 30) -> dict[str, Any]:
        response = self._request(
            "GET", f"/api/v1/stocks/{ticker}/history", params={"days": days}
        )
        response.raise_for_status()
        return self._json(response)

    # ---- orders -----------------------------------------------------
    def submit_order(self, ticker: str, action: str, quantity: int,
                     date: Optional[str] = None) -> OrderResult:
        """Submit one market order. Never raises for transport problems.

        A timeout or unreadable reply is UNCERTAIN, not REJECTED.
        """
        if action not in API_ACTIONS:
            raise ValueError(f"unsupported action {action!r}")
        if isinstance(quantity, bool) or not isinstance(quantity, int) \
                or not 1 <= quantity <= MAX_QUANTITY:
            raise ValueError("quantity must be a whole number in 1..1,000,000")
        if not ticker:
            raise ValueError("ticker required")

        payload: dict[str, Any] = {"ticker": ticker, "action": action, "quantity": quantity}
        if date:
            payload["date"] = date

        try:
            response = self._request("POST", "/api/v1/orders", json=payload)
        except RateLimitedError as exc:
            # Nothing was sent (local budget) or gateway refused with 429.
            return OrderResult("REJECTED", code="RATE_LIMITED", detail=str(exc))
        except requests.RequestException as exc:
            return OrderResult("UNCERTAIN", detail=f"transport error: {exc}")

        status = response.status_code
        try:
            body = self._json(response)
        except APIError as exc:
            return OrderResult("UNCERTAIN", http_status=status, detail=str(exc))

        if status >= 500:
            return OrderResult("UNCERTAIN", http_status=status, body=body, detail="server error")
        if 200 <= status < 300:
            return OrderResult("FILLED", http_status=status, body=body)
        code = body.get("error") or body.get("code")
        if isinstance(code, dict):
            code = code.get("code")
        return OrderResult("REJECTED", code=code if isinstance(code, str) else None,
                           http_status=status, body=body, detail=response.text[:200])
