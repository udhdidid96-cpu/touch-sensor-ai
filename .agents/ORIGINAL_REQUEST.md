# Original User Request

## 2026-08-24T02:00:08+09:00

วิเคราะห์และค้นหาจุดผิดพลาด (Defects/Bugs), ตรวจสอบความสอดคล้องกับ Invariants ของระบบ Project2 (Smart Extubation Early Warning) ทั้งหมด และดำเนินการแก้ไขจุดบกพร่องให้สมบูรณ์ พร้อมตรวจสอบความถูกต้องด้วยชุดทดสอบและเกณฑ์ชี้วัด

Working directory: c:\Users\denpo\OneDrive\Desktop\Project2
Integrity mode: development

## Verification Resources
- Test suite: `python -m pytest tests/ -q` (113+ automated tests)
- Metrics verification: `python main.py --verify-metrics` (เปรียบเทียบกับ `Data/metrics.json`)
- Corpus audit tool: `python main.py --audit Data`
- Invariant & sensor rules document: `AGENTS.md` และ `.agents/rules/`

## Requirements

### R1. Comprehensive Defect Analysis
- ตรวจสอบและวิเคราะห์ Codebase ทั้งระบบ (`main.py`, `web/index.html`, `web/style.css`, `web/app.js`, `web/web_serial.js`, `tests/`)
- ค้นหาจุดบกพร่อง (logic bugs, runtime errors, data parsing issues, concurrency issues, edge cases)
- ตรวจสอบการปฏิบัติตาม Invariants ทั้ง 9 ข้อใน `AGENTS.md` อย่างเข้มงวด

### R2. Invariants Enforcement & Correction
- **Browser never classifies**: ตรวจสอบให้แน่ใจว่า Frontend (`app.js`, `web_serial.js`) ไม่มีการคำนวณ Severity, CPRI, pad counts หรือใช้ตัวแปร `nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`
- **No hand-coded probability**: ฟังก์ชัน `classify_deltas()` และ endpoints ต้องไม่ใช้ heuristic/hand-coded probability แทนการเรียกโมเดลจริง
- **No invented patient identity**: ห้ามมีข้อมูลผู้ป่วยจำลองหรือ hardcoded patient IDs ทุก bed slot ต้องใช้ค่าจริงจาก operator หรือ `None`
- **Measured or absent metrics**: ค่าตัวเลขสถิติบน UI ต้องดึงจาก `/api/v6/metrics` เท่านั้น ห้าม hardcode หรือจำลองค่า
- **SPEC_DETACH_MAX**: ค่า threshold ต้องเป็น 25000 เท่านั้น
- **Security & Docker**: ห้ามใส่ `--allow-public-no-key` และป้องกัน non-loopback host เมื่อไม่มี access key
- **No emoji**: ไม่มี emoji ในโค้ด frontend, html, หรือ server status strings
- **Negated certified context**: ต้องมีข้อความปฏิเสธความรับผิดชอบ IEC 62304 ใน `index.html` และ `app.js`

### R3. Safe Implementation & Refactoring
- ดำเนินการแก้ไขจุดบกพร่องที่ค้นพบอย่างปลอดภัย โดยไม่กระทบสถาปัตยกรรมหลัก
- ห้าม revert โมเดลหรือเปลี่ยน feature set (ต้องใช้ 34 features: 25 pad deltas + 9 statistics ตามมาตรฐาน)
- ห้ามสร้าง launcher script เพิ่มขึ้นมาใหม่

### R4. Automated Verification & Regression Prevention
- รันชุดทดสอบทั้งหมดเพื่อให้มั่นใจว่าไม่มี regression
- ตรวจสอบ metrics ด้วย `--verify-metrics` ให้สอดคล้องกับ `Data/metrics.json`
- เพิ่มหรือปรับปรุง unit tests ใน `tests/` หากพบกรณีผิดพลาดใหม่ที่ยังไม่มี test guard ครอบคลุม

