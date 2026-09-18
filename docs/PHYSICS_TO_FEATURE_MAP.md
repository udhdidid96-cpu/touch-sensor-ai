# Physics to Feature Map

**One page for the supervisor: which physical effect each scenario produces, and
which of the 34 features sees it.**

No new measurement was taken for this page. Every number below is the median and
25th-75th percentile of post-warmup frames across the 81 round-1 recordings,
produced by:

```bash
python scripts/physics_feature_stats.py     # writes Data/physics_feature_stats.json
```

The calibration is `calibrate(raw, "kalman")` — the same offline path
`load_dataset` uses for `Data/metrics.json`. Frames 0-4 are dropped because the
Kalman baseline is still settling over `KALMAN_WARMUP = 5` and the console holds
Level 0 there. Percentiles rather than mean ± sd, because the count features are
bounded at zero and heavily skewed; a standard deviation would describe nothing
anyone can act on. `tests/test_physics_feature_map.py` fails if this page and
that JSON disagree.

---

## 1. The measurement

Delta values are counts against the tracked baseline. 59.85 counts/pF
(**[MEASURED]**, `docs/Hardware_Deck_Spec.md`), so 300 counts is about 5.0 pF.

| scenario | files | frames | Min Delta | Max Delta | Mean Delta | Std Delta |
|---|---:|---:|---:|---:|---:|---:|
| 1. Baseline | 5 | 564 | -14.7 [-18, -12] | 19.6 [15, 26] | 1.2 [-1, 4] | 8.6 [7.7, 9.9] |
| 2a. Brief Touch | 10 | 584 | -534.7 [-591, -38] | 925.5 [95, 2437] | 31.8 [-8, 108] | 235.9 [148.9, 507.2] |
| 2b. Sustained Press | 11 | 535 | -134.3 [-361, -28] | 2373.5 [881, 3595] | 149.5 [68, 193] | 571.1 [281.8, 710.8] |
| 3. Friction | 10 | 312 | -36.6 [-47, -26] | 110.4 [64, 177] | 8.0 [-2, 22] | 36.3 [24.2, 48.4] |
| 4a. Vertical Pull | 10 | 76 | -179.9 [-649, -20] | 370.2 [10, 556] | 4.7 [-54, 130] | 169.4 [135.7, 188.2] |
| 4b. Horizontal Pull | 10 | 237 | -14.4 [-28, -6] | 216.1 [18, 425] | 23.1 [-3, 94] | 51.4 [13.5, 116.0] |
| 4c. Power Pull | 10 | 189 | -21.5 [-79, -3] | 19.6 [10, 638] | -3.6 [-16, 170] | 117.1 [11.4, 210.1] |
| 5. Peeling | 10 | 166 | -851.0 [-872, -819] | -17.8 [-29, -7] | -328.7 [-356, -314] | 270.9 [251.2, 277.6] |
| 6. Normal Mix | 5 | 281 | -330.1 [-556, -75] | 347.9 [39, 1267] | -1.1 [-57, 55] | 179.2 [101.4, 315.5] |

Pad-count features, same frames. These count how many of the 25 pads cross a gate
in a single frame.

| scenario | Drop <= -300 | Drop <= -600 | Drop <= -1000 | Spike >= +300 | Spike >= +1000 |
|---|---:|---:|---:|---:|---:|
| 1. Baseline | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| 2a. Brief Touch | 1 [0, 2] | 0 [0, 0] | 0 [0, 0] | 1 [0, 2] | 0 [0, 1] |
| 2b. Sustained Press | 0 [0, 1] | 0 [0, 0] | 0 [0, 0] | 1 [1, 4] | 1 [0, 1] |
| 3. Friction | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| 4a. Vertical Pull | 0 [0, 2] | 0 [0, 1] | 0 [0, 0] | 2 [0, 4] | 0 [0, 0] |
| 4b. Horizontal Pull | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 1] | 0 [0, 0] |
| 4c. Power Pull | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | 0 [0, 6] | 0 [0, 0] |
| 5. Peeling | 10 [9, 11] | 6 [4, 6] | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| 6. Normal Mix | 1 [0, 3] | 0 [0, 0] | 0 [0, 0] | 1 [0, 2] | 0 [0, 1] |

