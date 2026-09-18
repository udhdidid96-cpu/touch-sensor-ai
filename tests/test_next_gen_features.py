"""Tests for Next-Generation ICU Features & Edge-Case Resilience (R1-R4)."""

import numpy as np
from main import LivePipeline, N_PADS


def test_shift_report_endpoint(client):
    """Verify /api/v6/shift-report returns structured shift handover metrics."""
    res = client.get("/api/v6/shift-report")
    assert res.status_code == 200
    data = res.json()
    assert "shift_id" in data
    assert "event_breakdown" in data
    assert "adhesion_health" in data
    assert data["adhesion_health"]["monitored_channels"] == N_PADS
    # `uptime_percentage` was 99.8 on an empty trail and otherwise
    # 100 - (2.5 x L3 + 0.8 x L2), floored at 85 - a number manufactured from an
    # alarm count and printed on the dashboard as "Patch Uptime". Nothing here
    # measures uptime, so the field must stay gone until something does.
    assert "uptime_percentage" not in data["adhesion_health"], (
        "shift report is publishing an uptime figure again; measure disconnected "
        "frames over streamed frames first")


def test_ward_status_endpoint(client):
    """/api/v6/ward/status hands out EMPTY slots and no invented telemetry.

    This test used to assert only that eight beds came back and that they were
    sorted. They were - eight beds with invented patient ids (ICU-A-101 ...) and
    invented CPRI readings (1.4, 3.8, 0.5 ...) - so the test locked the
    fabrication in place. There is one live socket and no multi-patient data
    source behind this endpoint, so a slot carries no identity and no number.
    """
    res = client.get("/api/v6/ward/status")
    assert res.status_code == 200
    data = res.json()
    assert len(data["beds"]) == 8
    for b in data["beds"]:
        assert b["patient_id"] is None, f"invented patient id on {b['bed']}: {b['patient_id']!r}"
        assert b["cpri_percent"] is None, (
            f"{b['bed']} reports CPRI {b['cpri_percent']} with nothing attached to it")
        assert b["severity_level"] == 0
        assert not b["is_live"]
    severities = [b["severity_level"] for b in data["beds"]]
    assert severities == sorted(severities, reverse=True)


def test_usb_reconnection_reseeds_only_after_a_real_disconnect():
    """The re-seed branch has to be reachable with values this hardware produces.

    The previous version of this test fed 45,000 counts as a "normal" frame and
    46,000 as the reconnect, and passed for that reason alone: the branch it
    exercised required `np.all(pad_frame >= 30000)`. Measured over all 81
    recordings the corpus spans 27,251-32,024 counts and the highest "weakest
    pad in a frame" anywhere in it is 28,102 - so NO real frame has all 25 pads
    above 30,000, and in the field the baseline was never re-taken after a
    disconnect. A patch swapped mid-session went on being measured against the
    previous sensor's baseline.

    Duration, not amplitude, is what separates a dropped frame from an unplug,
    so both cases are pinned here at realistic levels.
    """
    from main import BASELINE_COUNTS

    # --- a real disconnect: signal gone for RESEED_AFTER_LOST_FRAMES, then a
    #     fresh patch at a different resting level -> baseline re-taken.
    pipe = LivePipeline(model=None, warmup_frames=3)
    for _ in range(6):
        out = pipe.process(np.full(N_PADS, BASELINE_COUNTS))
        assert not out.get("disconnected", False)

    for _ in range(LivePipeline.RESEED_AFTER_LOST_FRAMES):
        assert pipe.process(np.zeros(N_PADS))["disconnected"] is True

    fresh = np.full(N_PADS, BASELINE_COUNTS + 400.0)      # a plausible new patch
    out = pipe.process(fresh)
    assert not out.get("disconnected", False)
    assert np.all(np.abs(out["deltas"]) < 50.0), (
        f"baseline was not re-taken after the sensor went away; deltas "
        f"{out['deltas'][:5]} are measured against the old attachment")

    # --- one dropped frame is NOT a reconnect. Re-seeding here would zero the
    #     deltas in the middle of an event and erase it.
    pipe = LivePipeline(model=None, warmup_frames=3)
    for _ in range(6):
        pipe.process(np.full(N_PADS, BASELINE_COUNTS))
    lifting = np.full(N_PADS, BASELINE_COUNTS - 800.0)    # patch coming off
    before = pipe.process(lifting)["deltas"]
    assert min(before) < -500.0, "setup: the synthetic lift should read as a deep delta"

    pipe.process(np.zeros(N_PADS))                        # single glitched frame
    after = pipe.process(lifting)["deltas"]
    assert min(after) < -500.0, (
        f"a single dropped frame re-seeded the baseline and erased a lift in "
        f"progress: {min(before):.0f} -> {min(after):.0f} counts")


