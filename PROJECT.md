# Project: Smart Extubation Early Warning (Project2) — Hardening & Vulnerability Remediation

## Architecture
- **Backend (`main.py`)**: Asynchronous clinical monitoring system (FastAPI, Uvicorn, scikit-learn). Serves REST API, WebSocket streams (`/ws/live_sensor`), and data endpoints. Model: `HistGradientBoostingClassifier` on 34 features with 7-of-6 hold 9 debouncer. Scale-normalized delta integration $\widetilde{\Delta C}_i = (\Delta C_i / C_{0, i}) \times 28000.0$.
- **Frontend (`web/`)**: Operator console (`index.html`, `style.css`, `app.js`, `web_serial.js`). Strictly bounded ring buffers (50 points), recycled Web Audio nodes, WebSerial hardware watchdog (<1.5s disconnect). Zero client-side classification or heuristics.
- **Data Corpus (`Data/`)**: 81 bench recordings across 9 classes. Immutable reference corpus.
- **Test Suite (`tests/`)**: Comprehensive regression and adversarial guard suite (fuzzing, disconnect bursts, memory bounds, domain generalization, invariant checks).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F1: WebSocket Malformed JSON Resilience | Wrap `ws.receive_json()` in local try/except block to drop corrupt packets without crashing session | M1 | Explorer 1 |
| 2 | F2: LivePipeline Bounds & Spike Filtering | Reject signed 16-bit underflow (<0 counts) and filter extreme electrical surges (>50,000 counts) | M1 | Explorer 1 |
| 3 | F3: Kalman Baseline Seed Transients Guard | Validate seed frame against physical plausibility bounds to prevent startup baseline poisoning | M1 | Explorer 1 |
| 4 | F4: SerialFrameSource Sub-1.5s Disconnect | Set `IDLE_TIMEOUT_S = 1.2s` and serial read timeout to 0.2s for clean <1.5s disconnect transition | M1 | Explorer 1 |
| 5 | F5: Serial Loop Thread Teardown & Port Retry | Ensure `_stop.is_set()` checked on read exceptions and add retry loop for transient USB enumeration | M1 | Explorer 1 |
| 6 | F6: Telemetry Ring Buffer Strict Bounds | Enforce `while (length > 50) shift()` in `web/app.js` and eliminate per-frame allocations in `web_serial.js` | M2 | Explorer 2 |
| 7 | F7: Web Audio Node Lifecycle Cleanup | Add `osc.onended` node disconnects with fallback cleanup timer and siren debouncing in `web/app.js` | M2 | Explorer 2 |
| 8 | F8: WebSerial Buffer & Line Length Capping | Cap chunk buffer at 4KB, bound line length at 512 chars, validate 25-28 token counts in `web_serial.js` | M2 | Explorer 2 |
| 9 | F9: Client Hardware Disconnect Watchdog | Add `navigator.serial` disconnect listener and 1.5s frame silence watchdog in `web_serial.js` | M2 | Explorer 2 |
| 10 | F10: Scale-Normalized Delta Integration | Integrate scale-normalized deltas $(\Delta C_i / C_{0, i}) \times 28000$ into `LivePipeline.process()` | M3 | Explorer 3 |
| 11 | F11: Surface Topography & Adaptive Gates | Connect `analyze_surface_topography()` to live stream for real-time per-pad adaptive gate calculation | M3 | Explorer 3 |
| 12 | F12: Adaptive Gate Propagation Integration | Pass adaptive lift gates vector to `PeelTracker` and `SPATIAL.propagation()` | M3 | Explorer 3 |
| 13 | F13: Adversarial Ingestion Fuzzing Suite | Automated 1,000+ malformed/NaN/Inf/spike frame stress test suite in `tests/test_adversarial_fuzzing.py` | M4 | Explorer 3 |
| 14 | F14: Disconnect Burst & Timing Suite | 50-cycle high-frequency disconnect/reconnect bursts and <1.5s timing test in `tests/test_disconnect_resilience.py` | M4 | Explorer 3 |
| 15 | F15: Memory Stability & Node Recycling Suite | 10,000-frame ring buffer bounding and Web Audio recycling tests in `tests/test_memory_and_stability.py` | M4 | Explorer 3 |
| 16 | F16: Synthetic Domain Generalization Suite | Synthetic ±20% baseline perturbations and stepped ridge tests in `tests/test_domain_generalization.py` | M4 | Explorer 3 |
| 17 | F17: Zero-Regression & Invariant Verification | Verify all 9 invariants, 100% passing pytest suite, and zero drift `--verify-metrics` against `Data/metrics.json` | M4 | System Invariants |
| 18 | F18: Final Adversarial Stress & Integrity Audit | 2 Challengers stress-test endpoints + Forensic Auditor executes binary integrity check | M5 | System Protocol |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend Ingest Fuzzing & Serial Hardware Resilience | Implement F1-F5 in `main.py` | none | **DONE** — verified 2026-09-17 (`IDLE_TIMEOUT_S`, 50,000-count spike filter present in `main.py`) |
| M2 | Frontend Memory Stability, Audio Recycling & Serial Jitter | Implement F6-F9 in `web/app.js` and `web/web_serial.js` | none | **DONE** — verified 2026-09-17 (`osc.onended` x4, `length > 50` ring bound, `navigator.serial` disconnect, 4096/512 caps) |
| M3 | Cross-Session Domain Generalization & Adaptive Gates | Implement F10-F12 in `main.py` | M1 | **DONE** — verified 2026-09-17 (`analyze_surface_topography`, scale-normalized 28000.0, adaptive gates wired) |
| M4 | Guard Suite Expansion & Invariant Verification | Implement F13-F17 in `tests/` | M1, M2, M3 | **DONE** — 2026-09-17: `pytest -q` **155 passed** in 1109 s, `--verify-metrics` reports no drift |
| M5 | Final Adversarial Challenge & Forensic Integrity Audit | 2 Challengers + Forensic Auditor | M4 | PLANNED — cannot be confirmed from the repository alone. `Data/trained_model.joblib.sha256.json` and `scripts/stress_test_m1.py` exist; the challenger/auditor passes are a process step, so mark this by hand when it has actually been run |

