"""Shared fixtures for the API tests.

The suite that used to live here was written against v5.0 and imported a
`get_app` symbol that v6.0 removed, so BOTH files failed at collection - which
means `pytest tests/` reported errors and ran zero assertions while the module
header claimed "14 defects, all with tests". Training a model per test module
was also the reason the old suite was slow enough to be skipped; the session
fixtures below train once for the whole run.

WRITE ISOLATION
---------------
Three endpoints mutate the filesystem: /api/v6/upload-csv writes into
Data/Custom_Uploads/, and the event-log endpoints read and write
Data/extubation_events_audit.json. The tests for them used to hit the real
directories, which had two consequences worth remembering:

  * Custom_Uploads/ sits at its 50-file quota in normal use, so every `pytest`
    run evicted real uploaded recordings to make room for its own fixtures;
  * the audit trail accumulated test events indistinguishable from clinical ones.

`isolated_data_root` redirects DATA_ROOT for the whole session into a tmp tree
that mirrors the corpus by COPY (so the read-only dataset tests still see all 81
recordings) but whose Custom_Uploads/ and audit trail are throwaway. Tests that
write must depend on it. Nothing under the real Data/ is modified by the suite.

This paragraph said "by symlink" long after the code stopped symlinking. It
matters which one it is: os.walk() does not follow symlinked directories, so a
symlinked corpus loads zero recordings and every dataset test skips silently.
The reason is spelled out at the copytree call below; do not re-optimise it back.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as M  # noqa: E402


def pytest_configure(config):
    """Put pytest's scratch root in the OS temp directory, not in the repo.

    This was `addopts = --basetemp=.pytest_temp` in pytest.ini, which put the
    scratch tree inside the working copy. pytest wipes basetemp at session
    start, so anything else that landed there - a redirected log, a second run -
    made every test error with WinError 32, and git saw the directory.

    Dropping basetemp entirely is not the fix either. Without it pytest uses its
    numbered-dir scheme under <temp>/pytest-of-<user>/, whose `pytest-current`
    symlink this machine cannot stat: session teardown then dies with
    `PermissionError: [WinError 5] Access is denied` AFTER the tests have run,
    losing the summary and the exit code. Creating that symlink needs Developer
    Mode or admin on Windows, which a test run must not require.

    So: an explicit basetemp, outside the repo, with a fixed name. Fixed rather
    than per-process on purpose - pytest clears basetemp at session start, so
    the directory is self-cleaning and does not accumulate. That makes two
    simultaneous runs collide, which AGENTS.md already forbids ("run one agent
    session at a time on this folder"); the collision this replaced was between
    a run and the repo, which nothing forbade.
    """
    if getattr(config.option, "basetemp", None) is None:
        config.option.basetemp = os.path.join(tempfile.gettempdir(), "project2-pytest")

REAL_DATA_ROOT = M.DATA_ROOT


@pytest.fixture(scope="session", autouse=True)
def isolated_data_root(tmp_path_factory):
    """Point DATA_ROOT at a disposable mirror of the corpus for the whole run."""
    sandbox = tmp_path_factory.mktemp("data_root")

    # Mirror the class folders by COPYING them.
    #
    # Symlinking looks cheaper and does not work: scan_csv_dirs() walks the tree
    # with os.walk(), which does not follow symlinked directories by default, so a
    # symlinked corpus loads zero recordings and every dataset test skips. The
    # whole corpus is well under 1 MB of CSV, so a copy costs nothing measurable
    # and behaves identically to the real thing.
    for entry in sorted(os.listdir(REAL_DATA_ROOT)) if os.path.isdir(REAL_DATA_ROOT) else []:
        src = os.path.join(REAL_DATA_ROOT, entry)
        if not os.path.isdir(src) or entry in ("Custom_Uploads", "research_plots"):
            continue
        shutil.copytree(src, os.path.join(sandbox, entry))

    # metrics.json is read by /api/v6/metrics; expose it if it exists so the
    # endpoint test can exercise its 200 branch rather than only the 503 one.
    real_metrics = os.path.join(REAL_DATA_ROOT, "metrics.json")
    if os.path.isfile(real_metrics):
        shutil.copy2(real_metrics, os.path.join(sandbox, "metrics.json"))

    os.makedirs(os.path.join(sandbox, "Custom_Uploads"), exist_ok=True)

    previous = M.DATA_ROOT
    M.DATA_ROOT = str(sandbox)
    # safe_data_path() and the model-cache paths are resolved against these.
    prev_model = M.MODEL_PERSISTENCE_PATH
    prev_digest = M.MODEL_DIGEST_PATH
    M.MODEL_PERSISTENCE_PATH = os.path.join(str(sandbox), "trained_model.joblib")
    M.MODEL_DIGEST_PATH = M.MODEL_PERSISTENCE_PATH + ".sha256.json"
    try:
        yield str(sandbox)
    finally:
        M.DATA_ROOT = previous
        M.MODEL_PERSISTENCE_PATH = prev_model
        M.MODEL_DIGEST_PATH = prev_digest


@pytest.fixture(scope="session")
def dataset(isolated_data_root):
    ds = M.load_dataset("kalman", verbose=False)
    if ds is None:
        pytest.skip(f"no recordings under {M.DATA_ROOT}")
    return ds


@pytest.fixture(scope="session")
def model(dataset):
    """One forest for the whole run. Fitting it per test was the reason the old
    suite was slow enough that people skipped it."""
    return M._new_rf(42).fit(dataset.X, dataset.y)


@pytest.fixture(scope="session")
def app(dataset, model):
    return M.create_app({"model": model, "use_gradient": False,
                         "calibration": "kalman"})


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture
def clean_event_log(isolated_data_root):
    """Start from a known-empty audit trail, and leave one behind."""
    path = os.path.join(M.DATA_ROOT, "extubation_events_audit.json")
    if os.path.exists(path):
        os.remove(path)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture(scope="session")
def sample_csv(dataset):
    """A recording that exists, URL-encoded the way the dashboard encodes it."""
    if dataset.files:
        return dataset.files[0]
    return "Peel/A_Peel_01.csv"
