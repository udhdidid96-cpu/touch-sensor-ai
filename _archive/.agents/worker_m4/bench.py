import os
import sys
import time

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression, RidgeClassifier

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()

models = [
    ("HGBD 80 (original)", HistGradientBoostingClassifier(learning_rate=0.1, max_iter=80, max_depth=10, random_state=42)),
    ("HGBD 20", HistGradientBoostingClassifier(learning_rate=0.1, max_iter=20, max_depth=6, random_state=42)),
    ("RF 15 (n_jobs=-1)", RandomForestClassifier(n_estimators=15, max_depth=8, random_state=42, n_jobs=-1)),
    ("ET 15 (n_jobs=-1)", ExtraTreesClassifier(n_estimators=15, max_depth=8, random_state=42, n_jobs=-1)),
    ("Ridge", RidgeClassifier()),
]

for name, clf in models:
    t0 = time.perf_counter()
    y_t, y_p = [], []
    for tr, te in logo.split(X, y, groups=groups):
        clf.fit(X[tr], y[tr])
        if hasattr(clf, "predict_proba"):
            p = clf.predict_proba(X[te])
            classes = getattr(clf, "classes_", None)
            if classes is not None:
                y_p.append(classes[p.mean(axis=0).argmax()])
        else:
            p = clf.predict(X[te])
            y_p.append(p[0])
        y_t.append(y[te][0])
    t1 = time.perf_counter()
    acc = accuracy_score(y_t, y_p)
    print(f"{name:20s}: Accuracy = {acc*100:6.2f}%, Execution Time = {t1-t0:6.4f}s")
