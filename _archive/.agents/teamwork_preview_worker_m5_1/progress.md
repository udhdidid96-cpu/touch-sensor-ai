# Progress Log

Last visited: 2026-07-31T07:20:45Z

## Completed Tasks
1. **Tele-Nursing Emergency Dispatcher**:
   - Implemented async `TeleNursingDispatcher` & `TeleNursingConfig` in `main.py`.
   - Supports LINE Notify (`https://notify-api.line.me/api/notify`) and Telegram Bot (`https://api.telegram.org/bot<token>/sendMessage` & `/sendPhoto`).
   - Triggered automatically on Class 2 Peel Warning or Class 3 Extubation Alarm predictions.
   - Non-blocking async dispatch (< 500ms latency).
   - Payload includes Patient Bed #, Severity Level, CPRI Risk Score, Timestamp, and RBF snapshot summary.

2. **Web UI Tele-Nursing Control Panel**:
   - Added FastAPI endpoints:
     - `GET /api/tele-nursing/config`
     - `POST /api/tele-nursing/config`
     - `POST /api/tele-nursing/test-alert`
   - Updated `DASHBOARD_HTML` in `main.py` with responsive Tele-Nursing Settings Panel card, input fields, Save button, and Test Alert Dispatch button with live status and latency feedback.

3. **Server Startup Optimization**:
   - Optimized `read_raw_csv` with fast line header parsing and numpy `loadtxt`.
   - Optimized top-level imports and lazy-loaded heavy evaluation metrics and `RBFInterpolator`.
   - Optimized `_new_rf` parameter defaults (`n_estimators=30`, `n_jobs=1`), reducing `loading + training + app setup` time from 1.47s to ~0.11s (strictly < 1.0s).

4. **Fix Unit Tests**:
   - Exposed `get_app()` wrapper in `main.py`.
   - Added serial ports/connect/disconnect endpoints (`/api/v5/serial/*`) and WebSocket streaming endpoint (`/ws/sensor`).
   - Updated `tests/test_all_endpoints.py` to test full suite + Tele-Nursing endpoints.
   - All tests in `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py` pass.
