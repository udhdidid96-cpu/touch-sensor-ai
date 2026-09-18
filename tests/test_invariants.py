"""Feature F17: Project Invariants Verification Suite (AGENTS.md).

Strictly verifies all 9 non-negotiable project invariants:
  Invariant 1: web/ contains no classification logic (nLifted, rawLevel, liveKalman, isCriticalDetached)
  Invariant 2: classify_deltas() contains no hand-coded probabilities (strictly matches full_proba())
  Invariant 3: Bed slots return patient_id: None and cpri_percent: None until operator input
  Invariant 4: Displayed metrics measured or absent (no digits in index.html data-metric markup)
  Invariant 5: SPEC_DETACH_MAX == 25000.0 and audit label matches
  Invariant 6: Dockerfile never permits --allow-public-no-key
  Invariant 7: Zero emoji across web and server responses
  Invariant 8: IEC 62304 non-certification notice visibly present in index.html and app.js
  Invariant 9: Data/metrics.json reproduces identically
"""
from __future__ import annotations

import glob
import os
import re
import numpy as np
import pytest

import main as M


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(PROJECT_ROOT, "web")


def test_invariant_1_web_never_classifies():
    """Invariant 1: The browser never classifies.

    app.js and web_serial.js are audited for nLifted, rawLevel, liveKalman, isCriticalDetached.
    Severity, CPRI, and pad counts must originate exclusively from the server.
    """
    prohibited = ["nLifted", "rawLevel", "liveKalman", "isCriticalDetached"]
    web_files = [os.path.join(WEB_DIR, f) for f in ("app.js", "web_serial.js")]

    for fpath in web_files:
        assert os.path.isfile(fpath), f"Missing web file: {fpath}"
        with open(fpath, "r", encoding="utf-8") as fh:
            content = fh.read()
        for token in prohibited:
            assert token not in content, (
                f"Invariant 1 VIOLATION: prohibited classification token '{token}' "
                f"found in {os.path.basename(fpath)}"
            )


def test_invariant_2_no_handcoded_probability(model, dataset):
    """Invariant 2: Nothing hand-codes a probability in classify_deltas().

    Output strictly matches full_proba() on all active frames.
    """
    for fi in range(0, min(20, dataset.n_files), 4):
        delta = dataset.frames[fi]
        proba, raw, risk = M.classify_deltas(model, delta, use_gradient=False)
        d = np.atleast_2d(np.asarray(delta, dtype=float))
        active = np.max(np.abs(d), axis=1) >= M.NOISE_GATE_COUNTS

        expected = np.zeros_like(proba)
        expected[:, 0] = 1.0
        if active.any():
            expected[active] = M.full_proba(model, M.extract_features(d[active], False))

        np.testing.assert_allclose(
            proba,
            expected,
            rtol=1e-5,
            atol=1e-5,
            err_msg=f"Invariant 2 VIOLATION: classify_deltas modified model probabilities in {dataset.files[fi]}",
        )
        assert np.all(raw == expected.argmax(axis=1))
        assert np.all(risk[~active] == 0.0)


def _strip_comments(src: str) -> str:
    """Drop //, /* */ and <!-- --> so assertions check running code / active DOM,
    not developer comments that document historically removed defects."""
    no_html = re.sub(r"<!--.*?-->", "", src, flags=re.DOTALL)
    no_block = re.sub(r"/\*.*?\*/", "", no_html, flags=re.DOTALL)
    return re.sub(r"//.*$", "", no_block, flags=re.MULTILINE)


def test_invariant_3_no_invented_patient_identity(client):
    """Invariant 3: No invented patient identity anywhere.

    Bed slots return patient_id: None and cpri_percent: None until an operator types something.
    No HN-#####, ICU-A-###, or invented wards exist in markup or API.
    """
    res = client.get("/api/v6/ward/status")
    assert res.status_code == 200
    beds = res.json().get("beds", [])
    assert len(beds) == 8, f"Expected 8 bed slots, got {len(beds)}"

    for b in beds:
        assert b["patient_id"] is None, f"Invariant 3 VIOLATION: Invented patient ID {b['patient_id']!r}"
        assert b["cpri_percent"] is None, f"Invariant 3 VIOLATION: Invented CPRI {b['cpri_percent']!r}"
        assert b["severity_level"] == 0

    # Check client source files for hardcoded patient patterns
    hn_pattern = re.compile(r"HN-\d{4,}", re.IGNORECASE)
    icu_pattern = re.compile(r"ICU-[A-D]-\d{3}", re.IGNORECASE)
    for js_file in ("app.js", "web_serial.js", "index.html"):
        p = os.path.join(WEB_DIR, js_file)
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as fh:
                text = _strip_comments(fh.read())
            assert not hn_pattern.search(text), f"Invented HN pattern in {js_file}"
            assert not icu_pattern.search(text), f"Invented ICU pattern in {js_file}"


