"""Serial framing resilience, checked against the JavaScript that ships.

There is no JS runtime in this suite, so these tests read web/web_serial.js and
check the properties that were actually wrong, not a transcription of the logic
into Python - a rewritten copy would pass while the shipped file stayed broken.

Two defects are pinned:

  * the overflow guard used buffer.slice(-4096), an arbitrary byte offset that
    lands mid-line. A link emitting no delimiters (wedged, wrong baud) then kept
    4,096 chars of garbage forever, and when real frames resumed the garbage was
    still glued to the first of them. The guard must cut at a frame boundary.
  * the client watchdog fired at 1000 ms while the server's own
    SerialFrameSource.IDLE_TIMEOUT_S is 1.2 s, so the page declared a stream
    frozen while the server still believed it live. The client must be the
    slower of the two.
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import main as M  # noqa: E402

WEB_SERIAL = os.path.join(ROOT, "web", "web_serial.js")
BRIDGE = os.path.join(ROOT, "stream_to_cloud.py")


def _js():
    with open(WEB_SERIAL, encoding="utf-8") as fh:
        return fh.read()


def _watchdog_ms():
    m = re.search(r"const\s+SERIAL_WATCHDOG_MS\s*=\s*(\d+)", _js())
    assert m, "SERIAL_WATCHDOG_MS not found in web/web_serial.js"
    return int(m.group(1))


def _server_idle_timeout_s():
    for name in ("SerialFrameSource",):
        src = getattr(M, name, None)
        if src is not None and hasattr(src, "IDLE_TIMEOUT_S"):
            return float(src.IDLE_TIMEOUT_S)
    return None


def _overflow_guard():
    """The guard body only - comments explaining the old behaviour mention it."""
    js = _js()
    start = js.index("if (buffer.length > 4096)")
    return js[start:js.index("const lines = buffer.split", start)]


def test_overflow_resyncs_to_a_frame_boundary_not_a_byte_offset():
    guard = _overflow_guard()
    assert "buffer.slice(-4096)" not in guard, (
        "the overflow guard is back to slicing at a byte offset; it must cut at "
        "the last newline so the buffer restarts on a real frame boundary")
    assert r"lastIndexOf('\n')" in guard, (
        "no newline resynchronisation found in the overflow guard")


def test_a_buffer_with_no_delimiter_at_all_is_discarded():
    """Garbage with no frame boundary has no boundary worth keeping. Anything
    else leaves it glued to the next valid frame."""
    guard = _overflow_guard()
    assert "lastBreak >= 0 ? buffer.slice(lastBreak + 1) : ''" in guard, guard


def test_client_watchdog_is_slower_than_the_server_idle_timeout():
    ms = _watchdog_ms()
    idle = _server_idle_timeout_s()
    if idle is None:
        pytest.skip("SerialFrameSource.IDLE_TIMEOUT_S not exposed")
    assert ms / 1000.0 > idle, (
        f"client watchdog {ms} ms is not slower than the server's {idle * 1000:.0f} ms "
        f"idle timeout; the page would declare a dropout the server has not seen")


def test_client_watchdog_still_trips_within_three_frame_periods():
    """Slower than the server, but not so slow that a stale screen looks live."""
    ms = _watchdog_ms()
    assert ms <= 3 * M.SAMPLE_PERIOD_S * 1000.0, (
        f"watchdog {ms} ms is more than three frame periods")


def test_the_watchdog_warns_and_does_not_tear_the_session_down():
    """A dropout is not evidence that the patient is fine. The last known state
    stays on screen and the server's debouncer keeps the level."""
    js = _js()
    start = js.index("function resetSerialWatchdog")
    body = js[start:js.index("function stopSerialWatchdog", start)]
    assert "setStreamFrozen(true)" in body
    assert "disconnectWebSerial" not in body, (
        "the watchdog tears the session down; it is a warning, not a disconnect")


def test_the_bridge_watchdog_matches_the_browser_one():
    with open(BRIDGE, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"SERIAL_WATCHDOG_S\s*=\s*([\d.]+)", src)
    assert m, "stream_to_cloud.py has no watchdog"
    assert float(m.group(1)) * 1000.0 == _watchdog_ms(), (
        "the two bridges disagree about when the link is down")


def test_the_bridge_read_timeout_is_shorter_than_its_watchdog():
    """readline() must return before the deadline or the watchdog never fires."""
    with open(BRIDGE, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"serial\.Serial\([^)]*timeout=([\d.]+)", src)
    assert m, "no serial read timeout found"
    w = re.search(r"SERIAL_WATCHDOG_S\s*=\s*([\d.]+)", src)
    assert float(m.group(1)) < float(w.group(1))


def test_the_bridge_does_not_send_while_the_link_is_down():
    """Silence is not a patient event. Nothing is fabricated to fill the gap."""
    with open(BRIDGE, encoding="utf-8") as fh:
        src = fh.read()
    start = src.index("if not line or line.startswith")
    watchdog = src[start:src.index("last_frame_at = time.time()", start)]
    assert "continue" in watchdog, watchdog
    assert "ws.send" not in watchdog, "the bridge sends something on a silent port"
