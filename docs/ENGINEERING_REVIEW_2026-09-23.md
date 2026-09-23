# Project2 engineering and ML review — 2026-09-23

Branch `ml/served-path-benchmark`. `master` is untouched (still `origin/master`).
Every figure below is either a generated metrics block (kept in sync by
`scripts/sync_metrics_blocks.py`) or is copied from a generated file named beside
it. None is typed from memory.

## Summary

- **The model recipe does not change.** Four candidate training changes were
  pre-registered and scored under a fixed rule. None passed. The closest one
  (training only on frames the served classifier is asked about) missed one more
  clean recording than the reference.
- **The published headline did not describe the running device, and now the
  running device is published too.** Every figure used to come from the model's
  vote on the offline delta, every frame. The server seeds its baseline from
  frame 0, repairs quiescent channels, rescales by F10, and never asks the model
  about a frame under the 60-count noise gate. Replayed through `LivePipeline`
  out of fold, the device misses one event the offline vote catches and alarms
  later. `--report` now publishes both, and `--verify-metrics` checks both.
- **Part of the offline headline rests on sub-gate frames.** 58 of the 240 votes
  behind the first offline alarms are frames with no excursion above the noise
  gate (post-hoc; `Data/served_path_diagnosis.json`).
- **Deploy reproducibility was broken in two ways, both fixed.** First, the
  image's Python 3.11 with ranged requirements installed an older numeric stack
  than the one every figure was measured on. Second, the workstation's model
  pickle was shipped into that image. The numeric stack is now pinned, the image
  is Python 3.13 and trains its own model at build time, and a cache written by
  another scikit-learn is refused.
- **Three new behavioural guards.** The suite no longer pays for the 81-fold
  pass twice.

## 1. Baseline, before any change

Run on the untouched tree (logs in `D:\Projects\_p2_agent`, outside the repo):

| gate | result |
|---|---|
| `python run.py test` | 215 passed, 875.56 s |
| `python run.py verify` | OK, every headline figure reproduces within 2% |
| `python run.py pads` | Spearman rho 1.0000, 0 inversions, exit 0 |
| `python run.py audit Data` | exit 2. These are the corpus findings already on record: peel never reaches 25,000 counts (unreachable by arithmetic), movement inside the 5-frame offset window in 40/81 files, 75/81 files shorter than 100 frames, baseline swing 234 counts |

The audit's exit 2 is the honest state of the round-1 corpus, not a regression.
It is unchanged after this work.

## 2. Diagnosis

**Published path versus served path** (read from the code):

| step | published (`compute_oof`, `evaluate_stream`) | served (`LivePipeline.process`) |
|---|---|---|
| Kalman seed | mean of frames 0–4, per-channel `r` from their spread | frame 0 alone, `r = 40` everywhere |
| baseline repair | none | quiescent negative-step recovery |
| scale | raw delta | F10: delta / C0 x 28,000 |
| frames classified | every frame | only frames at or above the 60-count gate |

**Noise.** The published robustness sweep retrains on the perturbed data. A model
trained on the clean bench and run on a noisier board had never been measured.

**Deployment.** `requirements.txt` capped scikit-learn below 1.9 and the image was
Python 3.11. The workstation that produced every published figure runs
scikit-learn 1.9.0, numpy 2.5.0 and pandas 3.0.3 on Python 3.13.
`Data/trained_model.joblib` is gitignored but was not dockerignored.

## 3. The pre-registered benchmark

Plan: `docs/ML_ENHANCEMENT_PLAN.md`, committed before any candidate was scored
(`fcfeff0`). Harness: `scripts/benchmark_served_path.py`. Results:
`Data/served_path_benchmark.json`.

- **Protocol.** Leave one recording out over all 81. Train on the clean corpus.
  Perturb the held-out recording with each of the 11 variants in
  `scripts/evaluate_robustness.py`, then replay it frame by frame through
  `LivePipeline`. The estimator, features, operating point and gates are fixed.
- **Harness check: passed.** The offline replay reproduces `Data/metrics.json`
  exactly.
- **Candidates.** C1 trains on served deltas. C2 is C1 with noise augmentation at
  sd 45/90/135, deliberately not the test levels. C3 is C1 trained on active
  frames only. C4 is C2 and C3 combined.
- **Rule.** Checked against the served reference: no clean loss of detections or
  gain of false alarms; alarm burden at most 1.10x; latency at most one frame
  later; file vote at most one recording worse. Robustness must pass a
  file-clustered sign test at 0.05/4. Pooled and per-variant harm limits apply.

Clean row and pooled perturbations (copied from the plan's section 9, which was
generated from the JSON):

