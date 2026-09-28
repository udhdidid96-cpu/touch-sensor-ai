"""scripts/evaluate_robustness.py: the perturbations do what they claim.

The full run takes ~20 minutes and is not part of the suite. These tests check
the parts that would silently invalidate a result: shape preservation, the
frame-drop floor, determinism per file, and that the read_raw_csv patch is
always removed even when evaluation fails. The shard merge is checked for its
ordering, its recomputed deltas, and its refusal to join shards that disagree.
"""
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pytest

import evaluate_robustness as er
import main


def _raw(n: int = 40, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 28000.0 + rng.normal(0, 20, size=(n, main.N_PADS))


def test_every_variant_preserves_pad_count():
    raw = _raw()
    for name, fn in er.VARIANTS.items():
        out = fn(raw, np.random.default_rng(1))
        assert out.shape[1] == main.N_PADS, name
        assert np.isfinite(out).all(), name


def test_gain_variants_scale_by_the_stated_factor():
    raw = _raw()
    rng = np.random.default_rng(0)
    assert np.allclose(er.VARIANTS["gain_global_p20"](raw, rng), raw * 1.2)
    assert np.allclose(er.VARIANTS["gain_global_m10"](raw, rng), raw * 0.9)


def test_frame_drop_keeps_first_frame_and_respects_floor():
    raw = _raw(n=100)
    out = er.VARIANTS["frame_drop_10"](raw, np.random.default_rng(3))
    assert np.array_equal(out[0], raw[0])
    assert 80 <= len(out) < 100
    tiny = _raw(n=main.MIN_FRAMES_PER_FILE)
    assert len(er.VARIANTS["frame_drop_10"](tiny, np.random.default_rng(3))) == len(tiny)


def test_spike_is_under_the_surge_filter():
    raw = _raw(n=2000)
    out = er.VARIANTS["spike_1pct"](raw, np.random.default_rng(5))
    diff = out - raw
    assert abs(diff.max() - 5000.0) < 1e-6
    assert out.max() < 50000.0, "a spike that the surge filter removes tests nothing"
    assert 5 <= int((diff > 0).sum()) <= 40


def test_rng_is_deterministic_per_file_and_variant():
    a = er.rng_for("Data/Peel/A_Peel_01.csv", "noise_sd60").normal()
    b = er.rng_for("Data/Peel/A_Peel_01.csv", "noise_sd60").normal()
    c = er.rng_for("Data/Peel/A_Peel_02.csv", "noise_sd60").normal()
    assert a == b and a != c


def test_read_raw_csv_is_restored_after_failure(monkeypatch: pytest.MonkeyPatch):
    def no_dataset(*args: object, **kwargs: object) -> None:
        return None

    original = main.read_raw_csv
    monkeypatch.setattr(main, "load_dataset", no_dataset)
    try:
        er.run_variant("identity", er.VARIANTS["identity"])
    except RuntimeError:
        pass
    assert main.read_raw_csv is original


def _shard(tmp_path: Path, name: str, rows: List[Dict[str, Any]]) -> str:
    path = tmp_path / name
    path.write_text(json.dumps({"calibration": "kalman_norm", "results": rows}), encoding="utf-8")
    return str(path)


def _row(variant: str, sensitivity: float, per_hour: float) -> Dict[str, Any]:
    return {"variant": variant, "sensitivity": sensitivity, "false_alarm_rate": 0.1,
            "alarms_per_hour": per_hour, "detected": 30, "fa_files": 2, "missed": []}


def test_merge_orders_by_variant_and_recomputes_deltas(tmp_path: Path):
    a = _shard(tmp_path, "a.json", [_row("identity", 0.9, 1.0), _row("noise_sd60", 0.8, 2.5)])
    b = _shard(tmp_path, "b.json", [_row("identity", 0.9, 1.0), _row("gain_global_p10", 0.85, 1.5)])
    merged = er.merge_shards([b, a])
    assert [r["variant"] for r in merged["results"]] == ["identity", "gain_global_p10", "noise_sd60"]
    assert merged["results"][2]["delta_sensitivity"] == pytest.approx(-0.1)
    assert merged["results"][2]["delta_alarms_per_hour"] == pytest.approx(1.5)
    assert "noise_sd30" in merged["variants_missing"]


def test_merge_refuses_shards_that_disagree(tmp_path: Path):
    a = _shard(tmp_path, "a.json", [_row("identity", 0.9, 1.0)])
    b = _shard(tmp_path, "b.json", [_row("identity", 0.8, 1.0)])
    with pytest.raises(SystemExit, match="measured differently"):
        er.merge_shards([a, b])
