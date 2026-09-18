# Plan: Addressing the Supervisor's Feedback with What Exists Today

Written 2026-09-18. Companion to `docs/ACTION_PLAN.md` (Thai). This document is
scoped deliberately: everything in it can be done with the **existing 81-recording
single-session corpus, the current relative-capacitance board, and the current
bench rig**, before round-2 data or the CDC board exist. Where an item cannot be
closed with current resources, it says so and states the smallest thing that can.

Every figure quoted here comes from `Data/metrics.json`, `Data/five_scenarios_evaluation.json`,
or `Data/model_comparison_100x.json`. Nothing is typed from memory; `tests/test_doc_metrics_sync.py`
enforces that for the headline block, and the rest cite their source file.

---

## 0. Where things stand (verified 2026-09-18)

| Check | Result |
|---|---|
| `python run.py test` | 159 passed (before this plan's additions; new tests below) |
| `python run.py verify` | metrics.json reproduces, zero drift, stamped 2026-09-17 |
| `python run.py pads` | Spearman ρ = 1.0000, 0 inversions — Sensor-N == pad N on the corpus |
| `python run.py audit` | 0/10 Peel files reach ≤ 25,000 counts, and the audit now prints *why that is arithmetic, not fixation* |

Headline, episode-level, out-of-fold, 7-of-6 hold 9: sensitivity 100.0 % [91.2–100.0],
false alarm 4.9 % per recording [1.3–16.1] = 7.8 alarms/hour, median time-to-alarm 5.60 s.

The three supervisor items, restated as engineering questions:

1. **Algorithm justification and 5-scenario generalisability** — *why* does this
   processing separate the states, and does it hold across Baseline / Touching /
   Friction / Pulling / Peeling without depending on incidental setup conditions?
2. **Relative → absolute capacitance** — the board zeroes at power-on; if the tube is
   attached at boot the baseline differs from when it is not. The lab is building a
   CDC board. What do we do until it arrives?
3. **Suction and backing** — the pump is weak and the backing too thick, so force does
   not transfer to the sensor. Use a stronger source.

---

## 1. Algorithm justification and 5-scenario generalisability

### 1.1 What exists

- `docs/ALGORITHM_JUSTIFICATION.md` — per-scenario physics (what changes physically,
  which feature sees it), why a bounded-depth gradient-boosted ensemble fits a
  3,349-frame / 34-feature tabular problem with axis-aligned threshold structure,
  and the measured alternatives: RandomForest + 9 statistics 70.0 % episode
  sensitivity at the same alarm budget, RandomForest + 34 features 87.5 %,
  HistGradientBoosting + 34 features 100.0 %. The BiLSTM comparison is multi-seed
  (0.9531 ± 0.0230 vs 0.9518 ± 0.0038, no significant difference, 6× the variance)
  and the corpus physically cannot feed a sequence model (3.36 s window against a
  6.7 s median Vertical Pull file).
- `scripts/evaluate_5_scenarios.py` → `Data/five_scenarios_evaluation.json`,
  re-run 2026-09-17, out-of-fold with Wilson intervals:

  | Scenario | Files | Alarm | Reading |
  |---|---|---|---|
  | Baseline | 5 | 0/5 | no false alarm |
  | Touching (Brief Touch + Press) | 21 | 1/21 | 4.8 % [0.8–22.7] — Press 0/11 |
  | Friction | 10 | 0/10 | no false alarm |
  | Pulling (vertical, horizontal, power) | 30 | 30/30 | 100 % [88.6–100] |
  | Peeling | 10 | 10/10 | 100 % [72.2–100] |

- A correction made 2026-09-17: the progress report had placed RandomForest's numbers
  (86.8 % ± 3.2 %) under a "Deep Learning" column and claimed a *p* = 3×10⁻¹⁸ win over
  deep learning. `Data/model_comparison_100x.json` contains no deep model; the win is
  over other tree ensembles. Fixed. The justification now says exactly what was compared.

### 1.2 The gap

"Not dependent on immediate environmental variables" is **not yet demonstrated.** All
81 recordings are one mounting, one day, one operator. Leave-one-file-out holds out a
file, not an attachment. The model may have learned the signature of that one
attachment rather than the physics of pulling. `--cv session` is the honest answer
and it cannot run until `Data/S1..S3` exist.

### 1.3 What can be done now — and was done

**Perturbation robustness on the existing corpus.** `scripts/evaluate_robustness.py`
(new) re-runs the exact out-of-fold episode evaluation behind `metrics.json` with the
raw counts perturbed *before* Kalman calibration and feature extraction, so the whole
shipped pipeline sees each perturbation the way it would see a different patch, a
noisier board, or a flaky link:

| Variant | Stands for |
|---|---|
| `gain_global_p10/m10/p20/m20` | a different resting C0 — another patch, thinner backing, other skin |
| `gain_per_pad_10` | pad-to-pad manufacturing spread on a second patch |
| `noise_sd30/60/120` | a noisier front end; 60 is the physics noise gate, 100 the SOP baseline-swing limit |
| `frame_drop_10` | serial dropouts |
| `spike_1pct` | +5,000-count single-pad hits — *under* the 50,000 surge filter, so the model, not the filter, must absorb them |

It writes `Data/robustness_evaluation.json` with sensitivity (Wilson CI), false-alarm
rate, alarms/hour and the list of missed files per variant, plus the delta from the
unperturbed run. Run it:

```
python scripts/evaluate_robustness.py           # all variants, about 20 minutes
python scripts/evaluate_robustness.py --quick   # identity + gain +20 % + noise 60
```

**What it proves and what it does not.** It answers "does the detector depend on
incidental constants of this setup?" — gain, offset, noise floor, timing. It does
**not** reproduce a re-attached patch: contact area, adhesive behaviour, and the
horizontal-pull signature this rig has never produced are outside its reach. Report
it as *robustness to modelled sensor variation*, never as *cross-session
generalisation*. Round 2 stays on the plan.

One thing to look for in the result: F10 scale-normalised deltas
`(ΔC/C0)·28000` were built for ±20 % baseline shifts, but F10 lives in
`LivePipeline` and **not** in the offline `calibrate()` path that produces
`metrics.json`. If `gain_global_p20` degrades offline, that is a finding about the
published numbers, not about the live device — and the fix is to put F10 in
`calibrate()` too, then re-run `--report`.

**Presentation aid for the supervisor — one page, no new measurement.** A
physics-to-feature table for the five scenarios: which physical quantity changes,
which of the 34 features captures it, its measured median on the corpus. The
material is already in `ALGORITHM_JUSTIFICATION.md` §2; this is a tabulation, ~1 hour.

### 1.3a First results — quick run, 2026-09-18 (`Data/robustness_evaluation.json`)

| Variant | Sensitivity [95 % CI] | FA / recording | Alarms / h | Missed |
|---|---|---|---|---|
| identity | 100.0 % [91.2–100.0] | 4.9 % (2/41) | 7.8 | 0 |
| gain_global_p20 | 97.5 % [87.1–99.6] | 9.8 % (4/41) | 13.0 | 1 — `A_VPull_01` |
| noise_sd60 | 85.0 % [70.9–92.9] | 7.3 % (3/41) | 13.0 | 6 — 2 VPull, 3 HPull, 1 PowerP |

Two findings, both usable with the supervisor today:

**Gain: the offline path is not scale-normalised, and it shows.** A patch resting
20 % higher (33,600 instead of 28,000 counts — which is what a thinner backing or a
ground plane will *produce*, see §3) doubles the false-alarm rate and drops one
event. The reason is mechanical: every gate is in raw counts (lift −300, press +300,
`PEEL_MEAN_GATE` −150, noise 60), so a ×1.2 patch makes every delta 20 % larger and
more press-side crossings clear the gates. F10 — `(ΔC / C0) × 28000` — was written
for exactly this, but it runs in `LivePipeline` only; the offline `calibrate()`
path behind `metrics.json` never applies it. **Action (software, current data):** add
a `kalman_norm` calibration mode that applies F10 after the Kalman step, re-run this
script with it, and confirm two things before making it the default — the identity
row is unchanged (bench C0 ≈ 28,000, so normalisation is a no-op there) and the
gain rows recover. Then re-run `--report`, because the published numbers will then
describe the same pipeline the live device runs. This is the single most valuable
software change available before round 2, because round 2 will change C0 on purpose.

**Measured 2026-09-18 — the mode exists, and the prediction above was half right.**
`calibrate(raw, "kalman_norm")` is implemented; `scripts/evaluate_robustness.py
--calibration kalman_norm` wrote `Data/robustness_evaluation_kalman_norm.json`
(`metrics.json` is still a `kalman` measurement and the default is unchanged).

| variant | sensitivity | FA/recording | alarms/h | missed |
|---|---|---|---|---|
| identity | 100.0 % [91.2–100.0] | 4.9 % (2/41) | 7.8 | 0 |
| gain_global_p20 | 97.5 % [87.1–99.6] | **7.3 %** (3/41) | 13.0 | 1 — `A_VPull_01` |
| noise_sd60 | **87.5 %** [73.9–94.5] | 7.3 % (3/41) | **7.8** | 5 |

Two corrections to the plan as written. First, the identity row is **not** bit-exact,
only outcome-identical: the corpus rests near 27,820 counts, not 28,000, so
normalisation is a ~0.6 % rescale that moves individual deltas by up to ~18 counts —
well inside the 60-count noise gate, which is why every headline figure is unchanged.
Second, the gain row **partially** recovers: false alarms fall 9.8 % → 7.3 %, but not
to the 4.9 % identity level, and alarms/hour stays at 13.0. So raw-count gates are
not the whole story. What F10 cannot normalise is the Kalman front end itself —
`KalmanBaseline` holds its innovation gate at 60 counts and clips `r_vec` to
[20, 150] counts², both absolute, so a ×1.2 patch tracks its baseline differently
*before* F10 ever applies. That residue is a noise-floor effect, not a scale effect,
which points the same way as the noise rows do: at the absolute CDC board. Adopt
`kalman_norm` as the default only together with a re-run of `--report`, and treat the
remaining gain gap as a front-end item for round 2, not a calibration one.

**Noise: the margin is about ten times the bench floor, then it falls off.** The
round-1 board's baseline noise is roughly 5–12 counts sd (Kalman `r_vec` after
seeding). At 60 counts sd — the physics noise gate — sensitivity drops to 85 %. The
misses are the classes with the least signal-to-noise: horizontal pull (detected via
the contact side, since it produces no lift), a 12-frame vertical pull whose event is
its last five frames, one power pull. Peel stays 10/10. **What this says to the
supervisor:** the detector's environmental dependence is on the *noise floor*, not
on gain or offset, and that is a hardware property — one more argument for the CDC
board (femtofarad resolution) and for the ground plane (which gives horizontal pull
a lift signal instead of leaning on contact artefacts). The full run
(`noise_sd30` / `noise_sd120`, per-pad gain, frame drop, spikes) locates the cliff.