## Acceptance Criteria

### Test & Metric Quality
- [ ] ชุดทดสอบ `python -m pytest tests/ -q` ผ่านครบทุกข้อ (100% green, 0 failures)
- [ ] คำสั่ง `python main.py --verify-metrics` ทำงานสำเร็จและค่าตรงกับ `Data/metrics.json`
- [ ] คำสั่ง `python main.py --audit Data` ผ่านเกณฑ์โดยไม่มี runtime crash

### Invariants Compliance
- [ ] ไฟล์ใน `web/` ผ่านการตรวจสอบ Invariant 1 (ไม่มี browser classification logic)
- [ ] ไฟล์ `main.py` ผ่านการตรวจสอบ Invariant 2 (ไม่มี handcoded proba ใน classify_deltas)
- [ ] ไม่มี mock patient data / invented Thai ward ในโค้ดหรือ UI (Invariant 3)
- [ ] ไม่มี emoji ใน `index.html`, `app.js`, `web_serial.js` หรือ API status (Invariant 7)
- [ ] ข้อความ IEC 62304 ปรากฏถูกต้องตาม Invariant 8

## 2026-08-24T20:32:36+09:00

ค้นหาและวิเคราะห์จุดบกพร่องเชิงลึก (Deep Defect Discovery), วิเคราะห์ Edge Cases, Concurrency, Memory Leaks, Code Quality, และความสอดคล้องกับ Invariants ของทั้งระบบ Project2 อย่างต่อเนื่อง พร้อมดำเนินการแก้ไขและทดสอบซ้ำจนเสร็จสมบูรณ์

Working directory: c:\Users\denpo\OneDrive\Desktop\Project2
Integrity mode: development

## Verification Resources
- Test suite: `python -m pytest tests/ -q` (113+ automated tests must stay 100% green)
- Pad verification: `python main.py --verify-pads` (Spearman rho = 1.0000)
- Corpus audit: `python main.py --audit Data`
- Metrics verification: `python main.py --verify-metrics`
- Invariant & sensor rules document: `AGENTS.md` and `.agents/rules/`

## Requirements

### R1. Deep Multi-Layer Defect Analysis
- สแกนและวิเคราะห์โค้ดอย่างละเอียดในทุกชั้น:
  - **Backend (`main.py`)**: ตรวจสอบ WebSocket connection lifecycles, exception handling, resource cleanup, race conditions, type annotations, API endpoint error codes, และ boundary condition checks
  - **Frontend (`web/app.js`, `web/web_serial.js`)**: ตรวจสอบ Web Serial stream framing, WebSocket reconnect backoff, Memory Leaks (Map/Cache retention), Chart.js instance management, AudioContext resumption, และ error reporting
  - **Styles & Markup (`web/index.html`, `web/style.css`)**: ตรวจสอบความถูกต้องของ DOM, Accessibility (WCAG AA), Theme token consistency, และ Responsive layout integrity
  - **Tests (`tests/`)**: ตรวจสอบความครอบคลุม (Coverage) และเพิ่ม test guards สำหรับ edge cases ใหม่ที่ตรวจพบ

### R2. Strict Invariants & Safety Compliance
- รักษากฎ Invariants ทั้ง 9 ข้อใน `AGENTS.md` อย่างเคร่งครัด 100%:
  - Browser ห้าม classify หรือมีตัวแปร `nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`
  - ฟังก์ชัน `classify_deltas()` ต้องไม่มี hand-coded probability
  - ห้ามสร้างหรือจำลองข้อมูลผู้ป่วย (No invented patient identity)
  - ตัวเลขสถิติต้องวัดจริงจาก API (Measured or absent)
  - `SPEC_DETACH_MAX` ต้องเป็น 25000 เท่านั้น
  - ห้ามใส่ `--allow-public-no-key` ใน Dockerfile
  - ไม่มี Emoji ในทุกส่วน
  - มีข้อความปฏิเสธความรับผิดชอบ IEC 62304 ชัดเจน
  - โมเดลต้องคงที่ 34 features (25 pad deltas + 9 statistics) และ Annunciator 7-of-6 (hold 9)

