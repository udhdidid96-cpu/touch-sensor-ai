/**
 * Web Serial: read the board over USB in the browser, classify on the server.
 *
 * WHAT THIS FILE USED TO DO, AND WHY IT DOESN'T ANYMORE
 * -----------------------------------------------------
 * This was a complete second implementation of the detection pipeline, written
 * in JavaScript, running on the operator's machine. It diverged from main.py on
 * every point that mattered:
 *
 *   * no AlarmDebouncer - `severity_level` was the raw per-frame class, so the
 *     one component that carries essentially all of the false-alarm suppression
 *     was simply absent and any single noisy frame sounded the red siren;
 *   * no PAD_ORDER - SerialFrameSource permutes Signal-* frames into pad order
 *     and this did not, so the same board was read in two different patch
 *     orientations depending on which button the operator pressed;
 *   * the trained forest was never consulted; the final branch hard-coded
 *     level 1 with p(touch) = 0.8;
 *   * `baseline += 0.05 * diff` is a fixed-gain EMA, not the gated Kalman filter
 *     (q=0.5, r=40), so the deltas differed from the server's for the same
 *     signal;
 *   * no disconnect guard, so connecting to a dead board seeded the baseline
 *     from zeros and then displayed a reassuring green "Normal" indefinitely;
 *   * `.filter(x => !isNaN(x))` silently dropped a garbled token and shifted
 *     every subsequent channel by one position, where the server rejects the
 *     line;
 *   * disconnecting never cleared the baseline, so reconnecting to a different
 *     patch produced deltas against the old sensor and an instant false L3.
 *
 * It only existed because main.py had no way to accept frames from a client.
 * It does now: /ws/live_sensor?source=client. So this file's whole job is to
 * move bytes - read lines from the port, push {"raw_frame": [...]} up, and hand
 * whatever comes back to renderFrame(). Every decision is made once, on the
 * server, by classify_deltas().
 *
 * Frames are sent in firmware order (Signal-1..25) exactly as the board emits
 * them; the server applies the pad permutation. Do not reorder them here.
 */

'use strict';

let webSerialPort = null;
let webSerialReader = null;
let webSerialActive = false;
let webSerialSocket = null;
let webSerialClosedPromise = null;
const MAX_CHART_POINTS = 50;

function withKey(url) {
  try {
    const params = new URLSearchParams(window.location.search);
    const key = params.get('key');
    if (!key) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}key=${encodeURIComponent(key)}`;
  } catch (e) {
    return url;
  }
}

function showError(msg) {
  if (typeof showToast === 'function') {
    showToast('Web Serial', msg, 'error');
  } else {
    console.error('Web Serial Error:', msg);
  }
}

function clearError() {
  // Clear any existing transient errors if needed
}

function webSerialLabel(active) {
  const btn = document.getElementById('btnWebSerial');
  if (!btn) return;
  btn.textContent = active ? 'Stop Web Serial' : 'Web Serial (USB Direct)';
  btn.classList.toggle('btn--danger', active);
}

async function toggleWebSerial() {
  if (webSerialActive) {
    await disconnectWebSerial();
    return;
  }

  if (!navigator.serial) {
    showError('This browser does not support the Web Serial API. Use Chrome or Edge on a desktop, or select the port under COM and press Start Live Monitoring instead.');
    return;
  }

  try {
    const existingPorts = await navigator.serial.getPorts();
    if (existingPorts && existingPorts.length === 1) {
      webSerialPort = existingPorts[0];
      try {
        await webSerialPort.open({ baudRate: 115200 });
      } catch (openErr) {
        webSerialPort = await navigator.serial.requestPort();
        await webSerialPort.open({ baudRate: 115200 });
      }
    } else {
      webSerialPort = await navigator.serial.requestPort();
      await webSerialPort.open({ baudRate: 115200 });
    }
  } catch (err) {
    // Includes the user dismissing the port picker, which is not an error.
    if (err && err.name !== 'NotFoundError') showError(`Web Serial: ${err.message}`);
    webSerialPort = null;
    return;
  }

  const opened = await openIngestSocket();
  if (!opened) {
    try { await webSerialPort.close(); } catch (e) { /* ignore */ }
    webSerialPort = null;
    return;
  }

  webSerialActive = true;
  document.body.dataset.mode = 'live';
  webSerialLabel(true);
  if (typeof showToast === 'function') {
    showToast('Web Serial Connected', 'เชื่อมต่อบอร์ด Smart Dressing ผ่าน USB สำเร็จ (115200 Baud)', 'success');
  }
  if (typeof playChime === 'function') {
    playChime('connect');
  }
  readWebSerialStream();
}

/**
 * Open the ingest socket and route every response through the normal renderer.
 */
function openIngestSocket() {
  return new Promise((resolve) => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws;
    try {
      ws = new WebSocket(withKey(`${proto}//${window.location.host}/ws/live_sensor?source=client`));
    } catch (e) {
      showError(`Cannot open the ingest socket: ${e.message}`);
      resolve(false);
      return;
    }

    ws.onopen = () => { clearError(); resolve(true); };
    ws.onerror = () => { showError('Ingest socket error.'); resolve(false); };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.error) { showError(msg.error); return; }
      if (msg.event) return;                     // started / finished
      // Exactly the same payload shape the replay and serial sources produce,
      // so it goes through exactly the same renderer.
      state.frames.push(msg);
      if (state.frames.length > MAX_CHART_POINTS) state.frames.shift();
      state.idx = state.frames.length - 1;
      renderFrame(msg, 0);
      if (typeof drawHeatmapGaussian === 'function') drawHeatmapGaussian(msg.deltas);
      paintChart(state.frames);
    };
    ws.onclose = () => {
      webSerialSocket = null;
      if (webSerialActive) {
        showError('Ingest socket closed; stopping Web Serial.');
        disconnectWebSerial();
      }
    };
    webSerialSocket = ws;
  });
}

