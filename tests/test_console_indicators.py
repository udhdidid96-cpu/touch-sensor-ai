"""Alarm-signal priority, baseline drift and CQI: computed by the server, rendered by the page.

These are anchored on behaviour: what the server sends for a given level or frame,
and that the page reads those fields instead of deriving them.
"""
import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest

import main as M

APP_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "app.js")


@pytest.mark.parametrize("level,priority,colour", [
    (3, "high", "red"), (2, "medium", "yellow"), (1, "info", None), (0, "none", None)])
def test_alarm_signal_priority_follows_debounced_level(level, priority, colour):
    sig = M.alarm_signal(level)
    assert sig["priority"] == priority and sig["colour"] == colour
    if priority == "high":
        assert 1.4 <= sig["flash_hz"] <= 2.8 and 0.2 <= sig["duty_cycle"] <= 0.6
    if priority == "medium":
        assert 0.4 <= sig["flash_hz"] <= 0.8 and 0.2 <= sig["duty_cycle"] <= 0.6
    assert "Not assessed" in sig["reference"]


def test_signal_loss_is_a_technical_alarm_and_warmup_is_silent():
    lost = M.alarm_signal(3, disconnected=True)
    assert lost["condition"] == "technical" and lost["priority"] == "medium"
    assert M.alarm_signal(3, warming=True)["priority"] == "none"


def test_signal_quality_components_and_drift():
    seed = np.full(M.N_PADS, 28000.0)
    q = M.signal_quality(seed, seed, 0.0)
    assert q["cqi"] == 100.0 and q["drift"]["max_abs"] == 0.0
    drifted = seed.copy()
    drifted[6] += 200.0
    q = M.signal_quality(drifted, seed, M.NOISE_GATE_COUNTS / 2, [0.0, 8.0])
    assert q["drift"]["max_abs_pad"] == 7 and q["drift"]["n_over_noise_gate"] == 1
    assert q["components"]["quiet"] == 0.5 and q["components"]["stable"] == 0.96
    assert 0.0 < q["cqi"] < 100.0 and q["drift"]["rate_counts_per_min"] > 0
    assert len(q["drift"]["per_pad"]) == M.N_PADS
    loose = M.signal_quality(np.full(M.N_PADS, 27000.0), np.full(M.N_PADS, 27000.0), 0.0)
    assert loose["cqi"] == 0.0, "a patch resting below the attached band cannot score as good contact"


def test_live_pipeline_frames_carry_the_indicators(model, dataset):
    pipe = M.LivePipeline(model)
    raw = M.read_raw_csv(M.os.path.join(M.DATA_ROOT, dataset.files[0]))
    outs = [pipe.process(f) for f in raw[:12]]
    for o in outs:
        assert o["alarm_signal"]["priority"] in M.ALARM_SIGNALS
        assert o["signal_quality"]["cqi"] is None or 0.0 <= o["signal_quality"]["cqi"] <= 100.0
    assert outs[-1]["signal_quality"]["drift"] is not None
    assert pipe.process(np.zeros(M.N_PADS))["alarm_signal"]["condition"] == "technical"


def test_replay_frames_carry_the_indicators(client, sample_csv):
    body = client.get(f"/api/v5/dataset/{sample_csv}", params={"calibration": "kalman"}).json()
    fr = body["frames"][-1]
    assert fr["alarm_signal"]["priority"] == M.alarm_signal(fr["severity_level"])["priority"]
    assert len(fr["signal_quality"]["drift"]["per_pad"]) == M.N_PADS


def test_page_renders_the_server_priority_instead_of_deriving_it(client):
    js = client.get("/static/app.js").text
    page = client.get("/").text
    assert "alarm_signal" in js and "signal_quality" in js
    assert re.search(r'id="alarmAnnunciator"', page) and re.search(r'id="cqiValue"', page)
    # the page must not map severity onto a priority of its own
    assert not re.search(r"severity_level\s*>=?\s*\d[^\n]{0,80}(high|medium)", js)


def test_touch_has_its_own_sound_and_is_not_an_alarm():
    touch, peel, detach = (M.alarm_signal(level) for level in (1, 2, 3))
    assert touch["priority"] == "info" and touch["condition"] is None
    assert len({touch["sound"], peel["sound"], detach["sound"], "none"}) == 4


# Runs the page's own siren() in node with a fake AudioContext and a fake clock.
_SIREN_HARNESS = r"""
const src = require('fs').readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('const SIREN_REPEAT_MS'), end = src.indexOf('function playChime');
if (start < 0 || end < start) throw new Error('siren block not found in app.js');
let now = 0, current = [];
class Ctx {
  constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }
  createOscillator() {
    const o = { type: '', frequency: { setValueAtTime: f => { o.f = f; } },
                connect() {}, disconnect() {}, stop() {}, start() { current.push(o.type + ':' + o.f); } };
    return o;
  }
  createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {}, disconnect() {} }; }
  resume() {}
}
Date.now = () => now;
global.setTimeout = () => 0;
const run = (frames, muted) => {
  const siren = new Function('state', 'window', src.slice(start, end) + '\nreturn siren;')(
    { isMuted: !!muted, audioCtx: null }, { AudioContext: Ctx });
  const bursts = [];
  for (const [t, prio] of frames) {
    now = t; current = [];
    siren(prio === 'none' ? null : { priority: prio, condition: null });
    if (current.length) bursts.push({ t, tones: current });
  }
  return bursts;
};
const held = (prio, secs, t0 = 0) => Array.from({ length: Math.floor(secs / 0.56) + 1 }, (_, i) => [t0 + i * 560, prio]);
console.log(JSON.stringify({
  touch_held: run(held('info', 30)),
  touch_twice: run([...held('info', 3), ...held('none', 3, 3500), ...held('info', 3, 7000)]),
  peel_held: run(held('medium', 12)),
  detach_held: run(held('high', 5)),
  muted: run(held('high', 5), true),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_console_touch_chime_sounds_once_per_contact_and_differs_from_alarms(tmp_path):
    harness = tmp_path / "siren_harness.js"
    harness.write_text(_SIREN_HARNESS, encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(harness), APP_JS], capture_output=True, text=True,
                                    check=True, timeout=60).stdout)
    assert len(out["touch_held"]) == 1, "touch must chime once when contact begins, not repeat"
    assert len(out["touch_twice"]) == 2, "a new contact must chime again"
    assert [b["t"] for b in out["peel_held"]] == [0, 5040, 10080]
    assert [b["t"] for b in out["detach_held"]] == [0, 2240, 4480]
    assert out["muted"] == []
    touch, peel, detach = (set(out[k][0]["tones"]) for k in ("touch_held", "peel_held", "detach_held"))
    assert not (touch & peel or touch & detach or peel & detach), (touch, peel, detach)
