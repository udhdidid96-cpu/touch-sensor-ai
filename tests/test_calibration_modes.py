"""calibrate(): the kalman_norm mode does what it is for, and nothing more.

Added 2026-09-18. Feature F10 - divide each delta by the Kalman baseline it was
measured against, re-express at BASELINE_COUNTS - ran in LivePipeline only, so
every offline figure (Data/metrics.json, the robustness table) measured a
pipeline the device does not run. `kalman_norm` closes that gap.

The property worth pinning is scale invariance: a patch resting at a different
C0 must produce the same deltas. It is also worth pinning that the mode did NOT
quietly become the default, because metrics.json was measured under `kalman`.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as M  # noqa: E402


def _bench(n=120, seed=0):
    """A resting patch with a press dipping four pads, at the nominal C0."""
    rng = np.random.default_rng(seed)
    raw = M.BASELINE_COUNTS + rng.normal(0, 15, size=(n, M.N_PADS))
    raw[60:90, 4:8] -= 900.0
    return raw


def test_kalman_norm_is_invariant_to_a_global_gain_change():
    """The point of F10. A +20% C0 must not move the deltas."""
    raw = _bench()
    base = M.calibrate(raw, "kalman_norm")
    gained = M.calibrate(raw * 1.20, "kalman_norm")
    assert np.abs(base - gained).max() < 1.0, (
        f"kalman_norm drifted {np.abs(base - gained).max():.1f} counts under a +20% gain")

    # and the unnormalised mode does not have that property - if this ever
    # passes, F10 has stopped doing anything and the test above is vacuous.
    plain = M.calibrate(raw, "kalman")
    plain_gained = M.calibrate(raw * 1.20, "kalman")
    assert np.abs(plain - plain_gained).max() > 50.0, (
        "the kalman mode became gain-invariant on its own; F10 is now untested")


def test_kalman_norm_stays_well_inside_the_noise_gate_on_bench_data():
    """Bench C0 is near BASELINE_COUNTS, so normalisation is close to a no-op.

    It is NOT bit-exact: the corpus rests near 27,820 counts, not 28,000, which
    is a ~0.6% rescale. What matters is that the difference stays far below the
    60-count noise gate, so no downstream decision changes.
    """
    raw = _bench()
    diff = np.abs(M.calibrate(raw, "kalman") - M.calibrate(raw, "kalman_norm")).max()
    assert diff < 60.0, f"normalisation moved a delta by {diff:.1f} counts, past the noise gate"


def test_unknown_modes_still_fall_back_to_static():
    """The API whitelist rejects anything outside static/kalman; calibrate() is
    the second line of that defence and must not start serving a new mode by
    accident."""
    raw = _bench(n=30)
    assert np.allclose(M.calibrate(raw, "kalman_norm_typo"), M.calibrate(raw, "static"))
    assert np.allclose(M.calibrate(raw, ""), M.calibrate(raw, "static"))


def test_metrics_were_measured_under_the_unnormalised_mode():
    """Data/metrics.json is a `kalman` measurement. Switching the default to
    kalman_norm without re-running --verify-metrics would leave every published
    figure describing a pipeline nothing runs - the exact defect F10 created."""
    import inspect
    sig = inspect.signature(M.calibrate)
    assert sig.parameters["mode"].default == "static"
