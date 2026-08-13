## 2026-07-31T22:27:01Z
<USER_REQUEST>
You are worker_m8_1, an implementation worker for Project2 (Touch Sensor Self-Extubation Early Warning System).
Working directory: C:\Users\denpo\OneDrive\Desktop\Project2

Your task is to implement and verify Milestone 8 (Universal One-Click Portable Deployment & Complete Cyber-Medical Front-End UI):

### MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

### Specific Tasks:
1. **R1: Universal One-Click Portable Execution (`start.bat` & `requirements.txt`)**:
   - Update `start.bat`:
     - Ensure robust package verification and installation if missing.
     - Check `Data/` dataset folder presence.
     - Launch `main.py` web dashboard server on `http://localhost:8081`.
     - Automatically open browser to `http://localhost:8081` (e.g. `start http://localhost:8081` after server launch or via small delay/background start).
     - Ensure clean execution without hardcoded environment paths.
   - Update `requirements.txt`:
     - Include all needed runtime and quality packages: `fastapi`, `uvicorn[standard]`, `numpy`, `scipy`, `scikit-learn`, `requests`, `pydantic`, `jinja2`, `flake8`, `pyright`, `pytest`.

2. **R2 & R3: Complete Front-End Web UI (`main.py`) & Demo Toolbar**:
   - Update `main.py` CSS & UI HTML layout for Japanese Zen & Cyber-Medical Aesthetic:
     - Color Palette: Japanese Torii Red (`#BC002D` / `#E60033`), Imperial Gold (`#D4AF37` / `#FFD700`), Indigo Navy (`#0F1423` / `#161E38`). English typography.
     - 25-Node 90x120mm Patch 2D Visualizer with 60 FPS HTML5 Canvas RBF Interpolator.
     - CPRI Risk Index Gauge display.
     - Real-Time Chart.js Multi-Class Probability Graph (visualizing class 0, 1, 2, 3 probabilities over time).
     - 8-Bed ICU Central Nurse Station Grid View (displaying 8 ICU bed cards with status, patient ID, CPRI score, and select button).
     - 1-Click Printable Medical PDF Audit Chart (endpoint `/api/pdf/audit-report` and UI button that opens a clean printable audit report).
     - Tele-Nursing LINE/Telegram Settings Panel with webhook fields, threshold sliders, and Test Alert Dispatch button.
     - USB Serial Port Ingestion Controller.
     - 4 One-click competition presentation scenario buttons (Normal, Touch, Peel, Extubation Alarm) that send simulated 25-pad sensor frames, trigger live predictions, update the Chart.js graph, and activate audio-visual sirens on alarm.

3. **Quality Verification & Testing**:
   - Run Flake8: `flake8 main.py test_normal_mix.py --max-line-length=120 --ignore=E203,W503` (must have 0 lint errors).
   - Run Pyright/Pylance: `pyright main.py` or type check (must have 0 errors).
   - Run Pytest: `pytest` (must pass 100%).
   - Verify LOFO CV accuracy >= 92.5% and False Alarm Rate = 0.0%.

Write your handoff report in `C:\Users\denpo\OneDrive\Desktop\Project2\.agents\teamwork_preview_worker_m8_1\handoff.md`.
Send a summary message back to orchestrator when finished.
</USER_REQUEST>
