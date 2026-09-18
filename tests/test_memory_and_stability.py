"""Feature F15: Memory Stability & Audio Node Recycling Suite.

Tests:
  1. 10,000-frame telemetry ring buffer boundedness (labels.length <= 50)
  2. Memory footprint stability in LivePipeline over 10,000 frames
  3. Web Audio node lifecycle cleanup, onended disconnect, and fallback timers in web/app.js
  4. WebSerial chunk buffer (<=4KB) and line length (<=512 chars) bounds in web/web_serial.js
"""
from __future__ import annotations

import os
import re
import subprocess
import numpy as np
import pytest

import main as M
from main import (
    LivePipeline,
    N_PADS,
    BASELINE_COUNTS,
)


def test_telemetry_ring_buffer_bounds_over_10000_frames():
    """F6/F15: Test simulated Chart.js ring buffer over 10,000 frames to ensure

    strict bounding at <= 50 entries and zero unbounded array growth.
    """
    # Execute actual JavaScript engine logic via Node.js
    js_code = """
    const state = {
      chart: {
        data: {
          labels: [],
          datasets: [
            { data: [] }, // delta_min
            { data: [] }, // delta_max
            { data: [] }  // cpri
          ]
        }
      }
    };

    function updateLiveChart(msg) {
      const t = msg.time_sec.toFixed(1);
      state.chart.data.labels.push(t);
      state.chart.data.datasets[0].data.push(msg.min_delta);
      state.chart.data.datasets[1].data.push(msg.max_delta);
      state.chart.data.datasets[2].data.push(msg.cpri_percent);

      while (state.chart.data.labels.length > 50) {
        state.chart.data.labels.shift();
        state.chart.data.datasets.forEach(ds => ds.data.shift());
      }
    }

    // Simulate 1,000 prior frames from review mode
    for (let i = 0; i < 1000; i++) {
      state.chart.data.labels.push(i.toString());
      state.chart.data.datasets.forEach(ds => ds.data.push(i));
    }

    // Now push 10,000 live streaming frames
    for (let i = 0; i < 10000; i++) {
      updateLiveChart({
        time_sec: i * 0.28,
        min_delta: -50.0,
        max_delta: 120.0,
        cpri_percent: 5.0
      });

      if (state.chart.data.labels.length > 50) {
        console.error(`Ring buffer overflowed: ${state.chart.data.labels.length}`);
        process.exit(1);
      }
      for (const ds of state.chart.data.datasets) {
        if (ds.data.length > 50) {
          console.error(`Dataset array overflowed: ${ds.data.length}`);
          process.exit(2);
        }
      }
    }

    console.log(JSON.stringify({
      final_label_count: state.chart.data.labels.length,
      final_dataset_count: state.chart.data.datasets[0].data.length
    }));
    """
    proc = subprocess.run(["node", "-e", js_code], capture_output=True, text=True)
    assert proc.returncode == 0, f"Node.js ring buffer test failed: {proc.stderr}"
    assert '"final_label_count":50' in proc.stdout
    assert '"final_dataset_count":50' in proc.stdout


def test_live_pipeline_memory_stability_10000_frames():
    """F15: Run 10,000 frames through LivePipeline and verify zero unbounded state accumulation."""
    pipe = LivePipeline(model=None, warmup_frames=3)

    for i in range(10000):
        val = BASELINE_COUNTS + (i % 20) - 10.0
        pipe.process(np.full(N_PADS, val))

    # Assert internal debouncer history is strictly capped by its window
    assert len(pipe.alarm._history) <= pipe.alarm.window
    # Assert kalman filter state is fixed shape
    assert pipe.kalman.b.shape == (N_PADS,)
    # Assert peel tracker state does not accumulate unbounded memory
    assert isinstance(pipe.peel.streak, int)
    assert pipe.index == 10000


def test_web_audio_node_lifecycle_in_app_js():
    """F7/F15: Verify web/app.js cleans up Web Audio nodes with onended handlers and fallback timers."""
    app_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Verify osc.onended disconnects both oscillator and gain nodes
    assert "osc.onended = () => {" in content
    assert "osc.disconnect();" in content
    assert "gain.disconnect();" in content

    # 2. Verify fallback timer for node cleanup
    assert "setTimeout(cleanup," in content or "setTimeout(() => cleanup()" in content

    # 3. Verify siren debouncing to prevent audio node storms
    assert "lastSirenTime" in content
    assert "nowMs - lastSirenTime < 300" in content or "nowMs - lastSirenTime" in content

    # 4. Verify singleton AudioContext initialization pattern
    assert "state.audioCtx" in content


def test_webserial_buffer_capping_in_web_serial_js():
    """F8/F15: Verify web/web_serial.js caps chunk buffer at 4KB, line length at 512, and bounds tokens."""
    ws_js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web", "web_serial.js")
    with open(ws_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Chunk buffer capped at 4096 characters.
    #
    # This used to also assert the literal "buffer.slice(-4096)". That pinned
    # HOW the cap was enforced, and the how was wrong: slicing at a byte offset
    # lands mid-line, so a link emitting no delimiters kept 4,096 chars of
    # garbage that stayed glued to the first frame when the stream resumed. The
    # cap is what this test is for and the cap is still here; the guard now
    # resynchronises to a frame boundary, which tests/test_serial_framing.py
    # checks. "A guard that greps for a name is not a guard" - AGENTS.md.
    assert "buffer.length > 4096" in content

    # 2. Max line length capped at 512 characters
    assert "line.length > 512" in content

    # 3. Token count bounded between 25 and 28 tokens
    assert "parts.length < 25 || parts.length > 28" in content

    # 4. Silence watchdog is active. The number is not pinned here either:
    #    tests/test_serial_framing.py holds the constraint that matters, which
    #    is that the client warns AFTER the server's own IDLE_TIMEOUT_S rather
    #    than before it. Pinning 1000 ms froze in the ordering that made the
    #    page and the server disagree about whether a patch was live.
    assert "SERIAL_WATCHDOG_MS" in content
    assert "SENSOR STREAM FROZEN / DISCONNECTED" in content
