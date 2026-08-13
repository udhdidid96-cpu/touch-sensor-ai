# flake8: noqa
"""
Test suite for main.py v6.0, driven by the Normal Mix recordings.

Normal Mix is the right probe for this system: each file mixes touching,
rubbing and releasing, so it exercises the spike path, the release path and
the quiescent path inside a single recording, and every frame in it is
ground-truth NORMAL. Anything the pipeline escalates to Level 2/3 on a
Normal Mix file is a false alarm by construction.

Run:  python test_normal_mix.py
"""

from __future__ import annotations

import glob
import os
import sys
import traceback
from typing import Callable, List, Tuple

import numpy as np
import shutil
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main as M  # noqa: E402

MIX_DIR = os.path.join(M.DATA_ROOT, "Normal Mix")
MIX_FILES = sorted(glob.glob(os.path.join(MIX_DIR, "*.csv")))

_results: List[Tuple[str, bool, str]] = []


def test(name: str) -> Callable:
    """Register a check with this file's own runner. NOT a pytest test.

    pytest collects any module-level callable whose name starts with `test`, so
    it picked this decorator factory up, saw a parameter called `name`, and
    failed the whole file with "fixture 'name' not found". That is why
    `pytest test_normal_mix.py` errored while `python test_normal_mix.py`
    passed 49/50 - the 50-check harness looked broken and got ignored. The
    marker below tells pytest to leave the factory alone.
    """
    def deco(fn: Callable) -> Callable:
        def run() -> None:
            try:
                msg = fn() or ""
                _results.append((name, True, str(msg)))
            except AssertionError as exc:
                _results.append((name, False, str(exc)))
            except Exception:
                _results.append((name, False, traceback.format_exc(limit=2).strip().splitlines()[-1]))
        run.__name__ = fn.__name__
        return run
    return deco


test.__test__ = False       # pytest: this is a decorator factory, not a test


# ---------------------------------------------------------------------------
# Geometry and wiring (regressions for FIX F1 / F2)
# ---------------------------------------------------------------------------
@test("F1 centre pad renders at the centre of the heatmap")
def t_centre_pad() -> str:
    # Pad 13 sits at (50, 50), dead centre. Spiking it must light up the middle.
    v = np.zeros(M.N_PADS)
    v[12] = 3000.0
    grid = M.SPATIAL.interpolate(v)
    r, c = np.unravel_index(np.argmax(grid), grid.shape)
    fx, fy = c / (grid.shape[1] - 1), r / (grid.shape[0] - 1)
    assert abs(fx - 0.5) < 0.08, f"x drifted to {fx:.3f}"
    assert abs(fy - 0.5) < 0.08, f"y drifted to {fy:.3f}"
    return f"hotspot at x={fx:.3f} y={fy:.3f}"


@test("F1 left-edge pad does not render on the right")
def t_edge_pad() -> str:
    # This is the exact v5.0 failure: pad 20 at x=20% appeared at x=83%.
    v = np.zeros(M.N_PADS)
    v[19] = 3000.0                      # pad 20 -> (20, 50)
    grid = M.SPATIAL.interpolate(v)
    r, c = np.unravel_index(np.argmax(grid), grid.shape)
    fx = c / (grid.shape[1] - 1)
    assert fx < 0.35, f"left-edge pad rendered at x={fx:.3f} (v5.0 bug gave 0.835)"
    return f"x={fx:.3f}, correctly on the left half"


@test("F1 grid shape is (rows=y, cols=x) and matches the patch aspect")
def t_grid_shape() -> str:
    g = M.SPATIAL.interpolate(np.zeros(M.N_PADS))
    assert g.shape == (M.SPATIAL.n_rows, M.SPATIAL.n_cols), f"got {g.shape}"
    assert g.shape[0] > g.shape[1], "patch is 90x120 mm; rows must exceed columns"
    return f"shape {g.shape}"


@test("F2 signal-to-pad permutation is a bijection matching the wiring table")
def t_permutation() -> str:
    assert sorted(M.PAD_TO_SIGNAL) == list(range(1, 26)), "not a permutation of 1..25"
    assert len(set(M.PAD_ORDER.tolist())) == 25, "duplicate indices"
    probe = np.arange(1.0, 26.0)                       # Signal-1..25 == 1..25
    pads = M.signals_to_pads(probe)
    assert pads[0] == 20.0, f"pad 1 should read Signal-20, got Signal-{int(pads[0])}"
    assert pads[24] == 1.0, f"pad 25 should read Signal-1, got Signal-{int(pads[24])}"
    return "pad1<-Signal-20, pad25<-Signal-1"


@test("F2 reordering is applied to Signal-* files")
def t_reorder_applied() -> str:
    """This assertion used to be made against the real corpus and FAILED.

    It read `pd.read_csv(f)[M.SIGNAL_COLS]` from a Normal Mix recording and
    died on KeyError, because every round-1 file carries Sensor-* headers - the
    branch that trusts the columns as pad order and never touches PAD_ORDER.
    The failure was real signal about the corpus, not a broken permutation, so
    the permutation is now tested where it actually runs (a synthesised
    Signal-* file) and the corpus question is asserted separately below.
    """
    import pandas as pd
    import tempfile
    vals = np.tile(np.arange(1.0, M.N_PADS + 1), (8, 1))
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "signal_order.csv")
        pd.DataFrame(vals, columns=M.SIGNAL_COLS).to_csv(p, index=False)
        conv: List[str] = []
        raw = M.read_raw_csv(p, convention_out=conv)
    assert conv == ["signal"] * 1, f"expected the Signal-* branch, got {conv}"
    assert raw is not None
    assert np.allclose(raw, vals[:, M.PAD_ORDER]), "reorder does not match PAD_ORDER"
    assert raw[0][0] == M.PAD_TO_SIGNAL[0], "pad 1 must read the Signal-20 column"
    return "Signal-* files are permuted through PAD_ORDER on load"


@test("A9 the corpus uses ONE column convention, and it is recorded")
def t_single_convention() -> str:
    """The loader has two branches for the same 25 numbers and they disagree
    about orientation. A corpus that mixes them pools two patch layouts into
    one set of spatial results, which no accuracy number would ever reveal."""
    ds = M.load_dataset("kalman", verbose=False)
    assert ds is not None, "no dataset"
    conv = ds.conventions
    assert conv, "load_dataset did not record a column convention"
    assert len(conv) == 1, (
        f"corpus MIXES conventions {conv} - half the recordings are read in a "
        f"different pad orientation from the other half")
    kind, n = next(iter(conv.items()))
    if kind == "sensor":
        return (f"{n} files, all Sensor-* (used as-is; PAD_ORDER not exercised - "
                f"the Sensor-N == pad N assumption still needs a bench check)")
    return f"{n} files, all Signal-* (permuted through PAD_ORDER)"


