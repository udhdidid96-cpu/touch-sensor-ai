# วิศวกรรมการชดเชยพื้นผิวโค้งมนและพื้นที่ต่างระดับ (Non-Planar Contours & Step-Height Compensation)
## ระบบ Smart Extubation Early Warning Smart Dressing (25-Channel Capacitive Sensing)

---

## 1. บทนำและปัญหาทางคลินิก (Clinical & Physical Problem)

ในการทดลองเบื้องต้นบนแท่นทดสอบ (Bench Testing) ชุดข้อมูลทั้ง 81 ไฟล์ถูกบันทึกบน **"แท่นทดสอบแผ่นเรียบ" (Flat Planar Acrylic Surface)** ซึ่งมีลักษณะทางเรขาคณิตที่สมบูรณ์แบบ แผ่นแปะเซนเซอร์ทั้ง 25 ช่องสัมผัสแนบสนิทกับผิวระนาบเดียวกัน ส่งผลให้ค่าความจุไฟฟ้าฐาน (Baseline Capacitance: $C_0$) ของทุกช่องมีค่าใกล้เคียงกัน ($\sim 28,000\text{ counts}$ หรือ $\sim 25-35\text{ pF}$)

อย่างไรก็ตาม ในการใช้งานจริงบนร่างกายผู้ป่วยวิกฤต (ICU Patients):
1. **กายวิภาคใบหน้ามีความโค้งมน 3 มิติ (3D Anatomical Curvature):**
   - โหนกแก้ม (Zygomatic arch), แนวกราม (Mandible), ร่องข้างแก้ม (Nasolabial fold), และมุมปาก (Vermilion border) มีรัศมีความโค้ง $R \approx 15 - 50\text{ mm}$
2. **การมีท่อช่วยหายใจและเทปยึดทำให้เกิด "สันต่างระดับ" (Step-Height Discontinuity):**
   - ท่อช่วยหายใจสำหรับผู้ใหญ่ (Endotracheal Tube - ETT) มีเส้นผ่านศูนย์กลางภายนอก (Outer Diameter: OD) ประมาณ **$9.0 - 11.5\text{ mm}$** (ขนาด Fr 28 - 34)
   - แถบพลาสเตอร์ยึดท่อ (เช่น Durapore, Sleek, หรือ AnchorFast) มีความหนาเพิ่มอีก $1 - 3\text{ mm}$
   - เมื่อนำแผ่นแปะเซนเซอร์มาปิดทับหรือทอดข้ามบริเวณท่อ แผ่นแปะจะต้องพาดข้ามสันความสูงต่างระดับที่สูงถึง **$3 - 10\text{ mm}$**

```
===================================================================================
กายวิภาคและการต่างระดับเมื่อใช้งานจริง (Non-Planar & Step-Height Discontinuity)
===================================================================================

                [แผ่นแปะทอดตัวโค้งตามสัน]
               ╭───────────────────────╮
               │ Pad-11  Pad-12  Pad-13│
    ┌──────────┴───────────────────────┴──────────┐  <-- Smart Dressing (FPC)
    │                                             │
    │                   ╭───────╮                 │
    │                   │  ETT  │ (OD 9-11.5 mm)  │
    │                   │ Tube  │                 │
    │                   ╰───────╯                 │
────┴───────╮                               ╭─────┴─────────────────────── ผิวหนัง
 ผิวระนาบ     │<--- โพรงอากาศ (Air Gap) --->│   ผิวระนาบ
 แนบสนิท     │      (Tenting Effect)       │   แนบสนิท
 C0 = 35 pF │      C0 = 12-18 pF          │   C0 = 35 pF
```

---

## 2. ผลกระทบทางฟิสิกส์ไฟฟ้าความจุ (Capacitive Electrodynamics of Steps)

เมื่อแผ่นแปะต้องรับมือกับพื้นที่ต่างระดับ จะเกิดปรากฏการณ์ทางฟิสิกส์ 3 ประการที่ส่งผลกระทบต่อข้อมูล (Data):