### 1.4 Done when

- `Data/robustness_evaluation.json` exists; every variant's sensitivity CI overlaps the
  unperturbed 100 % [91.2–100], or the variants that do not are named as limits.
- The supervisor deck carries the 5-scenario table with Wilson intervals and the
  single-session caveat in the same slide, not a later one.

---

## 2. Relative → absolute capacitance

### 2.1 What exists

The software side of the CDC path is complete: `convert_absolute_cdc_to_counts()`,
`/api/v6/cdc/tube-localization` (tube position from the dielectric shadow, no
zero-calibration), and `LivePipeline` auto-detects pF-scale frames. The trained model
needs no retraining — it consumes the same 34 features.

### 2.2 The gap, restated as the supervisor put it

With a relative board the software zeroes on whatever it sees at power-on. If the
patch is loose, absent, or being pressed at that moment, every later delta is
measured from the wrong place and nobody can tell. The existing F3 guard only rejects
seeds outside 10,000–45,000 counts — garbage, not "the patch was not on the skin yet".

### 2.3 What can be done now — and was done

**Report where the zero landed.** `main.py` gains `ATTACHED_SEED_BAND = (27500, 28600)`
and `seed_plausibility()`. The band comes from the corpus: every recording that
starts at rest seeds between 27,823 and 28,258 counts (median 28,025). The only
seeds outside it are 10 of the 11 Press recordings, which were started while the
operator was already pressing — the check flags them `above_band`, which is a real
validation of the feature on real data, not a synthetic one. Every `LivePipeline` frame now carries
`seed_plausibility: {status, seed_median, band, note}` with status one of
`attached_band` / `below_band` / `above_band` / `unknown`. It **never rejects** — a
genuinely different mounting may rest elsewhere — it reports, so the console can
say "verify attachment before trusting alarms" instead of silently trusting the
zero. The band is pinned to the corpus by `tests/test_seed_plausibility.py`, which
recomputes every recording's Kalman seed and asserts it falls inside; the constant
cannot drift from the data.

