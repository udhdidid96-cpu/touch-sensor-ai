"""Phase-1 architecture benchmark: does anything beat the shipped HistGradientBoosting?

Research only. Nothing in the serving path imports this file, and it writes nothing
under Data/ (results go to stdout; pass --json PATH to keep them).

Two corpora, scored separately because they cannot be pooled honestly:

  LEGACY  the 81 bench recordings in Data/<class>/*.csv, 4 classes, Kalman deltas
          (main.load_dataset("kalman")), leave-one-file-out, majority vote per file, and
          the episode line: the out-of-fold frame votes replayed through the shipped
          annunciator (main.evaluate_stream), i.e. sensitivity, false-alarm recordings,
          alarms/hour and time to alarm on the OFFLINE path. The served path
          (LivePipeline) is not re-run here.

  VACUUM  the 24 files in Data/data new vaccum/, 3 classes, deltas against the
          N_base1 C0 (scripts/evaluate_vacuum_station.py). Every model is scored on
          three controls, never on the 25-item headline alone:
            strict 24-file LOFO,
            settled tails (attached-and-still frames of pull files; fewer "pull"
            calls is better: those frames are not a pull),
            leave the last attachment out (7 files, re-attached patch never seen).

Representations
  F       the frame features each corpus already uses (34 legacy / 40 vacuum).
  F+T     F plus 12 causal temporal features over the last WINDOW frames
          (first and third differences, rolling extremes, motion energy).
          Causal, so the served path could compute them from the frames it holds.
  T+S     attachment-invariant: the temporal block plus within-window detrended
          spatial statistics, and no absolute delta at all. A static per-pad
          offset (a different attachment, an unattached patch) is invisible to it
          by construction. This is the physics question the vacuum set raises:
          is a pull recognisable from what changes, rather than from where the
          patch happens to rest?

Estimators
  hgb     production configuration (main.new_rf): HGB(150, depth 8, balanced).
  lgbm    LightGBM, matched capacity. Skipped if lightgbm is not installed.
  xgb     XGBoost, matched capacity, balanced sample weights. Skipped if absent.
  cnn     1-D temporal CNN over a WINDOW x 25 pad-delta window (+ stats channels).
          Skipped if torch is absent.
  ens     calibrated soft vote: isotonic-calibrated HGB + ExtraTrees, averaged.

Run:  python scripts/benchmark_architectures.py [--quick] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.utils.class_weight import compute_sample_weight

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M  # noqa: E402
import evaluate_vacuum_station as V  # noqa: E402

warnings.filterwarnings("ignore")

WINDOW = M.WINDOW_FRAMES  # 6 frames = 3.4 s, the same window main.py's temporal model uses

try:
    import lightgbm as lgb
except ImportError:
    lgb = None
try:
    import xgboost as xgb
except ImportError:
    xgb = None
try:
    import torch
    import torch.nn as nn
except ImportError:
    torch = None


# --------------------------------------------------------------------------- features

def temporal_features(d: np.ndarray, w: int = WINDOW) -> np.ndarray:
    """12 causal features per frame from the deltas of frames t-w+1..t of one file."""
    d = np.asarray(d, float)
    n = len(d)
    prev1 = np.vstack([d[:1], d[:-1]])
    prev3 = np.vstack([np.repeat(d[:1], 3, axis=0), d[:-3]])[:n]
    v1, v3 = d - prev1, d - prev3
    fmin, fmean = d.min(1), d.mean(1)
    nlift = (d <= M.LIFT_GATE_COUNTS).sum(1).astype(float)
    energy = np.abs(v1).sum(1)
    out = np.empty((n, 12))
    for t in range(n):
        s = slice(max(0, t - w + 1), t + 1)
        out[t] = (v1[t].mean(), v1[t].min(), v1[t].max(),
                  v3[t].mean(), v3[t].min(), v3[t].max(),
                  fmin[s].min(), fmean[s].std(), nlift[s].max(),
                  energy[s].sum(), energy[s].max(), (fmin[s][-1] - fmin[s][0]))
    return out


# temporal_features columns that are differences only. Dropped: the rolling minimum delta (6),
# the rolling lifted-pad count (8) and the change in the frame minimum (11) - which pad is the
# minimum depends on the per-pad offset, so a min-of-levels is not offset-free even when
# differenced (tests/test_benchmark_architectures.py checks this).
INVARIANT_T = [0, 1, 2, 3, 4, 5, 7, 9, 10]


def invariant_features(d: np.ndarray, w: int = WINDOW) -> np.ndarray:
    """Difference-only temporal terms + window-detrended spatial statistics (15 columns).
    No absolute level enters: every term is a difference between frames of the same file."""
    d = np.asarray(d, float)
    n = len(d)
    spat = np.empty((n, 6))
    for t in range(n):
        s = d[max(0, t - w + 1):t + 1]
        r = d[t] - s[0]                      # change across the window, per pad
        g = r.reshape(5, 5)
        spat[t] = (r.min(), r.max(), r.std(),
                   float(np.abs(np.diff(g, axis=0)).mean()),
                   float(np.abs(np.diff(g, axis=1)).mean()),
                   float((r <= M.LIFT_GATE_COUNTS).sum()))
    return np.hstack([temporal_features(d, w)[:, INVARIANT_T], spat])


def windows(d: np.ndarray, w: int = WINDOW) -> np.ndarray:
    """(n, w, 25) causal windows, left-padded with the first frame."""
    pad = np.vstack([np.repeat(d[:1], w - 1, axis=0), d])
    return np.stack([pad[t:t + w] for t in range(len(d))])


# --------------------------------------------------------------------------- estimators

def make_hgb(seed: int = 42):
    return HistGradientBoostingClassifier(max_iter=150, max_depth=8, class_weight="balanced", random_state=seed)


class _Weighted:
    """Wraps a booster so fit() gets balanced sample weights, like class_weight=balanced."""

    def __init__(self, est):
        self.est = est

    def fit(self, X, y):
        self.est.fit(X, y, sample_weight=compute_sample_weight("balanced", y))
        return self

    def predict(self, X):
        return np.asarray(self.est.predict(X)).astype(int).ravel()


def make_lgbm(seed: int = 42):
    return _Weighted(lgb.LGBMClassifier(n_estimators=150, max_depth=8, num_leaves=31, learning_rate=0.1,
                                        random_state=seed, verbose=-1, n_jobs=2))


class _XGB(_Weighted):
    """XGBoost needs labels 0..k-1; a LOFO fold can drop a class."""

    def fit(self, X, y):
        self.classes_ = np.unique(y)
        idx = np.searchsorted(self.classes_, y)
        self.est.fit(X, idx, sample_weight=compute_sample_weight("balanced", y))
        return self

    def predict(self, X):
        return self.classes_[np.asarray(self.est.predict(X)).astype(int)]


def make_xgb(seed: int = 42):
    return _XGB(xgb.XGBClassifier(n_estimators=150, max_depth=6, learning_rate=0.1, subsample=0.9,
                                  random_state=seed, n_jobs=2, verbosity=0))


class SoftVote:
    """Isotonic-calibrated HGB + ExtraTrees, probabilities averaged."""

    def __init__(self, seed: int = 42):
        self.seed = seed

    def fit(self, X, y):
        self.classes_ = np.unique(y)
        cv = 3 if np.bincount(y).min(initial=99) >= 3 or len(self.classes_) < 2 else 2
        self.m = [CalibratedClassifierCV(make_hgb(self.seed), method="isotonic", cv=cv).fit(X, y),
                  ExtraTreesClassifier(n_estimators=200, max_depth=12, class_weight="balanced_subsample",
                                       random_state=self.seed, n_jobs=2).fit(X, y)]
        return self

    def predict(self, X):
        p = sum(m.predict_proba(X) for m in self.m) / len(self.m)
        return self.classes_[p.argmax(1)]


class TemporalCNN:
    """Conv1d over time, 25 pad channels (+ k feature channels), standardised inputs."""

    def __init__(self, epochs: int = 30, seed: int = 0):
        self.epochs, self.seed = epochs, seed

    def _net(self, c_in: int, n_out: int):
        return nn.Sequential(nn.Conv1d(c_in, 32, 3, padding=1), nn.BatchNorm1d(32), nn.ReLU(),
                             nn.Conv1d(32, 32, 3, padding=1), nn.BatchNorm1d(32), nn.ReLU(),
                             nn.AdaptiveMaxPool1d(1), nn.Flatten(), nn.Dropout(0.2), nn.Linear(32, n_out))

    def fit(self, X, y):
        torch.manual_seed(self.seed)
        np.random.seed(self.seed)
        self.classes_ = np.unique(y)
        yi = np.searchsorted(self.classes_, y)
        self.mu = X.mean((0, 1), keepdims=True)
        self.sd = X.std((0, 1), keepdims=True) + 1e-6
        xt = torch.tensor(((X - self.mu) / self.sd).transpose(0, 2, 1), dtype=torch.float32)
        yt = torch.tensor(yi, dtype=torch.long)
        self.net = self._net(xt.shape[1], len(self.classes_))
        w = torch.tensor(len(yi) / (len(self.classes_) * np.bincount(yi)), dtype=torch.float32)
        opt = torch.optim.AdamW(self.net.parameters(), lr=3e-3, weight_decay=1e-3)
        lossf = nn.CrossEntropyLoss(weight=w)
        self.net.train()
        for _ in range(self.epochs):
            perm = torch.randperm(len(xt))
            for i in range(0, len(xt), 128):
                b = perm[i:i + 128]
                if len(b) < 2:
                    continue
                opt.zero_grad()
                lossf(self.net(xt[b]), yt[b]).backward()
                opt.step()
        return self

    def predict(self, X):
        self.net.eval()
        with torch.no_grad():
            xt = torch.tensor(((X - self.mu) / self.sd).transpose(0, 2, 1), dtype=torch.float32)
            return self.classes_[self.net(xt).argmax(1).numpy()]


def estimators(quick: bool, ens: bool = True) -> List[Tuple[str, Callable[[], Any]]]:
    out: List[Tuple[str, Callable[[], Any]]] = [("hgb", make_hgb)]
    if lgb is not None:
        out.append(("lgbm", make_lgbm))
    if xgb is not None:
        out.append(("xgb", make_xgb))
    if not quick and ens:
        out.append(("ens", SoftVote))
    return out


# --------------------------------------------------------------------------- scoring

def vote(p: np.ndarray, n_classes: int) -> int:
    """Majority vote, ties toward the higher (more alarming) class, as main.file_vote."""
    c = np.bincount(np.asarray(p, int), minlength=n_classes)
    return int(len(c) - 1 - int(np.argmax(c[::-1])))


def lofo_items(X: Sequence[np.ndarray], y: Sequence[int], factory: Callable[[], Any],
               skip: Optional[Sequence[int]] = None) -> List[np.ndarray]:
    """Leave one item out. X[i] is item i's (n_i, ...) matrix, y[i] its label."""
    preds: List[np.ndarray] = []
    for i in range(len(X)):
        tr = [j for j in range(len(X)) if j != i]
        clf = factory().fit(np.concatenate([X[j] for j in tr]),
                            np.concatenate([np.full(len(X[j]), y[j]) for j in tr]))
        preds.append(np.asarray(clf.predict(X[i])).astype(int))
    return preds