### R3. Continuous Hardening & Edge-Case Remediation
- แก้ไขปัญหาทุกจุดที่ตรวจพบทันทีโดยไม่สร้าง Breaking Changes
- ปรับปรุงการจัดการ Error Handling และ Concurrency Locks ให้ปลอดภัยสูงสุด
- ป้องกัน Resource Leaks ทั้งในระดับ Process, Threads และ Browser Session

### R4. Iterative Multi-Pass Verification
- รันชุดทดสอบ `pytest tests/` ซ้ำทุกครั้งหลังการปรับปรุง
- รัน `--verify-pads` และ `--audit Data` เพื่อยืนยันความถูกต้องของข้อมูล
- ตรวจสอบให้แน่ใจว่าไม่มีข้อผิดพลาดหลงเหลืออยู่

## Acceptance Criteria

### Test Suite & Robustness
- [ ] ชุดทดสอบ `python -m pytest tests/ -q` รันผ่านครบ 100% (0 failed)
- [ ] `python main.py --verify-pads` ได้ผลลัพธ์ Spearman rho = 1.0000 และ 0 inversions
- [ ] ทุก API Endpoints และ WebSockets ตอบสนองอย่างถูกต้องและมี Error Handling ที่ปลอดภัย
- [ ] Web Frontend และ Web Serial ทำงานราบรื่นโดยไม่มี Unhandled Promise Rejections หรือ Console Errors

### Invariant & Security Verification
- [ ] ผ่านการตรวจสอบ Invariants ทั้ง 9 ข้อใน `AGENTS.md` อย่างสมบูรณ์
- [ ] การเข้าถึงระยะไกล (Cloud Run / Public Deploy) มีระบบ Access Key ป้องกัน 401 เมื่อไม่มีคีย์

## 2026-09-16T08:55:51Z

Perform a comprehensive, full-spectrum engineering audit, hardening, and multi-faceted improvement of the Smart Extubation Early Warning 25-Channel Capacitive Sensing Smart Dressing system across all dimensions: AI/ML signal processing, electrodynamics, 3D non-planar/step-height contour compensation, absolute CDC hardware interfacing, clinical documentation, and zero-regression invariant verification.

Working directory: d:/Projects/Project2
Integrity mode: development

## Requirements

### R1. Comprehensive Architecture & Edge-Case Vulnerability Audit
Perform an exhaustive code and architecture audit across all server components (`main.py`), client bridge (`web/web_serial.js`, `web/app.js`), and test harnesses. Identify and eliminate any latent edge cases, numerical instability (NaN/Inf, negative capacitances), unit mismatches, serial drop artifacts, or unhandled physical transitions.

### R2. Electrodynamic Modeling & 3D Non-Planar / Step-Height Contour Compensation
Verify and harden the system's ability to operate on non-planar facial anatomy (mandible, cheek curvature $R \approx 15-50\text{ mm}$) and step-height physical discontinuities ($3-10\text{ mm}$ ridge caused by endotracheal tube OD $9.0-11.5\text{ mm}$ and anchor tape). Ensure relative fractional delta normalisation ($\delta_i = \Delta C_i / C_{0, i}$), per-pad adaptive lift gates ($\text{Gate}_i$), and static topography/tenting profiling (`analyze_surface_topography`) are fully integrated and mathematically validated.

### R3. Next-Gen Absolute CDC Hardware Integration & Static Tube Localization
Hardening of the Absolute Capacitance (CDC) subsystem: verify unit auto-detection ($< 500\text{ pF}$ vs raw counts), robust open-circuit/disconnect thresholds, conversion equations, and adaptive Median Absolute Deviation (MAD) static tube localization across vertical, horizontal, and diagonal orientations without requiring live zero-calibration.

