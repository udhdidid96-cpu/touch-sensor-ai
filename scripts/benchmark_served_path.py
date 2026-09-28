#!/usr/bin/env python3
"""Out-of-fold evaluation of the detector the server runs, and of four
candidate training changes, under the published sensor perturbations.

Implements docs/ML_ENHANCEMENT_PLAN.md, registered before any candidate below
was scored. Research only: nothing in main.py imports this file.

Why a second harness
--------------------
Every figure in Data/metrics.json comes from ``compute_oof`` +
``evaluate_stream``: the offline Kalman delta, ``clf.predict`` on every frame,
then the annunciator. The server does more than that. ``LivePipeline.process``
also runs the quiescent-recovery baseline repair, the F10 scale normalisation
and the 60-count noise gate inside ``classify_deltas``. Each of those can only
change what is annunciated, and none of them is in any published number. This
harness replays each held-out recording through ``LivePipeline`` itself - the
object the websocket and ``--replay`` use - with a model fitted without that
recording.

Protocol (plan section 3)
-------------------------
* Leave-one-file-out over the 81 recordings; the annunciator at its shipped
  operating point (6 votes in a 7-frame window, hold 9) through LivePipeline's
  own debouncer. Nothing - operating point, gates, estimator, features - is
  tuned on these results.
* C0_offline on clean data must reproduce Data/metrics.json exactly
  (harness_check); if it does not, no candidate is decided.
* Training is on the clean corpus. The held-out recording is perturbed at test
  time by each variant of scripts/evaluate_robustness.py (same functions, same
  deterministic per-file seeds): the deployment question "trained on this
  bench, run on a noisier board".
* Candidates:
    C0  the shipped recipe: offline Kalman deltas, every frame, HGB.
        Scored twice - the published offline way (C0_offline) and through
        LivePipeline (C0_served).
    C1  trained on the served deltas (LivePipeline's own calibration).
    C2  C1 plus three noisy copies of every training recording (raw-count
        white noise, sd 45 / 90 / 135 - deliberately not the test levels -
        with seeds independent of the test seeds).
    C3  C1, trained only on frames the classifier is asked about at serving
        time (largest |delta| at or above the 60-count noise gate).
    C4  C2 with C3's frame filter.

Usage
-----
    python scripts/benchmark_served_path.py --shard 1/6      # one share of folds
    python scripts/benchmark_served_path.py --merge          # score and decide
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from math import comb
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import evaluate_robustness as ER
import main

SHARD_DIR = os.path.join(tempfile.gettempdir(), "project2-served-path-shards")
OUT = os.path.join(main.DATA_ROOT, "served_path_benchmark.json")
CANDIDATES: Tuple[str, ...] = ("C0", "C1", "C2", "C3", "C4")
SCORED: Tuple[str, ...] = ("C0_offline", "C0_served", "C1", "C2", "C3", "C4")
AUG_SDS: Tuple[float, ...] = (45.0, 90.0, 135.0)
VARIANTS: Tuple[str, ...] = tuple(ER.VARIANTS)
MAX_ALARM_RATIO = 1.10
MAX_EXTRA_LATENCY_S = main.SAMPLE_PERIOD_S
MAX_POOLED_EXTRA_FA = 4
MAX_VARIANT_LOST_DETECTIONS = 1
MAX_VARIANT_EXTRA_FA = 2
MAX_FILE_ACCURACY_LOSS = 1
ALPHA = 0.05 / (len(CANDIDATES) - 1)


def load_corpus() -> Tuple[Any, List[str], List[np.ndarray]]:
    ds = main.load_dataset("kalman", False, verbose=False)
    if ds is None:
        raise SystemExit("no dataset under Data/")
    paths = [os.path.join(main.DATA_ROOT, rel) for rel in ds.files]
    raws = [np.asarray(main.read_raw_csv(p), dtype=float) for p in paths]
    return ds, paths, raws


def served_deltas(raw: np.ndarray) -> np.ndarray:
    """The delta LivePipeline hands classify_deltas, frame by frame.

    Captured from the pipeline itself rather than re-implemented, so the
    quiescent recovery, the gated Kalman update and the F10 normalisation are
    exactly the served ones.
    """
    pipe = main.LivePipeline(None)
    captured: List[np.ndarray] = []
    original = main.compute_fractional_deltas

    def capture(delta: np.ndarray, c0: np.ndarray, *a: Any, **k: Any) -> Any:
        result = original(delta, c0, *a, **k)
        captured.append(np.asarray(result, dtype=float) * main.BASELINE_COUNTS)
        return result

    main.compute_fractional_deltas = capture
    try:
        for row in raw:
            pipe.process(row)
    finally:
        main.compute_fractional_deltas = original
    if len(captured) != len(raw):
        raise RuntimeError(f"captured {len(captured)} deltas for {len(raw)} frames")
    return np.vstack(captured)


def aug_rng(path: str, sd: float) -> np.random.Generator:
    """Training-noise seed: disjoint from the test seeds (variant:basename)."""
    key = f"train-augment:{sd:g}:{os.path.basename(path)}".encode("utf-8")
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key).digest()[:8], "big"))


def training_tables(ds: Any, paths: List[str], raws: List[np.ndarray]
                    ) -> Dict[str, List[Tuple[np.ndarray, np.ndarray]]]:
    """Per candidate, per file: (features, frame labels) available to training."""
    offline: List[Tuple[np.ndarray, np.ndarray]] = []
    served: List[Tuple[np.ndarray, int]] = []
    augmented: List[Tuple[List[np.ndarray], int]] = []
    for fi, (path, raw) in enumerate(zip(paths, raws)):
        label = int(ds.labels[fi])
        off = ds.frames[fi]
        offline.append((main.extract_features(off, False),
                        np.full(len(off), label, dtype=int)))
        sv = served_deltas(raw)
        served.append((sv, label))
        copies = [served_deltas(raw + aug_rng(path, sd).normal(0.0, sd, raw.shape))
                  for sd in AUG_SDS]
        augmented.append((copies, label))

    def rows(deltas: Sequence[np.ndarray], label: int, active_only: bool
             ) -> Tuple[np.ndarray, np.ndarray]:
        d = np.vstack(deltas)
        if active_only:
            d = d[np.max(np.abs(d), axis=1) >= main.NOISE_GATE_COUNTS]
        if len(d) == 0:
            return np.zeros((0, 34)), np.zeros(0, dtype=int)
        return main.extract_features(d, False), np.full(len(d), label, dtype=int)

    return {
        "C0": offline,
        "C1": [rows([sv], lab, False) for sv, lab in served],
        "C2": [rows([sv] + cp, lab, False)
               for (sv, lab), (cp, _) in zip(served, augmented)],
        "C3": [rows([sv], lab, True) for sv, lab in served],
        "C4": [rows([sv] + cp, lab, True)
               for (sv, lab), (cp, _) in zip(served, augmented)],
    }


def fit(table: List[Tuple[np.ndarray, np.ndarray]], held: int) -> Any:
    x = np.vstack([t[0] for i, t in enumerate(table) if i != held and len(t[0])])
    y = np.hstack([t[1] for i, t in enumerate(table) if i != held and len(t[1])])
    return main.new_rf(42).fit(x, y)


def served_levels(model: Any, raw: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    pipe = main.LivePipeline(model)
    levels: List[int] = []
    raw_levels: List[int] = []
    for row in raw:
        out = pipe.process(row)
        levels.append(int(out["severity_level"]))
        raw_levels.append(int(out["raw_level"]))
    return np.asarray(levels), np.asarray(raw_levels)


def offline_levels(model: Any, raw: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """compute_oof + evaluate_stream for one file: the published path."""
    preds = model.predict(main.extract_features(main.calibrate(raw, "kalman"), False))
    deb = main.AlarmDebouncer()
    levels = [0 if k < main.KALMAN_WARMUP else deb.update(int(p))
              for k, p in enumerate(preds)]
    return np.asarray(levels), np.asarray(preds, dtype=int)


def outcome(levels: np.ndarray, raw_levels: np.ndarray) -> Dict[str, Any]:
    hits = np.nonzero(levels >= 2)[0]
    return {"annunciated": bool(hits.size),
            "max_level": int(levels.max(initial=0)),
            "onsets": main.count_onsets(levels),
            "latency_s": float(hits[0] * main.SAMPLE_PERIOD_S) if hits.size else None,
            "frames": int(len(levels)),
            "file_vote": main.file_vote(raw_levels)}


def run_fold(fi: int, ds: Any, paths: List[str], raws: List[np.ndarray],
             tables: Dict[str, List[Tuple[np.ndarray, np.ndarray]]]
             ) -> Dict[str, Any]:
    models = {c: fit(tables[c], fi) for c in CANDIDATES}
    result: Dict[str, Any] = {"file": ds.files[fi], "label": int(ds.labels[fi]),
                              "scores": {s: {} for s in SCORED}}
    for variant in VARIANTS:
        raw = ER.VARIANTS[variant](raws[fi].copy(), ER.rng_for(paths[fi], variant))
        result["scores"]["C0_offline"][variant] = outcome(*offline_levels(models["C0"], raw))
        result["scores"]["C0_served"][variant] = outcome(*served_levels(models["C0"], raw))
        for c in CANDIDATES[1:]:
            result["scores"][c][variant] = outcome(*served_levels(models[c], raw))
    return result


def summarise(folds: List[Dict[str, Any]], scored: str, variant: str) -> Dict[str, Any]:
    rows = [(f["label"], f["scores"][scored][variant]) for f in folds]
    normal = [o for lab, o in rows if lab <= 1]
    anomaly = [o for lab, o in rows if lab >= 2]
    detected = sum(o["annunciated"] for o in anomaly)
    fa = sum(o["annunciated"] for o in normal)
    hours = sum(o["frames"] for o in normal) * main.SAMPLE_PERIOD_S / 3600.0
    lat = [o["latency_s"] for o in anomaly if o["latency_s"] is not None]
    correct = sum(o["file_vote"] == lab for lab, o in rows)
    return {"detected": detected, "n_anomaly": len(anomaly),
            "sensitivity": detected / max(len(anomaly), 1),
            "sensitivity_ci": list(main.wilson(detected, len(anomaly))),
            "fa_files": fa, "n_normal": len(normal),
            "false_alarm_rate": fa / max(len(normal), 1),
            "alarms_per_hour": (sum(o["onsets"] for o in normal) / hours
                                if hours else 0.0),
            "median_latency_s": float(np.median(lat)) if lat else None,
            "file_vote_correct": correct, "n_files": len(rows)}


def sign_test_one_sided(gains: int, losses: int) -> float:
    """Exact P(at least `gains` of the discordant units favour the candidate)."""
    n = gains + losses
    if n == 0:
        return 1.0
    return float(sum(comb(n, k) for k in range(gains, n + 1)) / 2 ** n)


def decide(folds: List[Dict[str, Any]], table: Dict[str, Dict[str, Any]]
           ) -> Dict[str, Any]:
    """Plan section 5, applied to C1-C4 against C0_served.

    The robustness test is clustered by recording: the 10 perturbed replays of
    one file share its event, so they are not 10 independent trials. A file is
    a gain when the candidate annunciates in more of them than the reference,
    a loss when in fewer. Pair-level counts are kept for information only.
    """
    base = table["C0_served"]
    perturbed = [v for v in VARIANTS if v != "identity"]
    out: Dict[str, Any] = {}
    for c in CANDIDATES[1:]:
        clean, ref = table[c]["identity"], base["identity"]
        file_gains = file_losses = pair_gains = pair_losses = 0
        for f in folds:
            if f["label"] < 2:
                continue
            mine = [bool(f["scores"][c][v]["annunciated"]) for v in perturbed]
            theirs = [bool(f["scores"]["C0_served"][v]["annunciated"]) for v in perturbed]
            file_gains += sum(mine) > sum(theirs)
            file_losses += sum(mine) < sum(theirs)
            pair_gains += sum(a and not b for a, b in zip(mine, theirs))
            pair_losses += sum(b and not a for a, b in zip(mine, theirs))
        p = sign_test_one_sided(file_gains, file_losses)
        pooled_fa = sum(table[c][v]["fa_files"] for v in perturbed)
        pooled_fa_ref = sum(base[v]["fa_files"] for v in perturbed)
        checks = {
            "clean_sensitivity": clean["detected"] >= ref["detected"],
            "clean_false_alarms": clean["fa_files"] <= ref["fa_files"],
            "clean_alarm_burden": (clean["alarms_per_hour"]
                                   <= MAX_ALARM_RATIO * ref["alarms_per_hour"] + 1e-9),
            "clean_latency": (clean["median_latency_s"] is not None
                              and ref["median_latency_s"] is not None
                              and clean["median_latency_s"]
                              <= ref["median_latency_s"] + MAX_EXTRA_LATENCY_S + 1e-9),
            "file_accuracy": (clean["file_vote_correct"]
                              >= ref["file_vote_correct"] - MAX_FILE_ACCURACY_LOSS),
            "robustness_gain": file_gains > file_losses and p < ALPHA,
            "pooled_false_alarms": pooled_fa <= pooled_fa_ref + MAX_POOLED_EXTRA_FA,
            "no_variant_harm": all(
                table[c][v]["detected"] >= base[v]["detected"] - MAX_VARIANT_LOST_DETECTIONS
                and table[c][v]["fa_files"] <= base[v]["fa_files"] + MAX_VARIANT_EXTRA_FA
                for v in perturbed),
        }
        out[c] = {"checks": checks, "adopt": all(checks.values()),
                  "file_gains": file_gains, "file_losses": file_losses,
                  "sign_test_p": p, "alpha": ALPHA,
                  "pair_gains": pair_gains, "pair_losses": pair_losses,
                  "pooled_detected": sum(table[c][v]["detected"] for v in perturbed),
                  "pooled_detected_reference": sum(base[v]["detected"] for v in perturbed),
                  "pooled_fa_files": pooled_fa, "pooled_fa_reference": pooled_fa_ref}
    passing = [c for c in CANDIDATES[1:] if out[c]["adopt"]]
    order = ("C1", "C3", "C2", "C4")
    best = max(passing, key=lambda c: (out[c]["pooled_detected"], -order.index(c)),
               default=None)
    return {"per_candidate": out, "passing": passing, "chosen": best}


def harness_check(table: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Plan section 3: C0_offline on clean data must BE the published result.

    If this replay of compute_oof + evaluate_stream does not reproduce
    Data/metrics.json exactly, the harness is measuring something else and no
    candidate may be scored against it.
    """
    with open(os.path.join(main.DATA_ROOT, "metrics.json"), encoding="utf-8") as fh:
        m = json.load(fh)
    ep, rf = m["episode_level"], m["random_forest"]
    got = table["C0_offline"]["identity"]
    want = {"detected": got["n_anomaly"] - len(ep["missed"]),
            "fa_files": round(ep["false_alarm_rate"] * got["n_normal"]),
            "alarms_per_hour": ep["alarms_per_hour"],
            "median_latency_s": ep["median_latency_s"],
            "file_vote_correct": round(rf["accuracy_mean"] * got["n_files"])}
    diff = {k: (got[k], v) for k, v in want.items()
            if not (abs(got[k] - v) < 1e-6 if isinstance(v, float) else got[k] == v)}
    return {"valid": not diff, "mismatches": diff, "published": want}