**Wire it to the console** (small, next): show `seed_plausibility.note` in yellow
next to the calibration tag when status ≠ `attached_band`. Ten lines in `app.js`.

**Before the CDC board is finalised — one measurement.** The candidate parts
(AD7147 / AD7746 / FDC2214) were shortlisted for a **0–50 pF** range. That presupposes
C0 ≈ 30 pF, which is exactly the number that makes the ≤ 25,000-count spec
unreachable (§3). The two questions are the same question. Measure the absolute C0
with an LCR meter per `docs/DATA_COLLECTION_SOP_v2.md` §0.2 (15 minutes: OPEN
compensation, Cp–D mode, stated test frequency, attached/detached pair, three
repeats). If C0 is really ~30 pF the spec is wrong or in different units; if it is
> 50 pF the chip range is wrong. Either way it is cheaper to know before the board
is fabricated.

### 2.4 Done when

- `seed_plausibility` visible on the console; a deliberately loose patch at boot
  produces `below_band` on screen.
- C0 measured, with frequency, mode and D recorded, and written into the empty row
  of the Sensor Structure table in `docs/Hardware_Deck_Spec.md`.
- The CDC chip range chosen against that number, not against an assumption.

---

## 3. Suction and backing

### 3.1 What the supervisor asked for, and what the arithmetic adds

