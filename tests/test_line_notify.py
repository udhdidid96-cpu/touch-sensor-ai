"""LINE alerts: refusals, escalation, delivery and privacy, all without touching the network."""
import contextlib
import http.server
import io
import json
import os
import re
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request

import pytest

import main as M

# Identity a push must never carry: hospital/medical record numbers, patient id or
# name fields, and long digit runs (an HN is a 6+ digit number in every format seen).
IDENTITY_RE = re.compile(r"(?i)\b(hn|mrn)\b|patient[ _-]?(id|name)|\b\d{6,}\b")
IDENTITY = {"patient_id": "must-not-leave", "patient_name": "must-not-leave", "hn": "must-not-leave"}


@pytest.mark.parametrize("url", ["http://example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook",
                                 "https://10.1.2.3/hook", "https://169.254.169.254/latest/meta-data",
                                 "ftp://example.com"])
def test_webhook_to_a_private_or_plain_http_target_is_refused(client, url):
    r = client.post("/api/v6/notify/line", json={"message": "test", "webhook_url": url})
    assert r.status_code == 400 and "webhook_url rejected" in r.json()["detail"]
    r = client.post("/api/v6/alerts/line/config", json={"enabled": True, "webhook_url": url})
    assert r.status_code == 400


def test_message_and_a_credential_are_required(client):
    assert client.post("/api/v6/notify/line", json={"token": "x"}).status_code == 400
    assert client.post("/api/v6/notify/line", json={"message": "x"}).status_code == 400


def test_level_and_metric_must_be_numbers(client):
    r = client.post("/api/v6/notify/line", json={"token": "t", "message": "m", "level": "high"})
    assert r.status_code == 400


def test_line_notify_is_gone_and_the_console_never_pages_by_itself(client):
    src = M.__loader__.get_source(M.__name__)
    assert "notify-api.line.me" not in src, "LINE Notify was shut down on 2025-03-31"
    js = client.get("/static/app.js").text
    assert js.count("/api/v6/notify/line") == 1, (
        "only the Test Alert button may post a push from the browser; alarms come from "
        "the server pipeline, or the same event goes out twice")


class _Gateway:
    """Stands in for main._PUSH_OPENER. `codes` are answered in order (last one repeats)."""

    def __init__(self):
        self.sent = []
        self.codes = [200]
        self.delay = 0.0

    def open(self, req, timeout):
        self.sent.append((req, timeout))
        if self.delay:
            time.sleep(self.delay)
        code = self.codes[min(len(self.sent), len(self.codes)) - 1]
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "err", None,
                                         io.BytesIO(b'{"message":"Authentication failed"}'))
        return contextlib.nullcontext(types.SimpleNamespace(getcode=lambda: code))


@pytest.fixture
def gateway(monkeypatch):
    gw = _Gateway()
    monkeypatch.setattr(M, "_PUSH_OPENER", gw)
    monkeypatch.setattr(M, "LINE_ALERTS", M.LineAlerter())
    monkeypatch.setattr(M, "LINE_BACKOFF_S", 0.0)
    monkeypatch.setattr(M.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("1.1.1.1", 443))])
    return gw


def _frame(level, cpri=81.2):
    deltas = [-812.0 if i < 7 else -20.0 for i in range(M.N_PADS)]
    return {"severity_level": level, "cpri_percent": cpri, "deltas": deltas, "warming_up": False,
            "propagation": {"n_lifting_pads": 7}}


def test_line_push_is_a_bearer_broadcast_with_the_text_only(client, gateway):
    r = client.post("/api/v6/notify/line", json={"token": "tok", "message": "Bed 01 test", "level": 0,
                                                 "bed": "Bed 01", "cpri_percent": 81.2, **IDENTITY})
    assert r.json()["ok"] and r.json()["latency_ms"] >= 0
    req, timeout = gateway.sent[-1]
    assert req.full_url == M.LINE_BROADCAST_URL and req.get_header("Authorization") == "Bearer tok"
    assert timeout == M.LINE_TIMEOUT_S == 3.5
    assert json.loads(req.data) == {"messages": [{"type": "text", "text": "Bed 01 test"}]}


