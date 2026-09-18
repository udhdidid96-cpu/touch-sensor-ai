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

import glob
import json
import os
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
    serial_js = _strip_comments(client.get("/static/web_serial.js").text)
    affirmative = [
        r"62304\s*(?:CLASS\s*\w+\s*)?COMPLIAN",
        r"62304\s*Certified",
        r"ISO\s*62304\s*&",
        r"SaMD[^.]{0,40}Complian",
    ]
    sources = (("index.html", page), ("app.js", js), ("web_serial.js", serial_js))
    for pattern in affirmative:
        for name, text in sources:
            hit = re.search(pattern, text, re.I)
            assert not hit, f"compliance claim back in {name}: {hit.group(0)!r}"

    # "certified" needs its context checked rather than being banned outright.
    #
    # A bare r"\bCertified\b" was in the list above, and it cannot tell
    # "ISO 62304 Certified" from "is not a certified medical device" - so it
    # failed the honest disclaimer this very test demands three lines further
    # down. A claim is a claim only when it is not negated.
    negation = re.compile(r"(?:\bnot\b|\bno\b|\bnever\b|\bwithout\b|\buncertified\b)"
                          r"[^.]{0,40}$", re.I)
    for name, text in sources:
        for hit in re.finditer(r"\bcertified\b", text, re.I):
            preceding = text[max(0, hit.start() - 60):hit.start()]
            assert negation.search(preceding), (
                f"unqualified certification claim in {name}: "
                f"...{text[max(0, hit.start() - 60):hit.end() + 20]!r}")

    # The honest negative must be in BOTH files, and index.html is the one that
    # matters. This assertion covered app.js only, which was satisfied for a long
    # time by a console.info() on line 7 - executable, true, and invisible to
    # every person who will ever look at this dashboard, because nobody opens
    # devtools to find out whether a medical device is certified.
    assert re.search(r"not been assessed against IEC 62304", js), \
        "app.js lost the regulatory disclaimer"
    assert re.search(r"not been assessed against IEC 62304", page), \
        ("index.html has no VISIBLE regulatory disclaimer - a console.info() in "
         "app.js is not a disclaimer a viewer can read")