# ---------------------------------------------------------------------------
# Security (regression for FIX F3)
# ---------------------------------------------------------------------------
@test("F3 path traversal is rejected")
def t_traversal() -> str:
    blocked = 0
    for evil in ["../main.py", "../../secrets.csv", "..\\..\\Windows\\win.ini",
                 "Normal Mix/../../main.py", "/etc/passwd"]:
        try:
            M.safe_data_path(evil)
        except ValueError:
            blocked += 1
        else:
            raise AssertionError(f"escaped containment: {evil}")
    ok = M.safe_data_path("Normal Mix/N_Mix_01.csv")
    assert ok.startswith(M.DATA_ROOT), "legitimate path was rewritten outside Data/"
    return f"{blocked}/5 traversal attempts blocked, normal path still works"


# ---------------------------------------------------------------------------
# Numerical safety (regressions for FIX F5 / F7 and CPRI clamp)
# ---------------------------------------------------------------------------
@test("F5 gradient features use real coordinates, not a 5x5 reshape")
def t_gradient_geometry() -> str:
    # A perfectly linear ramp in x must give a constant dC/dx and ~zero dC/dy.
    ramp = (M.PAD_XY[:, 0] - 50.0) * 10.0
    g = M.SPATIAL.node_gradients(ramp)
    gx, gy = g[:, 0], g[:, 1]
    assert abs(gx.mean() - 10.0) < 0.5, f"dC/dx should be 10, got {gx.mean():.3f}"
    assert abs(gy).mean() < 1.0, f"dC/dy should be ~0, got {abs(gy).mean():.3f}"
    return f"dC/dx={gx.mean():.2f} dC/dy={abs(gy).mean():.3f}"


@test("F7 full_proba returns 4 columns even when a class is missing")
def t_full_proba() -> str:
    from sklearn.ensemble import RandomForestClassifier
    X = np.random.RandomState(0).rand(60, 9)
    y = np.array([0] * 20 + [1] * 20 + [2] * 20)        # class 3 absent
    clf = RandomForestClassifier(n_estimators=5, random_state=0).fit(X, y)
    p = M.full_proba(clf, X)
    assert p.shape == (60, 4), f"got {p.shape}"
    assert np.allclose(p[:, 3], 0.0), "absent class should be zero, not garbage"
    assert np.allclose(p.sum(axis=1), 1.0, atol=1e-6), "rows must still sum to 1"
    _ = M.cpri(p)                                        # must not raise
    return "4 columns, absent class zeroed, CPRI computes"


@test("CPRI stays within 0..100")
def t_cpri_bounds() -> str:
    rng = np.random.RandomState(1)
    p = rng.dirichlet(np.ones(4), size=500)
    v = M.cpri(p)
    assert v.min() >= 0.0 and v.max() <= 100.0, f"range {v.min():.2f}..{v.max():.2f}"
    assert abs(M.cpri(np.array([[0, 0, 0, 1.0]]))[0] - 100.0) < 1e-6
    assert abs(M.cpri(np.array([[0, 0, 1.0, 0]]))[0] - 70.0) < 1e-6
    return f"range {v.min():.1f}..{v.max():.1f}"


# ---------------------------------------------------------------------------
# LOOP 4 - Kalman baseline, exercised on Normal Mix
# ---------------------------------------------------------------------------
@test("L4 Kalman tracks slow drift without absorbing a touch spike")
def t_kalman_gate() -> str:
    raw = M.read_raw_csv(MIX_FILES[0])
    # inject 40 counts of linear drift across the file (sweat-like)
    drift = np.linspace(0, 40, len(raw))[:, None]
    drifted = raw + drift

    kal = M.KalmanBaseline().run(drifted)
    stat = M.calibrate(drifted, "static")

    # the static scheme carries the drift straight into the delta
    quiet = np.abs(M.calibrate(raw, "static")).max(axis=1) < 200
    if quiet.sum() < 5:
        quiet = np.ones(len(raw), dtype=bool)
    stat_bias = float(np.abs(stat[quiet].mean(axis=1)).mean())
    kal_bias = float(np.abs(kal[quiet].mean(axis=1)).mean())
    assert kal_bias < stat_bias, f"kalman bias {kal_bias:.1f} not below static {stat_bias:.1f}"

    # and the real spikes survive
    assert kal.max() > 1500.0, f"touch spike flattened to {kal.max():.0f}"
    return f"quiescent bias {stat_bias:.1f} -> {kal_bias:.1f} counts, peak preserved {kal.max():.0f}"


@test("L4 Kalman baseline does not chase a sustained press")
def t_kalman_sustained() -> str:
    raw = M.read_raw_csv(MIX_FILES[0])
    base = raw[:5].mean(axis=0)
    synth = np.tile(base, (40, 1))
    synth[10:35, 6] += 2500.0                 # 14 s press on one pad
    d = M.KalmanBaseline().run(synth)
    assert d[34, 6] > 2000.0, f"press decayed to {d[34, 6]:.0f} by the end (baseline chased it)"
    return f"press held at {d[34, 6]:.0f} counts after 14 s"


# ---------------------------------------------------------------------------
# LOOP 3 - propagation, on Normal Mix (must stay idle) and Peel (must fire)
# ---------------------------------------------------------------------------
@test("L3 peel gate: 0 false alarms on all normal classes, 10/10 on Peel")
def t_propagation() -> str:
    normal = ["N_base", "Brief Touch", "Press", "Friction", "Normal Mix"]
    false_files = 0
    normal_files = 0
    for folder in normal:
        for f in sorted(glob.glob(os.path.join(M.DATA_ROOT, folder, "*.csv"))):
            raw = M.read_raw_csv(f)
            if raw is None or len(raw) < M.MIN_FRAMES_PER_FILE:
                continue
            normal_files += 1
            tk = M.PeelTracker()
            if any(tk.update(d)["confirmed"] for d in M.calibrate(raw, "static")):
                false_files += 1
                print(f"      false alarm on {os.path.relpath(f, M.DATA_ROOT)}")

    peel = sorted(glob.glob(os.path.join(M.DATA_ROOT, "Peel", "*.csv")))
    fired = 0
    for f in peel:
        tk = M.PeelTracker()
        if any(tk.update(d)["confirmed"] for d in M.calibrate(M.read_raw_csv(f), "static")):
            fired += 1

    assert false_files == 0, f"{false_files}/{normal_files} normal files raised a peel alarm"
    assert fired == len(peel), f"only {fired}/{len(peel)} peel files confirmed"
    return f"Peel {fired}/{len(peel)} confirmed, {false_files}/{normal_files} normal false alarms"


