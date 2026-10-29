"""Offline, chronological replay of any registered strategy. No network, no order API.

Fills happen at the tick close (as observed in the simulator, see
docs/API_VERIFIED.md) with flat brokerage per order plus the DP charge on
delivery sells. Taxes are NOT modelled. Long-only, matching the strategy
contract. Results from synthetic data say nothing about profitability.
"""
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from src.contracts import Signal
from src.strategy.sma import SMAStrategy
from src.tax.engine import TaxBook

BROKERAGE_INR = 20.0
DP_CHARGE_INR = 15.34


def replay(rows: Iterable[dict], starting_cash: float = 1_000_000.0,
           brokerage: float = BROKERAGE_INR, dp_charge: float = DP_CHARGE_INR,
           strategy_factory: Callable = SMAStrategy, tax_harvest: bool = False,
           drawdown_brake: Optional[float] = None) -> dict:
    """rows: dicts with ``date``, ``ticker``, ``close`` (plus open/high/low/volume
    for bar-based strategies) in chronological order.

    Rows are consumed one at a time; the strategy only ever sees data up to and
    including the current row (no look-ahead). Returns summary metrics, including an
    Indian capital-gains tax estimate (src/tax/engine.py) and the after-tax result.
    With ``tax_harvest`` the same year-end loss-harvesting overlay the live bot uses
    sells losing positions in the last days before 31 March when that saves tax.
    With ``drawdown_brake`` (e.g. 0.06) new BUYs are skipped while equity is more than
    that fraction below its running peak (exits are always allowed), like the live
    risk manager.
    """
    strat = strategy_factory()
    book = TaxBook(brokerage, dp_charge)
    harvested = braked = 0
    peak_equity = starting_cash
    cash = starting_cash
    held: dict[str, int] = {}
    last_close: dict[str, float] = {}
    trades = []
    fees = 0.0
    equity_curve = []
    equity_by_date: dict = {}
    invested_fracs = []
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
        if hasattr(strat, "on_bar"):
            sig = strat.on_bar(ticker, row, held.get(ticker, 0), ts)
        else:
            sig = strat.on_close(ticker, close, held.get(ticker, 0), ts)
        last_close[ticker] = close
        if sig is None and tax_harvest and held.get(ticker, 0) > 0:
            for t, qty, _loss, _saved in book.harvest_candidates(date, {ticker: close}):
                if t == ticker:
                    sig = Signal(ticker, "SELL", qty, ts, "tax-loss harvest")
                    harvested += 1
        if sig is not None and sig.action == "BUY" and drawdown_brake is not None and equity_curve:
            if (peak_equity - equity_curve[-1]) / peak_equity > drawdown_brake:
                sig = None
                braked += 1
        if sig is not None:
            cost = sig.quantity * close
            if sig.action == "BUY":
                if cost + brokerage <= cash:
                    cash -= cost + brokerage
                    fees += brokerage
                    held[ticker] = held.get(ticker, 0) + sig.quantity
                    book.buy(ticker, sig.quantity, close, date)
                    trades.append((date, ticker, "BUY", sig.quantity, close))
            elif held.get(ticker, 0) >= sig.quantity:
                cash += cost - brokerage - dp_charge
                fees += brokerage + dp_charge
                held[ticker] -= sig.quantity
                book.sell(ticker, sig.quantity, close, date)
                trades.append((date, ticker, "SELL", sig.quantity, close))
        equity = cash + sum(q * last_close[t] for t, q in held.items())
        equity_curve.append(equity)
        if date is not None:
            equity_by_date[date] = equity
        peak_equity = max(peak_equity, equity)
        invested_fracs.append((equity - cash) / equity if equity > 0 else 0.0)

    final = equity_curve[-1] if equity_curve else starting_cash
    tax = book.total_tax()
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
        "fees_paid": fees,
        "tax_estimate": tax,
        "after_tax_return_pct": ((final - tax) / starting_cash - 1) * 100,
        "tax_years": book.summary()["years"],
        "harvest_sells": harvested,
        "brake_skips": braked,
        "avg_utilization_pct": 100 * sum(invested_fracs) / len(invested_fracs) if invested_fracs else 0.0,
        "open_positions": {t: q for t, q in held.items() if q},
        "equity_by_date": equity_by_date,
        "trade_log": trades,
    }


def compare(rows: list[dict], factories: dict[str, Callable], **kw) -> dict[str, dict]:
    """Replay the same rows through several strategies for a like-for-like comparison."""
    return {name: replay(rows, strategy_factory=f, **kw) for name, f in factories.items()}


def walk_forward(rows: list[dict], windows: int, **kw) -> list[dict]:
    """Replay consecutive, non-overlapping chronological windows.

    Parameters are fixed (nothing is fitted), so each window is an independent
    out-of-sample replay with fresh warm-up.
    """
    if windows < 1:
        raise ValueError("windows must be >= 1")
    size = len(rows) // windows
    out = []
    for i in range(windows):
        chunk = rows[i * size:(i + 1) * size] if i < windows - 1 else rows[i * size:]
        out.append(replay(chunk, **kw))
    return out
