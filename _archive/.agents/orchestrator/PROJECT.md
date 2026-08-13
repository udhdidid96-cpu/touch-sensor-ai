# Project Specification & Milestones — Project2: Touch Sensor Self-Extubation Early Warning System

## Architecture
- **Master Executable**: `main.py` serving as single entry point (FastAPI server on port 8081, CLI runner, plot generator, model trainer, async Tele-Nursing notification service).
- **Dataset**: `Data/` containing 81 CSV sensor logs across 9 directories mapped to 4 classes (0: Baseline Normal, 1: Incidental Touch/Press, 2: Dressing Peel Warning, 3: Extubation Pull Alarm).
- **Core Modules**:
  1. **Spatio-Temporal Feature Engine**: 11 features (min, max, mean, std delta, drop count, spike count, true 2D spatial grid gradients dX/dY, max spatial magnitude, etc.).
  2. **Multi-Class Classifier Engine**: ExtraTreesClassifier / RandomForestClassifier evaluated with Leave-One-Group-Out CV achieving >=95% accuracy and fast execution time.
  3. **RBF Spatial Interpolator & 60 FPS UI Engine**: Thin-plate spline interpolation rendered via requestAnimationFrame on Canvas for smooth 60 FPS 2D heatmaps across 90x120mm patch layout with 25 physical nodes and dual-color state indicators (🔴 Press vs 🔵 Unpeel).
  4. **Emergency Audio Siren**: Web Audio API dual-tone siren (960Hz / 770Hz) triggering on Class 3 Extubation Alarm events.
  5. **USB Serial COM Port Ingestion**: Auto-scanning COM ports, live serial byte stream parsing, and WebSocket real-time sensor frame broadcasting.
  6. **Instant Tele-Nursing Emergency Dispatcher & Web UI Control Panel**: Async LINE Notify and Telegram Bot dispatcher sending instant emergency alerts (<500ms for Class 3 Extubation or Class 2 Peel Warning with bed #, CPRI score, RBF snapshot). Interactive Web UI settings panel with token fields, threshold preferences, and one-click Test Alert Dispatch button.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Baseline Exploration & Code Quality Audit | Audit main.py, lints, LOGO-CV, startup, UI, COM streaming | None | DONE |
| 2 | Spatio-Temporal AI & LOGO-CV Optimization | Fix 2D grid gradient mapping, 11 features, LOGO-CV >= 95% accuracy, <1s startup | M1 | DONE |
| 3 | Web Dashboard 60 FPS RBF Heatmap & Siren UI | 90x120mm UI, 25 nodes, RBF spline 60 FPS Canvas loop, dual-color indicators, 960Hz/770Hz audio siren | M1 | DONE |
| 4 | USB Serial COM Port Streaming Interface | Auto COM scanning, background serial reader, 25-channel parsing, WebSocket broadcasting | M1 | DONE |
| 5 | Tele-Nursing Emergency Dispatcher & Web UI Control Panel | Instant LINE Notify & Telegram dispatcher (<500ms async), Tele-Nursing Settings Panel in Web UI, Test Alert Dispatch button, webhook configuration | M2, M3, M4 | DONE |
| 6 | Master Integration & Quality Hardening | Integrated main.py on http://localhost:8081 (<1s startup), zero Flake8 errors, zero Pylance type diagnostics across all python files | M5 | DONE |
| 7 | Dual Track E2E Testing & Forensic Audit | Requirement-driven test suite (Tiers 1-4, <500ms dispatch test, test alert test), Tier 5 whitebox hardening, Forensic Audit verification | M6 | DONE |
| 8 | Universal One-Click Deployment & Cyber-Medical UI Perfection | start.bat auto-launcher, Japanese Zen & Cyber-Medical aesthetic, 8-bed grid, printable PDF report, Chart.js probabilities, 4 demo scenario buttons, LOFO CV >= 92.5%, FAR=0.0%, zero Flake8 & zero Pylance errors | M7 | IN_PROGRESS |


## Interface Contracts
### AI Classifier ↔ Web Dashboard
- Endpoint `/api/predict` or WebSocket `/ws/sensor`: Accepts 25-channel sensor frame (25 float readings), returns class index (0..3), class label, confidence probabilities, and 11 extracted feature values.
### RBF Interpolator ↔ Web Dashboard
- Input: 25 pad physical coordinates (x, y) on 90x120mm patch and 25 pressure values.
- Output: 2D interpolated matrix rendered at 60 FPS on HTML5 Canvas.
### Tele-Nursing Dispatcher ↔ Web Dashboard / AI Classifier
- Endpoint `/api/tele-nursing/config`: GET/POST config (LINE Notify token, Telegram bot token/chat_id, thresholds).
- Endpoint `/api/tele-nursing/test-alert`: POST to trigger instant test alert dispatch to LINE and Telegram.
- Notification dispatch: Async task sending formatted text + RBF snapshot image within <500ms on Class 2 Peel Warning / Class 3 Extubation Pull events.
### USB Serial ↔ Master Engine
- Auto-detect available COM ports, stream incoming 25-sensor telemetry lines, push into async queue for prediction and UI WebSocket push.

## Code Layout
- `main.py`: Single master executable file containing all integrated components and FastAPI server.
- `Data/`: CSV datasets and evaluation summaries.
- `tests/`: Unit and E2E test scripts.
