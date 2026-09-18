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
 * It does now: /ws/live_sensor?source=client&permute=1. So this file's whole job is to
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
let serialWatchdogTimer = null;
// Frames arrive every 560 ms (1.79 Hz). 1500 ms is 2.68 frame periods: two
// dropped frames plus 380 ms of jitter trips this.
//
// It was 1000 ms, which put the client AHEAD of the server's own
// SerialFrameSource.IDLE_TIMEOUT_S (1.2 s) - so on a real dropout the page
// declared the stream frozen while the server still thought it was live, which
// is the two-components-disagreeing failure the old comment here warned about.
// At 1500 ms the server decides first and the console confirms, in that order.
//
// This is still a WARNING, not an alarm, and it clears itself on the next valid
// frame instead of latching: a dropout is not evidence that the patient is fine,
// and it is not evidence that they are not. The last known state stays on screen
// and the alarm level is held by the server's debouncer, untouched.
const SERIAL_WATCHDOG_MS = 1500;
const SERIAL_FROZEN_TEXT = 'SENSOR STREAM FROZEN / DISCONNECTED';
let serialStreamFrozen = false;
const MAX_CHART_POINTS = 50;

function setStreamFrozen(frozen) {
  if (serialStreamFrozen === frozen) return;
  serialStreamFrozen = frozen;
  const el = document.getElementById('liveTelemetryRate');
  if (el) {
    el.textContent = frozen ? SERIAL_FROZEN_TEXT : 'STREAMING: 560 ms (1.79 Hz)';
    el.classList.toggle('tag--warn', frozen);
  }
  const banner = document.getElementById('streamFrozenBanner');
  if (banner) banner.style.display = frozen ? '' : 'none';
  if (frozen && typeof showToast === 'function') {
    showToast(SERIAL_FROZEN_TEXT,
              'No valid frame for 1.0 s. Readings on screen are stale.', 'warning');
  }
}

/**
 * Forward a control message (currently only {"event":"reseed"}) to the server
 * over the serial ingest socket. Returns true if it went out.
 *
 * Invariant 1 holds trivially: this file never classifies, and a control event
 * carries no measurement. The server decides what "reseed" means.
 */
function sendSerialControl(payload) {
  if (!webSerialSocket || webSerialSocket.readyState !== WebSocket.OPEN) return false;
  try {
    webSerialSocket.send(payload);
    return true;
  } catch (e) {
    return false;
  }
}

function resetSerialWatchdog() {
  if (!webSerialActive) return;
  // A frame arrived, so whatever is on screen is current again.
  setStreamFrozen(false);
  if (serialWatchdogTimer) {
    clearTimeout(serialWatchdogTimer);
  }
  serialWatchdogTimer = setTimeout(() => {
    if (webSerialActive) {
      // Warn at 1.0 s; do NOT tear the session down here. The server's own
      // SerialFrameSource.IDLE_TIMEOUT_S (1.2 s) owns the disconnect decision,
      // and two components racing to declare the same disconnect is how the
      // UI ended up disagreeing with the server about whether a patch was live.
      setStreamFrozen(true);
    }
  }, SERIAL_WATCHDOG_MS);
}

function stopSerialWatchdog() {
  if (serialWatchdogTimer) {
    clearTimeout(serialWatchdogTimer);
    serialWatchdogTimer = null;
  }
  setStreamFrozen(false);
}

function handleHardwareDisconnect(reason = 'Sensor Disconnected') {
  if (!webSerialActive) return;
  showError(`Web Serial: ${reason}`);
  disconnectWebSerial(reason);
}

// Client-side hardware disconnect listener via navigator.serial
if (typeof navigator !== 'undefined' && navigator.serial && navigator.serial.addEventListener) {
  navigator.serial.addEventListener('disconnect', (event) => {
    if (webSerialActive && (!event.port || event.port === webSerialPort)) {
      handleHardwareDisconnect('Sensor Disconnected');
    }
  });
}