async function disconnectWebSerial() {
  webSerialActive = false;
  webSerialLabel(false);
  document.body.dataset.mode = 'review';
  if (typeof showToast === 'function') {
    showToast('Web Serial Disconnected', 'ตัดการเชื่อมต่อพอร์ต USB เรียบร้อยแล้ว', 'warning');
  }
  if (typeof playChime === 'function') {
    playChime('disconnect');
  }

  if (webSerialSocket) {
    try {
      if (webSerialSocket.readyState === WebSocket.OPEN) {
        webSerialSocket.send(JSON.stringify({ event: 'stop' }));
      }
      webSerialSocket.close();
    } catch (e) { /* already closing */ }
    webSerialSocket = null;
  }

  try {
    if (webSerialReader) {
      await webSerialReader.cancel();
      webSerialReader = null;
    }
    // pipeTo() rejects when the stream is cancelled; awaiting it here is what
    // stops that becoming an unhandled promise rejection.
    if (webSerialClosedPromise) {
      await webSerialClosedPromise.catch(() => {});
      webSerialClosedPromise = null;
    }
    if (webSerialPort) {
      await webSerialPort.close();
      webSerialPort = null;
    }
  } catch (e) {
    console.warn('Web Serial close:', e);
  }
  // No client-side baseline to reset - the server owns the Kalman state, and it
  // gets a fresh LivePipeline per socket. That is what stops a reconnect to a
  // different patch from being measured against the previous one's baseline.
}

async function readWebSerialStream() {
  const textDecoder = new TextDecoderStream();
  webSerialClosedPromise = webSerialPort.readable.pipeTo(textDecoder.writable);
  const reader = textDecoder.readable.getReader();
  webSerialReader = reader;
  let buffer = '';

  try {
    while (webSerialActive) {
      const { value, done } = await reader.read();
      if (done) break;
      if (!value) continue;
      buffer += value;
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) sendFrameLine(line);
    }
  } catch (err) {
    if (webSerialActive) {
      showError(`Web Serial read ended: ${err.message}`);
      disconnectWebSerial();
    }
  } finally {
    try { reader.releaseLock(); } catch (e) { /* ignore */ }
  }
}

/**
 * Parse one line and forward it verbatim. No classification, no reordering.
 *
 * A malformed line is DROPPED, not repaired. The previous version filtered out
 * non-numeric tokens and then took the first 25 of what was left, which silently
 * shifted every channel after the bad token by one position - a mis-mapped patch
 * that looks like valid data.
 */
function sendFrameLine(line) {
  const trimmed = line.trim();
  if (!trimmed || trimmed.startsWith('#')) return;
  if (!webSerialSocket || webSerialSocket.readyState !== WebSocket.OPEN) return;

  const parts = trimmed.replace(/,/g, ' ').split(/\s+/).filter((p) => p.length);
  if (parts.length < 25) return;

  const vals = [];
  for (let i = 0; i < 25; i++) {
    const v = parseFloat(parts[i]);
    if (!Number.isFinite(v)) return;             // garbled frame: drop it whole
    vals.push(v);
  }
  webSerialSocket.send(JSON.stringify({ raw_frame: vals }));
}
