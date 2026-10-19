# สรุปโครงสร้างระบบและการทำงานร่วมกัน (System Architecture & Component Mapping)
**โครงการ:** Smart Extubation Early Warning System  
**ผู้พัฒนา:** เด่นพงศ์ สุรเชษฐ์ชัย (Denpong Surachetchai)  

---

## 1. ภาพรวมระบบ (System Overview)

ระบบตรวจจับและแจ้งเตือนความเสี่ยงการดึงหรือหลุดของท่อช่วยหายใจ (Unplanned Extubation: UE) ล่วงหน้า ทำงานร่วมกับแผ่นตรวจวัดประจุไฟฟ้าความจุเหนี่ยวนำ (25-Channel Capacitive Sensor Array) โดยประมวลผลสัญญาณแบบ Real-time ที่ความถี่ 10 Hz ด้วยอัลกอริทึม Machine Learning เพื่อจำแนกเหตุการณ์ออกเป็น 4 ระดับ:
1. **Normal (Level 0):** สภาวะแผ่นปิดสนิท ไร้แรงรบกวน
2. **Touch (Level 1):** การสัมผัสหรือกดทับเบา ไม่มีความเสี่ยงดึงท่อ
3. **Peel (Level 2):** แผ่นเซนเซอร์เริ่มลอกตัวจากผิวหนัง (สัญญาณเตือนระยะเริ่มแรก)
4. **Pull (Level 3):** เกิดแรงดึงท่อโดยตรงหรือแผ่นหลุดวิกฤต (วิกฤติต้องเข้าจัดการทันที)

---

## 2. แผนผังการทำงานและการเชื่อมโยงโมดูล (Component Mapping)

```
[ Hardware: 25-ch Sensor Array ]
             │  (USB Serial 115200 baud / Web Serial API)
             ▼
[ Ingest Layer: STX/ETX Frame Parser ]
             │
             ▼
[ Signal Processing: LivePipeline (main.py) ]
   ├── Kalman Dynamic Baseline (ติดตาม Drift ของประจุแบบปรับตัวอัตโนมัติ)
   ├── Feature Extractor (สกัด 34 Features: 25 Pad Deltas + 9 Spatial Statistics)
   └── Model Predictor (HistGradientBoosting / Random Forest)
             │
             ├──► [ Annunciator & Temporal Voting ] (กรอง Jitter / Hold หน่วงเวลา)
             │          │
             │          ├──► [ WebSocket Server ] ──► [ Web Dashboard (web/) ]
             │          │                               ├── 25-Pad Capacitive Grid
             │          │                               ├── CPRI Risk Gauge & Chart
             │          │                               └── Alarm Signal (IEC convention)
             │          │
             │          └──► [ LineAlerter Engine ] ──► [ LINE Notify / Webhook ]
             │                                              ├── Token Server-Side Protection
             │                                              ├── Cooldown & Anti-Spam
             │                                              └── Audit Trail (JSON Lines)
```

---

## 3. รายละเอียดไฟล์และหน้าที่การทำงาน (What Uses What)

### 3.1 ฝั่ง Backend & ประมวลผลหลัก (`main.py`)
- **FastAPI / Uvicorn Server:** เป็นแกนกลางทำหน้าที่เปิด REST API และ WebSocket endpoint (`/ws/live_sensor`)
- **`LivePipeline` (Class):**
  - **ตัวรับข้อมูล:** รับเฟรมดิบ 25 channels จากทั้ง USB COM port ในเครื่อง หรือ Web Serial ผ่านเบราว์เซอร์
  - **Kalman Baseline (`KalmanBaseline`):** คัดกรองและปรับ baseline อัตโนมัติ ป้องกันปัญหา baseline ลอยตัวจากอุณหภูมิและความชื้นของเหงื่อ
  - **Feature Extraction:** คำนวณ delta เทียบ baseline และสกัดสถิติเชิงพื้นที่ (Spatial gradient, variance, max delta, ratio) รวม 34 features
  - **Classification Engine (`classify_deltas`):** ส่ง feature เข้าโมเดล Tree-based Ensemble เพื่อประเมินความน่าจะเป็นและ Class **โดยคำนวณที่ฝั่ง Server 100% (Browser ไม่ทำการ classify เอง)**
