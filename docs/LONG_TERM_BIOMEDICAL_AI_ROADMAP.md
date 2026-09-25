# Long-Term Biomedical AI Strategic Roadmap (24-Month Translation Plan)
## Smart Extubation Early Warning Smart Dressing (25-Channel Capacitive Sensing)
**Document Status:** Master Strategic Engineering Plan  
**Target Horizon:** 24 Months (Bench $\rightarrow$ Pre-Clinical $\rightarrow$ Multi-Center ICU Clinical Validation)  
**Regulatory Target:** IEC 62304 (Class B/C), ISO 14971, ISO 13485, CE-MDR / FDA SaMD / De Novo

---

## Executive Summary & Strategic Rationale
This roadmap defines the multi-year engineering, regulatory, and clinical translation trajectory of the Smart Dressing Self-Extubation Early Warning System. Moving beyond single-session bench prototypes ($S_0$, 81 recordings), this strategy resolves fundamental sensor physics, migrates the hardware architecture to absolute femtofarad CDC sensing, compensates for complex 3D facial step-height topologies, and establishes the clinical evidence pipeline required for ICU deployment.

```
========================================================================================================================
                                      24-MONTH CLINICAL TRANSLATION ROADMAP
========================================================================================================================
[Months 1-3: Bench & Physics]  ──► [Months 3-6: Absolute CDC HW] ──► [Months 6-9: 3D Phantom & Step]
 • Multi-session (S1-S3) LOFO        • Custom 25-ch CDC ASIC/AFE       • 3D Facial Phantom (R=15-50mm)
 • Ground-plane shear fix            • Femtofarad absolute readout     • Step blocks (3mm, 5mm, 8mm)
 • LCR true C0 measurement           • Zero-cal elimination            • Adaptive gate validation
 • High-vacuum (-40 to -60 kPa)      • Static tube localization        • Hydrocolloid air-gap mitigation
                                               │
                                               ▼
[Months 18-24: Prospective ICU] ◄── [Months 12-18: IEC 62304 / ISO] ◄── [Months 9-12: Pre-Clinical & IRB]
 • Multi-center ICU pilot (N=100)    • Class B/C Software lifecycle    • Healthy human volunteer cohort
 • Lead time validation (Δt > 3s)    • ISO 14971 Risk Management       • Facial motion & sweat/saliva
 • Alarm fatigue < 5 alarms/day      • Hazard analysis & mitigation    • Dual-stream OBS ground truth
 • FHIR / HL7 ICU integration        • Verification & Traceability     • Multi-frequency bio-impedance
========================================================================================================================
```

---

## 1. Phase 1: Bench Optimization & Sensor Physics Hardening (Months 1–3)
**Primary Goal:** Eliminate laboratory artifacts, resolve the detachment spec contradiction, and obtain multi-session data before hardware tape-out.

### 1.1 Multi-Session Data Collection (S1–S3 Protocol)
* **The Problem:** The current 81 recordings represent a single continuous mounting session ($S_0$). Cross-validation (LOFO) holds out files, not physical attachments, leaving open the risk that the model fits the static baseline of that specific placement.
* **Execution:**
  - Execute the Round 2 Data Collection Protocol (`docs/DATA_COLLECTION_SOP_v2.md`).
  - Capture 3 independent mounting sessions ($S_1, S_2, S_3$) across different days, ambient temperatures ($22^\circ\text{C} - 28^\circ\text{C}$), relative humidity levels ($40\% - 75\%$), and distinct sensor patch samples.
  - Implement and evaluate `--cv session` cross-validation in `main.py` to establish true cross-mounting generalizability.

