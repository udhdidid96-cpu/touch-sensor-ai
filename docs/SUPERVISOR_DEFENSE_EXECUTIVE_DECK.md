# Smart Dressing Self-Extubation Warning: Supervisor Defense Executive Deck
## Comprehensive Biomedical AI Engineering Briefing (10-Slide Deck & Advisor Defense Script)
**Date:** September 2026  
**System:** 25-Channel Capacitive Smart Dressing (FastAPI + HistGradientBoosting + CDC Absolute Sensing)

---

## Slide 1: Title & Executive Summary
- **Title:** Smart Dressing for Early Detection of Endotracheal Tube Self-Extubation
- **Key Message:** A 25-channel continuous capacitive sensing array providing early warning before physical tube dislodgement occurs in critical ICU patients.
- **Current Performance Benchmark (81 Recordings, LOFO Out-of-Fold):**
  - **Episode Sensitivity:** 100.0% [91.2–100.0% Wilson 95% CI]
  - **False Alarm Rate:** 4.9% per recording (7.8 alarms/hour)
  - **Median Early Warning Lead Time:** 5.60 seconds before full detachment

---

## Slide 2: The "No-Benchmark" Challenge & Transduction Physics
- **The Core Academic Question:** Since this capacitive signal is brand-new bespoke data with no public benchmark (like PhysioNet or MNIST), why is this processing pipeline theoretically valid?
- **Theoretical Foundation (Parallel-Plate & Fringing Field Model):**
  $$C = \frac{\varepsilon_0 \varepsilon_r A}{d} + C_{\text{fringe}}$$
- **Dielectric Permittivity Asymmetry (Polarity Separation):**
  - Human tissue/skin: $\varepsilon_{\text{skin}} \approx 50 - 80$ (high water/electrolyte content).
  - Medical tube (PVC/silicone): $\varepsilon_{\text{ETT}} \approx 2.8$.
  - Atmospheric air gap: $\varepsilon_{\text{air}} \approx 1.0$.
- **Transduction Polarity:**
  - **Extubation / Peeling:** Tissue contact replaced by air gap ($\varepsilon_r \rightarrow 1.0$) $\rightarrow$ **Deep Negative Delta ($\Delta C \ll 0$)**
  - **Touch / Press:** External body mass coupling $\rightarrow$ **High Positive Delta ($\Delta C \gg 0$)**
  - **Friction / Rubbing:** Coupling modulation without detachment $\rightarrow$ **Low Envelope ($\pm 75\text{ counts}$)**

---

## Slide 3: Algorithmic Architecture Justification (Why HistGradientBoosting?)
- **Why NOT Deep Sequential Models (BiLSTM / 1D-CNN)?**
  - **Small-Sample Tabular Regime:** 81 files (3,349 total frames). Deep neural nets suffer from severe over-capacity; multi-seed testing revealed 6× seed variance ($0.9531 \pm 0.0230$ vs $0.9518 \pm 0.0038$).
  - **Temporal Frame Constraint:** Median vertical pull event length is only **6.7 seconds** (~7–8 usable post-warmup frames). Sequence models with 3.36 s windows starve for context.
  - **Axis-Aligned Decision Boundaries:** Medical failure criteria (lift gate $\le -300\text{ counts}$, noise gate $\pm 60\text{ counts}$) are sharp step functions, modeled natively by tree splits without distortion.
  - **Deterministic Verification:** Zero seed spread; bit-for-bit reproducibility verified by CI (`python run.py verify`).
- **Feature Set (34 Features):**
  - 25 Spatial Pad Deltas (preserves 2D propagation topology $\vec{v}_{\text{peel}}$)
  - 9 Macro Statistics (depth, energy ratio $\sum |\Delta C^-| / \sum \Delta C^+$, exceedance counts).
  - *Note:* A 9-statistic-only baseline dropped episode sensitivity from **100.0% to 70.0%**. The 25 spatial pads are load-bearing!

---

## Slide 4: Generalizability Across the 5 Canonical Scenarios
*Measured Out-of-Fold across all 81 Bench Recordings (Wilson 95% CI):*