A stronger pump and a thinner backing. Both are on the round-2 rig list
(`DATA_COLLECTION_SOP_v2.md` §1: −40 to −60 kPa, backing ≤ 0.5 mm, hydrocolloid
adhesive, ground plane). But they do different things, and the difference matters
for what to expect:

| Change | What it moves | Effect on the ≤ 25,000 criterion |
|---|---|---|
| Stronger pump, real adhesive | how *completely* the patch lets go | **none** — even complete detachment floors at 28,000 − 30 × 59.85 = 26,205 counts |
| Thinner backing | C = εA/d → **C0 itself**, roughly ×2 for half the thickness | can make it reachable: at C0 ≈ 60 pF a 50 pF loss is physically possible |
| Ground plane | turns a fringing-field sensor into a two-plate one → raises C0, and gives lateral (horizontal) motion something to change | the only lever for the horizontal-pull blind spot |

So the supervisor's *backing* advice is the one that attacks the spec contradiction
directly, and the *pump* advice attacks fixation quality, which is a different
problem. (2026-09-18 correction to the repository: earlier wording said *no* rig
change could reach the criterion; that was too strong. Pump and adhesive cannot;
geometry can.)

### 3.2 What can be done now, in order

1. **Measure C0 on the current rig first** (§2.3, 15 min). This is the baseline the
   geometry change will be compared against, and it settles which of three published
   numbers is wrong. Without it, a later "it got better" has no denominator.
2. **Ground plane** — cheapest, and the only thing that addresses horizontal pull
   (0 of 10 files cross −300 counts today; Friction, a *normal* class, is louder).
   Foil or copper tape on the skin side of the bench surface, wired to board ground.
3. **Thinner backing** — the C0 lever. Re-measure C0 after; the number should roughly
   double if thickness halved.
4. **Adhesive**, then **pump** — fixation quality. Worth doing for round 2, not to chase
   the 25,000 figure.

Then run the round-2 collection per the SOP with the new acceptance criteria already
written there: **Horizontal Pull ≥ 5 of 7 files crossing −300 counts** (0/10 today),
Peel median deepest delta deeper than −1,500 counts (−869 today).

### 3.3 What cannot be done now

Nothing physical. Everything in §3.2 needs the bench. Software-side there is nothing
to add: the audit already prints the arithmetic, the tests pin the constants, and
`SPEC_DETACH_MAX` stays at 25,000 (invariant 5).

---

## 4. Execution order

| # | Task | Needs | Time | Owner |
|---|---|---|---|---|
| 1 | Run `scripts/evaluate_robustness.py` in full; read which variants hold (quick run done, §1.3a) | nothing new | 60 min compute | anyone |
| 1b | Add `kalman_norm` calibration (F10 in the offline path), re-run 1, then `--report` if identity holds and gain recovers | `main.py` edit + re-measure | 2 h | software |
| 2 | Show `seed_plausibility` on the console | `app.js` edit | 30 min | software |
| 3 | Measure C0 with the LCR meter (SOP §0.2), fill the deck table row | LCR meter | 15 min | bench |
| 4 | Decide the CDC chip range from that C0 | item 3 | — | lab |
| 5 | Ground plane on the rig; re-measure C0 | foil, wire | 1 h | bench |
| 6 | Thinner backing; re-measure C0 | material | 1 h | bench |
| 7 | Adhesive + pump | consumables | — | bench |
| 8 | Round-2 collection, 3 sessions, `Data/S1..S3`, `--cv session` | items 5–7 | 1 day | bench + software |

Items 1–3 need no purchase and no waiting. Items 3 and 5–6 each end with the same
15-minute measurement, so the geometry changes are evaluated by the number they are
supposed to move, not by feel.

---

## 5. Things this plan does not do, on purpose

- **No moisture / saliva compensation.** No wet recording exists. Clamping the
  baseline against an upward swell would make a later peel measure a *smaller* lift
  — the dangerous direction. Record wet files in round 2 first.
- **No band-stop for cough / ventilator at 0.2–0.35 Hz.** Sampling is 1.79 Hz; the
  annunciator window (7 frames = 3.92 s = 0.255 Hz) sits in the middle of that band.
  A notch there removes the detector's own operating band.
- **No change to `SPEC_DETACH_MAX`, the peel gates, or the operating point.** Tune on
  old, measure on new. Round 2 validates them as frozen.
- **No claim of cross-session generalisation** from the robustness script. It is
  labelled as modelled variation and stays that way until `--cv session` runs.