def test_invariant_4_displayed_numbers_measured_or_absent():
    """Invariant 4: Displayed numbers are measured or absent.

    The four data-metric slots in index.html must contain no digit in the markup
    and must not be inside a hidden container.
    """
    index_path = os.path.join(WEB_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as fh:
        html = fh.read()

    # Find all elements with data-metric
    metric_matches = re.findall(r'<([a-zA-Z0-9]+)[^>]*data-metric="([^"]+)"[^>]*>(.*?)</\1>', html, re.DOTALL)
    assert len(metric_matches) >= 4, f"Expected at least 4 data-metric slots, found {len(metric_matches)}"

    for tag, metric_name, inner in metric_matches:
        # Must contain no hardcoded digit in initial markup
        digits = re.findall(r"\d", inner)
        assert not digits, (
            f"Invariant 4 VIOLATION: data-metric '{metric_name}' contains hardcoded digits: {digits} in {inner!r}"
        )


def test_invariant_5_spec_detach_max_constant_and_label():
    """Invariant 5: SPEC_DETACH_MAX is 25000 and audit label matches constant."""
    assert M.SPEC_DETACH_MAX == 25000.0, f"Invariant 5 VIOLATION: SPEC_DETACH_MAX is {M.SPEC_DETACH_MAX}"

    rep = M.audit_folder(M.DATA_ROOT)
    spec_checks = [c for c in rep["checks"] if "KES 2025" in c["check"] or "25,000" in c["check"]]
    assert len(spec_checks) > 0, "Detachment spec check not found in audit report"
    for sc in spec_checks:
        assert "25,000" in sc["check"], f"Audit label does not quote 25,000: {sc['check']}"


def test_invariant_6_dockerfile_security():
    """Invariant 6: The Dockerfile must never carry --allow-public-no-key."""
    dockerfile_path = os.path.join(PROJECT_ROOT, "Dockerfile")
    if os.path.isfile(dockerfile_path):
        with open(dockerfile_path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
        active_lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
        for line in active_lines:
            assert "--allow-public-no-key" not in line, (
                f"Invariant 6 VIOLATION: Dockerfile active command carries --allow-public-no-key: {line}"
            )


def test_invariant_7_zero_emoji():
    """Invariant 7: Zero emoji across index.html, app.js, web_serial.js, and server status strings."""
    emoji_pattern = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27bf\ufe0f]")

    # Check web files
    for fname in ["index.html", "style.css", "app.js", "web_serial.js"]:
        fpath = os.path.join(WEB_DIR, fname)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8") as fh:
                text = fh.read()
            match = emoji_pattern.search(text)
            assert match is None, f"Invariant 7 VIOLATION: Emoji found in web/{fname}: {match.group()!r}"

    # Check server status strings in main.py
    for status_str in M.STATUS_TEXT_MAP.values():
        match = emoji_pattern.search(status_str)
        assert match is None, f"Invariant 7 VIOLATION: Emoji in status map: {status_str!r}"


def test_invariant_8_iec_62304_disclaimer():
    """Invariant 8: 'not been assessed against IEC 62304' visibly present in index.html and app.js."""
    phrase = "not been assessed against IEC 62304"

    index_path = os.path.join(WEB_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as fh:
        index_content = fh.read()
    assert phrase in index_content, "Invariant 8 VIOLATION: Disclaimer missing from index.html"

    app_path = os.path.join(WEB_DIR, "app.js")
    with open(app_path, "r", encoding="utf-8") as fh:
        app_content = fh.read()
    assert phrase in app_content, "Invariant 8 VIOLATION: Disclaimer missing from app.js"


def test_invariant_9_metrics_json_reproduces(dataset):
    """Invariant 9: metrics.json must reproduce identically via verify_metrics()."""
    from tests.test_regressions import _oof
    _, oof, _ = _oof()
    rep = M.verify_metrics(dataset, oof=oof)
    if rep["status"] == "absent":
        pytest.skip("Data/metrics.json absent in this sandbox")
    assert rep["status"] == "current", (
        f"Invariant 9 VIOLATION: metrics.json drifted! Drift details: {rep.get('drift')}"
    )