def test_webhook_payload_is_an_allowlist_without_identity(client, gateway):
    r = client.post("/api/v6/notify/line", json={"webhook_url": "https://relay.example/hook", "message": "L3",
                                                 "level": 3, "bed": "privacy-hook", "cpri_percent": 81.2, **IDENTITY})
    assert r.json()["ok"]
    sent = json.loads(gateway.sent[-1][0].data)
    assert set(sent) == {"bed", "kind", "level", "cpri_percent", "message", "timestamp", "source"}
    assert sent["cpri_percent"] == 81.2 and "must-not-leave" not in json.dumps(sent)


def test_escalation_normal_warning_critical_stabilized():
    a = M.LineAlerter()
    script = [(0, 0, None), (1, 1, None), (2, 2, "warning"), (2, 30, None),
              (3, 31, "critical"), (3, 50, None), (3, 61, "critical"), (2, 70, None),
              (0, 80, None), (1, 85, None), (0, 86, None), (0, 100, None), (0, 101, "cleared"),
              (0, 200, None), (2, 201, "warning"), (2, 260, None), (2, 261, "warning")]
    got = [(lvl, t, a.decide("esc", lvl, t)) for lvl, t, _ in script]
    assert got == script, "L0/L1 silent, L2 then 60 s, L3 bypasses and repeats at 30 s, all-clear after 15 s of L0"


def test_rapid_frames_do_not_spam():
    a = M.LineAlerter()
    frames = [k * M.SAMPLE_PERIOD_S for k in range(200)]
    warn = [a.decide("spam-2", 2, t) for t in frames]
    crit = [a.decide("spam-3", 3, t) for t in frames]
    assert warn.count("warning") == 2, "200 L2 frames over 112 s: once, then once after 60 s"
    assert crit.count("critical") == 4, "200 L3 frames over 112 s: every 30 s"


def test_critical_only_mutes_warnings(gateway):
    a = M.LineAlerter("tok")
    a.min_level = 3
    assert a.observe(_frame(2), now=0) is None
    fut = a.observe(_frame(3), now=1)
    assert fut is not None and fut.result(timeout=5)["ok"]


