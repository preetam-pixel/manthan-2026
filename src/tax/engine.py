"""Indian capital-gains tax book for the simulation (Income-tax Act, 1961 as stated in the brief).

* FIFO lots per ticker; fees are part of cost (Rs 20 brokerage on the buy) and reduce
  proceeds (Rs 20 brokerage + Rs 15.34 DP charge on the sell).
* Holding <= 365 days -> short-term (STCG 15%); > 365 days -> long-term (LTCG 10%,
  first Rs 1,00,000 of LTCG per financial year exempt, Section 112A).
* Set-off within a financial year (Sections 70/71): short-term losses offset STCG first,
  then LTCG; long-term losses offset only LTCG.
* Financial year = 1 April .. 31 March of the simulated calendar.
* Loss carry-forward across years is not modelled (the brief does not describe it).

This is an estimate for decisions and the dashboard; the exchange's own tax report is
authoritative.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date as Date
from typing import Optional

BROKERAGE_INR = 20.0
DP_CHARGE_INR = 15.34
STCG_RATE = 0.15
LTCG_RATE = 0.10
LTCG_EXEMPTION = 100_000.0
LONG_TERM_DAYS = 365


def to_date(value) -> Optional[Date]:
    if isinstance(value, Date):
        return value
    try:
        return Date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def fy_of(d: Date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY{start}-{(start + 1) % 100:02d}"


def fy_end(d: Date) -> Date:
    return Date(d.year if d.month < 4 else d.year + 1, 3, 31)


@dataclass
class Lot:
    qty: int
    cost_per_share: float       # price + buy brokerage spread over the lot
    bought: Date


@dataclass(frozen=True)
class Realization:
    ticker: str
    qty: int
    gain: float
    term: str                   # "ST" | "LT"
    fy: str
    sold: Date
    held_days: int


class TaxBook:
    def __init__(self, brokerage: float = BROKERAGE_INR, dp_charge: float = DP_CHARGE_INR):
        self.brokerage, self.dp_charge = brokerage, dp_charge
        self.lots: dict[str, deque] = defaultdict(deque)
        self.realized: list[Realization] = []
        self.fees_paid = 0.0

    # ---- recording fills ------------------------------------------------
    def buy(self, ticker: str, qty: int, price: float, when) -> None:
        d = to_date(when)
        if qty <= 0 or price <= 0 or d is None:
            return
        self.fees_paid += self.brokerage
        self.lots[ticker].append(Lot(qty, price + self.brokerage / qty, d))

    def sell(self, ticker: str, qty: int, price: float, when) -> list[Realization]:
        d = to_date(when)
        if qty <= 0 or price <= 0 or d is None:
            return []
        self.fees_paid += self.brokerage + self.dp_charge
        sell_fee_per_share = (self.brokerage + self.dp_charge) / qty
        out, remaining, lots = [], qty, self.lots[ticker]
        while remaining > 0 and lots:
            lot = lots[0]
            take = min(lot.qty, remaining)
            gain = take * (price - sell_fee_per_share - lot.cost_per_share)
            held = (d - lot.bought).days
            r = Realization(ticker, take, gain, "LT" if held > LONG_TERM_DAYS else "ST", fy_of(d), d, held)
            out.append(r)
            lot.qty -= take
            remaining -= take
            if lot.qty == 0:
                lots.popleft()
        self.realized.extend(out)
        return out

    def sync_quantity(self, ticker: str, qty: int, price: float, when) -> None:
        """Align with exchange holdings we did not open ourselves (e.g. after a restart)."""
        have = self.quantity(ticker)
        if qty > have:
            d = to_date(when)
            if d is not None and price > 0:
                self.lots[ticker].append(Lot(qty - have, price, d))     # unknown basis: use current price
        elif qty < have:
            excess, lots = have - qty, self.lots[ticker]
            while excess > 0 and lots:
                take = min(lots[0].qty, excess)
                lots[0].qty -= take
                excess -= take
                if lots[0].qty == 0:
                    lots.popleft()

    # ---- queries ------------------------------------------------------------
    def quantity(self, ticker: str) -> int:
        return sum(l.qty for l in self.lots.get(ticker, ()))

    def avg_cost(self, ticker: str) -> Optional[float]:
        q = self.quantity(ticker)
        return sum(l.qty * l.cost_per_share for l in self.lots[ticker]) / q if q else None

    def held_since(self, ticker: str) -> Optional[Date]:
        lots = self.lots.get(ticker)
        return lots[0].bought if lots else None

    def unrealized(self, ticker: str, price: float, when) -> dict:
        d = to_date(when)
        st = lt = 0.0
        for lot in self.lots.get(ticker, ()):
            g = lot.qty * (price - lot.cost_per_share)
            if d is not None and (d - lot.bought).days > LONG_TERM_DAYS:
                lt += g
            else:
                st += g
        return {"st": st, "lt": lt, "total": st + lt}

    def fy_summary(self, fy: str) -> dict:
        stg = sum(r.gain for r in self.realized if r.fy == fy and r.term == "ST" and r.gain > 0)
        stl = -sum(r.gain for r in self.realized if r.fy == fy and r.term == "ST" and r.gain < 0)
        ltg = sum(r.gain for r in self.realized if r.fy == fy and r.term == "LT" and r.gain > 0)
        ltl = -sum(r.gain for r in self.realized if r.fy == fy and r.term == "LT" and r.gain < 0)
        st_net, lt_net = stg - stl, ltg - ltl
        if st_net < 0:                       # excess short-term loss may offset long-term gains
            lt_net += st_net
            st_net = 0.0
        lt_net = max(lt_net, 0.0)            # long-term loss cannot offset short-term gains
        exempt = min(lt_net, LTCG_EXEMPTION)
        tax = STCG_RATE * st_net + LTCG_RATE * (lt_net - exempt)
        return {"fy": fy, "stcg": stg, "stcl": stl, "ltcg": ltg, "ltcl": ltl,
                "taxable_st": st_net, "taxable_lt": lt_net - exempt, "ltcg_exemption_used": exempt,
                "tax": tax}

    def years(self) -> list[str]:
        return sorted({r.fy for r in self.realized})

    def total_tax(self) -> float:
        return sum(self.fy_summary(fy)["tax"] for fy in self.years())

    def summary(self) -> dict:
        years = [self.fy_summary(fy) for fy in self.years()]
        return {"years": years, "total_tax": sum(y["tax"] for y in years),
                "realized_gain": sum(r.gain for r in self.realized), "fees_paid": self.fees_paid,
                "trades_realized": len(self.realized)}

    # ---- tax-loss harvesting -------------------------------------------------
    def harvest_candidates(self, when, prices: dict, window_days: int = 10,
                           min_loss: float = 1_000.0) -> list[tuple]:
        """Positions worth selling before 31 March to offset this year's taxable gains.

        Only inside the last ``window_days`` of the financial year, only while the year
        has a positive net taxable gain, and only for losses big enough to beat fees.
        Returns [(ticker, qty, unrealized_loss, tax_saved_estimate)], biggest saving first.
        """
        d = to_date(when)
        if d is None or (fy_end(d) - d).days > window_days:
            return []
        year = self.fy_summary(fy_of(d))
        room_st = year["taxable_st"]
        room_lt = year["taxable_lt"]
        if room_st <= 0 and room_lt <= 0:
            return []
        out = []
        for ticker, lots in self.lots.items():
            price = prices.get(ticker)
            q = self.quantity(ticker)
            if not price or q <= 0:
                continue
            u = self.unrealized(ticker, price, d)
            loss = -u["total"] - (self.brokerage + self.dp_charge)
            if u["total"] < 0 and loss >= min_loss:
                saved = min(loss, room_st) * STCG_RATE + max(0.0, min(loss - room_st, room_lt)) * LTCG_RATE
                if saved > self.brokerage + self.dp_charge:
                    out.append((ticker, q, -u["total"], saved))
        return sorted(out, key=lambda x: -x[3])