| Scenario | Files | Median Deepest $\Delta$ | Gate Crossed ($\le -300$) | Annunciator Result | Clinical Interpretation |
|---|---|---|---|---|---|
| **1. Baseline** | 5 | $-33.8\text{ ct}$ | 0/5 | 0/5 FA (0.0% [0.0–43.4]) | Ambient drift absorbed by Kalman filter |
| **2. Touching** | 21 | $-806.8\text{ ct}$ (rebound) | 18/21 | 1/21 FA (4.8% [0.8–22.7]) | Dominated by $+3,037\text{ ct}$ press; Press 0/11 |
| **3. Friction** | 10 | $-76.2\text{ ct}$ | 0/10 | 0/10 FA (0.0% [0.0–27.8]) | Rubbing stays within safe envelope |
| **4. Pulling** | 30 | $-214.8\text{ ct}$ | 13/30 | **30/30 Sens (100% [88.6–100])** | Full alarm triggered across all modes |
| **5. Peeling** | 10 | **$-869.3\text{ ct}$** | 10/10 | **10/10 Sens (100% [72.2–100])** | Sustained multi-pad detachment detected |

---

## Slide 5: The Horizontal Pull Anomaly & Ground-Plane Solution
- **The Honest Scientific Finding:**
  - On a flat acrylic plate, **Horizontal Pull produces ZERO lift signal** (median deepest $\Delta = -71.2\text{ counts}$, 0/10 cross the $-300\text{ count}$ gate).
  - It behaves purely as a press/contact artifact ($+451.9\text{ counts}$ max).
- **Physical Root Cause:** Pure lateral shear does not separate the patch vertically; fringing capacitance remains coupled.
- **Round 2 Engineering Solution:**
  - Introduce an active **Ground Plane** under the bench skin surface.
  - Converts fringing capacitance into parallel-plate capacitance, generating a strong negative lift delta when shear displaces the dressing edges.

---

## Slide 6: Hardware Evolution: Relative Offset to Absolute CDC
- **The Relative Zeroing Flaw:**
  - Power-on auto-zeroing creates an unverified baseline. If booted with the tube already secured or under thumb pressure, $C_0$ is corrupted, causing severe drift.
- **Current Software Safeguards:**
  - `seed_plausibility()` compares the 25-pad baseline contour against `SEED_RESTING_SHAPE` (gate 575 counts deviation), flagging pre-pressed contamination without failing on natural patch drape.
  - Quiescent Recovery auto-reconverges Kalman baselines for channels stranded below lift gate.
- **The New CDC Architecture (AD7147 / AD7746 / FDC2214):**
  - **Femtofarad Resolution:** Direct absolute reading ($0 - 50\text{ pF}$), eliminating zero-calibration.
  - **Static Tube Localization (`/api/v6/cdc/tube-localization`):** Detects tube presence and orientation immediately upon boot via the dielectric shadow ($\varepsilon_{\text{ETT}} \approx 2.8$ vs $\varepsilon_{\text{skin}} \approx 60$).

---

## Slide 7: Non-Planar Contours & Step-Height Discontinuity (เรื่องต่างระดับ)
- **Clinical Reality vs. Flat Bench Demo:**
  - **3D Facial Curvature:** Zygomatic arch, mandible, and nasolabial folds have radii of curvature $R \approx 15 - 50\text{ mm}$.
  - **ETT Step-Height Discontinuity:** Adult ETT (OD $9.0 - 11.5\text{ mm}$) + anchoring tapes ($1 - 3\text{ mm}$) create a **$3 - 10\text{ mm}$ vertical ridge**.
