# 24-Month Translation Plan and Technical Evaluation

## Smart Dressing Self-Extubation Early Warning (Project2): from one bench session to a first ICU study

| | |
|---|---|
| Date | 25 September 2026 |
| For | The academic supervisor and the project team |
| Status | Proposal for discussion. It reviews and corrects `docs/LONG_TERM_BIOMEDICAL_AI_ROADMAP.md`, which is left unchanged so the two can be compared. |
| Scope | Engineering, clinical validation and regulatory strategy, months 1 to 24 |
| Reproduce | `python scripts/translation_plan_checks.py` regenerates every computed number in this document (read-only, about a minute). The three headline blocks in §2.1 are written from `Data/metrics.json` by `python scripts/sync_metrics_blocks.py` and checked by the test suite. |

**Regulatory status, stated once.** This device has not been assessed against IEC 62304, ISO 14971, ISO 13485 or IEC 60601. This plan describes how that assessment would be prepared. It does not claim compliance.

---

## 0. The verdict

**The order of the six phases is right. Three of the plan's main promises cannot be kept as written. Each one fails on arithmetic or physics, not opinion.**

1. **Phase 6 cannot measure sensitivity.** 4,800 monitoring hours is 200 ventilator-days. Published rates are about one unplanned extubation per 100 ventilator-days, and 84–88% of those are self-extubations. So the planned study expects about **1.8** self-extubations, with a **17%** chance of seeing none at all. Even 5 detected out of 5 gives a 95% lower confidence bound of only **47.8%**. To show a lower bound of 90% (if the true sensitivity is 97%) takes at least **100 events**, and 114 to stay clear of the dips in exact-binomial power. That means **11,200–12,800 ventilator-days**, 56–64 times the planned study. Phase 6 should become a feasibility study with primary endpoints that 4,800 hours can measure well:
   - false-alarm burden
   - wear time and signal quality
   - skin safety
   - detection of tube-handling events annotated from video

   Sensitivity to real self-extubation comes from bench and simulated-use evidence now, and from a larger event-driven study after month 24.

2. **No lead time has ever been measured, and today's hardware cannot give 3 seconds of it.** Three project documents quote "3.2–5.6 s before the tube comes out". Nothing supports it: round 1 has no video and no timestamps for when each event starts. The "5.60 s median time to alarm" is counted from the start of each file. For 25 of the 40 anomaly recordings on the offline path it is exactly 5.60 s, which is the earliest the pipeline allows. After 5 warm-up frames, the sixth agreeing vote lands on frame index 10, and 10 × 0.56 s = 5.60 s. The 6 votes alone take 3.36 s. A lead-time claim needs three things: frames at 20 Hz or faster, onset timestamps from the rig, and a defined endpoint for when the tube counts as displaced.

3. **"Absolute CDC" gives you a zero you can check, not a detector without a zero.** (CDC = capacitance-to-digital converter.) Each patient's resting capacitance depends on their skin, contact, posture and how their body couples to ground. So detection will still compare each pad against that patient's own resting value. An absolute reading adds two things:
   - At power-on, it can check that resting value against a known "attached" range.
   - It can spot a slow detachment that the drift tracker would otherwise absorb.

   Today's CDC code path does neither. It re-zeroes on its first frame, and its power-on check reports "attached" for every starting value from 3 pF to 45 pF (§3.3, §9).

Four more findings change the design:

4. **A flat copper ground plane cannot see pure sliding.** A pad's capacitance to a uniform plane does not change when the pad slides parallel to it. The plane will make lifting and puckering louder, which is worth having. But a horizontal pull still produces no lift signal unless the dressing lifts. Today the bench's horizontal pulls are caught only through the press-like contact side. Detecting shear needs a patterned counter-electrode inside the dressing (a two-layer shear cell) or a sensor on the tube itself. Build a prototype in Phase 1 so that Phase 2 does not depend on the plane working.

5. **The chip shortlist does not match the stated 0–50 pF range, and none of the three chips can measure moisture loss.** AD7147 reads ±8 pF around an offset of up to 20 pF. AD7746 reads ±4 pF around up to 17 pF. Only FDC2214, a resonant design, reaches 50 pF. None of the three reports a dissipation factor (D, the "lossiness" that separates a wet film from an air gap). So Phase 4's plan to tell sweat from lift by D needs a front end that measures complex impedance, and that choice belongs in Phase 2.

6. **The physics model in the documents uses values from the wrong frequency band.** "Skin εr ≈ 50–80" is the value at about 100–300 MHz. In the kHz band where AD7147 and AD7746 work, dry skin is about 1,100 and wet skin 7,000–25,000. Even at 5 MHz, inside FDC2214's range, both are still 400–580. At all of these frequencies the tissue underneath conducts. In effect the body is the second plate of every pad's capacitor. This limits what "tube shadow" and "hydrocolloid fills the air gap" can do. It also means the round-1 bench measured a different capacitor from the one on a patient: those pads sat on an insulating plate with no body-like conductor under them. Every threshold must be re-derived on a body simulant.

7. **Month 12 is too late to start regulatory work, and the list of standards is incomplete.** Design controls and risk management should start in month 1. The plan also needs:
   - IEC 60601-1 (electrical safety)
   - IEC 60601-1-2 (EMC; a capacitive front end is exactly what RF immunity testing disturbs)
   - IEC 60601-1-8 (alarm systems)
   - IEC 62366-1 (usability)
   - ISO 10993 (materials in contact with skin)
   - ISO 14155 (clinical investigations)
   - IEC 81001-5-1 (health software security)

   Twenty-four months can take the device through a first ICU feasibility study. It cannot reach certification.

**What should stay:** the project's evidence discipline: pre-registered rules, generated metrics, frozen gates, and invariants enforced by tests. It is the project's strongest asset, and every gate below is written the same way.

### Scorecard of the six phases

| Phase | As written | Verdict | Main change |
|---|---|---|---|
| 1. Bench physics and multi-session (M1–3) | S1–S3 sessions, copper ground plane, LCR C0, industrial vacuum | Keep, with changes | Measure how counts map to pF (the full transfer), not only C0. Use a body simulant, not a bare plane. Hold the dressing with adhesive, not suction. Timestamp event onsets. Prototype a shear cell. Rewrite acceptance criteria as contrasts against normal activity. |
| 2. Relative to absolute CDC (M3–6) | AD7147 / AD7746 / FDC2214, <1 fF, no zero-calibration, tube shadow, serpentine FPC | Keep the goal, rewrite the requirements | Specify range from the measured C0 and noise from the measured sensitivity cliff; resolution is not the constraint. "Absolute" means calibrated and checkable. Retrain on the new board rather than converting units. Run the alarm on the bedside unit. |
| 3. 3D phantom and step height (M6–9) | Face phantom R 15–50 mm, 3/5/8 mm steps, hydrocolloid, adaptive gates | Keep, fix the gate units | Give the phantom a conductive core. Add an 11–12 mm step. Scale gates with capacitance, not raw counts. Measure adhesive drift before choosing hydrocolloid. |
| 4. Volunteers and confounders (M9–12) | N = 20, sweat/saliva D, OBS lead time ≥ 3.0 s | Keep N = 20 as a pilot, redefine lead time | Use a sham tube (no intubation). Hardware time sync. Measure lead time without targeting a value. Measure D only if the front end can. |
| 5. Software safety and regulatory (M12–18) | IEC 62304 B/C, ISO 14971, ISO 13485, mTLS/FHIR/HL7 | Start in month 1, add the missing standards | Separate the alarm path from the dashboard. Alarm locally first, network second. Plan electrical-safety and EMC tests before any patient study. |
| 6. Multi-center ICU trial (M18–24) | N = 100, 4,800 h, sensitivity ≥ 95%, false alarms < 5/bed/day | Re-scope as feasibility | Primary endpoints become false-alarm burden, valid-signal time, skin safety and video-annotated tube-handling events. Real self-extubations are reported as a case series. Include agitated patients. |

---

## 1. What was checked, and how

All runs used a copy of the repository as it stood at 23:31 JST on 24 September 2026. At that point `main.py` was last modified 24 September 00:14 JST, and the three documents under review between 23:01 and 23:13 JST. The environment was Linux with Python 3.13.13, scikit-learn 1.9.0, numpy 2.5.0, scipy 1.18.0, pandas 3.0.3 and joblib 1.5.3. That is the stack pinned in `requirements.txt`, which CI and the Dockerfile also use. The Windows workstation was not used for these runs.

