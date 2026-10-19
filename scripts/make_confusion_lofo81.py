"""Redraw the LOFO confusion figure from Data/metrics.json (random_forest block).

Same look as docs/figures/fig_confusion.png, but the counts are the ones the
current metrics.json holds (one seed, 81 file predictions) so the panel agrees
with the "79 of 81" headline on slide 8.
Usage: python make_confusion_lofo81.py metrics.json out.png
"""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

m = json.load(open(sys.argv[1]))["random_forest"]
cm = np.array(m["confusion_matrix"], dtype=float)
labels = ["Baseline", "Touch", "Peel", "Pull"]
n = int(cm.sum())

tp = np.diag(cm)
prec = tp / cm.sum(axis=0)
rec = tp / cm.sum(axis=1)
f1 = 2 * prec * rec / (prec + rec)
# cross-check against the stored per-class F1
stored = list(m["per_class_f1"].values())
assert np.allclose(f1, stored, atol=1e-6), (f1, stored)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "xtick.direction": "in", "ytick.direction": "in"})
fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.3), dpi=200,
                           gridspec_kw={"width_ratios": [1.05, 1]})

norm = cm / cm.sum(axis=1, keepdims=True)
im = a.imshow(norm, cmap="Blues", vmin=0, vmax=1)
for i in range(4):
    for j in range(4):
        a.text(j, i, f"{int(cm[i, j])}", ha="center", va="center", fontsize=11,
               color="white" if norm[i, j] > 0.5 else "black")
a.set_xticks(range(4), labels)
a.set_yticks(range(4), labels)
a.set_xlabel("Predicted class")
a.set_ylabel("True class")
a.set_title(f"Confusion matrix ({n} file predictions)", fontsize=10)
cb = fig.colorbar(im, ax=a, fraction=0.046, pad=0.03)
cb.set_label("Row-normalised")
a.text(-0.32, 1.06, "(a)", transform=a.transAxes, fontweight="bold")

x = np.arange(4)
w = 0.26
b.bar(x - w, prec, w, label="Precision", color="#1f77b4", edgecolor="black", linewidth=0.6)
b.bar(x, rec, w, label="Recall", color="#ff7f0e", edgecolor="black", linewidth=0.6)
b.bar(x + w, f1, w, label="F1-score", color="#2ca02c", edgecolor="black", linewidth=0.6)
b.set_xticks(x, labels)
b.set_ylim(0, 1.3)
b.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
b.set_xlabel("Class")
b.set_ylabel("Score")
b.set_title("Per-class performance", fontsize=10)
b.legend(loc="upper center", ncol=3, fontsize=7, frameon=True, edgecolor="0.6", handlelength=1.4, columnspacing=1.0, borderaxespad=0.6)
for xi in x:
    b.axvline(xi, color="0.85", lw=0.6, ls="--", zorder=0)
b.text(-0.14, 1.06, "(b)", transform=b.transAxes, fontweight="bold")

fig.tight_layout()
fig.savefig(sys.argv[2], dpi=200, facecolor="white")
print("n =", n, "P", prec.round(3), "R", rec.round(3), "F1", f1.round(3))