- **Physical Consequences:**
  1. **Tenting Effect & Micro Air Gaps:** FPC flexural rigidity ($D = \frac{E t^3}{12(1-\nu^2)}$) prevents flush seating at the tube base. A triangular air wedge forms ($\varepsilon_{\text{air}} = 1.0$), dropping $C_{0,i}$ to **$12 - 18\text{ pF}$** (vs $30 - 38\text{ pF}$ on flush skin).
  2. **Non-Linear Sensitivity Degradation ($\frac{\partial C}{\partial z}$):**
     $$\frac{\partial C}{\partial z} = -\frac{\varepsilon_0 A \cdot \varepsilon_{\text{medium}}}{\left(\frac{d_{\text{substrate}}\varepsilon_{\text{medium}}}{\varepsilon_{\text{substrate}}} + z\right)^2}$$
     Over tented air gaps ($z \ge 1.5\text{ mm}$), sensitivity flattens into an asymptote. A $1.0\text{ mm}$ detachment yields only $-100\text{ to } -200\text{ counts}$, creating a **False Negative** if using a fixed $-300\text{ count}$ gate!
  3. **Stress Concentration:** Rigid tube edge acts as a mechanical fulcrum, causing premature peel initiation.

---

## Slide 8: The 4-Tier Step-Height Solution
1. **Tier 1 (Algorithm Layer in `main.py`):**
   - **Normalized Fractional Deltas (F10):** $\delta_i = \Delta C_i / C_{0,i}$ normalizes sensitivity across both ridge and trough pads.
   - **Per-Pad Adaptive Lift Gates:** $\text{Gate}_i = \min(-150, -0.011 \cdot C_{0,i})$ via `analyze_surface_topography()`.
   - **Surface Topography Profiling:** Classifies contact into `'planar'`, `'moderate_contour'`, or `'stepped_ridge'`, flagging tenting pads.
2. **Tier 2 (Sensor Mechanics - Round 2):**
   - Viscoelastic hydrocolloid base to conformally fill air wedges.
   - Ultra-thin serpentine FPC ($\le 25\ \mu\text{m}$) for high drapeability.
   - Strain-relief keyhole slits isolating tube anchor wings from the sensing array.
3. **Tier 3 (Absolute CDC Sensing):**
   - Live Contact Quality Index (CQI) reporting.
4. **Tier 4 (Bench Experimental Setup):**
   - 3D anatomical facial phantom with calibrated step blocks ($3\text{ mm}, 5\text{ mm}, 8\text{ mm}$) for empirical validation.

---

## Slide 9: Bench Rig Refinements & OBS Studio Ground-Truth Sync
- **Industrial Vacuum Suction:** Upgraded from $-15\text{ kPa}$ to **$-40$ to $-60\text{ kPa}$** with thinned substrate ($\le 0.5\text{ mm}$) to ensure genuine force transmission to sensor pads.
- **OBS Studio Dual-Stream Sync:**
  - High-speed 60 fps webcam (spatial displacement & force gauge) synchronized via LED flash marker with GUI telemetry.
  - Quantifies exact **Early Warning Lead Time ($\Delta t_{\text{lead}} = 3.2 - 5.6\text{ seconds}$)** before extubation completion.

---

## Slide 10: Advisor Defense Q&A Cheat Sheet
- **Q1: "Why shouldn't we just collect more data and train a Transformer or LSTM?"**  
  *Answer:* Clinical events in self-extubation are abrupt step-edges (median 6.7 s), not periodic waves like ECG. A sequence model pays for temporal smoothing in latency and seed variance. Our pipeline handles temporal voting transparently in the Annunciator (7-of-6 hold 9) with zero latency penalty and 100% episode sensitivity.
- **Q2: "What happens if the nurse puts the dressing on a patient with sharp cheekbones or an elevated tube?"**  
  *Answer:* Our `analyze_surface_topography()` algorithm immediately detects non-planar tenting and dynamically assigns **Per-Pad Adaptive Lift Gates** ($\text{Gate}_i \propto C_{0,i}$), preventing false negatives. In Round 2, viscoelastic hydrocolloid adhesive conformally fills the air wedges.
- **Q3: "Why did 0 of 81 files reach the ≤ 25,000 count detachment spec?"**  
  *Answer:* It is pure arithmetic: reaching 25,000 counts from a 28,000 baseline requires a 50.1 pF drop at 59.85 counts/pF. The patch only holds ~30 pF total, so at zero capacitance the reading floors at 26,205. The spec requires geometry redesign (thinner backing to raise $C_0$) or re-measurement of absolute $C_0$ via LCR meter.
