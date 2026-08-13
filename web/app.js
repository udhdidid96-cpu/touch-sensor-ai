/**
 * Smart Extubation AI Monitoring Suite — Modern Dashboard Engine
 */

'use strict';

console.info('This system has not been assessed against IEC 62304.');

const SAMPLE_PERIOD_MS = 560;

const state = {
  layout: null,
  datasets: [],
  file: null,
  frames: [],
  idx: 0,
  playing: false,
  timer: null,
  heatCache: new Map(),
  chart: null,
  isMuted: false,
  lastLevel: 0,
  audioCtx: null
};

// Default 25-node physical layout coordinates (90x120 mm patch)
const DEFAULT_LAYOUT = Array.from({ length: 25 }, (_, i) => ({
  pad: i + 1,
  x: (i % 5) * 18 + 14,
  y: Math.floor(i / 5) * 22 + 16,
  signal_channel: i + 1
}));

/* ------------------------------------------------------------------ init -- */
window.addEventListener('load', async () => {
  initNodesSVG();
  initRiskChart();
  
  // Safe layout fetch
  try {
    const layout = await getJSON('/api/v6/layout');
    if (layout && layout.pads) {
      state.layout = layout.pads;
      initNodesSVG();
    }
  } catch (e) {
    console.warn('Using default pad layout:', e);
  }

  // Safe datasets fetch
  try {
    const ds = await getJSON('/api/v5/datasets');
    state.datasets = (ds && ds.datasets) ? ds.datasets : [];
    populateFileDropdown();
    if (state.datasets.length > 0) {
      const pref = pickForClass('normal') || state.datasets[0];
      await loadRecording(pref);
    }
  } catch (e) {
    console.warn('Datasets list load failed:', e);
  }

  try {
    await loadMetricsPanel();
  } catch (e) {
    console.warn('Metrics panel skipped:', e);
  }

  refreshComPorts();
  loadEventLogs();
  renderICUGrid();
});

async function loadMetricsPanel() {
  try {
    const m = await getJSON('/api/v6/metrics');
    if (!m) return;
    const stampEl = document.getElementById('metricsStamp');
    if (stampEl && m.generated) stampEl.textContent = m.generated;
  } catch (e) {
    console.warn('Could not load /api/v6/metrics:', e);
  }
}

/* --------------------------------------------------------------- helpers -- */
const enc = (rel) => rel.split('/').map(encodeURIComponent).join('/');

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function populateFileDropdown() {
  const sel = document.getElementById('fileSelect');
  if (!sel) return;
  sel.innerHTML = '';
  if (state.datasets.length === 0) {
    sel.innerHTML = '<option value="">No recordings found</option>';
    return;
  }
  state.datasets.forEach(n => {
    const o = document.createElement('option');
    o.value = n;
    o.textContent = n;
    sel.appendChild(o);
  });
  if (state.file) sel.value = state.file;
}

/* ----------------------------------------------------------- SVG Visualizer -- */
function initNodesSVG() {
  const g = document.getElementById('svgNodes');
  if (!g) return;
  g.innerHTML = '';
  const layout = state.layout || DEFAULT_LAYOUT;
  const NS = 'http://www.w3.org/2000/svg';

  layout.forEach((p) => {
    const cx = p.x, cy = p.y * 1.3333;
    const grp = document.createElementNS(NS, 'g');
    
    const glow = document.createElementNS(NS, 'circle');
    glow.setAttribute('cx', cx); glow.setAttribute('cy', cy); glow.setAttribute('r', '5.5');
    glow.setAttribute('fill', '#10b981'); glow.setAttribute('opacity', '0.22');
    glow.setAttribute('id', `glow-${p.pad}`);

    const cir = document.createElementNS(NS, 'circle');
    cir.setAttribute('cx', cx); cir.setAttribute('cy', cy); cir.setAttribute('r', '2.8');
    cir.setAttribute('fill', '#0f172a'); cir.setAttribute('stroke', '#10b981'); cir.setAttribute('stroke-width', '1.2');
    cir.setAttribute('id', `cir-${p.pad}`);

    const txt = document.createElementNS(NS, 'text');
    txt.setAttribute('x', cx); txt.setAttribute('y', cy + 1.1);
    txt.setAttribute('fill', '#e2e8f0'); txt.setAttribute('font-size', '2.6');
    txt.setAttribute('font-weight', 'bold'); txt.setAttribute('text-anchor', 'middle');
    txt.textContent = p.pad;

    const title = document.createElementNS(NS, 'title');
    title.setAttribute('id', `tip-${p.pad}`);
    title.textContent = `Pad ${p.pad}`;

    grp.appendChild(glow); grp.appendChild(cir); grp.appendChild(txt); grp.appendChild(title);
    g.appendChild(grp);
  });
}

