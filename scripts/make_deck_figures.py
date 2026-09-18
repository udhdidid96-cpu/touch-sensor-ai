"""Generate every figure in the deck from Project2's own data and its own model.

Pipeline stages are copied verbatim from main.py (KalmanBaseline, extract_features,
classify_deltas' noise gate, AlarmDebouncer) so the plots show what the shipped
code does, not an approximation of it.
"""
import json, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
D = os.environ.get("P2_DATA", os.path.join(_ROOT, "Data"))
OUT = os.environ.get("P2_FIGS", os.path.join(_ROOT, "docs", "figures"))
os.makedirs(OUT, exist_ok=True)

# ---- deck palette -----------------------------------------------------------
NAVY, SLATE, STEEL, LIGHT = "#0F172A", "#1E3A4C", "#2F5B6D", "#4C8299"
CYAN, DANGER, WARN, SAFE = "#0EA5E9", "#EF4444", "#F59E0B", "#10B981"
INK, INK2, INK3, PANEL = "#0F172A", "#334155", "#64748B", "#F1F5F9"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": "#CBD5E1", "axes.labelcolor": INK2, "axes.titlesize": 10,
    "axes.titleweight": "bold", "axes.titlecolor": INK,
    "xtick.color": INK3, "ytick.color": INK3, "text.color": INK2,
    "axes.grid": True, "grid.color": "#E2E8F0", "grid.linewidth": .7,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})
DIV = LinearSegmentedColormap.from_list("d", ["#1D4ED8", "#60A5FA", "#F1F5F9", "#FB923C", "#B91C1C"])

# ---- constants and stages, verbatim from main.py ----------------------------
N_PADS, N_CLASSES = 25, 4
BASELINE_COUNTS = 28000.0
NOISE_GATE_COUNTS, LIFT_GATE_COUNTS = 60.0, -300.0
KALMAN_WARMUP = 5
FRAME_S = 0.56                       # 9 frames = 5.04 s per METRICS.md
PHYSICAL_PAD_COORDS = {
    1:(57.,90.), 2:(73.,78.), 3:(58.,78.), 4:(79.,64.), 5:(65.,64.),
    6:(80.,50.), 7:(65.,50.), 8:(80.,36.), 9:(65.,36.), 10:(74.,24.),
    11:(58.,22.), 12:(50.,64.), 13:(50.,50.), 14:(50.,35.), 15:(41.,90.),
    16:(40.,78.), 17:(26.,78.), 18:(35.,64.), 19:(21.,64.), 20:(35.,50.),
    21:(20.,50.), 22:(35.,36.), 23:(20.,36.), 24:(40.,22.), 25:(25.,24.),
}
PAD_XY = np.array([PHYSICAL_PAD_COORDS[i] for i in range(1, N_PADS + 1)], float)


class KalmanBaseline:
    """Per-channel scalar Kalman baseline tracker - copied from main.py."""
    def __init__(self, q=0.05, r=40.0, gate=120.0, warmup=KALMAN_WARMUP):
        self.q, self.r, self.gate, self.warmup = q, r, gate, warmup
        self.b = self.p = self.r_vec = self.gate_vec = None

    def seed(self, frames):
        arr = np.asarray(frames, float); n = min(self.warmup, len(arr))
        self.b = arr[:n].mean(axis=0).astype(float)
        if n >= 2:
            self.r_vec = np.clip(np.std(arr[:n], axis=0) ** 2, 20.0, 150.0).astype(float)
        else:
            self.r_vec = np.full(arr.shape[1], self.r, float)
        self.gate_vec = np.full(arr.shape[1], self.gate, float)
        self.p = np.copy(self.r_vec)
        return self

    def step(self, z):
        z = np.asarray(z, float)
        p_pred = self.p + self.q
        innovation = z - self.b
        quiescent = np.abs(innovation) < self.gate_vec
        k = np.where(quiescent, p_pred / (p_pred + self.r_vec), 0.0)
        self.b = self.b + k * innovation
        self.p = (1.0 - k) * p_pred
        return z - self.b

    def run_with_baseline(self, raw):
        arr = np.asarray(raw, float); self.seed(arr)
        d, bs = [], []
        for row in arr:
            d.append(self.step(row)); bs.append(self.b.copy())
        return np.vstack(d), np.vstack(bs)