def test_dashboard_does_not_fabricate_its_numbers(client):
    """A12: CPRI came from Math.sin(), the class probabilities were literals and
    the ICU grid held eight invented patients. Every figure is API-sourced now.

    This test read app.js and nothing else, so it stayed green through the whole
    period when index.html carried 97.53% accuracy, 0.9652 macro F1, 100% peel F1
    and a 0.0% false-alarm rate as literals in the markup, under a "Validated"
    stamp, with no code that ever replaced them - the exact defect named in its
    own docstring. Its `"/api/v6/metrics" in js` assertion passed because app.js
    did fetch that endpoint; it just used the response for the timestamp. So:
    check the markup too, and check it for numerals rather than for the specific
    four that happened to be wrong last time.
    """
    js = _strip_comments(client.get("/static/app.js").text)
    serial_js = _strip_comments(client.get("/static/web_serial.js").text)
    page = _strip_comments(client.get("/").text)

    assert "Math.sin" not in js, "the risk index is being generated in JavaScript again"
    assert "/api/v5/dataset/" in js and "/api/v6/heatmap/" in js
    assert "/api/v6/metrics" in js

    # No figures in the metric value slots. Anything displayed there must arrive
    # from /api/v6/metrics at runtime, so the markup carries a placeholder only.
    #
    # Anchored on the data-metric attribute rather than on a regex over a region
    # of the document: the earlier version sliced from `class="metrics-card"` to
    # the next card and broke the moment the layout changed, which is exactly the
    # kind of guard that quietly stops guarding. One attribute per value slot is
    # stable across any redesign.
    slots = re.findall(r'data-metric="([^"]+)"[^>]*>([^<]*)<', page)
    assert len(slots) >= 4, (
        f"expected at least 4 data-metric value slots in index.html, found "
        f"{len(slots)}: {slots}")
    for name, text in slots:
        assert not re.search(r"\d", text), (
            f'metric slot "{name}" has a hard-coded value in the markup: {text!r}. '
            f"Render it from /api/v6/metrics in renderMetrics() instead.")

    # A slot nobody fills is not a guard, it is a stage prop.
    #
    # The four data-metric spans spent a while inside a `<div style="display:none">`
    # with the renderer that filled them deleted from app.js - so this test's
    # "no digits in a slot" rule passed on four hidden em dashes, and the panel
    # showed the operator no measured performance at all. Both halves are now
    # required: the slots must be visible, and something must write to them.
    hidden = re.search(r'style="[^"]*display:\s*none[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*'
                       r'<[^>]*data-metric=', page)
    assert not hidden, (
        "the data-metric slots are inside a hidden container - whatever is in "
        "them, nobody can read it")
    assert re.search(r'\[data-metric="?\$\{?|\[data-metric=', js), (
        "nothing in app.js writes to a [data-metric] slot; the measured figures "
        "will stay as placeholders forever")
    for key in ("random_forest", "episode_level", "accuracy_mean", "peel_f1"):
        assert key in js, (
            f"app.js does not read {key!r} from /api/v6/metrics - a figure it "
            f"cannot read is a figure it will invent or omit")

    # And the specific literals that were there last time, anywhere on the page.
    for literal in ("97.53", "0.9652"):
        assert literal not in page, f"{literal} is hard-coded in index.html again"

    # No emoji in a clinical readout. Every status glyph the old build shipped
    # (traffic lights, sirens, raised hands) read as a consumer app rather than a
    # bedside instrument, and they were in the API payload as well as the markup.
    emoji = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")
    for name, text in (("index.html", page), ("app.js", js), ("web_serial.js", serial_js)):
        hit = emoji.search(text)
        assert not hit, f"emoji back in {name}: {hit.group(0)!r}"

    # The ward view was a hard-coded 8-bed grid backed by no multi-patient API.
    # It was removed once, came back on 2026-08-18 as `icu-bed-card` with eight
    # invented Thai patients, HN-67081xx hospital numbers, ETT sizes and CPRI
    # readings between 0.5% and 4.2%, and this assertion stayed green because it
    # only knew the OLD class name. Guard the thing itself - invented patient
    # identity and invented telemetry - not the markup it happened to use.
    assert "bed-unit" not in js and "bed-unit" not in page, \
        "the fabricated ICU bed grid is back; it needs a real multi-patient API first"

    for blob, where in ((js, "app.js"), (page, "index.html")):
        hit = re.search(r"HN-\d{5,}|ICU-[A-D]-\d{3}", blob)
        assert not hit, (
            f"invented patient identifier {hit.group(0)!r} is back in {where}. Bed "
            f"slots carry no identity until an operator types one.")
        assert "ETT #" not in blob, (
            f"invented tube size/depth is back in {where} - this system measures "
            f"a dressing, it knows nothing about the tube")
    assert "uptime_percentage" not in js, (
        "the dashboard is printing a patch-uptime figure again; nothing in this "
        "system measures uptime")

    # No classifier in app.js either. web_serial.js was cleaned up and this file
    # then grew its own: a -45 count 'lifting' threshold and a -120/8-pad rule
    # that printed "Critical: Full Detachment" on its own authority, against
    # thresholds that exist nowhere in main.py. Pad counts come from
    # propagation.n_lifting_pads; severity comes from severity_level.
    for marker in ("nLifted", "rawLevel", "liveKalman", "isCriticalDetached"):
        assert marker not in js, (
            f"app.js is classifying again ({marker!r}). The browser renders what "
            f"classify_deltas() decided; it does not decide.")

    # No classifier in the browser. web_serial.js once carried a complete second
    # pipeline - its own thresholds, its own baseline filter, its own severity
    # levels, and no debouncer at all - which disagreed with main.py on every
    # recording.
    for marker in ("rawLevel", "severity_level:", "nLifted", "liveKalman"):
        assert marker not in serial_js, (
            f"web_serial.js is classifying again ({marker!r}). Frames go up via "
            f"?source=client; classify_deltas() decides, the browser renders.")


