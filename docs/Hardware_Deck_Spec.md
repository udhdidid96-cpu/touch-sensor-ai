# SLIDE DECK SPECIFICATION: SENSOR & HARDWARE
## Structured on the KES ver_3 section format

**Project:** Smart Extubation Early Warning System (25-channel capacitive smart dressing)
**Companion to:** `Smart_Extubation_Software_AI_Architecture.pptx` (16 slides, software / AI half)
**Format:** the same major-heading structure as `KESスライド_English.ver_3.pptx` — 23 slides, numbered `(n/m)` within each section.

---

## THE MAJOR HEADINGS

```
Title                                          1 slide
Background            (1/3) (2/3) (3/3)        3
Previous Research                              1
Purpose                                        1
Sensor Structure      (1/4) … (4/4)            4
Proposed Method       (1/3) … (3/3)            3
Experimental Method   (1/2) (2/2)              2
Results               (1/6) … (6/6)            6
Discussion                                     1
Conclusion                                     1
                                              ──
                                              23
```

Same shape as ver_3, which ran Background 3 · Previous Research 1 · Purpose 1 · Sensor Structure 2 · Proposed Method 5 · Experimental Method 2 · Results 6 · Discussion 1 · Conclusion 1. The weight moves from *Proposed Method* to *Sensor Structure* and *Results*, because this deck's contribution is the hardware and its characterisation rather than an algorithm.

---

## HOW TO READ THE MARKERS

- **[MEASURED]** — exists in this repository or the KES 2025 paper. Quote it; never retype it by hand.
- **[FILL]** — a hardware fact only you have. Measure it or read it off the part.
- **[DECIDE]** — an editorial choice.

**Standing rule:** no number reaches a slide unless it traces to `Data/METRICS.md`, the KES paper, or a datasheet.

---

# TITLE

- **Title:** A 25-Channel Capacitive Smart Dressing for Self-Extubation Early Warning — Sensor Design and Characterisation
- Authors and affiliations, matching ver_3. **[DECIDE — confirm the author list for this deck]**
- **Visual:** the dressing with its microcontroller board, from the bench. **[MEASURED — `ver_3.pptx`]**

---

# BACKGROUND (1/3) — What is self-extubation?

- Definition: a patient removes their own medical tube. **[MEASURED — `ver_3.pptx` slide 2]**
- Illustration of the incident. **[MEASURED — reuse]**
- Keep this slide as close to ver_3 as possible; it is the shared opening for both decks.

# BACKGROUND (2/3) — Impact

- Direct risks: massive bleeding, infection. Re-intervention and additional procedures raise cost. **[MEASURED — `ver_3.pptx` slide 3]**
- With central venous catheters or endotracheal tubes, removal can cause serious incident immediately.
- Incident-cause breakdown; drains and tubes share. **[MEASURED — pie chart, `ver_3.pptx` slide 3]**
- **Conclusion line:** the earliest possible detection is what changes the outcome.

# BACKGROUND (3/3) — Countermeasures and their problems

- Nursing rounds → high burden.
- Reinforced fixation → skin inflammation.
- Physical restraint for delirium → ethical problems.
  **[MEASURED — all three, `ver_3.pptx` slide 4]**
- **Conclusion line:** every existing countermeasure trades one harm for another, so automatic detection is needed.

---

# PREVIOUS RESEARCH

- RFID tag on the line — detects removal, not the approach to it. **[MEASURED — Nakajima & Takahashi 2015]**
- Camera plus deep learning — early warning demonstrated, but continuous video carries a privacy cost. **[MEASURED — Yang et al.]**
- **New row for this deck:** the group's own capacitive dressing with autoencoder anomaly detection — F1 0.882 vertical pulling, 0.833 horizontal with false detections. **[MEASURED — `ver_3.pptx` slides 19, 21]**
- **Gap statement:** the sensor itself has never been characterised as a sensor. Every result so far is an algorithm result on top of an uncharacterised front end.

---

# PURPOSE

State two hardware objectives, mirroring ver_3's two-method structure:

1. **Characterise the dressing as a measurement device** — baseline, drift, noise floor, dynamic range, channel mapping, and what each physical interaction actually does to the reading.
2. **Establish what the sensor can and cannot detect**, and specify the readout change needed to close the gap.

Say plainly that the second objective includes reporting a negative result.

---

# SENSOR STRUCTURE (1/4) — Smart dressing material

- Integration of a capacitive touch sensor with a dressing material used in medical institutions → early detection without privacy risk. **[MEASURED — `ver_3.pptx` slide 7]**
- **Specification table:**

