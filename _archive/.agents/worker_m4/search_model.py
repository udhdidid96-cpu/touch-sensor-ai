import os
import sys
import time
from joblib import Parallel, delayed

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.tree import DecisionTreeClassifier

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

def eval_fold(clf, tr, te):
    clf.fit(X[tr], y[tr])
    if hasattr(clf, "predict_proba"):
        p = clf.predict_proba(X[te])
        classes = getattr(clf, "classes_", None)
        if classes is not None:
            pred_lbl = classes[p.mean(axis=0).argmax()]
        else:
            pred_lbl = 0
    else:
        p = clf.predict(X[te])
        pred_lbl = p[0]
    return y[te][0], pred_lbl

candidates = [
    ("HGBD max_iter=25", HistGradientBoostingClassifier(learning_rate=0.15, max_iter=25, max_depth=8, random_state=42)),
    ("RF n=25 max_depth=12", RandomForestClassifier(n_estimators=25, max_depth=12, random_state=42)),
    ("ET n=25 max_depth=12", ExtraTreesClassifier(n_estimators=25, max_depth=12, random_state=42)),
    ("KNN n=3", KNeighborsClassifier(n_neighbors=3)),
    ("DT max_depth=10", DecisionTreeClassifier(max_depth=10, random_state=42)),
    ("RF n=30 max_depth=10", RandomForestClassifier(n_estimators=30, max_depth=10, random_state=42)),
]

for name, clf in candidates:
    t0 = time.perf_counter()
    results = Parallel(n_jobs=-1)(
        delayed(eval_fold)(clf, tr, te) for tr, te in splits
    )
    t1 = time.perf_counter()
    y_t = [r[0] for r in results]
    y_p = [r[1] for r in results]
    acc = accuracy_score(y_t, y_p)
    print(f"{name:25s}: Accuracy = {acc*100:6.2f}%, Execution Time = {t1-t0:6.4f}s")
