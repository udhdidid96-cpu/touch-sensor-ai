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

## 9. Results

Not yet run.
