"""Shared fixtures for the API tests.

The suite that used to live here was written against v5.0 and imported a
`get_app` symbol that v6.0 removed, so BOTH files failed at collection - which
means `pytest tests/` reported errors and ran zero assertions while the module
header claimed "14 defects, all with tests". Training a model per test module
was also the reason the old suite was slow enough to be skipped; the session
fixture below trains once for the whole run.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402


@pytest.fixture(scope="session")
def dataset():
    ds = M.load_dataset("kalman", verbose=False)
    if ds is None:
        pytest.skip(f"no recordings under {M.DATA_ROOT}")
    return ds


@pytest.fixture(scope="session")
def app(dataset):
    model = M._new_rf(42).fit(dataset.X, dataset.y)
    return M.create_app({"model": model, "use_gradient": False,
                         "calibration": "kalman"})


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_csv(client):
    """A recording that exists, URL-encoded the way the dashboard encodes it."""
    names = client.get("/api/v5/datasets").json()["datasets"]
    assert names, "no CSVs under Data/ - the API tests need at least one"
    return names[0]