### R4. 5-Scenario Generalizability & Empirical Metric Reproducibility
Validate performance across all 5 canonical scenarios (Baseline, Touching, Friction, Pulling, Peeling) on the 81 bench recordings under Leave-One-File-Out (LOFO) cross-validation (`scripts/evaluate_5_scenarios.py --mode oof`). Guarantee 100% episode sensitivity on critical detachment events (Pulling & Peeling) while maintaining zero or near-zero false alarms on normal behaviors.

### R5. Research Documentation, Presentation Deck, & Strict Invariant Enforcement
Ensure all research documentation (`docs/SMART_DRESSING_PROGRESS_REPORT_BIOMEDICAL_AI.md`, `docs/CONTOUR_AND_STEP_HEIGHT_COMPENSATION_GUIDE.md`, `docs/OBS_STUDIO_GROUND_TRUTH_SYNC_GUIDE.md`, `docs/Hardware_Deck_Spec.md`) perfectly match measured data. Strictly enforce all 9 repository invariants in `AGENTS.md` (browser never classifies, no hand-coded probabilities, no invented patient identity, no emoji, `SPEC_DETACH_MAX = 25000`, `Data/metrics.json` reproduces identically).

## Verification Resources
- Existing test suite: `python -m pytest tests/ -q` (119 tests covering invariants, endpoints, CDC, next-gen features, serial streaming, and regressions).
- Metric verification: `python main.py --verify-metrics` against `Data/metrics.json`.
- 5-Scenario evaluator: `python scripts/evaluate_5_scenarios.py --mode oof`.
- Repository contract: `AGENTS.md` detailing all 9 non-negotiable invariants.

## Acceptance Criteria

### Automated Test Suite & Invariants
- [ ] `python -m pytest tests/ -q` executes and passes 100% with zero failures.
- [ ] `python main.py --verify-metrics` passes with zero drift against `Data/metrics.json`.
- [ ] Invariant 1 verified: `app.js` and `web_serial.js` contain no classification logic (`nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`).
- [ ] Invariant 2 verified: `classify_deltas()` contains no hand-coded probabilities; probability outputs strictly match `full_proba()`.
- [ ] Invariant 3 verified: Bed slots return `patient_id: None` and `cpri_percent: None` until operator input (no fabricated patient names or wards).
- [ ] Invariant 5 verified: `SPEC_DETACH_MAX == 25000` maintained.
- [ ] Invariant 7 verified: Zero emoji in `web/index.html`, `web/app.js`, `web/web_serial.js`, or server status strings.

### 5-Scenario & Algorithm Generalizability
- [ ] Pulling and Peeling scenarios achieve 100% episode sensitivity under Leave-One-File-Out cross-validation.
- [ ] Sustained press (11 files) and friction (10 files) achieve 0.0% false alarms with the 7-of-6 Hold 9 annunciator.
- [ ] Horizontal pull is correctly recognized despite zero lift gate signal ($\le -300\text{ ct}$), via spatial distribution features.

### Hardware & Contour Compensation
- [ ] `analyze_surface_topography()` correctly classifies planar, contoured, and stepped ridge profiles and computes per-pad adaptive gates.
- [ ] `compute_fractional_deltas()` produces scale-invariant deltas across varying baseline baselines.
- [ ] CDC mode in `LivePipeline` correctly distinguishes normal pF values ($20-40\text{ pF}$) from true disconnects ($< 1.0\text{ pF}$).
- [ ] Adaptive MAD tube localization correctly identifies tube shadow across multiple geometric orientations without throwing on NaN/negative values.

## 2026-09-16T21:49:30Z

Perform a deep adversarial vulnerability audit, weakness discovery, and end-to-end hardening of the Smart Extubation Early Warning system across all layers: adversarial signal fuzzing, long-session memory leak prevention, serial communication jitter tolerance, and cross-session mounting domain generalization.