### 1.2 Ground-Plane Integration for Shear/Horizontal Pull
* **The Problem:** Horizontal pull produces no negative lift delta on flat acrylic (median deepest $\Delta = -71.2\text{ counts}$, 0/10 cross $-300\text{ count}$ gate), acting as a contact artifact (+451.9 counts max).
* **Execution:**
  - Embed a continuous copper ground plane beneath the simulated artificial skin substrate.
  - Converts fringing-field capacitance into a well-defined parallel-plate geometry.
  - When lateral shear displaces or puckers the patch boundary, coupling to the ground plane drops abruptly, generating genuine negative lift deltas ($\Delta C \ll 0$) for pure shear motions.
  - **Acceptance Criterion:** $\ge 5$ of 7 Horizontal Pull recordings must cross the $-300\text{ count}$ lift gate.

### 1.3 High-Vacuum Fixture & Substrate Thinning
* **The Problem:** The round-1 bench vacuum ($-15\text{ kPa}$) and thick silicone backing absorbed mechanical shear forces, preventing physical tube dislodgement forces from propagating to the sensing electrodes.
* **Execution:**
  - Upgrade to an industrial vacuum pump sustaining **$-40$ to $-60\text{ kPa}$**.
  - Thin the artificial skin backing membrane to $\le 0.5\text{ mm}$.
  - Apply medical-grade hydrocolloid adhesive layer between sensor and substrate to replicate physiological skin adhesion.

### 1.4 Baseline Capacitance $C_0$ Empirical Grounding via LCR Meter
* **The Problem:** The $\le 25,000\text{ count}$ detachment specification (KES 2025 §2.1) is mathematically unreachable from a 28,000 baseline at 59.85 counts/pF (requires 50.1 pF drop from a patch holding only ~30 pF; floor is 26,205 counts).
* **Execution:**
  - Perform bench measurement per `docs/DATA_COLLECTION_SOP_v2.md` §0.2 using a calibrated LCR meter (Keysight/Hioki).
  - Measurement parameters: $f = 100\text{ kHz}$, $V = 1.0\text{ V}$, Cp–D mode, open-lead fixture compensation.
  - Measure 3 repeat cycles of attached quiescent state vs. fully detached air state.
  - Update `docs/Hardware_Deck_Spec.md` with true physical baseline picofarad values to freeze input dynamic range for Phase 2.

---

## 2. Phase 2: Hardware Architecture Overhaul — From Relative to Absolute CDC (Months 3–6)
**Primary Goal:** Transition from legacy power-on relative offset subtraction to an absolute Capacitance-to-Digital Converter (CDC) front-end.

```
+──────────────────────────────────────────────────────────────────────────────────────────+
|                        PHASE 2: CDC HARDWARE BLOCK DIAGRAM                               |
|                                                                                          |
|   [25-Channel Flexible Sensing Patch]                                                    |
|   * 25 Serpentine Cu Electrodes (38.5 mm² each)                                          |
|   * Active Shield Layer (Prevents parasitic trace coupling)                              |
|                          │                                                               |
|                          ▼                                                               |
|   [Analog Front-End / CDC Array]                                                         |
|   * Multi-Channel CDC (e.g., AD7147 / AD7746 / FDC2214 or PSoC Σ-Δ Absolute)             |
|   * Dynamic Range: 0 - 50 pF, Resolution: < 1.0 fF, Sampling: 20-50 Hz per channel       |
|   * Built-in parasitic offset DACs (eliminates trace capacitance)                        |
|                          │                                                               |
|                          ▼ (I2C / SPI @ 400 kHz)                                         |
|   [Low-Power Medical MCU (STM32U5 / Nordic nRF5340)]                                     |
|   * Primary CRC-16 Frame Encoding                                                        |
|   * BLE 5.3 Long-Range / Isolated Medical USB Interface                                  |
|   * Power: Medical-grade isolated supply / LiPo battery with power-loss protection        |
+──────────────────────────────────────────────────────────────────────────────────────────+
```

### 2.1 Elimination of Power-On Zeroing Flaw
* Legacy systems measure $\Delta C = C(t) - C(t_0)$. If booted while the tube is pre-taped or an operator's hand rests on the dressing, $C(t_0)$ is corrupted, rendering subsequent alarms blind or hyper-sensitive.
* The absolute CDC reads true capacitance ($C_{\text{true}} \in [0, 50]\text{ pF}$) directly, eliminating boot-up zero-calibration.