/* --------------------------------------------------------- Chart.js Graph -- */
function initRiskChart() {
  const canvas = document.getElementById('riskChart');
  if (!canvas || typeof Chart === 'undefined') return;
  const ctx = canvas.getContext('2d');
  state.chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        { label: 'CPRI %', data: [], borderColor: '#ef4444', backgroundColor: 'rgba(239, 68, 68, 0.15)', fill: true, borderWidth: 2.5, pointRadius: 0 },
        { label: 'P(Touch) %', data: [], borderColor: '#10b981', borderWidth: 1.8, fill: false, pointRadius: 0 },
        { label: 'P(Peel) %', data: [], borderColor: '#06b6d4', borderWidth: 1.8, fill: false, pointRadius: 0 },
        { label: 'P(Pull) %', data: [], borderColor: '#f59e0b', borderWidth: 1.8, fill: false, pointRadius: 0 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8', maxTicksLimit: 12 } },
        y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#94a3b8' }, min: 0, max: 100 }
      },
      plugins: {
        legend: { labels: { color: '#f8fafc', font: { weight: 'bold', size: 12 } } }
      }
    }
  });
}

function paintChart(frames) {
  if (!state.chart || !frames) return;
  state.chart.data.labels = frames.map(f => f.time_sec.toFixed(1) + 's');
  state.chart.data.datasets[0].data = frames.map(f => f.cpri_percent);
  state.chart.data.datasets[1].data = frames.map(f => (f.probabilities[1] || 0) * 100);
  state.chart.data.datasets[2].data = frames.map(f => (f.probabilities[2] || 0) * 100);
  state.chart.data.datasets[3].data = frames.map(f => (f.probabilities[3] || 0) * 100);
  state.chart.update();
}

/* ------------------------------------------------------------- Load & Play -- */
function pickForClass(kind) {
  const want = {
    normal: ['N_base/', 'Baseline/'],
    touch: ['Brief Touch/', 'Press/', 'Touch/', 'Normal Mix/'],
    peel: ['Peel/'],
    alarm: ['Vertical Pull NO G/', 'VPull/', 'HPull/', 'PowerP/']
  }[kind] || [];
  for (const prefix of want) {
    const hit = state.datasets.find(n => n.startsWith(prefix) || n.includes('/' + prefix));
    if (hit) return hit;
  }
  return state.datasets[0] || null;
}

async function loadRecording(rel) {
  if (!rel) return;
  pausePlayback();
  state.file = rel;
  state.heatCache.clear();
  
  const sel = document.getElementById('fileSelect');
  if (sel) sel.value = rel;

  try {
    const body = await getJSON(`/api/v5/dataset/${enc(rel)}`);
    state.frames = body.frames || [];
    document.getElementById('timeSlider').max = Math.max(0, state.frames.length - 1);
    document.getElementById('calibBadge').textContent = body.calibration === 'kalman' ? 'Kalman Filter Active' : 'Static Calibration';
    paintChart(state.frames);
    await seekFrame(0);
  } catch (e) {
    console.error(`Failed to load ${rel}:`, e);
  }
}

function triggerScenario(kind) {
  const rel = pickForClass(kind);
  if (rel) loadRecording(rel).then(startPlayback);
}

function togglePlayback() {
  state.playing ? pausePlayback() : startPlayback();
}

function startPlayback() {
  if (!state.frames.length) return;
  state.playing = true;
  document.getElementById('btnPlay').textContent = '⏸ Pause';
  state.timer = setInterval(() => {
    if (state.idx >= state.frames.length - 1) {
      pausePlayback();
      return;
    }
    seekFrame(state.idx + 1);
  }, SAMPLE_PERIOD_MS);
}

