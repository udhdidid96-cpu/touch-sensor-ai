import os
import sys
from joblib import Parallel, delayed
from sklearn.base import clone

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier, VotingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

X, y, groups, n = load_dataset_matrix()

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

# Warmup parallel backend
_ = Parallel(n_jobs=-1)(delayed(lambda: 1)() for _ in range(10))

def eval_ensemble(clf_dict):
    def eval_fold(tr, te):
        preds = {}
        for name, clf_base in clf_dict.items():
            clf = clone(clf_base)
            clf.fit(X[tr], y[tr])
            probs = clf.predict_proba(X[te])
            classes = getattr(clf, "classes_", None)
            if classes is not None:
                preds[name] = probs.mean(axis=0)
        
        # Average probabilities across models in ensemble
        avg_probs = sum(preds.values()) / len(preds)
        pred_lbl = avg_probs.argmax()
        return y[te][0], pred_lbl

    import time
    t0 = time.perf_counter()
    results = Parallel(n_jobs=-1)(delayed(eval_fold)(tr, te) for tr, te in splits)
    t1 = time.perf_counter()
    
    y_t = [r[0] for r in results]
    y_p = [r[1] for r in results]
    acc = accuracy_score(y_t, y_p)
    return acc, t1 - t0

models_set = {
    "ET100": ExtraTreesClassifier(n_estimators=100, random_state=42),
    ("ET50_rs42"): ExtraTreesClassifier(n_estimators=50, random_state=42),
    ("ET50_rs123"): ExtraTreesClassifier(n_estimators=50, random_state=123),
    ("RF50_rs42"): RandomForestClassifier(n_estimators=50, random_state=42),
    ("HGBD"): HistGradientBoostingClassifier(learning_rate=0.1, max_iter=80, random_state=42),
}

for name, clf in models_set.items():
    acc, t = eval_ensemble({name: clf})
    print(f"Model {name:20s}: Acc = {acc*100:6.2f}% ({int(round(acc*81))}/81 files), Time = {t:6.4f}s")

# Test Voting Ensemble
acc, t = eval_ensemble(models_set)
print(f"Ensemble All           : Acc = {acc*100:6.2f}% ({int(round(acc*81))}/81 files), Time = {t:6.4f}s")
