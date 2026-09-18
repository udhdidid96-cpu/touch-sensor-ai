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


# ---------------------------------------------------------------------------
# Per-channel seed contamination (2026-09-18)
# ---------------------------------------------------------------------------
# Six of the ten Brief Touch recordings were started with a finger already on
# one or two pads. Those channels seeded high and then read 470-810 counts BELOW
# a baseline that was never valid, for the whole recording, in files labelled
# normal. The band check above cannot see it: it is a median over 25 pads, and
# one or two elevated channels do not move a 25-channel median.


def _seed_frame(folder, name):
    raw = main.read_raw_csv(os.path.join(main.DATA_ROOT, folder, name))
    assert raw is not None and len(raw) >= main.KALMAN_WARMUP, f"{folder}/{name} unusable"
    return raw[: main.KALMAN_WARMUP].mean(axis=0)


def _resting_shape():
    """Re-derive SEED_RESTING_SHAPE from the corpus, as the band tests do."""
    seeds = []
    for path in sorted(glob.glob(os.path.join(main.DATA_ROOT, "N_base", "*.csv"))):
        raw = main.read_raw_csv(path)
        if raw is not None and len(raw) >= main.KALMAN_WARMUP:
            seeds.append(raw[: main.KALMAN_WARMUP].mean(axis=0))
    return np.median(np.array(seeds), axis=0) if seeds else None


def test_resting_shape_is_what_the_resting_recordings_measure():
    """The reference is corpus-derived, so it must not drift from the corpus."""
    shape = _resting_shape()
    if shape is None:
        import pytest
        pytest.skip("no N_base recordings under this DATA_ROOT")
    assert shape.shape == main.SEED_RESTING_SHAPE.shape
    drift = float(np.abs(shape - main.SEED_RESTING_SHAPE).max())
    assert drift < 1.0, (
        f"SEED_RESTING_SHAPE is {drift:.1f} counts from the N_base recordings it "
        f"claims to describe; re-derive it rather than editing it by hand")


def test_n_touch_02_is_flagged_as_a_channel_outlier():
    """The named case, on the real recording, not a synthetic frame.

    N_Touch_02 pad 2 seeds at 28,718 counts while its median for the rest of the
    file is 27,926 - so every later frame reads about -790 against a baseline
    taken while a finger was resting on that pad.
    """
    out = main.seed_plausibility(_seed_frame("Brief Touch", "N_Touch_02.csv"))
    assert out["status"] == "channel_outlier", out
    assert 2 in out["outlier_pads"], out["outlier_pads"]
    assert out["outlier_pads_high"], "pad 2 seeded HIGH; direction must be reported"
    # the band check alone would have called this file fine, which is the point
    assert out["band_status"] == "attached_band"


def test_n_touch_06_is_flagged_too():
    out = main.seed_plausibility(_seed_frame("Brief Touch", "N_Touch_06.csv"))
    assert out["status"] == "channel_outlier", out
    assert 1 in out["outlier_pads"], out["outlier_pads"]


def test_a_resting_patch_is_never_flagged():
    """The safety criterion behind the threshold. A check that fires on a clean
    baseline is worse than no check - and 400 counts, the first value tried,
    flagged all five of these."""
    for path in sorted(glob.glob(os.path.join(main.DATA_ROOT, "N_base", "*.csv"))):
        raw = main.read_raw_csv(path)
        if raw is None or len(raw) < main.KALMAN_WARMUP:
            continue
        out = main.seed_plausibility(raw[: main.KALMAN_WARMUP].mean(axis=0))
        assert out["status"] != "channel_outlier", (os.path.basename(path), out)


def test_peel_recordings_are_never_flagged():
    """Peel is the class that must not be cluttered with advisories."""
    for path in sorted(glob.glob(os.path.join(main.DATA_ROOT, "Peel", "*.csv"))):
        raw = main.read_raw_csv(path)
        if raw is None or len(raw) < main.KALMAN_WARMUP:
            continue
        out = main.seed_plausibility(raw[: main.KALMAN_WARMUP].mean(axis=0))
        assert out["status"] != "channel_outlier", (os.path.basename(path), out)


