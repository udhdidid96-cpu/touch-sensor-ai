"""/api/v6/notify/line: refuses what it must refuse without touching the network."""
import contextlib
import http.server
import json
import re
import threading
import types
import urllib.error
import urllib.request

import pytest

import main as M


@pytest.mark.parametrize("url", ["http://example.com/hook", "https://127.0.0.1/hook", "https://localhost/hook",
                                 "https://10.1.2.3/hook", "https://169.254.169.254/latest/meta-data", "ftp://example.com"])
def test_webhook_to_a_private_or_plain_http_target_is_refused(client, url):
    r = client.post("/api/v6/notify/line", json={"message": "test", "webhook_url": url})
    assert r.status_code == 400 and "webhook_url rejected" in r.json()["detail"]


def test_message_and_a_credential_are_required(client):
    assert client.post("/api/v6/notify/line", json={"token": "x"}).status_code == 400
    assert client.post("/api/v6/notify/line", json={"message": "x"}).status_code == 400


def test_line_notify_is_gone_and_alerts_carry_no_patient_identity(client):
    src = M.__loader__.get_source(M.__name__)
    assert "notify-api.line.me" not in src, "LINE Notify was shut down on 2025-03-31"
    js = client.get("/static/app.js").text
    body = js[js.index("async function dispatchLineNotification"):]
    body = body[:body.index("\n}\n")]
    assert not re.search(r"patient_(name|id)", body), "a push message must not carry a patient name or number"


class _Outbox:
    """Stands in for main._PUSH_OPENER: records each request, never touches the network."""

    def __init__(self):
        self.sent = []
        self.fail = False

    def open(self, req, timeout):
        self.sent.append((req, timeout))
        if self.fail:
            raise urllib.error.URLError("offline")
        return contextlib.nullcontext(types.SimpleNamespace(getcode=lambda: 200))


@pytest.fixture
def outbox(monkeypatch):
    box = _Outbox()
    monkeypatch.setattr(M, "_PUSH_OPENER", box)
    monkeypatch.setattr(M.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("1.1.1.1", 443))])
    return box


IDENTITY = {"patient_id": "must-not-leave", "patient_name": "must-not-leave", "hn": "must-not-leave"}


def test_line_push_is_a_bearer_broadcast_with_the_text_only(client, outbox):
    r = client.post("/api/v6/notify/line", json={"token": "tok", "message": "Bed 01 L3", "level": 3,
                                                 "bed": "privacy-line", "cpri_percent": 81.2, **IDENTITY})
    assert r.json()["ok"]
    req, timeout = outbox.sent[-1]
    assert req.full_url == M.LINE_BROADCAST_URL and req.get_header("Authorization") == "Bearer tok"
    assert timeout == M.LINE_TIMEOUT_S
    assert json.loads(req.data) == {"messages": [{"type": "text", "text": "Bed 01 L3"}]}


def test_webhook_payload_is_an_allowlist_without_identity(client, outbox):
    r = client.post("/api/v6/notify/line", json={"webhook_url": "https://relay.example/hook", "message": "L3",
                                                 "level": 3, "bed": "privacy-hook", "cpri_percent": 81.2, **IDENTITY})
    assert r.json()["ok"]
    sent = json.loads(outbox.sent[-1][0].data)
    assert set(sent) == {"message", "level", "bed", "cpri_percent", "timestamp", "source"}
    assert sent["cpri_percent"] == 81.2 and "must-not-leave" not in json.dumps(sent)


def test_cooldown_per_bed_with_escalation_and_test_alerts_exempt(client, outbox):
    def push(bed, level):
        return client.post("/api/v6/notify/line", json={"token": "t", "message": "m", "level": level,
                                                        "bed": bed}).json()["status"]
    assert push("cool-A", 2) == "sent"
    assert push("cool-A", 2) == "throttled"
    assert push("cool-A", 3) == "sent", "an escalation must never wait out the cooldown"
    assert push("cool-A", 2) == "throttled"
    assert push("cool-B", 2) == "sent", "the cooldown is per bed"
    assert push("cool-A", 0) == push("cool-A", 0) == "sent", "Test Alert is never throttled"
    outbox.fail = True
    assert push("cool-C", 2) == "error"
    outbox.fail = False
    assert push("cool-C", 2) == "sent", "a failed push must not start the cooldown"


def test_level_and_metric_must_be_numbers(client):
    r = client.post("/api/v6/notify/line", json={"token": "t", "message": "m", "level": "high"})
    assert r.status_code == 400


def test_push_opener_refuses_redirects():
    hits = []

    class Hop(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
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
