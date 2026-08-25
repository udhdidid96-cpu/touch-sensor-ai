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
