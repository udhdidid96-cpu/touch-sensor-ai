"""docs/PHYSICS_TO_FEATURE_MAP.md must quote Data/physics_feature_stats.json.

Same rule as tests/test_doc_metrics_sync.py, same reason: this repository has
twice shipped a document whose headline figure no longer matched the code that
produced it. The physics-to-feature page is full of typed numbers, so it needs
the same guard - regenerate the JSON with

    python scripts/physics_feature_stats.py

and every cell below has to still be findable in the page.

This test reads two files and compares strings. It does not load the corpus, so
it costs milliseconds; the JSON is what carries the measurement.
"""
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(REPO_ROOT, "docs", "PHYSICS_TO_FEATURE_MAP.md")
STATS = os.path.join(REPO_ROOT, "Data", "physics_feature_stats.json")

# feature -> (median decimals, quartile decimals) as the page prints them.
# Std Delta keeps one decimal in its quartiles because the baseline row is the
# board's noise floor - 8.6 [7.7, 9.9] counts - and rounding that to [8, 10]
# throws away the resolution the 60-count noise gate is argued from.
FORMATS = {
    "Min Delta": (1, 0), "Max Delta": (1, 0), "Mean Delta": (1, 0), "Std Delta": (1, 1),
    "Drop Count (<= -300)": (0, 0), "Drop Count (<= -600)": (0, 0),
    "Drop Count (<= -1000)": (0, 0),
    "Spike Count (>= +300)": (0, 0), "Spike Count (>= +1000)": (0, 0),
}


def _load():
    if not os.path.isfile(STATS):
        pytest.skip(f"{STATS} not generated; run scripts/physics_feature_stats.py")
    with open(STATS, encoding="utf-8") as fh:
        stats = json.load(fh)
    with open(DOC, encoding="utf-8") as fh:
        return stats, fh.read()


def test_every_measured_cell_appears_in_the_page():
    stats, doc = _load()
    missing = []
    for scenario, r in stats["scenarios"].items():
        if not r["frames"]:
            continue
        # the row header itself
        if f"| {scenario} |" not in doc:
            missing.append(f"{scenario}: row missing entirely")
            continue
        if f"| {r['files']} | {r['frames']} |" not in doc:
            missing.append(f"{scenario}: files/frames {r['files']}/{r['frames']} not quoted")
        for name, (md, qd) in FORMATS.items():
            v = r["stats"][name]
            cell = f"{v['median']:.{md}f} [{v['q25']:.{qd}f}, {v['q75']:.{qd}f}]"
            if cell not in doc:
                missing.append(f"{scenario} / {name}: expected '{cell}'")
    assert not missing, (
        "docs/PHYSICS_TO_FEATURE_MAP.md no longer quotes Data/physics_feature_stats.json.\n"
        "Regenerate with:  python scripts/physics_feature_stats.py\n\n  "
        + "\n  ".join(missing))


def test_the_page_states_its_single_session_limit():
    """The corpus is one mounting. A physics page that reads like a datasheet
    without saying so is the overclaim AGENTS.md keeps warning about."""
    _, doc = _load()
    assert "Single session (S0)" in doc
    assert "not of a population of patches" in doc


def test_the_page_does_not_claim_the_gradient_features_are_in_use():
    """use_gradient defaults to False in the shipped configuration, so no
    published figure measures Grad Magnitude or Grad Anisotropy. 25 + 9 = 34."""
    _, doc = _load()
    assert "use_gradient=False" in doc
    assert "25 + 9 = 34" in doc
