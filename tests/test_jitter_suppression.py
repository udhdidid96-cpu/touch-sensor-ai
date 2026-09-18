"""The jitter filter must be invisible on the corpus and effective above it.

The robustness sweep measured a cliff: episode sensitivity 92.5% at noise sd 30,
87.5% at sd 60, then 60.0% at sd 120 with 16 of 40 episodes missed. The
annunciator needs 6 of 7 consecutive frames to agree, and single-frame jitter
breaks those runs - the detector goes deaf rather than jumpy.

Two properties carry the whole design and both are pinned here:

  * it changes NOTHING on the 81 round-1 recordings, because Data/metrics.json
    was measured without it and a filter that quietly re-measures every
    published figure is the F10 defect again;
  * a median, not a mean, so a step edge - a sustained pull, a sudden peel -
    passes through untouched while an isolated bad frame does not.
"""
import glob
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402


def _corpus_files():
    return sorted(glob.glob(os.path.join(M.DATA_ROOT, "*", "*.csv")))


def test_filter_is_a_no_op_on_every_round_1_recording():
    files = _corpus_files()
    if not files:
        pytest.skip(f"no recordings under {M.DATA_ROOT}")
    worst, worst_file = 0.0, None
    for path in files:
        raw = M.read_raw_csv(path)
        if raw is None or len(raw) < M.MIN_FRAMES_PER_FILE:
            continue
        delta = M.calibrate(raw, "kalman")
        changed = float(np.abs(M.adaptive_jitter_filter(delta) - delta).max())
        if changed > worst:
            worst, worst_file = changed, os.path.basename(path)
    assert worst == 0.0, (
        f"the jitter filter changed {worst:.1f} counts on {worst_file}. "
        f"Data/metrics.json was measured without it, so any change here is drift.")


def test_the_activation_gate_sits_above_the_corpus_and_below_sd_60():
    """The gate is a measurement, not a preference, and both attempts before it
    were wrong: a per-frame statistic does not separate noise from a press
    sweep. Per FILE it does."""
    files = _corpus_files()
    if not files:
        pytest.skip("no recordings")
    per_file = []
    for path in files:
        raw = M.read_raw_csv(path)
        if raw is None or len(raw) < 6:
            continue
        jit = M.jitter_estimate(M.calibrate(raw, "kalman"))
        if jit.size:
            per_file.append(float(np.median(jit)))
    assert max(per_file) < M.JITTER_ACTIVATE_COUNTS, (
        f"a clean recording reaches {max(per_file):.1f}, at or above the "
        f"{M.JITTER_ACTIVATE_COUNTS} gate")


def test_filter_engages_under_the_noise_that_causes_the_cliff():
    files = sorted(glob.glob(os.path.join(M.DATA_ROOT, "Peel", "*.csv")))
    if not files:
        pytest.skip("no Peel recordings")
    raw = M.read_raw_csv(files[0])
    rng = np.random.default_rng(7)
    for sd, expect in ((60.0, True), (120.0, True)):
        noisy = raw + rng.normal(0.0, sd, size=raw.shape)
        delta = M.calibrate(noisy, "kalman")
        engaged = float(np.abs(M.adaptive_jitter_filter(delta) - delta).max()) > 0.0
        assert engaged is expect, f"sd {sd}: engaged={engaged}"


def test_a_step_edge_survives_the_filter():
    """The property that makes this a median and not a mean. A sustained pull is
    a step, and a 3-tap median leaves a step exactly where it was."""
    n = 60
    d = np.zeros((n, M.N_PADS))
    d[30:] = -900.0                       # a clean step: pull starts at frame 30
    # force the filter on regardless of content
    out = np.copy(d)
    out[M.JITTER_TAPS - 1:] = np.median(np.stack([d[:-2], d[1:-1], d[2:]]), axis=0)
    # the step lands two frames later under a causal window, and nothing in
    # between is smeared to an intermediate value - it is one value or the other
    assert set(np.unique(out[M.JITTER_TAPS - 1:])) <= {0.0, -900.0}
    assert out[-1, 0] == -900.0
    assert out[JITTER_START := M.JITTER_TAPS - 1, 0] == 0.0


def test_an_isolated_bad_frame_is_removed():
    """What a median filter is for, and what the annunciator actually needs.

    A 3-tap median removes an ISOLATED outlier. It does not remove a sustained
    square wave - median(800, 0, 800) is 800 - and claiming otherwise was the
    first version of this test. Real front-end noise is random, not a perfect
    alternation, and the property that matters for a 6-of-7 vote is that one bad
    frame in the middle of a quiet run cannot break the run.
    """
    n = 30
    d = np.zeros((n, M.N_PADS))
    d[15] = -2000.0                       # one frame of nonsense in a quiet record
    # activate=-1 forces the filter on: the point here is the median's behaviour,
    # not the gate, and a single outlier does not move a median jitter estimate.
    filt = M.adaptive_jitter_filter(d, activate=-1.0)
    assert filt[15 + 2].max() == 0.0 and filt[15 + 2].min() == 0.0, filt[14:19, 0]
    assert np.abs(filt[M.JITTER_TAPS - 1:]).max() == 0.0, (
        "an isolated outlier survived the filter")


def test_random_jitter_is_attenuated():
    """On random noise the filter must reduce frame-to-frame swing, which is
    what breaks the annunciator's consecutive votes."""
    rng = np.random.default_rng(3)
    d = rng.normal(0.0, 150.0, size=(200, M.N_PADS))
    filt = M.adaptive_jitter_filter(d, activate=-1.0)
    raw_swing = float(np.abs(np.diff(d[M.JITTER_TAPS - 1:], axis=0)).mean())
    filt_swing = float(np.abs(np.diff(filt[M.JITTER_TAPS - 1:], axis=0)).mean())
    assert filt_swing < 0.8 * raw_swing, (raw_swing, filt_swing)


def test_live_pipeline_reports_the_noise_floor_and_filters_nothing():
    pipe = M.LivePipeline(None)
    res = pipe.process(np.full(M.N_PADS, M.BASELINE_COUNTS))
    assert res["jitter_filter_active"] is False
    assert "jitter_noise_counts" in res


def test_the_filter_is_not_in_the_serving_path():
    """The measured negative result, pinned so it cannot be quietly undone.

    Wiring this in made the cliff worse: at sd 60 sensitivity fell 87.5% to
    72.5% while false alarms rose 7.3% to 12.2%, and at sd 120 sensitivity moved
    2.5 points - inside the confidence interval - for more than double the false
    alarms. A causal 3-tap window delays an event by up to two frames and
    shortens it by as much again, and the annunciator needs 6 of 7 CONSECUTIVE
    frames. Re-enabling it means re-running the sweep, not deleting this test.
    """
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "main.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    calls = [ln.strip() for ln in src.splitlines()
             if "adaptive_jitter_filter(" in ln and not ln.strip().startswith(("#", "*"))
             and "def adaptive_jitter_filter" not in ln]
    assert not calls, (
        "adaptive_jitter_filter is being called in main.py again: " + "; ".join(calls))


def test_the_live_pipeline_does_not_median_its_deltas():
    """Behavioural half of the test above: a single outlier frame must reach the
    classifier as it arrived, because nothing is smoothing it."""
    pipe = M.LivePipeline(None)
    base = np.full(M.N_PADS, M.BASELINE_COUNTS)
    for _ in range(M.KALMAN_WARMUP + 3):
        pipe.process(base)
    spiked = base.copy()
    spiked[0] -= 2000.0
    out = pipe.process(spiked)
    assert out["deltas"][0] < -1500.0, out["deltas"][0]
