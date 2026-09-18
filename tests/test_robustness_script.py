"""scripts/evaluate_robustness.py: the perturbations do what they claim.

The full run takes ~20 minutes and is not part of the suite. These tests check
the parts that would silently invalidate a result: shape preservation, the
frame-drop floor, determinism per file, and that the read_raw_csv patch is
always removed even when evaluation fails.
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import main  # noqa: E402
import evaluate_robustness as er  # noqa: E402


def _raw(n=40, seed=0):
    rng = np.random.default_rng(seed)
    return 28000.0 + rng.normal(0, 20, size=(n, main.N_PADS))


def test_every_variant_preserves_pad_count():
    raw = _raw()
    for name, fn in er.VARIANTS.items():
        out = fn(raw, np.random.default_rng(1))
        assert out.shape[1] == main.N_PADS, name
        assert np.isfinite(out).all(), name


def test_gain_variants_scale_by_the_stated_factor():
    raw = _raw()
    assert np.allclose(er.VARIANTS["gain_global_p20"](raw, None), raw * 1.2)
    assert np.allclose(er.VARIANTS["gain_global_m10"](raw, None), raw * 0.9)


def test_frame_drop_keeps_first_frame_and_respects_floor():
    raw = _raw(n=100)
    out = er.VARIANTS["frame_drop_10"](raw, np.random.default_rng(3))
    assert np.array_equal(out[0], raw[0])
    assert 80 <= len(out) < 100
    tiny = _raw(n=main.MIN_FRAMES_PER_FILE)
    assert len(er.VARIANTS["frame_drop_10"](tiny, np.random.default_rng(3))) == len(tiny)


def test_spike_is_under_the_surge_filter():
    raw = _raw(n=2000)
    out = er.VARIANTS["spike_1pct"](raw, np.random.default_rng(5))
    diff = out - raw
    assert abs(diff.max() - 5000.0) < 1e-6
    assert out.max() < 50000.0, "a spike that the surge filter removes tests nothing"
    assert 5 <= int((diff > 0).sum()) <= 40


def test_rng_is_deterministic_per_file_and_variant():
    a = er._rng_for("Data/Peel/A_Peel_01.csv", "noise_sd60").normal()
    b = er._rng_for("Data/Peel/A_Peel_01.csv", "noise_sd60").normal()
    c = er._rng_for("Data/Peel/A_Peel_02.csv", "noise_sd60").normal()
    assert a == b and a != c


def test_read_raw_csv_is_restored_after_failure(monkeypatch):
    original = main.read_raw_csv
    monkeypatch.setattr(main, "load_dataset", lambda *a, **k: None)
    try:
        er.run_variant("identity", er.VARIANTS["identity"])
    except RuntimeError:
        pass
    assert main.read_raw_csv is original