| Item | Value | Source |
|---|---|---|
| Number of channels | 25 | **[MEASURED]** |
| Dressing size | 90 × 120 mm | **[MEASURED]** |
| Conversion | 59.85 raw counts / pF | **[MEASURED]** |
| Frame period | ≈600 ms (≈1.7 Hz) | **[MEASURED]** |
| Microcontroller | PSoC 5LP, CY8CKIT-059 | **[MEASURED]** |
| Host link | USB CDC serial | **[MEASURED]** |
| Pad diameter / pitch | — | **[FILL]** |
| Substrate | — | **[FILL]** |
| Supply and power draw | — | **[FILL]** |

# SENSOR STRUCTURE (2/4) — Electrode geometry and placement

- **Visual:** pad layout drawn to scale on the 90 × 120 mm outline. **[MEASURED — `PHYSICAL_PAD_COORDS` in `main.py`; pads span x 20–80 mm, y 22–90 mm]**
- 25 pads in a **staggered arrangement, not a square 5 × 5 grid.** State this explicitly — every spatial figure in both decks interpolates over the real coordinates.
- Trace routing, guard or shield layer. **[FILL]**
- Rationale for the pad count and spacing: coverage against channel count against routing. **[FILL / DECIDE]**

# SENSOR STRUCTURE (3/4) — Capacitor structure and sensing principle