def test_pipeline_push_never_blocks_the_frame_loop_and_carries_no_identity(gateway):
    gateway.delay = 0.5
    a = M.LineAlerter("tok", bed="Bed 01")
    t0 = time.monotonic()
    fut = a.observe(_frame(3), now=0)
    assert time.monotonic() - t0 < 0.05, "a slow gateway must not hold the frame"
    assert fut is not None and fut.result(timeout=5)["ok"]
    req, _ = gateway.sent[-1]
    assert req.full_url == M.LINE_BROADCAST_URL and req.get_header("Authorization") == "Bearer tok"
    text = json.loads(req.data)["messages"][0]["text"]
    for needle in ("Bed 01", "CPRI: 81.2%", "-812 counts", "7/25", "Immediate bedside verification required",
                   "レベル3", "ระดับ 3"):
        assert needle in text
    assert re.search(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", text), "ISO 8601 timestamp"
    assert not IDENTITY_RE.search(text)
    assert a.observe({**_frame(3), "warming_up": True}, now=100) is None


@pytest.mark.parametrize("kind", ["critical", "warning", "cleared"])
def test_every_message_kind_is_free_of_identity(kind):
    text = M.format_line_alert({"bed": "ICU Station A", "kind": kind, "level": 3, "cpri_percent": 81.2,
                                "max_delta": -812.0, "lifting_pads": 7})
    assert not IDENTITY_RE.search(text), text


def test_retries_back_off_on_5xx_and_stop_on_4xx_and_every_attempt_is_audited(gateway, monkeypatch):
    sleeps = []
    monkeypatch.setattr(M, "LINE_BACKOFF_S", 0.5)
    monkeypatch.setattr(M.time, "sleep", sleeps.append)
    a = M.LineAlerter("tok")
    fields = {"bed": "audit-bed", "kind": "critical", "level": 3}

    gateway.codes = [503, 503, 200]
    res = a.send("m", fields, "tok")
    assert res["ok"] and res["attempts"] == 3 and sleeps == [0.5, 1.0]

    gateway.sent, gateway.codes = [], [401]
    res = a.send("m", fields, "tok")
    assert not res["ok"] and res["attempts"] == 1 and res["code"] == 401
    assert a.status()["state"] == "error" and "401" in a.status()["detail"]

    with open(os.path.join(M.DATA_ROOT, M.LINE_AUDIT_FILE), encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh]
    assert [(r["ok"], r["http_status"], r["attempts"]) for r in records[-2:]] == [(True, 200, 3), (False, 401, 1)]
    assert all(r["latency_ms"] >= 0 for r in records[-2:])
    assert M.verify_audit_chain(records)["status"] == "intact"


def test_pipeline_and_route_share_one_idempotency_lock(client, gateway):
    M.LINE_ALERTS.configure(True, "tok", bed="Bed 07")
    fut = M.LINE_ALERTS.observe(_frame(3))
    assert fut is not None and fut.result(timeout=5)["ok"]
    r = client.post("/api/v6/notify/line", json={"token": "tok", "message": "dup", "level": 3, "bed": "Bed 07"})
    assert r.json()["status"] == "throttled" and len(gateway.sent) == 1


def test_config_verifies_the_token_and_never_echoes_it(client, gateway):
    bad = client.post("/api/v6/alerts/line/config", json={"enabled": True, "token": "t", "min_level": 5})
    assert bad.status_code == 400
    r = client.post("/api/v6/alerts/line/config",
                    json={"enabled": True, "token": "secret-token", "min_level": 3, "bed": "Bed 03"})
    assert r.status_code == 200 and r.json()["state"] == "connected"
    assert gateway.sent[-1][0].full_url == M.LINE_BOT_INFO_URL
    status = client.get("/api/v6/alerts/line/status")
    assert "secret-token" not in r.text + status.text
    assert status.json()["min_level"] == 3 and status.json()["bed"] == "Bed 03"
    assert client.post("/api/v6/alerts/line/config", json={"enabled": False}).json()["state"] == "disconnected"


def test_only_live_sources_page(client, monkeypatch, sample_csv):
    seen = []
    monkeypatch.setattr(M, "LINE_ALERTS", types.SimpleNamespace(observe=seen.append))
    url = f"/ws/live_sensor?source=replay&file={urllib.parse.quote(sample_csv)}&realtime=0"
    with client.websocket_connect(url) as ws:
        while ws.receive_json().get("event") != "finished":
            pass
    assert seen == [], "a replayed recording must never page a nurse"
    with client.websocket_connect("/ws/live_sensor?source=client") as ws:
        ws.receive_json()
        ws.send_json({"raw_frame": [28000.0] * M.N_PADS})
        ws.receive_json()
    assert len(seen) == 1, "browser serial is a live source"


def test_push_opener_refuses_redirects():
    hits = []

    class Hop(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                self.rfile.read(length)
            self.send_response(302)
            self.send_header("Location", "/latest/meta-data")
            self.send_header("Content-Length", "0")
            self.end_headers()
        do_GET = do_POST

        def log_message(self, *args):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Hop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert any(isinstance(h, M._NoRedirect) for h in M._PUSH_OPENER.handlers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), M._NoRedirect)
        with pytest.raises(urllib.error.HTTPError) as err:
            opener.open(urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/hook", data=b"{}"), timeout=5)
        assert err.value.code == 302 and hits == ["/hook"]
    finally:
        srv.shutdown()
        srv.server_close()
