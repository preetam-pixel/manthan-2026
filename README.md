# MANTHAN 2026 — Bot-Integrated Scaffold

Based on the uploaded `bot.py` and `HANDOFF.md`, not a generic trading-bot template.

- Original bot preserved at `src/legacy/bot_original.py`.
- Current SMA settings and behavior captured in `CONTRACTS.md` and `config/strategy.yaml`.
- Kafka topics, event names, REST routes, and order actions transcribed from the handoff.
- Modules split into market data, news, strategy, risk, execution, portfolio, app lifecycle, and frontend.

This is a migration scaffold; the new modules are not fully wired into a runnable trading system. Verify and test before enabling orders.

Run checks:
```bash
pip install -r requirements.txt
pytest
```

`python -m src.app` is a safe stub. Do not point it at the simulator until reviewed.
