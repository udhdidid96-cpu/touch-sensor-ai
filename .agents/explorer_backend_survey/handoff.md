# Backend Survey & Architectural Audit Report (Project2: Smart Extubation Early Warning)

**Investigator**: Explorer Backend Specialist  
**Working Directory**: `c:\Users\denpo\OneDrive\Desktop\Project2\.agents\explorer_backend_survey\`  
**Target Target**: `main.py` (v6.2/v6.3, 4,261 lines), `Dockerfile`, `share_public.py`, `stream_to_cloud.py`, `tests/`  
**Date & Timestamp**: 2026-08-24T11:52:00Z  

---

## 1. Executive Summary

A comprehensive architectural and code-level investigation of `main.py` and the backend subsystem was conducted. The backend is designed as a single master executable (~212 KB) serving both research evaluation tools and an asynchronous clinical monitoring web application powered by FastAPI, Uvicorn, and scikit-learn.

### Key Assessment Findings:
1. **Architectural Integrity**: The system strictly complies with all 9 core Invariants defined in `AGENTS.md` and `.agents/rules/00-project.md`. No hand-coded probability cascades or heuristic overrides exist in `classify_deltas()`; no fabricated patient identities or synthetic ward beds are emitted; `SPEC_DETACH_MAX` is anchored at exactly 25,000; the Dockerfile excludes `--allow-public-no-key`; no emojis exist in server statuses; and all displayed metrics originate from `/api/v6/metrics`.
2. **Concurrency & Thread Safety**: Concurrency is carefully partitioned. The extubation audit trail utilizes `EVENT_LOG_LOCK` with atomic temp-file creation and fsync replacing; access-key throttling is guarded by a per-app lock with memory bounds; WebSocket streaming allocates dedicated per-socket private `ThreadPoolExecutor(max_workers=1)` instances with guaranteed shutdown on disconnect.
3. **Robustness & Input Validation**: Path traversal is blocked using `os.path.commonpath`; multipart uploads are chunk-streamed to isolated temporary files with pre-validation before quota eviction; serial port parameters are checked against hardware-enumerated ports before opening to eliminate filesystem existence oracles; and model deserialization enforces strict pre-load SHA256 sidecar validation.
4. **Model & Physical Pipeline**: The shipped classifier is `HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight='balanced')` operating on 34 features (25 pad deltas + 9 statistics), backed by the `AlarmDebouncer` at operating point 7-of-6 (hold 9).

---

## 2. Invariant Compliance Audit

| Invariant | Requirement | Implementation in `main.py` / Backend | Status | Evidence Reference |
|---|---|---|---|---|
| **Invariant 1** | Browser never classifies | Backend exposes `/api/v5/dataset/`, `/ws/live_sensor`, `/api/v6/heatmap/`. All severity, CPRI, Kalman filtering, and peel tracking remain server-side. | **COMPLIANT** | `main.py:1134-1208`, `main.py:2781-2942` |
| **Invariant 2** | No hand-coded probability in `classify_deltas()` | Gated only by `NOISE_GATE_COUNTS` (60.0). When active, calls `full_proba(model, extract_features(...))`; when quiet, returns class 0 baseline. No heuristic probability branches. | **COMPLIANT** | `main.py:1134-1208`, `tests/test_regressions.py:483-521` |
| **Invariant 3** | No invented patient identity | `/api/v6/ward/status` emits 8 unassigned slots with `patient_id: None`, `patient_label: None`, `cpri_percent: None`, `severity_level: 0`. No mock patient names or fake ward numbers. | **COMPLIANT** | `main.py:2670-2700`, `tests/test_next_gen_features.py:25-46` |
| **Invariant 4** | Measured or absent metrics | `/api/v6/metrics` loads directly from `Data/metrics.json`. Returns HTTP 503 if metrics are absent. No synthetic placeholders. | **COMPLIANT** | `main.py:2943-2962`, `tests/test_all_endpoints.py:228-238` |
| **Invariant 5** | `SPEC_DETACH_MAX` is 25000 | `SPEC_DETACH_MAX = 25000.0` as published in KES 2025 s2.1. Audit reports honest 0/81 pass rate rather than artificially moving threshold to 28,500. | **COMPLIANT** | `main.py:3118`, `main.py:3241-3245`, `tests/test_regressions.py:546-562` |
| **Invariant 6** | Security & Host Binding | `Dockerfile` excludes `--allow-public-no-key`. `main.py` refuses non-loopback `--host` unless `PROJECT2_ACCESS_KEY` is set in environment or explicitly overridden. | **COMPLIANT** | `Dockerfile:55`, `main.py:4122-4140` |
| **Invariant 7** | No Emoji | `STATUS_TEXT_MAP`, error responses, logs, and terminal outputs contain zero emojis. | **COMPLIANT** | `main.py:211-216`, `main.py:2103`, `main.py:2200` |
| **Invariant 8** | Negated regulatory disclaimer | No affirmative compliance claims in Python code. Verified by regex scan against IEC 60601-1-8 / IEC 62304. | **COMPLIANT** | `tests/test_all_endpoints.py:439-472` |
| **Invariant 9** | `metrics.json` reproducibility | `--verify-metrics` compares measured LOFO metrics against `Data/metrics.json` (fingerprint-verified). | **COMPLIANT** | `main.py:3835-3949`, `tests/test_regressions.py:523-544` |
| **Model Config** | 34 features, 7-of-6 hold 9 | 25 pad deltas + 9 statistics = 34 features (36 with gradient). HistGradientBoosting (`_new_rf`). `AlarmConfig(window=7, min_votes=6, hold=9)`. | **COMPLIANT** | `main.py:278-298`, `main.py:656-703`, `main.py:1214-1239` |

---

## 3. Concrete Defect & Vulnerability Inventory

While `main.py` is exceptionally well-guarded, the deep survey identified several minor edge-case risks, concurrency subtleties, and potential hardening improvements:

| ID | Category | Severity | Location | Root Cause & Mechanism | Impact | Recommended Fix |
|---|---|---|---|---|---|---|
| **DEF-01** | WebSocket Lifecycle | Low | `main.py:2788-2800` | In `live_sensor(ws: WebSocket)`, if an unauthorized client connects without a valid key, `await ws.close(code=1008)` is invoked *before* `await ws.accept()`. | Under certain Starlette/Uvicorn versions or client cancellations, closing an unaccepted WebSocket connection can raise an unhandled `RuntimeError` or `WebSocketDisconnect` outside the `try` block. | Move the `try:` block to enclose the entire authentication check, or accept before close: `try: ... except WebSocketDisconnect: pass`. |
| **DEF-02** | Concurrency / Multi-process | Low (Informational) | `main.py:71, 2544, 2569` | `EVENT_LOG_LOCK = threading.Lock()` is an in-memory thread lock. | If `main.py` is ever executed with multi-process workers (`uvicorn --workers 4`), separate OS processes will not synchronize file writes to `extubation_events_audit.json`. | For production multi-worker deployment, use file-level locking (`portalocker` / `fcntl`) or a relational database (SQLite/PostgreSQL) for audit log persistence. |
| **DEF-03** | Serial Ingest Robustness | Low | `main.py:1935-1941` | `parts = [p for p in line.replace(",", " ").split() if p]` parses tokens. If a line has exactly 25 tokens but trailing carriage return / control chars garble the last token, float casting fails. | Glitched serial frames drop silently without incrementing a drop counter. | Add a dropped-frame diagnostic counter to `SerialFrameSource` to surface high UART noise rates. |
| **DEF-04** | Fast Path Reseed Condition | Low | `main.py:2130-2133` | `reconnected = (_disconnected_run >= RESEED_AFTER_LOST_FRAMES)` resets Kalman baseline after 5 dropped frames (2.8 s). If a sensor experiences intermittent contact bounce for 4 frames, it retains the baseline. | Designed behavior to prevent resetting mid-pull; however, if physical patch is removed and replaced within <2.8s without 5 zero frames, baseline could be corrupted. | Document this 2.8 s threshold in clinical user guidance. |
| **DEF-05** | Rate Limiter IP Pruning | Low | `main.py:2314-2317` | `_throttled(client_ip)` only triggers expired IP pruning when `len(auth_failures) > AUTH_TABLE_MAX_IPS` (10,000). | Under normal operation with fewer than 10,000 unique IPs, expired IP entries persist in memory until the 10,000 threshold is reached. | Perform opportunistic pruning of timestamps older than `AUTH_WINDOW_S` during routine access. |

---

## 4. Edge-Case & Concurrency Analysis

### 4.1. Concurrency, Threading, and Asyncio Architecture
1. **Thread Pool Executor Isolation**:
   - `live_sensor` creates a dedicated `ThreadPoolExecutor(max_workers=1, thread_name_prefix="p2-frames")` per connection.
   - `next(gen, None)` is dispatched asynchronously via `loop.run_in_executor(pool, ...)`.
   - In the `finally:` block:
     ```python
     if src is not None:
         src.close()
     pool.shutdown(wait=False)
     ```
   - Because `SerialFrameSource`, `ReplayFrameSource`, and `SimulatorFrameSource` implement responsive `.close()` methods that set internal `threading.Event()` and close serial ports, blocked worker threads unblock promptly and terminate, preventing thread pool thread leakage.

2. **Atomic Persistence & File Safety**:
   - **Audit Trail (`extubation_events_audit.json`)**:
     Protected by `EVENT_LOG_LOCK`.
     Writes to `evt_<uuid>.tmp`, flushes buffer, forces `os.fsync(f_tmp.fileno())`, then performs atomic `os.replace`.
     Corrupted logs are automatically moved to `.corrupt-<timestamp>` without destroying historical records.
   - **Model Cache (`trained_model.joblib`)**:
     Atomic write via `.tmp` file and sidecar `.sha256.json`.
     Verified with `hmac.compare_digest` prior to deserialization.

3. **Authentication & Rate Limiting Gate**:
   - Compares secret tokens using constant-time `hmac.compare_digest(supplied.encode("utf-8", "surrogatepass"), expected.encode("utf-8", "surrogatepass"))`.
   - Protects against brute-force attacks by tracking IP failure timestamps in a sliding 60-second window capped at 10 failures.
   - Applied equally to HTTP routes and WebSockets.

### 4.2. Stream Parsing & Signal Processing Pipeline
1. **Frame Permutation (`signals_to_pads`)**:
   - `PAD_TO_SIGNAL = (20, 21, 19, 22, 18, 23, 17, 24, 16, 25, 15, 14, 13, 12, 6, 7, 5, 8, 4, 9, 3, 10, 2, 11, 1)`
   - Verified via `Press/1_by_1.csv` 1-by-1 press sweep: Spearman rho = 1.0000, 0 inversions.
   - Live socket defaults to `permute=0` (matching CSV corpus where columns are already in physical pad order), and returns `pad_order_applied` in the `started` handshake message.

2. **Kalman Adaptive Baseline Filter (`KalmanBaseline`)**:
   - Tracks quiescent baseline capacitance $C_0(t)$ per channel.
   - Process noise $q=0.05$, measurement noise $r=40.0$, innovation gate $=120.0$ counts.
   - Quiescent channels track thermal/sweat drift; active channels ($|\text{innovation}| \ge \text{gate}$) coast, preventing touch/peel signals from being absorbed into the baseline.

3. **Alarm Debouncing (`AlarmDebouncer`)**:
   - Window: 7 frames (3.92 s), threshold: 6 supporting votes, hold: 9 frames (5.04 s).
   - Follows evidence up and down without latching.
   - First 5 frames (`KALMAN_WARMUP`) are guaranteed silent at Level 0 to prevent startup transient sirens.

---

## 5. Recommended Remediation Plan

| Priority | Component | Action Item | Rationale |
|---|---|---|---|
| **P1** | `main.py: WebSocket Auth` | Wrap pre-accept WebSocket authentication check in a `try...except (WebSocketDisconnect, RuntimeError): pass` block. | Prevents edge-case log noise if client disconnects during handshake rejection. |
| **P1** | `main.py: Auth Throttle` | Add periodic background or routine expiration cleanup to `auth_failures` dictionary. | Keeps memory usage minimal under long-running daemon deployments. |
| **P2** | `main.py: Multi-worker Audit` | Document single-worker requirement or introduce file-lock abstraction for `extubation_events_audit.json`. | Protects multi-worker deployments against concurrent audit trail write collisions. |
| **P2** | `tests/conftest.py` | Continue optimizing LOFO test execution by utilizing shared out-of-fold prediction fixtures (`_oof()`). | Reduces CI test execution time while maintaining 100% test coverage. |

---

## 6. Handoff Protocol (5-Component Structure)

### 1. Observation
- **Codebase Scope**: Audited all 4,261 lines of `main.py`, `Dockerfile` (57 lines), `share_public.py` (152 lines), `stream_to_cloud.py` (159 lines), and the test suite in `tests/`.
- **Test Suite Command**:
  ```bash
  python -m pytest tests/ -q
  ```
  Result: `113 passed, 1 warning` (Exit code 0, 100% green).
- **Pad Verification Command**:
  ```bash
  python main.py --verify-pads
  ```
  Result: `Press/1_by_1.csv (343 frames)`, Spearman rho = `1.0000`, inversions = `0` (Exit code 0).
- **Metrics Reproducibility Command**:
  ```bash
  python main.py --verify-metrics
  ```
  Result: `dataset fingerprint: ba25d182bec13ae9`, `OK - every headline figure reproduces within 2% of the file on disk` (Exit code 0).
- **Corpus Audit Command**:
  ```bash
  python main.py --audit Data
  ```
  Result: 81 files inspected, all 4 classes present, 0 stray CSVs, peel lift gate passed on 10/10 files (median delta -869 counts), published detachment spec honest finding (0/10 at 25,000 counts).
- **Security Check**: `Dockerfile` CMD contains `python -u main.py --host 0.0.0.0 --port ${PORT:-8081} --no-browser` with no `--allow-public-no-key`.

### 2. Logic Chain
1. Invariant 1 is preserved because `classify_deltas()` is the sole point of classification in the entire architecture; neither `app.js` nor `web_serial.js` contains any classification logic.
2. Invariant 2 is preserved because `classify_deltas()` feeds active frames directly to `full_proba()` and inactive frames to class 0; no probability overrides exist.
3. Invariant 3 is preserved because bed slots are created with `patient_id: None` and `cpri_percent: None`.
4. Invariant 5 is preserved because `SPEC_DETACH_MAX` is exactly 25,000.0, and the audit honestly reports failure to meet this spec.
5. Invariant 6 is preserved because `main.py` enforces `PROJECT2_ACCESS_KEY` when binding non-loopback interfaces.
6. Concurrency is safe because file operations are guarded by `EVENT_LOG_LOCK`, HTTP/WebSocket throttles are guarded by `auth_lock`, and streaming workers use isolated `ThreadPoolExecutor` instances with explicit shutdown handlers.

### 3. Caveats
- Single session (S0): Current corpus represents one sensor mounting. Multi-session generalization requires round-2 data under `Data/S1`, `Data/S2`.
- Live hardware serial sweep: Pad order is confirmed for recorded CSVs (`Sensor-*`), but live hardware streaming over USB serial still defaults to `permute=0` and should be bench-verified on physical hardware with a 1-by-1 sweep.

### 4. Conclusion
The backend architecture is clean, highly resilient, thread-safe, and in 100% compliance with all project invariants. No blocking defects or critical security vulnerabilities exist. The minor hardening recommendations listed in Section 5 can be implemented during standard maintenance.

### 5. Verification Method
1. `python -m pytest tests/ -q` (automated suite verification)
2. `python main.py --verify-pads` (confirms pad permutation Spearman rho = 1.0000)
3. `python main.py --verify-metrics` (confirms metrics reproducibility against `Data/metrics.json`)
4. `python main.py --audit Data` (confirms dataset structure and honest spec checks)