def test_frontend_wiring_and_helper_integrity(client):
    """Ensure uploadSelectedCSV, withKey, showError, clearError are properly implemented
    and that no inline hex color assignments violate rules/frontend.md."""
    js = client.get("/static/app.js").text
    serial_js = client.get("/static/web_serial.js").text
    page = client.get("/").text

    assert "uploadSelectedCSV" in js, "uploadSelectedCSV is missing in app.js"
    assert "uploadSelectedCSV" in page, "uploadSelectedCSV is not wired in index.html"
    assert "withKey" in js, "withKey is missing in app.js"
    assert "withKey" in serial_js, "withKey is missing in web_serial.js"
    assert "showError" in serial_js, "showError is missing in web_serial.js"
    assert "clearError" in serial_js, "clearError is missing in web_serial.js"

    # Check rules/frontend.md: Never inline a color in CSS or JS style.color = ...
    hex_color = re.compile(r"\.style\.(?:color|background|backgroundColor|borderColor)\s*=\s*['\"][^'\"]*#[0-9a-fA-F]{3,8}")
    for name, code in (("app.js", js), ("web_serial.js", serial_js)):
        hit = hex_color.search(code)
        assert not hit, f"inline hex color assignment in {name}: {hit.group(0)!r}"


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
        assert started["event"] == "started" and started["source"] == "replay"
        # The handshake also reports whether PAD_ORDER was applied to this
        # stream. It is not decoration: the live pad-order convention is the one
        # open item from A9, so a spatial result pulled off this socket has to
        # carry its own orientation rather than rely on a comment in main.py.
        assert started["pad_order_applied"] is False, (
            "a replay source feeds recorded Sensor-* frames, which are already in "
            "pad order; permuting them would scramble the patch")
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


