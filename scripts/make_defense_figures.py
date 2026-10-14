"""Two defense-deck figures drawn from Data/metrics.json and the main.py constants.

fig_detach_scale.png   the detachment spec against what this patch can read
fig_offline_served.png offline replay vs served path at the shipped operating point

Usage: python make_defense_figures.py METRICS_JSON OUT_DIR
Style follows the group's paper figures: framed axes, ticks in, dashed grid, small type.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# main.py constants (BASELINE_COUNTS, COUNTS_PER_PF, NOMINAL_BASELINE_PF, SPEC_DETACH_MAX)
BASELINE_COUNTS = 28000.0
COUNTS_PER_PF = 59.85
NOMINAL_BASELINE_PF = 30.0
SPEC_DETACH_MAX = 25000.0

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"],
    "font.size": 8.5, "axes.titlesize": 9.5, "axes.labelsize": 9, "xtick.labelsize": 8,
    "ytick.labelsize": 8, "legend.fontsize": 7.5, "xtick.direction": "in", "ytick.direction": "in",
    "xtick.top": True, "ytick.right": True, "axes.grid": True, "grid.linestyle": "--",
    "grid.linewidth": 0.5, "grid.color": "0.82", "axes.linewidth": 0.8, "savefig.dpi": 300,
})


def panel(ax, letter):
    ax.text(-0.02, 1.04, f"({letter})", transform=ax.transAxes, fontsize=9.5,
            fontweight="bold", ha="right", va="bottom")


def detach_scale(m, out):
    floor = BASELINE_COUNTS - NOMINAL_BASELINE_PF * COUNTS_PER_PF
    deepest = min(m["dataset"]["min_raw_count_by_class"].values())
    rows = [
        ("Attached, at rest", BASELINE_COUNTS, "tab:blue"),
        ("Deepest measured (81 files)", deepest, "tab:green"),
        ("Patch gone, C = 0 (floor)", floor, "tab:orange"),
        ("KES 2025 spec, detached", SPEC_DETACH_MAX, "tab:red"),
    ]
    fig, ax = plt.subplots(figsize=(7.4, 3.3))
    y = list(range(len(rows)))[::-1]
    lo = 24000
    for yi, (lab, v, c) in zip(y, rows):
        ax.barh(yi, v - lo, left=lo, height=0.55, color=c, edgecolor="black", linewidth=0.6)
        ax.text(v + 40, yi, f"{v:,.1f}" if v % 1 else f"{v:,.0f}", va="center", fontsize=8)
    ax.axvline(floor, color="black", lw=0.9, ls=":")
    ax.annotate("", xy=(SPEC_DETACH_MAX, -0.62), xytext=(floor, -0.62),
                arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((floor + SPEC_DETACH_MAX) / 2, -0.55, f"shortfall {floor - SPEC_DETACH_MAX:,.1f} counts",
            ha="center", va="bottom", fontsize=7.5)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_ylim(-0.95, len(rows) - 0.45)
    ax.set_xlim(lo, 28900)
    ax.set_xlabel("Raw counts")
    ax.grid(axis="y", visible=False)
    ax.tick_params(top=False)
    top = ax.secondary_xaxis("top", functions=(lambda c: (BASELINE_COUNTS - c) / COUNTS_PER_PF,
                                               lambda p: BASELINE_COUNTS - p * COUNTS_PER_PF))
    top.set_xticks([0, 10, 20, 30, 40, 50, 60])
    top.set_xlabel("Capacitance lost from rest (pF)")
    top.tick_params(direction="in")
    fig.tight_layout()
    fig.savefig(out / "fig_detach_scale.png")
    plt.close(fig)


def offline_served(m, out):
    off, srv = m["episode_level"], m["served_episode_level"]
    labs = ["Offline\nreplay", "Served\npath"]
    cols = ["tab:blue", "tab:orange"]
    fig, axs = plt.subplots(1, 3, figsize=(6.4, 2.9))
    sens = [100 * off["sensitivity"], 100 * srv["sensitivity"]]
    ci = [off["sensitivity_ci"], srv["sensitivity_ci"]]
    err = [[s - 100 * c[0] for s, c in zip(sens, ci)], [100 * c[1] - s for s, c in zip(sens, ci)]]
    axs[0].bar(labs, sens, color=cols, edgecolor="black", lw=0.6, yerr=err, capsize=3,
               error_kw=dict(lw=0.8))
    axs[0].set_ylabel("Episode sensitivity (%)")
    axs[0].set_ylim(80, 104)
    vals = [[off["alarms_per_hour"], srv["alarms_per_hour"]],
            [off["median_latency_s"], srv["median_latency_s"]]]
    axs[1].bar(labs, vals[0], color=cols, edgecolor="black", lw=0.6)
    axs[1].set_ylabel("Alarms per hour, normal files (alarms/h)")
    axs[2].bar(labs, vals[1], color=cols, edgecolor="black", lw=0.6)
    axs[2].set_ylabel("Median time to alarm (s)")
    fmt = [lambda v: f"{v:.1f}", lambda v: f"{v:.2f}", lambda v: f"{v:.2f}"]
    for k, ax in enumerate(axs):
        panel(ax, "abc"[k])
        data = sens if k == 0 else vals[k - 1]
        for i, v in enumerate(data):
            off_y = 0.3 if k == 0 else max(data) * 0.02
            ax.text(i + 0.22 if k == 0 else i, v + off_y, fmt[k](v), ha="left" if k == 0 else "center",
                    va="bottom", fontsize=7.5)
        if k:
            ax.set_ylim(0, max(data) * 1.25)
        ax.tick_params(axis="x", labelsize=7.5, top=False)
        ax.grid(axis="x", visible=False)
    fig.tight_layout(w_pad=1.6)
    fig.savefig(out / "fig_offline_served.png")
    plt.close(fig)


if __name__ == "__main__":
    metrics = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    detach_scale(metrics, outdir)
    offline_served(metrics, outdir)
