"""
Comprehensive 5-Scenario Verification & Signal Characterization Script
======================================================================
Evaluates the 81 bench recordings across the 5 canonical clinical scenarios:
  1. Baseline (อยู่นิ่ง - Resting / Quiescent)
  2. Touching (การสัมผัส - Brief Touch / Press)
  3. Friction (การเสียดสี / รูดสาย - Rubbing / Friction)
  4. Pulling (การดึงท่อ - Vertical & Horizontal Pull, Power Pull)
  5. Peeling (การลอกหลุด - Partial & Full Detachment)
Plus reference: Normal Mix (Touching + Rubbing + Resting)

Features:
  - Supports both Out-Of-Fold (Leave-One-File-Out CV) and In-Sample evaluation
  - Wilson 95% Score confidence intervals for medical accuracy and sensitivity
  - Physical signal bounds: min delta (lift depth), max delta (contact amplitude)
  - Gate compliance: Noise gate (60 counts) & Lift gate (-300 counts)
  - Annunciator episode alarm detection vs false alarm rate
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple
import numpy as np

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Calculate Wilson score interval with continuity bounds."""
    if n == 0:
        return 0.0, 0.0
    z = 1.95996  # 95% confidence
    p = k / n
    denom = 1.0 + (z**2) / n
    centre = (p + (z**2) / (2 * n)) / denom
    margin = (z * np.sqrt((p * (1 - p) / n) + (z**2) / (4 * (n**2)))) / denom
    return max(0.0, float(centre - margin)), min(1.0, float(centre + margin))


