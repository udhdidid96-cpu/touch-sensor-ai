"""/api/v6/notify/line: refuses what it must refuse without touching the network."""
import re

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