def static_baseline_delta(raw, k=5):
    arr = np.asarray(raw, float); k = min(k, len(arr))
    return (arr + (BASELINE_COUNTS - arr[:k].mean(axis=0))) - BASELINE_COUNTS


def extract_features(pad_delta):
    """use_gradient=False, include_pads=True -> 25 pads + 9 statistics = 34."""
    d = np.atleast_2d(np.asarray(pad_delta, float))
    stats = np.column_stack([
        d.min(axis=1), d.max(axis=1), d.mean(axis=1), d.std(axis=1),
        (d <= -300.).sum(axis=1).astype(float),
        (d <= -600.).sum(axis=1).astype(float),
        (d <= -1000.).sum(axis=1).astype(float),
        (d >= 300.).sum(axis=1).astype(float),
        (d >= 1000.).sum(axis=1).astype(float)])
    return np.hstack([d, stats])


class AlarmDebouncer:
    """6-of-7 with hold 9 - copied from main.py."""
    def __init__(self, window=7, min_votes=6, hold=9):
        self.window, self.min_votes, self.hold = window, min_votes, hold
        self.level, self._history, self._held, self._held_level = 0, [], 0, 0

    def _supported(self):
        for c in range(N_CLASSES - 1, 1, -1):
            if sum(1 for h in self._history if h >= c) >= self.min_votes:
                return c
        return 0

    def update(self, raw_level):
        self._history.append(int(raw_level))
        if len(self._history) > self.window:
            self._history.pop(0)
        sup = self._supported()
        if sup >= 2:
            self._held_level, self._held, self.level = sup, self.hold, sup
        elif self._held > 0:
            self._held -= 1; self.level = self._held_level
        else:
            self._held_level = 0; self.level = min(int(raw_level), 1)
        return self.level


def read_csv(rel):
    import csv
    with open(os.path.join(D, rel), newline="") as fh:
        rd = csv.reader(fh); hdr = next(rd)
        idx = [hdr.index("Sensor-%d" % (i + 1)) for i in range(N_PADS)]
        return np.array([[float(r[j]) for j in idx] for r in rd if r], float)


# ---- load the shipped model -------------------------------------------------
MODEL = None
try:
    import joblib
    obj = joblib.load(os.path.join(D, "trained_model.joblib"))
    MODEL = obj.get("model") if isinstance(obj, dict) else obj
    if not hasattr(MODEL, "predict_proba"):
        for v in (obj.values() if isinstance(obj, dict) else []):
            if hasattr(v, "predict_proba"):
                MODEL = v; break
    print("model:", type(MODEL).__name__, "n_features:", getattr(MODEL, "n_features_in_", "?"))
except Exception as e:
    print("MODEL LOAD FAILED:", e)


def classify(delta):
    """classify_deltas() - noise gate then model, nothing hand-coded."""
    d = np.atleast_2d(delta)
    proba = np.zeros((len(d), N_CLASSES)); proba[:, 0] = 1.0
    active = np.max(np.abs(d), axis=1) >= NOISE_GATE_COUNTS
    if MODEL is not None and active.any():
        p = MODEL.predict_proba(extract_features(d[active]))
        cls = list(getattr(MODEL, "classes_", range(N_CLASSES)))
        full = np.zeros((p.shape[0], N_CLASSES))
        for j, c in enumerate(cls):
            full[:, int(c)] = p[:, j]
        proba[active] = full
    return proba, proba.argmax(axis=1).astype(int), active


