"""
Comprehensive Machine Learning & Deep Learning (ResNet-1D / CNN / Ensembles) Benchmark Suite
"""

import time
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, Any
import warnings
warnings.filterwarnings("ignore")

from sklearn.ensemble import (
    RandomForestClassifier,
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    VotingClassifier,
    StackingClassifier
)
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, recall_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.preprocessing import StandardScaler
from sklearn.base import BaseEstimator, ClassifierMixin

import main as M


# _file_vote is NOT redefined here. It used to be a verbatim copy of
# main._file_vote, and that function carries a load-bearing rule - ties break
# toward the MORE SEVERE class, which is what stopped two real class-3 files
# being voted class 1. A private copy of a rule like that drifts silently, and
# then the benchmark measures a different voting scheme from the product it is
# supposed to be choosing an estimator for.
_file_vote = M._file_vote


# -----------------------------------------------------------------------------
# Deep ResNet-1D Architecture (PyTorch implementation wrapped in Scikit-Learn)
# -----------------------------------------------------------------------------

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import TensorDataset, DataLoader

    class ResNet1DBlock(nn.Module):
        def __init__(self, in_features, hidden_features):
            super().__init__()
            self.fc1 = nn.Linear(in_features, hidden_features)
            self.bn1 = nn.BatchNorm1d(hidden_features)
            self.relu = nn.ReLU(inplace=True)
            self.fc2 = nn.Linear(hidden_features, in_features)
            self.bn2 = nn.BatchNorm1d(in_features)
            self.dropout = nn.Dropout(0.15)

        def forward(self, x):
            residual = x
            out = self.fc1(x)
            out = self.bn1(out)
            out = self.relu(out)
            out = self.dropout(out)
            out = self.fc2(out)
            out = self.bn2(out)
            out = self.relu(out + residual)  # Residual Connection
            return out

    class ResNet1DModel(nn.Module):
        def __init__(self, input_dim=36, hidden_dim=64, num_classes=4):
            super().__init__()
            self.input_layer = nn.Sequential(
                nn.Linear(input_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.ReLU(inplace=True)
            )
            self.block1 = ResNet1DBlock(hidden_dim, hidden_dim * 2)
            self.block2 = ResNet1DBlock(hidden_dim, hidden_dim * 2)
            self.classifier = nn.Sequential(
                nn.Linear(hidden_dim, 32),
                nn.ReLU(inplace=True),
                nn.Linear(32, num_classes)
            )

        def forward(self, x):
            x = self.input_layer(x)
            x = self.block1(x)
            x = self.block2(x)
            return self.classifier(x)

    class PyTorchResNetClassifier(BaseEstimator, ClassifierMixin):
        def __init__(self, epochs=40, lr=0.003, batch_size=64):
            self.epochs = epochs
            self.lr = lr
            self.batch_size = batch_size
            self.model = None
            self.scaler = StandardScaler()

        def fit(self, X, y):
            X_scaled = self.scaler.fit_transform(X)
            input_dim = X.shape[1]
            self.model = ResNet1DModel(input_dim=input_dim, hidden_dim=64, num_classes=4)

            # Compute class weights for imbalanced clinical classes
            classes, counts = np.unique(y, return_counts=True)
            weights = len(y) / (len(classes) * counts)
            weight_tensor = torch.tensor(weights, dtype=torch.float32)

            criterion = nn.CrossEntropyLoss(weight=weight_tensor)
            optimizer = optim.AdamW(self.model.parameters(), lr=self.lr, weight_decay=1e-3)

            dataset = TensorDataset(torch.tensor(X_scaled, dtype=torch.float32), torch.tensor(y, dtype=torch.long))
            loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

            self.model.train()
            for epoch in range(self.epochs):
                for batch_x, batch_y in loader:
                    optimizer.zero_grad()
                    outputs = self.model(batch_x)
                    loss = criterion(outputs, batch_y)
                    loss.backward()
                    optimizer.step()
            return self

        def predict(self, X):
            proba = self.predict_proba(X)
            return np.argmax(proba, axis=1)

        def predict_proba(self, X):
            self.model.eval()
            X_scaled = self.scaler.transform(X)
            with torch.no_grad():
                tensor_x = torch.tensor(X_scaled, dtype=torch.float32)
                logits = self.model(tensor_x)
                proba = torch.softmax(logits, dim=1).numpy()
            return proba

    HAS_PYTORCH = True
except ImportError:
    HAS_PYTORCH = False


def build_raw_and_feature_matrix(ds: M.Dataset) -> np.ndarray:
    """The full 36-column feature vector: 25 pad deltas + 9 statistics + 2 gradient.

    This used to hstack `raw_deltas` in front of `extract_features(...)` on the
    reasoning that the result was "25 raw + 11 engineered = 36". It is not:
    extract_features defaults to include_pads=True, so it ALREADY returns the 25
    pad columns. The matrix was 61 wide with every pad delta present twice, and
    the whole leaderboard - including the row that was acted on and put into
    production - was measured on duplicated features under a caption that said
    36. Duplicated columns do not change what a tree can learn, but a benchmark
    whose stated feature set is not the one it ran is not a benchmark anybody can
    reproduce, and it is not the feature set main.py ships either (34: the same
    thing with use_gradient=False).
    """
    raw_deltas = np.vstack(ds.frames)
    return M.extract_features(raw_deltas, use_gradient=True)


def evaluate_model_lofo(model_factory, X: np.ndarray, y: np.ndarray, groups: np.ndarray, name: str) -> Dict[str, Any]:
    logo = list(LeaveOneGroupOut().split(X, y, groups=groups))
    y_true_file = []
    y_pred_file = []
    y_true_frame = []
    y_pred_frame = []
    latencies = []

    for tr, te in logo:
        clf = model_factory()
        clf.fit(X[tr], y[tr])

        t0 = time.perf_counter()
        preds = clf.predict(X[te])
        t1 = time.perf_counter()
        latencies.append((t1 - t0) / max(1, len(te)) * 1000.0)

        y_true_frame.extend(y[te])
        y_pred_frame.extend(preds)

        for f in np.unique(groups[te]):
            m = groups[te] == f
            y_true_file.append(int(y[te][m][0]))
            y_pred_file.append(_file_vote(preds[m]))

    y_true_file = np.array(y_true_file)
    y_pred_file = np.array(y_pred_file)
    y_true_frame = np.array(y_true_frame)
    y_pred_frame = np.array(y_pred_frame)

    file_acc = accuracy_score(y_true_file, y_pred_file)
    file_mf1 = f1_score(y_true_file, y_pred_file, average="macro")
    class_f1 = f1_score(y_true_file, y_pred_file, average=None, labels=[0, 1, 2, 3])

    pull_recall = recall_score(y_true_file == 3, y_pred_file == 3, zero_division=0)

    normal_mask = (y_true_file == 0)
    false_alarm_rate = np.mean(np.isin(y_pred_file[normal_mask], [2, 3])) if normal_mask.sum() > 0 else 0.0
    avg_latency_ms = np.mean(latencies)

    return {
        "name": name,
        "file_accuracy": file_acc * 100.0,
        "file_macro_f1": file_mf1,
        "f1_normal": class_f1[0],
        "f1_touch": class_f1[1],
        "f1_peel": class_f1[2],
        "f1_pull": class_f1[3],
        "pull_recall": pull_recall * 100.0,
        "false_alarm_rate": false_alarm_rate * 100.0,
        "latency_ms": avg_latency_ms,
    }


# =============================================================================
# Repeated grouped k-fold - the mode that produces the estimator-choice figure
# =============================================================================
def repeated_cv(n_repeats: int = 100, n_splits: int = 5) -> Dict[str, Any]:
    """Run each candidate estimator `n_repeats` times and report a DISTRIBUTION.

    One leave-one-file-out number per estimator is not enough to choose on: with
    81 recordings, which files land in which fold moves the result by more than
    the gap between two estimators. This re-draws the split every repeat and
    reports mean, SD and range, so the comparison is between distributions
    rather than between two single draws.

    Not 100 x LOFO: that is 8,100 fits per estimator. Grouped k-fold gives the
    same distribution at 5 fits a repeat, and groups are FILES, so no frame from
    a recording is ever in both train and test.

    Only the winner ships. main.py fits exactly one estimator; the others exist
    to make the choice defensible.
    """
    from sklearn.model_selection import StratifiedGroupKFold
    from sklearn.metrics import recall_score

    ds = M.load_dataset("kalman", verbose=False)
    if ds is None:
        raise SystemExit("no dataset")
    X, y, g = ds.X, ds.y, ds.groups
    file_label = np.array([int(l) for l in ds.labels])
    print(f"  {ds.n_files} files / {len(X)} frames / {X.shape[1]} features · "
          f"{n_repeats} repeats x grouped {n_splits}-fold")

    candidates = [
        ("Random Forest", lambda s: RandomForestClassifier(
            n_estimators=200, max_depth=12, class_weight="balanced_subsample",
            random_state=s, n_jobs=-1)),
        ("Extra Trees", lambda s: ExtraTreesClassifier(
            n_estimators=200, max_depth=12, class_weight="balanced_subsample",
            random_state=s, n_jobs=-1)),
        ("HistGradientBoosting", lambda s: HistGradientBoostingClassifier(
            max_iter=150, max_depth=8, class_weight="balanced", random_state=s)),
    ]

    out: Dict[str, Any] = {}
    for name, factory in candidates:
        t0 = time.time()
        runs = []
        for r in range(n_repeats):
            cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=r)
            oof = np.zeros(len(X), dtype=int)
            for tr, te in cv.split(X, y, groups=g):
                oof[te] = factory(r).fit(X[tr], y[tr]).predict(X[te])
            y_pred = np.array([_file_vote(oof[g == i]) for i in range(ds.n_files)])
            st = M.evaluate_stream(ds, 42, verbose=False, oof=oof)
            rec = recall_score(file_label, y_pred, labels=list(range(M.N_CLASSES)),
                               average=None, zero_division=0)
            runs.append({
                "file_accuracy": float(accuracy_score(file_label, y_pred)),
                "frame_accuracy": float((oof == y).mean()),
                "macro_f1": float(f1_score(file_label, y_pred, average="macro", zero_division=0)),
                "recall_peel": float(rec[2]), "recall_pull": float(rec[3]),
                "sensitivity": float(st["sensitivity"]),
                "alarms_per_hour": float(st["alarms_per_hour"]),
                "fa_per_recording": float(st["false_alarm_rate"]),
            })
        out[name] = runs
        acc = np.array([x["file_accuracy"] for x in runs]) * 100
        sen = np.array([x["sensitivity"] for x in runs]) * 100
        pul = np.array([x["recall_pull"] for x in runs])
        print(f"  {name:22s} acc {acc.mean():6.2f} +/- {acc.std(ddof=1):4.2f} "
              f"[{acc.min():.2f}, {acc.max():.2f}]   episode sens {sen.mean():5.1f} +/- {sen.std(ddof=1):4.1f}   "
              f"pull recall {pul.mean():.3f} +/- {pul.std(ddof=1):.3f}   ({time.time()-t0:.0f}s)")

    dest = os.path.join(M.DATA_ROOT, "model_comparison_100x.json")
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"\n  per-repeat results -> {dest}")
    print("  Paste the table into Data/model_comparison_benchmark.md; do not retype it.")
    return out