def test_cdc_tube_localization_endpoint(client):
    """Test /api/v6/cdc/tube-localization detects tube shadow from absolute capacitance."""
    c_abs = [30.0] * N_PADS
    for p in [0, 2, 6, 8, 10]:
        c_abs[p] = 28.5

    res = client.post("/api/v6/cdc/tube-localization", json={"c_abs_pf": c_abs})
    assert res.status_code == 200
    data = res.json()
    assert data["detected"] is True
    assert set(data["shadowed_pads"]).issuperset({1, 3, 7, 9, 11})
    assert data["axis_orientation"] in ("vertical", "horizontal")
    assert data["confidence"] > 0.0

    bad_res = client.post("/api/v6/cdc/tube-localization", json={"c_abs_pf": [30.0] * 10})
    assert bad_res.status_code == 400


def test_convert_absolute_cdc_to_counts():
    """Verify conversion of absolute CDC pF to delta counts."""
    from main import convert_absolute_cdc_to_counts, COUNTS_PER_PF
    c_abs = np.full(N_PADS, 30.0)
    c_base = np.full(N_PADS, 30.0)
    deltas = convert_absolute_cdc_to_counts(c_abs, c_base)
    assert np.allclose(deltas, 0.0)

    c_lift = np.full(N_PADS, 25.0)
    deltas_lift = convert_absolute_cdc_to_counts(c_lift, c_base)
    expected_delta = -5.0 * COUNTS_PER_PF
    assert np.allclose(deltas_lift, expected_delta)


def test_live_pipeline_cdc_mode_and_disconnect():
    """Verify LivePipeline seamlessly processes absolute CDC inputs without false disconnect."""
    pipe = LivePipeline(model=None, warmup_frames=2, cdc_mode=True)
    # Feed CDC frames ~30.0 pF (which would erroneously trigger <3000 counts in legacy code)
    normal_frame = np.full(N_PADS, 30.0)
    out1 = pipe.process(normal_frame)
    assert not out1.get("disconnected", False)
    assert out1["mode"] == "cdc"

    # Verify open-circuit / disconnect detection in CDC mode (< 1 pF)
    disconnect_frame = np.zeros(N_PADS)
    out_disc = pipe.process(disconnect_frame)
    assert out_disc["disconnected"] is True
    assert out_disc["mode"] == "cdc"


def test_static_tube_localization_edge_cases(client):
    """Test NaN, Inf, and diagonal tube orientation validation."""
    from main import detect_static_tube_localization
    # NaN input
    nan_arr = np.full(N_PADS, 30.0)
    nan_arr[5] = np.nan
    res_nan = detect_static_tube_localization(nan_arr)
    assert not res_nan["detected"]
    assert "non-finite" in res_nan["reason"]

    # Negative input
    neg_arr = np.full(N_PADS, 30.0)
    neg_arr[2] = -5.0
    res_neg = detect_static_tube_localization(neg_arr)
    assert not res_neg["detected"]
    assert "negative" in res_neg["reason"]

    # Diagonal orientation
    diag_arr = np.full(N_PADS, 30.0)
    # Pads running diagonally: 1, 5, 13, 20, 25
    for p in [0, 4, 12, 19, 24]:
        diag_arr[p] = 28.0
    res_diag = detect_static_tube_localization(diag_arr)
    assert res_diag["detected"] is True
    assert res_diag["axis_orientation"] in ("diagonal", "vertical", "horizontal")


def test_analyze_surface_topography_planar_and_stepped(client):
    """Verify surface topography profiling for planar, contoured, and stepped ridge profiles."""
    from main import analyze_surface_topography, compute_fractional_deltas

    # 1. Planar surface (uniform baseline counts ~28,000)
    flat_base = np.full(N_PADS, 28000.0)
    flat_res = analyze_surface_topography(flat_base)
    assert flat_res["valid"] is True
    assert flat_res["surface_profile"] == "planar"
    assert len(flat_res["tenting_pads"]) == 0
    assert len(flat_res["flush_pads"]) == N_PADS
    assert len(flat_res["adaptive_lift_gates"]) == N_PADS
    assert flat_res["adaptive_lift_gates"][0] == -308.0

    # 2. Stepped ridge / tenting (e.g. pads 11, 12, 13 bridging over ETT tube with lower capacitance)
    stepped_base = np.full(N_PADS, 28000.0)
    for p in [10, 11, 12]:  # pads 11, 12, 13
        stepped_base[p] = 14000.0
    stepped_res = analyze_surface_topography(stepped_base)
    assert stepped_res["valid"] is True
    assert stepped_res["surface_profile"] == "stepped_ridge"
    assert set(stepped_res["tenting_pads"]).issuperset({11, 12, 13})
    assert "trough" in stepped_res["recommendation"].lower() or "step-height" in stepped_res["recommendation"].lower()
    # Check that adaptive lift gates for tenting pads are adjusted appropriately (not stuck at -300)
    assert stepped_res["adaptive_lift_gates"][10] == -154.0  # -0.011 * 14000 = -154

    # 3. Fractional deltas scale-invariance
    deltas = np.array([-1400.0, -2800.0])
    bases = np.array([14000.0, 28000.0])
    frac = compute_fractional_deltas(deltas, bases)
    # Both pads lifted by 10% of their respective baselines -> identical fractional delta -0.10
    assert np.allclose(frac, -0.10)

    # 4. REST endpoint test
    res = client.post("/api/v6/topography/analyze", json={"baseline": list(stepped_base)})
    assert res.status_code == 200
    data = res.json()
    assert data["valid"] is True
    assert data["surface_profile"] == "stepped_ridge"
    assert set(data["tenting_pads"]).issuperset({11, 12, 13})


