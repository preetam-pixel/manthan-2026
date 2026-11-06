"""Replay every registered strategy over saved history in three windows.

Usage: py -m scripts.evaluate_strategies history.json
history.json: {"TICKER": [{"date","open","high","low","close","volume"}, ...], ...}
(as returned in `prices` by GET /api/v1/stocks/:ticker/history). Offline only.
"""
import json
import sys

from src.strategy.backtest import replay
from src.strategy.registry import STRATEGIES

data = json.load(open(sys.argv[1]))
rows = sorted(({"ticker": t, **b} for t, bars in data.items() for b in bars),
              key=lambda r: (r["date"], r["ticker"]))
dates = sorted({r["date"] for r in rows})
n = len(dates)
windows = {"ALL": (0, n), "W1": (0, n * 47 // 100), "W2": (n * 33 // 100, n * 76 // 100), "W3": (n * 54 // 100, n)}


def sub(a, b):
    keep = set(dates[a:b])
    return [r for r in rows if r["date"] in keep]


print(f"{'strategy':20}" + "".join(f"{w:>26}" for w in windows))
print(f"{'':20}" + "".join(f"{'ret%  maxDD%  trades':>26}" for _ in windows))
for name, factory in STRATEGIES.items():
    line = f"{name:20}"
    for a, b in windows.values():
        r = replay(sub(a, b), strategy_factory=factory)
        line += f"{r['return_pct']:>9.2f}{r['max_drawdown_pct']:>8.2f}{r['trades']:>9d}"
    print(line)
