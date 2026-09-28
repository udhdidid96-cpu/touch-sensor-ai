"""Frame-source and live-pipeline tests for main.py v6.2.

The v5.0 file this replaces drove `/api/v5/serial/connect` and a background
"LOOPBACK" thread that no longer exist. Real hardware is not available in CI,
so the serial parser is exercised against a fake port object instead of a real
one - which also lets us assert on the malformed lines a real UART produces.
"""
from __future__ import annotations

from typing import Iterable, List

import numpy as np
import pytest

import main as M


class FakePort:
    """The subset of serial.Serial that SerialFrameSource actually touches.

    Returning b"" is what pyserial does on a read timeout, so exhausting the
    scripted lines models a device that has gone quiet.
    """

    def __init__(self, lines: Iterable[bytes]) -> None:
        self._lines: List[bytes] = list(lines)
        self.closed = False
        self.reads = 0

    def readline(self) -> bytes:
        self.reads += 1
        return self._lines.pop(0) if self._lines else b""

    def close(self) -> None:
        self.closed = True


def _open(port: FakePort, idle_timeout: float = 0.15) -> M.SerialFrameSource:
    src = M.SerialFrameSource("fake", ser=port)
    src.IDLE_TIMEOUT_S = idle_timeout
    src.EMPTY_READ_SLEEP_S = 0.001
    return src


def _source(lines: Iterable[bytes], idle_timeout: float = 0.15) -> M.SerialFrameSource:
    return _open(FakePort(lines), idle_timeout)


def _line(vals: Iterable[float]) -> bytes:
    return (",".join(str(v) for v in vals) + "\r\n").encode()


def test_serial_frames_are_reordered_into_pad_order():
    """The firmware emits Signal-1..25 in electrical order; the source must
    apply PAD_ORDER so everything downstream shares one convention."""
    vals = list(range(1, M.N_PADS + 1))
    src = _source([_line(vals)])
    frame = next(src.frames())
    assert frame.shape == (M.N_PADS,)
    np.testing.assert_array_equal(frame, np.array(vals, dtype=float)[M.PAD_ORDER])
    assert frame[0] == M.PAD_TO_SIGNAL[0]


def test_serial_accepts_whitespace_and_comma_separators():
    vals = [28000 + i for i in range(M.N_PADS)]
    comma = next(_source([_line(vals)]).frames())
    space = next(_source([(" ".join(map(str, vals)) + "\n").encode()]).frames())
    np.testing.assert_array_equal(comma, space)


@pytest.mark.parametrize("bad", [
    b"\r\n",
    b"1,2,3\r\n",
    ("x," * M.N_PADS).encode() + b"\r\n",
    b"28000,28001,2800x," + b"0," * 22 + b"0\r\n",
])
def test_serial_skips_malformed_lines_without_raising(bad: bytes):
    good = _line([28000] * M.N_PADS)
    frames = list(_source([bad, good]).frames())
    assert len(frames) == 1
    np.testing.assert_array_equal(frames[0], np.full(M.N_PADS, 28000.0))


def test_serial_close_is_idempotent_and_stops_the_generator():
    port = FakePort([_line([1] * M.N_PADS)] * 5)
    src = _open(port)
    src.close()
    src.close()
    assert port.closed
    assert list(src.frames()) == []


def test_serial_ends_the_stream_when_the_device_goes_quiet():
    """A10: an unplugged sensor used to hang the generator forever - the
    dashboard froze on its last frame with no error and never recovered."""
    src = _source([_line([28000] * M.N_PADS)], idle_timeout=0.15)
    frames = list(src.frames())
    assert len(frames) == 1


def test_serial_does_not_busy_spin_on_empty_reads():
    """A10: with a port that returns immediately this loop hit ~7M reads/s,
    pinning the executor thread the WebSocket runs the generator on."""
    port = FakePort([])
    src = _open(port, idle_timeout=0.20)
    assert list(src.frames()) == []
    assert port.reads < 5000, f"busy-waited {port.reads} reads"


def test_list_serial_ports_degrades_gracefully():
    ports = M.list_serial_ports()
    assert isinstance(ports, list)
    assert all({"device", "description", "hwid"} <= set(p) for p in ports)


def test_replay_source_yields_pad_ordered_frames(dataset: M.Dataset):
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    frames = list(src.frames())
    assert len(frames) == len(src.raw)
    assert all(f.shape == (M.N_PADS,) for f in frames)


def test_replay_source_refuses_a_path_outside_data():
    with pytest.raises(ValueError):
        M.ReplayFrameSource("../main.py", realtime=False)


def test_live_pipeline_is_silent_during_warmup(dataset: M.Dataset):
    """The Kalman state is seeded from frame 0, so the first deltas are
    identically zero - a vector the classifier never saw. Unguarded, that
    produced a Level 3 siren on frame 0 of every stream."""
    model = M.new_rf(42).fit(dataset.X, dataset.y)
    pipe = M.LivePipeline(model)
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    for i, frame in enumerate(src.frames()):
        out = pipe.process(frame)
        if i < M.KALMAN_WARMUP:
            assert out["warming_up"] is True
            assert out["severity_level"] == 0
            assert out["cpri_percent"] == 0.0
        else:
            assert out["warming_up"] is False
            break


def test_live_pipeline_output_contract(dataset: M.Dataset):
    model = M.new_rf(42).fit(dataset.X, dataset.y)
    pipe = M.LivePipeline(model, fuse_imu=True)
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    out = [pipe.process(f) for f in src.frames()][-1]
    for key in ("index", "time_sec", "pad_values", "deltas", "baseline",
                "severity_level", "raw_level", "status", "probabilities",
                "cpri_percent", "propagation", "fusion"):
        assert key in out, f"missing {key}"
    assert len(out["pad_values"]) == len(out["deltas"]) == M.N_PADS
    assert abs(sum(out["probabilities"]) - 1.0) < 1e-6
    assert 0.0 <= out["cpri_percent"] <= 100.0
    assert out["index"] == len(src.raw) - 1


def test_live_pipeline_without_a_model_never_alarms(dataset: M.Dataset):
    pipe = M.LivePipeline(None)
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    assert all(pipe.process(f)["severity_level"] == 0 for f in src.frames())