### 2.2 Static Dielectric Shadow Tube Localization
* Adult ETT ($\varepsilon_{\text{ETT}} \approx 2.8$) displaces human skin contact ($\varepsilon_{\text{skin}} \approx 50-80$) over a distinct linear geometry.
* Upon power-on, the `/api/v6/cdc/tube-localization` algorithm evaluates the static capacitance topography:
  - Automatically identifies the ETT tube axis (vertical, horizontal, diagonal) with zero operator intervention.
  - Confirms adequate dressing seating before activation.
  - Yields a live Contact Quality Index (CQI) to guide clinical application.

### 2.3 Advanced FPC Mechanical Redesign
* **Serpentine Copper Traces:** Copper traces laid out in meander/serpentine geometry on a $\le 25\ \mu\text{m}$ polyimide base, enabling high multidirectional stretchability (> 15% strain) without trace fracture.
* **Strain-Relief Keyhole Slits:** Laser-cut mechanical cutouts separating the ETT fixation wings from the 25-channel sensing pad matrix. Mechanical torque applied to the external tube is decoupled from the peripheral dressing adhesive.

---

## 3. Phase 3: 3D Anatomical & Non-Planar Step-Height Validation (Months 6–9)
**Primary Goal:** Validate algorithm resilience against facial curvature and endotracheal tube step-height discontinuities.

```
================================================================================================
          NON-PLANAR TENTING & STEP-HEIGHT COMPENSATION ARCHITECTURE
================================================================================================
                               [ETT Tube OD 9-11.5mm]
                                       ╭───────╮
                                       │  ETT  │
             ╭─────────────────────────┴───────┴─────────────────────────╮  <-- FPC Dressing
             │               Pad 11         Pad 12        Pad 13         │
   ──────────┴───────────────╮                               ╭───────────┴──────────────── ผิวหนัง
    Flush Contact Area       │<--- Micro Air-Gap Wedge --->│        Flush Contact Area
    C0 ≈ 35 pF               │      (Tenting Effect)       │        C0 ≈ 35 pF
    Gate = -385 counts       │      C0 ≈ 12-18 pF          │        Gate = -385 counts
                             │      Gate = -150 to -198 ct │
                             ╰─────────────────────────────╯
================================================================================================
```

### 3.1 3D Facial Phantom & Calibrated Step Blocks
* Fabricate an anatomical adult facial phantom based on CT/MRI anthropometric scans replicating key landmark curvatures:
  - Zygomatic arch ($R \approx 20 - 35\text{ mm}$)
  - Mandibular margin ($R \approx 15 - 30\text{ mm}$)
  - Nasolabial fold ($R \approx 10 - 20\text{ mm}$)
* Precision modular acrylic/aluminum step blocks ($3\text{ mm}, 5\text{ mm}, 8\text{ mm}$) matching standard adult ETT outer diameters (Fr 28–34).

### 3.2 Mitigation of Tenting Air-Gap & Sensitivity Saturation
* **Theoretical Problem:** Flexural rigidity ($D = \frac{E t^3}{12(1-\nu^2)}$) creates an air tent ($\varepsilon_{\text{air}} = 1.0$) around the tube base, dropping baseline $C_0$ to $12-18\text{ pF}$ and flattening sensitivity $\frac{\partial C}{\partial z}$:
  $$\frac{\partial C}{\partial z} = -\frac{\varepsilon_0 A \cdot \varepsilon_{\text{medium}}}{\left(\frac{d_{\text{substrate}}\varepsilon_{\text{medium}}}{\varepsilon_{\text{substrate}}} + z\right)^2}$$
