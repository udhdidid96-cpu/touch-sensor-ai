"""ATTACHED_SEED_BAND must be what the corpus actually measured.

Supervisor item 2 (2026-09-17): with the current relative-capacitance board the
software zeroes on whatever the patch reads at power-on, so a patch that was
loose, absent or pressed at that moment gives a silently wrong baseline. Until
the absolute-CDC board exists, LivePipeline reports where its seed landed
against the band an attached patch rested in during round 1.

These tests pin the band to the data rather than to a typed number: the
per-file seed (mean of the first KALMAN_WARMUP frames of every recording) must
fall inside it, and the classifier must sort obviously-wrong seeds correctly.
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


PRESS_FOLDERS = {"Press", "N_Press"}


def _corpus_seed_means():
    """(folder, seed mean) for every usable recording."""
    out = []
    for folder in sorted(main.CLASS_MAPPING):
        for path in sorted(glob.glob(os.path.join(main.DATA_ROOT, folder, "*.csv"))):
            raw = main.read_raw_csv(path)
            if raw is None or len(raw) < main.MIN_FRAMES_PER_FILE:
                continue
            out.append((folder, float(np.mean(raw[: main.KALMAN_WARMUP]))))
    return out


def test_band_contains_every_recording_that_starts_at_rest():
    rows = _corpus_seed_means()
    assert len(rows) >= 60, f"expected the round-1 corpus, found {len(rows)} usable files"
    resting = [s for f, s in rows if f not in PRESS_FOLDERS]
    lo, hi = main.ATTACHED_SEED_BAND
    outside = [s for s in resting if not (lo <= s <= hi)]
    assert not outside, (f"{len(outside)} resting recording seed(s) fall outside "
                         f"ATTACHED_SEED_BAND {main.ATTACHED_SEED_BAND}: {outside[:5]}")
    # narrower than the F3 garbage bounds by a lot, or it means nothing
    assert (hi - lo) < 0.1 * (45000.0 - 10000.0)


def test_band_is_tight_around_the_resting_corpus_not_arbitrary():
    rows = _corpus_seed_means()
    resting = [s for f, s in rows if f not in PRESS_FOLDERS]
    lo, hi = main.ATTACHED_SEED_BAND
    # margins on each side no larger than a few noise gates
    assert 0.0 < min(resting) - lo < 6 * main.NOISE_GATE_COUNTS
    assert 0.0 < hi - max(resting) < 6 * main.NOISE_GATE_COUNTS


def test_recordings_started_mid_press_are_flagged():
    """The corpus already contains the failure this check is for.

    Ten of the eleven Press recordings were started while the operator was
    already pressing, so their Kalman seed sits 400-2,000 counts above rest.
    That is precisely "something was on the patch at power-on", and the check
    must say so on real data, not just on synthetic frames.
    """
    rows = _corpus_seed_means()
    press = [s for f, s in rows if f in PRESS_FOLDERS]
    assert len(press) >= 8
    flagged = [s for s in press if main.seed_plausibility(np.full(main.N_PADS, s))["status"] == "above_band"]
    assert len(flagged) >= 0.7 * len(press), (
        f"only {len(flagged)}/{len(press)} mid-press starts flagged above_band")


def test_classifier_sorts_seeds():
    lo, hi = main.ATTACHED_SEED_BAND
    mid = np.full(main.N_PADS, (lo + hi) / 2.0)
    assert main.seed_plausibility(mid)["status"] == "attached_band"
    assert main.seed_plausibility(mid - 3000.0)["status"] == "below_band"
    assert main.seed_plausibility(mid + 3000.0)["status"] == "above_band"
    assert main.seed_plausibility(np.full(main.N_PADS, np.nan))["status"] == "unknown"


def test_classifier_never_rejects_it_only_reports():
    """A different mounting may rest elsewhere; the check must not gate frames."""
    out = main.seed_plausibility(np.full(main.N_PADS, 20000.0))
    assert out["status"] == "below_band"
    assert "note" in out and out["seed_median"] == 20000.0


def test_live_pipeline_reports_where_it_seeded():
    pipe = main.LivePipeline(None)
    assert pipe.seed_plausibility["status"] == "unseeded"
    lo, hi = main.ATTACHED_SEED_BAND
    frame = np.full(main.N_PADS, (lo + hi) / 2.0)
    res = pipe.process(frame)
    assert res["seed_plausibility"]["status"] == "attached_band"
    low = main.LivePipeline(None)
    res2 = low.process(np.full(main.N_PADS, 24000.0))
    assert res2["seed_plausibility"]["status"] == "below_band"