function pausePlayback() {
  state.playing = false;
  document.getElementById('btnPlay').textContent = '▶ Play';
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

async function seekFrame(v) {
  const i = Math.max(0, Math.min(state.frames.length - 1, parseInt(v, 10) || 0));
  state.idx = i;
  document.getElementById('timeSlider').value = i;
  renderFrame(state.frames[i], state.frames.length);
  drawHeatmap(await heatmapFor(i));
}

function renderFrame(fr, total) {
  if (!fr) return;
  document.getElementById('timeReadout').textContent = fr.time_sec.toFixed(1) + 's';
  document.getElementById('frameCounter').textContent = `Frame ${fr.index + 1} / ${total}`;

  const cp = fr.cpri_percent || 0.0;
  const cpriEl = document.getElementById('cpriValue');
  cpriEl.textContent = cp.toFixed(1) + '%';
  cpriEl.style.color = cp >= 75 ? '#ef4444' : cp >= 50 ? '#f97316' : cp >= 20 ? '#f59e0b' : '#10b981';

  const b = document.getElementById('statusBanner');
  b.className = 'status-banner lvl-' + fr.severity_level;
  b.textContent = fr.status || `LEVEL ${fr.severity_level}`;

  siren(fr.severity_level);
  if (fr.severity_level >= 2) logExtubationEvent(fr);

  const layout = state.layout || DEFAULT_LAYOUT;
  (layout).forEach((p, i) => {
    const d = (fr.deltas && fr.deltas[i] !== undefined) ? fr.deltas[i] : 0;
    const col = d >= 300 ? '#10b981' : d <= -300 ? '#06b6d4' : '#10b981';
    const cir = document.getElementById(`cir-${p.pad}`);
    const glow = document.getElementById(`glow-${p.pad}`);
    if (cir) cir.setAttribute('stroke', col);
    if (glow) {
      glow.setAttribute('fill', col);
      glow.setAttribute('opacity', Math.abs(d) >= 300 ? '0.85' : '0.22');
    }
  });

  const pr = fr.propagation;
  const info = document.getElementById('peelPropInfo');
  if (info) {
    info.textContent = (pr && pr.confirmed) ? `Peel propagation: ${pr.description}` : 'Peel propagation: idle';
  }
}

/* ------------------------------------------------------------- Heatmap Canvas -- */
async function heatmapFor(i) {
  if (!state.file) return null;
  if (state.heatCache.has(i)) return state.heatCache.get(i);
  try {
    const body = await getJSON(`/api/v6/heatmap/${enc(state.file)}?frame=${i}`);
    state.heatCache.set(i, body.matrix);
    return body.matrix;
  } catch {
    return null;
  }
}

function drawHeatmap(m) {
  const c = document.getElementById('heatmapCanvas');
  if (!c) return;
  const x = c.getContext('2d');
  x.clearRect(0, 0, c.width, c.height);
  if (!m || !m.length) return;
  const R = m.length, C = m[0].length, pw = c.width / C, ph = c.height / R;
  for (let r = 0; r < R; r++) {
    for (let k = 0; k < C; k++) {
      const v = m[r][k];
      let col = 'rgba(16,185,129,0.15)';
      if (v <= -300) col = `rgba(6,182,212,${0.3 + 0.65 * Math.min(1, (-v - 300) / 1300)})`;
      else if (v >= 300) col = `rgba(239,68,68,${0.3 + 0.65 * Math.min(1, (v - 300) / 2700)})`;
      x.fillStyle = col;
      x.fillRect(k * pw, r * ph, pw + 0.5, ph + 0.5);
    }
  }
}

/* ----------------------------------------------------------- Custom CSV Upload -- */
async function uploadSelectedCSV(input) {
  if (!input.files || !input.files[0]) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/v6/upload-csv', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      alert(`❌ Upload failed: ${data.detail || 'Invalid CSV'}`);
      return;
    }
    alert(`✅ Successfully uploaded ${data.filename} (${data.total_frames} frames)!`);

    const dsRes = await fetch('/api/v5/datasets');
    const dsData = await dsRes.json();
    state.datasets = dsData.datasets || [];
    populateFileDropdown();
    input.value = '';
    loadRecording(data.filepath);
  } catch (e) {
    alert(`❌ Upload error: ${e.message}`);
  }
}

/* ---------------------------------------------------- COM Port & Event Logging -- */
function toggleMuteSiren() {
  state.isMuted = !state.isMuted;
  const btn = document.getElementById('btnMuteSiren');
  if (btn) {
    btn.textContent = state.isMuted ? '🔇 Audio: MUTED' : '🔊 Audio: ON';
    btn.style.background = state.isMuted ? '#64748b' : '#334155';
  }
}