* **Engineering Solution:**
  1. **Algorithmic:** Validate `analyze_surface_topography()` and `compute_fractional_deltas()` in `main.py`:
     - Fractional deltas $\delta_i = \Delta C_i / C_{0,i}$ ensure scale invariance.
     - Per-pad adaptive gates $\text{Gate}_i = \min(-150, -\alpha \cdot C_{0,i})$ prevent false negatives on tented pads.
  2. **Materials:** Formulate a viscoelastic hydrocolloid adhesive backing that cold-flows into triangular air wedges, raising local dielectric permittivity to $\varepsilon_r \approx 4-6$ and restoring sensitivity.

---

## 4. Phase 4: Pre-Clinical Validation & Environmental Confounder Studies (Months 9–12)
**Primary Goal:** Measure human physiological interaction, environmental artifacts, and true warning lead times.

### 4.1 Healthy Volunteer Cohort (IRB Protocol)
* Prospective study on 20 healthy adult volunteers.
* Protocol tasks:
  1. Spontaneous facial mimetic movement (smiling, frowning, grimacing, yawning).
  2. Head rotation and neck flexion/extension ($45^\circ$).
  3. Forced coughing and deep diaphragmatic breathing.
  4. Deliberate simulated accidental extubation maneuvers (vertical tug, 45-degree angle pull, lateral tube slide).

### 4.2 Environmental Confounders: Sweat, Saliva, and Moisture
* **The Physics:** Saliva and diaphoresis contain ionic electrolytes ($Na^+, Cl^-$) with high permittivity ($\varepsilon_r \approx 75-80$) and non-zero conductivity ($\sigma > 0.5\text{ S/m}$). Fluid accumulation under the dressing increases capacitance (positive shift).
* **The Risk:** If Kalman drift tracking clamps the baseline upward during sweating, a subsequent tube pull produces an artificially magnified lift delta, potentially causing false alarms, or if unmanaged, adhesive maceration drops coupling.
* **Mitigation:**
  - Multi-frequency interrogation: Measure dissipation factor $D = \tan \delta$ or conductance $G$. Moisture introduces measurable resistive loss ($G > 0$), whereas mechanical pull is purely reactive ($\Delta C < 0, G \approx 0$).
  - Breathable microporous polyurethane top film with high Moisture Vapor Transmission Rate ($\text{MVTR} \ge 3,000\text{ g/m}^2/24\text{h}$).

### 4.3 Optical-Telemetry Ground-Truth Lead Time Quantification
* Deploy OBS Studio Dual-Stream Protocol (`docs/OBS_STUDIO_GROUND_TRUTH_SYNC_GUIDE.md`) in all human and phantom trials.
* Quantify the Early Warning Lead Time ($\Delta t_{\text{lead}} = t_{\text{critical\_displacement}} - t_{\text{first\_alarm}}$).
* **Target Clinical Benchmark:** Mean $\Delta t_{\text{lead}} \ge 3.0\text{ seconds}$ prior to physical tube displacement $> 10\text{ mm}$.

---

## 5. Phase 5: Regulatory Compliance, Safety Architecture & Risk Management (Months 12–18)
**Primary Goal:** Complete medical device software compliance and risk management files.

### 5.1 IEC 62304 Compliance (Medical Device Software Lifecycle)
* **Software Safety Classification:** Classified as **Class B** (non-serious injury if warning fails, as secondary clinical surveillance) or **Class C** (potential for critical hazard if extubation goes completely unmonitored).
* **Software Architectural Invariants (Reinforced from `AGENTS.md`):**
  1. *The browser never classifies:* Centralized deterministic inference in backend engine.
  2. *Deterministic Model Scoring:* No unverified heuristic cascades or hand-coded probabilities.
  3. *Zero Invented Patient Identity:* Strict clinical data privacy (GDPR / HIPAA compliance).
  4. *Traceability Matrix:* Bi-directional mapping from System Requirements (SR) $\rightarrow$ Software Requirements Specification (SRS) $\rightarrow$ Software Unit Verification (Tests).

