"""Endpoint contract tests for main.py v6.2.

Replaces a v5.0 suite that could not even be imported: it called `get_app()`
(gone since v6.0) and asserted against `/api/v5/serial/connect`,
`/api/tele-nursing/*`, a `/ws/sensor` socket and an 11-feature vector - none of
which this program has. Both files therefore errored at COLLECTION, so
`pytest tests/` ran zero assertions while the module header claimed "14
defects, all with tests". Every route asserted below is one that `create_app`
really registers.
"""
from __future__ import annotations

import re
import urllib.parse
import uuid

import main as M


def _enc(rel: str) -> str:
    """Encode a dataset path the way the dashboard does - per segment."""
    return "/".join(urllib.parse.quote(p) for p in rel.split("/"))


# --------------------------------------------------------------------------
# health / metadata
# --------------------------------------------------------------------------
def test_health_reports_a_loaded_model(client):
    body = client.get("/api/v6/health").json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["n_pads"] == M.N_PADS
    assert body["sample_period_s"] == M.SAMPLE_PERIOD_S


def test_layout_exposes_25_pads_with_their_wiring(client):
    pads = client.get("/api/v6/layout").json()["pads"]
    assert len(pads) == M.N_PADS
    assert [p["pad"] for p in pads] == list(range(1, M.N_PADS + 1))
    # the wiring table must stay a bijection or the patch renders scrambled
    assert sorted(p["signal_channel"] for p in pads) == list(range(1, M.N_PADS + 1))