| scored | clean detected | clean FA recordings | clean alarms/h | clean median latency | perturbed detected (pooled) | perturbed FA recordings (pooled) |
|---|---|---|---|---|---|---|
| C0_offline | 40/40 | 2/41 | 7.8 | 5.60 s | 318/400 | 15/410 |
| C0_served | 39/40 | 2/41 | 5.2 | 7.28 s | 320/400 | 10/410 |
| C1 | 38/40 | 1/41 | 2.6 | 6.72 s | 320/400 | 7/410 |
| C2 | 39/40 | 6/41 | 15.5 | 6.72 s | 377/400 | 47/410 |
| C3 | 38/40 | 1/41 | 2.6 | 7.00 s | 329/400 | 7/410 |
| C4 | 38/40 | 4/41 | 10.4 | 6.72 s | 376/400 | 40/410 |

Decision: **no candidate adopted.**

- C3 passes the robustness test (14 recordings gained, 3 lost, p = 0.0064) and
  halves the clean alarm burden. It misses `A_HPull_07` on clean data, and the
  rule allows no clean loss.
- C2 and C4 lift the sd 120 variant from 9/40 to 34/40 and 37/40, at 6/41 and
  4/41 clean false-alarm recordings.

**Deployment finding.** Trained clean and run on a noisier board, the served
detector finds 27/40 events at sd 30, 14/40 at sd 60 and 9/40 at sd 120. The
published sweep retrains on the noise and reports 37, 35 and 24.

## 4. What changed

**`main.py`**

- `compute_oof(..., served=[...])` has each fold's model also stream its held-out
  recording through `LivePipeline`, on the same fit (`replay_levels`).
- `_episode_figures` is the one definition of sensitivity, false alarms,
  alarms/hour and latency. It is now shared by `evaluate_stream` (offline) and
  the new `evaluate_served`.
- `write_report` writes `served_episode_level` to `Data/metrics.json` and a served
  section to `Data/METRICS.md`.
- `verify_metrics` re-measures the served figures. Times to alarm are compared
  to within one frame, since they are counted in frames. Rates stay at 2%.
- `load_persisted_model` refuses a cache written by a different scikit-learn.

**Tests** (218, up from 215):

- `E5`: the served replay is `LivePipeline`, noise gate included.
- `R9b`: a tampered served figure makes `metrics.json` stale.
- `R9c`: a cache from another scikit-learn is retrained, not unpickled.
- `test_invariant_9` now reuses the collected `test_regressions` module. The
  81-fold pass used to run twice (220 s + 218 s).

**Deploy**

- `requirements.txt` pins scikit-learn, numpy, scipy, pandas and joblib.
- Dockerfile and CI moved to Python 3.13; the Dockerfile trains the model at
  build time.
- `.dockerignore` and `.gcloudignore` exclude the model cache.
- `DEPLOY_GOOGLE.md` records what was and was not verified.

**Docs**

- Served-path metric blocks in `README.md`, `docs/ACTION_PLAN.md` and the
  progress report.
- `README.md`'s operating-curve rows re-copied from `METRICS.md`; four were stale.
- `AGENTS.md` and `.agents/rules/verifying.md` updated.

## 5. Headline figures as published now

<!-- metrics:episode_headline_en -->
Episode-level, out-of-fold, 7-of-6 hold 9: sensitivity **100.0%** [91.2–100.0], false alarm **4.9%** per recording [1.3–16.1] = **7.8 alarms/hour**, median time-to-alarm **5.60 s** (worst 17.36 s), 0 missed events. Source: `Data/metrics.json` (2026-09-23, v6.2).
<!-- /metrics:episode_headline_en -->

<!-- metrics:served_headline_en -->
Served path (every recording streamed through LivePipeline), out-of-fold, 7-of-6 hold 9: sensitivity **97.5%** [87.1–99.6], false alarm **4.9%** per recording [1.3–16.1] = **5.2 alarms/hour**, median time-to-alarm **7.28 s** (worst 17.36 s), 1 missed (Vertical Pull NO G/A_VPull_06.csv). Source: `Data/metrics.json` (2026-09-23, v6.2).
<!-- /metrics:served_headline_en -->

<!-- metrics:file_level_en -->
File-level (file CV, 1 seeds, 81 files / 3349 frames / 34 features): accuracy **97.5%**, macro F1 **0.9612**. Source: `Data/metrics.json` (2026-09-23, v6.2).
<!-- /metrics:file_level_en -->

## 6. Deployment readiness (Cloud Run)

