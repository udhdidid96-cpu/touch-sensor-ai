import os
import sys
import time
from joblib import Parallel, delayed
from sklearn.base import clone

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

def eval_fold_cloned(base_clf, tr, te):
    clf = clone(base_clf)
    clf.fit(X[tr], y[tr])
    probs = clf.predict_proba(X[te])
    classes = getattr(clf, "classes_", None)
    if classes is not None:
        pred_lbl = classes[probs.mean(axis=0).argmax()]
    else:
        pred_lbl = 0
    return y[te][0], pred_lbl

models = [
    ("HGBD 80 (Sequential)", HistGradientBoostingClassifier(learning_rate=0.1, max_iter=80, max_depth=10, random_state=42)),
    ("HGBD 80 (Parallel)", HistGradientBoostingClassifier(learning_rate=0.1, max_iter=80, max_depth=10, random_state=42)),
    ("RF 50 max_depth=15 (Parallel)", RandomForestClassifier(n_estimators=50, max_depth=15, random_state=42, n_jobs=-1)),
    ("ET 50 max_depth=15 (Parallel)", ExtraTreesClassifier(n_estimators=50, max_depth=15, random_state=42, n_jobs=-1)),
]

for name, clf in models:
    t0 = time.perf_counter()
    if "Sequential" in name:
        results = [eval_fold_cloned(clf, tr, te) for tr, te in splits]
    else:
        results = Parallel(n_jobs=-1)(delayed(eval_fold_cloned)(clf, tr, te) for tr, te in splits)
    t1 = time.perf_counter()
    y_t = [r[0] for r in results]
    y_p = [r[1] for r in results]
    acc = accuracy_score(y_t, y_p)
    print(f"{name:32s}: Accuracy = {acc*100:6.2f}%, Execution Time = {t1-t0:6.4f}s")