- **`LineAlerter` (Class):**
  - ระบบคัดกรองและส่งการแจ้งเตือน LINE Messaging API / Webhook
  - ตรวจสอบระดับการเตือนตาม `levels` และ `min_level`
  - มี Cooldown รายเตียง (ป้องกันการส่งข้อความซ้ำซ้อนรบกวนพยาบาล) และกลไก Redirect Refusal เพื่อความปลอดภัยของระบบเครือข่าย

### 3.2 ฝั่งหน้าบ้าน Web Telemetry Console (`web/`)
- **`web/index.html`:**
  - ส่วนแสดงผลหน้าจอแบบ Real-time Dashboard ออกแบบตามมาตรฐานเครื่องมือแพทย์
  - ประกอบด้วย Heatmap 25 pads แสดงค่าประจุแต่ละจุด, แถบสถานะผู้ป่วย, มาตรวัดความเสี่ยง CPRI (Continuous Patient Risk Index), และตัวควบคุมการแจ้งเตือน LINE
- **`web/app.js`:**
  - เชื่อมต่อ WebSocket เข้ากับ Backend ดึงสตรีมข้อมูลมาวาดกราฟและอัปเดต Heatmap ทุกเฟรม (10 FPS)
  - ควบคุม Web Audio API สร้างเสียงเตือนระดับ Warning และ Critical ตามมาตรฐาน IEC 60601-1-8
  - จัดการ UI State, การสลับภาษา (EN/TH), และการส่งค่าตั้งค่าแจ้งเตือนไปยัง API
- **`web/web_serial.js`:**
  - เชื่อมต่อฮาร์ดแวร์บอร์ดเซนเซอร์ผ่านพอร์ต USB ตรงจากเบราว์เซอร์ด้วย Web Serial API โดยไม่ต้องลงไดรเวอร์พิเศษเพิ่มเติม
- **`web/style.css`:**
  - กำหนดธีมสีและการจัดวาง Layout แบบ Responsive สำหรับจอมอนิเตอร์ประจำเตียง

### 3.3 ชุดข้อมูลและโมเดล (`Data/`)
- **`Data/*.csv`:** ชุดบันทึกข้อมูลการทดลองจริง 81 ไฟล์ (Bench recordings) ครอบคลุมพฤติกรรมดึง ลอก สัมผัส และปกติ
- **`Data/metrics.json`:** บันทึกผลชี้วัดประสิทธิภาพของโมเดลระดับ Leave-One-File-Out (LOFO) ที่ผ่านการคำนวณและตรวจสอบความถูกต้องแล้ว (Accuracy, F1-Score, False Alarm Rate)

### 3.4 ชุดทดสอบความถูกต้อง (`tests/`)
- **`tests/test_invariants.py`:** ตรวจสอบ 9 กฎเหล็กของโปรเจกต์ เช่น ห้ามมี Emoji, ต้องมีข้อความปฏิเสธความรับผิดชอบ IEC 62304, ข้อกำหนด `SPEC_DETACH_MAX = 25000` และ metrics ต้อง reproduce ได้ตรงเดิม
- **`tests/test_line_notify.py`:** ทดสอบลอจิกการแจ้งเตือน LINE, การทดเวลา cooldown, การกรองสิทธิ์ และการบันทึก audit log
- **`tests/test_all_endpoints.py`:** ทดสอบการทำงานของ REST API และ WebSocket ทั้งหมด
- **`tests/test_console_indicators.py`:** ทดสอบสถานะไฟเตือนและการคำนวณตัวชี้วัดหน้าคอนโซล

### 3.5 สคริปต์เสริม (`scripts/`)
- **`scripts/make_confusion_lofo81.py`:** ดึงผลจาก `metrics.json` มาพล็อตภาพ Confusion Matrix
- **`scripts/make_defense_figures.py`:** สร้างกราฟวิเคราะห์เทียบสเปกเซนเซอร์และค่าสัญญาณสำหรับเอกสารสรุปผล
- **`run.py`:** ตัวช่วยรันโปรเจกต์คำสั่งเดียว เช่น `python run.py server`, `python run.py test`, `python run.py verify`

---

## 4. แหล่งข้อมูลและการเชื่อมต่อภายนอก (External Integrations)
1. **LINE Messaging API / Webhook:** ส่งข้อความแจ้งเตือนเข้าสมาร์ตโฟนของบุคลากรทางการแพทย์แบบ Real-time
2. **Local Storage:** เก็บประวัติการตรวจวัดและ Audit Log ไว้ที่เครื่อง ไม่มีการส่งข้อมูลส่วนบุคคลของผู้ป่วยออกนอกระบบ
