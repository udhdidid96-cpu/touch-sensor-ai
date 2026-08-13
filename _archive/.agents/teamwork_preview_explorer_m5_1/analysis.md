# Codebase Audit Report: Tele-Nursing & National Competition Requirements

## Executive Summary
This audit evaluates the codebase of **Project2 (Touch Sensor Self-Extubation Early Warning System)** against the requirements for National Competition & Patent-Grade Medical Product elevation (Milestone 5). 

The audit reveals that while the core spatio-temporal AI classifier, RBF spatial interpolator, baseline calibration (Kalman), and WebSocket live streaming exist in `main.py`, **all Milestone 5 Tele-Nursing Emergency Dispatcher features are completely missing**. Additionally, existing unit/E2E test files are broken due to API refactoring, server startup exceeds the 1-second benchmark, and 32 Pyright type errors exist across the Python files.

---

## 1. Tele-Nursing Emergency Dispatcher Audit

- **Requirement**: Asynchronous LINE Notify & Telegram Bot notification service sending instant emergency alerts (<500ms dispatch with patient bed number, severity level, CPRI score, and RBF snapshot) on Class 3 Extubation Pull and Class 2 Peel Warning events.
- **Current Status**: ❌ **NOT IMPLEMENTED (0%)**
- **Detailed Findings**:
  1. `main.py` contains **no LINE Notify API integration** (`https://notify-api.line.me/api/notify`) and **no Telegram Bot API integration** (`https://api.telegram.org/bot<token>/sendMessage` / `sendPhoto`).
  2. There is **no async notification dispatcher queue or background task manager** to trigger alerts asynchronously without blocking the <560ms frame acquisition cycle.
  3. No alert payload formatter exists to combine patient metadata (bed #), severity levels (Class 2 Peel Warning / Class 3 Extubation Alarm), CPRI risk score, and HTML5/RBF heatmap image snapshot.

---

## 2. Web UI Tele-Nursing Alert Configuration & Control Panel Audit

- **Requirement**: Interactive Tele-Nursing Settings Panel in the Web Dashboard (`main.py`) with input fields for LINE Notify token, Telegram Bot token, Telegram Chat ID, threshold preferences, a "Test Alert Dispatch" button, and backend endpoints `/api/tele-nursing/config` and `/api/tele-nursing/test-alert`.
- **Current Status**: ❌ **NOT IMPLEMENTED (0%)**
- **Detailed Findings**:
  1. **Missing Backend Endpoints**:
     - `GET /api/tele-nursing/config` - missing.
     - `POST /api/tele-nursing/config` - missing.
     - `POST /api/tele-nursing/test-alert` - missing.
  2. **Missing Frontend Controls**:
     - `DASHBOARD_HTML` (lines 1206–1463 in `main.py`) lacks the Tele-Nursing Settings Panel.
     - Missing input fields for LINE Notify token, Telegram Bot token, Telegram Chat ID, bed number, and CPRI trigger thresholds.
     - Missing the one-click "Test Alert Dispatch" trigger button and status indicators.

---

## 3. Server Port & Startup Time Audit

- **Requirement**: Server configured to run on `http://localhost:8081` with startup time < 1.0 second.
- **Current Status**: ⚠️ **PARTIALLY COMPLIANT (Port OK, Startup Exceeds Target)**
- **Detailed Findings**:
  1. **Server Port**: `main.py` uses `ap.add_argument("--port", type=int, default=8081)` and binds to `127.0.0.1:8081` by default. Compliant.
  2. **Startup Time**: Measured startup time (dataset loading + model training + app creation) is **1.258 seconds** (> 1.0s target).
     - *Root cause*: Sequential CSV file parsing across 9 subdirectories in `load_dataset()` plus standard `RandomForestClassifier(n_estimators=100)` fitting time. Optimization (e.g. pre-compiling/caching or parallel dataset read) is required to drop startup under 1.0s.

---

## 4. Code Quality & Lint Audit

- **Requirement**: Zero Flake8 lint errors and zero Pylance/Pyright type diagnostics across all Python source code.
- **Current Status**: ❌ **NON-COMPLIANT (32 Type Errors, Flake8 Ignored/Failing)**
- **Detailed Findings**:
  1. **Flake8 Errors**:
     - `main.py` line 1 and `test_normal_mix.py` line 1 use `# flake8: noqa` to suppress lint warnings. Removing `# flake8: noqa` exposes numerous PEP8 violations (line lengths >79, import positions, whitespace).
     - `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py` contain multiple PEP8 errors (E402, E302, E305, E501, W293).
  2. **Pyright Type Diagnostics (32 total errors)**:
     - `tests/test_all_endpoints.py:8` & `tests/test_serial_streaming.py:8`: `ImportError: "get_app" is unknown import symbol` (2 errors).
     - `main.py`: 10 type errors (e.g., `ndarray | None` passed to `ArrayLike`/`len()`, type mismatch on `RandomForestClassifier.fit` and `cpri`).
     - `test_normal_mix.py`: 20 type errors (e.g., `read_raw_csv` returning `ndarray | None` resulting in optional subscript/argument type errors).

---

## 5. Existing Test Suite Audit

- **Requirement**: All unit, integration, and E2E tests pass.
- **Current Status**: ❌ **FAILING (Import Errors in Test Scripts)**
- **Detailed Findings**:
  1. `tests/test_all_endpoints.py`: **FAILS** (`ImportError: cannot import name 'get_app' from 'main'`). `main.py` defines `create_app(model_holder)` instead of `get_app()`.
  2. `tests/test_serial_streaming.py`: **FAILS** (`ImportError: cannot import name 'get_app' from 'main'`).
  3. `test_normal_mix.py`: Executed directly, 25 out of 26 tests pass (1 failed: `F2 reordering is applied when loading real CSVs` fails with `KeyError` because `N_Mix_01.csv` uses `Sensor-1..25` column names while the test line 99 attempts to index `Signal-1..25` directly). Additionally, `test_normal_mix.py` has 20 Pyright type errors.

---

## Summary Table of Implementation Gaps

| Component | Target Requirement | Current State | Gap |
|---|---|---|---|
| Tele-Nursing Dispatcher | Async LINE Notify & Telegram Bot (<500ms) | None | Missing service class, HTTP async client, alert queue, payload generator |
| Web UI Control Panel | Settings Panel & `/api/tele-nursing/*` | None | Missing GET/POST config endpoints, test-alert endpoint, Dashboard HTML settings UI |
| Server Startup | Port 8081, < 1.0s startup | Port 8081, **1.258s** | Startup time exceeds limit by ~0.26s |
| Code Quality | Zero Flake8 & Zero Pyright errors | 32 Pyright errors, `# flake8: noqa` bypass | Structural type annotation fixes & lint cleanup needed |
| Test Suite | 100% passing tests | Test scripts broken | Fix `get_app()` vs `create_app()`, update endpoint names, add M5 tests |