@test("L3 persistence removes the press-release transient")
def t_persistence() -> str:
    # Without persistence the per-frame gate fires on 8/10 Press files.
    press = sorted(glob.glob(os.path.join(M.DATA_ROOT, "Press", "*.csv")))
    inst = sum(1 for f in press
               if any(M.SPATIAL.propagation(d)["active"]
                      for d in M.calibrate(M.read_raw_csv(f), "static")))
    conf = 0
    for f in press:
        tk = M.PeelTracker()
        if any(tk.update(d)["confirmed"] for d in M.calibrate(M.read_raw_csv(f), "static")):
            conf += 1
    assert conf < inst, f"persistence changed nothing ({inst} -> {conf})"
    assert conf == 0, f"{conf}/10 Press files still confirm as peel"
    return f"Press files firing: {inst}/10 instantaneous -> {conf}/10 confirmed"


@test("L3 propagation direction is physically sensible")
def t_propagation_direction() -> str:
    # Synthetic peel rooted at the top-right, deepening toward that corner.
    # Amplitude is set so the whole-grid mean lands near the -371 counts
    # measured on real Peel recordings, otherwise the gate correctly ignores it.
    v = np.zeros(M.N_PADS)
    for i, (x, y) in enumerate(M.PAD_XY):
        v[i] = -2600.0 * max(0.0, (x - 42.0) / 48.0) * max(0.0, (66.0 - y) / 44.0)
    pr = M.SPATIAL.propagation(v)
    assert pr["active"], (f"gate rejected a synthetic peel: {int((v <= -300).sum())} pads, "
                          f"grid mean {v.mean():.0f}")
    ox, oy = pr["origin"]["x"], pr["origin"]["y"]
    assert ox > 55 and oy < 45, f"origin ({ox},{oy}) is not top-right"
    assert "peeling from top-right" in pr["description"], pr["description"]
    return f"{pr['description']}, grid mean {pr['grid_mean']:.0f}"


@test("L3 an inactive gate still reports diagnostics")
def t_propagation_inactive() -> str:
    v = np.zeros(M.N_PADS)
    v[3] = -900.0                                   # one deep pad, nothing else
    pr = M.SPATIAL.propagation(v)
    assert pr["active"] is False, "single-pad dip should not confirm as a peel"
    assert pr["n_lifting_pads"] == 1, pr["n_lifting_pads"]
    assert "grid_mean" in pr, "diagnostics dropped when the gate rejects"
    return f"1 pad, grid mean {pr['grid_mean']}, correctly inactive"


# ---------------------------------------------------------------------------
# LOOP 1 - live pipeline replay of Normal Mix
# ---------------------------------------------------------------------------
@test("L1 replay source yields pad-ordered frames at the right length")
def t_replay_source() -> str:
    src = M.ReplayFrameSource("Normal Mix/N_Mix_01.csv", realtime=False)
    frames = list(src.frames())
    raw = M.read_raw_csv(MIX_FILES[0])
    assert len(frames) == len(raw), f"{len(frames)} != {len(raw)}"
    assert frames[0].shape == (25,), f"frame shape {frames[0].shape}"
    assert np.allclose(frames[0], raw[0]), "replay frame is not in pad order"
    return f"{len(frames)} frames replayed"


@test("L1 live pipeline processes Normal Mix end to end")
def t_live_pipeline() -> str:
    ds = M.load_dataset("static", False, verbose=False)
    assert ds is not None
    model = M._new_rf(42).fit(ds.X, ds.y)
    pipe = M.LivePipeline(model, False, fuse_imu=True)
    src = M.ReplayFrameSource("Normal Mix/N_Mix_02.csv", realtime=False)
    out = [pipe.process(f) for f in src.frames()]
    assert len(out) > 0
    keys = {"index", "time_sec", "deltas", "severity_level", "probabilities",
            "cpri_percent", "propagation", "fusion"}
    assert keys.issubset(out[0].keys()), f"missing {keys - set(out[0].keys())}"
    assert len(out[0]["deltas"]) == 25
    assert abs(out[5]["time_sec"] - 5 * M.SAMPLE_PERIOD_S) < 1e-6
    import json
    json.dumps(out[0])                                    # must be JSON-serialisable
    return f"{len(out)} frames, JSON-serialisable"


@test("L1 warmup window is silent")
def t_warmup_guard() -> str:
    """Two regressions in one pass.

    (a) The Kalman state is seeded from the first frame, so the opening deltas
        are identically zero - a point the classifier never sees in training,
        and it landed in the alarm class. On a ward that is an ICU siren the
        instant the dressing is connected.
    (b) Raw per-frame argmax flickers to Level 3 on touch-release transients.
        The debouncer must absorb that.
    """
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    model = M._new_rf(42).fit(ds.X, ds.y)
    worst_raw = 0
    worst_out = 0
    for f in MIX_FILES:
        rel = os.path.relpath(f, M.DATA_ROOT).replace(os.sep, "/")
        pipe = M.LivePipeline(model, False, fuse_imu=False)
        for k, frame in enumerate(M.ReplayFrameSource(rel, realtime=False).frames()):
            out = pipe.process(frame)
            if k < M.KALMAN_WARMUP:
                assert out["severity_level"] == 0, (
                    f"{os.path.basename(f)} frame {k}: level {out['severity_level']} during warmup")
                assert out["cpri_percent"] == 0.0, f"CPRI {out['cpri_percent']} during warmup"
                assert out["warming_up"] is True
            else:
                worst_raw = max(worst_raw, out["raw_level"])
                worst_out = max(worst_out, out["severity_level"])
    # The residual escalation budget is owned by the debouncer test below, which
    # names the offending file. This test asserts only that the warmup window is
    # silent and that debouncing strictly reduces what reaches the annunciator.
    assert worst_out <= worst_raw, "debouncer raised a level the classifier never emitted"
    return (f"{len(MIX_FILES)} files: warmup silent, raw peaked at L{worst_raw}, "
            f"annunciated max L{worst_out}")


