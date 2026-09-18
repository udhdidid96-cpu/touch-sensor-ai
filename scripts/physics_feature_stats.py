#!/usr/bin/env python3
"""Per-scenario medians and IQRs of the 9 statistics, measured from Data/.

Why this exists
---------------
`docs/PHYSICS_TO_FEATURE_MAP.md` is a one-page answer to the supervisor's
question "which feature sees which physical effect". Every number on that page
has to come from the corpus, not from a plausible guess (AGENTS.md, invariant 4
and the "measure before claiming" rule). This script is where those numbers come
from; re-run it and the page can be checked line by line.

What it measures
----------------
For each scenario folder group, every post-warmup frame of every recording is
calibrated through the shipped offline path - `calibrate(raw, "kalman")`, the
same call `load_dataset` makes for `Data/metrics.json` - and reduced to the 9
frame statistics of the 34-feature vector. Reported per statistic: median and
the 25th-75th percentile range across frames.

Frames 0..KALMAN_WARMUP-1 are dropped because the Kalman baseline is still
settling there and the console holds Level 0 over exactly those frames; keeping
them would put the settling transient into the medians.

Percentiles, not mean +/- sd: several of these distributions are counts bounded
at zero and heavily skewed (Drop Count is 0 on most normal frames), where a
standard deviation describes nothing anyone can act on.

    python scripts/physics_feature_stats.py

Writes Data/physics_feature_stats.json and prints the table. Changes no
threshold and touches no model.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from typing import Dict, List

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

# Folder groups, identical to scripts/evaluate_5_scenarios.py so the two
# documents cannot describe different partitions of the same corpus.
SCENARIOS: Dict[str, List[str]] = {
    "1. Baseline":            ["N_base"],
    "2a. Brief Touch":        ["Brief Touch"],
    "2b. Sustained Press":    ["Press"],
    "3. Friction":            ["Friction"],
    "4a. Vertical Pull":      ["Vertical Pull NO G"],
    "4b. Horizontal Pull":    ["Horizontal Pull NO G"],
    "4c. Power Pull":         ["PowerP"],
    "5. Peeling":             ["Peel"],
    "6. Normal Mix":          ["Normal Mix"],
}


def _stats_for(folders: List[str]) -> Dict[str, object]:
    frames: List[np.ndarray] = []
    n_files = 0
    for folder in folders:
        for path in sorted(glob.glob(os.path.join(main.DATA_ROOT, folder, "*.csv"))):
            raw = main.read_raw_csv(path)
            if raw is None or len(raw) <= main.KALMAN_WARMUP:
                continue
            delta = main.calibrate(raw, "kalman")[main.KALMAN_WARMUP:]
            # include_pads=False -> the 9 statistics only; the 25 pad deltas are
            # per-pad and have no meaningful scenario-level median.
            frames.append(main.extract_features(delta, use_gradient=False, include_pads=False))
            n_files += 1
    if not frames:
        return {"files": 0, "frames": 0, "stats": {}}

    mat = np.vstack(frames)
    out: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(main.BASE_FEATURE_NAMES):
        col = mat[:, i]
        q25, med, q75 = (float(v) for v in np.percentile(col, [25, 50, 75]))
        out[name] = {"median": round(med, 1), "q25": round(q25, 1), "q75": round(q75, 1)}
    return {"files": n_files, "frames": int(len(mat)), "stats": out}


def main_cli() -> int:
    results = {name: _stats_for(folders) for name, folders in SCENARIOS.items()}

    shown = ["Min Delta", "Max Delta", "Mean Delta", "Drop Count (<= -300)", "Spike Count (>= +300)"]
    print(f"{'scenario':22s} {'files':>5s} {'frames':>7s} " + " ".join(f"{s[:13]:>21s}" for s in shown))
    for name, r in results.items():
        if not r["frames"]:
            print(f"{name:22s} {'-':>5s} {'-':>7s}  (no recordings)")
            continue
        cells = []
        for s in shown:
            v = r["stats"][s]
            cells.append(f"{v['median']:>9.1f} [{v['q25']:.0f},{v['q75']:.0f}]".rjust(21))
        print(f"{name:22s} {r['files']:5d} {r['frames']:7d} " + " ".join(cells))

    payload = {
        "generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "calibration": "kalman",
        "protocol": (f"post-warmup frames only (frames 0..{main.KALMAN_WARMUP - 1} dropped); "
                     "median and 25th-75th percentile across all frames of all files in the group"),
        "caveat": ("single session (S0), one mounting, one operator - these distributions "
                   "characterise this corpus, not a population of patches"),
        "gates_for_reference": {
            "lift_gate_counts": -main.DELTA_THRESHOLD,
            "noise_gate_counts": main.NOISE_GATE_COUNTS,
            "peel_mean_gate_counts": main.PEEL_MEAN_GATE,
            "peel_min_pads": main.PEEL_MIN_PADS,
        },
        "scenarios": results,
    }
    out_path = os.path.join(main.DATA_ROOT, "physics_feature_stats.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
