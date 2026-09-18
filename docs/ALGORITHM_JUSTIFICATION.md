# Algorithm Justification — Smart Dressing Self-Extubation Early Warning

**Scope.** This document states the theoretical and empirical grounds for every stage of the detection pipeline: why capacitive delta signals separate the five canonical scenarios, why each signal-processing stage exists, why the chosen classifier is defensible for a brand-new data modality with no public benchmark, and what the honest limits of the current evidence are.

**Ground rule.** Every number in this document is machine-generated (`Data/METRICS.md` via `python main.py --report`, and `Data/five_scenarios_evaluation.json` via `python scripts/evaluate_5_scenarios.py --mode oof`, run 2026-09-16). Nothing is retyped by hand or extrapolated.

---

## 1. The no-benchmark problem, and how this project answers it

The 25-channel capacitive smart dressing produces a data modality with no public benchmark dataset, no prior published corpus, and no standard evaluation protocol. A model cannot therefore be justified by leaderboard comparison. Justification instead rests on three independent legs:

1. **Physics first.** Each of the five scenarios has a predicted capacitive signature derived from the parallel-plate model, and the measured corpus confirms or refutes each prediction (Section 2). Where the physics predicts *no* signal (horizontal pull), that is reported as a limitation, not hidden.
2. **Held-out validation on our own corpus.** All published figures are out-of-fold: leave-one-file-out cross-validation (LOFO) over 81 recordings, so no recording is ever scored by a model that saw it. Small-sample honesty is enforced with Wilson 95% confidence intervals on every proportion.
3. **Model-independent physics gates.** The learned classifier is wrapped by hard gates derived from measured signal physics (noise gate, lift gate, peel persistence), so a model failure mode cannot silently invent detections that the raw signal does not support.

This is the structure a reviewer should audit: prediction → measurement → held-out validation → independent guard.

---

## 2. Sensing physics and the measured signature of each scenario

### 2.1 The capacitor model

Each pad forms a capacitor whose value follows the parallel-plate relation C = ε₀ εᵣ A / d. The dominant variables are the effective dielectric constant εᵣ of whatever occupies the field volume (skin ≈ 50–80, PVC/silicone tube ≈ 2.8, air ≈ 1) and the effective coupling distance d. The bench sensor reads ≈ 28,000 counts attached and quiescent (nominal C₀, KES 2025 §2.1), at a resolution of 59.85 counts/pF.

Two directions of change follow directly:

- **Detachment / lift** replaces high-εᵣ contact with an air gap: d increases, εᵣ drops → **negative delta** (capacitance loss).
- **Touch / press** adds conductive-dielectric mass and reduces d → **positive delta** (capacitance gain).

Every downstream design decision exploits this sign asymmetry: the dangerous direction (dressing leaving the skin) is negative, and the benign direction (contact) is positive.

### 2.2 Measured signatures, out-of-fold, 81 recordings

| Scenario | Files | Median deepest Δ (counts) | Median max Δ (counts) | Lift gate ≤ −300 crossed | Annunciator result (95% CI) |
|---|---|---|---|---|---|
| 1. Baseline (resting) | 5 | −33.8 | +42.0 | 0/5 | FA 0/5, 0.0% [0.0–43.4] |
| 2. Touching (touch + press) | 21 | −806.8 | +3037.0 | 18/21 | FA 1/21, 4.8% [0.8–22.7] |
| 3. Friction (rubbing) | 10 | −76.2 | +304.8 | 0/10 | FA 0/10, 0.0% [0.0–27.8] |
| 4. Pulling (all three modes) | 30 | −214.8 | +508.5 | 13/30 | **Sens 30/30, 100% [88.6–100]** |
| — 4a. Vertical pull | 10 | −770.9 | +555.3 | 10/10 | Sens 10/10, 100% [72.2–100] |
| — 4b. Horizontal pull | 10 | −71.2 | +451.9 | **0/10** | Sens 10/10, 100% [72.2–100] |
| — 4c. Power pull | 10 | −159.7 | +608.0 | 3/10 | Sens 10/10, 100% [72.2–100] |
| 5. Peeling (detachment) | 10 | **−869.3** | +43.7 | 10/10 | **Sens 10/10, 100% [72.2–100]** |
| Ref. Normal Mix | 5 | −544.3 | +2784.8 | 3/5 | FA 1/5, 20.0% [3.6–62.4] |