## Interface Contracts
### Client ↔ Server Communication
- REST API: JSON endpoints under `/api/v5/` and `/api/v6/`. Key query parameter `?key=` for non-loopback authentication.
- WebSockets: `/ws/live_sensor` accepts `?source=client|serial|replay|simulator&key=...`.
- Framing: Frames sent to `/ws/live_sensor?source=client` must contain 25 numeric floats. Corrupt JSON packets dropped without disconnecting.
- Disconnect transition: Within 1.5s of cable severance or frame silence, both client and server transition to disconnected state.
- Scale-normalization: $\widetilde{\Delta C}_i = (\Delta C_i / C_{0, i}) \times 28000.0$ preserves mathematical identity on bench data ($C_0 \approx 28000$) while providing scale-invariance across arbitrary mountings.

## Code Layout
- `main.py`: Backend server, API routes, WebSocket streaming, model classification, CLI verification tools.
- `web/index.html`: Web operator console markup.
- `web/style.css`: Web console styling & theme tokens.
- `web/app.js`: Web console client-side state, rendering, telemetry display, chart management, audio alarms.
- `web/web_serial.js`: Web Serial API hardware bridge for browser-to-sensor communication.
- `Data/`: 81 raw CSV recordings and `metrics.json`.
- `tests/`: Pytest suite (`test_all_endpoints.py`, `test_next_gen_features.py`, `test_serial_streaming.py`, `test_regressions.py`, `test_adversarial_fuzzing.py`, `test_disconnect_resilience.py`, `test_memory_and_stability.py`, `test_domain_generalization.py`, `conftest.py`), `test_invariants.py`, `test_doc_metrics_sync.py`).
- `scripts/sync_metrics_blocks.py`: renders `<!-- metrics:KEY -->` regions in the markdown from `Data/metrics.json`, so no headline figure is typed by hand. `--check` is what `tests/test_doc_metrics_sync.py` runs.
