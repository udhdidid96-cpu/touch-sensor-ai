# ML enhancement plan: score the detector the server runs, then try to improve it

Pre-registered 2026-09-23, before any candidate below was scored.
Harness: `scripts/benchmark_served_path.py`. Output: `Data/served_path_benchmark.json`.
Sections 1 to 8 are frozen once this file is committed. Results go in section 9
and nothing above it is edited to fit them.

## 1. Why this plan exists

Every published figure comes from `compute_oof()` + `evaluate_stream()`:

<!-- metrics:episode_headline_en -->
Episode-level, out-of-fold, 7-of-6 hold 9: sensitivity **100.0%** [91.2–100.0], false alarm **4.9%** per recording [1.3–16.1] = **7.8 alarms/hour**, median time-to-alarm **5.60 s** (worst 17.36 s), 0 missed events. Source: `Data/metrics.json` (2026-09-17, v6.2).
<!-- /metrics:episode_headline_en -->

That path is not the one the server runs. Reading the code side by side:

| step | published path (`compute_oof`, `evaluate_stream`) | served path (`LivePipeline.process`) |
|---|---|---|
| Kalman seed | mean of the first 5 frames, per-channel `r` from their spread (`KalmanBaseline.run`) | frame 0 alone, `r = 40` on every channel (`seed(working_frame[None, :])`) |
| baseline repair | none | quiescent negative-step recovery |
| scale | raw Kalman delta | F10: delta / C0 x 28,000 |
| frames classified | every frame, `clf.predict` | only frames whose largest \|delta\| is at least the 60-count noise gate; the rest are class 0 without asking the model |
| warmup | 5 frames held at level 0 | 5 frames held at level 0 |

`python run.py audit Data` reports movement inside the 5-frame offset window in
40 of the 81 recordings, so the two seeds differ on half the corpus. The model is
trained on one delta and served another, and no published number measures the
served one.

The second reason is the noise cliff. In the published sweep
(`Data/robustness_evaluation_kalman_norm.json`, train and test both perturbed),
the `noise_sd120` variant detects 24 of 40 events.

## 2. Hypotheses

- **H0 (measurement).** Out of fold, the served path does not score the same as the
  published path. Reported, not decided: it is a measurement, not a change.
- **H1 (train/serve alignment).** Training on the deltas the server actually
  classifies (C1) does no harm on clean data and helps under perturbation.
- **H2 (noise augmentation).** Adding noisy copies of the training recordings (C2)
  moves the noise cliff without costing clean performance.
- **H3 (label noise).** Quiet frames inside anomaly recordings carry the anomaly
  label, but the served classifier is never asked about quiet frames. Training only
  on frames at or above the noise gate (C3) removes that label noise.
- **H4.** C2 and C3 combined (C4).

## 3. Protocol

- **Folds.** Leave one recording out, over all 81 (one session, S0). The model for
  each fold never sees the held-out recording, nor any augmented copy of it.
- **Train clean, test perturbed.** Training uses the clean corpus. The held-out
  recording is perturbed at test time by each of the 11 variants in
  `scripts/evaluate_robustness.py` (identity, four global gains, per-pad gain,
  white noise sd 30/60/120, 10% frame drop, 1% spikes), with that script's
  functions and its deterministic per-file seeds. This asks the deployment
  question: trained on this bench, run on a worse board. It is not the published
  sweep's protocol (which perturbs training too), so the two are not compared
  row by row.
- **Scoring.** Each held-out recording is replayed frame by frame through
  `LivePipeline(model).process()`, the object the websocket and `--replay` use, and
  scored on its `severity_level`. `C0_offline` is the one exception: it is scored
  the published way (`calibrate(raw, "kalman")`, `clf.predict`, `AlarmDebouncer`
  with the same warmup), so the gap between it and `C0_served` is H0.
- **Fixed, not tuned.** Estimator `_new_rf(42)` (HistGradientBoosting, 150
  iterations, depth 8, balanced classes), the 34 features, the operating point
  (6 votes in a 7-frame window, hold 9), the 60-count noise gate, the -300 lift gate
  and the peel gate are all unchanged. None of them is re-tuned on these results.
- **Harness check.** Before any candidate is decided, `C0_offline` on the identity
  variant must reproduce `Data/metrics.json` exactly: detections, false-alarm
  recordings, alarms per hour, median latency, and file-vote accuracy. If it does
  not, the harness is measuring something else, and no candidate is chosen.