def evaluate_5_scenarios(mode: str = "oof") -> Dict[str, Any]:
    print("=" * 78)
    print("5-SCENARIO BIOMEDICAL SIGNAL & ALGORITHM BENCHMARK")
    print("Smart Extubation Early Warning (25-Channel Capacitive Smart Dressing)")
    print(f"Evaluation Mode: {mode.upper()} ({'Leave-One-File-Out CV' if mode == 'oof' else 'In-Sample Fitted'})")
    print("=" * 78)

    ds = M.load_dataset("kalman", verbose=False)
    if ds is None or ds.n_files == 0:
        print("ERROR: Could not load dataset from Data/")
        return {}

    # Define scenario mapping based on file folder names
    scenario_defs = {
        "1. Baseline (อยู่นิ่ง)": {
            "folders": ["N_base"],
            "description": "Resting attached dressing, quiescent state, ambient drift only",
            "is_anomaly": False,
        },
        "2. Touching (การสัมผัส - รวม)": {
            "folders": ["Brief Touch", "Press"],
            "description": "Direct finger touch or compressive press without displacement",
            "is_anomaly": False,
        },
        "  2a. Brief Touch (สัมผัสสั้น)": {
            "folders": ["Brief Touch"],
            "description": "Light momentary touch events across various pads",
            "is_anomaly": False,
        },
        "  2b. Sustained Press (กดทับ)": {
            "folders": ["Press"],
            "description": "Firm compressive presses (includes 1-by-1 pad sweep)",
            "is_anomaly": False,
        },
        "3. Friction (การเสียดสี)": {
            "folders": ["Friction"],
            "description": "Cloth/glove rubbing and line sliding across the dressing",
            "is_anomaly": False,
        },
        "4. Pulling (การดึงท่อ - รวม)": {
            "folders": ["Vertical Pull NO G", "Horizontal Pull NO G", "PowerP"],
            "description": "Tension and displacement applied to the intubation tube",
            "is_anomaly": True,
        },
        "  4a. Vertical Pull (ดึงแนวดิ่ง)": {
            "folders": ["Vertical Pull NO G"],
            "description": "Upward perpendicular displacement opening direct air gap",
            "is_anomaly": True,
        },
        "  4b. Horizontal Pull (ดึงแนวราบ)": {
            "folders": ["Horizontal Pull NO G"],
            "description": "Lateral shear displacement without adhesive coupling",
            "is_anomaly": True,
        },
        "  4c. Power Pull (ดึงกระชากแรง)": {
            "folders": ["PowerP"],
            "description": "High-velocity traumatic pulling episode",
            "is_anomaly": True,
        },
        "5. Peeling (การลอกหลุด)": {
            "folders": ["Peel"],
            "description": "Progressive adhesive failure and detachment from substrate",
            "is_anomaly": True,
        },
        "Ref. Normal Mix (ผสมทั่วไป)": {
            "folders": ["Normal Mix"],
            "description": "Multi-action sequence mixing touches, rubs, and rest periods",
            "is_anomaly": False,
        },
    }

    # Model inference preparation
    if mode == "oof":
        print("Computing Leave-One-File-Out (Out-Of-Fold) predictions over 81 files ...")
        oof_preds = M.compute_oof(ds, 42)
    else:
        print("Fitting model in-sample on entire corpus ...")
        clf = M._new_rf(42).fit(ds.X, ds.y)
        oof_preds = clf.predict(ds.X)

    scenario_results = {}
    all_summary = []

    for name, sdef in scenario_defs.items():
        folders = sdef["folders"]
        indices = [i for i, f in enumerate(ds.files) if any(f.startswith(fd + "/") or f.startswith(fd + "\\") for fd in folders)]

        if not indices:
            continue

        file_count = len(indices)
        total_frames = sum(len(ds.frames[i]) for i in indices)

        deepest_deltas = []
        max_deltas = []
        lift_gate_crossings = 0
        noise_gate_crossings = 0

        alarms_triggered = 0
        file_votes = []
        mismatched_files = []

        for fi in indices:
            raw_frames = ds.frames[fi]  # (n_frames, 25)
            min_val = float(np.min(raw_frames))
            max_val = float(np.max(raw_frames))
            deepest_deltas.append(min_val)
            max_deltas.append(max_val)

            # Check gate crossings (LIFT_GATE_COUNTS is -300.0)
            if min_val <= M.LIFT_GATE_COUNTS:
                lift_gate_crossings += 1
            if max_val >= M.NOISE_GATE_COUNTS or min_val <= -M.NOISE_GATE_COUNTS:
                noise_gate_crossings += 1

            # Predictions for this file
            file_mask = (ds.groups == fi)
            preds = oof_preds[file_mask]

            # File-level majority vote
            vote = M._file_vote(preds)
            file_votes.append(vote)
            true_label = ds.labels[fi]
            if vote != true_label:
                mismatched_files.append((ds.files[fi], true_label, vote))

            # Annunciator / Episode alarm evaluation (7-of-6 hold 9)
            debouncer = M.AlarmDebouncer(window=7, min_votes=6, hold=9)
            triggered = False
            for p in preds:
                lvl = int(p)
                alarm_active = debouncer.update(lvl) >= 2
                if alarm_active:
                    triggered = True
                    break
            if triggered:
                alarms_triggered += 1

        is_anomaly = sdef["is_anomaly"]
        alarm_rate_pct = (alarms_triggered / file_count) * 100.0
        alarm_ci_low, alarm_ci_high = wilson_score_interval(alarms_triggered, file_count)
        lift_ci_low, lift_ci_high = wilson_score_interval(lift_gate_crossings, file_count)

        scenario_stat = {
            "scenario": name,
            "description": sdef["description"],
            "files": file_count,
            "frames": total_frames,
            "is_anomaly": is_anomaly,
            "median_deepest_delta": float(np.median(deepest_deltas)),
            "min_delta_range": [float(np.min(deepest_deltas)), float(np.max(deepest_deltas))],
            "median_max_delta": float(np.median(max_deltas)),
            "max_delta_range": [float(np.min(max_deltas)), float(np.max(max_deltas))],
            "lift_gate_files": f"{lift_gate_crossings}/{file_count}",
            "lift_gate_pct": (lift_gate_crossings / file_count) * 100.0,
            "lift_gate_95ci": [round(lift_ci_low * 100, 1), round(lift_ci_high * 100, 1)],
            "alarm_files": f"{alarms_triggered}/{file_count}",
            "alarm_rate_pct": alarm_rate_pct,
            "alarm_rate_95ci": [round(alarm_ci_low * 100, 1), round(alarm_ci_high * 100, 1)],
            "vote_distribution": {
                "0:Baseline": int(sum(1 for v in file_votes if v == 0)),
                "1:Touch/Press": int(sum(1 for v in file_votes if v == 1)),
                "2:Peel": int(sum(1 for v in file_votes if v == 2)),
                "3:Pull": int(sum(1 for v in file_votes if v == 3)),
            },
            "mismatched_files": [f[0] for f in mismatched_files],
        }
        scenario_results[name] = scenario_stat
        all_summary.append(scenario_stat)

    # Print Formatted Markdown Profile
    print("\n### 5-SCENARIO BIOMEDICAL PROFILE TABLE\n")
    header = (
        f"{'Scenario':<32} | {'Files':<5} | {'Median Min Δ':<12} | "
        f"{'Median Max Δ':<12} | {'Lift Gate (≤-300)':<18} | {'Annunciator Alarm (95% CI)':<26}"
    )
    print(header)
    print("-" * len(header))

    for s in all_summary:
        if s["is_anomaly"]:
            metric_label = f"Sens: {s['alarm_rate_pct']:.1f}% [{s['alarm_rate_95ci'][0]}-{s['alarm_rate_95ci'][1]}%]"
        else:
            metric_label = f"FA: {s['alarm_rate_pct']:.1f}% [{s['alarm_rate_95ci'][0]}-{s['alarm_rate_95ci'][1]}%]"

        print(
            f"{s['scenario']:<32} | "
            f"{s['files']:<5} | "
            f"{s['median_deepest_delta']:>9.1f} ct | "
            f"{s['median_max_delta']:>9.1f} ct | "
            f"{s['lift_gate_files']:<6} ({s['lift_gate_pct']:>4.1f}%) | "
            f"{s['alarm_files']:<5} ({metric_label})"
        )

    print("\n### MAJORITY VOTE CLASSIFICATION BREAKDOWN\n")
    for s in all_summary:
        vd = s["vote_distribution"]
        mismatch_str = f" -> Mismatches: {s['mismatched_files']}" if s['mismatched_files'] else ""
        print(f"  * {s['scenario']:<32}: Base={vd['0:Baseline']}, Touch={vd['1:Touch/Press']}, Peel={vd['2:Peel']}, Pull={vd['3:Pull']}{mismatch_str}")

    # Output to JSON
    out_path = os.path.join(M.DATA_ROOT, "five_scenarios_evaluation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "mode": mode,
            "timestamp": M.time.strftime("%Y-%m-%d %H:%M:%S"),
            "scenarios": scenario_results
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved detailed scenario benchmark to: {out_path}")

    return scenario_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate 5 canonical scenarios across the 81 bench recordings")
    parser.add_argument("--mode", choices=["oof", "insample"], default="oof",
                        help="Evaluation mode: 'oof' (Leave-One-File-Out CV) or 'insample'")
    args = parser.parse_args()
    evaluate_5_scenarios(mode=args.mode)
