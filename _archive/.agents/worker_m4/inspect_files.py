import os
import sys
from joblib import Parallel, delayed
from sklearn.base import clone

sys.path.insert(0, r"C:\Users\denpo\OneDrive\Desktop\Project2")

from main import load_dataset_matrix
from sklearn.metrics import accuracy_score
from sklearn.model_selection import LeaveOneGroupOut
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier

X, y, groups, n = load_dataset_matrix()

# Find mapping from group index to folder and filename
folder_files = []
for folder in ["N_base", "Brief Touch", "Press", "Friction", "Normal Mix", "Peel", "Vertical Pull NO G", "Horizontal Pull NO G", "PowerP"]:
    fdir = os.path.join(r"C:\Users\denpo\OneDrive\Desktop\Project2\Data", folder)
    if os.path.exists(fdir):
        import glob
        for f in glob.glob(os.path.join(fdir, "*.csv")):
            folder_files.append((folder, os.path.basename(f)))

fpath_1by1 = r"C:\Users\denpo\OneDrive\Desktop\Project2\Data\1 by 1.csv"
if os.path.exists(fpath_1by1):
    folder_files.append(("1by1_root", "1 by 1.csv"))

print(f"Total file metadata mapped: {len(folder_files)}")

logo = LeaveOneGroupOut()
splits = list(logo.split(X, y, groups=groups))

clf_base = ExtraTreesClassifier(n_estimators=100, random_state=42)

def eval_fold(tr, te, g):
    clf = clone(clf_base)
    clf.fit(X[tr], y[tr])
    probs = clf.predict_proba(X[te])
    pred_lbl = clf.classes_[probs.mean(axis=0).argmax()]
    true_lbl = y[te][0]
    return g, true_lbl, pred_lbl

results = Parallel(n_jobs=-1)(delayed(eval_fold)(tr, te, te_g[0]) for (tr, te), te_g in zip(splits, [groups[te] for _, te in splits]))

misclassified = []
for g, t_lbl, p_lbl in results:
    if t_lbl != p_lbl:
        folder, fname = folder_files[g]
        misclassified.append((g, folder, fname, t_lbl, p_lbl))

print(f"\nMisclassified Files Count: {len(misclassified)} / {len(results)}")
for g, folder, fname, t_lbl, p_lbl in misclassified:
    print(f"Group {g:2d} | Folder: {folder:20s} | File: {fname:30s} | True: {t_lbl} | Pred: {p_lbl}")
