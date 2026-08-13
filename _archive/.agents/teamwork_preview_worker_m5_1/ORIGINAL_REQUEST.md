## 2026-07-31T07:11:19Z

You are a Worker subagent (teamwork_preview_worker).
Your working directory is: C:\Users\denpo\OneDrive\Desktop\Project2\.agents\teamwork_preview_worker_m5_1
The project workspace is: C:\Users\denpo\OneDrive\Desktop\Project2

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your mission is to implement Milestone 5 (Tele-Nursing Emergency Dispatcher & Web UI Control Panel, Server Startup Optimization, and Test Repairs) in `main.py` and `tests/`.

Tasks:
1. **Tele-Nursing Emergency Dispatcher**:
   - Implement an async `TeleNursingDispatcher` in `main.py` capable of sending emergency alerts via LINE Notify (`https://notify-api.line.me/api/notify`) and Telegram Bot (`https://api.telegram.org/bot<token>/sendMessage` & `/sendPhoto`).
   - Must trigger automatically when Class 3 Extubation Alarm or Class 2 Peel Warning events are predicted.
   - Must complete alert dispatch in < 500ms asynchronously without blocking frame processing.
   - Alert payload must include Patient Bed #, Severity Level, CPRI Risk Score, Timestamp, and RBF snapshot matrix/summary.

2. **Web UI Tele-Nursing Control Panel**:
   - Add FastAPI endpoints:
     - `GET /api/tele-nursing/config`
     - `POST /api/tele-nursing/config`
     - `POST /api/tele-nursing/test-alert`
   - Update `DASHBOARD_HTML` in `main.py` to add a responsive Tele-Nursing Settings Panel with fields for LINE token, Telegram token, Telegram Chat ID, Bed Number, thresholds, and a "Test Alert Dispatch" button with live latency/status feedback.

3. **Server Startup Optimization**:
   - Optimize dataset loading and model setup in `main.py` so total server startup (loading + training + app setup) takes strictly < 1.0 second on `http://localhost:8081`.

4. **Fix Unit Tests**:
   - Update `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py` (e.g. expose `get_app()` wrapper or update test imports) so all tests run and pass without errors.

Verify your changes by running tests, measuring startup time, and testing the tele-nursing endpoints.
Write your report and handoff details to `C:\Users\denpo\OneDrive\Desktop\Project2\.agents\teamwork_preview_worker_m5_1\handoff.md` and send a message back to orchestrator.