Reference gates, for reading the tables: lift **-300** counts, noise **60**
counts, peel whole-grid mean **-150** counts over at least **3** pads.

---

## 2. Baseline — nothing is happening, and that is a measurement

The patch is attached and untouched. $C$ sits at $C_0$; the only variation is
front-end noise. **Measured Std Delta is 8.6 counts [7.7, 9.9]** — that is this
board's noise floor, and it is why the 60-count noise gate sits about seven times
above it. Every one of the five count features is exactly 0 on the median frame.

The feature that carries baseline is **Std Delta**, and its job is to say
"nothing is happening" rather than to detect anything.

## 3. Touching — a grounded conductor enters the fringing field

A finger is a large grounded conductor. Two effects add: fringing field lines
that would have returned to the receive pad terminate on the finger instead, and
pressing compresses the backing so the local $d$ in $C = \varepsilon A / d$ falls.
Both push counts **up**.

**Measured: the press side is the signature, and it is large.** Sustained Press
reaches a median Max Delta of **+2373.5 counts** (about 40 pF) with `Spike >= +300`
at 1 [1, 4] pads, while its `Drop <= -300` median stays at 0. Brief Touch is the
same mechanism with less force and less dwell: Max Delta +925.5, Mean Delta +31.8
against the press's +149.5.

Features: **Max Delta** and the two **Spike Count** features. **Mean Delta** stays
positive, which is what separates a press from a peel — see §6.

## 4. Friction — shear without normal displacement

Cloth sliding over the patch is almost pure shear. The dielectric gap $d$ barely
changes, and fabric is a poor conductor, so it loads the fringing field weakly.

**Measured: friction is the quietest non-baseline scenario in the corpus.** Min
Delta -36.6, Max Delta +110.4, Std Delta 36.3, and **all five count features are 0
across the whole interquartile range**. Friction never reaches the -300 lift gate,
and on the negative side it barely reaches the 60-count noise gate. That is the
measured reason friction contributes 0/10 false alarms.

## 5. Pulling — tube displacement through the adhesive, and it depends on direction

**Vertical pull** transmits normal displacement, so pads genuinely lift: Min Delta
-179.9 with a 25th percentile of **-649**, and `Drop <= -300` reaching 2 pads at
the 75th percentile. Note the frame count: **76 usable post-warmup frames across
10 files** — by far the thinnest scenario in the corpus, because these recordings
are short and the event is a small fraction of each. Medians here rest on little
data and should be read as such.

**Horizontal pull is the blind spot, and the numbers say so plainly.** Its median
Min Delta is **-14.4 counts against Baseline's -14.7** — the lift channel sees
nothing at all. What does move is the press side: Max Delta +216.1, Mean Delta
+23.1. Shear does not change $d$, so the only thing the patch registers is the
contact artifact of the tube and hand as they are drawn sideways. This is why
horizontal pull detects 0/10 today, and it is the measured argument for the
conductive ground plane: turning fringing coupling into parallel-plate coupling
is what would give lateral displacement a capacitance to change.

**Power pull** is real but sparse in time. Its median Max Delta is +19.6 while the
75th percentile is **+638**, and `Spike >= +300` is 0 at the median but 6 at the
75th percentile. A high-velocity event occupies a handful of frames out of 189, so
the median understates it and the upper quartile is the honest column to read.

## 6. Peeling — the whole patch lifts at once, and only peeling does that

Adhesive separation increases $d$ over an **area**, not a point. This is the one
scenario where every pad moves the same way.

**Measured: Peel is the only scenario whose median Max Delta is negative,
-17.8 counts.** Even the least affected pad in the median frame sits below
baseline. Mean Delta is **-328.7 [-356, -314]**, past the -150 peel gate by a
factor of two; Min Delta is -851.0; `Drop <= -300` is **10 pads** and `Drop <= -600`
is **6 pads** on the median frame.

Features: **Mean Delta** is the discriminator — it is the only feature that
separates "many pads down together" from "one pad down while others are pressed".
The **Drop Count** trio quantifies how far the separation has spread. This
combination is what the peel tracker keys on (`PEEL_MEAN_GATE = -150`,
`PEEL_MIN_PADS = 3`), and why peel measures 10/10.