def main():
    print("=" * 80)
    print("COMPREHENSIVE BENCHMARK: MACHINE LEARNING & RESNET ARCHITECTURES")
    print("=" * 80)

    print("\nLoading clinical dataset...")
    ds = M.load_dataset("kalman", verbose=False)
    if ds is None:
        print("ERROR: No dataset found.")
        return
    print(f"Loaded {ds.n_files} recordings, {len(ds.X)} frames across 4 classes.")

    # ds.X is what main.py trains on: 34 columns (25 pad deltas + 9 statistics),
    # NOT the 11 the label below claimed. The comparison rows are named from
    # these two shapes, so the names are derived rather than typed.
    X_std = ds.X
    X_comb = build_raw_and_feature_matrix(ds)
    n_std, n_comb = X_std.shape[1], X_comb.shape[1]
    print(f"  feature matrices: production {n_std} columns, +gradient {n_comb} columns")
    y = ds.y
    groups = ds.groups

    models = [
        # 1. Current Baseline: Random Forest (11 features)
        (f"1. Random Forest, production features ({n_std})", lambda: RandomForestClassifier(n_estimators=200, max_depth=12, class_weight="balanced_subsample", random_state=42, n_jobs=-1), X_std),

        # 2. Random Forest on Combined 36 features
        (f"2. Random Forest, +gradient ({n_comb})", lambda: RandomForestClassifier(n_estimators=200, max_depth=14, class_weight="balanced_subsample", random_state=42, n_jobs=-1), X_comb),

        # 3. Extra Trees Classifier (Extremely Randomized Trees)
        (f"3. Extra Trees, +gradient ({n_comb})", lambda: ExtraTreesClassifier(n_estimators=250, max_depth=14, class_weight="balanced_subsample", random_state=42, n_jobs=-1), X_comb),

        # 4. HistGradientBoosting (LightGBM-style)
        (f"4. HistGradientBoosting, +gradient ({n_comb})", lambda: HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced", random_state=42), X_comb),

        # 5. Multi-Layer Perceptron (Deep MLP)
        (f"5. Deep MLP, +gradient ({n_comb})", lambda: MLPClassifier(hidden_layer_sizes=(128, 64, 32), activation="relu", max_iter=250, random_state=42, early_stopping=True), X_comb),

        # 6. Ensemble Meta-Stacking (RF + ExtraTrees + HistGBM)
        (f"6. Ensemble Meta-Stacking, +gradient ({n_comb})", lambda: StackingClassifier(
            estimators=[
                ("rf", RandomForestClassifier(n_estimators=100, max_depth=10, class_weight="balanced_subsample", random_state=42, n_jobs=-1)),
                ("et", ExtraTreesClassifier(n_estimators=100, max_depth=10, class_weight="balanced_subsample", random_state=42, n_jobs=-1)),
                ("hgb", HistGradientBoostingClassifier(max_iter=100, max_depth=6, class_weight="balanced", random_state=42))
            ],
            final_estimator=LogisticRegression(class_weight="balanced", max_iter=200),
            n_jobs=-1
        ), X_comb),

        # 7. Soft Voting Ensemble (RF + ExtraTrees + HistGBM)
        (f"7. Soft Voting Ensemble, +gradient ({n_comb})", lambda: VotingClassifier(
            estimators=[
                ("rf", RandomForestClassifier(n_estimators=150, max_depth=12, class_weight="balanced_subsample", random_state=42, n_jobs=-1)),
                ("et", ExtraTreesClassifier(n_estimators=150, max_depth=12, class_weight="balanced_subsample", random_state=42, n_jobs=-1)),
                ("hgb", HistGradientBoostingClassifier(max_iter=120, max_depth=7, class_weight="balanced", random_state=42))
            ],
            voting="soft",
            n_jobs=-1
        ), X_comb)
    ]

    if HAS_PYTORCH:
        models.append(("8. PyTorch ResNet-1D with Skip Connections", lambda: PyTorchResNetClassifier(epochs=35, lr=0.003, batch_size=64), X_comb))

    results = []
    print("\nRunning Leave-One-File-Out (LOFO) Cross Validation across all architectures...\n")

    for name, factory, data_x in models:
        print(f"Evaluating: {name} ...", flush=True)
        res = evaluate_model_lofo(factory, data_x, y, groups, name)
        results.append(res)
        print(f"  -> Acc: {res['file_accuracy']:.2f}% | Macro F1: {res['file_macro_f1']:.4f} | Peel F1: {res['f1_peel']:.4f} | Pull Recall: {res['pull_recall']:.1f}% | Latency: {res['latency_ms']:.3f} ms\n")

    df_res = pd.DataFrame(results)

    print("\n" + "=" * 95)
    print("ARCHITECTURE COMPARISON LEADERBOARD")
    print("=" * 95)
    print(df_res[["name", "file_accuracy", "file_macro_f1", "f1_peel", "f1_pull", "pull_recall", "false_alarm_rate", "latency_ms"]].to_string(index=False))

    os.makedirs("Data", exist_ok=True)
    df_res.to_json("Data/ml_architecture_benchmark_results.json", indent=2)
    print("\nDetailed results saved to Data/ml_architecture_benchmark_results.json")
    print("\nNOTE: file-level LOFO accuracy is NOT the unit this project reports. It "
          "depends on clip length (see the length-invariance caveat) and it says "
          "nothing about the alarm burden a ward would carry. Before adopting any "
          "row here, re-run `python main.py --report --stream` with that estimator "
          "and compare episode sensitivity and alarms/hour.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Estimator comparison for the report. "
                                             "main.py ships exactly one of these.")
    ap.add_argument("--repeats", type=int, default=0,
                    help="run N repeats of grouped 5-fold per estimator and report "
                         "mean +/- SD (the mode behind the estimator-choice figure). "
                         "0 = the single leave-one-file-out leaderboard instead.")
    ap.add_argument("--splits", type=int, default=5, help="folds per repeat (default 5)")
    args = ap.parse_args()
    if args.repeats > 0:
        repeated_cv(args.repeats, args.splits)
    else:
        main()
