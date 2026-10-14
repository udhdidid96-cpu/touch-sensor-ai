"""Universal Cross-Station Machine Learning Benchmark.

Evaluates joint learning and generalization between:
1. Legacy Bench Dataset (81 recordings under Data/)
2. New Vacuum Station Dataset (24 recordings under Data/data new vaccum/)

Total: 105 recordings.

Features (40 features):
- 25 pad deltas (calibrated against seated/quiescent baseline)
- 9 physics & statistical invariants (mean, std, min, max, ptp, n_lift, n_touch, mean_lift, mean_touch)
- 6 spatial shear gradient features (grad_y, grad_x, |grad_y|, |grad_x|, shear magnitude, spatial variance)

Evaluations:
A. Leave-One-File-Out (LOFO) across all 105 recordings/chunks.
B. Cross-Station Transfer:
   - Train on Legacy Bench (81 files) -> Test on Vacuum Station (24 files)
   - Train on Vacuum Station (24 files) -> Test on Legacy Bench (81 files)
C. Joint Production Model Evaluation.
"""

from __future__ import annotations
import glob
import os
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from typing import List, Tuple
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import confusion_matrix, accuracy_score

LEGACY_DIR = "Data"
VACUUM_DIR = "Data/data new vaccum"
BASELINE_COUNTS = 28000.0


def get_vacuum_baseline() -> np.ndarray:
    """Computes ground truth settled baseline of the vacuum station."""
    base_file = os.path.join(VACUUM_DIR, "N_base", "N_base1.csv")
    df = pd.read_csv(base_file)
    if "Signal-26" in df.columns:
        df = df.drop(columns=["Signal-26"])
    cols = [c for c in df.columns if c.startswith("Signal-")]
    return df[cols].iloc[20:100].mean().to_numpy()


def extract_features(arr: np.ndarray, c0: np.ndarray) -> np.ndarray:
    """Extracts 25 pad deltas + 9 statistics + 6 spatial shear gradient features (40 total)."""
    deltas = arr - c0
    n_frames, _ = deltas.shape
    features: List[List[float]] = []

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


def load_legacy_corpus() -> Tuple[List[np.ndarray], List[int], List[str], List[str]]:
    """Loads all 81 legacy bench recordings."""
    X_files: List[np.ndarray] = []
    y_files: List[int] = []
    file_names: List[str] = []
    station_names: List[str] = []

    class_map = {
        "N_base": 0,
        "Brief Touch": 1,
        "Press": 1,
        "Friction": 1,
        "Normal Mix": 1,
        "Peel": 2,
        "Vertical Pull NO G": 2,
        "Horizontal Pull NO G": 2,
        "PowerP": 2,
    }

    all_files = sorted(glob.glob(os.path.join(LEGACY_DIR, "*", "*.csv")))
    all_files = [f for f in all_files if "data new vaccum" not in f.replace("\\", "/")]

    for path in all_files:
        rel = os.path.relpath(path, LEGACY_DIR).replace("\\", "/")
        folder = rel.split("/")[0]
        if folder not in class_map:
            continue

        df = pd.read_csv(path)
        cols = [c for c in df.columns if c.startswith("Sensor-")]
        if len(cols) != 25:
            continue
        arr = df[cols].to_numpy()
        if len(arr) < 5:
            continue

        c0 = arr[:5].mean(axis=0)
        feats = extract_features(arr, c0)

        X_files.append(feats)
        y_files.append(class_map[folder])
        file_names.append(f"Legacy/{rel}")
        station_names.append("legacy")

    return X_files, y_files, file_names, station_names


