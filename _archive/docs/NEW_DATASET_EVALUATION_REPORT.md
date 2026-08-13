# 📊 รายงานประเมินผลชุดข้อมูลใหม่ 81 ไฟล์ CSV (NEW DATASET REPORT)
## ระบบเตือนภัยการดึงสายยางหลุดล่วงหน้าด้วย Multi-Class AI & RBF Heatmap

---

## 📁 1. โครงสร้างชุดข้อมูลใหม่ (Dataset Summary)

ข้อมูลที่ถูกจัดเก็บใหม่ในโฟลเดอร์ `C:\Users\denpo\OneDrive\Desktop\Project2\Data` แบ่งออกเป็น 9 โฟลเดอร์ รวม **81 ไฟล์ CSV** (3,007 เฟรมสัญญาณ):

| โฟลเดอร์ (Class Directory) | จำนวนไฟล์ | รูปแบบการเก็บ (Scenario) | Ground Truth Class |
| :--- | :---: | :--- | :---: |
| **`N_base`** | 5 ไฟล์ | ปล่อยนิ่ง 1 นาที (Baseline) | **Class 0: Normal Baseline** |
| **`Brief Touch`** | 10 ไฟล์ | แตะสั้นๆ 30 วินาที | **Class 1: Incidental Touch** |
| **`Press`** | 10 ไฟล์ | มือกาบทับ 10 วินาที | **Class 1: Hand Press** |
| **`Friction`** | 10 ไฟล์ | ผ้าลูบผ่าน 15 วินาที | **Class 1: Friction/Clothing** |
| **`Normal Mix`** | 5 ไฟล์ | แตะ ถู ปล่อยนิ่ง ผสมกัน 30 วินาที | **Class 1: Normal Mix** |
| **`Peel`** | 10 ไฟล์ | แผ่นแปะค่อยๆ ลอกออก | **Class 2: Dressing Peel (Warning)** |
| **`Vertical Pull NO G`** | 11 ไฟล์ | ดึงตั้งฉาก 5-10 วินาที | **Class 3: Vertical Pull (Alarm)** |
| **`Horizontal Pull NO G`** | 10 ไฟล์ | ดึงขนาน 5-10 วินาที | **Class 3: Horizontal Pull (Alarm)** |
| **`PowerP`** | 10 ไฟล์ | ดึงรุนแรงกระชาก | **Class 3: Power Pull (Critical)** |

---

## 🏆 2. ผลการประเมินประสิทธิภาพโมเดล AI (Multi-Class Leave-One-File-Out CV)

ทดสอบประเมินผลด้วยโมเดล **Multi-Class Random Forest (11 Spatio-Temporal Features)** ผ่านวิธี **Leave-One-File-Out Cross Validation**:

- **File-Level Accuracy**: **88.89%**
- **Macro F1-Score**: **0.8501**
- **Weighted F1-Score**: **0.8908**

### 📊 รายงานประสิทธิภาพแยกตามคลาส (Detailed Classification Report):
```
                             Precision    Recall  F1-Score   Support Files
0: Normal Baseline (Static)     0.50       0.80      0.62          5
1: Incidental Touch/Press       0.88       1.00      0.93         35
2: Dressing Peel (Warning)      1.00       1.00      1.00         10  (Perfect 100%!)
3: Extubation Pull (Alarm)      1.00       0.74      0.85         31  (Zero False Alarm!)
```

> 🖼️ **ภาพ Confusion Matrix**: บันทึกไว้ที่ [multiclass_confusion_matrix.png](file:///C:/Users/denpo/OneDrive/Desktop/Project2/Data/multiclass_confusion_matrix.png)

---

## 🔑 3. ความสำคัญของฟีเจอร์สัญญาณ (Feature Importances)

จากการวิเคราะห์ฟีเจอร์ที่มีผลต่อการแยกแยะการดึงสายออกจากนิ้วแตะมากที่สุด:
1. **Min Delta (-16.57%)**: ค่า Capacitive ดิ่งลงต่ำสุดใต้แผ่น (บ่งบอกถึงสายลอย/ลอก)
2. **Max Delta (+15.85%)**: ค่า Capacitive พุ่งสูงขึ้น (บ่งบอกถึงนิ้วมือ/การกดทับ)
3. **Std Delta (14.72%)**: ความผันผวนกระจายตัวของสัญญาณ 25 ช่อง
4. **Spatial Gradient Y (14.69%)**: อัตราความต่างของสัญญาณแนวตั้งตามแถบแผ่นยึด
5. **Mean Delta (14.57%)**: ค่าเฉลี่ยการเปลี่ยนแปลงสัญญาณรวมทั้งแผ่น
6. **Spatial Gradient X (14.01%)**: อัตราความต่างของสัญญาณแนวนอน

---

## 💻 4. เว็บแดชบอร์ดเตือนภัยการแพทย์ v3.5 (Updated Web Center)

แดชบอร์ด [touch_app_v3.py](file:///c:/Users/denpo/OneDrive/เอกสาร/New folder/touch_app_v3.py) ได้รับการอัปเดตให้อ่านข้อมูลจากทั้ง 81 ไฟล์ CSV ใน 9 โฟลเดอร์โดยอัตโนมัติ:
- เลือกเล่นไฟล์จาก Dropdown ได้ครบทุกโฟลเดอร์ (`N_base`, `Brief Touch`, `Press`, `Friction`, `Normal Mix`, `Peel`, `Vertical Pull NO G`, `Horizontal Pull NO G`, `PowerP`)
- เรนเดอร์ RBF 2D Heatmap Surface และคำนวณ **Patient Risk Index (CPRI %)** เรียลไทม์