### 2.1 ปรากฏการณ์ขึงตึงเกิดโพรงอากาศ (Tenting Effect & Micro Air Gaps)
แผ่นวงจรพิมพ์แบบยืดหยุ่น (FPC) และแผ่นฟิล์มโพลียูรีเทนมีความแข็งแกร็งต่อการดัดงอ (Flexural Rigidity: $D = \frac{E t^3}{12(1-\nu^2)}$)
- เมื่อแผ่นแปะพาดข้ามสันของท่อ ETT แผ่นแปะจะไม่สามารถหักมุม $90^\circ$ แนบลงไปถึงโคนท่อได้ทันที
- เกิด **โพรงอากาศสามเหลี่ยม (Air Gap Wedge)** บริเวณซอกข้างท่อ
- ค่าสภาพยอมสัมพัทธ์ (Relative Permittivity):
  $$\varepsilon_{\text{air}} \approx 1.0 \quad \ll \quad \varepsilon_{\text{skin}} \approx 50 - 80$$
- ส่งผลให้ Pad ที่คร่อมอยู่เหนือโพรงอากาศมีค่า Baseline เริ่มต้น $C_{0, i}$ **ลดต่ำลงอย่างมาก** (เหลือเพียง $12 - 18\text{ pF}$ เทียบกับ Pad ที่แนบผิวซึ่งอยู่ที่ $30 - 38\text{ pF}$)

### 2.2 ปัญหาความไม่เป็นเชิงเส้นของความไวในการตรวจจับ ($\frac{\partial C}{\partial z}$ Non-linearity)
จากสมการความจุไฟฟ้าระหว่างแผ่นขั้วกับผิวหนัง:
$$C(z) = \frac{\varepsilon_0 \cdot A}{\frac{d_{\text{substrate}}}{\varepsilon_{\text{substrate}}} + \frac{z}{\varepsilon_{\text{medium}}}} + C_{\text{fringe}}$$

อัตราการเปลี่ยนแปลงของความจุไฟฟ้าต่อระยะการยกตัว ($z$):
$$\frac{\partial C}{\partial z} = -\frac{\varepsilon_0 A \cdot \varepsilon_{\text{medium}}}{\left(\frac{d_{\text{sub}}\varepsilon_{\text{med}}}{\varepsilon_{\text{sub}}} + z\right)^2}$$

- **Pad ที่แนบสนิท ($z \approx 0$):** มีความไวสูงมาก ($\left|\frac{\partial C}{\partial z}\right|$ สูง) เมื่อแผ่นเริ่มเผยอเพียง $0.5\text{ mm}$ ค่าความจุจะดรอปทันที **$-800$ ถึง $-1,500\text{ counts}$**
- **Pad ที่อยู่บนโพรงอากาศต่างระดับ ($z = 1.0 - 2.0\text{ mm}$ อยู่แล้ว):** ค่าอนุพันธ์ $\left|\frac{\partial C}{\partial z}\right|$ อยู่ในโซนอิ่มตัว (Flat asymptote) เมื่อแผ่นหลุดออกอีก $1.0\text{ mm}$ ค่าความจุจะลดลงเพียง **$-100$ ถึง $-200\text{ counts}$**
- **ผลเสียต่อระบบ:** หากใช้อัลกอริทึมที่มีเกณฑ์ Lift Gate แบบตายตัว (เช่น $\le -300\text{ counts}$) ช่องที่อยู่บนรอยต่างระดับจะ **ตรวจไม่ผ่านเกณฑ์ (False Negative)** ทำให้ระบบมองไม่เห็นการหลุดลอกในบริเวณนั้น!

### 2.3 การรวมตัวของความเค้นที่ขอบสัน (Stress Concentration at Step Edges)
- บนพื้นผิวเรียบ แรงดึงท่อจะกระจายตัวอย่างสม่ำเสมอ
- บนพื้นผิวต่างระดับ ขอบสันของท่อทำหน้าที่เป็นจุดคานงัด (Fulcrum) ก่อให้เกิด **Peel Stress Concentration**
- การหลุดลอกจะเริ่มต้นที่ขอบรอยต่อต่างระดับเสมอ (Peel Initiation) ก่อนจะลามไปยังพื้นที่ราบ

---

## 3. สถาปัตยกรรมทางวิศวกรรมเพื่อแก้ปัญหาพื้นที่ต่างระดับ (4-Tier Solution)