## 4. Candidates

| id | training deltas | training frames | augmentation |
|---|---|---|---|
| C0 | offline Kalman (the shipped recipe) | all | none |
| C1 | served (captured from `LivePipeline` itself) | all | none |
| C2 | served | all | + 3 noisy copies per recording |
| C3 | served | largest \|delta\| >= 60 counts only | none |
| C4 | served | largest \|delta\| >= 60 counts only | + 3 noisy copies per recording |

- Served deltas are captured from the running pipeline, not re-implemented, so the
  seed, the quiescent recovery and F10 are exactly the served ones.
- Augmentation adds white noise to the raw counts at sd 45, 90 and 135. These
  levels are deliberately not the test levels (30, 60, 120). Seeds come from
  `train-augment:<sd>:<file>` and never collide with the test seeds
  (`<variant>:<file>`).
- The noise variants are still in-family for C2 and C4: same noise model,
  different levels. Gains there are expected by construction. The gain, frame-drop
  and spike variants, and the clean row, are where harm would show, and section 5
  guards each one.
- With augmentation the training set passes 10,000 rows, so the unchanged estimator
  turns on its own early stopping (`early_stopping="auto"`). That is part of the
  candidate as it would ship.

## 5. Decision rule (as coded in `decide()`)

The reference is `C0_served`: what the server runs today. A candidate is adopted
only if every check holds.

1. Clean detections: at least the reference's.
2. Clean false-alarm recordings: no more than the reference's.
3. Clean alarms per hour: at most 1.10 x the reference.
4. Clean median latency: at most the reference + one frame (0.56 s).
5. Clean file-vote accuracy: at most one recording below the reference.
6. **Robustness gain**, clustered by recording. For each of the 40 anomaly
   recordings, compare how many of the 10 perturbed variants the candidate
   annunciates against the reference. A file is a gain if the candidate
   annunciates in more, a loss if in fewer. Gains must exceed losses, and the
   exact one-sided sign test must give p < 0.0125: that is 0.05 Bonferroni-split
   over the four candidates. Pair-level counts (file x variant) are reported
   for information only: they treat the 10 replays of one event as independent,
   and they are not.
7. Pooled false-alarm recordings over the 10 perturbed variants: at most the
   reference + 4.
8. No single perturbed variant loses more than one detection or gains more than two
   false-alarm recordings against the reference.

If more than one candidate passes, the one with the most pooled detections is
chosen. A tie goes to the simplest, in the order C1, C3, C2, C4. If none passes,
the model recipe does not change, and the result is recorded here as a negative
result.

## 6. What an adoption would change

- The training calibration becomes the served one, so the model is fitted on the
  delta it is asked about.
- The report must measure that same thing. Adoption therefore also moves
  `--report` / `--verify-metrics` onto the served path. The headline is
  regenerated by the code, and the metrics blocks by
  `scripts/sync_metrics_blocks.py`. Nothing is typed.
- Nothing changes in the browser, the alarm operating point, the gates, or
  anything pinned by `tests/test_spec_reachability.py`.

## 7. Measurement integrity (independent of section 5)

If `C0_served` and `C0_offline` differ on any identity-row outcome, the published
headline describes a pipeline the device does not run. In that case the report
gains the served figure as a published, reproducible number, whichever candidate
(if any) is adopted. The headline stays whatever the code measures.

## 8. Limits stated in advance

- One session and one mounting. Leave-one-file-out measures generalisation within
  one attachment, not to a new one. Round 2 is still required.
- The perturbations are modelled. A synthetic gain is not a re-attached patch, and
  white noise is not the board's real noise spectrum.
- Forty anomaly recordings bound what any clean-row comparison can show. The clean
  checks are non-inferiority guards, not claims of superiority.

## 9. Results (2026-09-23)

Run: `--shard k/7` for k = 1..7, then `--merge --expect 81`. Every figure below is
copied from `Data/served_path_benchmark.json`, apart from the post-hoc diagnosis,
which comes from `Data/served_path_diagnosis.json` (`--diagnose`).

**Harness check: passed.** `C0_offline` on the identity variant reproduces
`Data/metrics.json` exactly: detections, false-alarm recordings, alarms per hour,
median latency and file vote all match.

### 9.1 Clean row, and all perturbations pooled

