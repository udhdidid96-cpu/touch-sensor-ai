# Original User Request

## Initial Request — 2026-07-30T19:03:38Z

Build an advanced, production-grade Touch Sensor Self-Extubation Early Warning System for ICU Patients (Project2). The system must combine spatio-temporal AI classification, real-time RBF spatial interpolation, a 90mm x 120mm dressing patch web UI, USB Serial COM Port hardware streaming, and an emergency audio siren alarm.

Working directory: C:\Users\denpo\OneDrive\Desktop\Project2
Integrity mode: development

## Requirements

### R1. Full End-to-End System Integration & Execution
- Ensure main.py serves as a high-performance single master executable combining the RBF spatial interpolator, 11-feature spatio-temporal extractor, multi-class classification engine, research plot generator, and FastAPI Web Dashboard.

### R2. Advanced Signal Processing & Multi-Class AI Optimization
- Implement spatio-temporal 11-feature extraction (min/max/mean/std delta, drop/spike counts, 2D spatial gradients) and optimize multi-class prediction (Baseline Normal, Incidental Touch/Press, Dressing Peel Warning, Extubation Pull Alarm).

### R3. Web Dashboard Center & Dual-Tone Emergency Audio Siren
- Provide a responsive 90x120mm physical dressing patch UI rendering 25 physical pad nodes, RBF thin-plate spline heatmaps, dual-color state indicators (🔴 Press vs 🔵 Unpeel), and a dual-tone ICU emergency audio siren (960Hz / 770Hz).

### R4. USB Serial COM Port Real-Time Streaming Interface
- Implement automated USB Serial COM Port scanning and streaming data ingestion for live hardware microcontrollers connected via USB/Serial.

## Acceptance Criteria

### Performance & Functional Criteria
- Model training and server startup complete in < 1 second.
- Multi-class classification accuracy >= 95% on leave-one-group-out cross-validation.
- Web Dashboard displays smooth 60 FPS RBF heatmaps and zero-latency sensor state updates.

## Follow-up — 2026-07-31T07:08:06Z

Elevate Project2 (Touch Sensor Self-Extubation Early Warning System for ICU Patients) to a National Competition & Patent-Grade Medical Product by integrating Instant LINE Notify & Telegram Emergency Tele-Nursing Alerts.

Working directory: C:\Users\denpo\OneDrive\Desktop\Project2
Integrity mode: development

## Requirements

### R1. Instant LINE Notify & Telegram Tele-Nursing Emergency Dispatcher
- Implement an automated async notification service sending instant emergency alerts (with patient bed number, severity level, CPRI score, and RBF snapshot) directly to the attending nurse's LINE / Telegram when Class 3 Extubation Pull or Class 2 Peel Warning events occur.

### R2. Web UI Tele-Nursing Alert Configuration & Webhook Control Panel
- Add an interactive Tele-Nursing Settings Panel in the Web Dashboard (main.py) allowing nurses to set LINE Notify tokens, Telegram Bot tokens, threshold preferences, and test alert dispatches with one click.

### R3. Full End-to-End System Integration & Audio-Visual Alarm Synchronization
- Ensure seamless integration with the existing 25-pad RBF spatial interpolator, 11-feature AI classifier, USB Serial COM Port reader, and Web Audio ICU siren alarm.

## Acceptance Criteria

### [National Competition Guardrails]
- Emergency LINE Notify / Telegram message dispatched within 500ms of Class 3 Extubation Alarm detection.
- Dashboard Settings Panel provides instant "Test Alert Dispatch" verification.
- Zero Flake8 lint errors and zero Pylance type diagnostics across all python source code.
- Server startup time < 1 second on http://localhost:8081.

## Follow-up — 2026-07-31T22:25:00Z

Universal One-Click Portable Deployment & Complete Front-End UI (Japanese Zen & Cyber-Medical Edition) for Touch Sensor Self-Extubation Early Warning System.

Working directory: C:\Users\denpo\OneDrive\Desktop\Project2
Integrity mode: development

## Requirements

### R1. Universal One-Click Portable Execution (start.bat & requirements.txt)
- Ensure start.bat and requirements.txt automatically handle package verification, dataset check, and web dashboard startup so anyone can run the project on any computer in 1 click.

### R2. Complete 100% Comprehensive Front-End Web UI (main.py)
- Finalize the complete Web Dashboard with Japanese Zen & Cyber-Medical Aesthetic (Japanese Torii Red, Imperial Gold, Indigo Navy palette, English text).
- Include 25-Node 90x120mm Physical Patch 2D Visualizer, RBF Thin-Plate Interpolator, CPRI Risk Index Gauge, Real-Time Chart.js Multi-Class Probability Graph.
- 8-Bed ICU Central Nurse Station Grid View, 1-Click Printable Medical PDF Audit Chart, Tele-Nursing LINE/Telegram Settings Panel, and USB Serial Port Ingestion Controller.

### R3. Interactive Competition Demo Toolbar & Full System Verification
- 4 One-click competition presentation scenario buttons (Normal, Touch, Peel, Extubation Alarm) that trigger live audio-visual sirens and instant predictions.
- Zero Flake8 lint errors, zero Pylance warnings, and 100% clean test execution.

## Acceptance Criteria

### [Universal Deployment & Front-End Perfection]
- [ ] start.bat launches the complete web server automatically on http://localhost:8081 without requiring manual package installations.
- [ ] Front-End UI features 100% complete controls (Demo Scenarios, 8-Bed ICU Grid, PDF Report, Tele-Nursing Panel, Real-Time Chart).
- [ ] Zero Flake8 lint errors and zero Pylance type warnings.
- [ ] Leave-One-File-Out Cross Validation accuracy >= 92.5% and False Alarm Rate = 0.0%.