FILES = {"peel": "Peel/A_Peel_05.csv", "base": "N_base/N_Base_01.csv",
         "hpull": "Horizontal Pull NO G/A_HPull_02.csv", "vpull": "Vertical Pull NO G/A_VPull_03.csv"}
RAW = {k: read_csv(v) for k, v in FILES.items()}
for k, v in RAW.items():
    print(k, v.shape, "min %.0f max %.0f" % (v.min(), v.max()))


# ============================================================= PAPER FIGURE STYLE
# Conventional scientific plotting, matching the figure style of this group's
# published work: framed axes with ticks and units, boxed legends, (a)(b)(c)
# panel labels, standard colour cycle, standard colorbar. Nothing decorative.
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5,
    "axes.titlesize": 9.5, "axes.titleweight": "normal", "axes.titlecolor": "black",
    "axes.labelsize": 9, "axes.labelcolor": "black",
    "xtick.labelsize": 8, "ytick.labelsize": 8,
    "xtick.color": "black", "ytick.color": "black", "text.color": "black",
    "xtick.direction": "in", "ytick.direction": "in",
    "legend.fontsize": 7.5, "legend.frameon": True, "legend.framealpha": .92,
    "legend.edgecolor": "0.6", "legend.borderpad": .4, "legend.handlelength": 1.8,
    "axes.grid": True, "grid.color": "0.85", "grid.linestyle": "--", "grid.linewidth": .6,
    "axes.spines.top": True, "axes.spines.right": True,
    "axes.edgecolor": "black", "axes.linewidth": .9,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})
C_BLUE, C_ORANGE, C_GREEN, C_RED, C_GREY = "tab:blue", "tab:orange", "tab:green", "tab:red", "0.72"
CMAP = "RdBu_r"


def panel(ax, letter, dx=-0.16, dy=1.04):
    ax.text(dx, dy, "(%s)" % letter, transform=ax.transAxes,
            fontsize=9.5, fontweight="bold", va="bottom", ha="left")


# 25 visually separable channel colours, held in channel order across every figure
CH = plt.cm.turbo(np.linspace(0.04, 0.96, N_PADS))


# ================================================================= FIG 1 - raw 25
def fig_raw25():
    raw = RAW["peel"]; t = np.arange(len(raw)) * FRAME_S
    fig, ax = plt.subplots(figsize=(5.9, 2.9), dpi=200)
    for i in range(N_PADS):
        ax.plot(t, raw[:, i], lw=.9, color=CH[i], label="Sensor-%d" % (i + 1))
    ax.set_xlabel("Time (s)"); ax.set_ylabel("Raw counts")
    ax.set_xlim(t[0], t[-1]); ax.set_title("25 capacitive channels, one peel recording")
    ax.legend(loc="center left", bbox_to_anchor=(1.005, .5), ncol=2, fontsize=5.4,
              handlelength=1.0, handletextpad=.4, labelspacing=.24, columnspacing=.7,
              borderpad=.35)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_raw25.png"); plt.close(fig)


# =========================================================== FIG 2 - Kalman in/out
def _all_channels_proxy(n=5):
    """Striped swatch standing for the 25 faint per-channel traces."""
    from matplotlib.lines import Line2D
    idx = np.linspace(0, N_PADS - 1, n).astype(int)
    return tuple(Line2D([], [], color=CH[i], lw=1.4, alpha=.9) for i in idx)


ALL_CH_LABEL = "All 25 channels (Sensor 1–25)"
# the one trace drawn in black: pinned to Sensor-25 in both columns
HIGHLIGHT_PAD = 24                       # 0-based index -> Sensor-25