---

## 7. The 34 features, and what each group is for

| feature group | count | physical quantity | primary scenario |
|---|---:|---|---|
| `Pad-1..25 Delta` | 25 | per-pad $\Delta C$, in physical pad order | **where** — the only features that can tell a peel front at one edge from a uniform lift |
| `Min Delta` | 1 | deepest single-pad lift | detachment depth (peel, vertical pull) |
| `Max Delta` | 1 | strongest single-pad press | contact and shear artifact (press, touch, horizontal pull) |
| `Mean Delta` | 1 | whole-patch offset | **peel vs press** — the sign separates them |
| `Std Delta` | 1 | spatial spread across pads | activity vs rest; carries the noise floor |
| `Drop Count (<= -300 / -600 / -1000)` | 3 | how many pads are lifting, and how far | peel extent |
| `Spike Count (>= +300 / +1000)` | 2 | how many pads are pressed | touch and press extent |

25 + 9 = 34. The two gradient features (`Grad Magnitude`, `Grad Anisotropy`) exist
in `extract_features` but are **off** in the shipped configuration
(`use_gradient=False`), so they are not part of the 34 and no figure measures them.

---

## 8. What this page cannot say

- **Single session (S0).** One mounting, one operator, one day. These are the
  distributions of this corpus, not of a population of patches. The nearest
  available substitute is `Data/robustness_evaluation*.json`, which perturbs these
  same recordings; it is not cross-session generalisation.
- **Frame-level, not episode-level.** These are per-frame distributions. Detection
  performance is an episode-level question answered by
  `scripts/evaluate_5_scenarios.py` and the 7-of-6 hold-9 annunciator, not by any
  median in the tables above.
- **Vertical pull rests on 76 frames.** Fewer than any other scenario by a factor
  of two. Round 2 should record longer pull episodes.
- **The class labels are coarser than the folders.** Brief Touch, Press, Friction
  and Normal Mix all carry label 1; all three pull folders carry label 3. The
  tables split by folder because the physics differs even where the label does not.

---

## 9. One corpus finding that came out of building this page

Brief Touch has a median Min Delta of **-534.7 counts**, deeper than the -300 lift
gate, in a folder of recordings labelled normal. That is not a touch transient. Per
file, six of the ten recordings sit at a **persistent** floor for their whole
length — median and minimum within about 25 counts of each other:

```
N_Touch_02   median min -791.8    N_Touch_06   median min -808.2
N_Touch_03   median min -553.9    N_Touch_10   median min -598.3
N_Touch_04   median min -549.0    N_Touch_05   median min -534.2
```

The cause is an **inflated Kalman seed on individual pads**. In `N_Touch_02`, pad 2
seeds at 28,718 counts (mean of the first five frames) while its median for the
rest of the file is 27,926 — the recording was started with a finger already on
that pad. Every subsequent frame then reads about -790 against a baseline that was
never valid. Pad 15 in the same file: seed 28,384, rest-of-file median 27,912.
`N_Touch_06`, pad 1: seed 28,789, rest-of-file median 27,981. The raw absolute
values of these pads are entirely normal; only the baseline they are measured
against is wrong.

**`seed_plausibility()` does not catch this, by construction.** It takes the median
across all 25 pads, and in both files that whole-frame median is 28,199 counts —
comfortably inside `ATTACHED_SEED_BAND`, so it reports `attached_band`. A median
over 25 channels is exactly the statistic that hides one or two elevated ones. It
catches the whole-patch case it was built for (10 of 11 Press recordings start
mid-press and are correctly flagged `above_band`) and misses the per-pad case.

Two consequences worth putting in front of the supervisor:

1. **Some of the measured false-alarm rate may be an artifact of how recordings
   were started**, not of the detector. Six normal files carry a permanent
   sub-gate phantom lift.
2. **The fix is procedural before it is algorithmic.** SOP v2 should require a
   clean untouched patch for the first second of every recording. In software, a
   per-pad seed check — flagging any channel whose seed sits far from the
   corpus-wide resting band — would cover the case the median check cannot. That
   is proposed, not implemented; nothing in this repository does it today.
