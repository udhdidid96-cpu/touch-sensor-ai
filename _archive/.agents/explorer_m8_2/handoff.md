# Baseline Audit Report: Project2 (Touch Sensor Self-Extubation Early Warning System)

**Audit Date:** 2026-08-03  
**Auditor:** Explorer Subagent (`explorer_m8_2`)  
**Project Root:** `C:\Users\denpo\OneDrive\Desktop\Project2`  
**Working Directory:** `C:\Users\denpo\OneDrive\Desktop\Project2\.agents\explorer_m8_2`

---

## 1. Observation

A systematic read-only baseline audit was executed across the codebase (`main.py`, `start.bat`, `requirements.txt`, `test_normal_mix.py`, `tests/`, and `Data/`). Build, lint, test, and model evaluation commands were run to determine current compliance against Requirements R1–R5.

### Requirement 1: Universal 1-Click Execution
- **`start.bat` (`C:\Users\denpo\OneDrive\Desktop\Project2\start.bat`)**:
  - Line 11: `python --version >nul 2>&1` validates Python installation.
  - Line 20: `python -m pip install -q -r requirements.txt` installs dependencies.
  - Line 24: `echo Dashboard URL: http://localhost:8081` outputs launch URL.
  - Line 28: `python -u main.py` runs FastAPI dashboard on `http://localhost:8081`.
- **`requirements.txt` (`C:\Users\denpo\OneDrive\Desktop\Project2\requirements.txt`)**:
  - Contains 7 runtime dependencies: `fastapi>=0.100.0`, `uvicorn>=0.20.0`, `scikit-learn>=1.2.0`, `numpy>=1.24.0`, `scipy>=1.10.0`, `pyserial>=3.5`, `httpx>=0.24.0`.
- **Port Alignment**: `main.py:2679` defaults `--port` argument to `8081` (`ap.add_argument("--port", type=int, default=8081)`).

### Requirement 2: Web Dashboard UI & Feature Audit (`main.py`)
- **UI Aesthetic & Color Palette**:
  - `main.py:1900`: `<html lang="th">` (Thai language attribute used instead of English `lang="en"`).
  - `main.py:1905-1906`: `:root{--bg:#060913;--card:rgba(15,23,42,.88);--line:rgba(56,189,248,.25);--cyan:#06b6d4;--red:#ef4444;--green:#10b981;--txt:#f8fafc;--mut:#94a3b8}`.
  - **Indigo Navy**: `#0F172A` (`rgba(15,23,42,.88)`) and `#1E293B` present.
  - **MISSING - Color Gap**: Japanese Torii Red `#D7000F` is missing (generic red `#ef4444` / `#f87171` is used).
  - **MISSING - Color Gap**: Imperial Gold `#FFD700` is missing (generic amber `#f59e0b` / `#fbbf24` is used).
- **25-Node 90x120mm Patch Visualizer**:
  - `main.py:1946`: `<div class="sub">90 x 120 mm patch &middot; 25 pads &middot; Kalman baseline &middot; peel-propagation vectors</div>`.
  - `main.py:1961-1969 & 2081-2098`: SVG path and 25 circular node overlays dynamically rendered from pad coordinate matrix `PAD_XY`.
- **RBF Thin-Plate Interpolator**:
  - `main.py:469`: `RBFInterpolator(self.points, vals, smoothing=self.smoothing, kernel="thin_plate_spline")` computes spatial heatmap. Backend endpoint `/api/v6/heatmap` yields a 60x80 interpolated matrix.
- **CPRI Gauge**:
  - `main.py:1975-1976`: `<div class="gauge"><div style="font-size:.75rem;color:var(--mut);text-transform:uppercase">Composite Patient Risk Index</div><div class="gv" id="cpri">0.0%</div></div>`.
- **Real-time Chart.js Graph**:
  - `main.py:1984 & 2020-2037`: `<canvas id="ch"></canvas>` with Chart.js plotting CPRI %, P(Peel) %, P(Pull) %.
- **8-Bed ICU Grid View**:
  - **MISSING FEATURE**: `main.py` contains 0 instances of 8-bed layout or ICU multi-bed monitoring grid. Only single-patient patch UI is rendered.