@test("L1 debouncer keeps sensitivity while cutting false alarms")
def t_debouncer() -> str:
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    model = M._new_rf(42).fit(ds.X, ds.y)
    groups = {"normal": ("N_base/", "Brief Touch/", "Press/", "Friction/", "Normal Mix/"),
              "peel": ("Peel/",),
              "pull": ("Vertical Pull", "Horizontal Pull", "PowerP/")}
    raw_fire = {k: 0 for k in groups}
    out_fire = {k: 0 for k in groups}
    totals = {k: 0 for k in groups}
    offenders: List[str] = []
    for f in ds.files:
        key = next((k for k, pre in groups.items() if f.startswith(pre)), None)
        if key is None:
            continue
        totals[key] += 1
        pipe = M.LivePipeline(model, False, fuse_imu=False)
        raws, outs = [], []
        for frame in M.ReplayFrameSource(f, realtime=False).frames():
            o = pipe.process(frame)
            raws.append(o["raw_level"])
            outs.append(o["severity_level"])
        if max(raws[M.KALMAN_WARMUP:] or [0]) >= 2:
            raw_fire[key] += 1
        if max(outs[M.KALMAN_WARMUP:] or [0]) >= 2:
            out_fire[key] += 1
            if key == "normal":
                offenders.append(f)

    assert out_fire["peel"] == totals["peel"], f"peel sensitivity dropped to {out_fire['peel']}/{totals['peel']}"
    assert out_fire["pull"] == totals["pull"], f"pull sensitivity dropped to {out_fire['pull']}/{totals['pull']}"
    assert out_fire["normal"] <= 2, f"{out_fire['normal']}/{totals['normal']} normal files still alarm: {offenders}"
    assert out_fire["normal"] < raw_fire["normal"], "debouncer changed nothing"
    return (f"normal {raw_fire['normal']}/{totals['normal']} -> {out_fire['normal']}/{totals['normal']}"
            f"{' (' + ', '.join(offenders) + ')' if offenders else ''}; "
            f"peel {out_fire['peel']}/{totals['peel']}, pull {out_fire['pull']}/{totals['pull']}")


@test("L1 serial port scan degrades gracefully with no hardware")
def t_serial_scan() -> str:
    ports = M.list_serial_ports()
    assert isinstance(ports, list), "must return a list even with no COM device"
    return f"{len(ports)} port(s) visible on this host"


# ---------------------------------------------------------------------------
# LOOP 5 - fusion
# ---------------------------------------------------------------------------
@test("L5 fusion never lowers risk and stays bounded")
def t_fusion_bounds() -> str:
    d = M.calibrate(M.read_raw_csv(MIX_FILES[0]), "static")
    imu = M.synthesise_imu(d)
    base = np.linspace(0, 90, len(d))
    fused = M.FusionEngine().run(base, imu)
    assert (fused >= base - 1e-6).all(), "fusion reduced the capacitive risk"
    assert fused.max() <= 100.0 + 1e-6, f"fused risk exceeded 100: {fused.max():.2f}"
    return f"max fused {fused.max():.1f}%, never below capacitive input"


@test("L5 lead-time helper reports a positive gain when fusion crosses first")
def t_lead_time() -> str:
    a = np.array([0, 10, 20, 30, 45, 55, 70])
    b = np.array([0, 20, 40, 60, 75, 85, 95])
    g = M.lead_time_gain(a, b, threshold=50.0)
    assert g is not None and g > 0, f"expected a positive lead, got {g}"
    assert M.lead_time_gain(a, np.zeros(7), 50.0) is None, "no crossing should give None"
    return f"lead {g:.2f} s"


# ---------------------------------------------------------------------------
# Dataset hygiene and the headline metric
# ---------------------------------------------------------------------------
@test("short files are excluded from training")
def t_short_files() -> str:
    ds = M.load_dataset("static", False, verbose=False)
    assert ds is not None
    bad = [f for f, r in ds.skipped if "frames" in r]
    for f in ds.files:
        n = len(M.read_raw_csv(os.path.join(M.DATA_ROOT, f)))
        assert n >= M.MIN_FRAMES_PER_FILE, f"{f} has {n} frames but was kept"
    return f"{ds.n_files} files kept, {len(bad)} short file(s) skipped: {bad or 'none'}"


@test("Normal Mix false-alarm rate under leave-one-file-out")
def t_mix_false_alarm() -> str:
    ds, oof, _ = _oof()
    y_pred = [M._file_vote(oof[ds.groups == i]) for i in range(ds.n_files)]
    mix_idx = [i for i, f in enumerate(ds.files) if f.startswith("Normal Mix/")]
    assert mix_idx, "no Normal Mix files loaded"
    preds = [y_pred[i] for i in mix_idx]
    escalated = sum(1 for p in preds if p >= 2)
    assert escalated == 0, f"{escalated}/{len(mix_idx)} Normal Mix files raised a false alarm: {preds}"
    return f"0/{len(mix_idx)} Normal Mix files escalated (preds={preds})"


@test("Normal Mix frame-level escalation (single-frame RF weakness)")
def t_mix_frame_level() -> str:
    """Documents the residual weakness the temporal model exists to fix.

    A single frame carries no history, so an RF cannot tell a finger arriving
    from a dressing lifting off. Roughly one Normal Mix frame in eight is
    escalated. File-level majority voting absorbs it (see the test above), and
    LOOP 2 addresses it directly - run with --temporal to measure that.
    """
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    res = M.evaluate_rf(ds, seeds=(42,), verbose=False)
    mix_files = [i for i, f in enumerate(ds.files) if f.startswith("Normal Mix/")]
    mask = np.isin(ds.groups, mix_files)
    frame_pred = res["oof_proba"][mask].argmax(axis=1)
    rate = 100.0 * (frame_pred >= 2).sum() / max(mask.sum(), 1)
    assert rate < 20.0, f"{rate:.1f}% escalated - worse than the documented baseline"
    return f"{rate:.1f}% of {int(mask.sum())} frames (file-level vote absorbs all of it)"