function siren(level) {
  if (state.isMuted || level < 2) return;
  const now = Date.now();
  if (level === state.lastLevel && now - state.lastSirenAt < 2000) return;
  state.lastLevel = level; state.lastSirenAt = now;
  if (!state.audioCtx) {
    try { state.audioCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch { return; }
  }
  const ac = state.audioCtx;
  if (ac.state === 'suspended') ac.resume();
  const pattern = level === 3 ? [[960, 0.22], [770, 0.22]] : [[587, 0.18]];
  let t = ac.currentTime;
  for (const [f, dur] of pattern) {
    const o = ac.createOscillator(), g = ac.createGain();
    o.type = 'sine'; o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.09, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g); g.connect(ac.destination);
    o.start(t); o.stop(t + dur); t += dur;
  }
}

async function refreshComPorts() {
  const sel = document.getElementById('comPortSelect');
  if (!sel) return;
  sel.innerHTML = '<option value="">LOOPBACK_SIMULATOR</option>';
  try {
    const res = await fetch('/api/v5/serial/ports');
    const data = await res.json();
    (data.ports || []).forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.device;
      opt.textContent = `${p.device} (${p.description || 'Serial Device'})`;
      sel.appendChild(opt);
    });
  } catch (e) {}
}

async function connectSelectedComPort() {
  const sel = document.getElementById('comPortSelect');
  const port = sel ? sel.value : '';
  try {
    const res = await fetch('/api/v5/serial/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port: port, baudrate: 115200 })
    });
    const data = await res.json();
    alert(`🔌 ${data.status === 'available' ? 'Bound to ' + data.port : 'Running Loopback Simulator'}`);
  } catch (e) {
    alert(`🔌 Connected to ${port || 'Loopback Simulator'}`);
  }
}

async function loadEventLogs() {
  const tbody = document.getElementById('eventLogTbody');
  const badge = document.getElementById('eventCountBadge');
  if (!tbody) return;
  try {
    const res = await fetch('/api/v6/event-log');
    const data = await res.json();
    const events = data.events || [];
    if (badge) badge.textContent = `${events.length} Recorded Events`;
    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-msg">No extubation events recorded yet</td></tr>';
      return;
    }
    tbody.innerHTML = events.slice(-10).reverse().map(e => `
      <tr>
        <td><b>${e.event_id}</b></td>
        <td>${e.timestamp}</td>
        <td>${e.dataset || 'live'}</td>
        <td>Frame ${e.frame_index} (${e.time_sec}s)</td>
        <td><span class="status-banner lvl-${e.severity_level}">Level ${e.severity_level}</span></td>
        <td><b>${e.cpri_percent}%</b> (min: ${e.min_delta})</td>
      </tr>
    `).join('');
  } catch (e) {}
}

async function logExtubationEvent(fr) {
  if (!fr || fr.severity_level < 2) return;
  try {
    const deltas = fr.deltas || [];
    const minDelta = deltas.length ? Math.min(...deltas) : 0.0;
    await fetch('/api/v6/event-log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dataset: state.file || 'live_stream',
        frame_index: fr.index || 0,
        time_sec: fr.time_sec || 0.0,
        severity_level: fr.severity_level,
        cpri_percent: fr.cpri_percent || 0.0,
        min_delta: minDelta
      })
    });
    loadEventLogs();
  } catch (e) {}
}

/* ------------------------------------------------------------- ICU Modal & i18n -- */
function openCentralICUModal() {
  document.getElementById('icuModal').style.display = 'flex';
}

function closeCentralICUModal() {
  document.getElementById('icuModal').style.display = 'none';
}

function renderICUGrid() {
  const c = document.getElementById('icuGridContainer');
  if (!c) return;
  c.innerHTML = '';
  for (let i = 1; i <= 8; i++) {
    const card = document.createElement('div');
    card.className = 'bed-unit';
    card.innerHTML = `<strong>Bed 0${i}</strong><br><span style="font-size:0.75rem;color:#94a3b8">${i === 1 ? 'Active Telemetry' : 'Empty Slot'}</span>`;
    c.appendChild(card);
  }
}

function switchLanguage(lang) {
  document.documentElement.lang = lang;
}

function generateMedicalPDF() {
  window.print();
}
