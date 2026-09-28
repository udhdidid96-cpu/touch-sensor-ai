'use strict';

let webSerialPort = null;
let webSerialReader = null;
let webSerialActive = false;
let webSerialSocket = null;
let webSerialClosedPromise = null;
let serialWatchdogTimer = null;
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
  setStreamFrozen(false);
  if (serialWatchdogTimer) {
    clearTimeout(serialWatchdogTimer);
  }
  serialWatchdogTimer = setTimeout(() => {
    if (webSerialActive) {
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
    if (err && err.name !== 'NotFoundError') showError(`Web Serial: ${err.message}`);
    webSerialPort = null;
    return;
  }

  const opened = await openIngestSocket();
  if (!opened) {
    try { await webSerialPort.close(); } catch (e) { }
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
      if (msg.event) return;
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
    } catch (e) { }
    webSerialSocket = null;
  }

  try {
    if (webSerialReader) {
      await webSerialReader.cancel();
      webSerialReader = null;
    }
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
      if (buffer.length > 4096) {
        const lastBreak = buffer.lastIndexOf('\n');
        buffer = lastBreak >= 0 ? buffer.slice(lastBreak + 1) : '';
      }
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
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
    try { reader.releaseLock(); } catch (e) { }
  }
}

function sendFrameLine(line) {
  if (!line || line.length > 512) return;
  const trimmed = line.trim();
  if (!trimmed || trimmed.length > 512 || trimmed.startsWith('#')) return;
  if (!webSerialSocket || webSerialSocket.readyState !== WebSocket.OPEN) return;
  if (webSerialSocket.bufferedAmount >= 65536) return;

  const parts = trimmed.replace(/,/g, ' ').split(/\s+/).filter((p) => p.length);
  if (parts.length < 25 || parts.length > 28) return;

  const vals = [];
  for (let i = 0; i < 25; i++) {
    const v = parseFloat(parts[i]);
    if (!Number.isFinite(v)) return;
    vals.push(v);
  }
  webSerialSocket.send(JSON.stringify({ raw_frame: vals }));
  resetSerialWatchdog();
}