@test("L2 temporal vs RF, reported honestly [slow, --temporal]")
def t_temporal() -> str:
    """The claim this test used to make was false.

    It asserted BiLSTM macro F1 > RF macro F1, and passed - because
    evaluate_temporal hard-coded seed 0, the one draw out of four where that is
    true. Across seeds the two models are within each other's spread. This test
    now asserts only what is actually established: the comparison runs, varies
    with the seed, and is reported with a spread.
    """
    if "--temporal" not in sys.argv:
        return "skipped (pass --temporal to run, ~6 min)"
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    tr = M.evaluate_temporal_multi(ds, seeds=(0, 1, 2), verbose=False)
    assert tr is not None, "PyTorch unavailable"
    mix = [i for i, f in enumerate(ds.files) if f.startswith("Normal Mix/")]
    worst = 0
    for r in tr["runs"]:
        pos = {f: k for k, f in enumerate(r["files"])}
        worst = max(worst, max(r["y_pred_nn"][pos[i]] for i in mix))
    assert worst <= 1, f"BiLSTM escalated a Normal Mix file to level {worst}"
    return (f"BiLSTM {tr['nn_macro_f1_mean']:.4f}±{tr['nn_macro_f1_sd']:.4f} vs "
            f"RF {tr['rf_macro_f1_mean']:.4f}±{tr['rf_macro_f1_sd']:.4f}; "
            f"Normal Mix never escalated")


@test("R2 SOP folder names (VPull/HPull) are recognised")
def t_sop_folder_names() -> str:
    for name in ("VPull", "HPull", "PowerPull", "Baseline", "Touch"):
        assert name in M.CLASS_MAPPING, f"SOP folder '{name}' would load as zero files"
    assert M.CLASS_MAPPING["VPull"]["label"] == 3
    assert M.CLASS_MAPPING["HPull"]["label"] == 3
    assert M.CLASS_MAPPING["Baseline"]["label"] == 0
    return "VPull/HPull/PowerPull/Baseline/Touch all map to the right class"


@test("R9 incomplete class coverage is flagged, not silently scored")
def t_class_coverage() -> str:
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None and ds.complete, "full corpus should report complete"
    assert ds.classes_present == [0, 1, 2, 3]
    return f"classes present {ds.classes_present}, complete={ds.complete}"


@test("R5 file vote breaks ties toward the more severe class")
def t_tie_break() -> str:
    assert M._file_vote(np.repeat([0, 1, 2, 3], [2, 6, 1, 6])) == 3, "tie went to the benign class"
    assert M._file_vote(np.repeat([0, 1, 2, 3], [3, 4, 1, 4])) == 3
    assert M._file_vote(np.repeat([0, 1, 2, 3], [9, 1, 0, 0])) == 0, "clear majority must still win"
    assert M._file_vote(np.array([2, 2, 2])) == 2
    return "ties -> higher class, clear majorities unchanged"


@test("R8 k-of-n debouncer: escalates on support, holds, then releases")
def t_debouncer_semantics() -> str:
    d = M.AlarmDebouncer(window=5, min_votes=3, hold=2)
    out = [d.update(x) for x in [3, 3, 3, 3, 0, 0, 0, 0, 0]]
    assert out[2] == 3, f"3 supporting frames should escalate: {out}"
    assert out[0] < 2, f"one frame must not annunciate: {out}"
    assert out[-1] == 0, f"alarm never released: {out}"
    held = out[4:7]
    assert 3 in held, f"alarm did not hold after support ended: {out}"
    return f"out={out}"


@test("R8 an intermittent classifier still annunciates (1/3 and 2/3 patterns)")
def t_debouncer_oscillation() -> str:
    # v6.0 annunciated nothing on 2/3; v6.1 annunciated nothing on 1/3. Both are
    # exactly what a real pull produces at the edge of the decision boundary.
    for pattern, name in ([[2, 3] * 8, "2/3"], [[1, 3] * 8, "1/3"]):
        d = M.AlarmDebouncer(window=5, min_votes=3, hold=2)
        out = [d.update(x) for x in pattern]
        assert max(out) >= 2, f"{name} oscillation annunciated nothing: {out}"
    d = M.AlarmDebouncer(window=5, min_votes=3, hold=2)
    out = [d.update(x) for x in [3, 3, 3] + [0] * 12]
    assert out[-1] == 0, f"alarm latched forever: {out}"
    return "1/3 and 2/3 both annunciate; no permanent latch"


@test("R8 a single spurious frame never annunciates")
def t_debouncer_spike() -> str:
    d = M.AlarmDebouncer(window=5, min_votes=3, hold=2)
    out = [d.update(x) for x in [0, 0, 3, 0, 0, 0, 0, 0]]
    assert max(out) < 2, f"single spike annunciated: {out}"
    return f"out={out}"


@test("R8 _file_vote is safe on empty and out-of-range input")
def t_file_vote_guards() -> str:
    assert M._file_vote(np.array([], dtype=int)) == 0, "empty input must not alarm"
    assert M._file_vote(np.array([7, 7, 1])) == 1, "out-of-range labels must be ignored"
    return "empty -> 0, out-of-range ignored"


@test("R6 empty / corrupt CSV is skipped by name, never crashes")
def t_bad_csv() -> str:
    tmp = tempfile.mkdtemp()
    try:
        empty = os.path.join(tmp, "aborted.csv")
        open(empty, "w").close()
        assert M.read_raw_csv(empty) is None, "empty file should return None"
        assert "empty" in M.describe_csv_problem(empty).lower()

        junk = os.path.join(tmp, "junk.csv")
        with open(junk, "w") as fh:
            fh.write("hello,world\n1,2\n")
        assert M.read_raw_csv(junk) is None
        assert M.describe_csv_problem(junk)

        nan = os.path.join(tmp, "nan.csv")
        import pandas as pd
        df = pd.DataFrame(np.full((10, 25), 28000.0), columns=M.SIGNAL_COLS)
        df.iloc[3, 6] = np.nan
        df.to_csv(nan, index=False)
        assert M.read_raw_csv(nan) is None, "NaN file must not reach the model"
        assert "non-finite" in M.describe_csv_problem(nan)
        return "empty / malformed / NaN all rejected with a reason"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test("R3 audit recurses into session folders and demands all four classes")
def t_audit_sessions() -> str:
    rep = M.audit_folder(M.DATA_ROOT)
    names = {c["check"] for c in rep["checks"]}
    assert "all four classes recorded" in names, "completeness check missing"
    assert any("baseline swing" in n for n in names), "SOP criterion 5 not implemented"
    assert not rep["passed"], "round-1 data must not pass the spec audit"
    fails = {c["check"] for c in rep["checks"] if not c["pass"]}
    assert any("25,000" in f for f in fails), "detachment spec failure not reported"
    assert any("baseline swing" in f for f in fails), f"baseline swing passed: {fails}"
    return f"{len(rep['checks'])} checks, {len(fails)} failing as expected"