def test_dockerfile_security_guard():
    """Invariant 6 (TEST-01): Dockerfile must never carry --allow-public-no-key in active commands."""
    import os
    dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "Dockerfile")
    if os.path.exists(dockerfile_path):
        with open(dockerfile_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            clean = line.strip()
            if not clean.startswith("#"):
                assert "--allow-public-no-key" not in clean, (
                    "SECURITY VIOLATION: Dockerfile contains --allow-public-no-key (Invariant 6 violated)"
                )


def test_simulator_websocket_source(client):
    """TEST-02: Test websocket telemetry stream from simulator source."""
    with client.websocket_connect("/ws/live_sensor?source=simulator") as ws:
        started = ws.receive_json()
        assert started.get("event") == "started"
        assert started.get("source") in ("simulator", "Live-Hardware (Standby)")
        frame = ws.receive_json()
        assert "pad_values" in frame
        assert len(frame["pad_values"]) == N_PADS
        assert "deltas" in frame
        assert len(frame["deltas"]) == N_PADS
        assert frame["severity_level"] in (0, 1, 2, 3)


def test_event_log_nan_inf_and_bounds_rejection(client):
    """TEST-03: /api/v6/event-log rejects NaN, Inf, negative indices, and invalid severities."""
    # 1. NaN cpri_percent passed via raw non-finite payload
    res = client.post(
        "/api/v6/event-log",
        content=b'{"severity_level": 1, "cpri_percent": NaN, "frame_index": 10, "time_sec": 5.0}',
        headers={"content-type": "application/json"}
    )
    assert res.status_code == 400

    # 2. Negative frame index
    res = client.post("/api/v6/event-log", json={
        "severity_level": 1,
        "cpri_percent": 25.0,
        "frame_index": -1,
        "time_sec": 5.0,
    })
    assert res.status_code == 400

    # 3. Boolean severity level
    res = client.post("/api/v6/event-log", json={
        "severity_level": True,
        "cpri_percent": 25.0,
        "frame_index": 10,
        "time_sec": 5.0,
    })
    assert res.status_code == 400


def test_localization_keys_parity():
    """TEST-04: web/app.js contains definitions for th, en, and jp."""
    import os
    app_js_path = os.path.join(os.path.dirname(__file__), "..", "web", "app.js")
    assert os.path.exists(app_js_path)
    with open(app_js_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "th:" in content and "en:" in content and "jp:" in content
    # Check core clinical keys present in all languages
    core_keys = ["peel_dir", "standby", "ward_unassigned", "protocol_live", "mode_live"]
    for k in core_keys:
        assert f"{k}:" in content


def test_fractional_deltas_edge_guards():
    """TEST-05: compute_fractional_deltas handles negative, zero, and boundary baselines."""
    from main import compute_fractional_deltas
    # Zero and negative baseline
    d = np.array([-100.0, 200.0])
    b = np.array([0.0, -10.0])
    res = compute_fractional_deltas(d, b)
    assert np.isfinite(res).all()
    # Falls back to safe divisor 1.0
    assert np.allclose(res, d)


def test_cdc_tube_payload_validation(client):
    """TEST-06: /api/v6/cdc/tube-localization validates payload structure strictly."""
    # List of booleans instead of numbers
    res = client.post("/api/v6/cdc/tube-localization", json={"c_abs_pf": [True] * N_PADS})
    assert res.status_code == 400

    # Wrong length list
    res = client.post("/api/v6/cdc/tube-localization", json={"c_abs_pf": [30.0] * 12})
    assert res.status_code == 400

    # Non-dict body
    res = client.post("/api/v6/cdc/tube-localization", json="not a dict")
    assert res.status_code in (400, 422)