def ci(k: int, n: int) -> str:
    lo, hi = M.wilson(k, n)
    return f"{k}/{n} ({100 * k / max(n, 1):.1f}%, 95% CI {100 * lo:.0f}-{100 * hi:.0f})"


# --------------------------------------------------------------------------- legacy

def legacy(models: Sequence[Tuple[str, Callable[[], Any]]], use_cnn: bool,
           only_reps: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    ds = M.load_dataset("kalman", verbose=False)
    assert ds is not None and ds.n_files == 81, "expected the 81 bench recordings"
    labels = np.array(ds.labels)
    split = np.cumsum([len(f) for f in ds.frames])[:-1]
    F = np.split(ds.X, split)
    T = [temporal_features(d) for d in ds.frames]
    S = [invariant_features(d) for d in ds.frames]
    reps = {"F": F, "F+T": [np.hstack([a, b]) for a, b in zip(F, T)], "T+S": S}
    hp = np.array(["Horizontal Pull" in f for f in ds.files])
    out: Dict[str, Any] = {}
    print(f"\nLEGACY bench: {ds.n_files} files, {len(ds.X)} frames, 4 classes "
          f"(base {sum(labels == 0)}, touch/press {sum(labels == 1)}, peel {sum(labels == 2)}, pull {sum(labels == 3)})")
    print(f"  {'model':16s} {'file acc':>24s} {'pull recall':>22s} {'HPull':>6s} {'peel rec':>9s} "
          f"{'non-alarm->alarm':>16s} {'frame acc':>9s} | {'episode sens':>12s} {'FA rec':>6s} {'alarm/h':>7s} "
          f"{'t-alarm':>7s} {'s':>5s}")
    runs = [(f"{m}/{r}", f, reps[r]) for r in reps if not only_reps or r in only_reps for m, f in models]
    if use_cnn:
        W = [np.concatenate([windows(d), np.repeat(t[:, None, :], WINDOW, 1)], axis=2)
             for d, t in zip(ds.frames, T)]
        runs.append(("cnn/window", TemporalCNN, W))
    for name, factory, X in runs:
        t0 = time.time()
        p = lofo_items(X, labels, factory)
        v = np.array([vote(q, 4) for q in p])
        frames_ok = sum(int((q == lab).sum()) for q, lab in zip(p, labels))
        fa = int(np.isin(v[labels <= 1], [2, 3]).sum())
        oof = np.concatenate(p)  # files are contiguous and in ds order, so this is ds.y's order
        st = M.evaluate_stream(ds, verbose=False, oof=oof)
        r = {"episode_sensitivity": float(st["sensitivity"]), "episode_missed": list(st["missed"]),
             "false_alarm_files_episode": int(st["false_alarm_files"]),
             "alarms_per_hour": float(st["alarms_per_hour"]), "median_latency_s": st["median_latency_s"],
             "file_acc": float((v == labels).mean()), "pull_recall": float((v[labels == 3] == 3).mean()),
             "hpull_hit": int((v[hp] == 3).sum()), "peel_recall": float((v[labels == 2] == 2).mean()),
             "false_alarm_files": fa, "frame_acc": frames_ok / len(ds.X),
             "confusion": [[int(((labels == a) & (v == b)).sum()) for b in range(4)] for a in range(4)]}
        out[name] = r
        print(f"  {name:16s} {ci(int((v == labels).sum()), 81):>24s} {ci(int((v[labels == 3] == 3).sum()), int((labels == 3).sum())):>22s} "
              f"{r['hpull_hit']:>3d}/10 {100 * r['peel_recall']:8.1f}% {fa:>9d}/{int((labels <= 1).sum())} {100 * r['frame_acc']:8.2f}% "
              f"| {100 * r['episode_sensitivity']:11.1f}% {r['false_alarm_files_episode']:>3d}/41 {r['alarms_per_hour']:7.1f} "
              f"{(r['median_latency_s'] or float('nan')):6.2f}s {time.time() - t0:5.0f}", flush=True)
    return out


# --------------------------------------------------------------------------- vacuum

def vacuum(models: Sequence[Tuple[str, Callable[[], Any]]], use_cnn: bool,
           only_reps: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    c0 = V.get_seated_baseline()
    items = V.load_dataset(chunked=False)
    names = [n for n, _, _ in items]
    y = np.array([lab for _, lab, _ in items])
    D = [a - c0 for _, _, a in items]
    F = [V.extract_features(a, c0) for _, _, a in items]
    T = [temporal_features(d) for d in D]
    reps = {"F": F, "F+T": [np.hstack([a, b]) for a, b in zip(F, T)], "T+S": [invariant_features(d) for d in D]}
    tails = [i for i, (n, lab, a) in enumerate(items)
             if lab == 2 and n not in V.ENDS_DETACHED
             and np.abs(a[-V.TAIL:] - a[-V.TAIL:].mean(0)).max() <= V.NOISE_GATE]
    last = [i for i, n in enumerate(names) if n in V.LAST_ATTACHMENT]
    rest = [i for i in range(len(items)) if i not in last]
    hard = [i for i, n in enumerate(names) if "HPull" in n or "OPull" in n]
    print(f"\nVACUUM station: {len(items)} files (strict, N_base1 whole), 3 classes, deltas vs N_base1 C0")
    print(f"  {'model':16s} {'strict LOFO':>24s} {'pull rec':>8s} {'H/OPull':>7s} {'press->pull':>11s} "
          f"{'tails->pull':>11s} {'last-attach':>11s} {'s':>5s}")
    runs = [(f"{m}/{r}", f, reps[r]) for r in reps if not only_reps or r in only_reps for m, f in models]
    if use_cnn:
        runs.append(("cnn/window", TemporalCNN,
                     [np.concatenate([windows(d), np.repeat(t[:, None, :], WINDOW, 1)], axis=2) for d, t in zip(D, T)]))
    out: Dict[str, Any] = {}
    for name, factory, X in runs:
        t0 = time.time()
        p = lofo_items(X, y, factory)
        v = np.array([vote(q, 3) for q in p])
        tail_calls = sum(int((p[i][-V.TAIL:] == 2).sum()) for i in tails)
        clf = factory().fit(np.concatenate([X[j] for j in rest]),
                            np.concatenate([np.full(len(X[j]), y[j]) for j in rest]))
        lv = [vote(np.asarray(clf.predict(X[i])).astype(int), 3) for i in last]
        r = {"strict_acc": float((v == y).mean()), "pull_recall": float((v[y == 2] == 2).mean()),
             "hard_hit": int((v[hard] == 2).sum()), "press_to_pull": int((v[y == 1] == 2).sum()),
             "tail_pull_frames": tail_calls, "tail_frames": len(tails) * V.TAIL,
             "last_attachment_pull_votes": int(sum(x == 2 for x in lv)),
             "last_attachment_votes": {names[i]: int(x) for i, x in zip(last, lv)},
             "strict_votes": {n: int(x) for n, x in zip(names, v)}}
        out[name] = r
        print(f"  {name:16s} {ci(int((v == y).sum()), len(y)):>24s} {int((v[y == 2] == 2).sum()):>5d}/13 "
              f"{r['hard_hit']:>5d}/6 {r['press_to_pull']:>9d}/7 {tail_calls:>6d}/{len(tails) * V.TAIL:<4d} "
              f"{r['last_attachment_pull_votes']:>8d}/7 {time.time() - t0:5.0f}", flush=True)
    return out


def served_levels(model: Any, raw: np.ndarray, temporal: bool) -> np.ndarray:
    """Annunciated level per frame on the SERVED path, for a model on F or F+T.

    LivePipeline's deltas do not depend on the model (Kalman, quiescent recovery and
    F10 normalisation read only the raw frames), so they are taken from a model-less
    pipeline and then classified exactly as classify_deltas does: frames under the
    60-count noise gate are baseline without calling the model, warm-up frames are
    level 0, and every frame goes through a fresh AlarmDebouncer. For F+T the temporal
    block is computed causally over the served deltas seen so far.
    """
    pipe, deb, hist, out = M.LivePipeline(None), M.AlarmDebouncer(), [], []
    for row in np.asarray(raw, dtype=float):
        fr = pipe.process(row)
        d = np.asarray(fr["normalized_deltas"], dtype=float)
        hist.append(d)
        level = 0
        if not fr["warming_up"] and np.abs(d).max() >= M.NOISE_GATE_COUNTS:
            x = M.extract_features(d[None, :], use_gradient=False)
            if temporal:
                x = np.hstack([x, temporal_features(np.vstack(hist[-WINDOW:]))[-1:]])
            level = int(M.full_proba(model, x).argmax(axis=1)[0])
        out.append(deb.update(level))
    return np.asarray(out, dtype=int)


def served_compare() -> Dict[str, Any]:
    """Leave-one-file-out on the 81 bench files; shipped F vs F+T, scored on the served path."""
    ds = M.load_dataset("kalman", verbose=False)
    assert ds is not None and ds.n_files == 81
    XF = ds.X
    XT = np.hstack([XF, np.vstack([temporal_features(d) for d in ds.frames])])
    raws = [M.read_raw_csv(os.path.join(M.DATA_ROOT, f)) for f in ds.files]
    out: Dict[str, Any] = {}
    print("\nSERVED PATH (LivePipeline deltas, noise gate, warm-up, 7-of-6 hold 9), 81 files LOFO")
    for name, X, temporal in (("hgb/F", XF, False), ("hgb/F+T", XT, True)):
        t0, levels = time.time(), []
        for fi in range(ds.n_files):
            tr = ds.groups != fi
            clf = make_hgb().fit(X[tr], ds.y[tr])
            levels.append(served_levels(clf, raws[fi], temporal))
        st = M.evaluate_served(ds, levels, verbose=False)
        out[name] = {k: st[k] for k in ("sensitivity", "false_alarm_rate", "alarms_per_hour", "median_latency_s", "missed")}
        print(f"  {name:8s} episodes {round(st['sensitivity'] * 40)}/40  FA rec {round(st['false_alarm_rate'] * 41)}/41  "
              f"alarms/h {st['alarms_per_hour']:.2f}  median t-alarm {st['median_latency_s']:.2f}s  missed {st['missed']}  "
              f"({time.time() - t0:.0f}s)", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true", help="skip the calibrated ensemble and the CNN")
    ap.add_argument("--only", choices=("legacy", "vacuum"), help="run one corpus")
    ap.add_argument("--json", help="write results here (not under Data/)")
    ap.add_argument("--reps", help="comma list of representations to run (F,F+T,T+S); default all")
    ap.add_argument("--no-cnn", action="store_true", help="skip the temporal CNN")
    ap.add_argument("--no-ens", action="store_true", help="skip the calibrated soft-vote ensemble (slowest)")
    ap.add_argument("--served", action="store_true", help="only: shipped F vs F+T on the served path (LivePipeline)")
    a = ap.parse_args()
    if a.json and os.path.realpath(a.json).startswith(M.DATA_ROOT):
        raise SystemExit("refusing to write results under Data/ (Data/ holds recordings only)")
    models = estimators(a.quick, not a.no_ens)
    use_cnn = torch is not None and not a.quick and not a.no_cnn
    only = a.reps.split(",") if a.reps else None
    print("estimators:", ", ".join(m for m, _ in models) + (", cnn" if use_cnn else ""),
          "| missing:", ", ".join(k for k, v in (("lightgbm", lgb), ("xgboost", xgb), ("torch", torch)) if v is None) or "none")
    res: Dict[str, Any] = {"window_frames": WINDOW}
    if a.served:
        res["served"] = served_compare()
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=1)
        return 0
    if a.only != "vacuum":
        res["legacy"] = legacy(models, use_cnn, only)
    if a.only != "legacy":
        res["vacuum"] = vacuum(models, use_cnn, only)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print(f"\nresults -> {a.json}")
    print("\nFile accuracy is not this project's reporting unit; any row adopted here must be re-run "
          "through `python main.py --report --stream` (episode sensitivity, alarms/hour, served path).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