def test_dashboard_is_served_from_the_web_folder(client):
    """A12: the dashboard is web/index.html now, not a string literal in main.py."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Smart Extubation Early Warning" in resp.text
    assert "/static/app.js" in resp.text


def _strip_comments(src: str) -> str:
    """Drop //, /* */ and <!-- --> so the checks below test what a viewer sees.

    Without this these tests fail on their own documentation: the code carries
    comments naming the exact claims that were removed, which is the opposite
    of asserting them.
    """
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", src)


def test_dashboard_claims_no_medical_certification(client):
    """A12: the previous build printed "ISO 62304 CLASS B COMPLIANT" above two
    clinician signature lines. Nothing here has been assessed against IEC 62304,
    and software is not certified to it by writing a dashboard.

    Affirmative claims only - the disclaimer says the system has NOT been
    assessed against IEC 62304, and that sentence must survive.
    """
    page = _strip_comments(client.get("/").text)
    js = _strip_comments(client.get("/static/app.js").text)
    affirmative = [
        r"62304\s*(?:CLASS\s*\w+\s*)?COMPLIAN",
        r"62304\s*Certified",
        r"ISO\s*62304\s*&",
        r"SaMD[^.]{0,40}Complian",
        r"\bCertified\b",
    ]
    for pattern in affirmative:
        for name, text in (("index.html", page), ("app.js", js)):
            hit = re.search(pattern, text, re.I)
            assert not hit, f"compliance claim back in {name}: {hit.group(0)!r}"
    # the honest negative must still be there
    assert re.search(r"not been assessed against IEC 62304", js)


def test_dashboard_does_not_fabricate_its_numbers(client):
    """A12: CPRI came from Math.sin(), the class probabilities were literals and
    the ICU grid held eight invented patients. Every figure is API-sourced now."""
    js = _strip_comments(client.get("/static/app.js").text)
    assert "Math.sin" not in js, "the risk index is being generated in JavaScript again"
    assert "/api/v5/dataset/" in js and "/api/v6/heatmap/" in js
    assert "/api/v6/metrics" in js


def test_metrics_endpoint_serves_the_generated_file(client):
    """Anything that displays a number reads it from here."""
    resp = client.get("/api/v6/metrics")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        body = resp.json()
        assert "random_forest" in body and "dataset" in body
        assert "caveats" in body
    else:
        assert "--report" in resp.json()["detail"]


def test_serial_ports_endpoint_survives_having_no_hardware(client):
    body = client.get("/api/v5/serial/ports").json()
    assert isinstance(body["ports"], list)
    assert body["available"] == len(body["ports"])


# --------------------------------------------------------------------------
# dataset listing and analysis
# --------------------------------------------------------------------------
def test_datasets_lists_recordings(client):
    names = client.get("/api/v5/datasets").json()["datasets"]
    assert names and all(n.endswith(".csv") for n in names)
    assert names == sorted(names)
    assert not any(n.startswith("/") or ".." in n for n in names)


def test_dataset_analysis_shape_and_bounds(client, sample_csv):
    body = client.get(f"/api/v5/dataset/{_enc(sample_csv)}").json()
    frames = body["frames"]
    assert body["total_frames"] == len(frames) > 0
    assert body["calibration"] in ("static", "kalman")
    for fr in frames:
        assert len(fr["deltas"]) == M.N_PADS
        assert len(fr["probabilities"]) == M.N_CLASSES
        assert 0 <= fr["severity_level"] <= 3
        assert 0.0 <= fr["cpri_percent"] <= 100.0


def test_dataset_analysis_honours_the_warmup_guard(client, sample_csv):
    """R4/L1: the first KALMAN_WARMUP frames must never annunciate.

    The Kalman baseline is seeded from those frames, so their deltas are near
    zero - a feature vector the classifier never saw in training, which used to
    produce a Level 3 siren on frame 0 of every stream.
    """
    frames = client.get(f"/api/v5/dataset/{_enc(sample_csv)}").json()["frames"]
    warm = frames[:M.KALMAN_WARMUP]
    assert all(f["warming_up"] for f in warm)
    assert all(f["severity_level"] == 0 for f in warm)
    assert all(f["cpri_percent"] == 0.0 for f in warm)


def test_dataset_analysis_applies_the_debouncer(client):
    """R4: this endpoint feeds the dashboard's default view.

    It once returned the bare per-frame argmax, so 5 of 40 normal recordings
    sounded the Level 3 siren on page load while the WebSocket path - the only
    one under test - behaved correctly.
    """
    normals = [n for n in client.get("/api/v5/datasets").json()["datasets"]
               if n.split("/")[0] in ("N_base", "Brief Touch", "Friction",
                                      "Normal Mix", "Press")]
    if not normals:
        return
    for rel in normals:
        frames = client.get(f"/api/v5/dataset/{_enc(rel)}").json()["frames"]
        worst = max(f["severity_level"] for f in frames)
        assert worst < 3, f"{rel} escalated to the Level 3 siren on a normal recording"


def test_calibration_query_param_is_whitelisted(client, sample_csv):
    for asked, expected in [("static", "static"), ("kalman", "kalman"),
                            ("../etc", "kalman"), ("", "kalman")]:
        body = client.get(f"/api/v5/dataset/{_enc(sample_csv)}",
                          params={"calibration": asked}).json()
        assert body["calibration"] == expected


# --------------------------------------------------------------------------
# heatmap
# --------------------------------------------------------------------------
def test_heatmap_grid_is_rows_y_by_cols_x(client, sample_csv):
    """FIX F1: v5.0 built (80, 60) and reshaped to (60, 80), mirroring the patch."""
    body = client.get(f"/api/v6/heatmap/{_enc(sample_csv)}", params={"frame": 0}).json()
    assert body["rows"] == M.SPATIAL.n_rows and body["cols"] == M.SPATIAL.n_cols
    assert len(body["matrix"]) == M.SPATIAL.n_rows
    assert all(len(row) == M.SPATIAL.n_cols for row in body["matrix"])
    assert "propagation" in body


def test_heatmap_rejects_an_out_of_range_frame(client, sample_csv):
    assert client.get(f"/api/v6/heatmap/{_enc(sample_csv)}",
                      params={"frame": 10 ** 6}).status_code == 416
    assert client.get(f"/api/v6/heatmap/{_enc(sample_csv)}",
                      params={"frame": -1}).status_code == 416


def test_heatmap_honours_the_requested_calibration(client, sample_csv):
    """R14: this endpoint used to ignore ?calibration= and serve the default."""
    a = client.get(f"/api/v6/heatmap/{_enc(sample_csv)}",
                   params={"frame": 0, "calibration": "static"}).json()
    b = client.get(f"/api/v6/heatmap/{_enc(sample_csv)}",
                   params={"frame": 0, "calibration": "kalman"}).json()
    assert a["calibration"] == "static" and b["calibration"] == "kalman"


# --------------------------------------------------------------------------
# errors and containment
# --------------------------------------------------------------------------
def test_missing_dataset_is_404_not_500(client):
    assert client.get("/api/v5/dataset/Peel/nope.csv").status_code == 404
    assert client.get("/api/v6/heatmap/Peel/nope.csv").status_code == 404


def test_path_traversal_is_refused_on_both_file_endpoints(client):
    """FIX F3: Starlette does not normalise '..' for a {name:path} converter."""
    for evil in ["../main.py", "../../etc/passwd", "Peel/../../main.py",
                 "..%2F..%2Fmain.py"]:
        for route in ("/api/v5/dataset/", "/api/v6/heatmap/"):
            code = client.get(route + evil).status_code
            assert code in (400, 404), f"{route}{evil} returned {code}"


# --------------------------------------------------------------------------
# live socket
# --------------------------------------------------------------------------
def test_websocket_replays_a_recording_end_to_end(client, sample_csv):
    url = (f"/ws/live_sensor?source=replay"
           f"&file={urllib.parse.quote(sample_csv)}&realtime=0")
    with client.websocket_connect(url) as ws:
        started = ws.receive_json()
        assert started == {"event": "started", "source": "replay"}
        first = ws.receive_json()
        assert first["index"] == 0
        assert first["warming_up"] is True
        assert first["severity_level"] == 0        # warmup must be silent
        assert len(first["deltas"]) == M.N_PADS
        assert len(first["pad_values"]) == M.N_PADS
        assert len(first["probabilities"]) == M.N_CLASSES
        assert "propagation" in first


def test_websocket_reports_a_bad_file_instead_of_dropping(client):
    url = "/ws/live_sensor?source=replay&file=../../main.py&realtime=0"
    with client.websocket_connect(url) as ws:
        msg = ws.receive_json()
        if msg.get("event") == "started":
            msg = ws.receive_json()
        assert "error" in msg


def test_websocket_serial_source_needs_a_port(client):
    with client.websocket_connect("/ws/live_sensor?source=serial") as ws:
        assert "error" in ws.receive_json()


# --------------------------------------------------------------------------
# access gate (A13) — off unless PROJECT2_ACCESS_KEY is set
# --------------------------------------------------------------------------
def test_access_gate_is_off_by_default(client):
    assert client.get("/api/v6/health").status_code == 200


def _gated_client(dataset, key="unit-test-key"):
    import os
    from fastapi.testclient import TestClient
    os.environ["PROJECT2_ACCESS_KEY"] = key
    try:
        app = M.create_app({"model": M._new_rf(42).fit(dataset.X, dataset.y),
                            "use_gradient": False, "calibration": "kalman"})
    finally:
        os.environ.pop("PROJECT2_ACCESS_KEY", None)
    return TestClient(app), key


def test_access_gate_rejects_and_admits(dataset):
    c, key = _gated_client(dataset)
    assert c.get("/api/v6/health").status_code == 401
    assert c.get("/api/v6/health?key=wrong").status_code == 401
    assert c.get("/api/v6/health?key=" + key).status_code == 200
    assert c.get("/api/v6/health").status_code == 200            # cookie carries it
    assert c.get("/api/v6/health", headers={"X-Access-Key": key}).status_code == 200


def test_access_gate_also_covers_the_websocket(dataset):
    """A13b: @app.middleware("http") does not run for websocket scopes, so the
    gate missed /ws/live_sensor — the one route that opens a serial port on the
    host machine. That is the endpoint a public tunnel most needs closed."""
    from starlette.websockets import WebSocketDisconnect
    c, key = _gated_client(dataset)
    for url in ("/ws/live_sensor?source=serial&port=COM3",
                "/ws/live_sensor?source=replay&file=Peel/A_Peel_01.csv&realtime=0"):
        try:
            with c.websocket_connect(url):
                raise AssertionError(f"websocket accepted without a key: {url}")
        except WebSocketDisconnect:
            pass
    ok = "/ws/live_sensor?source=replay&realtime=0&key=" + key
    with c.websocket_connect(ok) as ws:
        assert ws.receive_json()["event"] == "started"


def test_no_regulatory_compliance_claim_anywhere_in_python(client):
    """B1: the ISO 62304 sweep only scanned index.html and app.js, so
    `AlarmDebouncer`'s "per IEC 60601-1-8 expectations" survived it.

    Nothing in this repo has been assessed against any medical standard. This
    checks the AFFIRMATIVE phrasings rather than the bare standard number: a
    first attempt looked for disowning words nearby, and a mutation probe showed
    that re-adding "compliant with IEC 60601-1-8" one line above the paragraph
    explaining the removal sailed straight through.
    """
    import inspect
    affirmative = re.compile(
        r"complian\w*\s+with"
        r"|complies\s+with"
        r"|conforms?\s+to"
        r"|certified"
        r"|per\s+[\w/ ]*6(?:0601|2304)[\w.-]*\s+expectation"
        r"|6(?:0601|2304)[\w.-]*\s*(?:CLASS\s+\w+\s*)?COMPLIAN",
        re.I)
    # the v6.2 changelog quotes verbatim the claim it deleted; that exact string
    # is the only affirmative form allowed to appear anywhere.
    quoted_removals = ('"ISO 62304 CLASS B COMPLIANT"',
                       '"per IEC 60601-1-8 expectations"')

    for i, line in enumerate(inspect.getsource(M).splitlines()):
        probe = line
        for allowed in quoted_removals:
            probe = probe.replace(allowed, " ")
        hit = affirmative.search(probe)
        assert not hit, (
            f"main.py:{i + 1} asserts conformance to a standard nothing here has "
            f"been assessed against: {hit.group(0)!r} in {line.strip()!r}")


def test_serial_port_must_be_one_this_machine_enumerates(client):
    """B6: the ?port= string went straight to serial.Serial(), so anyone with
    the link could name any path on the host — and pyserial's differing error
    text made it a filesystem existence oracle."""
    with client.websocket_connect("/ws/live_sensor?source=serial&port=/etc/hosts") as ws:
        msg = ws.receive_json()
    assert msg.get("error") == "unknown serial port"
    assert "attached" in msg and "/etc/hosts" not in str(msg["attached"])


def test_non_ascii_access_key_is_rejected_not_a_500(dataset):
    """B2: hmac.compare_digest raises TypeError on non-ASCII str, so ?key=é
    escaped the gate as an unhandled 500 instead of a 401."""
    c, key = _gated_client(dataset)
    for bad in ("é", "ключ", "🔑", "x" * 500):
        assert c.get("/api/v6/health", params={"key": bad}).status_code == 401, bad
    assert c.get("/api/v6/health?key=" + key).status_code == 200


def test_serial_connect_validates_port_and_handles_loopback(client):
    # Empty port returns disconnected loopback mode
    res1 = client.post("/api/v5/serial/connect", json={"port": ""})
    assert res1.status_code == 200
    assert res1.json()["status"] == "disconnected"

    # Non-existent port returns 404
    res2 = client.post("/api/v5/serial/connect", json={"port": "NON_EXISTENT_COM999"})
    assert res2.status_code == 404
    assert "not available" in res2.json()["detail"]


def test_event_log_records_only_real_telemetry(client):
    # GET initial logs
    res_get = client.get("/api/v6/event-log")
    assert res_get.status_code == 200
    assert "events" in res_get.json()

    # POST valid telemetry event
    valid_payload = {
        "dataset": "Normal Mix/N_Mix_01.csv",
        "frame_index": 12,
        "time_sec": 6.72,
        "severity_level": 2,
        "cpri_percent": 68.4,
        "min_delta": -1850.0
    }
    res_post = client.post("/api/v6/event-log", json=valid_payload)
    assert res_post.status_code == 200
    evt = res_post.json()["event"]
    assert evt["severity_level"] == 2
    assert evt["cpri_percent"] == 68.4
    assert evt["min_delta"] == -1850.0
    assert "action_taken" not in evt  # ensure no fake unbacked claim strings exist

    # Bad payload missing required numeric fields returns 400
    res_bad = client.post("/api/v6/event-log", json={"invalid": "data"})
    assert res_bad.status_code == 400


def test_upload_custom_csv_endpoint(client):
    # Non-CSV extension is rejected with 400
    res_bad_ext = client.post("/api/v6/upload-csv", files={"file": ("test.txt", b"hello", "text/plain")})
    assert res_bad_ext.status_code == 400

    # Valid 25-channel sensor CSV upload
    header = ",".join([f"Sensor-{i+1}" for i in range(25)]) + "\n"
    row1 = ",".join(["28000.0"] * 25) + "\n"
    row2 = ",".join(["27500.0"] * 25) + "\n"
    csv_content = (header + row1 * 10 + row2 * 10).encode("utf-8")

    res_ok = client.post("/api/v6/upload-csv", files={"file": ("unit_test_sample.csv", csv_content, "text/csv")})
    assert res_ok.status_code == 200
    data = res_ok.json()
    assert data["status"] == "uploaded"
    assert "unit_test_sample" in data["filename"]
    assert data["total_frames"] == 20


def test_upload_custom_csv_size_limit_and_collision(client):
    # Test M3: Upload over 5 MB returns HTTP 413
    huge_data = b"0," * 24 + b"0\n" + b"28000," * 24 + b"28000\n"
    huge_payload = huge_data * 150000  # > 5 MB
    res_large = client.post("/api/v6/upload-csv", files={"file": ("huge_file.csv", huge_payload, "text/csv")})
    assert res_large.status_code == 413
    assert "exceeds limit" in res_large.json()["detail"]

    # Test M3: Duplicate filename creates collision-free suffix
    unique_fn = f"dup_{uuid.uuid4().hex[:6]}.csv"
    header = ",".join([f"Sensor-{i+1}" for i in range(25)]) + "\n"
    row = ",".join(["28000.0"] * 25) + "\n"
    small_csv = (header + row * 10).encode("utf-8")

    res1 = client.post("/api/v6/upload-csv", files={"file": (unique_fn, small_csv, "text/csv")})
    res2 = client.post("/api/v6/upload-csv", files={"file": (unique_fn, small_csv, "text/csv")})
    assert res1.status_code == 200 and res2.status_code == 200
    assert res1.json()["filename"] == unique_fn
    assert res2.json()["filename"] != unique_fn  # collision prevented


def test_event_log_concurrency_safety(client):
    # Test M2: Concurrent event log POSTs
    import concurrent.futures

    def _send_log(i):
        return client.post("/api/v6/event-log", json={
            "dataset": "Normal Mix/N_Mix_01.csv",
            "frame_index": i,
            "time_sec": i * 0.56,
            "severity_level": 2,
            "cpri_percent": 50.0 + i,
            "min_delta": -1200.0
        })

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(_send_log, i) for i in range(10)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    assert all(r.status_code == 200 for r in results)
    logs = client.get("/api/v6/event-log").json()
    assert logs["total_events"] >= 10


def test_access_key_gate_rate_limiting(dataset):
    # Test M7: Rate limit after 10 failed key guesses
    c, key = _gated_client(dataset)
    for _ in range(10):
        c.get("/api/v6/health?key=badkey")
    
    # 11th attempt returns 429
    res_limited = c.get("/api/v6/health?key=badkey")
    assert res_limited.status_code == 429
    assert "Too Many Failed" in res_limited.text


def test_websocket_multi_client(client, sample_csv):
    # Test M8: Multi-client WebSocket stream
    url = f"/ws/live_sensor?source=replay&file={urllib.parse.quote(sample_csv)}&realtime=0"
    with client.websocket_connect(url) as ws1:
        with client.websocket_connect(url) as ws2:
            m1 = ws1.receive_json()
            m2 = ws2.receive_json()
            assert m1["event"] == "started"
            assert m2["event"] == "started"
            f1 = ws1.receive_json()
            f2 = ws2.receive_json()
            assert f1["index"] == 0 and f2["index"] == 0



