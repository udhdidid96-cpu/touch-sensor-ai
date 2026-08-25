# Estimator selection — measured 2026-08-19

**Only one estimator ships.** `main.py` fits a single
`HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced")`
on the 34-feature matrix. Random Forest and Extra Trees appear here for one
reason: to make that choice defensible with numbers rather than assertion.

Reproduce:

```
python benchmark_ml_architectures.py --repeats 100     # the table below
python benchmark_ml_architectures.py                   # single-LOFO leaderboard
```

Figure: `Data/research_plots/model_comparison_2026-08-19.png`.

---

## Protocol

- **100 repeats of grouped 5-fold cross-validation per estimator** — 1,500 model
  fits in total. The fold split is re-drawn every repeat; **groups are
  recordings**, so no frame from a file is ever in both train and test.
- Identical folds, identical 34-feature matrix (25 pad deltas + 9 statistics)
  and identical Kalman calibration for all three. The estimator is the only
  variable.
- File-level figures use the project's own majority vote (ties break toward the
  more severe class). Episode figures are each repeat's out-of-fold predictions
  replayed through `AlarmDebouncer` at the shipped operating point.
- Why not 100 × leave-one-file-out: that is 8,100 fits per estimator. With 81
  recordings, *which files land in which fold* moves the result by more than the
  gap between two estimators, so re-drawing the split is exactly the variation
  worth sampling — and k-fold samples it at 5 fits a repeat.

## Results — mean ± standard deviation over 100 repeats

| Estimator | File acc. | Frame acc. | Macro F1 | Pull recall | Peel recall | Episode sens. | Alarms/h | FA/recording |
|---|---|---|---|---|---|---|---|---|
| Random Forest (200, d12) | 96.53% ± 1.00 | 85.19% ± 0.46 | 0.952 ± 0.012 | 0.940 ± 0.027 | 1.000 ± 0.000 | 86.8% ± 3.2 | 6.92 ± 3.13 | 5.24% ± 2.15 |
| Extra Trees (200, d12) | 87.09% ± 1.06 | 80.26% ± 0.53 | 0.823 ± 0.010 | 0.691 ± 0.028 | 1.000 ± 0.000 | 90.4% ± 2.2 | 10.80 ± 2.83 | 7.98% ± 1.42 |
| **HistGradientBoosting (150, d8)** | **98.44% ± 0.62** | **86.44% ± 0.43** | **0.967 ± 0.007** | **0.991 ± 0.016** | 1.000 ± 0.000 | **98.2% ± 1.9** | 7.93 ± 1.76 | 5.27% ± 1.19 |

File-level accuracy range over the 100 repeats: RF 93.83–98.77, ET 83.95–88.89,
**HGB 96.30–100.00**.

## Paired comparison (same 100 fold-splits for every estimator)

| Comparison | Mean difference | HGB better in | Wilcoxon signed-rank |
|---|---|---|---|
| HGB vs RF — file accuracy | +1.91 pp | 89/100 (10 ties, 1 loss) | p = 7 × 10⁻¹⁷ |
| HGB vs RF — pull recall | +0.051 | 89/100 (10 ties) | p = 7 × 10⁻¹⁷ |
| HGB vs RF — episode sensitivity | +11.4 pp | 100/100 | p = 3 × 10⁻¹⁸ |
| HGB vs ET — file accuracy | +11.36 pp | 100/100 | p = 2 × 10⁻¹⁸ |
| HGB vs ET — pull recall | +0.300 | 100/100 | p = 2 × 10⁻¹⁸ |
| HGB vs ET — episode sensitivity | +7.8 pp | 99/100 (1 tie) | p = 2 × 10⁻¹⁸ |

## Why HistGradientBoosting

1. **It wins on the metric the device is judged by.** Episode sensitivity 98.2%
   against 86.9% for the forest — about eleven percentage points, which over 40
   anomaly recordings is four to five real extubation events per pass. It leads
   in 100 of 100 repeats.
2. **It is the steadiest.** Lowest SD on file accuracy (0.62 vs 1.00 / 1.06), on
   pull recall (0.016 vs 0.027 / 0.028), on episode sensitivity (1.9 vs 3.2) and
   on alarm burden (1.76 vs 3.13 per hour). For a patch re-attached to a new
   patient every shift, the estimator that moves least when the data changes is
   worth as much as the one with the best average.
3. **It is fastest where speed is used.** 0.127 ms per frame at inference
   against ~1.04 ms for both tree ensembles — 8×. It is ~1.5× slower to *fit*
   (1.43 s vs 0.97 s per fold), which a device that trains once and caches to
   `Data/trained_model.joblib` never pays at the bedside.
4. **Extra Trees is not competitive.** Randomised split thresholds cost it pull
   recall outright: 0.691 against 0.991. Pull is the class where a miss harms
   someone.

**The one column it does not lead:** Random Forest averages a slightly quieter
6.92 alarms/hour against 7.93 — but pays 11.4 points of sensitivity for it,
which is the wrong side of that trade for a safety device.

**Peel recall is 1.000 ± 0.000 for all three.** That class separates on this
corpus whatever you fit, so it is not evidence for any of them; do not quote it
as a differentiator.

## What this does not show

Every figure here comes from a corpus recorded on a **single sensor mounting**,
so none of it demonstrates generalisation to a re-attached patch. Horizontal
Pull produces **no lift signal on this patch at all** — a physical limit no
estimator can fix (see the caveats in `METRICS.md`). This comparison establishes
which of the three to ship. It does not establish that the device detects every
extubation.

---

## Retraction — the 2026-08-17 leaderboard

The previous version of this file reported **HistGradientBoosting at 100.00%
LOFO accuracy, macro F1 1.0000, 100% pull recall, 0% false alarms**, and it was
the document that justified the production swap. It was wrong in three ways:

1. **It reported a feature set it did not run.** Every row captioned
   "36 Feats (25 Pads + 11 Stats)" was measured on a **61-column** matrix —
   `build_raw_and_feature_matrix()` hstacked the 25 pad deltas in front of
   `extract_features(...)`, which already returns those same 25 columns. Every
   pad delta was present twice. The row captioned "11 Feats" ran on 34.
2. **The 100.00% was a single draw on one split.** On the production 34 columns,
   leave-one-file-out, the same estimator scores 97.53% — and over 100 repeats,
   98.44% ± 0.62. A perfect score over 81 files should have been read as a bug
   report.
3. **It compared on the wrong unit.** File-level accuracy depends on clip
   length, which is why this project leads with the episode metric. Nothing in
   that leaderboard measured alarm burden, and alarm burden is what moved most
   when the estimator changed.

The duplication and the captions are fixed in `benchmark_ml_architectures.py`.
The ensemble, MLP and ResNet rows have **not** been re-run since and are
therefore not carried over.