Working directory: d:/Projects/Project2
Integrity mode: development

## Requirements

### R1. Adversarial Signal Fuzzing & Malformed Frame Resilience
Perform rigorous adversarial stress-testing against the real-time ingest pipeline (`LivePipeline` in `main.py`, WebSocket `/ws/live_sensor`, and `SerialFrameSource`). Inject byte-level corruptions, packet truncation, frame desync, extreme capacitive noise spikes ($> 50,000\text{ counts}$), mixed NaN/Inf arrays, and high-frequency disconnect/reconnect thrashing. Ensure the system never crashes, hangs, deadlocks, or allows baseline state poisoning.

### R2. Long-Session Memory Leak & Browser Console Stability
Audit and harden `web/app.js` and `web/web_serial.js` against memory exhaustion during continuous multi-hour ICU monitoring sessions. Verify that Chart.js telemetry ring buffers, audio context oscillator nodes, WebSocket event listeners, and WebSerial chunk buffers are strictly bounded and garbage-collected without memory leaks or UI rendering degradation.

### R3. Hardware Communication & Serial Jitter Tolerance
Harden client-side WebSerial and server serial bridges against hardware anomalies: USB unplugging mid-stream, transient port enumeration delays, line jitter, and corrupted delimiter bytes. Ensure that hardware disconnects immediately and cleanly transition to the "Sensor Disconnected" state without triggering false clinical alarms or crashing background worker threads.

### R4. Cross-Session Generalization & Synthetic Domain Adaptation
Examine model behavior under simulated physical mounting perturbations (baseline shifts $\pm 20\%$, skin impedance variations, non-planar stress concentration). Hardening of feature normalization and decision logic to ensure detection robustness across different sensor applications beyond the single bench session (S0), while maintaining strict mathematical transparency.

### R5. Zero-Regression Invariant Verification & Guard Suite Expansion
Strictly maintain all 9 non-negotiable invariants defined in `AGENTS.md` (the browser never classifies, nothing hand-codes probabilities in `classify_deltas()`, no invented patient identities, no emoji, `SPEC_DETACH_MAX = 25000`, `Data/metrics.json` reproduces identically). Add comprehensive automated tests covering all newly identified weaknesses and edge cases.

## Verification Resources
- Existing test suite: `python -m pytest tests/ -q` (all tests passing green).
- Metrics reproduction check: `python main.py --verify-metrics` against `Data/metrics.json`.
- 5-Scenario evaluator: `python scripts/evaluate_5_scenarios.py --mode oof`.
- Invariants definition: `AGENTS.md`.

## Acceptance Criteria

### Automated Stress Testing & Fuzzing Resilience
- [ ] Ingestion pipelines successfully survive an automated fuzzing suite (1,000+ malformed, non-finite, and out-of-order frames) with 0 unhandled exceptions or filter corruption.
- [ ] High-frequency disconnect/reconnect bursts (50 cycles) transition cleanly between active and disconnected states without race conditions or thread starvation.

### Browser Console & Memory Stability
- [ ] Telemetry ring buffers in `web/app.js` are strictly capped (e.g. maximum frame history), with zero unbound array growth over 10,000 simulated frames.
- [ ] Audio alarm synthesizers recycle audio contexts cleanly without leaking active audio nodes.

### Hardware & Communication Jitter
- [ ] Serial stream parser safely drops corrupted lines, framing noise, and non-numeric tokens without throwing unhandled exceptions.
- [ ] A disconnected serial port or severed cable triggers clean disconnect reporting on both server and client within 1.5 seconds.

