"""Frame-source and live-pipeline tests for main.py v6.2.

The v5.0 file this replaces drove `/api/v5/serial/connect` and a background
"LOOPBACK" thread that no longer exist. Real hardware is not available in CI,
so the serial parser is exercised against a fake port object instead of a real
one - which also lets us assert on the malformed lines a real UART produces.
"""
from __future__ import annotations

import numpy as np
import pytest

import main as M


class FakePort:
    """The subset of serial.Serial that SerialFrameSource actually touches.

    Returning b"" is what pyserial does on a read timeout, so exhausting the
    scripted lines models a device that has gone quiet.
    """

    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False
        self.reads = 0

    def readline(self):
        self.reads += 1
        return self._lines.pop(0) if self._lines else b""

    def close(self):
        self.closed = True


def _source(lines, idle_timeout=0.15):
    src = M.SerialFrameSource.__new__(M.SerialFrameSource)   # skip __init__/pyserial
    src._ser = FakePort(lines)
    src._stop = __import__("threading").Event()
    src.IDLE_TIMEOUT_S = idle_timeout        # keep the tests fast
    src.EMPTY_READ_SLEEP_S = 0.001
    return src


def _line(vals):
    return (",".join(str(v) for v in vals) + "\r\n").encode()


# --------------------------------------------------------------------------
# serial parsing
# --------------------------------------------------------------------------
def test_serial_frames_are_reordered_into_pad_order():
    """The firmware emits Signal-1..25 in electrical order; the source must
    apply PAD_ORDER so everything downstream shares one convention."""
    vals = list(range(1, M.N_PADS + 1))
    src = _source([_line(vals)])
    frame = next(src.frames())
    assert frame.shape == (M.N_PADS,)
    np.testing.assert_array_equal(frame, np.array(vals, dtype=float)[M.PAD_ORDER])
    assert frame[0] == M.PAD_TO_SIGNAL[0]      # pad 1 carries Signal-20's value


def test_serial_accepts_whitespace_and_comma_separators():
    vals = [28000 + i for i in range(M.N_PADS)]
    comma = next(_source([_line(vals)]).frames())
    space = next(_source([(" ".join(map(str, vals)) + "\n").encode()]).frames())
    np.testing.assert_array_equal(comma, space)


@pytest.mark.parametrize("bad", [
    b"\r\n",                                        # blank keepalive
    b"1,2,3\r\n",                                   # short frame
    ("x," * M.N_PADS).encode() + b"\r\n",           # non-numeric tokens
    b"28000,28001,2800x," + b"0," * 22 + b"0\r\n",  # one garbled token
])
def test_serial_skips_malformed_lines_without_raising(bad):
    good = _line([28000] * M.N_PADS)
    frames = list(_source([bad, good]).frames())
    assert len(frames) == 1
    np.testing.assert_array_equal(frames[0], np.full(M.N_PADS, 28000.0))


def test_serial_close_is_idempotent_and_stops_the_generator():
    src = _source([_line([1] * M.N_PADS)] * 5)
    src.close()
    src.close()
    assert src._ser.closed
    assert list(src.frames()) == []      # _stop is set, so it yields nothing


def test_serial_ends_the_stream_when_the_device_goes_quiet():
    """A10: an unplugged sensor used to hang the generator forever - the
    dashboard froze on its last frame with no error and never recovered."""
    src = _source([_line([28000] * M.N_PADS)], idle_timeout=0.15)
    frames = list(src.frames())          # must terminate, not block
    assert len(frames) == 1


def test_serial_does_not_busy_spin_on_empty_reads():
    """A10: with a port that returns immediately this loop hit ~7M reads/s,
    pinning the executor thread the WebSocket runs the generator on."""
    src = _source([], idle_timeout=0.20)
    assert list(src.frames()) == []
    # 0.20 s at a 1 ms floor is ~200 reads; anything near a million is a spin.
    assert src._ser.reads < 5000, f"busy-waited {src._ser.reads} reads"


def test_list_serial_ports_degrades_gracefully():
    ports = M.list_serial_ports()
    assert isinstance(ports, list)
    assert all({"device", "description", "hwid"} <= set(p) for p in ports)


# --------------------------------------------------------------------------
# replay source
# --------------------------------------------------------------------------
def test_replay_source_yields_pad_ordered_frames(dataset):
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    frames = list(src.frames())
    assert len(frames) == len(src.raw)
    assert all(f.shape == (M.N_PADS,) for f in frames)


def test_replay_source_refuses_a_path_outside_data():
    with pytest.raises(ValueError):
        M.ReplayFrameSource("../main.py", realtime=False)


# --------------------------------------------------------------------------
# live pipeline
# --------------------------------------------------------------------------
def test_live_pipeline_is_silent_during_warmup(dataset):
    """The Kalman state is seeded from frame 0, so the first deltas are
    identically zero - a vector the classifier never saw. Unguarded, that
    produced a Level 3 siren on frame 0 of every stream."""
    model = M._new_rf(42).fit(dataset.X, dataset.y)
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


def test_live_pipeline_output_contract(dataset):
    model = M._new_rf(42).fit(dataset.X, dataset.y)
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


def test_live_pipeline_without_a_model_never_alarms(dataset):
    pipe = M.LivePipeline(None)
    src = M.ReplayFrameSource(dataset.files[0], realtime=False)
    assert all(pipe.process(f)["severity_level"] == 0 for f in src.frames())