Source: `Data/five_scenarios_evaluation.json`, mode `oof`, 2026-09-16.

Reading of the table, scenario by scenario:

- **Baseline** sits inside ±75 counts — this measured envelope is what defines the noise gate (Section 3.3).
- **Touching/Press** is dominated by the positive side (+3037 median max), exactly as the physics predicts for added coupling. Its negative excursions are press-release rebound and edge-lift under the finger, which is why a lift-gate crossing alone must never raise an alarm (18/21 normal touch files cross it).
- **Friction** is the quietest active class in both directions (−76 / +305): rubbing modulates coupling without breaking it.
- **Vertical pull and peel** produce deep, sustained negative excursions (−771 and −869 median deepest; 10/10 gate crossings each) — the direct dielectric signature of the dressing leaving the substrate.
- **Horizontal pull is the honest exception.** It produces *no* lift signal (median deepest −71, 0/10 gate crossings — quieter than Friction, a normal class). What moves is the positive/contact side (median max +452). The classifier detects it, but on a press-like proxy, not on a detachment signature. This is stated as a limitation in Section 7 and drives the round-2 rig upgrade (Section 9).

The separation that the classifier exploits is therefore not incidental: sign, depth, spatial extent, and persistence of the delta field differ between classes for stated physical reasons, and the measured corpus confirms each of them.

---

## 3. Signal-processing chain — stage-by-stage justification

Order of operations per frame: raw counts → baseline estimation → delta → scale normalization → noise gate → feature extraction → classifier → temporal annunciator.

### 3.1 Baseline estimation (static seed + Kalman drift tracking)

Capacitance drifts with temperature, humidity, and adhesive relaxation, so a fixed offset is wrong within minutes. The pipeline seeds a static baseline from the first `k = 5` quiescent frames (`static_baseline`, `KALMAN_WARMUP = 5` frames held at Level 0), then tracks slow drift with a per-pad Kalman filter. The corpus validates the warmup assumption by construction: every recording opens with a quiescent segment before the named behaviour begins. The Kalman innovation gate prevents the baseline from absorbing genuine events: fast excursions are classified, slow drift is followed.

The SOP enforces the premise instrumentally: `--audit` rejects any recording whose baseline segment swings more than `BASELINE_MAX_SWING = 100` counts.

### 3.2 Scale-normalized delta

Deltas are normalized as Δ̃Cᵢ = (ΔCᵢ / C₀,ᵢ) × 28000. On the bench corpus (C₀ ≈ 28,000) this is the mathematical identity, so no published number changes; on an arbitrary future mounting it makes every threshold a *fraction of that pad's own baseline* rather than an absolute count, giving scale invariance across mountings and sensor revisions without retuning.

### 3.3 Noise gate (±60 counts)

`NOISE_GATE_COUNTS = 60` sits just above the measured baseline envelope (extreme deepest −41, extreme max +75 across the 5 baseline files; Section 2.2 row 1). Its justification is dual:

