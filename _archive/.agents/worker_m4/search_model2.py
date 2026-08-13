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
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

X, y, groups, n = load_dataset_matrix()
print(f"Loaded matrix: {X.shape} across {n} files")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

def eval_model(clf_factory):
    t0 = time.perf_counter()
    def eval_fold(tr, te):
        clf = clf_factory()
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
        
        # Frame level preds
        p_frame = clf.predict(X[te])
        return y[te][0], pred_lbl, y[te], p_frame

    results = Parallel(n_jobs=-1)(
        delayed(eval_fold)(tr, te) for tr, te in splits
    )
    t1 = time.perf_counter()
    y_tf = [r[0] for r in results]
    y_pf = [r[1] for r in results]
    file_acc = accuracy_score(y_tf, y_pf)
    
    y_true_frames = [item for r in results for item in r[2]]
    y_pred_frames = [item for r in results for item in r[3]]
    frame_acc = accuracy_score(y_true_frames, y_pred_frames)
    
    return file_acc, frame_acc, t1 - t0

models = [
    ("Scaled KNN 5", lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=5, weights='distance'))),
    ("Scaled KNN 3", lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=3, weights='distance'))),
    ("Scaled KNN 1", lambda: make_pipeline(StandardScaler(), KNeighborsClassifier(n_neighbors=1))),
    ("ET 20 max_depth=15", lambda: ExtraTreesClassifier(n_estimators=20, max_depth=15, random_state=42)),
    ("RF 20 max_depth=15", lambda: RandomForestClassifier(n_estimators=20, max_depth=15, random_state=42)),
]

for name, factory in models:
    file_acc, frame_acc, exec_time = eval_model(factory)
    print(f"{name:25s}: FileAcc={file_acc*100:6.2f}%, FrameAcc={frame_acc*100:6.2f}%, Time={exec_time:6.4f}s")
