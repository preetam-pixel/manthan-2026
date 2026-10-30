\# MANTHAN 2026 — MarketPulse Demo Runbook



\## 1. Purpose



Demonstrate the simulated stock-trading system, its strategy decisions, risk controls, portfolio reconciliation, and QA evidence.



\## 2. Current QA Status



\- Unit tests collected: 116

\- Unit tests passed: 116

\- Test failures in the recorded run: 0

\- Live simulator and Kafka integration: Not yet verified according to README.md.



Passing unit tests do not establish that the complete live system is operational.



\## 3. Pre-Demo Checklist



\- \[ ] Run from the project root.

\- \[ ] Confirm dependencies are installed using `python -m pip install -r requirements.txt`.

\- \[ ] Run `python -m pytest -q`.

\- \[ ] Confirm the expected test results.

\- \[ ] Review `CONTRACTS.md` and `docs/API\_VERIFIED.md`.

\- \[ ] Confirm the simulator environment and permitted operating mode with the backend owner.

\- \[ ] Never expose authentication tokens or other secrets.

\- \[ ] Keep a fallback using test output and prepared screenshots.



\## 4. Demo Flow



1\. Introduce MarketPulse and explain that it is a simulated trading system.

2\. Explain the market-data input and supported ticker universe.

3\. Explain the SMA8 strategy and its documented entry/exit thresholds.

4\. Show how a signal passes through the risk manager.

5\. Explain how an approved order is submitted through the execution adapter.

6\. Show portfolio reconciliation and resulting holdings/cash when verified evidence is available.

7\. Explain that news is informational and is not itself a trade trigger.

8\. Present QA results and discuss limitations.



Only demonstrate live order submission after the environment and integration have been explicitly verified.



\## 5. Important QA Scenarios



\- Normal market snapshot and valid signal.

\- Stale or missing market data.

\- Duplicate tick or signal.

\- Insufficient cash or position limit.

\- API timeout, malformed response, or uncertain order status.

\- Paused or completed simulation.

\- News timestamp after the trading decision.

\- Portfolio reconciliation and rejected orders.



For each scenario, record the test name, expected behavior, actual result, and pass/fail status.



\## 6. Fallback Plan



If the live simulator, Kafka, or API is unavailable:



1\. Do not repeatedly retry uncertain orders.

2\. Use recorded pytest output as evidence of unit-test results.

3\. Use prepared screenshots or mock fixtures to explain the expected workflow.

4\. Clearly label mocked behavior and previously recorded results.

5\. Do not present simulated screenshots as proof of live integration.



\## 7. Limitations



\- Unit tests use fakes; live integration is not yet confirmed.

\- Historical backtest results do not guarantee future performance.

\- Strategy evaluation and market-data limitations should be explained using `docs/STRATEGY\_EVAL.md`.

\- Any remaining integration failures must be disclosed.



\## 8. Final Sign-Off



\- \[ ] QA results recorded.

\- \[ ] Demo steps rehearsed.

\- \[ ] Fallback evidence prepared.

\- \[ ] Live integration status accurately disclosed.

\- \[ ] Final presentation reviewed by the team.

