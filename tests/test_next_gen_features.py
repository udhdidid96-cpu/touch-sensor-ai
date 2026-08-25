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
