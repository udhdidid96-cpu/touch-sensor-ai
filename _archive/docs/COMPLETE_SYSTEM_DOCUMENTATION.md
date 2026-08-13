# 📘 คู่มือและคำอธิบายระบบสมบูรณ์ (Complete System Documentation)
## ระบบเฝ้าระวังและแจ้งเตือนการหลุดของสายยางทางการแพทย์ล่วงหน้าด้วย Capacitive Touch Sensor, Multi-Class AI และ RBF Heatmap UI

---

## 1. 🎯 ภาพรวมของโครงการ (Project Overview)
โครงการนี้มีวัตถุประสงค์เพื่อสร้างระบบเตือนภัยล่วงหน้าทางการแพทย์ (Early Warning System) เพื่อป้องกัน **การหลุดของสายยางหลอดลมหรือสายให้สารน้ำโดยไม่ตั้งใจ (Unplanned Extubation / Tube Dislodgement)** ในผู้ป่วยวิกฤต โดยใช้แผ่นยึดสายยางอัจฉริยะความละเอียด 25 ช่องสัญญาณ (Capacitive Touch Sensor Patch) 

ระบบสามารถแยกแยะระหว่าง **"เหตุการณ์ปกติ/สัมผัสสั้นๆ (Incidental Touch/Press)"** กับ **"เหตุการณ์อันตรายลอกหลุด (Dressing Peel & Tube Pulling)"** ได้อย่างแม่นยำ ปราศจาก False Alarm 

---

## 2. 📁 การจัดการและโครงสร้างชุดข้อมูลใหม่ (Dataset Architecture)

ชุดข้อมูลใหม่ถูกจัดเก็บและสแกนอย่างเป็นระบบที่ `C:\Users\denpo\OneDrive\Desktop\Project2\Data` รวมทั้งสิ้น **81 ไฟล์ CSV** (3,006 เฟรมสัญญาณ):

| ชื่อโฟลเดอร์ (Folder Name) | จำนวนไฟล์ | คำอธิบายสภาวะการทดลอง (Experiment Scenario) | กำหนดคลาส (Ground Truth) |
| :--- | :---: | :--- | :---: |
| **`N_base`** | 5 ไฟล์ | แผ่นยึดติดนิ่งบนผิว 1 นาที (Normal Baseline) | **Class 0: Normal Baseline** |
| **`Brief Touch`** | 10 ไฟล์ | นิ้วมือแตะสั้นๆ 30 วินาที | **Class 1: Incidental Touch** |
| **`Press`** | 10 ไฟล์ | ฝ่ามือกาบทับ 10 วินาที | **Class 1: Hand Press** |
| **`Friction`** | 10 ไฟล์ | ผ้าลูบผ่านแผ่นยึด 15 วินาที | **Class 1: Clothing Friction** |
| **`Normal Mix`** | 5 ไฟล์ | กิจกรรมปกติผสมกัน (แตะ ถู ปล่อยนิ่ง) 30 วินาที | **Class 1: Normal Mix Activity** |
| **`Peel`** | 10 ไฟล์ | แผ่นยึดค่อยๆ ลอกออกจากขอบผิวหนัง | **Class 2: Dressing Peel (Warning)** |
| **`Vertical Pull NO G`** | 11 ไฟล์ | สายยางถูกดึงในแนวตั้งฉาก 5-10 วินาที | **Class 3: Vertical Pull (Alarm)** |
| **`Horizontal Pull NO G`** | 10 ไฟล์ | สายยางถูกดึงในแนวนอนขนานผิว 5-10 วินาที | **Class 3: Horizontal Pull (Alarm)** |
| **`PowerP`** | 10 ไฟล์ | สายยางถูกกระชากดึงรุนแรง | **Class 3: Power Pull (Critical)** |

---

## 3. 🔌 การสอบเทียบสัญญาณและการจัดเรียงพิกัด (Physical Order & Standardization)