- **1-Click Printable PDF Audit Chart**:
  - **MISSING FEATURE**: `main.py` contains 0 instances of PDF generation/rendering (only CSV export `patch_log.csv` exists at `main.py:2145`).
- **Tele-Nursing LINE/Telegram Panel**:
  - **MISSING FEATURE**: `main.py` contains 0 endpoints or UI components for LINE or Telegram dispatch/notifications.
- **USB Serial Controller**:
  - `main.py:1860+`: `SerialReader` class for reading 25-channel CSV packet lines from COM ports, with `/api/v5/serial/ports`, `/api/v5/serial/connect`, and `/api/v5/serial/disconnect` API routes.

### Requirement 3: Interactive Demo Toolbar
- **4 Scenario Buttons (`Normal`, `Touch`, `Peel`, `Extubation Alarm`)**:
  - **MISSING FEATURE**: Header bar (`main.py:1947-1954`) has `<select id="ds">`, `Play`, `Reset`, `Live stream`, `Export log`. Explicit 1-click shortcut scenario simulation buttons (`Normal`, `Touch`, `Peel`, `Extubation Alarm`) are missing.
- **Audio-Visual Sirens**:
  - `main.py:1994-2010`: `siren(level)` JS function uses Web Audio API to play 960Hz / 770Hz dual-tone sirens for level 3 alarm (`[[960,.22],[770,.22],[960,.22],[770,.22]]`). Banner `.l3` uses CSS pulsing shadow animation (`@keyframes pl`).
- **Instant Predictions**:
  - Predictions update in real time on frame change via slider controls or WebSocket `/ws/live_sensor`.

### Requirement 4: Lints & Tests Execution
- **Flake8 Compliance**:
  - Command: `python -m flake8 main.py test_normal_mix.py tests/`
  - Result: **0 errors (100% PASS)**.
- **Pyright / Pylance Type Checks**:
  - Command: `npx pyright`
  - Result: **29 errors, 0 warnings**:
    - `main.py` (3 errors): invalid `zero_division=0` passed to sklearn `classification_report` (lines 1030, 2566) and `f1_score` (line 1238).
    - `test_normal_mix.py` (24 errors): optional type subscripting, missing `Any` imports (lines 702-721), array type assignments.
    - `tests/test_all_endpoints.py` (1 error): `from main import get_app` ImportError.
    - `tests/test_serial_streaming.py` (1 error): `from main import get_app` ImportError.
- **pytest Test Suite**:
  - Command: `python -m pytest`
  - Result: **FAIL (2 collection errors)**. `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py` fail during import collection with:
    `ImportError: cannot import name 'get_app' from 'main'` because `main.py` defines `app = FastAPI(...)` without `get_app()`.
- **`test_normal_mix.py` Execution**:
  - Command: `python test_normal_mix.py`
  - Result: **50/50 PASSED (100%)**. Executed 50 unit and integration assertions covering geometry, baseline, propagation, debouncing, and safety bounds with zero failures.

### Requirement 5: Model Accuracy & False Alarm Rate (FAR)
- Command: `python main.py --report`
- Result Output:
  - **LOFO-CV (Leave-One-File-Out Cross-Validation) File-Level Accuracy**: **97.53%** (5-seed mean: 96.75% ± 0.68%, pooled accuracy: 97.53%, Wilson 95% CI [91.3, 99.3]). Exceeds requirement target (>= 95.0%).
  - **False Alarm Rate on Normal Files**: **0.0%** (0 false alarms out of 41 normal recordings under LOFO-CV). Satisfies requirement target (= 0.0%).

---

## 2. Logic Chain

1. **R1 Analysis**: `start.bat` correctly checks Python, installs dependencies from `requirements.txt`, and launches `main.py` on default port `8081`. Universal 1-click execution is operational.
2. **R2 Analysis**: Core signal processing and single-patient visualization (25-node SVG, RBF thin-plate interpolator, CPRI gauge, Chart.js, USB serial controller) are implemented in `main.py`. However:
   - Color palette uses standard Tailwind red (`#ef4444`) and gold (`#f59e0b`) rather than Japanese Torii Red (`#D7000F`) and Imperial Gold (`#FFD700`).
   - HTML language tag is Thai (`<html lang="th">`).
   - 8-Bed ICU Grid View, Printable PDF Audit Chart generation, and Tele-Nursing LINE/Telegram notification endpoints/panel are absent from `main.py`.
