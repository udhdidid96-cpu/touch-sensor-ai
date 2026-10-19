"""Leave-one-file-out benchmark on the new vacuum demo station (Data/data new vaccum/).

1. Reads the 24 CSVs and keeps Signal-1..25 (Signal-26 is an empty trailing column).
2. C0 = mean of N_base1 frames 20..99, the settled attached state.
3. 40 features per frame: 25 pad deltas + 9 statistics + 6 spatial gradient features.
4. LOFO over 25 items (N_base1 split into frames 20..69 and 70..119), majority vote per
   held-out item, Clopper-Pearson 95% intervals. Preprocessing is the same for every class.
5. Controls, printed with every run because the headline alone misleads on this set:
   (a) strict LOFO over the 24 files, N_base1 whole. With the split, each N_base chunk is
       recognised from its twin chunk in training;
   (b) settled tails: the last frames of pull files, where the patch is attached and still,
       scored by the same held-out models. A pull detector should not call these "pull";
   (c) leave the last attachment out: the 7 files recorded after the patch was re-attached
       are scored by a model that never saw that attachment, frame by frame.

All class-2 files were recorded after all class-0/1 files (16:20-18:08, 2026-09-25), and
each attachment rests at its own per-pad level, so file labels let a classifier separate
the classes by attachment state alone. Keep this in mind before quoting
any number printed here.
"""

from __future__ import annotations

import glob
import os
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.stats import beta
from sklearn.ensemble import HistGradientBoostingClassifier

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Data", "data new vaccum")
LABELS = ["0: Base", "1: Touch/Press", "2: Detach Pull"]
NOISE_GATE = 60.0
TAIL = 5
ENDS_DETACHED = ("A_VPull/A_VPulldown1.csv", "A_VPull/A_VPulldwon2.csv")
LAST_ATTACHMENT = ("A_HPull/A_HPull1.csv", "A_HPull/A_HPull2.csv", "A_HPull/A_HPull3.csv",
                   "A_VPull/A_VPull5.csv", "A_OPull/A_OPull1.csv", "A_OPull/A_OPull2.csv",
                   "A_OPull/A_OPull3.csv")


def read(path: str) -> np.ndarray:
    """Raw counts, Signal-1..25 only (drops the empty trailing Signal-26)."""
    return pd.read_csv(path)[[f"Signal-{i}" for i in range(1, 26)]].to_numpy(float)


def get_seated_baseline() -> np.ndarray:
    """C0: per-pad mean of N_base1 frames 20..99 (patch settled on the station)."""
    return read(os.path.join(DATA_DIR, "N_base", "N_base1.csv"))[20:100].mean(axis=0)


def extract_features(arr: np.ndarray, c0: np.ndarray) -> np.ndarray:
    """Extracts 25 pad deltas + 9 statistics + 6 spatial shear gradient features (40 total)."""
    deltas = arr - c0
    n_frames, _ = deltas.shape
    features: list[list[float]] = []

    grid = deltas.reshape(n_frames, 5, 5)
    grad_y = np.diff(grid, axis=1).mean(axis=(1, 2))
    grad_x = np.diff(grid, axis=2).mean(axis=(1, 2))

    for i in range(n_frames):
        d: NDArray[np.float64] = deltas[i]
        mean_d = float(np.mean(d))
        std_d = float(np.std(d))
        min_d = float(np.min(d))
        max_d = float(np.max(d))
        ptp_d = max_d - min_d

        lift_mask = d < -300.0
        touch_mask = d > 60.0

        n_lift = float(np.sum(lift_mask))
        n_touch = float(np.sum(touch_mask))

        mean_lift = float(np.mean(d[lift_mask])) if n_lift > 0 else 0.0
        mean_touch = float(np.mean(d[touch_mask])) if n_touch > 0 else 0.0

        stats = [mean_d, std_d, min_d, max_d, ptp_d, n_lift, n_touch, mean_lift, mean_touch]

        gy = float(grad_y[i])
        gx = float(grad_x[i])
        mag = float(np.sqrt(gx**2 + gy**2))
        cell: NDArray[np.float64] = grid[i]
        spatial_var = float(np.var(cell))
        grads = [gy, gx, abs(gy), abs(gx), mag, spatial_var]

        row_feat = list(d) + stats + grads
        features.append(row_feat)

    return np.array(features, dtype=float)


def load_dataset(chunked: bool = True) -> list[tuple[str, int, np.ndarray]]:
    """(name, label, raw frames) per item.

    Labels: 0 = rest (N_base1, "noting do" = patch lying unattached), 1 = N_Press/N_Fric,
    2 = A_VPull/A_HPull/A_OPull. N_base1 contributes frames 20..119 (0..19 hold the attach
    step), as two chunks or as one item.
    """
    items: list[tuple[str, int, np.ndarray]] = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*", "*.csv"))):
        rel = os.path.relpath(path, DATA_DIR).replace(os.sep, "/")
        cat, arr = os.path.dirname(rel), read(path)
        if cat == "N_base":
            parts = [(" [chunk 1]", arr[20:70]), (" [chunk 2]", arr[70:120])] if chunked else [("", arr[20:120])]
            items += [(rel + tag, 0, a) for tag, a in parts]
        else:
            items.append((rel, 1 if ("Press" in cat or "Fric" in cat) else 2 if "Pull" in cat else 0, arr))
    return items