### 3.1 การวิเคราะห์ลำดับกดปุ่มดั้งเดิม (`1 by 1.csv`)
จากไฟล์ `1 by 1.csv` ระบบได้ใช้อัลกอริทึมใน [analyze_sensor_mapping.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/analyze_sensor_mapping.py) สกัดลำดับการถูกกดจริงตามกายภาพของแผ่นแปะ:
```
Signal-20 -> Signal-21 -> Signal-19 -> Signal-22 -> Signal-18 -> Signal-23 -> Signal-17 -> Signal-24 -> Signal-16 -> Signal-25 -> Signal-15 -> Signal-14 -> Signal-13 -> Signal-12 -> Signal-6 -> Signal-7 -> Signal-5 -> Signal-8 -> Signal-4 -> Signal-9 -> Signal-3 -> Signal-10 -> Signal-2 -> Signal-11 -> Signal-1
```

### 3.2 การแปลงชื่อ Header ด้านบน (Standardized Sensor Headers)
สคริปต์ [rename_and_reorder_all_sensors.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/rename_and_reorder_all_sensors.py) ได้ทำการจัดเรียงคอลัมน์และเปลี่ยนชื่อ Header ด้านบนของไฟล์ CSV ทุกไฟล์ (175 ไฟล์) ให้กลายเป็น **`Sensor-1` ถึง `Sensor-25`** เพื่อขจัดความสับสน:
- **`Sensor-1`**: ตรงกับปุ่มที่ถูกกดตัวที่ 1 (`Signal-20` ดั้งเดิม)
- **`Sensor-2`**: ตรงกับปุ่มที่ถูกกดตัวที่ 2 (`Signal-21` ดั้งเดิม)
- ...
- **`Sensor-25`**: ตรงกับปุ่มที่ถูกกดตัวที่ 25 (`Signal-1` ดั้งเดิม)

### 3.3 การปรับชดเชยระดับฐาน (Offset Calibration)
ใช้เฟรมแรกเริ่ม 5 เฟรมในการปรับชดเชย (Baseline Calibration) ค่า Capacitance ให้อยู่ที่ระดับ **28,000 counts**:
$$\text{Offset}_i = 28000.0 - \frac{1}{5}\sum_{t=1}^{5} S_{i,t}$$
$$S_{i,t}^{\text{calibrated}} = S_{i,t}^{\text{raw}} + \text{Offset}_i$$

---

## 4. 🤖 โมเดลปัญญาประดิษฐ์ Multi-Class AI & ผลการประเมิน (Machine Learning Suite)

สคริปต์ [train_multiclass_classifier.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/train_multiclass_classifier.py) สกัดฟีเจอร์มิติเวลาและพื้นที่ 11 ตัวแปร (11 Spatio-Temporal Features) ได้แก่:
1. `Min Delta`: ค่าการลดลงต่ำสุดใต้แผ่น ($\min(S_i - 28000)$)
2. `Max Delta`: ค่าการเพิ่มขึ้นสูงสุดบนแผ่น ($\max(S_i - 28000)$)
3. `Mean Delta`: ค่าเฉลี่ยการเปลี่ยนแปลงรวม ($\text{mean}(S_i - 28000)$)
4. `Std Delta`: ค่าความผันผวนกระจายตัว ($\text{std}(S_i - 28000)$)
5. `Drop Count (<= -300)`: จำนวนเซนเซอร์ที่สัญญาณดิ่งลดลง
6. `Drop Count (<= -600)`: จำนวนเซนเซอร์ที่สัญญาณดิ่งลดลงปานกลาง
7. `Drop Count (<= -1000)`: จำนวนเซนเซอร์ที่สัญญาณดิ่งลดลงรุนแรง
8. `Spike Count (>= +300)`: จำนวนเซนเซอร์ที่สัญญาณพุ่งสูงขึ้น
9. `Spike Count (>= +1000)`: จำนวนเซนเซอร์ที่สัญญาณพุ่งสูงขึ้นรุนแรง
10. `Spatial Grad X`: อัตราความต่างของสัญญาณแนวนอน
11. `Spatial Grad Y`: อัตราความต่างของสัญญาณแนวตั้ง

### 🏆 ผลการทดสอบโมเดล (Leave-One-File-Out Cross Validation):
- **Accuracy รวมทุกคลาส**: **90.00%**
- **Weighted F1 Score**: **0.8989**
- **Class 2 (Dressing Peel Warning)**: Precision **1.00**, Recall **1.00**, F1-score **1.00** *(สมบูรณ์แบบ 100%)*
- **Class 3 (Extubation Pull Alarm)**: Precision **1.00** *(Zero False Alarm ปราศจากการแจ้งเตือนผิดพลาด)*