def load_vacuum_corpus() -> Tuple[List[np.ndarray], List[int], List[str], List[str]]:
    """Loads all 24 new vacuum recordings with proper baseline referencing."""
    c0 = get_vacuum_baseline()
    X_files: List[np.ndarray] = []
    y_files: List[int] = []
    file_names: List[str] = []
    station_names: List[str] = []

    all_files = sorted(glob.glob(os.path.join(VACUUM_DIR, "*", "*.csv")))

    for path in all_files:
        rel = os.path.relpath(path, VACUUM_DIR).replace("\\", "/")
        cat = rel.split("/")[0]
        df = pd.read_csv(path)
        if "Signal-26" in df.columns:
            df = df.drop(columns=["Signal-26"])
        cols = [c for c in df.columns if c.startswith("Signal-")]
        arr = df[cols].to_numpy()

        if "N_base" in cat:
            f1 = extract_features(arr[20:70], c0)
            f2 = extract_features(arr[70:120], c0)
            X_files.append(f1)
            y_files.append(0)
            file_names.append(f"Vacuum/{rel} [chunk 1]")
            station_names.append("vacuum")
            X_files.append(f2)
            y_files.append(0)
            file_names.append(f"Vacuum/{rel} [chunk 2]")
            station_names.append("vacuum")
            continue

        elif "Press" in cat or "Fric" in cat:
            if len(arr) > 4:
                arr = arr[4:]
            label = 1
        elif "Pull" in cat:
            label = 2
        else:
            label = 0

        feats = extract_features(arr, c0)
        X_files.append(feats)
        y_files.append(label)
        file_names.append(f"Vacuum/{rel}")
        station_names.append("vacuum")

    return X_files, y_files, file_names, station_names


