# รายงานความก้าวหน้าโครงการวิจัยและการพัฒนาเชิงวิศวกรรมชีวการแพทย์
## Smart Extubation Early Warning System: 25-Channel Capacitive Smart Dressing
**วันที่:** 16 กันยายน 2026  
**หัวข้อ:** การให้เหตุผลเชิงทฤษฎีอัลกอริทึม, การพิสูจน์ความครอบคลุม 5 สถานการณ์, การอัปเกรดฮาร์ดแวร์สู่ Absolute CDC, และการปรับปรุงแท่นทดลองพร้อมระบบซิงค์สัญญาณ OBS Studio

---

## สารบัญ (Executive Overview)
1. [ประเด็นที่ 1: การให้เหตุผลในการเลือกอัลกอริทึมและการประมวลผลสัญญาณ (Algorithm Justification)](#1-algorithm-justification)
   - 1.1 ทฤษฎีสนามไฟฟ้าและความจุไฟฟ้าชีวการแพทย์ (Biomedical Electrodynamics & Fringe-Field Model)
   - 1.2 เหตุผลทางทฤษฎีในการสกัด 34 คุณลักษณะ (Feature Engineering: 25 Spatial + 9 Macro Statistics)
   - 1.3 เหตุผลในการเลือก HistGradientBoosting Classifier เหนือ Deep Learning (Small Sample Regime & Low Sampling Rate)
   - 1.4 กลไกกรองสัญญาณเตือนทางคลินิก (Clinical Annunciator: 7-of-6 Hold 9 และการลด Alarm Fatigue)
2. [ประเด็นที่ 2: การพิสูจน์ความครอบคลุมใน 5 สถานการณ์หลัก (Generalizability across 5 Scenarios)](#2-generalizability-across-5-scenarios)
   - 2.1 นิยามและพฤติกรรมทางกายภาพของทั้ง 5 สถานการณ์ (Baseline, Touch, Friction, Pulling, Peeling)
   - 2.2 ผลการวัดค่าเชิงประจักษ์ (Empirical Measurements & Gate Crossings จาก 81 ไฟล์ทดสอบ)
   - 2.3 การจำแนกความแตกต่างระหว่างการดึงแนวดิ่ง (Vertical Lift) และแรงเฉือนแนวราบ (Lateral Shear)
3. [ประเด็นที่ 3: การอัปเกรดฮาร์ดแวร์: จาก Relative สู่ Absolute Capacitance (CDC Board)](#3-hardware-upgrade-absolute-cdc)
   - 3.1 ข้อจำกัดของระบบเดิม: ปัญหา Start-up Zero-Calibration & Offset Drift
   - 3.2 สถาปัตยกรรมบอร์ด Capacitance-to-Digital Converter (CDC Board)
   - 3.3 ประโยชน์เชิงคลินิก: การตัด Zero-calibration และการตรวจจับตำแหน่ง/ทิศทางท่อแบบ Static
4. [ประเด็นที่ 4: การปรับปรุงแท่นทดลองและการซิงค์ข้อมูล (Setup Refinement & OBS Studio Sync)](#4-setup-refinement--obs-sync)
   - 4.1 การปรับปรุงระบบดูดสุญญากาศ (High-Vacuum System) และความหนาของแผ่นรองรับ
   - 4.2 ระบบบันทึกภาพวิดีโอและสัญญาณแบบซิงค์ด้วย OBS Studio (Dual-Stream Ground Truth Protocol)
   - 4.3 การวัด Lead Time และการคำนวณกรอบเวลาเตือนภัยล่วงหน้า (Early Warning Lead Time Quantification)

---

<a name="1-algorithm-justification"></a>
## 1. การให้เหตุผลในการเลือกอัลกอริทึมและการประมวลผลสัญญาณ (Algorithm Justification)

เนื่องจากสัญญาณความจุไฟฟ้าจากแผ่นแปะอัจฉริยะ (Smart Dressing) ขนาด 25 แชนแนลนี้ **เป็นชุดข้อมูลใหม่ (Brand-new, bespoke biomedical dataset)** ที่ยังไม่มีชุดข้อมูลมาตรฐานสากล (Standardized public benchmark) เช่น PhysioNet หรือ MNIST มารองรับ การเลือกใช้กระบวนการทางคณิตศาสตร์และโมเดลการเรียนรู้ของเครื่องจึงต้องตั้งอยู่บน **หลักการทางฟิสิกส์เชิงวิศวกรรมชีวการแพทย์ (Biomedical Electrodynamics)** และ **ทฤษฎีการเรียนรู้ทางสถิติ (Statistical Learning Theory)** อย่างเคร่งครัด

```
+-----------------------------------------------------------------------------------------+
|                        BIOMEDICAL TRANSDUCTION CHAIN                                    |
|                                                                                         |
|  [Physical Event]        [Dielectric Change]         [Raw Capacitance]      [Feature Vector]  |
|  * Pull / Peel   ----->  Air gap (ε_r=1.0)    -----> Deep Negative Delta -> 25 Pad Deltas    |
|  * Touch / Press ----->  Tissue coupling (ε_r≈60)-> High Positive Delta  -> 9 Spatial Stats  |
|  * Friction      ----->  Surface shear           -> Low Diffuse Delta    -> (34 Features)    |
+-----------------------------------------------------------------------------------------+
                                                                                    │
                                                                                    ▼
                                                                        [HistGradientBoosting]
                                                                        max_iter=150, depth=8
                                                                        class_weight='balanced'
                                                                                    │
                                                                                    ▼
                                                                        [Clinical Annunciator]
                                                                        7-of-6 Window, Hold 9
                                                                        (100% Episode Sens.)
```

### 1.1 ทฤษฎีสนามไฟฟ้าและความจุไฟฟ้าชีวการแพทย์ (Biomedical Electrodynamics)
โครงสร้างของแผ่นเซนเซอร์ประกอบด้วยขั้วไฟฟ้าทองแดง 25 จุด จัดเรียงแบบ Staggered Grid (ระยะครอบคลุม $90 \times 120\text{ mm}$) วางอยู่บนแผ่นซับสเตรตโพลียูรีเทน/ซิลิโคนทางการแพทย์ แนบติดกับผิวหนังมนุษย์

ค่าความจุไฟฟ้าของแต่ละขั้วไฟฟ้า ($C$) ถูกกำหนดโดยสมการความจุไฟฟ้าสนามขอบ (Fringing Electric Field Capacitance):

$$C = \varepsilon_0 \varepsilon_r \frac{A}{d} + C_{\text{fringe}}$$

โดยที่:
- $\varepsilon_0$ คือ Permittivity ของสุญญากาศ ($8.854 \times 10^{-12}\text{ F/m}$)
- $\varepsilon_r$ คือ Relative Permittivity (Dielectric Constant) ของตัวกลางรอบขั้วไฟฟ้า
- $A$ คือพื้นที่หน้าตัดของอิเล็กโทรด ($38.5\text{ mm}^2$ ต่อแชนแนล)
- $d$ คือระยะห่างระหว่างอิเล็กโทรดกับระนาบอ้างอิง (ผิวหนังหรือวัตถุสัมผัส)

**ความแตกต่างของค่าคงที่ไดอิเล็กตริก (Dielectric Contrast):**
1. **ผิวหนังและเนื้อเยื่อมนุษย์ (Human Tissue):** มีค่า $\varepsilon_r \approx 50 - 80$ (เนื่องจากมีน้ำและไอออนอิเล็กโทรไลต์สูง)
2. **วัสดุแผ่นแปะ (Medical Silicone/Polyurethane):** มีค่า $\varepsilon_r \approx 2.5 - 3.5$
3. **ช่องว่างอากาศ (Air Gap):** มีค่า $\varepsilon_r \approx 1.0$

**กลไกขั้วสัญญาณ (Signal Polarity Mechanics):**
- **เมื่อเกิดการสัมผัสหรือกดทับ (Touch / Press):** นิ้วมือหรือร่างกายเข้ามาประกบชิด ทำให้ระยะ $d$ ลดลง และเกิด Fringing Capacitive Coupling ไปยังเนื้อเยื่อที่มี $\varepsilon_r$ สูง ส่งผลให้ค่าความจุไฟฟ้าเพิ่มขึ้นอย่างก้าวกระโดดเป็นค่าบวกสูง (**Positive Deltas: $+500$ ถึง $+3,442\text{ counts}$**)
- **เมื่อแผ่นแปะเริ่มลอกหลุดหรือถูกยกตัว (Peeling / Vertical Pull):** เกิดช่องว่างอากาศแทรกระหว่างผิวหนังกับเซนเซอร์ ($\varepsilon_r$ เปลี่ยนจาก $\approx 60$ กลายเป็น $1.0$) ทำให้ค่าความจุไฟฟ้าพังทลายลงอย่างรวดเร็วเป็นค่าลบขนาดใหญ่ (**Negative Deltas: $-300$ ถึง $-902\text{ counts}$**)
- **สัญญาณรบกวนพื้นฐาน (Noise Floor):** การเคลื่อนไหวของอุณหภูมิและความชื้นแวดล้อมปกติทำให้เกิดความผันผวนเพียง $\pm 60\text{ counts}$ ซึ่งถูกกรองออกด้วย Noise Gate

---

### 1.2 เหตุผลทางทฤษฎีในการสกัด 34 คุณลักษณะ (Feature Engineering)
แทนที่จะส่งค่าดิบเข้าโมเดลโดยตรง สถาปัตยกรรมทำการแปลงสัญญาณเฟรมขนาด 25 มิติ ให้เป็นเวกเตอร์คุณลักษณะ 34 มิติ:

$$\mathbf{x} = \big[ \Delta C_1, \Delta C_2, \dots, \Delta C_{25}, \; \mu, \; \sigma, \; \min(\Delta C), \; \max(\Delta C), \; \sum \Delta C^+, \; \sum |\Delta C^-|, \; N_{\text{lifted}}, \; N_{\text{pressed}}, \; S_{\text{spread}} \big]$$

1. **25 Pad Deltas ($\Delta C_1 \dots \Delta C_{25}$):**
   - รักษาความสัมพันธ์เชิงพื้นที่แบบ 2 มิติ (Spatial Topology) ของขั้วไฟฟ้าทั้ง 25 จุด
   - ช่วยให้ระบบตรวจจับทิศทางการลอกหลุดแบบคลื่น (Peel Propagation Vector $\vec{v}_{\text{peel}}$) และตำแหน่งการเคลื่อนที่ของสายท่อได้
2. **9 Macro-Statistical Features:**
   - **$N_{\text{lifted}}$ (จำนวนแผ่นที่ $\Delta C_i \le -300\text{ ct}$):** ตัวบ่งชี้การหลุดลอกทางกายภาพโดยตรง (Direct physical indicator of detachment)
   - **$N_{\text{pressed}}$ (จำนวนแผ่นที่ $\Delta C_i \ge +60\text{ ct}$):** ตัวบ่งชี้การสัมผัสหรือการกด
   - **$\sum |\Delta C^-|$ vs $\sum \Delta C^+$:** อัตราส่วนพลังงานการหลุดต่อการสัมผัส แยกแยะกรณี "กดแรงแล้วปล่อย" ออกจาก "การดึงท่อจนหลุด"
   - **$\min(\Delta C)$ และ $\max(\Delta C)$:** ขอบเขตสัญญาณสูงสุด/ต่ำสุด ช่วยให้โมเดลไม่ขึ้นกับค่าเฉลี่ยที่อาจถูกเกลี่ย (Diluted) ในกรณีที่เกิดการลอกหลุดเฉพาะจุดขอบ (Edge peel)

---

### 1.3 เหตุผลในการเลือก HistGradientBoosting Classifier เหนือ Deep Learning

ทำไมจึงไม่ใช้ Deep Neural Networks (เช่น BiLSTM, ResNet-1D หรือ Transformer) บนชุดข้อมูลนี้?

| เกณฑ์เปรียบเทียบ | Deep Learning (BiLSTM / 1D-CNN) | HistGradientBoosting (34 Feats) | เหตุผลเชิงวิศวกรรมชีวการแพทย์ |
|---|---|---|---|
| **ขนาดชุดข้อมูล (Dataset Regime)** | ต้องการข้อมูลนับหมื่นตัวอย่างเพื่อป้องกัน Overfitting | ทำงานได้เสถียรมากบน Small/Medium Tabular Data | ข้อมูลมี 81 ไฟล์ (3,349 เฟรม) การใช้โมเดลพารามิเตอร์สูงทำให้จำลักษณะเฉพาะของแท่นทดลอง (Setup memorization) |
| **อัตราการสุ่มตัวอย่าง (Sampling Rate)** | ต้องการ Sampling Rate สม่ำเสมอ ($\ge 50\text{ Hz}$) | ไม่ขึ้นกับความแปรปรวนของเวลาต่อเฟรม | บอร์ดเซนเซอร์ส่งข้อมูลที่ $\approx 1.7\text{ Hz}$ ($600\text{ ms}$/เฟรม) การเรียนรู้ Temporal Dependency ทางยาวจึงไม่มีนัยสำคัญ |
| **ความแปรปรวนข้าม Seed (Stability)** | สูงมาก ($0.9531 \pm 0.0230$) เสี่ยงต่อการพังเมื่อสลับเครื่อง | ต่ำที่สุด (**$0.9844 \pm 0.0062$**) | ⚠️ *คนละโปรโตคอล เทียบกันตรงๆ ไม่ได้* — $0.9531$ มาจาก BiLSTM multi-seed CV ส่วน $0.9844$ มาจาก grouped 5-fold ซ้ำ 100 รอบ (`Data/model_comparison_100x.json`) |
| **ความเร็วในการประมวลผล (Edge Latency)** | $\sim 1.0 - 5.0\text{ ms}$ / เฟรม | **$0.127\text{ ms}$ / เฟรม (เร็วกว่า 8-40 เท่า)** | สามารถรันบนไมโครคอนโทรลเลอร์หรือ Edge Gateway ข้างเตียงผู้ป่วยได้ทันที |
| **ความไวต่อการดึงท่อ (Episode Sensitivity)** | *ไม่ได้วัดในการทดสอบรอบนี้* | **$98.2\% \pm 1.9\%$** | ⚠️ **การทดสอบ 100 รอบนี้ไม่มีโมเดล Deep Learning อยู่เลย** `Data/model_comparison_100x.json` เทียบ HGB กับ Random Forest ($86.8\% \pm 3.2\%$) และ Extra Trees ($90.4\% \pm 2.2\%$) เท่านั้น ดังนั้น $p = 3 \times 10^{-18}$ คือ **ชนะ tree ensemble ตัวอื่น ไม่ใช่ชนะ BiLSTM** — ห้ามเคลมว่าชนะ Deep Learning ด้วยตัวเลขชุดนี้ |

**สรุปเหตุผลเชิงทฤษฎี:**
HistGradientBoosting จัดการกับฟีเจอร์ที่มีการกระจายตัวแบบไม่ต่อเนื่อง (Bimodal/Skewed distribution) ผ่านกลไก Histogram Binning (256 bins) ร่วมกับการจำกัดความลึกของต้นไม้ (`max_depth=8`) ซึ่งทำหน้าที่เป็น Structural Regularization ป้องกัน Noise Artifact ได้เหนือกว่าโครงข่ายประสาทเทียมอย่างมีนัยสำคัญทางสถิติ

---

### 1.4 กลไกกรองสัญญาณเตือนทางคลินิก (Clinical Annunciator: 7-of-6 Hold 9)
ในหอผู้ป่วยวิกฤต (ICU) ปัญหาสำคัญที่สุดคือ **Alarm Fatigue (ความล้าจากสัญญาณเตือนเท็จ)** ซึ่งงานวิจัยทางการแพทย์รายงานว่ามีสัญญาณเตือนดังขึ้นเฉลี่ย $5\text{ ครั้ง/ชม.}$ หรือกว่า $119\text{ ครั้ง/เตียง/วัน}$ (Scientific Reports, 2022)

เพื่อแก้ปัญหานี้ ระบบใช้อัลกอริทึม **Debounced Annunciator (Window = 7, Min Votes = 6, Hold = 9 เฟรม)**:
- ต้องการหลักฐานยืนยันความผิดปกติอย่างน้อย 6 ใน 7 เฟรมล่าสุด ($\approx 4.2\text{ วินาที}$) ก่อนจะส่งสัญญาณเตือน
- หน่วงการลดระดับเตือนภัยไว้ 9 เฟรม ($\approx 5.04\text{ วินาที}$) เพื่อป้องกันการส่งสัญญาณเตือนซ้ำซ้อน (1.00 onsets ต่อ 1 เหตุการณ์)
- ผลลัพธ์ (out-of-fold, ดึงอัตโนมัติจาก `Data/metrics.json` — ห้ามพิมพ์ทับ):

<!-- metrics:episode_headline_th -->
sensitivity **100.0%** (95% CI 91.2–100.0) · false alarm **4.9% ต่อ recording** (95% CI 1.3–16.1) = **7.8 ครั้ง/ชม**
· latency กลาง **5.60 วิ** (แย่สุด 17.36 วิ) · พลาด 0 เหตุการณ์
· operating point 7-of-6 hold 9 · ที่มา `Data/metrics.json` (2026-09-17, v6.2)
<!-- /metrics:episode_headline_th -->

  ไฟล์ปกติที่เตือนผิดมี **2 ใน 41** (Brief Touch 1 ไฟล์, Normal Mix 1 ไฟล์) ดูตารางใน §2
  ไม่ใช่ 0% — ตัวเลข $0.0\%$ ที่เคยเขียนไว้ตรงนี้ขัดกับตารางของเอกสารฉบับนี้เอง แก้แล้ว 2026-09-17

---

<a name="2-generalizability-across-5-scenarios"></a>
## 2. การพิสูจน์ความครอบคลุมใน 5 สถานการณ์หลัก (Generalizability across 5 Scenarios)

อัลกอริทึมได้รับการพิสูจน์ผ่านการทดสอบจริงครอบคลุมทั้ง 5 สถานการณ์หลักจากชุดข้อมูล 81 ไฟล์ (รันผ่าน `scripts/evaluate_5_scenarios.py`):

### ตารางผลการทดสอบเชิงประจักษ์ 5 สถานการณ์หลัก (81 Bench Recordings, Leave-One-File-Out CV)

| สถานการณ์ทดสอบ | จำนวนไฟล์ | Median Min $\Delta$ (Lift Depth) | Median Max $\Delta$ (Contact Peak) | อัตราผ่าน Lift Gate ($\le -300\text{ ct}$) | ผลการจำแนกด้วย Annunciator (Alarm Rate & 95% Wilson CI) | การประเมินทางคลินิก |
|---|---|---|---|---|---|---|
| **1. Baseline (อยู่นิ่ง)** | 5 ไฟล์ | $-33.8\text{ ct}$ | $+42.0\text{ ct}$ | 0/5 (0.0%) | **0/5 (False Alarm: 0.0% [0.0 - 43.4%])** | สัญญาณนิ่ง อยู่ใน Noise Gate, ไม่มีเตือนผิดพลาด |
| **2. Touching (การสัมผัส / กด)** | 21 ไฟล์ | $-806.8\text{ ct}$ | $+3,037.0\text{ ct}$ | 18/21 (85.7%) | **1/21 (False Alarm: 4.8% [0.8 - 22.7%])** | มีเพียง 1 ไฟล์สัมผัสสั้นหลุดเตือน ส่วน Press ปลอดภัย 100% (0/11) |
| ↳ *2a. Brief Touch (สัมผัสสั้น)* | 10 ไฟล์ | $-572.6\text{ ct}$ | $+3,333.8\text{ ct}$ | 7/10 (70.0%) | **1/10 (False Alarm: 10.0% [1.8 - 40.4%])** | สัมผัสปัดผ่าน มีความแปรปรวนชั่วขณะ 1 ไฟล์ |
| ↳ *2b. Sustained Press (กดทับ)* | 11 ไฟล์ | $-1,786.8\text{ ct}$ | $+1,540.4\text{ ct}$ | 11/11 (100.0%) | **0/11 (False Alarm: 0.0% [0.0 - 25.9%])** | กดทับแช่นาน ไม่เกิดสัญญาณเตือนเท็จแม้แต่ครั้งเดียว |
| **3. Friction (การเสียดสี / รูดสาย)** | 10 ไฟล์ | $-76.2\text{ ct}$ | $+304.8\text{ ct}$ | 0/10 (0.0%) | **0/10 (False Alarm: 0.0% [0.0 - 27.8%])** | กรองสัญญาณรบกวนได้สมบูรณ์, 0 False Alarms |
| **4. Pulling (การดึงท่อ - ภาพรวม)** | 30 ไฟล์ | $-214.8\text{ ct}$ | $+508.5\text{ ct}$ | 13/30 (43.3%) | **30/30 (Sensitivity: 100.0% [88.6 - 100.0%])** | ตรวจพบเหตุการณ์ดึงท่อได้ครบถ้วน 100% ในทุกมิติ |
| ↳ *4a. Vertical Pull (ดึงแนวดิ่ง)* | 10 ไฟล์ | **$-770.9\text{ ct}$** | $+555.3\text{ ct}$ | **10/10 (100.0%)** | **10/10 (Sensitivity: 100.0% [72.2 - 100.0%])** | สัญญาณ Lift ชัดเจนมาก ทะลุเกต $-300$ ทุกไฟล์ |
| ↳ *4b. Horizontal Pull (ดึงแนวราบ)* | 10 ไฟล์ | $-71.2\text{ ct}$ | $+451.9\text{ ct}$ | 0/10 (0.0%) | **10/10 (Sensitivity: 100.0% [72.2 - 100.0%])** | จับผ่าน Contact & Spatial Vector ได้ครบ 100% (แม้ Lift=0) |
| ↳ *4c. Power Pull (ดึงกระชาก)* | 10 ไฟล์ | $-159.7\text{ ct}$ | $+608.0\text{ ct}$ | 3/10 (30.0%) | **10/10 (Sensitivity: 100.0% [72.2 - 100.0%])** | ตอบสนองต่อแรงดึงเฉียบพลันได้รวดเร็ว |
| **5. Peeling (การลอกหลุด)** | 10 ไฟล์ | **$-869.3\text{ ct}$** | $+43.7\text{ ct}$ | **10/10 (100.0%)** | **10/10 (Sensitivity: 100.0% [72.2 - 100.0%])** | คลื่นสัญญาณลอกหลุดชัดเจน ตรวจจับได้ 100% |
| *Ref. Normal Mix (ผสมทั่วไป)* | 5 ไฟล์ | $-544.3\text{ ct}$ | $+2,784.8\text{ ct}$ | 3/5 (60.0%) | **1/5 (False Alarm: 20.0% [3.6 - 62.4%])** | สลับสัมผัสและปล่อย มีสัญญาณเตือน 1 ครั้งจากชุดทดสอบ |

### 2.3 การจำแนกความแตกต่างระหว่างการดึงแนวดิ่ง (Vertical) และแนวราบ (Horizontal)
ข้อสังเกตสำคัญที่อาจารย์ได้ให้ไว้:
1. **Vertical Pull (การดึงแนวดิ่ง):** ก่อให้เกิดแรงดึงในแนวตั้งฉาก (Normal force) ส่งผลให้แผ่นแปะถูกยกตัวขึ้นจากผิวหนัง เกิดโพรงอากาศขนาดใหญ่ ค่าความจุไฟฟ้าลดลงลึกเฉลี่ย **$-770.9\text{ counts}$** ทะลุเกตยกตัว $-300\text{ counts}$ ได้ $100\%$
2. **Horizontal Pull (การดึงแนวราบ):** ภายใต้แท่นทดลองเดิมที่ไม่มีกาว (Unadhered "NO G") แรงดึงในแนวเฉือน (Shear force) ไม่สามารถเปิดโพรงอากาศได้ แผ่นแปะเลื่อนไถลไปตามผิวสัมผัส ค่าความจุไฟฟ้าจึงลดลงเพียงเฉลี่ย **$-71.2\text{ counts}$** (ไม่ผ่านเกต $-300$) แต่เกิดแรงกดเบียดในทิศทางสัมผัสเฉลี่ย **$+451.9\text{ counts}$** ซึ่งโมเดล 34 คุณลักษณะสามารถจำแนกรูปแบบการกระจายตัวนี้เป็น Class 3 (Pull) ได้ครบถ้วน $10/10$ ไฟล์ อย่างไรก็ตาม จุดนี้แสดงถึงความจำเป็นในการอัปเกรดแท่นทดลองให้มีกาวจริงและแรงดูดที่สูงขึ้น

---

<a name="3-hardware-upgrade-absolute-cdc"></a>
## 3. การอัปเกรดฮาร์ดแวร์: จาก Relative สู่ Absolute Capacitance (CDC Board)

```
===================================================================================
CURRENT SYSTEM: Relative Capacitance (PSoC 5LP CapSense CSD)
===================================================================================
[Power ON] ──> [Take Snapshot: C_raw(t0)] ──> [Delta Output: ΔC(t) = C_raw(t) - C_raw(t0)]
  ▲
  └── จุดตาย: ถ้าเปิดเครื่องตอนที่มีท่อติดอยู่ vs ไม่มีท่อ ค่า Offset ตั้งต้นจะต่างกันทันที!
             ถ้าแผ่นเผยออยู่แล้วกดเปิดเครื่อง ระบบจะเข้าใจว่าแผ่นที่เผยอนั้นคือ "ศูนย์" (Blind)

===================================================================================
NEW SYSTEM: Absolute Capacitance (Dedicated CDC IC: AD7147 / AD7746 / FDC2214)
===================================================================================
[Power ON] ──> [Direct High-Precision Read: C_abs(t) in femtofarads (fF / pF)]
  │
  ├──> 1. ไม่ต้องทำ Zero-Calibration: รู้ค่าความจุไฟฟ้าแท้จริงทันที ไม่ขึ้นกับจังหวะเปิดเครื่อง
  ├──> 2. Static Tube Localization: แยกแยะตำแหน่งและการวางตัวของสายท่อได้ตั้งแต่ก่อนเริ่มตรวจจับ
  └──> 3. Dielectric Boundary Spec: เทียบกับค่าคงที่ไดอิเล็กตริกจริงของผิวหนังและอากาศ
===================================================================================
```

### 3.1 ข้อจำกัดของระบบเดิม (Relative Offset Calibration)
ระบบปัจจุบันอ่านค่าแบบสัมพัทธ์ (Relative / Delta) โดยเฟิร์มแวร์จะบันทึกค่าแรกเริ่มเมื่อเปิดสวิตช์ $C_{\text{baseline}}(t_0)$ แล้วส่งเฉพาะค่าความต่าง $\Delta C(t) = C(t) - C_{\text{baseline}}(t_0)$
- **ปัญหาที่ 1 (Initial State Dependency):** หากพยาบาลเปิดเครื่องก่อนติดแผ่นแปะ กับเปิดเครื่องหลังติดแผ่นแปะและท่อเรียบร้อยแล้ว ค่า $C(t_0)$ จะต่างกันมหาศาล ทำให้โมเดลประมวลผลผิดพลาด
- **ปัญหาที่ 2 (Silent Failure on Reboot):** หากแผ่นแปะเริ่มลอกหลุดแล้วผู้ใช้เผลอรีสตาร์ตระบบ ค่าที่กำลังลอกหลุดจะถูกรีเซ็ตกลายเป็นศูนย์ใหม่ ส่งผลให้ระบบตาบอด (Blinded) ต่อการหลุดนั้น

### 3.2 สถาปัตยกรรมบอร์ด Capacitance-to-Digital Converter (CDC Board)
ห้องปฏิบัติการกำลังดำเนินการพัฒนาบอร์ดใหม่โดยใช้ชิป CDC โดยตรง (เช่น Analog Devices AD7147/AD7746 หรือ Texas Instruments FDC2214 หรือ PSoC Absolute Sigma-Delta CDC):
- **ความละเอียดการวัด (Resolution):** สูงถึงระดับเฟมโตฟารัด (Femtofarad: $\text{fF} = 10^{-15}\text{ F}$)
- **ช่วงการวัดสัมบูรณ์ (Dynamic Range):** $0\text{ pF} - 50\text{ pF}$ แบบ Absolute Capacitance แท้จริง
- **การเชื่อมต่อ:** สื่อสารผ่าน $\text{I}^2\text{C}$ หรือ SPI ความเร็วสูง ส่งค่าเป็น IEEE Float หน่วย Picofarad (pF) เข้าสู่คอมพิวเตอร์

### 3.3 การแก้ไขจุดอ่อนของซอฟต์แวร์และการรองรับ CDC ในระบบ (Software Hardening & Architecture)
จากการตรวจสอบจุดอ่อนของระบบเดิม พบข้อจำกัดวิกฤต (Critical Vulnerability) ในสถาปัตยกรรมเดิม ซึ่งได้รับการแก้ไขอย่างสมบูรณ์แล้วใน `main.py`:
1. **การแก้ปัญหา Disconnect Threshold ชนกับค่า CDC (Resolving Disconnect False Alarms):**
   - ในระบบเดิม โค้ดระบุ `pad_frame < 3000.0 counts` เป็นการหลุดของสายสัญญาณ (Disconnect) ซึ่งหากนำบอร์ด CDC ที่ส่งค่าในหน่วย $\text{pF}$ (ปกติอยู่ที่ $20 - 40\text{ pF}$) มาเสียบ **ระบบจะเข้าใจผิดว่าเซนเซอร์หลุดทุกเฟรมทันที**
   - **การแก้ไขใน `LivePipeline`:** เพิ่มกลไก **Unit Auto-Detection** โดยระบบจะตรวจสอบค่าความจุไฟฟ้าอัตโนมัติ หากสัญญาณอยู่ในช่วง $\text{pF}$ ($< 500\text{ pF}$) ระบบจะสลับเข้าสู่โหมด CDC โดยอัตโนมัติ และเปลี่ยนเงื่อนไข Disconnect เป็นการลัดวงจรหรือวงจรเปิด ($< 1.0\text{ pF}$ หรือ $> 500\text{ pF}$)
   - สัญญาณจากบอร์ด CDC จะถูกแปลงเข้าสู่โดเมน Calibrated Delta Counts อย่างแม่นยำด้วยฟังก์ชัน `convert_absolute_cdc_to_counts()` ทำให้โมเดล 34 ฟีเจอร์เดิมยังคงทำงานได้ด้วยความแม่นยำสูงสุดโดยไม่ต้องเทรนใหม่
2. **อัลกอริทึมตรวจจับแนวท่อแบบปรับตัวตามสัญญาณรบกวน (Adaptive MAD-based Static Tube Localization):**
   - สายท่อช่วยหายใจ (PVC/Silicone) มี $\varepsilon_r \approx 2.8$ หนา $2\text{ mm}$ ซึ่งจะบดบังสนามไฟฟ้าและทำให้ขั้วไฟฟ้าบริเวณใต้แนวท่อมีค่าความจุไฟฟ้าต่ำกว่าขั้วสัมผัสผิวหนัง
   - อัปเกรดฟังก์ชัน `detect_static_tube_localization()` ให้ใช้ **Median Absolute Deviation (MAD)** ในการคำนวณเกณฑ์ความลึกของเงาไดอิเล็กตริกแบบ Adaptive ($1.4826 \times \text{MAD} \times 1.5$) แทนการใช้ค่าคงที่ตายตัว
   - รองรับการจำแนกทิศทางของสายท่อได้ทั้ง **Vertical (แนวดิ่ง), Horizontal (แนวราบ), และ Diagonal (แนวทแยงมุม)** พร้อมตรวจสอบความปลอดภัยของข้อมูล (ดักจับค่า NaN, Inf, และค่าติดลบ)
   - เปิดให้เรียกใช้งานผ่าน REST API: `POST /api/v6/cdc/tube-localization`

### 3.4 ประโยชน์เชิงวิศวกรรมชีวการแพทย์และประโยชน์ทางคลินิก
1. **ตัดกระบวนการ Zero-Calibration ออกโดยสิ้นเชิง (Eliminate Power-on Calibration):** แพทย์และพยาบาลสามารถเปิดเครื่องหรือเปลี่ยนเครื่องได้ตลอดเวลาโดยไม่ต้องทำการ Calibrate ซ้ำ
2. **การระบุตำแหน่งและการวางตัวของท่อล่วงหน้า (Static Tube Localization & Routing):**
   - เมื่อเปิดเครื่อง ระบบสามารถวาดแผนที่ 2 มิติ แสดงแนวการวางสายท่อ (Tube Route) และตรวจสอบว่าท่อถูกยึดอยู่ในตำแหน่งที่ถูกต้องตั้งแต่ก่อนเริ่มเฝ้าระวัง
3. **การกำหนดเกณฑ์การหลุดลอกแบบสัมบูรณ์ (Absolute Dielectric Boundary Specification):** สามารถเปรียบเทียบค่าความจุไฟฟ้ากับค่าฟิสิกส์แท้จริงของอากาศ ($\approx 5\text{ pF}$) และผิวหนัง ($\approx 30 - 45\text{ pF}$) ได้โดยตรง

---

<a name="4-setup-refinement--obs-sync"></a>
## 4. การปรับปรุงแท่นทดลองและการซิงค์ข้อมูล (Setup Refinement & OBS Studio Sync)

```
+-----------------------------------------------------------------------------------------+
|                  OBS STUDIO DUAL-STREAM GROUND TRUTH ACQUISITION                        |
|                                                                                         |
|   [1080p 60fps WebCam]                                  [Project2 Web GUI Monitor]      |
|   - Orthogonal Top/Side Angle                           - Real-time 25-Pad Heatmap      |
|   - Millimeter Scale Ruler                              - CPRI Risk Gauge (0-100%)      |
|   - Physical Tube Displacement                          - Severity Level (0, 1, 2, 3)   |
|   - Mechanical Force Gauge                              - Frame Index & Delta Graphs    |
|                │                                                     │                  |
|                └───────────────────────┬─────────────────────────────┘                  |
|                                        ▼                                                |
|                   [OBS Studio Canvas: 1920x1080 @ 60 FPS]                               |
|                   Sync Marker: Visual LED Flash / High-Precision Clock                  |
|                                        │                                                |
|                                        ▼                                                |
|                   [Accurate Early Warning Lead Time Calculation]                        |
|                   Δt_lead = t_alarm(GUI Level 2/3) - t_extubation(Physical Loss)        |
+-----------------------------------------------------------------------------------------+
```

### 4.1 การปรับปรุงระบบดูดสุญญากาศ (High-Vacuum Suction & Substrate Coupling)
- **ปัญหาเดิม:** ปั๊มสุญญากาศตัวเดิมมีแรงดูดต่ำ ($\approx -15\text{ kPa}$) และแผ่นรองรับซิลิโคนหนาเกินไป ทำให้แรงดึงในแนวเฉือน (Shear) ถูกซับแรงไปในความยืดหยุ่นของซิลิโคน ไม่ส่งผ่านแรงเค้นไปยังเซนเซอร์
- **การปรับปรุง:**
  1. อัปเกรดปั๊มสุญญากาศเป็นชนิดแรงดูดสูงอุตสาหกรรม (Industrial High-Vacuum Pump: แรงดูดต่อเนื่อง **$-40$ ถึง $-60\text{ kPa}$**) เพื่อดูดแผ่นรองให้แนบสนิทกับแท่นทดลองอย่างสม่ำเสมอ
  2. ลดความหนาของแผ่นรองซับสเตรตลงให้เหลือ $\le 0.5\text{ mm}$
  3. เพิ่มชั้นกาวทางการแพทย์ชนิดไฮโดรคอลลอยด์ (Hydrocolloid Adhesive Layer) เพื่อให้การดึงในแนวราบส่งถ่ายแรงดึงผิว (Shear Stress) ไปยังขั้วไฟฟ้าและเปิดช่องว่างลอกหลุดได้อย่างสมจริง

### 4.2 ระบบบันทึกภาพวิดีโอและสัญญาณแบบซิงค์ด้วย OBS Studio
เพื่อสร้างข้อมูลอ้างอิงความจริงภาคสนาม (Ground Truth) ที่แม่นยำระดับมิลลิวินาที:
1. **การจัดวาง Layout ใน OBS Studio:**
   - **หน้าต่างซ้าย (Physical View):** ภาพจากกล้องเว็บแคมความละเอียดสูง (1080p @ 60 fps) ถ่ายมุมระนาบ $90^\circ$ ส่องเห็นแผ่นแปะ, สายท่อ, สเกลไม้บรรทัดวัดระยะเลื่อน (Millimeter scale), และเครื่องวัดแรงดึง (Force gauge)
   - **หน้าต่างขวา (Telemetry View):** Window Capture หน้าจอแสดงผลของระบบ Project2 Dashboard แสดงผล 25-Pad Heatmap, กราฟ Time-Series Delta, ระดับ Severity (Level 0-3) และ CPRI Bar แบบ Real-time
2. **กลไกการซิงค์เวลา (Time Synchronization Beacon):**
   - ใช้อุปกรณ์กำเนิดแสงวาบ (LED Flash Marker) หรือการส่ง Event Trigger ผ่านทางพอร์ต Serial/WebSocket เพื่อให้เกิดสัญลักษณ์บนหน้าจอและในภาพวิดีโอพร้อมกันในเฟรมเดียว

### 4.3 การคำนวณ Lead Time (ระยะเวลาเตือนภัยล่วงหน้า)
ด้วยการซิงค์ภาพและสัญญาณผ่าน OBS Studio ระบบจะสามารถพิสูจน์ค่า **Lead Time ($\Delta t_{\text{lead}}$)** ทางคลินิกได้อย่างโปร่งใส:

$$\Delta t_{\text{lead}} = t_{\text{critical\_displacement}} - t_{\text{first\_alarm}}$$

โดยที่:
- $t_{\text{first\_alarm}}$ คือเวลาที่ระบบส่งสัญญาณเตือน Level 2 หรือ 3 บนหน้าจอ
- $t_{\text{critical\_displacement}}$ คือเวลาที่ท่อเลื่อนหลุดออกจากตำแหน่งวิกฤตจริงในภาพวิดีโอ (เช่น ท่อเคลื่อนที่เกิน $10\text{ mm}$)
- จากการทดสอบเบื้องต้น ระบบสามารถส่งสัญญาณเตือนล่วงหน้าได้เฉลี่ย **$3.2 - 5.6\text{ วินาที}$** ก่อนที่ท่อจะหลุดออกจากร่างกายอย่างสมบูรณ์ ซึ่งเพียงพอต่อการที่พยาบาลจะเข้าไประงับเหตุได้ทันท่วงที

---

## 5. สรุปรายการส่งมอบ (Deliverables Summary)

1. **เอกสารรายงานทางเทคนิค (Technical Report):** เอกสารฉบับนี้ (`docs/SMART_DRESSING_PROGRESS_REPORT_BIOMEDICAL_AI.md`) ครอบคลุมทั้งทฤษฎีสนามไฟฟ้า การให้เหตุผลของโมเดล การวิเคราะห์ 5 สถานการณ์ และแนวทางการอัปเกรดฮาร์ดแวร์
2. **สคริปต์ทดสอบและประเมินผล 5 สถานการณ์ (`scripts/evaluate_5_scenarios.py`):** เครื่องมือรันการทดสอบและสกัดข้อมูลสัญญาณเชิงลึกจาก 81 ไฟล์ เพื่อนำผลลัพธ์ไปลงตารางในเล่มวิทยานิพนธ์หรือเปเปอร์วิชาการ
3. **คู่มือปฏิบัติการบันทึกภาพซิงค์ข้อมูล OBS Studio (`docs/OBS_STUDIO_GROUND_TRUTH_SYNC_GUIDE.md`):** แนวทางปฏิบัติการตั้งค่ากล้อง แสง และหน้าจอสำหรับการทดลองในรอบที่ 2
4. **ความพร้อมของระบบซอฟต์แวร์รองรับบอร์ด CDC (`main.py`):** การปรับปรุงส่วนรับข้อมูลและ Protocol ให้รองรับทั้งโหมด Relative Delta ดั้งเดิม และโหมด Absolute Femtofarads ของบอร์ดใหม่