- **Visual:** cross-section — dressing / electrode / dressing / skin, tube above. **[MEASURED — a PowerPoint-shape version already exists on the software deck's slide 2]**
- `C = ε · A / d`.
- **Dielectric loading:** tissue relative permittivity ≈50–80 against ≈1 for air, so proximity raises capacitance. Presses measured at +456 to +1,717 counts. **[MEASURED]**
- **Air gap:** lift-off drops permittivity toward 1 and the reading collapses. Peel median deepest −866 counts. **[MEASURED]**
- Scale: −300 counts ≈ −5 pF, +60 counts ≈ +1 pF. **[MEASURED]**
- ver_3 slide 8 made the same point in one line — *touch raises the value, peeling lowers it.* This slide is the quantified version of that.

# SENSOR STRUCTURE (4/4) — Acquisition chain

- **Visual:** block diagram, pad → CapSense → MCU → USB → host.
- CapSense technique (CSD / CSX), scan parameters, resolution. **[FILL]**
- Per-channel scan time, and why the frame period lands at ≈600 ms. **[FILL]**
- **Speaker note:** this is the most consequential number in the whole project — it sets the alarm latency floor. An early draft of the software deck claimed 20–50 Hz, roughly thirty times too fast, and survived several review passes before being caught.

---

# PROPOSED METHOD (1/3) — Verifying the channel mapping

- The problem: firmware emits `Signal-1..25` in electrical order, and the physical pad at position k is wired to a different channel. Feeding raw order into the coordinate table scrambles the patch.
- The method: press each pad once, in pad order, and test whether each column's peak time increases monotonically with its index. **[MEASURED — `Data/Press/1_by_1.csv`, 343 frames / 192 s]**
- This replaces an assumption that stood unverified for a long time with a measurement.

# PROPOSED METHOD (2/3) — Baseline tracking

- Why a fixed reference fails: sweat and body heat move every pad over a shift, so a reference taken once at start-up is wrong an hour later.
- Per-channel baseline estimate, updated slowly, **gated** so that a jump beyond 120 counts stops the update and the estimate coasts. Without that gate a sustained press is absorbed and becomes the new normal. **[MEASURED — `KalmanBaseline` in `main.py`]**
- Everything downstream works on the distance from that estimate, never on the absolute number.

# PROPOSED METHOD (3/3) — Detachment criterion

- Published criterion, KES 2025 §2.1: full detachment ≤ 25,000 counts; direct finger contact > 30,000 counts. **[MEASURED]**
- Criterion the detector actually uses: a **relative** lift gate at −300 counts from the tracked baseline, plus a ±60 count noise gate.
- Set up the question this deck answers in Results (4/6): do the two agree?

---

# EXPERIMENTAL METHOD (1/2) — Bench and fixation

- **Visual:** bench photographs. **[MEASURED — `ver_3.pptx` slides 14, 15]**
- Tube fixed with a slack loop, mirroring clinical practice. **[MEASURED]**
- Round 1: vacuum rig, **no adhesive**, one session, one sensor mounting. **[MEASURED]**
- Round 2 in progress: high-suction industrial source (-40 to -60 kPa), thinned backing membrane (≤0.5 mm) with medical-grade hydrocolloid adhesive, so shear applied at the tube reaches the pads instead of being absorbed by a loose mount. **[MEASURED — in progress]**
- Multi-stream synchronized video: OBS Studio dual-channel capture (1080p @ 60 fps webcam + real-time GUI heatmap) with visual sync beacon for millisecond lead-time quantification.
- Suction pressure: Round 1 ≈ -15 kPa vs. Round 2 -40 to -60 kPa; substrate: medical-grade polyurethane. **[MEASURED]**

# EXPERIMENTAL METHOD (2/2) — Protocol and corpus

- Pull speed ≈10 mm/s, quantified with an accelerometer alongside the tube. **[MEASURED — `ver_3.pptx` slide 15]**
- **Five interaction scenarios:** baseline · touching · rubbing · pulling · peeling, plus vertical and horizontal pull directions.
- Corpus: **81 recordings, 3,349 frames**, class counts baseline 5 · incidental 36 · peel 10 · pull 30. **[MEASURED — `METRICS.md`]**
- **Note honestly:** every recording opens with a quiescent segment before the named behaviour begins, so a folder label describes an event *inside* a recording, not the whole recording. **[MEASURED — `sensor_findings.md`]**

---

# RESULTS (1/6) — Channel mapping

- **Figure:** each channel's peak time against its index, from the 1-by-1 sweep.
- Result: strictly increasing, **Spearman ρ = 1.0000, 0 inversions** → `Sensor-N` is physical pad N for all 81 recordings. **[MEASURED]**
- **Still open:** the live serial path has never had this sweep run through it, in either direction, so spatial output from live hardware remains unverified. **[MEASURED — `METRICS.md` caveat 7]**

# RESULTS (2/6) — Baseline, noise and dynamic range

- **Figure (a):** 25 raw channels over a long quiet recording. **[MEASURED — regenerate with `scripts/make_deck_figures.py`]**
- **Figure (b):** the same recording after baseline tracking, with the ±60 and −300 gates drawn.
- Resting attached value ≈28,000 counts; corpus range 27,259–31,424. **[MEASURED]**
- Drift over one session and its cause; the noise floor the ±60 gate is derived from. **[MEASURED]**
- Channel-to-channel uniformity. **[FILL]**

# RESULTS (3/6) — Signal signature per scenario

- **Figure:** reconstructed field over the 25 real pad positions — peel, pulling, touch. **[MEASURED — `fig_heatmaps.png`, already built]**
- Peel min Δ −902 · pulling min Δ −610 · touch max Δ +3,442 counts.
- **Table:** median deepest delta by class — peel −866, vertical pull −777, friction −94, horizontal pull −64, baseline −31. **[MEASURED — `sensor_findings.md`]**
- Point out that a touch is several thousand counts while a detachment is several hundred, and that this asymmetry is the calibration problem.

# RESULTS (4/6) — Against the published detachment specification

- **Result: no anomaly recording reaches the ≤25,000 count criterion.** Deepest is **27,251** against 28,000 nominal — a 2.7% drop. **0 of 81 files pass.** **[MEASURED — `METRICS.md` caveat 3]**
- The dressing genuinely detached during those recordings, so this is not a fixation failure.
- **The criterion is unreachable by arithmetic, not merely unmet. [MEASURED — constants + `spec_detach_reachability()`]** 28,000 − 25,000 = 3,000 counts; at the measured 59.85 counts/pF that is a **50.1 pF** drop, from a patch holding about **30 pF**. At zero capacitance the reading still floors at **26,205 counts**, 1,205 above the threshold. No *fixation* change — pump, adhesive — can pass this: it only sets how completely the patch lets go. What can is *geometry*, because C = εA/d sets C0 itself: **halve the backing thickness and C0 roughly doubles; a ground plane makes a fringing-field sensor a two-plate one.** At C0 ≈ 60 pF a 50 pF loss becomes possible. That is the supervisor's thin-backing advice as capacitor arithmetic. **[REASONED — verify with the LCR C0 measurement before and after the geometry change]**
- **Conclusion:** the published threshold does not describe what this patch reads at detachment. The relative −300 gate does — peel and vertical pull cross it 10 of 10 each.
- **Ask on this slide:** the Sensor Structure table's absolute-C0 row is still empty. That single measurement decides which of the three published numbers is wrong. The bench procedure is written up — LCR meter, OPEN compensation, Cp-D mode, attached-vs-detached pair, and a decision table for the result — in `docs/DATA_COLLECTION_SOP_v2.md` section 0.2. It also gives a second, more direct check: measure counts-per-pF empirically from one peel event and compare it against the published 59.85. **[FILL — 15 minutes at the bench]**
- **Speaker note:** raising the constant to 28,500 was tried. It passes 81 of 81 files *including bare baselines*, because the resting value sits above it. That is why it was reverted.

# RESULTS (5/6) — Vertical pull and peel

- **Figure:** the two classes that produce a clean lift signature.
- Peel 10/10 cross −300, median −866. Vertical pull 10/10 cross −300, median −777. **[MEASURED]**
- This is the sensor working as designed, and it is what the software half's 100% episode sensitivity rests on.

# RESULTS (6/6) — Horizontal pull

- **Figure:** deepest delta by class, with the −300 gate marked. **[MEASURED — bar chart already built for the software deck]**
- **Horizontal pull produces no lift signal at all:** median deepest **−64 counts**, deepest −161, **0 of 10** cross the gate — quieter than Friction, which is a normal class. **[MEASURED]**
- **Why, and it is not a defect in the firmware.** Parallel-plate capacitance varies with plate *separation*, not lateral position. The round-1 patch is a **single layer with no ground plane**, so there is no true counter-electrode on the skin side — only fringing field. Vertical pull and peel increase the separation and the capacitance falls, which is the lift signal. A horizontal pull slides the patch sideways at **constant separation**, so capacitance barely moves; what does move is the hand and tube line approaching the pads, which *raises* capacitance. The system therefore classifies a horizontal detachment as a press. **[REASONED from the measured deltas above]**
- **This is what the ground plane is for.** With a counter-electrode present, lateral displacement changes the plate *overlap area*, which capacitance is directly proportional to. That makes horizontal pull detectable in principle. Whether it becomes detectable in practice is the primary round-2 acceptance criterion (`DATA_COLLECTION_SOP_v2.md` section 8): HPull at least 5 of 7 files crossing −300, against 0 of 10 today.
- What does move is the contact side, median +456 counts, so anything flagged there is flagged as a press, not a detachment.
- Worse, the separation runs on press *magnitude*: heavy presses of +1,357 to +1,717 counts produce no pull frames while moderate ones do. For a safety device that ordering is backwards. **[MEASURED]**

---

# DISCUSSION

- **What the sensor senses well:** normal lift. Both peel and axial pull open a gap, and the reading collapses by hundreds of counts, 10 of 10 recordings each.
- **What it cannot sense:** lateral shear. The patch slides without opening a gap, so the measured quantity barely changes. This is a *transduction* limit, not an algorithm limit.
- **Convergent evidence:** the group's own autoencoder hit the same wall on the same hardware — F1 0.833 horizontal against 0.882 vertical, with explicit false detections and the note that the score "does not react much to weak pulling". Two independent methods failing identically points at the sensor. **[MEASURED — `ver_3.pptx` slides 20–22]**
- **On the specification:** a criterion written before characterisation did not survive contact with the corpus. Report the measurement, not the specification.
- **Scope:** one sensor mounting, one session. Nothing here shows the patch behaves the same when re-applied.

---

# CONCLUSION

- Characterised the 25-channel capacitive dressing as a measurement device: baseline ≈28,000 counts, 59.85 counts/pF, ≈600 ms frame, channel mapping verified at ρ = 1.0000.
- Peel and vertical pull produce a reliable lift signature; **horizontal detachment produces none.**
- The published ≤25,000 count detachment criterion is not met by any recording, and a relative −300 count gate is used instead.

**Future Work**

- Re-measure on round-2 data from the high-suction bench (-40 to -60 kPa with hydrocolloid adhesive), without retuning anything on it.
- Port to an absolute capacitance-to-digital converter (CDC) board (e.g. AD7147 / AD7746 / FDC2214 or PSoC in absolute sigma-delta CDC mode; femtofarad resolution, 0-50 pF dynamic range). Eliminates power-on zero-calibration dependence and enables static tube localization/routing verification prior to monitoring.
- Synchronized multi-stream ground-truth validation using OBS Studio (webcam + GUI heatmap) for frame-accurate early warning lead-time measurement.
- A sensing route for lateral shear via adhesive shear coupling and mechanical force-distribution analysis.
- Record across several mountings and several people, and report per-session results.

---

## WHAT I CAN BUILD NOW

Fully sourced and buildable today: **Title, Background 1–3, Previous Research, Purpose, Sensor Structure 2 and 3, Proposed Method 1–3, Experimental Method 1–2, Results 1–6, Discussion, Conclusion** — 19 of 23 slides, every figure regenerated from `Data/`.

Blocked on **[FILL]**: Sensor Structure (1/4) specification table has four empty rows, Sensor Structure (4/4) needs the CapSense configuration and power figures, and Future Work needs the CDC part. Nothing in the repository holds any of these.

Say the word and I will build the 19.