def run_shard(part: int, parts: int) -> str:
    ds, paths, raws = load_corpus()
    t0 = time.time()
    tables = training_tables(ds, paths, raws)
    print(f"  training tables built in {time.time() - t0:.0f}s", flush=True)
    folds: List[Dict[str, Any]] = []
    for fi in range(part - 1, ds.n_files, parts):
        t1 = time.time()
        folds.append(run_fold(fi, ds, paths, raws, tables))
        print(f"  fold {fi:2d} {ds.files[fi]}: {time.time() - t1:.0f}s", flush=True)
    os.makedirs(SHARD_DIR, exist_ok=True)
    target = os.path.join(SHARD_DIR, f"shard_{part}of{parts}.json")
    with open(target + ".part", "w", encoding="utf-8") as fh:
        json.dump({"folds": folds, "variants": list(VARIANTS)}, fh)
    os.replace(target + ".part", target)
    return target


def merge(expected: Optional[int] = None) -> int:
    folds: List[Dict[str, Any]] = []
    for name in sorted(os.listdir(SHARD_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(SHARD_DIR, name), encoding="utf-8") as fh:
                folds += json.load(fh)["folds"]
    folds.sort(key=lambda f: f["file"])
    if expected is not None and len(folds) != expected:
        print(f"expected {expected} folds, found {len(folds)}")
        return 2
    table = {s: {v: summarise(folds, s, v) for v in VARIANTS} for s in SCORED}
    check = harness_check(table)
    decision = decide(folds, table)
    if not check["valid"]:
        decision["chosen"] = None
        decision["passing"] = []
    print(f"{'scored':11s} {'variant':16s} {'detected':>9s} {'FA files':>9s} "
          f"{'alarms/h':>9s} {'latency':>8s} {'file vote':>10s}")
    for s in SCORED:
        for v in VARIANTS:
            r = table[s][v]
            lat = "-" if r["median_latency_s"] is None else f"{r['median_latency_s']:.2f}"
            print(f"{s:11s} {v:16s} {r['detected']:>4d}/{r['n_anomaly']:<4d} "
                  f"{r['fa_files']:>4d}/{r['n_normal']:<4d} {r['alarms_per_hour']:9.1f} "
                  f"{lat:>8s} {r['file_vote_correct']:>5d}/{r['n_files']}")
    print(f"harness reproduces Data/metrics.json: {check['valid']} {check['mismatches']}")
    for c, d in decision["per_candidate"].items():
        failed = [k for k, ok in d["checks"].items() if not ok]
        print(f"{c}: adopt={d['adopt']} files +{d['file_gains']}/-{d['file_losses']} "
              f"p={d['sign_test_p']:.4f} (alpha {d['alpha']:.4f}); pairs "
              f"+{d['pair_gains']}/-{d['pair_losses']}; pooled detected "
              f"{d['pooled_detected']} vs {d['pooled_detected_reference']}; pooled FA "
              f"{d['pooled_fa_files']} vs {d['pooled_fa_reference']}; failed {failed}")
    print(f"chosen: {decision['chosen']}")
    payload = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "plan": "docs/ML_ENHANCEMENT_PLAN.md",
        "protocol": ("leave-one-file-out; trained on the clean corpus; the held-out "
                     "recording perturbed by scripts/evaluate_robustness.py's variants "
                     "and replayed through LivePipeline (C0_offline: compute_oof + "
                     "evaluate_stream on the offline Kalman delta)"),
        "operating_point": {"window": main.ALARM.window, "votes": main.ALARM.min_votes,
                            "hold": main.ALARM.hold},
        "caveat": ("one sensor mounting; modelled perturbations, not a new patch"),
        "augmentation_sd_counts": list(AUG_SDS),
        "harness_check": check, "table": table, "decision": decision, "folds": folds,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    print(f"wrote {OUT}")
    return 0


def diagnose() -> int:
    """Post-hoc, not part of the decision: what the first offline alarms stand on.

    For each anomaly recording the published path annunciates, count the
    supporting votes (out-of-fold prediction >= 2) in the window that raised the
    first alarm, and how many of them are frames whose largest served |delta| is
    under the noise gate - frames the server never asks the model about.
    """
    ds, _, raws = load_corpus()
    oof = main.compute_oof(ds, 42)
    rows: List[Dict[str, Any]] = []
    quiet = total = 0
    for fi, label in enumerate(ds.labels):
        if label < 2:
            continue
        preds = oof[ds.groups == fi]
        peak = np.max(np.abs(served_deltas(raws[fi])), axis=1)
        deb = main.AlarmDebouncer()
        levels = np.asarray([0 if k < main.KALMAN_WARMUP else deb.update(int(p))
                             for k, p in enumerate(preds)])
        hits = np.nonzero(levels >= 2)[0]
        if not hits.size:
            continue
        first = int(hits[0])
        start = max(main.KALMAN_WARMUP, first - main.ALARM.window + 1)
        votes = [k for k in range(start, first + 1) if preds[k] >= 2]
        below = [k for k in votes if peak[k] < main.NOISE_GATE_COUNTS]
        active = np.nonzero(peak[main.KALMAN_WARMUP:] >= main.NOISE_GATE_COUNTS)[0]
        quiet, total = quiet + len(below), total + len(votes)
        rows.append({"file": ds.files[fi], "first_offline_alarm_frame": first,
                     "votes": len(votes), "votes_below_gate": len(below),
                     "first_frame_at_or_above_gate": (int(active[0]) + main.KALMAN_WARMUP
                                                      if active.size else None)})
    out = os.path.join(main.DATA_ROOT, "served_path_diagnosis.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "what": ("votes behind each first offline alarm, and how many are "
                            "frames the served noise gate never lets the model see"),
                   "post_hoc": True,
                   "noise_gate_counts": main.NOISE_GATE_COUNTS,
                   "votes_below_gate": quiet, "votes": total,
                   "recordings_all_votes_below_gate": sum(
                       r["votes"] > 0 and r["votes_below_gate"] == r["votes"] for r in rows),
                   "recordings": rows}, fh, indent=1)
    print(f"{quiet}/{total} votes behind the first offline alarms are below the "
          f"{main.NOISE_GATE_COUNTS:g}-count gate -> {out}")
    return 0


def main_cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shard", default="", help="k/n: score every n-th fold from k")
    ap.add_argument("--merge", action="store_true", help="combine shards and decide")
    ap.add_argument("--diagnose", action="store_true",
                    help="post-hoc: sub-gate votes behind the first offline alarms")
    ap.add_argument("--expect", type=int, default=81)
    args = ap.parse_args()
    if args.diagnose:
        return diagnose()
    if args.merge:
        return merge(args.expect)
    part, parts = (int(x) for x in (args.shard or "1/1").split("/"))
    print(f"-> {run_shard(part, parts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