@test("R3 audit refuses a folder that is missing classes")
def t_audit_incomplete() -> str:
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "N_base")
        os.makedirs(d)
        shutil.copy(os.path.join(M.DATA_ROOT, "N_base", "N_Base_02.csv"), d)
        rep = M.audit_folder(tmp)
        assert not rep["passed"], "a baseline-only folder must not report ready"
        miss = [c for c in rep["checks"] if c["check"] == "all four classes recorded"]
        assert miss and not miss[0]["pass"], "missing classes not detected"
        return f"baseline-only folder rejected: {miss[0]['detail']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test("R7 pooled confusion matrix agrees with the headline mean")
def t_report_consistency() -> str:
    from sklearn.metrics import confusion_matrix
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    res = M.evaluate_rf(ds, seeds=(42, 43, 44), verbose=False)
    cm = confusion_matrix(res["y_true"], res["y_pred"], labels=list(range(M.N_CLASSES)))
    from_cm = float(np.trace(cm) / cm.sum())
    assert abs(from_cm - res["accuracy_mean"]) < 1e-9, (
        f"matrix says {from_cm*100:.2f}%, headline says {res['accuracy_mean']*100:.2f}%")
    assert len(res["y_true"]) == 3 * ds.n_files
    return f"{from_cm*100:.2f}% both ways over {len(res['y_true'])} predictions"


@test("R4 the REST dataset endpoint applies the same guards as the live path")
def t_rest_guards() -> str:
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        return "skipped (fastapi TestClient unavailable)"
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    model = M._new_rf(42).fit(ds.X, ds.y)
    client = TestClient(M.create_app({"model": model, "use_gradient": False,
                                      "calibration": "kalman"}))
    alarms, arrows, checked = [], [], 0
    for f in ds.files:
        if not any(f.startswith(p) for p in
                   ("N_base/", "Brief Touch/", "Press/", "Friction/", "Normal Mix/")):
            continue
        checked += 1
        r = client.get("/api/v5/dataset/" + "/".join(f.split("/")))
        assert r.status_code == 200, f"{f}: HTTP {r.status_code}"
        frames = r.json()["frames"]
        assert "raw_level" in frames[0] and "warming_up" in frames[0]
        if max(fr["severity_level"] for fr in frames) >= 3:
            alarms.append(f)
        if any(fr["propagation"].get("confirmed") for fr in frames):
            arrows.append(f)
    assert len(alarms) <= 1, f"{len(alarms)}/{checked} normal files sound the siren: {alarms}"
    assert not arrows, f"peel arrow confirmed on normal files: {arrows}"
    return f"{len(alarms)}/{checked} siren, {len(arrows)}/{checked} peel arrow"


@test("R1 the BiLSTM comparison is reported with a spread [slow, --temporal]")
def t_temporal_spread() -> str:
    if "--temporal" not in sys.argv:
        return "skipped (pass --temporal to run, ~6 min)"
    ds = M.load_dataset("kalman", False, verbose=False)
    assert ds is not None
    tr = M.evaluate_temporal_multi(ds, seeds=(0, 1, 2), verbose=False)
    assert tr is not None, "PyTorch unavailable"
    assert tr["n_seeds"] >= 3, "a comparison needs at least 3 seeds"
    assert tr["nn_macro_f1_sd"] > 0, "sd of zero means the seed is not varying"
    assert "verdict" in tr
    # The point of this test is that no single-seed claim survives.
    return (f"BiLSTM {tr['nn_macro_f1_mean']:.4f} ± {tr['nn_macro_f1_sd']:.4f} vs "
            f"RF {tr['rf_macro_f1_mean']:.4f} ± {tr['rf_macro_f1_sd']:.4f} -> {tr['verdict']}")


@test("R10-R14 CLI flags behave")
def t_cli() -> str:
    # Project root = the PARENT of tests/. This file used to sit at the top
    # level, where dirname(__file__) was the root; after the move it pointed at
    # tests/, main.py was not there, and every subprocess below failed for the
    # wrong reason.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def run(*a):
        return subprocess.run([sys.executable, "main.py", *a], cwd=here,
                              capture_output=True, text=True, timeout=180)
    r = run("--seeds", "0", "--eval")
    assert r.returncode != 0 and "--seeds must be >= 1" in (r.stderr + r.stdout), \
        "--seeds 0 silently ran one seed"
    r = run("--replay", "Peel/does_not_exist.csv")
    assert r.returncode == 2, f"bad --replay path exit {r.returncode}"
    assert "cannot replay" in r.stdout and "Traceback" not in r.stderr, "raw traceback on bad path"
    r = run("--eval", "--cv", "session")
    assert r.returncode == 2 and "needs recordings under" in r.stdout
    return "--seeds 0 rejected, bad --replay handled, --cv session guarded"


# ---------------------------------------------------------------------------
# Runner - collected at call time so tests appended below still register
# ---------------------------------------------------------------------------


# ===========================================================================
# v6.2 - episode-level evaluation and out-of-fold honesty
# ===========================================================================
_STREAM_CACHE: List[Any] = []
_OOF_CACHE: List[Any] = []


def _oof() -> Any:
    """Leave-one-file-out predictions, computed once for the whole suite."""
    if not _OOF_CACHE:
        from sklearn.model_selection import LeaveOneGroupOut
        ds = M.load_dataset("kalman", False, verbose=False)
        assert ds is not None
        clf = M._new_rf(42)
        oof = np.zeros(len(ds.X), dtype=int)
        for tr, te in LeaveOneGroupOut().split(ds.X, ds.y, groups=ds.groups):
            clf.fit(ds.X[tr], ds.y[tr])
            oof[te] = clf.predict(ds.X[te])
        _OOF_CACHE.append((ds, oof, clf))
    return _OOF_CACHE[0]


def _stream() -> Any:
    if not _STREAM_CACHE:
        ds = M.load_dataset("kalman", False, verbose=False)
        assert ds is not None
        _STREAM_CACHE.append((ds, M.evaluate_stream(ds, verbose=False)))
    return _STREAM_CACHE[0]