| Check | Result |
|---|---|
| `python run.py test` | **218 passed**, 1 warning (Starlette's deprecation notice for `httpx`, already present before), 2,344 s, exit 0. Run with `-p no:cacheprovider`, which only stops pytest writing its cache folder. The 23 September engineering review recorded the same 218 on the workstation. |
| `python run.py verify` | **OK**: every headline figure reproduces within 2% of `Data/metrics.json`, and times to alarm within one frame. Dataset fingerprint `346759f6cb62eebc`. 420 s, exit 0. |
| `python run.py pads` | Spearman ρ 1.0000, 0 inversions, exit 0. Sensor-N is physical pad N for the CSV corpus. |
| `python run.py audit Data` | Exit 2, the known state of the round-1 corpus: 0/10 Peel files reach ≤ 25,000 counts (unreachable by arithmetic), while 10/10 cross the −300 lift gate. Movement inside the 5-frame offset window in 40/81 files. 75/81 files shorter than 100 frames. Worst baseline swing 234 counts. |
| `python scripts/translation_plan_checks.py` | New and read-only, exit 0. It produces every computed number in §3, §9 and Appendix A. |

Code read: `LivePipeline`, `KalmanBaseline`, `classify_deltas`, `AlarmDebouncer`, `seed_plausibility`, `analyze_surface_topography`, `compute_fractional_deltas`, `convert_absolute_cdc_to_counts`, `detect_static_tube_localization`, `spec_detach_reachability`, `_episode_figures`, `cpri`.

Documents read: the three under review, plus `Data/METRICS.md`, `AGENTS.md`, `docs/DATA_COLLECTION_SOP_v2.md` §0–§9, `docs/PLAN_SUPERVISOR_FEEDBACK_EN.md` and `docs/ENGINEERING_REVIEW_2026-09-23.md`.

Three sources could not be read (rate limit or captcha): the PubMed and Europe PMC abstracts of the 2022 meta-analysis and of the Safe-ICU study, and the 2025 OUTCOMEREA self-extubation paper. The incidence figures in §3.7 come from the ScienceDirect abstracts of the first two instead.

---

## 2. Where the project stands

### 2.1 Headline figures (generated, do not edit)

<!-- metrics:episode_headline_en -->
Episode-level, out-of-fold, 7-of-6 hold 9: sensitivity **100.0%** [91.2–100.0], false alarm **4.9%** per recording [1.3–16.1] = **7.8 alarms/hour**, median time-to-alarm **5.60 s** (worst 17.36 s), 0 missed events. Source: `Data/metrics.json` (2026-09-25, v6.2).
<!-- /metrics:episode_headline_en -->

<!-- metrics:served_headline_en -->
Served path (every recording streamed through LivePipeline), out-of-fold, 7-of-6 hold 9: sensitivity **97.5%** [87.1–99.6], false alarm **4.9%** per recording [1.3–16.1] = **5.2 alarms/hour**, median time-to-alarm **7.28 s** (worst 17.36 s), 1 missed (Vertical Pull NO G/A_VPull_06.csv). Source: `Data/metrics.json` (2026-09-25, v6.2).
<!-- /metrics:served_headline_en -->

<!-- metrics:file_level_en -->
File-level (file CV, 1 seeds, 81 files / 3349 frames / 34 features): accuracy **97.5%**, macro F1 **0.9612**. Source: `Data/metrics.json` (2026-09-25, v6.2).
<!-- /metrics:file_level_en -->

How to read them:

- **The served line describes the device.** The offline line is the model voting on a cleaner signal that the device never computes (`docs/ML_ENHANCEMENT_PLAN.md` §9).
- **The episode is the clinical unit.** File-level accuracy changes with clip length (METRICS caveat 2).
- **"Time to alarm" counts from frame 0 of each recording, quiet lead-in included, and cannot be lower than 5.60 s** (§3.5). It is neither a detection latency nor a lead time.
- **Every figure comes from one sensor mounting, on one day, with one operator (session S0).** None of them shows that the result generalises to a patch that has been taken off and put back on.

### 2.2 Five facts that shape every phase

1. **One session.** 81 recordings and 3,349 frames, all from one mounting. Leave-one-file-out holds out a file, not an attachment.
2. **Horizontal pull produces no lift signal, whichever calibration is used.** The median deepest delta is −111 counts with the static baseline, −71 with the Kalman tracker and −75 on the served path. In all three, 0 of 10 files cross −300. METRICS caveat 6 quotes −64 (deepest −161, median max +456), but that text is a hard-coded string in `_caveats()` that no current calibration reproduces. The finding stands. The numbers should be regenerated from data, and the calibration named.
3. **One frame takes 0.56 s (about 1.8 Hz).** `docs/Hardware_Deck_Spec.md` still leaves "why the frame period lands at ≈600 ms" as [FILL].
4. **Sensitivity falls steeply as front-end noise rises.** `docs/ENGINEERING_REVIEW_2026-09-23.md` §3 tested the served detector, trained on the clean bench data, with noise added:

   | Added noise (sd, counts) | Events found |
   |---|---|
   | 30 | 27/40 |
   | 60 | 14/40 |
   | 120 | 9/40 |

   The bench noise floor is about 8.4–8.6 counts sd: `docs/PHYSICS_TO_FEATURE_MAP.md` gives 8.6 [7.7–9.9], and the script gets 8.4 from frame-to-frame differences over the N_base pads. At 30 counts of added noise, about 3.6 times that floor, the served detector already finds 27 events against 39 on clean data. No noise level between clean and 30 counts has been tested. So the safe margin is below 3.6× the bench floor, and it has not been mapped.
5. **The absolute capacitance has never been measured.** Three published constants and one assumption cannot all hold:
   - about 28,000 counts at rest;
   - 59.85 counts/pF (labelled as measured);
   - ≤ 25,000 counts at detachment;
   - a patch capacitance of about 30 pF, which has never been measured (`main.py`, the note under `NOMINAL_BASELINE_PF`).

   If C0 is above about 50 pF, the spec becomes reachable and the contradiction disappears (METRICS caveat 3). Until C0 and the counts-to-pF transfer are measured, every pF value in the documents is an assumption. That includes 12–18 pF for tented pads, 30–38 pF for flush pads, air ≈ 5 pF, and the 0–50 pF chip range.

### 2.3 What is not known yet, and where the plan measures it

| Unknown | Why it matters | Measured in |
|---|---|---|
| Absolute C0, and the counts-to-pF offset and slope | Settles the ≤ 25,000 contradiction; sets the converter's input range | Phase 1, week 1 |
| Each pad's coupling to a body-like conductor | Every threshold depends on it | Phases 1–3 |
| When each event starts (onset time) | Needed for latency, clean labels and lead time | Phase 1 (motorised rig) |
| Lead time | The central clinical claim | Phase 4 (volunteers), Phase 6 (surrogate events) |
| Horizontal-pull signal with adhesive and a ground plane | The known blind spot | Phase 1 |
| Frame rate the current PSoC board can reach | Lead time | Phase 1 |
| Effect of sweat and saliva on C (and on loss) | False alarms and misses | Phases 3–4 |
| Pad order on the live socket paths | Heatmap and peel direction on live hardware | Phase 1 |
| How often ICU patients touch the dressing | False-alarm burden | Phase 6 |
| Which direction real self-extubation pulls go | How much the horizontal-pull blind spot matters | Phase 6 (video) |

---

## 3. First-principles review of cross-cutting issues

### 3.1 What a pad actually measures on a person

The documents model the pad with a dielectric contrast: skin (εr ≈ 50–80) against the tube (εr ≈ 2.8) against air (εr = 1). Those skin values belong to the 100–300 MHz range. At the frequencies these converters use, published tissue data give very different values (Gabriel et al. 1996, four-Cole-Cole fits; computed by the script):

| Frequency | Dry skin εr | Wet skin εr | Muscle εr | Muscle σ (S/m) |
|---|---|---|---|---|
| 32 kHz (AD7746 class) | 1,130 | 24,977 | 12,096 | 0.35 |
| 100 kHz (LCR test) | 1,119 | 15,369 | 8,089 | 0.36 |
| 250 kHz (AD7147) | 1,098 | 7,189 | 5,763 | 0.40 |
| 5 MHz (inside FDC2214's range) | 579 | 398 | 308 | 0.59 |
| 300 MHz (for comparison) | 50 | 52 | 58 | 0.77 |
| 1 GHz (for comparison) | 41 | 46 | 55 | 0.98 |

From kHz up to a few MHz, which covers all three converters, the tissue under the skin behaves as a conductor. Each pad forms a capacitor whose other plate is the patient's body. Its value depends mostly on how far the pad sits from that conductor, and on what fills the gap: dressing, adhesive, the outer skin layer, and any air. Three things follow.

- **The tube acts as a spacer, not as a dielectric.** It holds the dressing away from the body (tenting). A static map of C0 can show where contact is poor, whatever the cause. Calling that "tube localisation" is an overclaim until the phantom work in Phase 3 shows the two can be told apart.
- **Sweat and saliva are conductive films.** They can connect a pad to the body or to its neighbours. That adds loss and can raise C. Neither effect is small, and neither has been measured.
- **Round-1 counts do not transfer to skin.** The round-1 pads sat on an insulating acrylic plate with no body-like conductor underneath. The copper plane in Phase 1 is really a body simulant, and it changes the physics being measured.

**An order-of-magnitude check that exposes an inconsistency.** A 38.5 mm² pad (the area in the progress report) over a dielectric of εr ≈ 3 couples to a conductor with about:

| Backing thickness | Coupling |
|---|---|
| 0.5 mm | 2.05 pF |
| 0.1 mm | 10.2 pF |
| 0.05 mm | 20.5 pF |

Lifting that pad 0.5 mm off a 0.5 mm backing changes its coupling by only about −1.5 pF, or −92 counts, well short of the −300 lift gate. Yet the median bench peel is −869 counts, about 14.5 pF. For a full loss, that implies an effective d/εr of about 24 µm to a conductor (d ≈ 70 µm at εr 3). This is hard to square with a backing that the documents call thick, on an insulating plate. One of three things must be true:

- something conductive sits close under the pads on the rig;
- fringing fields to nearby structure dominate the reading;
- 59.85 counts/pF does not describe this rig. It is labelled as measured, so this is the least likely of the three.

These parallel-plate numbers are rough estimates, not measurements. The LCR work in Phase 1 settles which explanation is right, and it is the same measurement that settles the ≤ 25,000 contradiction.

### 3.2 Why a flat ground plane cannot see pure sliding

Slide a small pad sideways over a large, uniform conducting plane and nothing about its capacitance changes. The plane looks the same from every position. This is translation symmetry, and it holds whatever the adhesive or the vacuum. Two documents say the plane "gives lateral motion something to change" and that "lateral displacement changes the plate overlap area". That only happens when the pad moves off the plane's edge, or when the counter-electrode is patterned.

What the plane **does** do:

- It defines a reference.
- It makes lift and puckering more visible per millimetre.
- It stands in for the body.

Shear usually starts a lift at the trailing edge, so some horizontal pulls may become visible through lift. The Phase 1 acceptance test will show how many. A pull that slides the dressing without lifting it will still be invisible.

Three ways to measure shear directly:

1. **Two-layer shear cell.** One electrode is fixed to the tube anchor and a pair below it is fixed to the skin side, separated by a soft dielectric about 0.5–1 mm thick. Shear shifts the overlap, and the difference between the pair measures the displacement. This is a mutual or differential capacitance measurement, so the Phase 2 converter must be chosen to support it. AD7147 is a single-electrode part.
2. **Tube-position channel.** A marker on the tube is read by the dressing, so the device measures the tube moving, which is the thing that matters clinically.
3. **Strain sensing** in the fixation strap.

A different technology already addresses the same clinical question: acoustic reflectometry checks tube position and obstruction in real time (Medtronic SonarMed, aimed at neonatal and pediatric patients). Regulators and clinicians will ask how this device compares.

### 3.3 The count scale, and what it does to normalisation and gates

The three constants in `main.py` imply that counts = 26,204.5 + 59.85 × C (pF). At rest, 94% of the reading is a fixed offset. If that model holds, three things follow (numbers from the script):

- **F10 normalisation barely normalises.** It divides each delta by the raw count baseline and multiplies by 28,000. Between a 15 pF pad (27,102 counts) and a 35 pF pad (28,299 counts) that rescales by only about 4%. It cannot provide the scale invariance the documents describe. Dividing by capacitance, that is by counts minus the offset, would.
- **The per-pad adaptive gates in counts mode are about 4% apart:** −298 counts for a 15 pF pad against −311 for a 35 pF pad.
- **In pF mode the gates are off by a factor of 13–31.** They come out at −0.16 to −0.38 pF, which is −10 to −23 counts. That is inside the ±60-count noise gate and 13–31 times tighter than the −300-count lift gate (−5.0 pF). The comment in `analyze_surface_topography` takes 1.1% of a *count* reading and applies it to a *capacitance*.
- **On the live CDC path, all 25 gates come out at −308.** They are computed from the re-zeroed baseline, which is flat by construction.

None of this changes a published figure, because these gates feed only the peel tracker (its pad count and confirmed flag, which the console shows as patch integrity), not the alarm level. What fails is the claim that "tented pads receive appropriately scaled gates". **Fix:** once C0 is measured, express every gate in capacitance units (or as a fraction of each pad's own capacitance). Then test the gates on the step phantom and freeze them before any new data is collected.

### 3.4 The slow-detachment blind zone of the drift tracker

The baseline tracker is a Kalman filter: a running estimate of each pad's resting value that follows slow drift and ignores fast changes. Any tracker of this kind has a speed limit below which a real change looks like drift. The shipped tracker has a fixed process noise and an innovation gate of 120 counts (the innovation is the difference between a new reading and the tracked baseline).

On the device path (`LivePipeline`), the tracker is seeded from a single frame, so its measurement noise is fixed at 40 counts² on every pad. The speed limit comes out at about:

- 4.2 counts per frame, which is
- 7.4 counts per second, which is
- **0.124 pF per second.**

The offline path sets the noise from the first five frames instead. There the limit is 0.095 pF/s at the measured bench noise, and 0.065–0.175 pF/s across the range the code allows.

The script streams noise-free ramps through `LivePipeline` itself:

- **At 0.8 times the device limit:** the delta settles near −93 counts and never reaches −300 in 3,000 frames (28 minutes).
- **At 1.2 times:** the delta runs away and crosses the lift gate. Crossing the gate is not an alarm in itself; the model decides the alarm (§8 row 4).

The deepest round-1 peel is −902 counts, about 15 pF. A detachment that deep is absorbed as drift if it develops over more than about 2 minutes: 121 s on the device, and 86–233 s offline depending on noise. That is fine for a sudden pull. It is not fine for adhesive that loosens slowly over a shift.

**Fix:** add a cumulative-drift monitor. It compares the current baseline with the baseline at seed (and, once absolute readings exist, with an attached range in pF) and raises a technical "check dressing" alarm when the difference grows too large.

### 3.5 Timing: what the alarm can and cannot promise

| Quantity | Value | Source |
|---|---|---|
| Frame period | 0.56 s | `SAMPLE_PERIOD_S` |
| Frames needed to agree before an alarm | 6 of 7 | `AlarmConfig` |
| Evidence needed at 0.56 s per frame | 3.36 s | script |
| Same six votes at 10 / 20 / 50 Hz | 0.60 / 0.30 / 0.12 s | script |
| Earliest possible alarm, counted from file start | 5.60 s: frames 0–4 are warm-up, frames 5–10 carry the six votes, and frame index 10 sits 10 × 0.56 s after frame 0 | script |
| Anomaly recordings alarming at exactly that floor | 25/40 offline, 12/39 served | script, from `Data/served_path_benchmark.json` |

Lead time is t(critical displacement) − t(first alarm). It is positive only if the dressing is disturbed long enough before the tube moves: at today's frame rate, 3.4 s of qualifying frames at the very least. Whether patients disturb the dressing that early is an empirical question, and nobody has measured it.

The plan therefore does four things:

- raises the frame rate;
- timestamps event onsets from the rig;
- reports latency from onset, not from the start of the file;
- turns vote windows counted in frames into windows measured in seconds, re-derived and pre-registered for each new frame rate.

### 3.6 Bench suction: what −15, −40 and −60 kPa actually hold down

If suction acts over the whole 90 × 120 mm footprint, it holds the dressing down with:

| Suction | Force | Weight equivalent |
|---|---|---|
| −15 kPa | about 162 N | 16.5 kg |
| −40 kPa | about 432 N | 44 kg |
| −60 kPa | about 648 N | 66 kg |

If the suction holds the dressing itself, what the bench records at release is a seal breaking, not an adhesive letting go, and more vacuum makes that worse. The supervisor's aim is right: force should reach the pads rather than be absorbed by a loose backing. The way to get there is to use suction, or clamps, only to hold the skin simulant flat on the fixture. The dressing should be held by the adhesive intended for patients. Record the vacuum level as a nuisance variable, meaning a condition that is logged but not relied on.

### 3.7 Clinical event rates, and what a 4,800-hour study can measure

- **Incidence.** A 2022 meta-analysis (38 studies, 18 countries) pooled unplanned extubation at **1.06 per 100 ventilator-days** (95% CI 0.7–1.3). 84.2% of those were self-extubations, and 50.2% of patients needed reintubation within 48 h (Li, Sun, Xu, Intensive Crit Care Nurs 2022). A 47-ICU French prospective study found **1.0 per 100 ventilation days** with 88% self-extubation. By day 7, 35% of self-extubated patients and 83% of accidentally extubated patients had been reintubated (Guillemin et al., Anaesth Crit Care Pain Med 2024).
- **What 4,800 h buys.** 200 ventilator-days give an expected **1.76–1.79** self-extubations. The chance of seeing **none** is **17%**, and the central 95% range is 0–5 events.
- **What a perfect record would show.** The 95% lower bound on sensitivity if every event is detected:

  | Events detected | Lower bound |
  |---|---|
  | 2/2 | 15.8% |
  | 5/5 | 47.8% |
  | 10/10 | 69.2% |
  | 30/30 | 88.4% |
  | 59/59 | 93.9% |

- **What it would take** (80% power, two-sided 95% Clopper–Pearson bound, meta-analysis rate). Exact-binomial power rises in a saw-tooth, so each cell gives two numbers: the first sample size that reaches 80% power, and the one from which power stays above 80%. A protocol should plan on the second.

  | Goal | Events needed | Ventilator-days | Multiple of the planned study |
  |---|---|---|---|
  | Lower bound ≥ 80% if true sensitivity is 95% | 41 / 48 | 4,594 / 5,378 | 23× / 27× |
  | Lower bound ≥ 90% if true sensitivity is 97% | 100 / 114 | 11,204 / 12,773 | 56× / 64× |
  | Lower bound ≥ 90% if true sensitivity is 99% | 54 / 54 | 6,050 | 30× |
  | Lower bound ≥ 95% if true sensitivity is 99% | 142 / 173 | 15,910 / 19,383 | 80× / 97× |

- **What 4,800 h measures well: false alarms.** At the target of 5 per bed-day, the study would see about 1,000 false alarms. The Poisson 95% interval is 4.69–5.32 per bed-day. That interval is too narrow, because alarms cluster within patients, so the analysis should model each patient's rate (negative-binomial). Even so, the precision is ample.

---

## 4. The six phases, revised

Each phase is set out the same way: goal as written, what holds, what changes and why, work packages, gate criteria fixed before any data is collected, deliverables, and risks with a fallback.

### Phase 1: Bench physics and multi-session generalisation (months 1–3)

**Goal as written.** Collect sessions S1–S3, add a copper ground plane for horizontal pull, measure absolute C0 with an LCR meter, and install an industrial vacuum pump.

**What holds.** The S1–S3 protocol in `docs/DATA_COLLECTION_SOP_v2.md`:

- 52 files per session;
- 60–120 s per file, with events repeated inside each file;
- parameters frozen before collection;
- session cross-validation (`--cv session`) as the published unit.

The LCR measurement and the ground plane also stay.

**What changes, and why.**

- **Measure the transfer, not just C0.** Take at least three points: the pad in air, the pad attached, and one or two known reference capacitors switched onto a pad input. Fit the offset and slope with their uncertainty. Measure pad to board ground through the same cable and ground the PSoC uses, and record frequency, Cp–D mode and D (SOP v2 §0.2). Repeat after adding the ground plane and after thinning the backing. This single measurement settles which of the three constants is wrong (§2.2), fixes the converter's input range, and gives the gates a physical unit.
- **Build a body simulant, not a bare plane.** Put a conductive layer (copper, or a conductive gel of physiological conductivity) under a thin skin-like dielectric. Connect it to board ground both directly and through a series capacitor of about 100 pF, the value common human-body models use, so that strong and weak body coupling are both covered.
- **Adhesive holds the dressing, suction holds only the simulant** (§3.6).
- **Use motorised pulls with onset timestamps.** A linear stage with a load cell pulls a tube stub at set angles (0°, 45°, 90°) and speeds. It logs force, displacement and onset on the same clock as the sensor frames: the microcontroller drives an LED the camera can see and writes a serial marker at the same moment. This gives true onsets for latency, clean labels (only frames after onset count as the event), and a first bench lead-time measurement. It also fixes the known label noise from quiet lead-ins, where 58 of the 240 votes behind the first offline alarms are sub-gate frames.
- **Profile the frame rate.** Find where the 600 ms goes in the PSoC scan: scan resolution, averaging, serial link. Target at least 10 Hz on the current board, with noise no worse than today's 8.4 counts sd, and document the trade-off curve.
- **Prototype a shear cell.** Put two to four two-layer cells at the edge of the dressing nearest the tube and run them through the same pulls (§3.2).
- **Write acceptance criteria as contrasts.** The current criterion ("≥ 5 of 7 HPull files cross −300") can be passed for the wrong reason, because a ground plane raises every signal, normal ones included. Write it as a rule with two sides, within one session. **Proposal:** at least 5 of 7 HPull files cross a lift gate that at most 1 of 5 Friction files and at most 1 of 5 Touch files cross. Freeze it before S1.
- **Make small software corrections, each with a test:**
  - latency measured from onset;
  - the CDC power-on check done in pF;
  - gates in capacitance units;
  - caveat 6 generated from data;
  - drift-monitor telemetry;
  - an honest statement of what gates the alarm (§8, §9).
- **Verify pad order on the live path.** Run the 1-by-1 sweep through `/ws/live_sensor`. This has been open since August.

| Work package | Content | Weeks |
|---|---|---|
| WP1.1 | LCR transfer measurement on the current rig, then again after each geometry change | 1, 5, 7 |
| WP1.2 | Body simulant and adhesive fixation; vacuum only for the simulant | 2–4 |
| WP1.3 | Motorised pull rig with force and displacement logging and hardware sync | 2–6 |
| WP1.4 | PSoC frame-rate profiling and noise trade-off | 2–4 |
| WP1.5 | Shear-cell prototype on the dressing edge | 4–9 |
| WP1.6 | S1–S3 collection per SOP v2, with contrast criteria frozen beforehand | 7–11 |
| WP1.7 | Session-CV report, served path first | 11–12 |
| WP1.8 | Live-path 1-by-1 pad-order sweep | 3 |
| WP1.9 | Software corrections listed in §9, each with a test | 2–10 |

**Gate 1 (end of month 3).** Every criterion is written down before S1.

1. The C0 and counts-to-pF transfer are measured with stated uncertainty, and the ≤ 25,000 contradiction is resolved in writing: which value was wrong, and on what evidence.
2. The session-CV served-path episode results are reported with Wilson intervals. Episode sensitivity for Peel and Vertical Pull is not lower than round 1 beyond the interval, and false alarms per recording are not higher.
3. The horizontal-pull contrast result is reported. If it passes, horizontal pull joins the claims. If it fails, it is recorded as a geometry limit and Phase 2 carries the shear channel.
4. The frame rate on the current board is either at least 10 Hz at no worse noise, or the root cause is documented and carried into the Phase 2 requirements.
5. The live-path pad order is verified.
6. The frozen parameters are unchanged (SOP v2 §7).

**Deliverables.** Transfer report; S1–S3 dataset; session-CV report; horizontal-pull contrast result; frame-rate study; shear-cell result; regenerated `Data/METRICS.md`.

**Risks and fallback.**

- Horizontal pull stays silent. This is the expected outcome (§3.2), and the shear channel moves into Phase 2.
- C0 turns out far above 50 pF. The chip choice changes.
- The PSoC cannot beat about 2 Hz. The Phase 2 board has to deliver the rate.

### Phase 2: Front end, from relative counts to calibrated capacitance (months 3–6)

**Goal as written.** An integrated AD7147 / AD7746 / FDC2214 converter array with < 1 fF resolution, complete elimination of zero-calibration, static tube localisation by dielectric shadow, and a serpentine FPC redesign.

**What holds.** A dedicated converter; serpentine traces and strain-relief slits; a power-on plausibility check; a contact map as a feature to test.

**What changes, and why.**

**1. Write requirements from measurements, not from datasheet headlines.** Resolution below 1 fF is not the constraint: the signals are pF-scale, and the device's problem is noise and range.

| Requirement | Proposed value | Where it comes from |
|---|---|---|
| Input range | At least the measured C0 plus parasitics, with ≥ 30% margin | Phase 1 transfer measurement |
| Noise | ≤ about 0.2 pF RMS per pad at the operating frame rate (about 12 counts on today's scale) | The served detector already drops to 27/40 at 30 counts sd; the bench floor is 8.4 counts |
| Frame rate | ≥ 20 Hz across all pads and shear cells | §3.5 |
| Temperature drift | Characterised over 20–40 °C and kept well below the tracker's blind-zone speed | §3.4 |
| RF immunity | Works through the IEC 61000-4-6 conducted test at the level IEC 60601-1-2 sets for the intended environment | EMC |
| Channel faults | Per-pad open or short detection raising a technical alarm | IEC 60601-1-8; §9 item 7 |
| Loss (optional) | Complex impedance (in-phase and quadrature) on at least some pads, if Phase 4 needs D | §3.1 |

**2. Know what each chip can do** (details in Appendix B).

| Chip | Chips needed for 25 pads | Range | Notes |
|---|---|---|---|
| AD7147 | 3 (13 inputs but 12 conversion stages per sequence), or 2 running two sequences per frame | ±8 pF around an offset of up to 20 pF | Cannot measure a 0–50 pF absolute range; single-electrode |
| AD7746 | 13 (2 channels each) | ±4 pF around up to 17 pF | Impractical at this channel count |
| FDC2214 | 7 (4 channels each) | Reaches 50 pF | 0.3 fF noise at 100 SPS. Resonant, so it needs an inductor per channel, and parasitics and temperature shift its frequency; absolute accuracy must be calibrated. |

PSoC self- and mutual-capacitance sensing stays a candidate if Phase 1 shows it can reach the rate and noise targets.

**3. Treat "absolute" as "calibrated".** That means on-board reference capacitors, per-channel calibration, and a temperature sensor. It delivers three things:

- a power-on plausibility check in pF, against an attached range measured first on the body simulant and then on volunteers;
- the slow-detachment monitor (§3.4);
- a contact-quality index that means the same on every patient.

It does not remove the per-patient baseline.

**4. Retrain; do not convert.** `convert_absolute_cdc_to_counts()` lets the round-1 model run unchanged on a new front end. That is a design change with no evidence behind it. Treat new hardware as a new sensor: collect bench sessions S4–S6 on it, retrain, re-verify and freeze.

**5. Put the alarm on the bedside unit.** The baseline tracker, classifier and annunciator should run on the device, not in a browser or behind a cloud tunnel. The dashboard becomes a secondary view. Port the trained model to C by code generation and show that its output matches the Python model's on the whole corpus. That is the embedded version of invariant 2: one classifier.

**6. Decide on shielding with data.** An active shield on the outer face of the dressing would make it less sensitive to hands and to the tube lying on top. That would cut touch false alarms, but it would also remove the press-side signal the model currently uses to catch horizontal pull. Test both on the phantom.

**7. Design for electrical safety from the start.** The dressing is an applied part on the patient's face. Plan patient isolation from USB and mains, leakage-current limits and battery safety now. Adding them after the design is frozen costs a redesign.

**Gate 2 (end of month 6).**

1. Bench-measured noise, drift and range meet the table above, with the body simulant connected.
2. A conducted-RF pre-compliance test passes, or its margin is documented.
3. A single-pad open or short raises a technical alarm within the specified time.
4. The power-on check works in pF on the simulant.
5. The 1-by-1 pad-order sweep passes on the new board.
6. The new-board dataset (S4–S6) is collected, and the model is retrained and frozen before Phase 3.

**Deliverables.** Requirements specification with IDs; board design files; verification report; retrained model with its generated metrics; the embedded classifier with its agreement test.

**Risks and fallback.**

- No single part meets range, noise and rate together. Use a hybrid: FDC2214 for range, plus a mutual-capacitance part for the shear cells.
- The embedded port does not match the Python model. Keep the bedside unit as a small single-board computer running the same Python.

### Phase 3: 3D anatomy and step height (months 6–9)

**Goal as written.** A facial phantom with R 15–50 mm, step blocks of 3/5/8 mm, viscoelastic hydrocolloid, and adaptive per-pad lift gates.

**What holds.** An anatomical phantom, step blocks, per-pad gates, an adhesive study.

**What changes, and why.**

- **Give the phantom a conductive core** (the body simulant from Phase 1) under a skin-like surface layer. Mount a tube stub of adult outer diameter (9–11.5 mm, as the documents state) in a realistic position at the mouth.
- **Extend the step set.** Add an 11–12 mm step (tube OD plus tape) to the 3/5/8 mm blocks, and hold one configuration out as the test set.
- **Treat the documents' C0 values as hypotheses to test.** Measure the tenting geometry (photographs or a profilometer) together with each pad's C map. Compare the result with the predicted 12–18 pF (tented) and 30–38 pF (flush). Both are unmeasured today.
- **Derive gates in capacitance units** on the training configurations, freeze them, and test them on the held-out configuration.
- **Choose the adhesive on data.** Compare hydrocolloid with a soft-silicone adhesive on four things:
  - how well each fills the wedge beside the tube;
  - how much C drifts over 24–48 h at controlled humidity;
  - peel force;
  - how gentle each is on skin.

  Hydrocolloid absorbs moisture and swells, so it may turn a static air gap into a slow drift (§3.4). Measure that before choosing it.
- **Reframe tube localisation as a contact and tenting map** (§3.1), and validate it against the photographed geometry.

**Gate 3 (end of month 9).**

1. On the held-out step configuration, the frozen per-pad gates meet the pre-registered episode sensitivity, with false alarms no worse than on the flat phantom.
2. The adhesive is chosen on measured drift, conformity and peel data.
3. The contact map agrees with the photographed tenting within a pre-set tolerance, or the claim is dropped.

**Deliverables.** Phantom design files; step-height dataset; gate specification in pF; adhesive comparison report.

**Risks and fallback.**

- Tented pads lose too much sensitivity for any gate to work. Change the dressing shape so no pad crosses the ridge; the strain-relief slits are the natural place to route around it.

### Phase 4: Healthy volunteers, confounders and lead time (months 9–12)

**Goal as written.** An IRB-approved study in 20 healthy volunteers, telling saliva and sweat apart by bio-impedance D, and OBS dual-stream verification of a lead time of at least 3.0 s.

**What holds.** Twenty volunteers as a pilot; facial movement, head rotation, cough and breathing tasks; synchronised video.

**What changes, and why.**

- **Ethics and design.** Submit to the institution's human research ethics committee by month 6, register the study in the Thai Clinical Trials Registry, and follow ISO 14155 principles. Nobody is intubated: a sham tube stub is taped to the face with the dressing, not inserted. That generates realistic dressing mechanics without the hazard.
- **Tasks:**
  - facial movement and mouth movement (patients grimace and mouth even while intubated);
  - head rotation to ±45°;
  - cough;
  - sweating (a warm room or light exercise);
  - artificial saliva applied near the lip corner;
  - hand-to-face gestures;
  - force-limited tugs on the stub at set angles, with a skin-safety stop.
- **Endpoints:**
  - false alarms per activity-hour (primary);
  - detection of scripted tugs, with confidence intervals;
  - lead time, measured and reported as found, not targeted;
  - skin tolerability;
  - adhesion over the session.
- **What N = 20 can and cannot show** (script). If tugs were independent:
  - 97 of 100 detected gives a 95% CI of 91.5–99.4%;
  - 0 false alarms in 200 activity trials puts the upper bound at 1.8%.

  They are not independent, because each person contributes several tugs, so report intervals clustered by subject. Twenty people is a pilot for variance and feasibility, not proof of sensitivity.
- **Moisture.** Measure C, and G or D where the front end supports it, under controlled wetting on the phantom first and then on volunteers. If no channel can measure loss, the moisture question is answered only by C and false-alarm counts, and the plan says so.
- **Lead time.**
  - Take onset and displacement times from 60 fps video, synchronised by a microcontroller-driven LED that writes a serial marker at the same moment.
  - Have two blinded annotators mark the events and report how well they agree.
  - Report the distribution of (displacement − alarm), negative values included.
  - The "3.2–5.6 s" figure stays out of every document until this measurement exists.

**Gate 4 (end of month 12).**

1. Ethics approval is in place and all 20 participants are completed.
2. False-alarm rate per activity-hour is reported with an interval clustered by subject.
3. Scripted-tug detection is reported with intervals.
4. The lead-time distribution is reported as measured.
5. No skin injury needed treatment.
6. The moisture effect size is measured, with a decision on whether a loss channel is needed.

**Deliverables.** Protocol and approval; volunteer dataset; confounder report; lead-time report.

**Risks and fallback.**

- Ethics approval takes longer than planned. Submit in month 6, and in the meantime run the protocol on the phantom.

### Phase 5: Quality, safety and regulatory (months 1–18; formal verification in months 12–18)

**Goal as written.** An IEC 62304 Class B/C architecture, ISO 14971 hazard analysis and FMEA, an ISO 13485 QMS, and mTLS/FHIR/HL7 integration with the bedside monitor.

**Start now, not in month 12.**

- **Design controls.** Keep a design history file, write requirements with IDs, and trace each one to a test. The existing guard suite is a good start on traceability. Add change control and a risk management file from month 1.
- **The hazard list must be longer than four.** It should cover at least:
  - missed alarms from each known blind spot: horizontal pull, slow detachment (§3.4), tented pads, the noise cliff, the CDC power-on check, a failed pad absorbed by quiescent recovery (§9);
  - alarm fatigue;
  - disconnection;
  - wrong pad order on the live path;
  - skin injury (MARSI and device-related pressure injury);
  - leakage current;
  - EMC interference from electrosurgery and defibrillation;
  - cybersecurity (the API serves recordings and accepts uploads);
  - audit-trail integrity;
  - use errors (misplaced patch, re-seeding while pressing);
  - automation complacency: staff watching less closely because a device is watching. A silent failure then costs more than having no device.

  Every control must map to a test.
- **IEC 62304 class.** The ventilator's disconnection alarms and SpO2 alarms work independently of this device, and the 2015 amendment to IEC 62304 lets such external controls count toward a lower class. So Class B is arguable. Argue it in the risk file. Whatever the outcome, build the alarm path to Class C rigour, so the classification decision cannot force rework.
- **Architecture.** `main.py` is a single 285 KB file that mixes training, evaluation, web API and CLI. Separate the alarm path (acquisition, baseline tracker, classifier, annunciator) as a small unit that is verified on its own. List every piece of third-party software it uses (numpy, scikit-learn, FastAPI and the rest; IEC 62304 calls this SOUP) and assess its risk.
- **Machine-learning controls.**
  - a locked model;
  - a data management plan;
  - pre-registration, as this project already does;
  - an FDA predetermined change control plan (PCCP; final guidance December 2024) if the model will be updated after release;
  - for the EU, the AI Act. A provisional agreement in May 2026 moved obligations for AI in regulated products to 2 August 2028, pending formal adoption; check its status before relying on it.
- **Alarms (IEC 60601-1-8).**
  - Map Level 3 to high priority and Level 2 to medium.
  - Add technical alarms: disconnection, pad fault, noise outside the validated range, slow drift.
  - The current browser tones are ad hoc oscillators, not IEC 60601-1-8 alarm signals; the 2020 amendment to that standard revised the alarm sounds.
  - Label CPRI plainly as a heuristic index until it is validated. It maps class probabilities and delta magnitudes to 0–100% by hand-set formulas.
- **Network.** Export data with FHIR Observation, HL7 v2 or the IHE PCD profiles. The alarm sounds at the bedside first. A central-station alarm is a distributed alarm system with its own requirements, and is out of scope within 24 months. Secure network features under IEC 81001-5-1 (mTLS, authentication, audit logging, a software bill of materials).
- **Electrical safety and EMC.** Run pre-compliance on the new board in months 5–6. Have the frozen design tested by an accredited lab before the ICU study; hospital biomedical engineering and the ethics committee will ask for the reports.
- **Biocompatibility.** Do an ISO 10993-1 evaluation for prolonged skin contact (up to 30 days) near the lips: at least cytotoxicity, sensitisation and irritation. Prefer materials that already have a record of skin contact.
- **Usability (IEC 62366-1).** Cover applying the dressing at the bedside, re-seating it, what the nurse sees at power-on (the plausibility status), and the response to an alarm.
- **Regulatory route.** Thailand classifies devices into four classes (Ministry of Public Health notification, 14 November 2020, under the Medical Device Act B.E. 2551). The EU uses the MDR classification rules; the US decides between 510(k) and De Novo through a pre-submission. Classify with a regulatory professional and consult early. Until then the device is for research use only.

**Gate 5 (end of month 18).**

1. Design freeze.
2. Verification complete against the requirements.
3. Risk management file complete, with every control verified.
4. Summative usability test in simulated use.
5. Electrical-safety and EMC reports.
6. Security documentation.
7. Clinical investigation plan approved by ethics (and by the regulator if needed); hospital engineering acceptance.

**Deliverables.** Design history file; risk management file; software documentation per IEC 62304; test reports; clinical investigation plan.

**Risks and fallback.**

- Nobody on the team holds quality and regulatory skills. Bring in an advisor by month 2, and consider a manufacturing partner or spin-off, because ISO 13485 certification needs a legal manufacturer.

### Phase 6: First ICU clinical investigation (months 18–24)

**Goal as written.** A prospective observational trial at 3 centres, 100 patients, 4,800 monitoring hours, sensitivity ≥ 95% and fewer than 5 false alarms per bed per day.

**Re-scoped as a feasibility study.** Prospective, observational and device-blinded: the device records its alarms but does not show them, and standard care is unchanged. That removes the ethical conflict between measuring lead time and responding to alarms.

**Primary endpoints, all estimable at 4,800 h:**

- false-alarm burden per patient-day. The < 5 per bed-day proposal is a sensible ceiling to pre-register; the precision is in §3.7;
- the fraction of monitoring time with a valid signal;
- skin safety: MARSI by type (skin stripping, tension blister, skin tear, irritant or allergic dermatitis, maceration, folliculitis) and device-related pressure injury by NPIAP stage;
- adhesion over 48 h.

**Secondary endpoints:**

- detection of video-annotated tube-handling events: hands on the tube or dressing, tape pulls, visible tube movement. These happen far more often than extubations, so sensitivity and positive predictive value with intervals become estimable;
- every unplanned extubation reported as a case series with the full sensor trace (about 1.8 expected; §3.7).

**Population.** RASS +3 is defined as "pulls or removes tube(s) or catheter(s)", so the proposed range of −2 to +2 excludes, by definition, the behaviour the device exists to catch. Include agitated and delirious patients, with appropriate safeguards.

**Endpoint definitions.** "Irreversible cuff emergence" cannot be seen from outside. Define displacement by the tube's depth mark at the lips, with a threshold agreed with the clinical team before the study starts.

**Consent and data.** Intubated patients cannot consent, so plan for surrogate or deferred consent. Continuous video needs its own consent and privacy plan. Handle data under Thailand's PDPA.

**Sites.** Start at one site and add sites only after the first 20 patients' data have been reviewed for safety and data quality.

**Beyond month 24.** Plan an event-driven pivotal study in a population enriched for risk, or a regulator-agreed package that combines bench and simulated-use sensitivity with clinical false-alarm and safety data. Decide which in pre-submission meetings.

**Gate 6 (month 24).**

1. Feasibility endpoints reported with intervals.
2. Case series of unplanned extubations.
3. Go or no-go decision on the pivotal design, informed by early regulator feedback.

---

## 5. Schedule, dependencies and critical path

| Months | Bench and physics | Hardware | Software and ML | Clinical and ethics | Quality and regulatory |
|---|---|---|---|---|---|
| 1–3 | LCR transfer; body simulant; motorised rig; S1–S3 | PSoC frame-rate study; shear-cell prototype | §9 corrections; session CV; onset-based latency | Choose clinical lead and site 1 | Design controls, risk file, advisor on board |
| 3–6 | Re-measure C0 after geometry changes | Converter requirements, board, pre-compliance EMC | Retrain on S4–S6; embedded classifier | Write the Phase 4 protocol; submit by month 6 | Requirements with IDs; hazard analysis v1 |
| 6–9 | Face phantom, steps, adhesive drift | Revise the board if Gate 2 fell short | Gates in pF; drift monitor; technical alarms | Ethics review of Phase 4 | Usability formative; biocompatibility plan |
| 9–12 | Confounder bench work | Freeze candidate hardware | Freeze model for volunteers | Run the volunteer study (N = 20); draft the ICU protocol | Hazard analysis v2 with volunteer data |
| 12–18 | Remaining verification | Design freeze; accredited safety and EMC tests | Verification per IEC 62304; security | Submit ICU protocol (month 12); site setup (months 16–18) | Design history file and risk file complete; Gate 5 |
| 18–24 | Support | Support | Monitoring; data management | Enrol and follow up; analyse in month 24 | Pre-submission meetings; plan the pivotal study |

**Critical path:** C0 and transfer measured → converter requirements → new board → data on the new board → frozen design → electrical-safety and EMC reports → ethics approval → enrolment. A slip at the start moves the ICU study one-for-one. The single most valuable action in month 1 is the transfer measurement, which takes about a day.

---

## 6. Standards map

| Standard | What it governs here | When it matters | Current state |
|---|---|---|---|
| ISO 13485 | Quality system and design controls | From month 1 | Not started; the pinned stack, tests and generated metrics are useful groundwork |
| ISO 14971 (with ISO/TR 24971) | Risk management | From month 1 | Four hazards drafted in the roadmap; needs expansion |
| IEC 62304 (+A1:2015) | Software life cycle and safety class | From month 1; formal verification months 12–18 | Not assessed |
| IEC 60601-1 | Basic safety and essential performance, applied part | Board design (month 3) to tests (months 12–18) | Not started |
| IEC 60601-1-2 | EMC, including conducted RF immunity at the sensing frequencies | Pre-compliance months 5–6; tests months 12–18 | Not started |
| IEC 60601-1-8 (+A2:2020) | Alarm priorities, signals, technical alarms | Phase 2 onward | Tones and levels are ad hoc |
| IEC 62366-1 | Usability engineering | Formative from month 6, summative by month 18 | Not started |
| ISO 10993-1, -5, -10, -23 | Biocompatibility of materials touching skin | Adhesive choice (Phase 3) | Not started |
| ISO 14155 | Good clinical practice for device investigations | Phases 4 and 6 | Not started |
| IEC 81001-5-1 | Security across the health-software life cycle | Phase 5 | An access key and upload limits exist |
| HL7 FHIR, HL7 v2, IHE PCD, IEEE 11073 SDC | Data exchange; central-station alerts | After month 18, secondary | Not started |
| Thailand MoPH classification (2020); EU MDR; US FDA pre-submission | Market route | Months 12–24 | Not started |

---

## 7. Project risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Horizontal pull stays invisible after Phase 1 | High (§3.2) | High | Shear cell or tube-position channel planned in Phase 2 |
| C0 far from the chip ranges assumed | Medium | High | Measure in week 1; choose the chip after |
| The frame rate cannot reach 20 Hz at acceptable noise | Medium | High (no lead time) | Profile in Phase 1; make the rate a hard Phase 2 requirement |
| The model does not generalise across sessions or people | Medium | High | Session CV, then subject CV; retrain per hardware generation |
| Noise in the ICU exceeds the bench by 3.6× or more | Medium | High (sensitivity collapses, §2.2 item 4) | Noise requirement; EMC pre-compliance; noise telemetry wired to a technical alarm |
| Ethics timelines slip | Medium | Medium | Submit early (month 6 and month 12); phantom work fills the gap |
| No regulatory or quality expertise on the team | High | High | Advisor by month 2 |
| Adhesive injures skin over 48 h | Low–medium | High | Materials with skin-contact history; Phase 4 tolerability data |
| Two agent sessions edit the repository at once | Medium | Medium | One session at a time (AGENTS.md); review diffs before commit |
| Documents drift from the code again | High (§8 lists 15 instances) | Medium | Generated blocks for every figure; claims register reviewed at each gate |

---

## 8. Corrections register: claims in the repository that should change

These are not edits made by this review. They are the list to fix, in the owner's order.

| # | Where | Claim | What the evidence says | Suggested fix |
|---|---|---|---|---|
| 1 | Progress report §5.3; OBS guide §5 timeline; SUPERVISOR_DEFENSE_EXECUTIVE_DECK.md slide 9 | Lead time "3.2–5.6 s" (the progress report calls it a preliminary result) | No lead time has been measured; round 1 has no video or onset times. 5.60 s is the time-to-alarm floor counted from file start (§3.5). SOP v2 §6 says it correctly: a 3.2 s warning cannot be measured without synced video. | Remove, or label as a hypothesis to be measured in Phase 4 |
| 2 | ALGORITHM_JUSTIFICATION §9 | "≥ 8/10 peel recordings must reach ≤ 25,000 counts"; suction is the "leading hypothesis" for never reaching the spec | Contradicts §7.4 of the same document, METRICS caveat 3 and AGENTS.md: the spec is unreachable by arithmetic, and SOP v2 §8 already replaced this criterion | Delete; point to SOP v2 §8 |
| 3 | ALGORITHM_JUSTIFICATION §5 table | 5 of 7 votes at 7.3% false alarms per recording and 13.0/h; 3 of 5 at 12.2% | METRICS.md (2026-09-23) gives 9.8% and 18.1/h, and 14.6% | Copy the rows from METRICS.md again, or generate them |
| 4 | ALGORITHM_JUSTIFICATION §1 leg 3 and §3.5 | The classifier is "wrapped by hard gates (noise, lift, peel persistence)", so a model failure "cannot silently invent detections" | Only the 60-count noise gate stands in front of the model. The lift gate and peel tracker are reported beside it and do not affect the alarm level | Say exactly that |
| 5 | Roadmap §2.2, ALGORITHM_JUSTIFICATION §2.1 and §8, progress report §1.1 and §4.2, `detect_static_tube_localization` docstring | Skin εr ≈ 50–80 against a tube at 2.8 | At 32–250 kHz, dry skin is about 1,100 and wet skin 7,000–25,000, and tissue conducts (§3.1) | State the conductor-and-gap model |
| 6 | Roadmap §2; ALGORITHM_JUSTIFICATION §8; Hardware deck; progress report §3.2 | A 0–50 pF range for AD7147 / AD7746 / FDC2214 | Only FDC2214 reaches it. AD7147 reads ±8 pF (offset ≤ 20 pF); AD7746 reads ±4 pF (≤ 17 pF) | Correct it; choose the chip from the measured C0 |
| 7 | Roadmap §2.1; progress report §3.4; ALGORITHM_JUSTIFICATION §8 | An absolute converter "eliminates zero-calibration" | It makes the zero checkable. The current CDC path re-zeroes on frame 0, and its power-on check reports "attached" for 3–45 pF | Reword; fix the code (§9 items 1–2) |
| 8 | Progress report §3.3; PLAN_SUPERVISOR_FEEDBACK §2.1; ALGORITHM_JUSTIFICATION §8 ("the model does not change") | The model needs no retraining on the CDC board | A new front end is a new sensor; nothing measures the transfer | Retrain and re-verify (Phase 2) |
| 9 | Roadmap §1.2 ("negative lift deltas … for pure shear motions"); Hardware deck (line 213); PLAN_SUPERVISOR_FEEDBACK §3.1 | A ground plane gives lateral motion an overlap change or a lift signal | Not for a continuous plane (§3.2) | Reword; add the shear-cell option |
| 10 | Roadmap §1.2; METRICS caveat 6 | Horizontal pull at −71.2 / +451.9 counts (roadmap) versus −64 / −161 / +456 (caveat 6) | The same finding under different calibrations: Kalman −71.2, static −111.4, served −74.8; the caveat 6 numbers are a hard-coded string | Generate caveat 6 from data and name the calibration |
| 11 | Roadmap §5.2, HAZ-02 | Residual risk "Low (< 5 false alarms/day)" | No ICU data exists; a residual risk cannot be rated before it is measured | Mark as "to be estimated in Phase 6" |
| 12 | Roadmap §5.1 | "Zero invented patient identity" amounts to GDPR/HIPAA compliance | The invariant prevents fabricated identities. It is not a privacy programme; Thailand's PDPA applies to real patient data | Separate the two |
| 13 | Roadmap §6.2 | MARSI "stage ≥ 2" | MARSI is classified by type. Stages belong to device-related pressure injury (NPIAP) | Use both correctly (Phase 6 endpoints) |
| 14 | Roadmap §6.1–6.2 | RASS −2 to +2; lead time measured to "cuff emergence" | RASS +3 means pulling out tubes. Cuff emergence cannot be seen from outside | Widen the RASS range; define displacement by the depth mark |
| 15 | Roadmap §2.2; progress report §3.4 | Tube localisation "with zero operator intervention", confirming seating | Never run on an absolute board or a phantom | Claim it only after Phase 3 |

---

## 9. Code-level findings

Each item is reproduced by `scripts/translation_plan_checks.py` or can be read directly in the code. Items 1, 2, 7, 8 and 9 sit on paths the published evaluation does not exercise, which is why nothing caught them. Items 3–6 are on the published path: F10 and the device tracker shape the served figures, item 5 defines the published time to alarm, and caveat 6's text is stored in `metrics.json`. None of them makes a published number irreproducible. They change what the numbers mean.

1. **The power-on check is blind on the CDC path.** `LivePipeline` converts the first CDC frame to exactly 28,000 counts on every pad, so `seed_plausibility()` reports `attached_band` for any power-on value. The script tried 3, 5, 12, 30 and 45 pF: all read `attached_band`. On the counts path the same check works: 5 pF reads `below_band` and 45 pF reads `above_band`. A patch powered up in air and applied afterwards reads as a +1,496-count press.
2. **Adaptive gates barely adapt** (§3.3). In counts mode they are −298 against −311. In pF mode they are 13–31 times too tight, and on the live CDC path they are uniform at −308. They feed only the peel tracker and the console's patch-integrity readout, not the alarm.
3. **F10 is close to the identity on raw counts** (§3.3): it rescales by at most about 4% between pads.
4. **The Kalman tracker has a slow-detachment blind zone** (§3.4): 0.124 pF/s on the device path, and 0.095 pF/s offline at bench noise (0.065–0.175 across the allowed noise range).
5. **Time to alarm is measured from file start, warm-up included** (`_episode_figures`), and its floor is 5.60 s (§3.5). Measure latency from an annotated onset.
6. **Caveat 6 is a literal.** `_caveats()` promises that "every figure below is now measured from the dataset", but the horizontal-pull numbers are typed into a string.
7. **A failed pad is absorbed without an alarm.** When one electrode steps −1,500 counts and stays still, quiescent recovery engages after 2.8 s. The pad's delta is back inside the noise gate after 9.0 s, and nothing flags a fault. The docstring calls this a known residual risk for a genuine single-pad lift. For a hardware fault it is a loss of coverage, and it needs a technical alarm.
8. **Channel faults are only partly detected.** A NaN or negative value on any pad marks the whole frame as disconnected. But the range checks (< 3,000 or > 50,000 counts) use `np.all`, so they fire only when every pad fails together. A single pad that saturates above 50,000 counts is silently replaced by its baseline: its delta reads 0 and nothing is flagged. A single pad stuck low is re-zeroed by quiescent recovery (item 7). Both belong on the hazard list.
9. **CPRI is a heuristic.** It maps probabilities and delta magnitudes to 0–100% by hand-set formulas (`cpri()`). Until it is validated, label it as a display index, not a risk estimate.

---

## 10. Decisions needed from the supervisor

1. **Phase 6 scope.** Accept a feasibility study with false-alarm, signal-quality, skin-safety and tube-handling endpoints, with the pivotal sensitivity study after month 24?
2. **Bench fixation.** Adhesive on a skin simulant, with suction holding only the simulant (§3.6)?
3. **Converter choice.** A decision at month 3, based on the measured C0 and transfer, including whether a loss or impedance channel is required?
4. **Shear sensing.** Fund a two-layer shear cell or a tube-position channel in Phase 2?
5. **Where the alarm runs.** Move the alarm decision onto the bedside unit, with the dashboard as a secondary view?
6. **Headline figure.** Lead with the served line (the device) rather than the offline line?
7. **People.** Who is the clinical lead, who is the quality and regulatory advisor, and which ICU is site 1?

---

## Appendix A: Output of `scripts/translation_plan_checks.py`

| Check | Value |
|---|---|
| Evidence time for 6 votes at 0.56 s per frame | 3.36 s |
| Earliest alarm counted from file start | 5.60 s |
| Anomaly files alarming exactly at the floor | 25/40 offline; 12/39 served (served median 7.28 s) |
| Bench noise, median across N_base pads | 8.4 counts sd |
| Kalman steady-state gain, device path (r = 40) / offline at bench noise | 0.0347 / 0.0264 |
| Fastest ramp still absorbed as drift | Device: 4.17 counts/frame = 7.44 counts/s = 0.124 pF/s. Offline: 3.17 counts/frame = 5.66 counts/s = 0.095 pF/s (0.065–0.175 across the allowed noise range) |
| Ramp streamed through `LivePipeline` at 0.8× / 1.2× the device limit | deepest delta −92.7 counts (absorbed) / runs away past the lift gate |
| Deepest round-1 peel delta (Kalman) | −902.4 counts, 15.1 pF |
| Time to absorb that peel at the limit | 121 s device; 159 s offline (86–233 s) |
| Sensitivity study, events needed (first n reaching 80% power / n from which it stays there) | 41 / 48; 100 / 114; 54 / 54; 142 / 173 (the four goals in §3.7) |
| CDC power-on at 3 / 5 / 12 / 30 / 45 pF | `attached_band` for all five |
| Counts power-on at 5 / 30 / 45 pF | `below_band` / `attached_band` / `above_band` |
| Adaptive gate, counts mode, 35 pF / 15 pF | −311.3 / −298.1 counts |
| Adaptive gate, pF mode, 35 pF / 15 pF | −0.38 / −0.16 pF, which is −22.7 / −9.6 counts |
| Lift gate / noise gate in pF | −5.01 / 1.00 pF |
| Live CDC adaptive gates | all −308.0 |
| Horizontal pull: median deepest, deepest, median max, files over gate | static −111.4 / −212.4 / +442.9 / 0; Kalman −71.2 / −201.5 / +451.9 / 0; served −74.8 / −202.5 / +452.2 / 0 |
| Self-extubations expected in 200 ventilator-days | 1.79 (meta-analysis) / 1.76 (Safe-ICU); P(0) = 0.168 / 0.172 |
| Single-pad fault (−1,500 counts, still) | recovery at 2.8 s; back inside the noise gate at 8.96 s; not flagged as disconnection |
| Holding force over 90 × 120 mm | 162 / 432 / 648 N at −15 / −40 / −60 kPa |

## Appendix B: Converter facts

| Part | Channels | Range | Resolution or noise | Rate | Principle |
|---|---|---|---|---|---|
| AD7147 (Analog Devices) | 13 inputs; 12 conversion stages per sequence | ±8 pF, with offset compensation up to 20 pF (0.32 pF steps) | Femtofarad, 16-bit | 9 ms for all 13 inputs | 250 kHz excitation, single-electrode |
| AD7746 (Analog Devices) | 2 | ±4 pF changing; up to 17 pF common-mode | 4 aF resolution; 4 fF accuracy | 10–90 Hz | Sigma-delta |
| FDC2214 (Texas Instruments) | 4 | Up to 250 nF (at 10 kHz with a 1 mH inductor) | 28-bit; 0.3 fF noise floor at 100 SPS | Up to 4.08 kSPS | Resonant LC; sensor frequency 10 kHz–10 MHz |

None of the three reports loss or dissipation. A loss measurement needs a complex-impedance front end.

## Appendix C: Sources

- Li P, Sun Z, Xu J. Unplanned extubation among critically ill adults: a systematic review and meta-analysis. *Intensive Crit Care Nurs* 2022. https://www.sciencedirect.com/science/article/abs/pii/S0964339722000222
- Guillemin J, et al. Prospective multi-center evaluation of the incidence of unplanned extubation and its outcomes in French intensive care units: the Safe-ICU study. *Anaesth Crit Care Pain Med* 2024;43(5):101411. https://www.sciencedirect.com/science/article/pii/S2352556824000699
- Gabriel S, Lau RW, Gabriel C. The dielectric properties of biological tissues: III. Parametric models for the dielectric spectrum of tissues. *Phys Med Biol* 1996;41:2271. Table 1 parameters, as reproduced at https://mriquestions.com/uploads/3/4/5/7/34572113/s_gabriel_1996_phys._med._biol._41_003.pdf
- Analog Devices AD7147 data sheet: https://www.analog.com/media/en/technical-documentation/data-sheets/AD7147.pdf
- Analog Devices AD7746 product page: https://www.analog.com/en/products/ad7746.html
- Texas Instruments FDC2214 product page: https://www.ti.com/product/FDC2214
- Medtronic SonarMed airway monitoring system: https://news.medtronic.com/SonarMed-TM-Airway-Monitoring-System
- FDA, Marketing Submission Recommendations for a Predetermined Change Control Plan for AI-Enabled Device Software Functions (final guidance, December 2024): https://www.fda.gov/regulatory-information/search-fda-guidance-documents/marketing-submission-recommendations-predetermined-change-control-plan-artificial-intelligence
- IEC 60601-1-8 Amendment 2 (2020), new alarm sounds: https://array.aami.org/content/news/updated-iec-60601-1-8-breaks-new-ground-development-alarm-sounds
- EU AI Act omnibus, provisional agreement of May 2026: https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/
- Thailand MoPH notification on risk classification of medical devices (14 November 2020): https://en.fda.moph.go.th/media.php?id=482372261249163264&name=20201114+Notification+of+the+Ministry+of+Public+Health+Re+Risk+Classification+of+Medical+Devices.pdf
- Repository sources: `Data/METRICS.md` and `Data/metrics.json` (2026-09-23), `Data/served_path_benchmark.json`, `docs/ENGINEERING_REVIEW_2026-09-23.md`, `docs/DATA_COLLECTION_SOP_v2.md`, `docs/PLAN_SUPERVISOR_FEEDBACK_EN.md`, `AGENTS.md`, `main.py`.