def fig_kalman():
    from matplotlib.legend_handler import HandlerTuple
    tuple_handler = {tuple: HandlerTuple(ndivide=5, pad=0.0)}

    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.6), dpi=200)
    letters = [["a", "b"], ["c", "d"]]
    for col, (key, head) in enumerate([("base", "Baseline recording"), ("peel", "Peel recording")]):
        raw = RAW[key]
        delta, bl = KalmanBaseline().run_with_baseline(raw)
        t = np.arange(len(raw)) * FRAME_S
        k = HIGHLIGHT_PAD
        name = "Sensor-%d (highlighted pad)" % (k + 1)

        a = axes[0, col]
        for i in range(N_PADS):
            a.plot(t, raw[:, i], lw=.7, color=CH[i], alpha=.85)
        h_hi, = a.plot(t, raw[:, k], lw=1.5, color="black")
        h_bl, = a.plot(t, bl[:, k], lw=1.5, color="black", ls="--")
        a.set_ylabel("Raw counts"); a.set_xlim(t[0], t[-1])
        a.set_title("%s — before" % head)
        a.legend([_all_channels_proxy(), h_hi, h_bl],
                 [ALL_CH_LABEL, name, "Estimated baseline (Sensor-%d)" % (k + 1)],
                 handler_map=tuple_handler, loc="best", ncol=1, fontsize=6.5,
                 handlelength=1.6, handletextpad=.5, labelspacing=.3, borderpad=.35)
        panel(a, letters[0][col])

        b = axes[1, col]
        for i in range(N_PADS):
            b.plot(t, delta[:, i], lw=.7, color=CH[i], alpha=.85)
        h_hi, = b.plot(t, delta[:, k], lw=1.5, color="black")
        h_ng = b.axhline(NOISE_GATE_COUNTS, color="black", lw=1.0, ls=":")
        b.axhline(-NOISE_GATE_COUNTS, color="black", lw=1.0, ls=":")
        h_lg = b.axhline(LIFT_GATE_COUNTS, color=C_RED, lw=1.3, ls="-.")
        b.set_xlabel("Time (s)"); b.set_ylabel("Δ from baseline (counts)")
        b.set_xlim(t[0], t[-1])
        b.set_ylim(min(delta.min(), -430) * 1.15, max(delta.max() * 1.3, 340))
        b.set_title("%s — after" % head)
        b.legend([_all_channels_proxy(), h_hi, h_ng, h_lg],
                 [ALL_CH_LABEL, name, "Noise gate ±60", "Lift gate −300"],
                 handler_map=tuple_handler,
                 loc="upper right" if col else "lower center", ncol=2, fontsize=6.3,
                 handlelength=1.6, handletextpad=.5, labelspacing=.3,
                 columnspacing=.9, borderpad=.35)
        panel(b, letters[1][col])
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_kalman.png"); plt.close(fig)


# ======================================================== FIG 3 - classifier in/out
def fig_model_io():
    raw = RAW["peel"]
    delta, _ = KalmanBaseline().run_with_baseline(raw)
    proba, raw_lvl, active = classify(delta)
    deb = AlarmDebouncer(); ann = np.array([deb.update(l) for l in raw_lvl])
    t = np.arange(len(raw)) * FRAME_S

    fig, axes = plt.subplots(3, 1, figsize=(5.2, 5.4), dpi=200, sharex=True)
    a, b, c = axes
    v = np.abs(delta).max()
    im = a.imshow(delta.T, aspect="auto", cmap=CMAP, vmin=-v, vmax=v,
                  extent=[t[0], t[-1] + FRAME_S, N_PADS + .5, .5], interpolation="nearest")
    a.set_yticks([1, 5, 10, 15, 20, 25]); a.set_ylabel("Channel")
    a.set_title("Input: per-channel Δ"); a.grid(False)
    cb = fig.colorbar(im, ax=a, pad=.02, fraction=.040)
    cb.set_label("Δ (counts)", fontsize=9); cb.ax.tick_params(labelsize=8)
    panel(a, "a")

    for ci, (nm, col) in enumerate([("Baseline", C_GREEN), ("Touch/press", C_ORANGE),
                                    ("Peel", C_BLUE), ("Pull", C_RED)]):
        b.plot(t, proba[:, ci], lw=1.6, color=col, label=nm)
    b.set_ylim(-.05, 1.35); b.set_yticks([0, .5, 1.0]); b.set_ylabel("Class probability")
    b.set_title("Output: posterior probabilities")
    b.legend(loc="upper center", ncol=4, columnspacing=.9, handlelength=1.2)
    panel(b, "b")

    c.step(t, raw_lvl, where="post", lw=1.4, color="0.45", ls="--", label="Frame-level prediction")
    c.step(t, ann, where="post", lw=1.9, color=C_RED, label="Annunciated (6-of-7, hold 9)")
    c.set_yticks([0, 1, 2, 3]); c.set_ylim(-.3, 4.0)
    c.set_ylabel("Severity level"); c.set_xlabel("Time (s)")
    c.set_title("Decision: after temporal debouncing")
    c.legend(loc="upper center", ncol=1)
    c.set_xlim(t[0], t[-1]); panel(c, "c")
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_model_io.png"); plt.close(fig)
    return proba, raw_lvl, ann