- **Physical:** below this amplitude the signal is indistinguishable from ambient drift, so no classification should be attempted.
- **Statistical:** every recording's opening baseline segment carries the *file's* label (a peel file's quiet lead-in is labelled "peel"), which is known frame-level label noise. The gate suppresses exactly those frames before they reach the classifier, so the model is never asked to act on physically-quiet frames however they are labelled.

### 3.4 Feature extraction (25 + 9 = 34 features)

Per frame: the 25 per-pad deltas (spatial pattern) plus 9 aggregate statistics — min, max, mean, std, and pad-count exceedances at Δ ≤ −300, ≤ −600, ≤ −1000, Δ ≥ +300, ≥ +1000. The aggregates encode depth and extent of lift and contact directly in the units the physics gates use; the raw pads preserve spatial arrangement (which pads, how many, how contiguous).

The 9-statistic-only variant was measured and rejected: at the same alarm budget it detects **70.0%** of episodes against **100.0%** for the 34-feature set (LOFO, 7-of-6 operating point). The spatial channels are load-bearing, not decorative.

### 3.5 Independent physics gates

The peel detector requires `PEEL_MIN_PADS = 3` simultaneous pads below threshold, whole-grid mean below `PEEL_MEAN_GATE = −150` counts, persisting `PEEL_PERSIST_FRAMES = 3` (1.68 s) — jointly demanding that a "detachment" claim be deep, spatially extended, and sustained, which single-pad noise, spikes, and press-release transients are not. The lift gate (`LIFT_GATE_COUNTS = −300`) is reported beside every model decision and audited per corpus (`--audit`). These gates are not features of the model; they are checks *on* the model, which is precisely the guard a benchmark-free modality needs.

---

## 4. Classifier choice

**Chosen: HistGradientBoostingClassifier, max_iter=150, max_depth=8, class_weight="balanced", on the 34 features.**

Justification against measured alternatives (LOFO over the 81 recordings, identical folds):

| Model | File-level accuracy | Episode sensitivity @ 7-of-6 (7.8 alarms/h) |
|---|---|---|
| RandomForest + 9 statistics (v6.2) | 93.83% | 70.0% |
| RandomForest + 34 features | 96.30% | 87.5% |
| **HistGradientBoosting + 34 features** | **97.53%** | **100.0%** |

Why a gradient-boosted tree ensemble is the right model class here, not merely the winning one:

- **Tabular, small-n, threshold-structured data.** 3,349 frames, 34 physically-meaningful features whose class boundaries are approximately axis-aligned thresholds (depth gates, pad counts). Tree ensembles represent exactly this geometry; they need no feature scaling and are robust to the heavy-tailed count distributions.
- **Sample efficiency.** With classes of n=5 and n=10 *files*, high-capacity models are the wrong risk profile. Boosted trees with bounded depth carry an explicit complexity budget.
- **Determinism and auditability.** On this corpus the estimator is deterministic (seed spread exactly 0.00), so every published number reproduces bit-for-bit via `python main.py --verify-metrics`. For a safety device, reproducibility is part of the justification.
- **The sequence-model alternative was measured, not assumed away.** Multi-seed comparison: BiLSTM 0.9531 ± 0.0230 vs RF 0.9518 ± 0.0038 — no significant advantage, at 6× the seed variance, and the corpus physically cannot feed it: BiLSTM windows of 3.36 s against a median Vertical-Pull recording of 6.7 s leave a handful of windows per file. The single-seed "BiLSTM 0.9658 beats RF 0.8621" figure from v6.0 was an artifact of one hard-coded CV seed and mismatched calibration, and is retired. Temporal integration is instead done *after* the classifier, where it is transparent (Section 5).
- **Frame-level probabilities are model-only.** An invariant test (`t_no_handcoded_proba`) verifies that no hand-coded heuristic can inject probabilities into `classify_deltas()`; the serving path and the evaluation path score the same model.

Headline file-level result: **97.53%** accuracy (79/81, Wilson 95% CI [91.4, 99.3]; bootstrap over files [93.8, 100.0]), macro F1 0.9612.

---

## 5. Temporal decision layer (annunciator)

Raw frame predictions are debounced by a voting annunciator: alarm requires **6 of the last 7 frames** to agree, and holds for **9 frames (5.04 s)**. This converts frame-level evidence into episode-level decisions — the clinical unit — and is the mechanism that buys specificity without touching the model:

| window | votes | sensitivity | FA/recording | alarms/hour | latency |
|---|---|---|---|---|---|
| 5 | 3 | 100.0% | 12.2% | 20.7 | 3.92 s |
| 7 | 5 | 100.0% | 7.3% | 13.0 | 5.04 s |
| **7** | **6** | **100.0%** | **4.9%** | **7.8** | **5.60 s** |
| 5 | 5 | 97.5% | 2.4% | 5.2 | 5.04 s |

Operating point (7-of-6, hold 9) at episode level, out-of-fold: **sensitivity 100.0% [91.2–100.0], false alarm per recording 4.9% [1.3–16.1], 7.8 alarms/hour, median time-to-alarm 5.60 s, 1.00 alarm onsets per detected event, zero missed events.** The point is a stated clinical trade-off, not a tuned hyperparameter: a retrospective ICU cohort reports a median ≈ 5 alarms/hour of existing burden with no published "safe" threshold (Sci Rep 2022, s41598-022-26261-4), so the default is justified as roughly doubling existing burden while keeping sensitivity at 100% with zero repeat-alarm chatter. It was tuned on round-1 data and is frozen for round-2 validation.

---

## 6. Generalizability across the five scenarios

The requirement is that the algorithm not depend on incidental conditions of any one scenario. The evidence:

1. **All figures are out-of-fold** (LOFO), so every scored recording is unseen by its scoring model.
2. **All five scenarios are evaluated under one frozen configuration** — one model, one operating point, no per-scenario tuning — and the per-scenario table in Section 2.2 is generated by a single script from the same predictions used for the headline metrics.
3. **Small-n honesty is structural.** Every proportion carries a Wilson 95% CI; a 10/10 result is reported as [72.2–100], never as "perfect".
4. **Both normal and anomaly scenarios are covered.** Sensitivity 100% on all three pull modes and on peel; false-alarm behaviour measured separately on baseline, touch, press, friction, and the mixed-activity reference (2 of 41 normal recordings alarm: one Brief Touch, one Normal Mix).

What this does **not** yet show is cross-session generalization: all 81 recordings share one sensor mounting, one day, one operator. The remedy is procedural and already implemented in code: round-2 collection under `Data/S1..S3` with the patch re-attached per session, scored with `python main.py --eval --cv session` (train 2 sessions, test 1). Session-CV numbers, not LOFO, are the ones to publish after round 2. All thresholds and the operating point are frozen before seeing round-2 data: tune on old, measure on new.

---

## 7. Known limitations (to be stated wherever results are quoted)

1. **Horizontal pull has no detachment signature on this patch** (0/10 lift-gate crossings, quieter than Friction). Detection of that mode currently rides on a press-like proxy, and the discriminator is press *magnitude* — heavy presses (+1357…+1717) produce zero pull-frames while moderate ones (≈ +456) read as pull, which is the wrong direction for a safety device. Do not describe the system as detecting detachment in general until a horizontal signal is demonstrated on the round-2 rig.
2. **Single session** — no evidence yet of generalization to a re-attached patch (Section 6).
3. **Small classes** — Baseline n=5, Peel n=10; every claim carries its Wilson CI.
4. **No anomaly recording reaches the ≤ 25,000-count detachment spec** (KES 2025 §2.1; deepest 27,251), and as of 2026-09-17 none ever can: the criterion asks for a 50.1 pF drop (3,000 counts at the measured 59.85 counts/pF) from a patch that holds about 30 pF, so even at zero capacitance the reading floors at 26,205 counts. This is a contradiction among three published numbers, not a property of the round-1 fixation, and it does not change the model or the gates — detection uses the delta from the tracked baseline throughout. The direction (attached = high, detached = low) is confirmed; the absolute criterion is not, and cannot be evaluated until the patch's absolute C0 is measured. See `spec_detach_reachability()` and `tests/test_spec_reachability.py`.
5. **Frame-level labels carry lead-in noise** (every file opens quiescent under the file's label). Episode-level metrics are therefore the primary reporting unit; the noise gate suppresses the affected frames at inference.

---

## 8. Absolute capacitance (CDC) readiness

**Why the current relative measurement is a limitation.** The PSoC path measures change against a power-on offset. Booting with the tube already attached versus not attached yields different starting offsets, so the system cannot distinguish those states at startup — it only ever sees *change since boot*.

**What absolute capacitance buys.** A capacitance-to-digital converter (CDC) board (e.g. AD7147 / AD7746 / FDC2214, or PSoC in absolute sigma-delta mode; femtofarad resolution, 0–50 pF range) reads each pad's true capacitance. Because a PVC/silicone tube (εᵣ ≈ 2.8) casts a measurable dielectric shadow against skin contact (εᵣ ≈ 50–80), an absolute reading identifies *at power-on, before any monitoring*: whether the dressing is attached, whether the tube is present, and along which axis it runs — with no zero-calibration step.

**Software is already CDC-ready; the model does not change.** The compatibility layer exists and is tested:

- `convert_absolute_cdc_to_counts()` maps absolute pF to the count domain the 34-feature model was trained in (59.85 counts/pF against a 30 pF nominal), so the trained classifier serves both hardware generations unchanged.
- `LivePipeline` auto-detects the unit domain per frame (pF < 500 vs counts > 3000) and reports `"mode": "cdc"` in its telemetry; CDC open-circuit and rail-saturation states are treated as disconnection, not data.
- `POST /api/v6/cdc/tube-localization` implements static tube localization from a single absolute frame: median-referenced dielectric-shadow detection with a MAD-adaptive threshold (clamped 0.35–1.5 pF), requiring ≥ 3 shadowed pads, returning tube presence, the shadowed pad set, axis orientation (vertical / horizontal / diagonal), and a confidence score.
- Surface topography analysis (`analyze_surface_topography`) accepts either domain and drives per-pad adaptive gates.

Remaining work is hardware-side: fabricate and bench the CDC board, capture a 1-by-1 pad sweep through the live socket to verify channel order on the new path (`--verify-pads`), then record round 2 on it.

---

## 9. Test-rig and acquisition upgrades feeding this validation (advisor review, 2026-09-17)

- **Suction fixation.** The round-1 vacuum rig held the dressing without adhesive and with insufficient suction; the backing was thick enough to absorb shear, which is the leading hypothesis for the horizontal-pull blind spot and for the corpus never reaching the detachment spec. Round 2 uses a high-suction source (−40 to −60 kPa; an industrial/vacuum-cleaner-grade source is acceptable per the advisor) with a thinned backing membrane (≤ 0.5 mm) and medical-grade hydrocolloid adhesive, so tube-applied force reaches the pads. Acceptance criterion: ≥ 8/10 peel recordings must reach ≤ 25,000 counts.
- **Synchronized ground truth.** All round-2 recordings are captured with OBS Studio in a dual-source scene — bench webcam plus the live GUI heatmap — with a shared sync beacon, per `docs/OBS_STUDIO_GROUND_TRUTH_SYNC_GUIDE.md`. This is what turns "the model alarmed" into a measured **lead time in seconds before detachment**, which is the clinically meaningful figure.

---

## 10. Reproduction

```
python main.py --report                      # regenerates Data/metrics.json + Data/METRICS.md
python main.py --verify-metrics              # re-measures headline figures, diffs against metrics.json
python scripts/evaluate_5_scenarios.py       # OOF 5-scenario table -> Data/five_scenarios_evaluation.json
python main.py --verify-pads                 # channel-order verification against Press/1_by_1.csv
python main.py --eval --cv session           # session-based CV (requires Data/S1..S3, round 2)
```
