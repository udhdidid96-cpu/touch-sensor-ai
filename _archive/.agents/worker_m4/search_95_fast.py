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
from sklearn.neighbors import KNeighborsClassifier

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

def eval_candidate(base_clf):
    def eval_fold(tr, te):
        clf = clone(base_clf)
        clf.fit(X[tr], y[tr])
        probs = clf.predict_proba(X[te])
        classes = getattr(clf, "classes_", None)
        if classes is not None:
            pred_lbl = classes[probs.mean(axis=0).argmax()]
        else:
            pred_lbl = 0
        return y[te][0], pred_lbl

    t0 = time.perf_counter()
    results = Parallel(n_jobs=-1)(delayed(eval_fold)(tr, te) for tr, te in splits)
    t1 = time.perf_counter()
    y_t = [r[0] for r in results]
    y_p = [r[1] for r in results]
    acc = accuracy_score(y_t, y_p)
    return acc, t1 - t0

candidates = [
    ("ET n=30 max_depth=None", ExtraTreesClassifier(n_estimators=30, random_state=42)),
    ("ET n=40 max_depth=None", ExtraTreesClassifier(n_estimators=40, random_state=42)),
    ("ET n=50 max_depth=None", ExtraTreesClassifier(n_estimators=50, random_state=42)),
    ("ET n=30 max_depth=15", ExtraTreesClassifier(n_estimators=30, max_depth=15, random_state=42)),
    ("ET n=40 max_depth=15", ExtraTreesClassifier(n_estimators=40, max_depth=15, random_state=42)),
    ("RF n=40 max_depth=None", RandomForestClassifier(n_estimators=40, random_state=42)),
    ("HGBD max_iter=30", HistGradientBoostingClassifier(max_iter=30, random_state=42)),
]

for name, clf in candidates:
    acc, exec_time = eval_candidate(clf)
    print(f"{name:35s}: Accuracy = {acc*100:6.2f}%, Execution Time = {exec_time:6.4f}s")