def test_event_log_records_all_extended_telemetry_and_exports_csv(client, clean_event_log):
    # POST event with full telemetry
    full_payload = {
        "dataset": "Live-Hardware",
        "frame_index": 45,
        "time_sec": 25.2,
        "severity_level": 3,
        "status": "Critical: full detachment",
        "cpri_percent": 89.5,
        "probabilities": [0.01, 0.05, 0.14, 0.80],
        "min_delta": -2450.0,
        "max_delta": 120.0,
        "attached_nodes": 5,
        "lifting_pads": 20,
        "grid_mean": -650.0,
        "peel_desc": "peeling from top-left, spreading S (20 pads lifted)",
        "deltas": [-2450.0, -1200.0, -800.0] + [0.0] * 22
    }
    res_post = client.post("/api/v6/event-log", json=full_payload)
    assert res_post.status_code == 200
    evt = res_post.json()["event"]
    assert evt["severity_level"] == 3
    assert evt["status"] == "Critical: full detachment"
    assert evt["attached_nodes"] == 5
    assert evt["lifting_pads"] == 20
    assert len(evt["deltas"]) == 25
    assert evt["probabilities"] == [0.01, 0.05, 0.14, 0.8]

    # Test CSV export endpoint
    res_csv = client.get("/api/v6/event-log/export-csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers.get("content-type", "")
    assert "attachment" in res_csv.headers.get("content-disposition", "")
    assert "event_logs_" in res_csv.headers.get("content-disposition", "")
    csv_body = res_csv.text
    assert "Event_ID,Sequence,Timestamp,Dataset,Frame_Index" in csv_body
    assert "Critical: full detachment" in csv_body
    assert "89.5" in csv_body
    assert "-2450.0" in csv_body


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


# --------------------------------------------------------------------------
# regressions from the 2026-08-17 review
# --------------------------------------------------------------------------
def test_rate_limit_state_is_per_app_not_module_global(dataset, model):
    """The failed-attempt table used to be a module-level defaultdict.

    Every app built in one process therefore shared it: a test that exhausted the
    limit left the NEXT app pre-throttled, so this suite's result depended on the
    order its tests happened to run in, and two apps served from one process
    would have leaked throttle state across them. Measured before the fix: a
    freshly built app's very first request answered 429.
    """
    c1, _ = _gated_client(dataset, key="key-app-one")
    for _ in range(11):
        c1.get("/api/v6/health?key=wrong")
    assert c1.get("/api/v6/health?key=wrong").status_code == 429

    c2, key2 = _gated_client(dataset, key="key-app-two")
    first = c2.get("/api/v6/health?key=wrong")
    assert first.status_code == 401, \
        f"a fresh app inherited throttle state from another app ({first.status_code})"
    assert c2.get(f"/api/v6/health?key={key2}").status_code == 200


def test_websocket_auth_is_rate_limited_too(dataset, model):
    """The socket skipped the throttle entirely, so the key was brute-forceable
    at full speed through the one route that opens a serial port on the host."""
    c, key = _gated_client(dataset)
    refused = 0
    for _ in range(12):
        try:
            with c.websocket_connect("/ws/live_sensor?source=replay&key=wrong"):
                pass
        except Exception:
            refused += 1
    assert refused == 12, "unauthenticated sockets were accepted"
    # The shared table means the HTTP gate has now seen those failures.
    assert c.get("/api/v6/health?key=wrong").status_code == 429, \
        "WebSocket auth failures are not counted against the rate limit"


def test_client_ingest_classifies_server_side(client):
    """?source=client must accept frames and answer with a classified payload.

    main.py contained no ws.receive_* call at all, and any unrecognised source=
    fell through to the CSV replay branch - so stream_to_cloud.py, which sends
    {"raw_frame": [...]}, streamed real sensor data to a server that discarded
    every message and replayed a canned recording back at it. web_serial.js
    worked around the same gap by reimplementing the classifier in JavaScript.
    """
    with client.websocket_connect("/ws/live_sensor?source=client") as ws:
        hello = ws.receive_json()
        assert hello["event"] == "started" and hello["source"] == "client"

        quiet = [28000.0] * M.N_PADS
        out = None
        for _ in range(M.KALMAN_WARMUP + 2):
            ws.send_json({"raw_frame": quiet})
            out = ws.receive_json()
        assert out is not None
        for key in ("severity_level", "cpri_percent", "probabilities", "deltas",
                    "propagation", "raw_level"):
            assert key in out, f"ingest reply is missing {key}"
        assert abs(sum(out["probabilities"]) - 1.0) < 1e-6
        assert out["severity_level"] == 0, "a flat baseline must not annunciate"

        # Malformed frames are rejected, not silently repaired.
        ws.send_json({"raw_frame": [1.0, 2.0]})
        assert "error" in ws.receive_json()
        ws.send_json({"raw_frame": ["x"] * M.N_PADS})
        assert "error" in ws.receive_json()

        ws.send_json({"event": "stop"})
        assert ws.receive_json()["event"] == "finished"


def test_rejected_upload_never_deletes_existing_files(client, isolated_data_root):
    """Quota eviction used to run BEFORE the size check.

    Measured: against a full Custom_Uploads/, one oversized POST returned a
    correct 413 and destroyed seven existing recordings on its way out. Nothing
    may be deleted for an upload that is not accepted.
    """
    custom = os.path.join(M.DATA_ROOT, "Custom_Uploads")
    os.makedirs(custom, exist_ok=True)
    header = ",".join(f"Sensor-{i+1}" for i in range(25)) + "\n"
    row = ",".join(["28000.0"] * 25) + "\n"
    good = (header + row * 10).encode()

    for i in range(M.MAX_CUSTOM_UPLOADS):
        with open(os.path.join(custom, f"keep_{i:03d}.csv"), "wb") as fh:
            fh.write(good)
    before = sorted(os.listdir(custom))

    oversized = (header + row * 400000).encode()
    assert len(oversized) > M.MAX_UPLOAD_BYTES
    res = client.post("/api/v6/upload-csv",
                      files={"file": ("huge.csv", oversized, "text/csv")})
    assert res.status_code == 413
    assert sorted(os.listdir(custom)) == before, \
        "a rejected upload deleted existing recordings"

    # A non-CSV and an invalid CSV must be just as harmless.
    client.post("/api/v6/upload-csv", files={"file": ("x.txt", b"hi", "text/plain")})
    client.post("/api/v6/upload-csv", files={"file": ("bad.csv", b"a,b\n1,2\n", "text/csv")})
    assert sorted(os.listdir(custom)) == before

    # A VALID upload at the cap is allowed to evict exactly one, the oldest.
    res_ok = client.post("/api/v6/upload-csv",
                         files={"file": ("fresh.csv", good, "text/csv")})
    assert res_ok.status_code == 200
    after = os.listdir(custom)
    assert len(after) == M.MAX_CUSTOM_UPLOADS and "fresh.csv" in after


def test_audit_trail_is_never_silently_truncated(client, clean_event_log):
    """A corrupt trail must fail loudly, not be replaced by one event.

    Measured before the fix: one unparseable byte plus one POST took a 23-event
    trail down to 1, answered 200 "recorded", and restarted event_id at EVT-0001
    so the new ids collided with the destroyed ones.
    """
    payload = {"dataset": "Peel/A_Peel_01.csv", "frame_index": 3, "time_sec": 1.68,
               "severity_level": 2, "cpri_percent": 61.0, "min_delta": -900.0}
    for _ in range(3):
        assert client.post("/api/v6/event-log", json=payload).status_code == 200
    assert client.get("/api/v6/event-log").json()["total_events"] == 3

    with open(clean_event_log, "w", encoding="utf-8") as fh:
        fh.write("{not json")

    assert client.get("/api/v6/event-log").status_code == 500
    post = client.post("/api/v6/event-log", json=payload)
    assert post.status_code == 500, "a corrupt trail was silently replaced"
    assert "NOT" in post.json()["detail"]

    # The unreadable file is preserved rather than overwritten.
    assert glob.glob(clean_event_log + ".corrupt-*"), "the corrupt trail was not kept"
    for stray in glob.glob(clean_event_log + ".corrupt-*"):
        os.remove(stray)


def test_event_ids_are_unique_across_a_truncation(client, clean_event_log):
    """event_id was f"EVT-{len(logs)+1:04d}", so it restarted at 1 whenever the
    trail got shorter - duplicate identifiers for different events."""
    payload = {"dataset": "d", "frame_index": 1, "time_sec": 0.5,
               "severity_level": 2, "cpri_percent": 50.0, "min_delta": -800.0}
    ids = set()
    for _ in range(5):
        ids.add(client.post("/api/v6/event-log", json=payload).json()["event"]["event_id"])
    assert len(ids) == 5

    # Shorten the trail by hand, the way a partial restore would.
    with open(clean_event_log, "w", encoding="utf-8") as fh:
        json.dump([], fh)
    for _ in range(3):
        ids.add(client.post("/api/v6/event-log", json=payload).json()["event"]["event_id"])
    assert len(ids) == 8, "event ids collided after the trail was shortened"


def test_datasets_endpoint_exposes_the_whole_corpus(client, dataset):
    """It walked only Custom_Uploads/ for a while, which hid all 81 recordings
    from the dashboard AND silently disarmed
    test_dataset_analysis_applies_the_debouncer, whose 'normals' list is built by
    filtering this response by class folder."""
    names = client.get("/api/v5/datasets").json()["datasets"]
    folders = {n.split("/")[0] for n in names}
    assert len(folders) > 1, f"only {folders} visible - is this walking all of Data/?"
    for expected in ("N_base", "Peel"):
        assert any(n.startswith(expected + "/") for n in names), \
            f"{expected}/ recordings are invisible to the dashboard"
    assert not any("research_plots" in n for n in names)
    assert len(names) >= dataset.n_files


def test_the_two_serving_paths_agree(client, sample_csv, model):
    """LIVE and REVIEW must not disagree about the same recording.

    They did: with the rule cascade in LivePipeline and the model argmax in the
    REST view, Peel/A_Peel_01.csv reported Level 3 through the socket and Level 2
    through REST. Both now call classify_deltas().
    """
    rest = client.get(f"/api/v5/dataset/{_enc(sample_csv)}").json()["frames"]
    url = (f"/ws/live_sensor?source=replay"
           f"&file={urllib.parse.quote(sample_csv)}&realtime=0")
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["event"] == "started"
        live = []
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "finished":
                break
            live.append(msg)

    assert len(live) == len(rest)
    # The REST view calibrates the whole file at once and the socket runs an
    # incremental Kalman, so per-frame deltas legitimately differ. The verdict
    # must not: the worst level either path reaches has to match.
    assert max(f["severity_level"] for f in live) == max(f["severity_level"] for f in rest), \
        "the live socket and the REST view disagree on the severity of one recording"