# ============================================================== FIG 4 - heatmaps
def fig_heatmaps():
    from scipy.interpolate import RBFInterpolator
    x0, x1, y0, y1 = 15.0, 85.0, 17.0, 95.0
    gx, gy = np.meshgrid(np.linspace(x0, x1, 150), np.linspace(y0, y1, 165))
    pts = np.column_stack([gx.ravel(), gy.ravel()])

    def field(d):
        f = RBFInterpolator(PAD_XY, d, kernel="thin_plate_spline", smoothing=1e-2)
        return f(pts).reshape(gx.shape)

    picks = []
    for key, title in [("peel", "Peel"), ("vpull", "Vertical pull"), ("hpull", "Horizontal pull")]:
        delta, _ = KalmanBaseline().run_with_baseline(RAW[key])
        i = int(np.argmin(delta.min(axis=1)))
        picks.append((title, delta[i], float(delta[i].min())))

    v = 900.0
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 3.1), dpi=200)
    for j, (ax, (title, d, dmin)) in enumerate(zip(axes, picks)):
        im = ax.imshow(field(d), origin="lower", extent=[x0, x1, y0, y1],
                       cmap=CMAP, vmin=-v, vmax=v, interpolation="bilinear", aspect="equal")
        ax.scatter(PAD_XY[:, 0], PAD_XY[:, 1], s=9, c="white", edgecolors="black",
                   linewidths=.6, zorder=3)
        ax.set_title("%s\nmin Δ = %.0f counts" % (title, dmin), fontsize=10)
        ax.set_xlabel("x (mm)")
        if j == 0:
            ax.set_ylabel("y (mm)")
        ax.set_xticks([20, 50, 80]); ax.set_yticks([20, 50, 80])
        ax.grid(False)
        panel(ax, "abc"[j], dx=-0.10, dy=1.24)
    cb = fig.colorbar(im, ax=axes, pad=.018, fraction=.030)
    cb.set_label("Δ from baseline (counts)", fontsize=9); cb.ax.tick_params(labelsize=8)
    fig.savefig(f"{OUT}/fig_heatmaps.png", bbox_inches="tight"); plt.close(fig)


