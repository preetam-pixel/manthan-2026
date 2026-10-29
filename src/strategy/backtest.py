"""Offline, chronological replay of SMAStrategy. No network, no order API.

Fills happen at the tick close (as observed in the simulator, see
docs/API_VERIFIED.md) with a flat brokerage per order. Long-only, matching the
strategy contract. Results from synthetic data say nothing about profitability.
"""
from datetime import datetime, timezone
from typing import Iterable, Optional

from src.strategy.sma import SMAStrategy

BROKERAGE_INR = 20.0


def replay(rows: Iterable[dict], starting_cash: float = 1_000_000.0,
           brokerage: float = BROKERAGE_INR) -> dict:
    """rows: dicts with ``date``, ``ticker``, ``close`` in chronological order.

    Rows are consumed one at a time; the strategy only ever sees data up to and
    including the current row (no look-ahead). Returns summary metrics.
    """
    strat = SMAStrategy()
    cash = starting_cash
    held: dict[str, int] = {}
    last_close: dict[str, float] = {}
    trades = []
    equity_curve = []
    prev_date: Optional[str] = None

    for row in rows:
        date, ticker, close = row.get("date"), row.get("ticker"), row.get("close")
        if prev_date is not None and date is not None and date < prev_date:
            raise ValueError(f"rows not chronological: {date} after {prev_date}")
        if date is not None:
            prev_date = date
        if ticker is None or close is None or close <= 0:
            continue  # missing/invalid price: abstain, never treat as zero
        ts = datetime.fromisoformat(date).replace(tzinfo=timezone.utc) if date else datetime.now(timezone.utc)
        sig = strat.on_close(ticker, close, held.get(ticker, 0), ts)
        last_close[ticker] = close
        if sig is not None:
            cost = sig.quantity * close
            if sig.action == "BUY":
                if cost + brokerage <= cash:
                    cash -= cost + brokerage
                    held[ticker] = held.get(ticker, 0) + sig.quantity
                    trades.append((date, ticker, "BUY", sig.quantity, close))
            else:
                cash += cost - brokerage
                held[ticker] = held.get(ticker, 0) - sig.quantity
                trades.append((date, ticker, "SELL", sig.quantity, close))
        equity = cash + sum(q * last_close[t] for t, q in held.items())
        equity_curve.append(equity)

    final = equity_curve[-1] if equity_curve else starting_cash
    peak, max_dd = starting_cash, 0.0
    for e in equity_curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    return {
        "starting_cash": starting_cash,
        "final_equity": final,
        "return_pct": (final / starting_cash - 1) * 100,
        "max_drawdown_pct": max_dd * 100,
        "trades": len(trades),
        "open_positions": {t: q for t, q in held.items() if q},
        "trade_log": trades,
    }


def walk_forward(rows: list[dict], windows: int, **kw) -> list[dict]:
    """Replay consecutive, non-overlapping chronological windows.

    The strategy has fixed parameters (nothing is fitted), so each window is an
    independent out-of-sample replay with fresh warm-up.
    """
    if windows < 1:
        raise ValueError("windows must be >= 1")
    size = len(rows) // windows
    out = []
    for i in range(windows):
        chunk = rows[i * size:(i + 1) * size] if i < windows - 1 else rows[i * size:]
        out.append(replay(chunk, **kw))
    return out