3. **R3 Analysis**: Audio siren (960Hz / 770Hz) and instant predictions are functional. The demo toolbar lacks 4 explicit shortcut buttons (`Normal`, `Touch`, `Peel`, `Extubation Alarm`).
4. **R4 Analysis**: Clean code compliance (`flake8`) passes with 0 errors on core files. `python test_normal_mix.py` passes 100% (50/50 tests). However, `pytest` fails completely due to `get_app` import mismatch in `tests/`, and `pyright` flags 29 type errors.
5. **R5 Analysis**: Evaluated via LOFO-CV. 97.53% file-level accuracy and 0.0% false alarm rate on normal files satisfy and exceed clinical performance criteria.

---

## 3. Caveats

- Dataset evaluated is based on single sensor mounting session (`S0` with 81 files, 3349 frames). Multi-session mounting generalization (`S1..S3`) was not tested.
- USB serial controller testing relied on simulated/replay stream logic (`LOOPBACK`); hardware connection was verified via mock serial interface.

---

## 4. Conclusion

### Summary Table

| Requirement | Target Criteria | Current Audit Status | Verified Output / Gaps |
|---|---|---|---|
| **R1. 1-Click Execution** | `start.bat` launching on `http://localhost:8081` | **PASS** | `start.bat` & `requirements.txt` operational, `--port 8081` default |
| **R2. Web Dashboard UI** | Palette (`#D7000F`, `#FFD700`, `#0F172A`, English text), 25-node patch, RBF, CPRI, Chart.js, 8-Bed ICU Grid, Printable PDF, Tele-Nursing LINE/Telegram, USB Serial | **PARTIAL** | Core visualizer & USB serial present. **Gaps:** palette uses `#ef4444`/`#f59e0b`, `lang="th"`, 8-Bed Grid missing, PDF export missing, LINE/Telegram panel missing |
| **R3. Interactive Demo Toolbar** | 4 scenario buttons (`Normal`, `Touch`, `Peel`, `Extubation Alarm`), sirens (960/770Hz), instant predictions | **PARTIAL** | Dual-tone siren (960Hz/770Hz) & predictions present. **Gap:** 4 explicit scenario buttons missing from toolbar |
| **R4. Lints & Tests** | 0 Flake8 errors, 0 Pyright errors, 100% pytest pass, test_normal_mix | **FAIL** | Flake8 0 errors (PASS), `test_normal_mix.py` 50/50 passed (PASS). **Gaps:** 29 Pyright errors, 2 pytest collection errors (`get_app` missing) |
| **R5. Model Accuracy & FAR** | LOFO-CV accuracy >= 95.0%, FAR = 0.0% | **PASS** | Accuracy: **97.53%**, FAR: **0.0%** |

---

## 5. Verification Method

To independently verify all observations and test results, execute the following commands from `C:\Users\denpo\OneDrive\Desktop\Project2`:

1. **Verify Universal Execution & Port**:
   ```pwsh
   cmd /c start.bat
   ```
   Confirm server launches on `http://localhost:8081`.

2. **Verify Code Quality & Linting**:
   ```pwsh
   python -m flake8 main.py test_normal_mix.py tests/
   ```

3. **Verify Type Checking Errors**:
   ```pwsh
   npx pyright main.py test_normal_mix.py tests/
   ```

4. **Verify Pytest Collection Failure**:
   ```pwsh
   python -m pytest
   ```

5. **Verify Normal Mix Test Suite (50/50 Pass)**:
   ```pwsh
   python test_normal_mix.py
   ```

6. **Verify Model Accuracy & False Alarm Rate**:
   ```pwsh
   python main.py --report
   ```
   Inspect output block for `File-Level Accuracy: 97.53%` and `false-alarm rate on normal files: 0.0%`.

7. **Verify UI Code & Missing Feature Gaps**:
   Inspect `main.py` lines 1899–2156 (`DASHBOARD_HTML`) for color palette definitions, HTML language tag, button toolbar layout, and absence of 8-Bed ICU Grid, PDF chart, and Tele-Nursing panel endpoints.
