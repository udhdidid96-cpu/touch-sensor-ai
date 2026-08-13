# Master Plan: Touch Sensor Self-Extubation Early Warning System

## Objective
Finalize, verify, and harden the Touch Sensor Self-Extubation Early Warning System project to achieve 100% completion against all requirements (R1, R2, R3) and acceptance criteria.

## Requirements Breakdown

### R1. Universal One-Click Portable Execution
- `start.bat` and `requirements.txt` for universal 1-click execution on http://localhost:8081 without manual package installation.

### R2. Comprehensive Front-End Web UI (main.py)
- Japanese Zen & Cyber-Medical Aesthetic (Japanese Torii Red #D7000F, Imperial Gold #FFD700, Indigo Navy #0F172A / #1E293B palette, English text).
- 25-Node 90x120mm Physical Patch 2D Visualizer.
- RBF Thin-Plate Interpolator rendering real-time heatmap on HTML5 Canvas.
- CPRI (Clinical Pull Risk Index) Gauge.
- Real-Time Chart.js Multi-Class Probability Graph.
- 8-Bed ICU Central Nurse Station Grid View.
- 1-Click Printable Medical PDF Audit Chart.
- Tele-Nursing LINE/Telegram Settings Panel.
- USB Serial Port Ingestion Controller.

### R3. Interactive Demo Toolbar & System Hardening
- 4 One-click competition presentation scenario buttons (Normal, Touch, Peel, Extubation Alarm) with live audio-visual sirens (Web Audio API 960Hz / 770Hz) and instant predictions.
- Zero Flake8 lint errors.
- Zero Pylance / Pyright type warnings.
- 100% clean test execution (`pytest` and `test_normal_mix.py`).
- Leave-One-File-Out Cross Validation (LOFO-CV) accuracy >= 95.0% and False Alarm Rate (FAR) = 0.0%.

---

## Orchestration Milestones & Workflow

### Milestone 8A: Comprehensive Baseline Exploration & Audit
- **Agent**: `explorer_m8_2` (`teamwork_preview_explorer`)
- **Task**: Audit `main.py`, `start.bat`, `requirements.txt`, test scripts, Flake8 linting, Pyright type checking, LOFO-CV accuracy, and FAR on Normal Mix datasets. Document exact gaps against R1, R2, and R3.

### Milestone 8B: Targeted Feature & UI Hardening (Worker)
- **Agent**: `worker_m8_2` (`teamwork_preview_worker`)
- **Task**: Apply any necessary fixes to `main.py`, `start.bat`, `requirements.txt`, or tests to ensure 100% Japanese Zen & Cyber-Medical styling, full endpoint reliability, PDF generation, 8-Bed ICU grid, demo scenario toolbar, zero lint/type errors, and LOFO-CV >= 95.0% with FAR = 0.0%. Run tests and verify build.

### Milestone 8C: Dual Independent Review
- **Agents**: `reviewer_m8_3` & `reviewer_m8_4` (`teamwork_preview_reviewer`)
- **Task**: Review code quality, design compliance, test coverage, and start.bat behavior.

### Milestone 8D: Adversarial Testing & Performance Benchmarking
- **Agents**: `challenger_m8_3` & `challenger_m8_4` (`teamwork_preview_challenger`)
- **Task**: Empirically verify server startup, scenario execution, LOFO-CV metrics, and UI interactivity.

### Milestone 8E: Forensic Integrity Audit
- **Agent**: `auditor_m8_2` (`teamwork_preview_auditor`)
- **Task**: Run full static and dynamic integrity audit to ensure no hardcoded results, facade implementations, or cheating.

### Milestone 8F: Final Victory Claim to Sentinel
- Send completion message to parent/sentinel with full verification evidence.
