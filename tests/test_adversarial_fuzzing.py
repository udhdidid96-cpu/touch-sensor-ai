"""Feature F13: Adversarial Ingestion Fuzzing Suite.

Automated 1,000+ malformed, non-finite, extreme spike (>50k counts), and negative
count frames stress test suite against:
  1. LivePipeline in raw counts mode (F2 Bounds & Spike Filtering)
  2. LivePipeline in CDC mode (Unit detection & Open/Short guards)
  3. WebSocket `/ws/live_sensor?source=client` (F1 JSON resilience)
  4. SerialFrameSource (F8 Line length, token bounds, and non-numeric safety)

Verifies zero unhandled exceptions and zero Kalman filter state poisoning.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List

import numpy as np
import pytest

from main import (
    LivePipeline,
    N_PADS,
    BASELINE_COUNTS,
    SerialFrameSource,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def _generate_adversarial_frames(n_frames: int = 1050) -> list[np.ndarray]:
    """Generate 1,000+ structured adversarial and malformed frames."""
    rng = np.random.RandomState(42)
    frames: list[np.ndarray] = []

    for i in range(n_frames):
        if i < 100:
            f = np.full(N_PADS, BASELINE_COUNTS, dtype=float)
            nan_count = rng.randint(1, N_PADS + 1)
            nan_indices = rng.choice(N_PADS, size=nan_count, replace=False)
            f[nan_indices] = np.nan
        elif i < 200:
            f = np.full(N_PADS, BASELINE_COUNTS, dtype=float)
            inf_mask = rng.choice([True, False], size=N_PADS, p=[0.3, 0.7])
            signs = rng.choice([1.0, -1.0], size=N_PADS)
            f[inf_mask] = signs[inf_mask] * np.inf
        elif i < 300:
            f = np.full(N_PADS, BASELINE_COUNTS, dtype=float)
            subnormals = rng.choice([1e-308, -1e-308, 1e-300, -1e-300, 1e300], size=N_PADS)
            mask = rng.choice([True, False], size=N_PADS, p=[0.4, 0.6])
            f[mask] = subnormals[mask]
        elif i < 400:
            f = np.full(N_PADS, BASELINE_COUNTS, dtype=float)
            spike_channels = rng.choice(N_PADS, size=rng.randint(1, 5), replace=False)
            spike_values = rng.uniform(50001.0, 1000000.0, size=len(spike_channels))
            f[spike_channels] = spike_values
        elif i < 500:
            f = np.full(N_PADS, BASELINE_COUNTS, dtype=float)
            neg_channels = rng.choice(N_PADS, size=rng.randint(1, 10), replace=False)
            neg_values = rng.uniform(-65535.0, -0.01, size=len(neg_channels))
            f[neg_channels] = neg_values
        elif i < 600:
            boundary_pool = np.array([-32768.0, -1.0, 0.0, 32767.0, 65535.0, 100000.0])
            f = rng.choice(boundary_pool, size=N_PADS)
        elif i < 700:
            sign = 1.0 if (i % 2 == 0) else -1.0
            f = np.full(N_PADS, sign * 40000.0)
        elif i < 800:
            if i % 2 == 0:
                f = np.zeros(N_PADS, dtype=float)
            else:
                f = np.zeros(N_PADS, dtype=float)
                f[rng.randint(0, N_PADS)] = 65535.0
        elif i < 900:
            f = np.zeros(N_PADS, dtype=float)
            ch = rng.randint(0, N_PADS)
            f[ch] = rng.choice([np.nan, -500.0, 60000.0, -np.inf])
        else:
            f = rng.choice(
                [BASELINE_COUNTS, np.nan, np.inf, -np.inf, -1000.0, 0.0, 55000.0, 999999.0, 1e-10],
                size=N_PADS,
                p=[0.3, 0.1, 0.05, 0.05, 0.1, 0.1, 0.1, 0.1, 0.1]
            )

        frames.append(f)

    return frames


def test_live_pipeline_survives_1000_adversarial_frames():
    """F13: Verify LivePipeline processes 1,000+ malformed frames with zero crashes
    and that the Kalman filter baseline state is not poisoned or corrupted.
    """
    pipe = LivePipeline(model=None, warmup_frames=3)

    for _ in range(5):
        out = pipe.process(np.full(N_PADS, BASELINE_COUNTS))
        assert not out.get("disconnected", False)

    adversarial_frames = _generate_adversarial_frames(1050)
    assert len(adversarial_frames) >= 1000

    processed_count = 0
    for idx, bad_frame in enumerate(adversarial_frames):
        try:
            out = pipe.process(bad_frame)
            processed_count += 1
        except Exception as exc:
            pytest.fail(f"LivePipeline crashed on adversarial frame {idx}: {exc}")

        assert isinstance(out, dict), f"Frame {idx} output is not a dict"
        assert "severity_level" in out
        assert "deltas" in out
        assert out.get("disconnected", False) in (True, False)
        assert len(out["deltas"]) == N_PADS

    assert processed_count == len(adversarial_frames)

    rec_out = {}
    for _ in range(10):
        rec_out = pipe.process(np.full(N_PADS, BASELINE_COUNTS))

    assert pipe.kalman.b is not None
    assert np.all(np.isfinite(pipe.kalman.b)), "Kalman baseline contains non-finite values after fuzzing"
    assert np.all(pipe.kalman.b > 20000.0), f"Kalman baseline underflowed: {pipe.kalman.b.min()}"
    assert np.all(pipe.kalman.b < 40000.0), f"Kalman baseline overflowed: {pipe.kalman.b.max()}"

    assert not rec_out.get("disconnected", False)
    assert np.all(np.abs(rec_out["deltas"]) < 100.0), (
        f"Deltas did not settle after fuzz recovery: {rec_out['deltas']}"
    )


def test_live_pipeline_single_pad_extreme_surge_is_filtered():
    """F2/F13: Verify extreme electrical surge (>50k) on single pad is filtered
    and does not trigger a false Level 2/3 alarm or poison baseline.
    """
    pipe = LivePipeline(model=None, warmup_frames=3)
    for _ in range(5):
        pipe.process(np.full(N_PADS, BASELINE_COUNTS))

    surge_frame = np.full(N_PADS, BASELINE_COUNTS)
    surge_frame[12] = 80000.0

    out = pipe.process(surge_frame)
    assert out["severity_level"] < 2, f"Spike triggered false alarm level {out['severity_level']}"
    assert pipe.kalman.b is not None
    assert pipe.kalman.b[12] < 35000.0, f"Pad 12 baseline corrupted by surge: {pipe.kalman.b[12]}"


def test_live_pipeline_cdc_mode_adversarial_fuzzing():
    """F13: Verify CDC mode survives extreme pF values, opens (<1pF) and shorts (>500pF)."""
    pipe = LivePipeline(model=None, warmup_frames=3, cdc_mode=True)

    for _ in range(5):
        out = pipe.process(np.full(N_PADS, 30.0))
        assert not out.get("disconnected", False)
        assert out["mode"] == "cdc"

    out_open = pipe.process(np.full(N_PADS, 0.4))
    assert out_open["disconnected"] is True

    out_short = pipe.process(np.full(N_PADS, 550.0))
    assert out_short["disconnected"] is True

    out_neg = pipe.process(np.array([-5.0] + [30.0] * 24))
    assert out_neg["disconnected"] is True

    out_nan = pipe.process(np.array([np.nan] * N_PADS))
    assert out_nan["disconnected"] is True

    out_rec = {}
    for _ in range(10):
        out_rec = pipe.process(np.full(N_PADS, 30.0))

    assert not out_rec.get("disconnected", False)
    assert pipe.kalman.b is not None
    assert np.all(np.isfinite(pipe.kalman.b))


def test_websocket_malformed_json_and_fuzzing(client: TestClient):
    """F1/F13: WebSocket /ws/live_sensor?source=client handles corrupt JSON and bad payloads without crashing."""
    with client.websocket_connect("/ws/live_sensor?source=client") as ws:
        welcome = ws.receive_json()
        assert welcome.get("event") == "started"

        ws.send_json(["not", "a", "dict"])
        res1 = ws.receive_json()
        assert "error" in res1

        ws.send_json({"foo": "bar"})
        res2 = ws.receive_json()
        assert "error" in res2

        ws.send_json({"raw_frame": [28000.0] * 10})
        res3 = ws.receive_json()
        assert "error" in res3

        ws.send_json({"raw_frame": ["corrupt"] * 25})
        res4 = ws.receive_json()
        assert "error" in res4

        ws.send_json({"raw_frame": [None] * 25})
        res5 = ws.receive_json()
        assert "error" in res5

        ws.send_text("THIS IS NOT VALID JSON {[[{")
        res6 = ws.receive_json()
        assert "error" in res6

        ws.send_json({"raw_frame": [28000.0] * 25})
        res7 = ws.receive_json()
        assert "severity_level" in res7
        assert "deltas" in res7

        ws.send_json({"event": "stop"})


def test_serial_frame_source_adversarial_lines():
    """F8/F13: Verify SerialFrameSource drops malformed lines, framing noise,
    and bounded lengths without throwing unhandled exceptions.
    """
    class MockPort:
        def __init__(self, lines: List[bytes]) -> None:
            self._lines = list(lines)
            self.closed = False

        def readline(self) -> bytes:
            return self._lines.pop(0) if self._lines else b""

        def close(self) -> None:
            self.closed = True

    corrupt_chars = b"28000,28001,GARBAGE_TOKEN,28003\r\n"
    short_line = b"28000,28001,28002\r\n"
    nan_line = (",".join(["nan"] * 25) + "\r\n").encode()
    valid_line = (",".join(["28000"] * 25) + "\r\n").encode()

    src = SerialFrameSource("mock", permute=False,
                            ser=MockPort([corrupt_chars, short_line, nan_line, valid_line]))
    src.IDLE_TIMEOUT_S = 0.15
    src.EMPTY_READ_SLEEP_S = 0.001

    frames = list(src.frames())
    assert len(frames) == 1
    assert frames[0].shape == (N_PADS,)
    assert np.allclose(frames[0], 28000.0)