| scored | clean detected | clean FA recordings | clean alarms/h | clean median latency | clean file vote | perturbed detected (10 variants pooled) | perturbed FA recordings (pooled) |
|---|---|---|---|---|---|---|---|
| C0_offline | 40/40 | 2/41 | 7.8 | 5.60 s | 79/81 | 318/400 | 15/410 |
| C0_served | 39/40 | 2/41 | 5.2 | 7.28 s | 71/81 | 320/400 | 10/410 |
| C1 | 38/40 | 1/41 | 2.6 | 6.72 s | 72/81 | 320/400 | 7/410 |
| C2 | 39/40 | 6/41 | 15.5 | 6.72 s | 69/81 | 377/400 | 47/410 |
| C3 | 38/40 | 1/41 | 2.6 | 7.00 s | 74/81 | 329/400 | 7/410 |
| C4 | 38/40 | 4/41 | 10.4 | 6.72 s | 71/81 | 376/400 | 40/410 |

### 9.2 Decision

| candidate | files gained / lost | sign test p (alpha 0.0125) | failed checks |
|---|---|---|---|
| C1 | 10 / 4 | 0.0898 | clean_sensitivity, robustness_gain |
| C2 | 29 / 0 | 0.0000 | clean_false_alarms, clean_alarm_burden, file_accuracy, pooled_false_alarms, no_variant_harm |
| C3 | 14 / 3 | 0.0064 | clean_sensitivity |
| C4 | 29 / 1 | 0.0000 | clean_sensitivity, clean_false_alarms, clean_alarm_burden, pooled_false_alarms, no_variant_harm |

**No candidate is adopted.** The model recipe does not change.

- **C3 came closest.** It passes the robustness test (14 recordings gained, 3
  lost, p = 0.0064). On clean data it has fewer false-alarm recordings (1/41) and
  half the alarm burden. It fails one check: it misses one more clean recording
  than the served reference, A_HPull_07, as C1 does too. The rule allows no clean
  loss, so C3 is not adopted.
- **C2 and C4 close the noise cliff.** At sd 120 they detect 34/40 and 37/40,
  against 9/40 for the served reference. They pay for it in false alarms (6/41 and
  4/41 clean, 15.5 and 10.4 alarms/h). Their noise gains are also in-family by
  construction (section 4). They fail five checks each.

### 9.3 H0: the published path is not the served path (confirmed)

The same out-of-fold models, replayed through `LivePipeline`, give different
results. Sensitivity is 39/40 instead of 40/40, and the median time to alarm is
7.28 s instead of 5.60 s. The recording missed is `Vertical Pull NO
G/A_VPull_06.csv`. The comment above `AlarmConfig` in `main.py` already describes
this miss in sample: a 12-frame clip whose pull stops one frame short of the sixth
vote. It is now measured out of fold. The count of false-alarm recordings is the
same on both paths, 2/41.

**Post-hoc diagnosis (not pre-registered).** This explains most of the latency
gap. Of the 240 votes behind the first offline alarms, 58 come from frames whose
largest served |delta| is under the 60-count gate. For four recordings, every vote
behind the first offline alarm is such a frame: A_HPull_03, HP_3, VP_2 and VP_4.
The offline classifier calls "pull" on frames with no excursion above baseline
noise, before the event is physically visible. That comes from the per-file
labels (every frame of a pull recording is labelled pull), not from the event.
The served path's gate never lets the model see those frames, so its alarms start
when the signal does.

### 9.4 Deployment finding: a clean-trained detector on a noisier board

When the model is trained clean and the board is noisy, the served detector finds
27/40 events at sd 30, 14/40 at sd 60, and 9/40 at sd 120. The published sweep
retrains on the perturbed data (`Data/robustness_evaluation_kalman_norm.json`:
37, 35 and 24 of 40), so it describes a system retrained on its own noise, not
the one that would be deployed. Section 9.2 shows that augmentation recovers most
of the loss, but under the rule as registered it costs too many false alarms. The
existing `jitter_noise_counts` telemetry is the live sign that a board has left
the validated range.

### 9.5 What follows (section 7 applies)

The identity row differs between `C0_served` and `C0_offline`, so section 7's
trigger is met. The report now publishes the served-path figures next to the
offline headline, generated by the code and checked by `--verify-metrics`. C3 and
C4 are the candidates worth pre-registering against round-2 data, unchanged: tune
on old, measure on new.