---

## 🎨 5. ระบบหน้าจอแสดงผล Web Dashboard Center v5.0 ([touch_app_v5.py](file:///c:/Users/denpo/OneDrive/เอกสาร/New folder/touch_app_v5.py))

หน้าจอแดชบอร์ดทำงานบน `http://localhost:8081` ถูกพัฒนาด้วย FastAPI, HTML5 Canvas, SVG Dynamic Overlay และ SciPy RBF Surface Interpolation:

### 📐 5.1 โครงสร้างรูปทรงแผ่นแปะจริง (90mm x 120mm Custom Patch Silhouette)
จำลองพิกัดพิกเซลตามรูปถ่ายแผ่นแปะจริงขนาด 90x120 mm วางตำแหน่งจุดเซนเซอร์ทั้ง 25 จุดที่พิกัดทางกายภาพจริง:
- **แถวบนสุด (Top Row)**: Pad 16, 15, 11, 10
- **แถวที่ 2**: Pad 18, 17, 12, 9, 8
- **แถวกลาง (Mid Row)**: Pad 20, 19, 13, 7, 6
- **แถวที่ 4**: Pad 22, 21, 14, 5, 4
- **แถวที่ 5**: Pad 24, 23, 3, 2
- **แถวล่างสุด (Bottom Row)**: Pad 25, 1

### 🔴🔵 5.2 การแยกสีตามสภาวะเหตุการณ์ (Dual-Color Indication System)
- **🔴 สีแดง / ส้ม (RED / CORAL GLOW)**: สภาวะ **แรงกดทับ / นิ้วแตะ (Press / Touch Contact)** ($\Delta C \ge +300$)
- **🔵 สีฟ้า / น้ำเงิน (CYAN / NEON BLUE GLOW)**: สภาวะ **โดนดึงออก / สายหลุด / แผ่นแปะร่อน (Peel / Pulling)** ($\Delta C \le -300$)
- **🟢 สีเขียวมรกต (EMERALD GREEN)**: สภาวะ **ปกติ (Static Baseline)** ($\Delta C \approx 0$)

---

## 📊 6. การสร้างภาพและกราฟงานวิจัย ([generate_research_plots.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/generate_research_plots.py))

สคริปต์อัตโนมัติในการรวบรวมข้อมูลเพื่อสร้างภาพกราฟสำหรับใช้ในตีพิมพ์หรือรายงานวิชาการ:
1. 🖼️ [feature_importances.png](file:///C:/Users/denpo/OneDrive/Desktop/Project2/Data/research_plots/feature_importances.png): กราฟแสดงความสำคัญของฟีเจอร์ในการแยกแยะสายหลุด
2. 🖼️ [multiclass_roc_curves.png](file:///C:/Users/denpo/OneDrive/Desktop/Project2/Data/research_plots/multiclass_roc_curves.png): เส้นโค้ง ROC-AUC แสดงประสิทธิภาพระดับ 0.90+
3. 🖼️ [3d_rbf_surface_peel.png](file:///C:/Users/denpo/OneDrive/Desktop/Project2/Data/research_plots/3d_rbf_surface_peel.png): ภาพ 3D Surface พื้นผิวความตึงการลอกของแผ่นแปะ

---

## 🛠️ 7. สรุปตำแหน่งไฟล์และสคริปต์สำคัญในโครงการ

- **สคริปต์รันเซิร์ฟเวอร์ UI v5.0**: [touch_app_v5.py](file:///c:/Users/denpo/OneDrive/เอกสาร/New folder/touch_app_v5.py) (`http://localhost:8081`)
- **สคริปต์เทรนและประเมินผล AI**: [train_multiclass_classifier.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/train_multiclass_classifier.py)
- **สคริปต์คำนวณ RBF Surface 2D**: [rbf_heatmap_engine.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/rbf_heatmap_engine.py)
- **สคริปต์จัดเรียงคอลัมน์ & เปลี่ยนชื่อ Header**: [rename_and_reorder_all_sensors.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/rename_and_reorder_all_sensors.py)
- **สคริปต์สร้างกราฟวิจัย**: [generate_research_plots.py](file:///C:/Users/denpo/OneDrive/Desktop/Project2/generate_research_plots.py)
