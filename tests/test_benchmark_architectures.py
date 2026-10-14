"""scripts/benchmark_architectures.py: the properties its comparison rests on.

The benchmark itself is not part of the suite (it fits hundreds of models). These
checks fail if the temporal block stops being causal or the invariant block starts
reading the absolute level, which is the whole point of the T+S representation.
"""
import numpy as np

import benchmark_architectures as B


def _walk(n: int = 30, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, 40, (n, 25)), axis=0)


def test_temporal_features_are_causal():
    d = _walk()
    changed = d.copy()
    changed[20:] += 900.0
    np.testing.assert_allclose(B.temporal_features(d)[:20], B.temporal_features(changed)[:20])
    np.testing.assert_allclose(B.invariant_features(d)[:20], B.invariant_features(changed)[:20])


def test_invariant_block_ignores_a_static_per_pad_offset():
    d = _walk(seed=1)
    offset = np.random.default_rng(2).normal(0, 500, 25)
    np.testing.assert_allclose(B.invariant_features(d), B.invariant_features(d + offset), atol=1e-6)
    assert not np.allclose(B.temporal_features(d), B.temporal_features(d + offset)), \
        "the full temporal block is expected to read the level (rolling minimum, lifted-pad count)"


def test_windows_are_left_padded_and_causal():
    d = _walk(8)
    w = B.windows(d)
    assert w.shape == (8, B.WINDOW, 25)
    np.testing.assert_allclose(w[0], np.repeat(d[:1], B.WINDOW, axis=0))
    np.testing.assert_allclose(w[-1][-1], d[-1])


def test_vote_breaks_ties_toward_the_alarm():
    assert B.vote(np.array([1, 1, 2, 2]), 3) == 2
