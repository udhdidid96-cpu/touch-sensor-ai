#!/usr/bin/env python3
"""Merge sharded evaluate_robustness.py runs into one results file.

Why shards exist
----------------
The full sweep is 11 variants at roughly 200-535 s each - 60 to 90 minutes in a
single process. On a machine where that is not a comfortable thing to leave
running, `evaluate_robustness.py --variants a,b` produces a shard, and this
merges them. Nothing about the measurement changes: each variant is evaluated by
the same `run_variant` on the same corpus with the same per-file seed, so a
variant measured alone is bit-identical to the same variant measured in a batch.

That claim is checked rather than asserted. `identity` appears in more than one
shard, and this script refuses to merge if the copies disagree - which is a real
determinism check on the whole pipeline, not a formality.

Deltas against `identity` are recomputed here, because a shard that does not
contain `identity` deliberately omits them rather than computing them against
the wrong baseline.

    python scripts/merge_robustness_shards.py Data/rob_kn_*.json --out Data/robustness_evaluation_kalman_norm.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any, Dict, List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
from evaluate_robustness import VARIANTS  # noqa: E402

COMPARE_KEYS = ("sensitivity", "false_alarm_rate", "alarms_per_hour", "detected", "fa_files")


def _merge(paths: List[str]) -> Dict[str, Any]:
    by_variant: Dict[str, Dict[str, Any]] = {}
    calibrations = set()
    sources: List[str] = []

    for path in paths:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        calibrations.add(payload.get("calibration", "kalman"))
        sources.append(os.path.basename(path))
        for row in payload["results"]:
            name = row["variant"]
            row = {k: v for k, v in row.items()
                   if k not in ("delta_sensitivity", "delta_alarms_per_hour")}
            if name in by_variant:
                old = by_variant[name]
                disagree = [k for k in COMPARE_KEYS if old.get(k) != row.get(k)]
                if disagree:
                    raise SystemExit(
                        f"'{name}' measured differently in two shards, on {', '.join(disagree)}:\n"
                        f"  {old.get('_source')}: "
                        + ", ".join(f"{k}={old.get(k)}" for k in disagree) + "\n"
                        f"  {os.path.basename(path)}: "
                        + ", ".join(f"{k}={row.get(k)}" for k in disagree) + "\n"
                        "The sweep is supposed to be deterministic per file and variant. "
                        "Do not merge past this; find out why it is not.")
                continue
            row["_source"] = os.path.basename(path)
            by_variant[name] = row

    if len(calibrations) > 1:
        raise SystemExit(f"shards mix calibration modes: {sorted(calibrations)}")

    ordered = [by_variant[n] for n in VARIANTS if n in by_variant]
    ordered += [r for n, r in by_variant.items() if n not in VARIANTS]

    if ordered and ordered[0]["variant"] == "identity":
        base = ordered[0]
        for r in ordered[1:]:
            r["delta_sensitivity"] = round(r["sensitivity"] - base["sensitivity"], 4)
            r["delta_alarms_per_hour"] = round(r["alarms_per_hour"] - base["alarms_per_hour"], 2)

    missing = [n for n in VARIANTS if n not in by_variant]
    return {
        "generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "calibration": calibrations.pop(),
        "merged_from": sources,
        "variants_missing": missing,
        "protocol": ("leave-one-file-out, 7-of-6 hold 9, perturbation applied to raw counts "
                     "before calibrate() and extract_features(); merged from per-variant shards, "
                     "identity cross-checked between shards"),
        "caveat": ("robustness to MODELLED sensor variation on one mounting; not cross-session "
                   "generalisation, which needs Data/S1..S3 and --cv session"),
        "operating_point": {"window": 7, "votes": 6, "hold": 9},
        "results": ordered,
    }


def main_cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shards", nargs="+", help="shard JSON files (globs are expanded)")
    ap.add_argument("--out", default=os.path.join(main.DATA_ROOT,
                                                  "robustness_evaluation_kalman_norm.json"))
    args = ap.parse_args()

    paths: List[str] = []
    for pattern in args.shards:
        hits = sorted(glob.glob(pattern))
        if not hits:
            raise SystemExit(f"no file matches {pattern}")
        paths += hits
    # a shard cannot merge with itself, and --out may already exist as an input
    paths = [p for p in dict.fromkeys(paths)]

    payload = _merge(paths)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"{'variant':18s} {'sens':>7s} {'FA/rec':>7s} {'alarm/h':>8s} {'missed':>6s}  source")
    for r in payload["results"]:
        print(f"{r['variant']:18s} {r['sensitivity']*100:6.1f}% {r['false_alarm_rate']*100:6.1f}% "
              f"{r['alarms_per_hour']:8.1f} {len(r['missed']):6d}  {r['_source']}")
    if payload["variants_missing"]:
        print("\nNOT MEASURED: " + ", ".join(payload["variants_missing"]))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
