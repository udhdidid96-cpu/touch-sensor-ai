import os
import sys
import time
from joblib import Parallel, delayed
from sklearn.base import clone

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier, AdaBoostClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

def eval_candidate(base_clf):
    def eval_fold(tr, te):
        clf = clone(base_clf)
        clf.fit(X[tr], y[tr])
        if hasattr(clf, "predict_proba"):
            probs = clf.predict_proba(X[te])
            classes = getattr(clf, "classes_", None)
            if classes is not None:
                pred_lbl = classes[probs.mean(axis=0).argmax()]
            else:
                pred_lbl = 0
        else:
            p = clf.predict(X[te])
            pred_lbl = p[0]
        return y[te][0], pred_lbl

    t0 = time.perf_counter()
    results = Parallel(n_jobs=-1)(delayed(eval_fold)(tr, te) for tr, te in splits)
    t1 = time.perf_counter()
    y_t = [r[0] for r in results]
    y_p = [r[1] for r in results]
    acc = accuracy_score(y_t, y_p)
    return acc, t1 - t0

candidates = [
    ("RF n=100 max_d=None", RandomForestClassifier(n_estimators=100, random_state=42)),
    ("RF n=50 max_d=10 min_samples_leaf=2", RandomForestClassifier(n_estimators=50, max_depth=10, min_samples_leaf=2, random_state=42)),
    ("ET n=100 max_d=None", ExtraTreesClassifier(n_estimators=100, random_state=42)),
    ("SVC rbf C=10", make_pipeline(StandardScaler(), SVC(C=10.0, probability=True, random_state=42))),
    ("SVC rbf C=100", make_pipeline(StandardScaler(), SVC(C=100.0, probability=True, random_state=42))),
    ("MLP (100, 50)", make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(100, 50), max_iter=200, random_state=42))),
    ("HGBD l2=1.0", HistGradientBoostingClassifier(l2_regularization=1.0, max_iter=80, random_state=42)),
    ("HGBD lr=0.2 max_iter=40", HistGradientBoostingClassifier(learning_rate=0.2, max_iter=40, random_state=42)),
]

for name, clf in candidates:
    acc, exec_time = eval_candidate(clf)
    print(f"{name:40s}: Accuracy = {acc*100:6.2f}%, Execution Time = {exec_time:6.4f}s")
