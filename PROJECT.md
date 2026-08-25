# Project: Smart Extubation Early Warning (Project2)

## Architecture
- **Backend (`main.py`)**: Asynchronous clinical monitoring system (FastAPI, Uvicorn, scikit-learn). Serves REST API, WebSocket streams (`/ws/live_sensor`), and data endpoints. Model: `HistGradientBoostingClassifier` on 34 features with 7-of-6 hold 9 debouncer.
- **Frontend (`web/`)**: Operator console (`index.html`, `style.css`, `app.js`, `web_serial.js`). Opaque rendering and communication layer. Zero client-side classification or heuristics.
- **Data Corpus (`Data/`)**: 81 bench recordings across 9 classes. Immutable reference corpus.
- **Test Suite (`tests/`)**: 113+ automated tests enforcing behavioral guards, invariant contracts, and regression limits.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | FE-01: Audit Trail Logging Fix | Reset `state.lastLoggedLevel = null` on `lvl < 2` to prevent dropping repeating clinical alarms | M1 | Frontend Survey |
| 2 | FE-02: `state.lastLevel` Tracking | Maintain `state.lastLevel` in `renderFrame()` for language switch synchronization | M1 | Frontend Survey |
| 3 | FE-03: Replay Timer Pause on Live Switch | Pause replay interval timer when switching dashboard mode to Live | M1 | Frontend Survey |
| 4 | FE-04: WebSocket Reconnect Stale Guard | Check socket instance identity before resetting streaming UI on `onclose`/`onerror` | M1 | Frontend Survey |
| 5 | FE-05: Web Serial Disconnect on Error | Ensure `disconnectWebSerial()` is invoked on stream read exception or hardware unplug | M1 | Frontend Survey |
| 6 | FE-06: Web Audio Autoplay Unlock | Attach user interaction listeners to unlock AudioContext on first gesture | M1 | Frontend Survey |
| 7 | BE-01: WebSocket Auth Exception Safety | Wrap pre-accept WebSocket close in exception handler for disconnect safety | M2 | Backend Survey |
| 8 | BE-02: Auth Failure Table Pruning | Routine cleanup of expired IP throttle entries to bound memory usage | M2 | Backend Survey |
| 9 | TEST-01: Dockerfile Invariant 6 Guard | Static test asserting `Dockerfile` contains no `--allow-public-no-key` | M3 | Test Survey |
| 10 | TEST-02: Simulator WebSocket Test | Automated test covering `/ws/live_sensor?source=simulator` | M3 | Test Survey |
| 11 | TEST-03: Event Log Bounds & Validation | Tests for boundary floats, NaN/Inf, and ranges on `/api/v6/event-log` | M3 | Test Survey |
| 12 | TEST-04: Localization Dictionary Parity | Test verifying all keys in `en` exist in `th` and `ja` | M3 | Test Survey |
| 13 | VERIF-01: Full Multi-Pass Verification | End-to-end suite passing, pad verification, corpus audit, metrics reproducibility | M4 | System Invariants |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Frontend & WebSerial Hardening | Remediate FE-01 to FE-06 in `web/app.js` and `web/web_serial.js` | none | PLANNED |
| M2 | Backend Concurrency & Auth Hardening | Remediate BE-01 and BE-02 in `main.py` | none | PLANNED |
| M3 | Test Suite Expansion & Edge-Case Guards | Implement TEST-01 to TEST-04 in `tests/` | M1, M2 | PLANNED |
| M4 | Comprehensive Multi-Pass Verification & Audit | Execute all verification commands and forensic integrity check | M1, M2, M3 | PLANNED |

## Interface Contracts
### Client ↔ Server Communication
- REST API: JSON endpoints under `/api/v5/` and `/api/v6/`. Key query parameter `?key=` for non-loopback authentication.
- WebSockets: `/ws/live_sensor` accepts `?source=client|serial|replay|simulator&key=...`.
- Framing: Frames sent to `/ws/live_sensor?source=client` must contain 25 numeric floats representing raw sensor counts.
- Response payload: Server emits JSON dictionary containing `severity_level`, `cpri_percent`, `propagation`, and `probabilities`.

## Code Layout
- `main.py`: Backend server, API routes, WebSocket streaming, model classification, CLI verification tools.
- `web/index.html`: Web operator console markup.
- `web/style.css`: Web console styling & theme tokens.
- `web/app.js`: Web console client-side state, rendering, telemetry display, chart management, audio alarms.
- `web/web_serial.js`: Web Serial API hardware bridge for browser-to-sensor communication.
- `Data/`: 81 raw CSV recordings and `metrics.json`.
- `tests/`: Pytest suite (`test_all_endpoints.py`, `test_next_gen_features.py`, `test_serial_streaming.py`, `test_regressions.py`, `conftest.py`).