@test("E1 streaming metrics are out-of-fold, not in-sample")
def t_stream_out_of_fold() -> str:
    """The v6.1 suite fit the forest on the whole corpus and then replayed files
    from it, so every alarm number in the README was in-sample. In-sample the
    corpus shows 0/40 normal recordings alarming; out of fold it is materially
    worse, and that is the number a new patient would see."""
    ds, st = _stream()
    in_model = M._new_rf(42).fit(ds.X, ds.y)
    in_fa = 0
    for fi, lab in enumerate(ds.labels):
        if lab > 1:
            continue
        deb = M.AlarmDebouncer()
        lv = [0 if k < M.KALMAN_WARMUP else deb.update(int(p))
              for k, p in enumerate(in_model.predict(ds.X[ds.groups == fi]))]
        in_fa += max(lv) >= 2
    assert st["false_alarm_files"] >= in_fa, (
        "out-of-fold should not look better than in-sample - check the fold logic")
    return f"in-sample {in_fa}/{st['n_normal']} vs out-of-fold {st['false_alarm_files']}/{st['n_normal']}"


@test("E2 episode metrics are within clinical bounds and fully reported")
def t_episode_metrics() -> str:
    _, st = _stream()
    for key in ("sensitivity", "sensitivity_ci", "false_alarm_rate", "false_alarm_ci",
                "alarms_per_hour", "median_latency_s", "onsets_per_anomaly", "curve"):
        assert key in st, f"missing {key}"
    assert st["sensitivity"] >= 0.80, f"sensitivity {st['sensitivity']:.3f} too low to ship"
    # B10: this used to read "exceeds the desensitisation threshold" against a
    # 10/hour bar. README's Retracted claims table lists that threshold as
    # having no source - the cited paper says explicitly that no threshold
    # defining a "high" alarm rate exists. Enforcing it here made a retracted
    # number the harness's own pass criterion. Kept as a REGRESSION bound
    # (roughly double the ~6/hour the shipped operating point measures), which
    # is a guard against the annunciator degrading, not a clinical claim.
    assert st["alarms_per_hour"] <= 12.0, (
        f"{st['alarms_per_hour']:.1f} alarms/hour - well above the ~6/hour this "
        f"operating point measures; the annunciator has regressed. This bound is "
        f"a regression guard, not a published safe limit.")
    assert st["onsets_per_anomaly"] <= 1.2, (
        f"{st['onsets_per_anomaly']:.2f} onsets per event - the annunciator is re-arming mid-event")
    assert st["median_latency_s"] is not None
    return (f"sens {st['sensitivity']*100:.1f}%, {st['alarms_per_hour']:.1f} alarms/h, "
            f"latency {st['median_latency_s']:.2f}s, {st['onsets_per_anomaly']:.2f} onsets/event")


@test("E3 episode detection is invariant to recording length; file vote is not")
def t_length_invariance() -> str:
    """The round-2 SOP prescribes 60-120 s recordings. Re-voting the same events
    padded to that length takes file-vote pull recall to zero while episode
    detection is unchanged. This is why the reported unit had to change."""
    ds, oof, clf = _oof()
    quiet = np.concatenate([ds.frames[i] for i, l in enumerate(ds.labels) if l == 0])
    rng = np.random.default_rng(0)
    res = {}
    for target in (22, 161):
        votes, eps = [], []
        for fi, lab in enumerate(ds.labels):
            if lab != 3:
                continue
            p = list(oof[ds.groups == fi])
            pad = target - len(p)
            if pad > 0:
                q = list(clf.predict(M.extract_features(quiet[rng.integers(0, len(quiet), pad)], False)))
                p = q[:pad // 2] + p + q[pad // 2:]
            votes.append(M._file_vote(np.array(p)) == 3)
            eps.append(max(p) >= 2)
        res[target] = (float(np.mean(votes)), float(np.mean(eps)))
    short_v, short_e = res[22]
    long_v, long_e = res[161]
    assert long_e >= 0.9 * short_e, "episode detection degraded with length"
    assert long_v < short_v, "expected the file vote to degrade with length"
    return (f"12 s: vote {short_v:.3f} / episode {short_e:.3f}  |  "
            f"90 s: vote {long_v:.3f} / episode {long_e:.3f}")


@test("E4 Wilson and bootstrap intervals are sane")
def t_intervals() -> str:
    lo, hi = M.wilson(0, 40)
    assert lo == 0.0 and 0.05 < hi < 0.15, f"0/40 Wilson [{lo}, {hi}]"
    lo, hi = M.wilson(40, 40)
    assert hi == 1.0 and 0.85 < lo < 0.95, f"40/40 Wilson [{lo}, {hi}]"
    lo, hi = M.wilson(20, 40)
    assert lo < 0.5 < hi
    b = M.bootstrap_ci([0, 1, 2, 3] * 10, [0, 1, 2, 3] * 10, n_boot=200)
    assert b["accuracy"][0] == 1.0, "perfect predictions should bootstrap to 1.0"
    return f"0/40 -> [0.0, {M.wilson(0,40)[1]*100:.1f}%], perfect -> 1.0"


@test("E5 a non-numeric token is rejected, not raised")
def t_bad_token() -> str:
    tmp = tempfile.mkdtemp()
    try:
        p = os.path.join(tmp, "glitch.csv")
        import pandas as pd
        df = pd.DataFrame(np.full((10, 25), 28000.0), columns=M.SIGNAL_COLS)
        df = df.astype(object)
        df.iloc[4, 6] = "2800x"                     # a garbled UART token
        df.to_csv(p, index=False)
        assert M.read_raw_csv(p) is None, "non-numeric token slipped through"
        assert M.describe_csv_problem(p), "no reason reported"
        rep = M.audit_folder(tmp)                   # must not raise
        assert isinstance(rep, dict)
        return f"rejected: {M.describe_csv_problem(p)[:48]}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _plant(root: str, rel: str, n: int = 3) -> None:
    """Copy n real Peel recordings into root/rel."""
    d = os.path.join(root, *rel.split("/"))
    os.makedirs(d, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(M.DATA_ROOT, "Peel", "*.csv")))[:n]:
        shutil.copy(f, d)


