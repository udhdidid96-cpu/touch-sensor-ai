#!/usr/bin/env python3
"""Robustness of the shipped detector to sensor-level perturbations.

Why this exists
---------------
Every published figure comes from one sensor mounting: 81 recordings, one day,
one operator, one attachment. ``--cv session`` - the honest answer to "does it
generalise to a new patch" - cannot run until round 2 exists. This script
answers the narrower question that CAN be answered today:

    Does the detector depend on incidental constants of this one setup?

It re-runs the exact out-of-fold episode evaluation behind ``Data/metrics.json``
(``compute_oof`` + ``evaluate_stream``, 7-of-6 hold 9) with the RAW COUNTS
perturbed *before* baseline calibration and feature extraction, so the Kalman
tracker, the 34 features and the model see the perturbation the way they would
see a different patch, a noisier board, or a flaky serial link.

What each perturbation stands for
---------------------------------
  gain_global_pNN / mNN  every count scaled by 1 +/- NN% - a different resting
                     C0 (another patch, thinner backing, other skin). F10 was
                     built for this; note that F10 lives in LivePipeline and
                     NOT in the offline calibrate() path that produces the
                     metrics, so this measures the offline path as shipped.
  gain_per_pad_10    each pad scaled by its own factor in [0.90, 1.10] -
                     pad-to-pad manufacturing spread on a second patch.
  noise_sdNN         white noise of NN counts added to every count. The
                     physics noise gate is 60 counts; SOP criterion 5 allows a
                     100-count baseline swing.
  frame_drop_10      10% of frames removed at random - serial dropouts.
  spike_1pct         1% of frames get one pad bumped by +5,000 counts. This is
                     UNDER the 50,000-count surge filter on purpose, so it is
                     the model and the debouncer that have to absorb it.

What this does NOT show
-----------------------
It is not a substitute for round 2. A synthetic gain is not a re-attached
patch: it cannot reproduce a changed contact area, a different adhesive, or a
horizontal-pull signature that this rig has never produced. Report these
figures as "robustness to modelled sensor variation", never as "cross-session
generalisation", and keep the round-2 plan.

Usage
-----
    python scripts/evaluate_robustness.py            # all variants, ~20 min
    python scripts/evaluate_robustness.py --quick    # identity + two variants
    python scripts/evaluate_robustness.py --variants identity,noise_sd60

Writes Data/robustness_evaluation.json and prints a table. Nothing here
changes a threshold, retrains anything into the model cache, or touches
Data/metrics.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Callable, Dict, List

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

Perturb = Callable[[np.ndarray, np.random.Generator], np.ndarray]


def _identity(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return raw


def _gain_global(factor: float) -> Perturb:
    def f(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return raw * factor
    return f


def _gain_per_pad(spread: float) -> Perturb:
    def f(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        g = rng.uniform(1.0 - spread, 1.0 + spread, size=raw.shape[1])
        return raw * g[None, :]
    return f


def _noise(sd_counts: float) -> Perturb:
    def f(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        return raw + rng.normal(0.0, sd_counts, size=raw.shape)
    return f


def _frame_drop(fraction: float) -> Perturb:
    def f(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        keep = rng.random(len(raw)) >= fraction
        keep[0] = True          # the Kalman seed stays the frame it would be live
        if keep.sum() < main.MIN_FRAMES_PER_FILE:
            return raw
        return raw[keep]
    return f


def _spike(fraction: float, magnitude: float) -> Perturb:
    def f(raw: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        out = raw.copy()
        for i in np.nonzero(rng.random(len(out)) < fraction)[0]:
            out[i, rng.integers(out.shape[1])] += magnitude
        return out
    return f


VARIANTS: Dict[str, Perturb] = {
    "identity":        _identity,
    "gain_global_p10": _gain_global(1.10),
    "gain_global_m10": _gain_global(0.90),
    "gain_global_p20": _gain_global(1.20),
    "gain_global_m20": _gain_global(0.80),
    "gain_per_pad_10": _gain_per_pad(0.10),
    "noise_sd30":      _noise(30.0),
    "noise_sd60":      _noise(60.0),
    "noise_sd120":     _noise(120.0),
    "frame_drop_10":   _frame_drop(0.10),
    "spike_1pct":      _spike(0.01, 5000.0),
}
QUICK = ["identity", "gain_global_p20", "noise_sd60"]


def _rng_for(path: str, variant: str) -> np.random.Generator:
    """Deterministic per file and per variant, so a re-run reproduces."""
    key = f"{variant}:{os.path.basename(path)}".encode("utf-8")
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key).digest()[:8], "big"))


def run_variant(name: str, perturb: Perturb, seed: int = 42,
                calibration: str = "kalman") -> Dict[str, object]:
    original = main.read_raw_csv

    def patched(path: str, *args, **kwargs):
        raw = original(path, *args, **kwargs)
        if raw is None:
            return None
        return perturb(np.asarray(raw, dtype=float), _rng_for(path, name))

    main.read_raw_csv = patched  # type: ignore[assignment]
    t0 = time.time()
    try:
        ds = main.load_dataset(calibration, False, verbose=False)
        if ds is None:
            raise RuntimeError("no dataset under Data/")
        oof = main.compute_oof(ds, seed)
        st = main.evaluate_stream(ds, seed, verbose=False, oof=oof)
    finally:
        main.read_raw_csv = original  # type: ignore[assignment]

    n_anom = int(st["n_anomaly"])
    n_norm = int(st["n_normal"])
    detected = int(round(float(st["sensitivity"]) * n_anom))
    fa_files = int(round(float(st["false_alarm_rate"]) * n_norm))
    lo, hi = main.wilson(detected, n_anom)
    missed = st.get("missed", [])
    return {
        "variant": name,
        "calibration": calibration,
        "files": int(ds.n_files),
        "frames": int(len(ds.X)),
        "sensitivity": float(st["sensitivity"]),
        "sensitivity_ci": [round(lo, 4), round(hi, 4)],
        "detected": detected, "n_anomaly": n_anom,
        "false_alarm_rate": float(st["false_alarm_rate"]),
        "fa_files": fa_files, "n_normal": n_norm,
        "alarms_per_hour": float(st["alarms_per_hour"]),
        "missed": [m.get("file", m) if isinstance(m, dict) else m for m in missed],
        "seconds": round(time.time() - t0, 1),
    }


def main_cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help=f"only {', '.join(QUICK)}")
    ap.add_argument("--variants", default="", help="comma-separated subset")
    ap.add_argument("--calibration", choices=["kalman", "kalman_norm", "static"], default="kalman",
                    help="offline baseline scheme; kalman_norm adds the F10 scale normalisation "
                         "that LivePipeline applies but the shipped offline path does not")
    ap.add_argument("--out", default="",
                    help="output JSON; defaults to Data/robustness_evaluation[_<calibration>].json")
    args = ap.parse_args()
    if not args.out:
        suffix = "" if args.calibration == "kalman" else f"_{args.calibration}"
        args.out = os.path.join(main.DATA_ROOT, f"robustness_evaluation{suffix}.json")

    if args.variants:
        names = [v.strip() for v in args.variants.split(",") if v.strip()]
    elif args.quick:
        names = list(QUICK)
    else:
        names = list(VARIANTS)
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        print(f"unknown variant(s): {', '.join(unknown)}\nknown: {', '.join(VARIANTS)}")
        return 2
    # identity is the row every delta is measured against, so a full or --quick
    # run always starts there. An explicit --variants subset is left alone: on a
    # machine where a long run does not survive, the only way to finish the sweep
    # is one or two variants per process, and re-measuring identity each time
    # costs more than the whole remainder. Deltas are then omitted rather than
    # computed against the wrong baseline, and merging the shards restores them.
    explicit_subset = bool(args.variants)
    if not explicit_subset and names[0] != "identity":
        names = ["identity"] + [n for n in names if n != "identity"]

    results: List[Dict[str, object]] = []
    print(f"{'variant':18s} {'sens':>7s} {'95% CI':>15s} {'FA/rec':>7s} {'alarm/h':>8s} {'missed':>6s} {'sec':>6s}")
    for name in names:
        r = run_variant(name, VARIANTS[name], calibration=args.calibration)
        results.append(r)
        ci = r["sensitivity_ci"]
        print(f"{name:18s} {r['sensitivity']*100:6.1f}% [{ci[0]*100:5.1f},{ci[1]*100:5.1f}] "
              f"{r['false_alarm_rate']*100:6.1f}% {r['alarms_per_hour']:8.1f} "
              f"{len(r['missed']):6d} {r['seconds']:6.1f}", flush=True)

    if results and results[0]["variant"] == "identity":
        base = results[0]
        for r in results[1:]:
            r["delta_sensitivity"] = round(r["sensitivity"] - base["sensitivity"], 4)
            r["delta_alarms_per_hour"] = round(r["alarms_per_hour"] - base["alarms_per_hour"], 2)

    payload = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "calibration": args.calibration,
        "protocol": ("leave-one-file-out, 7-of-6 hold 9, perturbation applied to raw counts "
                     f"before calibrate(raw, '{args.calibration}') and extract_features(); "
                     "'kalman' is the offline path as shipped, 'kalman_norm' adds F10"),
        "caveat": ("robustness to MODELLED sensor variation on one mounting; not cross-session "
                   "generalisation, which needs Data/S1..S3 and --cv session"),
        "operating_point": {"window": 7, "votes": 6, "hold": 9},
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