### 5.2 ISO 14971 Risk Management & Hazard Analysis (FMEA)
| Hazard ID | Failure Mode | Clinical Cause | System Safeguard | Residual Risk Level |
|---|---|---|---|---|
| **HAZ-01** | False Negative (Silent Extubation) | Tented pad over step-height fails fixed $-300\text{ ct}$ gate | Per-pad adaptive gates $\text{Gate}_i \propto C_{0,i}$ + hydrocolloid filling | Low / Broadly Acceptable |
| **HAZ-02** | False Alarm Storm (Alarm Fatigue) | Patient cough / swallowing transient | Annunciator 7-of-6 consecutive voting window + Hold 9 | Low (< 5 false alarms/day) |
| **HAZ-03** | Corrupt Zero-Baseline | Board booted during clinical tape application | Absolute CDC architecture + `seed_plausibility()` contour check | Low |
| **HAZ-04** | Disconnection Masked as Detachment | USB/BLE cable disconnect | Open-circuit detection ($C < 1\text{ pF}$) prompts instant hardware alert | Low |

### 5.3 Hospital Network Integration (HL7 / FHIR / Central Station)
* Implement authenticated WebSocket and REST endpoints with mTLS.
* HL7 v2 / FHIR Observation resource formatting for centralized ICU bedside monitoring stations (e.g., Philips IntelliVue / GE Healthcare CARESCAPE integration).

---

## 6. Phase 6: Multi-Center Prospective ICU Clinical Trial (Months 18–24)
**Primary Goal:** Prove clinical efficacy, reduction in Unplanned Extubation (UE) rates, and lead time in real ICU settings.

### 6.1 Clinical Study Design
* **Design:** Prospective, multi-center, observational pilot trial across 3 Tertiary ICU Centers (Surgical, Medical, Trauma).
* **Sample Size:** $N = 100$ intubated adult patients monitored continuously for $\ge 48\text{ hours}$ per patient ($\approx 4,800\text{ monitoring hours}$).
* **Inclusion Criteria:** Adult ICU patients intubated with oral ETT (Fr 28–34), anticipated mechanical ventilation $\ge 24\text{ hours}$, Richmond Agitation-Sedation Scale (RASS) $-2\text{ to }+2$.

### 6.2 Primary & Secondary Clinical Endpoints
* **Primary Endpoints:**
  1. **Unplanned Extubation Episode Sensitivity:** $\ge 95.0\%$ across all verified accidental pull events.
  2. **Early Warning Lead Time:** Median lead time $\ge 3.5\text{ seconds}$ before irreversible cuff emergence.
* **Secondary Endpoints:**
  1. **False Alarm Rate (Alarm Fatigue Index):** $\le 0.2\text{ alarms/patient-hour}$ (< 5 alarms per bed per 24-hour shift).
  2. **Dressing Contact Quality Index (CQI) Stability:** $\ge 95\%$ contact adherence across 48-hour continuous wear.
  3. **Skin Integrity:** Zero incidence of Medical Adhesive-Related Skin Injury (MARSI) stage $\ge 2$.

---

## 7. Execution Matrix & Milestone Gateways

```
========================================================================================================================
MILESTONE GATEWAY               DELIVERABLE                                     SUCCESS CRITERION               TIMELINE
========================================================================================================================
Gate 1: Bench Physics Complete  Round 2 (S1-S3) + Ground-plane testing           Horizontal Pull Sens >= 80%     Month 3
Gate 2: CDC Hardware Frozen     25-channel CDC prototype PCB benched            < 1.0 fF RMS noise, No zero-cal Month 6
Gate 3: 3D Topography Validated 3D Facial Phantom evaluation complete           Adaptive gates pass all steps   Month 9
Gate 4: Pre-Clinical Human Test IRB volunteer study (N=20) completed            Lead time >= 3.0 s verified     Month 12
Gate 5: Regulatory Package      IEC 62304 / ISO 14971 DHF ready                 100% test traceability          Month 18
Gate 6: Multi-Center Clinical   100-patient ICU clinical trial data             UE Sensitivity >= 95%           Month 24
========================================================================================================================
```