def run_benchmark() -> None:
    print("=" * 80)
    print("UNIVERSAL CROSS-STATION BENCHMARK (LEGACY BENCH + NEW VACUUM STATION)")
    print("=" * 80)

    X_leg, y_leg, _, _ = load_legacy_corpus()
    print(f"Loaded Legacy Corpus: {len(X_leg)} recordings (Classes: Base={y_leg.count(0)}, Touch/Press={y_leg.count(1)}, Detach={y_leg.count(2)})")

    X_vac, y_vac, _, _ = load_vacuum_corpus()
    print(f"Loaded Vacuum Corpus: {len(X_vac)} recordings/chunks (Classes: Base={y_vac.count(0)}, Touch/Press={y_vac.count(1)}, Detach={y_vac.count(2)})")

    X_all = X_leg + X_vac
    y_all = y_leg + y_vac
    n_all = len(X_all)
    print(f"Total Unified Corpus: {n_all} recordings/chunks\n")

    print("--- EXPERIMENT 1: TRAIN ON LEGACY BENCH -> TEST ON VACUUM STATION ---")
    X_train_leg = np.vstack(X_leg)
    y_train_leg = np.concatenate([np.full(len(X_leg[i]), y_leg[i]) for i in range(len(X_leg))])

    clf_leg = HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced", random_state=42)
    clf_leg.fit(X_train_leg, y_train_leg)

    vac_preds_file: List[int] = []
    for X_test in X_vac:
        preds = clf_leg.predict(X_test)
        vals, counts = np.unique(preds, return_counts=True)
        pred = vals[np.argmax(counts)]
        vac_preds_file.append(pred)

    acc_vac_transfer = accuracy_score(y_vac, vac_preds_file)
    pull_idx_vac = [i for i, y in enumerate(y_vac) if y == 2]
    pull_det_vac = [vac_preds_file[i] == 2 for i in pull_idx_vac]
    pull_recall_vac = np.mean(pull_det_vac) * 100
    print(f"Legacy -> Vacuum Transfer File Accuracy : {acc_vac_transfer * 100:.2f}% ({np.sum(np.array(y_vac) == np.array(vac_preds_file))}/{len(y_vac)})")
    print(f"Legacy -> Vacuum Pull Recall           : {pull_recall_vac:.2f}% ({np.sum(pull_det_vac)}/{len(pull_idx_vac)})\n")

    print("--- EXPERIMENT 2: TRAIN ON VACUUM STATION -> TEST ON LEGACY BENCH ---")
    X_train_vac = np.vstack(X_vac)
    y_train_vac = np.concatenate([np.full(len(X_vac[i]), y_vac[i]) for i in range(len(X_vac))])

    clf_vac = HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced", random_state=42)
    clf_vac.fit(X_train_vac, y_train_vac)

    leg_preds_file: List[int] = []
    for X_test in X_leg:
        preds = clf_vac.predict(X_test)
        vals, counts = np.unique(preds, return_counts=True)
        pred = vals[np.argmax(counts)]
        leg_preds_file.append(pred)

    acc_leg_transfer = accuracy_score(y_leg, leg_preds_file)
    pull_idx_leg = [i for i, y in enumerate(y_leg) if y == 2]
    pull_det_leg = [leg_preds_file[i] == 2 for i in pull_idx_leg]
    pull_recall_leg = np.mean(pull_det_leg) * 100
    print(f"Vacuum -> Legacy Transfer File Accuracy : {acc_leg_transfer * 100:.2f}% ({np.sum(np.array(y_leg) == np.array(leg_preds_file))}/{len(y_leg)})")
    print(f"Vacuum -> Legacy Pull Recall           : {pull_recall_leg:.2f}% ({np.sum(pull_det_leg)}/{len(pull_idx_leg)})\n")

    print("--- EXPERIMENT 3: UNIFIED LOFO CROSS-VALIDATION (ALL 105 RECORDINGS) ---")
    y_true_all: List[int] = []
    y_pred_all: List[int] = []
    total_frames = 0
    correct_frames = 0

    for test_idx in range(n_all):
        X_train_list = [X_all[i] for i in range(n_all) if i != test_idx]
        y_train_list = [y_all[i] for i in range(n_all) if i != test_idx]

        X_tr = np.vstack(X_train_list)
        y_tr = np.concatenate([np.full(len(X_train_list[i]), y_train_list[i]) for i in range(len(X_train_list))])

        X_te = X_all[test_idx]
        y_te_true = y_all[test_idx]

        clf = HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced", random_state=42)
        clf.fit(X_tr, y_tr)

        preds = clf.predict(X_te)
        total_frames += len(preds)
        correct_frames += int(np.count_nonzero(preds == y_te_true))

        vals, counts = np.unique(preds, return_counts=True)
        file_pred = vals[np.argmax(counts)]

        y_true_all.append(y_te_true)
        y_pred_all.append(file_pred)

        if (test_idx + 1) % 15 == 0 or test_idx == n_all - 1:
            print(f"  Processed {test_idx + 1:3d}/{n_all} files...")

    lofo_acc = accuracy_score(y_true_all, y_pred_all)
    frame_acc = correct_frames / total_frames

    print("\n" + "=" * 80)
    print("FINAL UNIFIED BENCHMARK RESULTS")
    print("=" * 80)
    print(f"Unified LOFO File Accuracy : {lofo_acc * 100:.2f}% ({np.sum(np.array(y_true_all) == np.array(y_pred_all))}/{n_all} files)")
    print(f"Unified Frame Accuracy     : {frame_acc * 100:.2f}% ({correct_frames}/{total_frames} frames)")

    labels = ["0: Base", "1: Touch/Press", "2: Detachment"]
    cm = confusion_matrix(y_true_all, y_pred_all)
    print("\nConfusion Matrix (File Level):")
    print("                Pred: Base | Pred: Touch/Press | Pred: Detach")
    for r_idx, row in enumerate(cm):
        print(f"True {labels[r_idx]:15s} : {row[0]:9d} | {row[1]:17d} | {row[2]:12d}")

    pull_indices = [i for i, y in enumerate(y_true_all) if y == 2]
    pull_detected = [y_pred_all[i] == 2 for i in pull_indices]
    pull_recall = np.mean(pull_detected) * 100
    print(f"\nOverall Detachment Recall : {pull_recall:.2f}% ({np.sum(pull_detected)}/{len(pull_indices)} files)")


if __name__ == "__main__":
    run_benchmark()