function withKey(url) {
  try {
    const params = new URLSearchParams(window.location.search);
    let key = params.get("key");
    if (key) {
      localStorage.setItem("p2_access_key", key);
      document.cookie = `p2key=${encodeURIComponent(key)}; path=/; max-age=2592000; SameSite=Lax`;
    } else {
      key = localStorage.getItem("p2_access_key");
      if (!key) {
        const match = document.cookie.match(/(?:^|;\s*)p2key=([^;]+)/);
        if (match) key = decodeURIComponent(match[1]);
      }
    }
    if (!key) return url;
    const separator = url.includes("?") ? "&" : "?";
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
  if (typeof state !== 'undefined') {
    state.liveStreaming = true;
    state.mode = 'live';
  }
  document.body.dataset.mode = 'live';
  webSerialLabel(true);
  if (typeof updateLiveStreamButton === 'function') {
    updateLiveStreamButton(true);
  }
  const statEl = document.getElementById('hardwareLinkStatus');
  if (statEl) statEl.textContent = 'USB Web Serial (Live)';

  const liveTelEl = document.getElementById('liveTelemetryStatusText');
  if (liveTelEl) liveTelEl.textContent = 'STREAMING: 560 ms (1.79 Hz)';

  const calibTag = document.getElementById('calibStatusTag');
  if (calibTag) {
    calibTag.textContent = 'Baseline active (25 nodes)';
    calibTag.className = 'tag tag--ok';
  }

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
      ws = new WebSocket(withKey(`${proto}//${window.location.host}/ws/live_sensor?source=client&permute=1`));
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
      if (typeof state !== 'undefined') {
        state.livePackets = (state.livePackets || 0) + 1;
        state.liveFrameCount = (state.liveFrameCount || 0) + 1;
        const countEl = document.getElementById('livePacketCount');
        if (countEl) countEl.textContent = `Live Packets: ${state.livePackets}`;

      }
      renderFrame(msg, 0);
      if (typeof updateLiveChart === 'function') {
        updateLiveChart(msg);
      }
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

async function disconnectWebSerial(reason = 'Standby') {
  stopSerialWatchdog();
  const wasActive = webSerialActive;
  webSerialActive = false;
  if (typeof state !== 'undefined') {
    state.liveStreaming = false;
  }
  webSerialLabel(false);
  if (typeof updateLiveStreamButton === 'function') {
    updateLiveStreamButton(false);
  }
  const statEl = document.getElementById('hardwareLinkStatus');
  const isSensorDisconnect = (reason === 'Sensor Disconnected' || (typeof reason === 'string' && reason.startsWith('Sensor Disconnected')));
  if (statEl) {
    statEl.textContent = isSensorDisconnect ? 'Sensor Disconnected' : reason;
  }

  const calibTag = document.getElementById('calibStatusTag');
  if (calibTag) {
    if (isSensorDisconnect) {
      calibTag.textContent = 'Sensor Disconnected - no hardware signal';
      calibTag.className = 'tag tag--bad';
    } else {
      calibTag.textContent = 'ยังไม่ได้สตรีม - กด Live ก่อน / not streaming, nothing to re-seed';
      calibTag.className = 'tag tag--muted';
    }
  }
  document.body.dataset.mode = 'review';
  if (wasActive && typeof showToast === 'function') {
    if (isSensorDisconnect) {
      showToast('Sensor Disconnected', 'ตรวจพบการตัดการเชื่อมต่อฮาร์ดแวร์หรือไม่มีสัญญาณเกิน 1.5 วินาที / Hardware disconnected or silent > 1.5s', 'error');
    } else {
      showToast('Web Serial Disconnected', 'ตัดการเชื่อมต่อพอร์ต USB เรียบร้อยแล้ว', 'warning');
    }
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

  resetSerialWatchdog();

  try {
    while (webSerialActive) {
      const { value, done } = await reader.read();
      if (done) break;
      if (!value) continue;
      buffer += value;
      // Resynchronise, do not truncate.
      //
      // This used to be buffer.slice(-4096), which keeps the last 4,096 CHARS -
      // an arbitrary byte offset that lands in the middle of a line. The
      // surviving head is then a partial frame with fewer tokens, and while
      // sendFrameLine() drops it on the token count, the failure mode is worse
      // than that: a device emitting no delimiters at all (a wedged link, a
      // wrong baud rate) fills the buffer with garbage that is never cleared,
      // and when real frames resume the leading garbage is still glued to the
      // first of them.
      //
      // Cutting at the last newline instead means the buffer always restarts on
      // a real frame boundary. With no delimiter anywhere in 4,096 chars there
      // is no frame boundary to keep, so the whole buffer goes - that is the
      // resync. The watchdog above is what tells the operator it happened.
      if (buffer.length > 4096) {
        const lastBreak = buffer.lastIndexOf('\n');
        buffer = lastBreak >= 0 ? buffer.slice(lastBreak + 1) : '';
      }
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        // Bound max line length at 512 chars
        if (line.length <= 512) {
          sendFrameLine(line);
        }
      }
    }
  } catch (err) {
    if (webSerialActive) {
      showError(`Web Serial read ended: ${err.message}`);
      disconnectWebSerial('Sensor Disconnected');
    }
  } finally {
    stopSerialWatchdog();
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
  if (!line || line.length > 512) return;
  const trimmed = line.trim();
  if (!trimmed || trimmed.length > 512 || trimmed.startsWith('#')) return;
  if (!webSerialSocket || webSerialSocket.readyState !== WebSocket.OPEN) return;
  if (webSerialSocket.bufferedAmount >= 65536) return;

  const parts = trimmed.replace(/,/g, ' ').split(/\s+/).filter((p) => p.length);
  // Validate token counts (25 <= N <= 28) before parsing to prevent framing noise and channel misalignment
  if (parts.length < 25 || parts.length > 28) return;

  const vals = [];
  for (let i = 0; i < 25; i++) {
    const v = parseFloat(parts[i]);
    if (!Number.isFinite(v)) return;             // garbled frame: drop it whole
    vals.push(v);
  }
  webSerialSocket.send(JSON.stringify({ raw_frame: vals }));
  resetSerialWatchdog();
}