เพื่อแก้ปัญหาพื้นที่ต่างระดับอย่างสมบูรณ์แบบ ระบบได้วางแนวทางแก้ไขครอบคลุม 4 ระดับ:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. DATA & ALGORITHM LAYER (ซอฟต์แวร์และการประมวลผลข้อมูล)                   │
│    - Normalized Fractional Deltas: δ_i = ΔC_i / C_{0, i}                     │
│    - Per-Pad Adaptive Lift Gates: Gate_i = min(-150, -α * C_{0, i})         │
│    - Static Topography & Tenting Profiling (ตรวจหาโพรงอากาศก่อนมอนิเตอร์)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ 2. HARDWARE & SENSOR STRUCTURE (การออกแบบเซนเซอร์ทางกล)                    │
│    - Viscoelastic Hydrocolloid Base (กาวปรับระนาบ ไหลเติมเต็มโพรงอากาศ)      │
│    - Ultra-thin Serpentine FPC (แผ่นวงจรพิมพ์ยืดหยุ่นสูงพิเศษ <= 25 µm)      │
│    - Strain-Relief Keyhole Slits (รอยบากผ่อนแรงแยกปีกยึดท่อออกจากแผ่นเซนเซอร์)│
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ 3. ABSOLUTE CDC SENSING LAYER (การวัดความจุไฟฟ้าสัมบูรณ์)                   │
│    - วัดค่า fF/pF แท้จริง ไม่ขึ้นกับ Offset การเปิดเครื่อง                  │
│    - รายงาน Contact Quality Index ต่อพยาบาลผู้ติดแผ่นแปะ                    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ 4. BENCH EXPERIMENTAL SETUP (การปรับปรุงแท่นทดสอบให้ต่างระดับ)              │
│    - 3D Anatomical Facial Phantom (แท่นใบหน้า 3 มิติที่มีส่วนโค้งมน)        │
│    - Step-Height Ridge Blocks (สันจำลองขนาด 3 mm, 5 mm, 8 mm)                │
│    - Silicone Artificial Skin with Negative Pressure Suction               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. รายละเอียดการประมวลผลข้อมูลและอัลกอริทึม (Data & Algorithm Normalization)

### 4.1 การแปลงค่าเป็น Relative Fractional Delta ($\delta_i$)
แทนที่จะใช้ผลต่างดิบเป็น Absolute Counts ($\Delta C_i = C_i(t) - C_{0, i}$) ซึ่งสเกลของสัญญาณขึ้นอยู่กับความหนาแน่นของการสัมผัส ให้คำนวณ **Relative Fractional Delta**:

$$\delta_i(t) = \frac{C_i(t) - C_{0, i}}{C_{0, i}} = \frac{\Delta C_i(t)}{C_{0, i}}$$

- **ข้อดี:** ทำให้เกณฑ์การตรวจจับเป็นเปอร์เซ็นต์ของการหลุดลอก (Percentage of Coupling Loss)
- **ตัวอย่าง:**
  - Pad แนบสนิท ($C_0 = 35\text{ pF}$): ดรอปลง $7\text{ pF} \implies \delta = \frac{-7}{35} = -0.20$ (หลุด $20\%$)
  - Pad คร่อมสัน ($C_0 = 15\text{ pF}$): ดรอปลง $3\text{ pF} \implies \delta = \frac{-3}{15} = -0.20$ (หลุด $20\%$ เท่ากัน)
- ทั้งสองจุดจะให้ค่าสเกลาร์ที่เท่ากัน ทำให้โมเดล AI และ Annunciator ตรวจจับการหลุดลอกได้อย่างแม่นยำแม้ความสูงเริ่มต้นจะไม่เท่ากัน

### 4.2 เกณฑ์ยกตัวแบบปรับตัวตามช่อง (Per-Pad Adaptive Lift Gate)
สำหรับระบบที่ยังใช้หน่วย Counts จากบอร์ดปัจจุบัน ให้กำหนดเกณฑ์ Lift Gate ของแต่ละช่องให้แปรผันตาม Baseline ประจำช่องนั้น:

$$\text{Gate}_i = \min\left(-150, \; -\alpha \cdot C_{0, i}\right)$$

โดยเลือกค่า $\alpha \approx 0.010 - 0.012$ ($1.0\% - 1.2\%$ ของ Baseline):
- ถ้า $C_{0, i} = 28,000\text{ counts} \implies \text{Gate}_i = -308\text{ counts}$ (สอดคล้องกับค่า $-300\text{ counts}$ เดิม)
- ถ้า $C_{0, i} = 16,000\text{ counts}$ (ช่องที่คร่อมสันต่างระดับ) $\implies \text{Gate}_i = -176\text{ counts}$
- ป้องกันการเกิด Dead Zone บนช่องที่อยู่บริเวณรอยต่างระดับ