| item | state | evidence |
|---|---|---|
| Numeric stack reproduces the published figures | yes, on the workstation | fresh Python 3.13 venv from `requirements.txt`: `--verify-metrics` OK, served figures included |
| The old image stack | reproduced every rate; served latency moved one frame | Python 3.11 venv with the old ranges (scikit-learn 1.8.0) |
| Model in the image | trained at build time by the image's own scikit-learn | simulated: build step 2.7 s fit, start loads without retrain in 1.5 s |
| Stale pickle shipped | no longer possible | cache excluded from build context; version guard in `load_persisted_model` |
| Public bind without a key | refuses, exit 2 | same simulation |
| `--allow-public-no-key` in the Dockerfile | absent | invariant 6 tests |
| `$PORT` | `CMD` uses `${PORT:-8081}`; Cloud Run sets `PORT` | Dockerfile |
| Non-root | uid 10001, `Data/` owned by it | Dockerfile |
| Not exercised here | Docker build, a Linux run of the pinned stack, websockets behind Cloud Run's proxy | no Docker daemon or Linux host on the workstation |

The first Linux run of the pinned stack will be CI on Python 3.13. The
time-to-alarm check tolerates exactly one frame for that reason. A larger move
means the platform changes the model, and it should be investigated, not
tolerated.

## 7. The nine invariants

| # | invariant | how it was checked |
|---|---|---|
| 1 | the browser never classifies | `test_invariant_1`, untouched `web/` |
| 2 | no hand-coded probability in `classify_deltas()` | `t_no_handcoded_proba`, `test_invariant_2`; the function is unchanged |
| 3 | no invented patient identity | `test_invariant_3` |
| 4 | `data-metric` slots measured or blank | `test_invariant_4`; `index.html` unchanged |
| 5 | `SPEC_DETACH_MAX` 25000, f-string label, 0/81 | `test_spec_reachability.py`, `t_spec_label_matches_constant`, audit output |
| 6 | no `--allow-public-no-key` in the Dockerfile | `test_invariant_6`, `test_next_gen_features` |
| 7 | no emoji | `test_invariant_7` |
| 8 | "certified" only negated; IEC 62304 notice in `index.html` and `app.js` | `test_dashboard_claims_no_medical_certification`, `test_invariant_8` |
| 9 | `metrics.json` reproduces via `--verify-metrics`, never hand-edited | regenerated by `--report --stream --stamp 2026-09-23`; `run.py verify` OK; `test_invariant_9`, `t_metrics_not_stale` |

## 8. For the owner to decide

1. **Which figure goes on stage.** The offline row and the served row are both
   published and both reproducible. Only the served one describes the device.
   The docs now show both; which one headlines the paper is your call.
2. **Round 2.** Pre-register C3 and C4 unchanged against the round-2 corpus. That
   is the first data they would be measured on without having been chosen on it.
3. **Frame-level labels.** The 58 sub-gate votes come from labelling every frame
   of a recording with its class. Event boundaries from the OBS sync procedure
   (`docs/OBS_STUDIO_GROUND_TRUTH_SYNC_GUIDE.md`) would let training use event
   frames only.
4. **Noise.** A board noisier than the bench loses sensitivity fast. The
   `jitter_noise_counts` telemetry already reports the noise floor. Whether the
   console should warn when it leaves the validated range is a product decision;
   nothing was added.
5. **Merge.** `ml/served-path-benchmark` is local and not pushed.

## 9. Verification of this branch

Final gates were run on the finished tree. Logs are in `D:\Projects\_p2_agent`.

| gate | workstation environment | fresh Python 3.13 venv from `requirements.txt` |
|---|---|---|
| `python run.py test` | **218 passed**, 1 warning, 728.54 s | **218 passed**, 1 warning, 730.80 s |
| `python run.py verify` | OK: rates within 2%, times to alarm within one frame, served path included | OK (same check) |
| `python run.py pads` | rho 1.0000, 0 inversions, exit 0 | — |
| `python run.py audit Data` | exit 2, output byte-identical to the baseline run | — |
| `scripts/sync_metrics_blocks.py --check` | 10 blocks match `Data/metrics.json` | — |
| flake8 (`F`, `E9`) on the changed Python files | clean | — |

The suite is 2.5 minutes shorter than the 215-test baseline (875.56 s) even with
three more checks, because the 81-fold pass now runs once. The one warning is
Starlette's own deprecation notice for `httpx`. It was present before this work.

Commits on `ml/served-path-benchmark`, all on top of `origin/master` (`45bc389`):

1. `fcfeff0` pre-registration: plan and harness, before any scoring
2. `fff283a` benchmark results; no candidate adopted
3. `9460a38` served-path figures published and verified
4. `282b316` deploy: pinned stack, Python 3.13 image, build-time model
5. this review
