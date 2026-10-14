"""scripts/evaluate_vacuum_station.py: ingestion and feature facts its numbers rest on.

The LOFO run itself is not part of the suite (three passes, ~30 s). These checks
fail if the 25-channel ingestion, the 40-feature layout, the class counts, the
confidence-interval arithmetic or the file names the controls depend on drift.
"""
import os

import numpy as np
import pytest

import evaluate_vacuum_station as V

pytestmark = pytest.mark.skipif(not os.path.isdir(V.DATA_DIR), reason="Data/data new vaccum absent")


def test_items_have_25_clean_channels_and_expected_classes():
    items = V.load_dataset()
    assert len(items) == 25 and len(V.load_dataset(chunked=False)) == 24
    assert all(a.shape[1] == 25 and np.isfinite(a).all() for _, _, a in items)
    assert np.bincount([label for _, label, _ in items]).tolist() == [5, 7, 13]


def test_control_file_names_exist():
    names = {name for name, _, _ in V.load_dataset()}
    assert set(V.LAST_ATTACHMENT) <= names and set(V.ENDS_DETACHED) <= names


def test_40_features_and_what_the_spatial_ones_reduce_to():
    arr = V.read(os.path.join(V.DATA_DIR, "A_HPull", "A_HPull1.csv"))
    c0 = V.get_seated_baseline()
    X = V.extract_features(arr, c0)
    assert X.shape == (len(arr), 40)
    grid = (arr - c0).reshape(-1, 5, 5)
    np.testing.assert_allclose(X[:, 34], (grid[:, 4, :] - grid[:, 0, :]).mean(axis=1) / 4)
    np.testing.assert_allclose(X[:, 35], (grid[:, :, 4] - grid[:, :, 0]).mean(axis=1) / 4)
    np.testing.assert_allclose(X[:, 39], X[:, 26] ** 2)


def test_clopper_pearson():
    assert V.ci(13, 13) == "13/13 = 100.00% (95% CI 75.3-100.0%)"
    assert V.ci(23, 24) == "23/24 = 95.83% (95% CI 78.9-99.9%)"