@test("D3 a mis-named session folder is reported, never silently dropped")
def t_stray_session_typo() -> str:
    tmp = tempfile.mkdtemp()
    real = M.DATA_ROOT
    try:
        for cls in ("N_base", "Brief Touch", "Peel", "VPull"):
            _plant(tmp, cls, 2)
        _plant(tmp, "Session1/Peel", 3)          # 'Session1' does not match S<n>
        _plant(tmp, "Peel/retake", 3)            # sub-folder inside a class folder
        M.DATA_ROOT = tmp
        ds = M.load_dataset(verbose=False)
        assert ds is not None, "planted folder failed to load at all"
        assert ds.n_lost_files == 6, f"expected 6 lost CSVs, got {ds.n_lost_files}"
        rels = {r for r, _, _ in ds.unknown_folders}
        assert rels == {"Session1/Peel", "Peel/retake"}, f"reported: {rels}"
        hints = {r: h for r, _, h in ds.unknown_folders}
        assert "S1" in hints["Session1/Peel"], "hint does not name the fix"
        assert "class folder" in hints["Peel/retake"], "hint does not name the cause"
        return f"{ds.n_files} loaded, {ds.n_lost_files} reported lost with fixes"
    finally:
        M.DATA_ROOT = real
        shutil.rmtree(tmp, ignore_errors=True)


@test("D3 --audit fails when any CSV sits where the loader cannot see it")
def t_audit_rejects_strays() -> str:
    tmp = tempfile.mkdtemp()
    try:
        for cls in ("N_base", "Brief Touch", "Peel", "VPull"):
            _plant(tmp, cls, 2)
        clean = M.audit_folder(tmp)
        stray_check = "every CSV sits in a folder the loader reads"
        c0 = [c for c in clean["checks"] if c["check"] == stray_check]
        assert c0 and c0[0]["pass"], "a clean folder was flagged as having strays"
        _plant(tmp, "Session1/Peel", 3)
        dirty = M.audit_folder(tmp)
        c1 = [c for c in dirty["checks"] if c["check"] == stray_check]
        assert c1 and not c1[0]["pass"], "audit passed a folder with 3 lost CSVs"
        assert dirty["lost_files"] == 3, f"lost_files={dirty['lost_files']}"
        assert not dirty["passed"], "overall audit still reported ready"
        return f"clean folder passes, 3 stray CSVs fail the audit"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test("D3 every CSV on disk is loaded, skipped, or reported - none vanish")
def t_no_csv_unaccounted() -> str:
    ds = M.load_dataset(verbose=False)
    assert ds is not None
    on_disk = len(glob.glob(os.path.join(M.DATA_ROOT, "**", "*.csv"), recursive=True))
    accounted = ds.n_files + len(ds.skipped) + ds.n_lost_files
    assert accounted == on_disk, (
        f"{on_disk} CSVs on disk but only {accounted} accounted for "
        f"({ds.n_files} loaded + {len(ds.skipped)} skipped + {ds.n_lost_files} stray)")
    return f"{on_disk} on disk = {ds.n_files} loaded + {len(ds.skipped)} skipped + {ds.n_lost_files} stray"


@test("D3 a correctly-named session folder still loads and is not called stray")
def t_valid_session_loads() -> str:
    tmp = tempfile.mkdtemp()
    real = M.DATA_ROOT
    try:
        for cls in ("N_base", "Brief Touch", "Peel", "VPull"):
            _plant(tmp, cls, 2)
            _plant(tmp, f"S1/{cls}", 2)
            _plant(tmp, f"S2/{cls}", 2)
        M.DATA_ROOT = tmp
        ds = M.load_dataset(verbose=False)
        assert ds is not None
        assert ds.n_lost_files == 0, f"valid layout flagged: {ds.unknown_folders}"
        assert set(ds.session_names) == {"S0", "S1", "S2"}, ds.session_names
        assert ds.n_files == 24, f"expected 24 files, got {ds.n_files}"
        return f"{ds.n_files} files across {ds.n_sessions} sessions, 0 stray"
    finally:
        M.DATA_ROOT = real
        shutil.rmtree(tmp, ignore_errors=True)


@test("D4 a weak Friction class cannot hide inside a pooled contact check")
def t_contact_check_not_pooled() -> str:
    tmp = tempfile.mkdtemp()
    try:
        for cls in ("N_base", "Peel", "VPull"):
            _plant(tmp, cls, 2)
        # Brief Touch that never reaches 30,000 - the SOP criterion must fail
        # even though Press/Friction files sit alongside it.
        for cls in ("Brief Touch", "Press", "Friction"):
            os.makedirs(os.path.join(tmp, cls), exist_ok=True)
            for f in sorted(glob.glob(os.path.join(M.DATA_ROOT, "Friction", "*.csv")))[:4]:
                shutil.copy(f, os.path.join(tmp, cls))
        rep = M.audit_folder(tmp)
        c = [x for x in rep["checks"] if x["check"].startswith("Brief Touch")]
        assert c, f"contact check missing: {[x['check'] for x in rep['checks']]}"
        assert not c[0]["pass"], f"weak Brief Touch passed: {c[0]['detail']}"
        assert "/4" in c[0]["detail"], f"detail counts pooled files: {c[0]['detail']}"
        adv = " ".join(rep.get("advisories", []))
        assert "Friction" in adv, "Friction strength not surfaced at all"
        return f"weak Brief Touch rejected ({c[0]['detail']}), Friction advisory shown"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_regression_suite() -> None:
    """Run all 51 checks under pytest, reporting every failure at once.

    The checks below are registered with this file's own @test decorator rather
    than being pytest functions, because they were written to run standalone as
    a single readable PASS/FAIL table. This wrapper is what makes
    `pytest tests/` cover them too, so there is one command to run rather than
    two - `python tests/test_regressions.py` still prints the table.
    """
    assert MIX_FILES, f"no Normal Mix CSVs under {MIX_DIR}"
    _results.clear()
    for fn in [v for k, v in sorted(globals().items())
               if k.startswith("t_") and callable(v)]:
        fn()
    failed = [(n, m) for n, ok, m in _results if not ok]
    assert not failed, f"{len(failed)} of {len(_results)} checks failed:\n" + \
        "\n".join(f"  {n}\n      {m}" for n, m in failed)


def run_all() -> int:
    if not MIX_FILES:
        print(f"No Normal Mix CSVs under {MIX_DIR}")
        return 1
    tests = [v for k, v in sorted(globals().items()) if k.startswith("t_") and callable(v)]
    print(f"Regression suite  ({len(MIX_FILES)} Normal Mix files, {len(tests)} checks)\n" + "=" * 78)
    for fn in tests:
        fn()
    width = max(len(n) for n, _, _ in _results)
    passed = sum(1 for _, ok, _ in _results if ok)
    for name, ok, msg in _results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name.ljust(width)}  {msg}")
    print("=" * 78)
    print(f"{passed}/{len(_results)} passed")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(run_all())
