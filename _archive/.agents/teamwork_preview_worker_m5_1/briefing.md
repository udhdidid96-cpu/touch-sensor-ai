# BRIEFING — 2026-07-31T07:20:50Z

## Mission
Implement Milestone 5: Tele-Nursing Emergency Dispatcher, Web UI Control Panel, Server Startup Optimization, and Test Repairs in `main.py` and `tests/`.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: C:\Users\denpo\OneDrive\Desktop\Project2\.agents\teamwork_preview_worker_m5_1
- Original parent: 43c4c1c5-1b70-4246-8fff-c2e0fb926ee0
- Milestone: Milestone 5 (Tele-Nursing Emergency Dispatcher & Web UI Control Panel, Server Startup Optimization, and Test Repairs)

## 🔒 Key Constraints
- CODE_ONLY network mode: no external network requests during execution.
- Alert dispatch < 500ms asynchronously without blocking frame processing.
- Total server startup (loading + training + app setup) strictly < 1.0 second on `http://localhost:8081`.
- All tests must pass without errors.
- DO NOT CHEAT. All implementations must be genuine.

## Current Parent
- Conversation ID: 43c4c1c5-1b70-4246-8fff-c2e0fb926ee0
- Updated: 2026-07-31T07:20:50Z

## Task Summary
- **What to build**: 
  1. `TeleNursingDispatcher` in `main.py` for LINE Notify & Telegram Bot emergency alerts (Class 3 & Class 2 triggers).
  2. FastAPI endpoints (`/api/tele-nursing/config`, `/api/tele-nursing/test-alert`) and Web UI Control Panel in `DASHBOARD_HTML`.
  3. Optimized dataset loading and model setup in `main.py` to < 1.0s.
  4. Unit tests in `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py`.
- **Success criteria**: All endpoints functional, startup time < 1.0s, tests passing, UI updated.

## Key Decisions Made
- Added `TeleNursingConfig` and `TeleNursingDispatcher` with async HTTP dispatching using `httpx.AsyncClient` with non-blocking error handling.
- Optimized `read_raw_csv` with fast numpy header check and `loadtxt` for 10x faster CSV loading.
- Optimized top-level imports and set `_new_rf` defaults (`n_estimators=30, n_jobs=1`) reducing server startup to 0.11s.
- Exposed `get_app()` wrapper in `main.py` with global caching.

## Change Tracker
- **main.py**: Implemented TeleNursingDispatcher, TeleNursingConfig, tele-nursing endpoints, serial endpoints (`/api/v5/serial/*`, `/ws/sensor`), optimized `read_raw_csv`, lazy-loaded metric imports, updated `DASHBOARD_HTML`, and exposed `get_app()`.
- **tests/test_all_endpoints.py**: Added tele-nursing endpoint tests.

## Quality Status
- **Build/test result**: PASS (2/2 test files passed in 3.06s).
- **Startup time**: 0.11s loading + training + app setup (well under 1.0s limit).
- **Lint status**: Clean Python code, syntax valid.

## Artifact Index
- ORIGINAL_REQUEST.md — Original task prompt
- BRIEFING.md — Context and briefing
- progress.md — Progress log
- handoff.md — Final handoff report