def test_every_status_carries_the_outlier_key():
    """Consumers read seed_plausibility()['outlier_pads'] unconditionally."""
    lo, hi = main.ATTACHED_SEED_BAND
    mid = np.full(main.N_PADS, (lo + hi) / 2.0)
    for frame in (mid, mid - 3000.0, mid + 3000.0, np.full(main.N_PADS, np.nan)):
        assert "outlier_pads" in main.seed_plausibility(frame)


# ---------------------------------------------------------------------------
# Quiescent negative-step recovery
# ---------------------------------------------------------------------------
def _contaminated_stream(n=40, bad_pad=1, offset=800.0, seed=0):
    """A patch at rest, with one pad held `offset` high for the seed frames only.

    That is the contamination: the finger is on pad `bad_pad` while the baseline
    is taken and gone immediately after, so the channel reads -offset from then
    on against a zero that was never valid.
    """
    rng = np.random.default_rng(seed)
    raw = main.BASELINE_COUNTS + rng.normal(0, 8.0, size=(n, main.N_PADS))
    raw[: main.KALMAN_WARMUP, bad_pad] += offset
    return raw


def test_quiescent_recovery_repairs_a_contaminated_channel():
    pipe = main.LivePipeline(None)
    raw = _contaminated_stream()
    deltas = [pipe.process(row)["deltas"][1] for row in raw]
    # right after the finger leaves, the channel reads deeply negative
    assert deltas[main.KALMAN_WARMUP + 1] < main.LIFT_GATE_COUNTS, deltas[:10]
    # and by the end of the record the baseline has walked back to the skin
    assert abs(deltas[-1]) < abs(deltas[main.KALMAN_WARMUP + 1]) / 4.0, (
        f"quiescent recovery did not converge: {deltas[main.KALMAN_WARMUP + 1]:.0f} "
        f"-> {deltas[-1]:.0f}")
    assert abs(deltas[-1]) < main.DELTA_THRESHOLD


def test_quiescent_recovery_reports_which_pads_it_touched():
    pipe = main.LivePipeline(None)
    engaged = []
    for row in _contaminated_stream():
        res = pipe.process(row)
        if res["quiescent_recovery"]["active_pads"]:
            engaged.append(tuple(res["quiescent_recovery"]["active_pads"]))
    assert engaged, "recovery never engaged on a contaminated channel"
    assert all(p == (2,) for p in engaged), engaged


def test_quiescent_recovery_never_touches_a_moving_channel():
    """A real pull keeps moving. Only stillness qualifies."""
    rng = np.random.default_rng(1)
    n = 40
    raw = main.BASELINE_COUNTS + rng.normal(0, 8.0, size=(n, main.N_PADS))
    # one pad driven steadily downward from frame 10: a slow, real lift
    raw[10:, 1] -= np.linspace(300.0, 1200.0, n - 10)
    pipe = main.LivePipeline(None)
    engaged = False
    for row in raw:
        if pipe.process(row)["quiescent_recovery"]["active_pads"]:
            engaged = True
    assert not engaged, "recovery engaged on a channel that was still moving"


def test_quiescent_recovery_never_engages_on_a_peel():
    """PEEL_MIN_PADS or more channels below the gate is a peel front, and a peel
    front that has come to rest is still a peel. Recovery must stay out."""
    rng = np.random.default_rng(2)
    n = 40
    raw = main.BASELINE_COUNTS + rng.normal(0, 8.0, size=(n, main.N_PADS))
    raw[main.KALMAN_WARMUP:, 0:6] -= 900.0      # six pads down together, then still
    pipe = main.LivePipeline(None)
    engaged = False
    for row in raw:
        if pipe.process(row)["quiescent_recovery"]["active_pads"]:
            engaged = True
    assert not engaged, "recovery engaged while six pads were below the lift gate"