def lofo(items: Sequence[tuple[str, int, np.ndarray]],
         ref: Callable[[str], np.ndarray]) -> list[np.ndarray]:
    """Leave one item out; returns the held-out model's frame predictions for each item."""
    X = [extract_features(a, ref(name)) for name, _, a in items]
    preds: list[np.ndarray] = []
    for i in range(len(items)):
        train = [j for j in range(len(items)) if j != i]
        clf = HistGradientBoostingClassifier(max_iter=100, max_depth=6, random_state=42)
        clf.fit(np.vstack([X[j] for j in train]),
                np.concatenate([np.full(len(X[j]), items[j][1]) for j in train]))
        preds.append(clf.predict(X[i]))
    return preds


def ci(k: int, n: int) -> str:
    """k/n with its Clopper-Pearson 95% interval."""
    lo = beta.ppf(0.025, k, n - k + 1) if k else 0.0
    hi = beta.ppf(0.975, k + 1, n - k) if k < n else 1.0
    return f"{k}/{n} = {100 * k / n:.2f}% (95% CI {100 * lo:.1f}-{100 * hi:.1f}%)"


def report(title: str, items: Sequence[tuple[str, int, np.ndarray]],
           preds: Sequence[np.ndarray], per_file: bool = False) -> None:
    y = np.array([label for _, label, _ in items])
    yhat = np.array([np.bincount(p, minlength=3).argmax() for p in preds])
    print(f"\n=== {title} ===")
    if per_file:
        for (name, label, _), p, v in zip(items, preds, yhat):
            print(f"  {name:32s} true {label} pred {v} [{'PASS' if v == label else 'FAIL'}]"
                  f"  frames {np.mean(p == label) * 100:5.1f}%")
    cm_file = np.zeros((3, 3), int)
    cm_frame = np.zeros((3, 3), int)
    for label, v, p in zip(y, yhat, preds):
        cm_file[label, v] += 1
        cm_frame[label] += np.bincount(p, minlength=3)
    frames_ok = np.trace(cm_frame)
    print(f"  file accuracy   : {ci(int((y == yhat).sum()), len(y))}")
    print(f"  pull recall     : {ci(int(cm_file[2, 2]), int(cm_file[2].sum()))}")
    print(f"  Touch/Press files called pull: {cm_file[1, 2]}/{cm_file[1].sum()}"
          f" | non-pull frames called pull: {cm_frame[0, 2] + cm_frame[1, 2]}/{cm_frame[:2].sum()}"
          f" | frame accuracy {frames_ok}/{cm_frame.sum()} = {100 * frames_ok / cm_frame.sum():.2f}%")
    for name, cm in (("file", cm_file), ("frame", cm_frame)):
        print(f"  {name}-level confusion (rows true, cols pred: Base | Touch/Press | Pull)")
        for label, row in zip(LABELS, cm):
            print(f"    {label:15s} {row[0]:6d} {row[1]:6d} {row[2]:6d}")


def run_lofo_benchmark() -> None:
    c0 = get_seated_baseline()
    print(f"C0 (N_base1 frames 20..99): mean {c0.mean():.0f}, median {np.median(c0):.0f}, "
          f"pads {c0.min():.0f}..{c0.max():.0f} counts")
    items = load_dataset()
    preds = lofo(items, lambda name: c0)
    report("LOFO, 25 items (N_base1 in two chunks), deltas vs N_base1 C0", items, preds, per_file=True)

    print("\n--- Controls ---")
    strict = load_dataset(chunked=False)
    report("(a) strict LOFO, 24 files (N_base1 whole)", strict, lofo(strict, lambda name: c0))

    k = n = 0
    for (name, label, a), p in zip(items, preds):
        t = a[-TAIL:]
        if label == 2 and name not in ENDS_DETACHED and np.abs(t - t.mean(axis=0)).max() <= NOISE_GATE:
            k, n = k + int((p[-TAIL:] == 2).sum()), n + TAIL
    print(f"\n=== (b) settled tails: last {TAIL} frames of pull files that end attached and still"
          f" (every pad within {NOISE_GATE:.0f} counts) ===\n  frames called pull: {k}/{n}")

    train = [(a, label) for name, label, a in items if name not in LAST_ATTACHMENT]
    clf = HistGradientBoostingClassifier(max_iter=100, max_depth=6, random_state=42)
    clf.fit(np.vstack([extract_features(a, c0) for a, _ in train]),
            np.concatenate([np.full(len(a), label) for a, label in train]))
    print(f"\n=== (c) leave the last attachment out: trained on the other {len(train)} items,"
          f" tested on the {len(LAST_ATTACHMENT)} files recorded after the patch was re-attached ===")
    votes = 0
    for name, label, a in items:
        if name in LAST_ATTACHMENT:
            p = clf.predict(extract_features(a, c0))
            votes += int(np.bincount(p, minlength=3).argmax() == 2)
            print(f"  {name:24s} vote {np.bincount(p, minlength=3).argmax()}  frames {''.join(map(str, p))}")
    print(f"  pull votes: {ci(votes, len(LAST_ATTACHMENT))}. Read the frame strings: each of these files"
          f" opens displaced below its settled level and ends settled.")


if __name__ == "__main__":
    run_lofo_benchmark()
