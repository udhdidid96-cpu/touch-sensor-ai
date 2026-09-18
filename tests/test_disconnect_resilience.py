"""Feature F14: Disconnect Resilience & Burst Recovery Suite.

Tests:
  1. 50-cycle high-frequency disconnect/reconnect bursts
  2. Clean sub-1.5s disconnect transitions without thread starvation or race conditions
  3. Zero false Level 2/3 alarms triggered during disconnect and reconnection transients
  4. Alarm level hold preservation during disconnects (a severed cable during an event holds alarm)
"""
from __future__ import annotations

import time
import numpy as np
import pytest

import main as M
from main import (
    LivePipeline,
    N_PADS,
    BASELINE_COUNTS,
    SAMPLE_PERIOD_S,
    SerialFrameSource,
)


def test_50_cycle_disconnect_reconnect_bursts():
    """F14: 50-cycle high-frequency disconnect/reconnect bursts transition cleanly

    without race conditions, thread starvation, or false Level 2/3 alarms.
    """
    pipe = LivePipeline(model=None, warmup_frames=3)

    for cycle in range(50):
        # 1. Active resting frames (3 frames at baseline)
        for _ in range(3):
            out = pipe.process(np.full(N_PADS, BASELINE_COUNTS))
            assert not out.get("disconnected", False), f"Cycle {cycle}: active frame marked disconnected"
            assert out["severity_level"] < 2, f"Cycle {cycle}: false alarm on active frame"

        # 2. Single dropped frame (0 ct) -> must flag disconnected but NOT reseed yet
        drop_out = pipe.process(np.zeros(N_PADS))
        assert drop_out["disconnected"] is True
        assert drop_out["severity_level"] < 2, f"Cycle {cycle}: false alarm on single glitch"

        # 3. 10 severed frames (0 ct) -> complete disconnect run
        for _ in range(10):
            disc_out = pipe.process(np.zeros(N_PADS))
            assert disc_out["disconnected"] is True
            assert disc_out["severity_level"] < 2, f"Cycle {cycle}: false alarm during disconnect run"

        # 4. Fresh reconnected patch at slightly different baseline (+300 counts)
        # Must trigger re-seed because disconnected_run >= RESEED_AFTER_LOST_FRAMES (10)
        fresh_baseline = BASELINE_COUNTS + (cycle % 5) * 50.0
        reconnect_out = pipe.process(np.full(N_PADS, fresh_baseline))
        assert not reconnect_out.get("disconnected", False), f"Cycle {cycle}: reconnect frame failed"
        assert reconnect_out["severity_level"] < 2, f"Cycle {cycle}: false alarm on reconnect"
        assert np.all(np.abs(reconnect_out["deltas"]) < 50.0), (
            f"Cycle {cycle}: baseline was not re-taken on reconnect! deltas: {reconnect_out['deltas'][:5]}"
        )


def test_sub_1_5s_serial_disconnect_transition():
    """F4/F14: A quiet or severed serial connection transitions within 1.5 seconds."""
    class QuietPort:
        def readline(self):
            # Simulates an unplugged/silent COM port
            time.sleep(0.02)
            return b""

        def close(self):
            pass

    src = SerialFrameSource.__new__(SerialFrameSource)
    src._ser = QuietPort()
    src._stop = __import__("threading").Event()
    # SerialFrameSource.IDLE_TIMEOUT_S is 1.2s, guaranteed < 1.5s
    src.IDLE_TIMEOUT_S = 1.2
    src.EMPTY_READ_SLEEP_S = 0.01

    t0 = time.monotonic()
    frames = list(src.frames())
    elapsed = time.monotonic() - t0

    assert len(frames) == 0
    # Must exit in >= 1.2s and strictly < 1.5s
    assert 1.15 <= elapsed < 1.50, f"Disconnect transition took {elapsed:.3f}s; expected < 1.5s"


def test_immediate_live_pipeline_disconnect_detection():
    """F14: LivePipeline flags disconnected: True immediately on frame 0 of silence."""
    pipe = LivePipeline(model=None, warmup_frames=3)
    pipe.process(np.full(N_PADS, BASELINE_COUNTS))

    # Cable severed -> next frame is 0s
    t0 = time.monotonic()
    out = pipe.process(np.zeros(N_PADS))
    elapsed = time.monotonic() - t0

    assert out["disconnected"] is True
    assert elapsed < 0.05, f"LivePipeline disconnect detection took {elapsed:.3f}s"
    assert "Sensor disconnected" in out["status"]


def test_disconnect_preserves_alarm_hold_mid_event():
    """F14: If a cable is knocked loose during an active pull event, the debouncer

    holds its alarm level rather than dropping immediately to Level 0 (benign).
    """
    pipe = LivePipeline(model=None, warmup_frames=1)
    # Seed
    pipe.process(np.full(N_PADS, BASELINE_COUNTS))

    # Manually simulate debouncer at Level 3 (siren active)
    pipe.alarm.level = 3

    # Disconnect occurs
    disc_frame = pipe.process(np.zeros(N_PADS))
    assert disc_frame["disconnected"] is True
    # Held level must be reported so nurses know detachment was in progress
    assert disc_frame["severity_level"] == 3

    # After full lost run (10 frames), reseed clears state
    for _ in range(pipe.RESEED_AFTER_LOST_FRAMES):
        pipe.process(np.zeros(N_PADS))

    # Fresh patch attached
    fresh = pipe.process(np.full(N_PADS, BASELINE_COUNTS))
    assert fresh["severity_level"] == 0