### Invariant & Metric Reproducibility
- [ ] `python -m pytest tests/ -q` executes and passes 100% with zero failures.
- [ ] `python main.py --verify-metrics` reproduces within 2% (0 drift) against `Data/metrics.json`.
- [ ] Invariant 1 verified: `web/app.js` and `web/web_serial.js` contain zero classification logic.
- [ ] Invariant 2 verified: `classify_deltas()` contains zero hand-coded probabilities.
- [ ] Invariant 3 verified: Bed slots return `patient_id: None` and `cpri_percent: None` until operator input.

## 2026-09-17T02:05:11Z

Comprehensive full-spectrum defect audit, weakness elimination, and robust hardening of the Smart Extubation Early Warning system across backend ingestion, frontend console, hardware serial bridge, and invariant compliance.

Working directory: d:/Projects/Project2
Integrity mode: development

## Requirements

### R1. Comprehensive System-Wide Defect Audit & Hardening
Audit the full Smart Extubation Early Warning codebase (`main.py`, `web/app.js`, `web/web_serial.js`, `web/index.html`, `web/style.css`, and `tests/`) to identify and resolve software bugs, numerical instabilities, unhandled exceptions, and edge-case failures across real-time ingestion, API endpoints, and client console.

### R2. Strict Invariants & Clinical Guardrails Enforcement
Ensure complete, non-negotiable compliance with all 9 project invariants defined in `AGENTS.md`:
1. The browser console must never classify or compute severity, CPRI, or pad counts.
2. The model serving path must never use hand-coded probabilities in `classify_deltas()`.
3. No invented patient identities, fabricated ward data, or fake bed statistics.
4. Displayed numbers must be measured from `/api/v6/metrics` or left blank.
5. `SPEC_DETACH_MAX` must remain 25,000 counts.
6. The Dockerfile and deployment scripts must never permit `--allow-public-no-key`.
7. Zero emoji in UI, console, scripts, and server status strings.
8. Disclaimer that the system has not been assessed against IEC 62304 must appear in both `index.html` and `app.js`.
9. `Data/metrics.json` must strictly reproduce via `--verify-metrics`.

### R3. Real-Time Streaming, Hardware Bridge & Memory Reliability
Harden the real-time sensor ingest pipeline and frontend against streaming anomalies, including serial framing noise, transient USB disconnects, WebSocket reconnect storms, and long-session memory leaks in canvas/chart ring buffers. Ensure clean transitions to disconnected states without phantom clinical alarms or thread deadlocks.

### R4. Regression Guard Expansion & Empirical Metric Verification
Maintain 100% green test passing on all existing and newly added automated tests. Any newly identified edge case or defect must be accompanied by an objective behavioral test guard in `tests/` that fails on the defect and passes on the fix.

## Acceptance Criteria

### Test Suite & Metric Integrity
- [ ] `python -m pytest tests/ -q` passes 100% with 0 failures.
- [ ] `python main.py --verify-metrics` passes with zero drift against `Data/metrics.json`.
- [ ] `python main.py --verify-pads` reports Spearman rho = 1.0000 and 0 inversions.
- [ ] `python main.py --audit Data` completes without runtime crash.

### Invariants Compliance
- [ ] Verification checks confirm that `web/app.js` and `web/web_serial.js` contain no classification logic (`nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`).
- [ ] `classify_deltas()` probability outputs strictly match `full_proba()` across all evaluation frames.
- [ ] Bed slots report `patient_id: None` and `cpri_percent: None` until explicit user input.
- [ ] Zero emoji characters found across `web/index.html`, `web/app.js`, `web/web_serial.js`, and server responses.
- [ ] IEC 62304 non-certification notice is visibly present in `web/index.html` and running in `web/app.js`.

### Reliability & Resilience
- [ ] Serial stream ingestion handles corrupted lines, truncated bytes, and non-numeric tokens without uncaught exceptions.
- [ ] Simulated hardware disconnect cleanly updates system state within 1.5 seconds without emitting false level-2/3 alarms.
- [ ] Browser console telemetry buffers remain bounded without memory leaks over extended playback.