### 4.3 อัลกอริทึมวิเคราะห์ภูมิประเทศและโพรงอากาศ (Static Topography & Tenting Profiling)
ฟังก์ชัน `analyze_surface_topography(baseline_capacitance)` ใน [`main.py`](file:///d:/Projects/Project2/main.py):
1. คำนวณ Median และ Interquartile Range (IQR) ของค่า Baseline ทั้ง 25 ช่อง
2. คำนวณ Spatial Gradient ของพื้นผิว $\mathbf{G} = \nabla C_0$
3. จำแนกประเภทของแต่ละ Pad:
   - **`flush_contact`**: สัมผัสแนบสนิท ($C_0 \ge \text{Median} - 0.5 \times \text{IQR}$)
   - **`contoured`**: อยู่บนพื้นที่โค้งมน ($C_0$ ลดหลั่นตามแนวระนาบ)
   - **`tenting_step_bridge`**: เกิดโพรงอากาศข้ามสัน ($C_0 \le \text{Median} - 1.5 \times \text{IQR}$)
4. ส่งผลการวินิจฉัยกลับไปยัง UI ให้พยาบาลทราบก่อนเริ่มมอนิเตอร์:
   - *"Topography: Stepped Contour detected. Tenting on Pads [12, 13]. Adaptive gates engaged."*

---

## 5. การออกแบบโครงสร้างทางกลและวัสดุ (Mechanical & Material Solutions)

### 5.1 สารตัวกลางไฮโดรคอลลอยด์ปรับระนาบ (Viscoelastic Hydrocolloid Cushion)
- แผ่นฟิล์มใสทั่วไปไม่สามารถไหลเข้ารูปได้
- การใช้ฐานกาวไฮโดรคอลลอยด์ (Hydrocolloid Adhesive Base) หนา **$0.8 - 1.2\text{ mm}$**
- คุณสมบัติหยุ่นหนืด (Viscoelastic flow) จะทำให้เนื้อกาวค่อยๆ ไหลยุบตัวเติมเต็มช่องว่างรอบท่อ ETT และรอยต่อต่างระดับภายใน 1-2 นาทีหลังปิดแผ่นแปะ
- ขจัดโพรงอากาศ ($d_{\text{air}} \to 0$) ทำให้ค่า $\varepsilon_{\text{effective}}$ บริเวณรอยต่อมีค่าสูงและต่อเนื่อง สัญญาณไฟฟ้าความจุจึงถ่ายทอดได้สม่ำเสมอ

### 5.2 แผ่นวงจรพิมพ์ยืดหยุ่นสูง (Ultra-Thin Serpentine FPC)
- ใช้ Substrate ชนิด Polyimide ความหนาเพียง **$\le 25\,\mu\text{m}$** (เทียบกับ FPC ทั่วไปที่หนา $100\,\mu\text{m}$)
- ลายเส้นทองแดงระหว่างขั้วอิเล็กโทรด 25 จุดออกแบบเป็นลาย **Serpentine (ลอนคลื่นเกือกม้า)**
- ช่วยให้แผ่นแปะสามารถบิดโค้งใน 3 มิติ (Double curvature conformability) แนบไปกับสันกรามและท่อได้โดยไม่เกิดแรงสปริงงัดตัวเองขึ้นมา

### 5.3 รอยบากผ่อนแรง (Strain-Relief Keyhole Slits)
- ทำรอยตัดเลเซอร์ (Laser cutout) เป็นรูปทรงรูกุญแจ (Keyhole slot) หรือรอยบากรัศมี (Radial slits) รอบช่องทางออกของท่อ ETT
- ช่วยแยกแรงดึง (Mechanical decoupling) ระหว่าง:
  1. ส่วนปีกยึดท่อ (Anchor wings) ที่ต้องรับแรงกระชากของท่อโดยตรง
  2. แผ่นเซนเซอร์ตรวจจับ (Sensor sensing array)
- ป้องกันไม่ให้แรงงัดของสันต่างระดับทำให้แผ่นเซนเซอร์หลุดลอกก่อนเวลาอันควร

---

## 6. การปรับปรุงแท่นทดสอบสำหรับพื้นที่ต่างระดับ (3D Stepped Bench Setup)

ในการพัฒนาเฟสถัดไป (Session S1 & S2) แท่นทดสอบในห้องปฏิบัติการจะได้รับการอัปเกรดดังนี้:

```
[3D-Printed Mandible/Cheek Phantom]
   ├── วัสดุ: SLA Resin หรือ PETG ความละเอียดสูง
   ├── รัศมีความโค้งมน: R = 30 mm (จำลองความโค้งโหนกแก้มและแนวกราม)
   ├── สันจำลองต่างระดับ (Step Blocks):
   │     ├── สันความสูง 3 mm  (จำลองขอบพลาสเตอร์ยึดท่อหนา)
   │     ├── สันความสูง 5 mm  (จำลองท่อ ETT ขนาดเล็ก / กึ่งฝัง)
   │     └── สันความสูง 8 mm  (จำลองท่อ ETT ขนาดมาตรฐานผู้ใหญ่)
   └── ผิวหนังเทียมซิลิโคน (Silicone Artificial Skin):
         ├── ซิลิโคน Ecoflex 00-30 ผสม Carbon Conductive Particle (ε_r ≈ 50)
         └── ช่องดูดสุญญากาศแรงดูดสูง (-40 ถึง -60 kPa)
```

### การจัดเก็บ Dataset เฟสใหม่ (Curved & Stepped Dataset)
1. **Curved Surface Baseline (อยู่นิ่งบนผิวโค้ง):** บันทึก 10 ไฟล์ ยืนยันความนิ่งของสัญญาณ
2. **Curved Surface Touching & Press:** บันทึก 20 ไฟล์ ตรวจสอบการกรอง False Alarm
3. **Step-Height Pulling (การดึงท่อบนสันต่างระดับ):**
   - ดึงแนวดิ่ง (Vertical Pull over 5 mm Step)
   - ดึงแนวราบ (Horizontal Pull over 5 mm Step)
   - ดึงกระชาก (Power Pull over 8 mm Step)
4. ประเมินโมเดลแบบ **Cross-Session Validation (Train on S0-Flat, Test on S1-Curved and S2-Stepped)** เพื่อพิสูจน์ Generalization ข้ามพื้นผิวที่ต่างระดับอย่างแท้จริง

---

## 7. สรุปคำตอบสำหรับนำเสนออาจารย์ (Key Takeaway for Advisor)

| คำถาม | คำตอบเชิงวิศวกรรมที่ชัดเจนและพิสูจน์ได้ |
|---|---|
| **ปัญหาคืออะไรถ้าพื้นผิวต่างระดับ?** | เกิด **Tenting (โพรงอากาศ)** ใต้แผ่นแปะ ทำให้ Baseline ดรอปเฉพาะจุด, สภาพความไว ($\frac{\partial C}{\partial z}$) ลดลงจน Lift Gate ตายตัวอาจมองไม่เห็น, และเกิด **Stress Concentration** ที่ขอบสัน |
| **ซอฟต์แวร์แก้ปัญหาอย่างไร?** | 1. ใช้ **Relative Fractional Delta ($\delta = \Delta C / C_0$)** เพื่อให้สเกลสัญญาณเป็น Scale-invariant<br>2. ใช้ **Per-Pad Adaptive Lift Gate** ปรับเกณฑ์ตาม Baseline ของแต่ละช่อง<br>3. ตรวจหาโพรงอากาศล่วงหน้าด้วยฟังก์ชัน **Topography & Tenting Profiling** |
| **ฮาร์ดแวร์แก้ปัญหาอย่างไร?** | 1. เสริมชั้นกาว **Viscoelastic Hydrocolloid** ไหลเติมเต็มโพรงอากาศขจัด $d_{\text{air}} \to 0$<br>2. ใช้แผ่น FPC แบบ **Ultra-Thin ($\le 25\,\mu\text{m}$) ลาย Serpentine** แนบโค้ง 3 มิติได้โดยไม่งัด<br>3. ทำ **Strain-Relief Keyhole Slits** แยกแรงดึงท่อออกจากแผ่นเซนเซอร์ |
| **แท่นทดลองจะทำอย่างไร?** | เปลี่ยนจากแผ่นอะคริลิกเรียบ สู่ **3D Anatomical Facial Phantom** ที่มีรัศมีความโค้ง $R=30\text{ mm}$ และสันความสูงต่างระดับ $3-8\text{ mm}$ พร้อมท่อ ETT จริง |