# ================================================= FIG 5 - confusion + per-class
def fig_confusion():
    m = json.load(open(os.path.join(D, "metrics.json")))
    cm = np.array(m["random_forest"]["confusion_matrix"], float)
    labs = ["Baseline", "Touch", "Peel", "Pull"]
    f1 = m["random_forest"]["per_class_f1"]

    fig, (a, b) = plt.subplots(1, 2, figsize=(7.4, 3.3), dpi=200)
    row = cm / cm.sum(axis=1, keepdims=True)
    im = a.imshow(row, cmap="Blues", vmin=0, vmax=1)
    for i in range(4):
        for j in range(4):
            a.text(j, i, "%d" % cm[i, j], ha="center", va="center", fontsize=11,
                   color="white" if row[i, j] > .55 else "black")
    a.set_xticks(range(4), labs, fontsize=9); a.set_yticks(range(4), labs, fontsize=9)
    a.set_xlabel("Predicted class"); a.set_ylabel("True class")
    a.set_title("Confusion matrix (243 file predictions)"); a.grid(False)
    cb = fig.colorbar(im, ax=a, pad=.02, fraction=.046)
    cb.set_label("Row-normalised", fontsize=9); cb.ax.tick_params(labelsize=8)
    panel(a, "a", dx=-0.22)

    prec = np.diag(cm) / np.where(cm.sum(0) == 0, 1, cm.sum(0))
    rec = np.diag(cm) / np.where(cm.sum(1) == 0, 1, cm.sum(1))
    f1v = [f1["0: Baseline"], f1["1: Touch/Press"], f1["2: Peel"], f1["3: Pull"]]
    x = np.arange(4); w = .26
    for k, (vals, name, col) in enumerate([(prec, "Precision", C_BLUE),
                                           (rec, "Recall", C_ORANGE), (f1v, "F1-score", C_GREEN)]):
        b.bar(x + (k - 1) * w, vals, w, label=name, color=col, edgecolor="black", linewidth=.5)
    b.set_xticks(x, labs, fontsize=9); b.set_ylim(0, 1.28); b.set_yticks([0, .25, .5, .75, 1.0])
    b.set_ylabel("Score"); b.set_xlabel("Class")
    b.set_title("Per-class performance")
    b.legend(loc="upper center", ncol=3, columnspacing=.9, handlelength=1.3)
    b.grid(axis="y"); b.set_axisbelow(True)
    panel(b, "b", dx=-0.16)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_confusion.png"); plt.close(fig)


# ============================================== FIG 6 - cross-validation spread
def fig_training():
    raw = json.load(open(os.path.join(D, "model_comparison_100x.json")))
    order = ["Extra Trees", "Random Forest", "HistGradientBoosting"]
    ticks = ["ET", "RF", "HGB"]
    metrics = [("file_accuracy", "File accuracy"), ("macro_f1", "Macro F1"),
               ("recall_pull", "Pull recall"), ("sensitivity", "Episode sensitivity")]

    fig, axes = plt.subplots(1, 4, figsize=(8.6, 3.0), dpi=200)
    for j, (ax, (key, title)) in enumerate(zip(axes, metrics)):
        data = [[r[key] for r in raw[e]] for e in order]
        bp = ax.boxplot(data, widths=.55, patch_artist=True, showfliers=True,
                        flierprops=dict(marker="o", markersize=2, markerfacecolor="0.5",
                                        markeredgecolor="none"),
                        medianprops=dict(color="black", lw=1.3),
                        whiskerprops=dict(color="black", lw=.9),
                        capprops=dict(color="black", lw=.9),
                        boxprops=dict(edgecolor="black", linewidth=.8))
        for patch, col in zip(bp["boxes"], [C_BLUE, C_ORANGE, C_GREEN]):
            patch.set_facecolor(col); patch.set_alpha(.75)
        ax.set_xticks([1, 2, 3], ticks, fontsize=9)
        ax.set_ylabel(title, fontsize=9.5)
        lo = min(min(d) for d in data)
        ax.set_ylim(lo - .04, 1.04)
        ax.grid(axis="y"); ax.set_axisbelow(True)
        panel(ax, "abcd"[j], dx=-0.34, dy=1.03)
    fig.suptitle("Grouped 5-fold cross-validation, 100 repeats  (ET = Extra Trees, "
                 "RF = Random Forest, HGB = HistGradientBoosting, shipped)", fontsize=9, y=1.02)
    fig.tight_layout(); fig.savefig(f"{OUT}/fig_training.png", bbox_inches="tight"); plt.close(fig)


fig_raw25(); fig_kalman(); p, rl, an = fig_model_io(); fig_heatmaps(); fig_confusion(); fig_training()
print("figures rebuilt in paper style")
