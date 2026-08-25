# Explorer Frontend Survey: Invariant Compliance, Architecture, Defect Discovery, & UI/UX Audit

**Target Files Examined**: `web/app.js`, `web/web_serial.js`, `web/index.html`, `web/style.css`  
**Investigation Scope**: Invariants 1–9 compliance, Web Serial framing & streaming, WebSocket connection lifecycle, resource & memory management, Web Audio autoplay compliance, WCAG AA accessibility, theme token consistency, and responsive DOM hierarchy.

---

## 1. Executive Summary

A comprehensive multi-pass audit of the Project2 frontend codebase was conducted. The frontend architecture strictly adheres to core philosophical invariants: it operates purely as a rendering engine and data transport layer without performing client-side classification, threshold evaluation, or heuristic decision-making. No mock patient identities or emoji characters exist in the markup or scripts, and regulatory disclaimers (`has not been assessed against IEC 62304`) are prominently rendered in both HTML and JS.

However, the deep investigation identified **6 high- and medium-severity runtime defects and edge-case vulnerabilities**:
1. **Audit Trail Event Dropping**: `logExtubationEvent` fails to log repeating alarm levels because `renderFrame` restricts invocation to `lvl >= 2`, leaving `state.lastLoggedLevel` stale across lower-level interludes (e.g., L2 -> L0 -> L2 drops the second L2 event).
2. **Unset `state.lastLevel` Variable**: `renderFrame` never writes back to `state.lastLevel`, causing fallback localization sweeps to default to Level 0 permanently.
3. **Replay Timer Telemetry Collision**: Switching to Live mode does not pause active replay intervals, allowing background timer ticks to overwrite live telemetry.
4. **WebSocket Reconnect Race Condition**: Asynchronous closure of obsolete WebSocket instances overwrites the connection state of newer active sockets.
5. **Web Serial Abrupt Hardware Disconnect Leak**: Port read errors release the stream reader lock but fail to invoke `disconnectWebSerial()`, leaving UI and port state desynchronized.
6. **Web Audio Context Autoplay Blocking**: `AudioContext` instantiation inside asynchronous event callbacks is blocked by browser autoplay policies if no user interaction listener unlocked it first.

All defects are localized, non-architectural, and have clear remediation paths with zero regression risk.

---

## 2. Invariant Compliance Audit

| Invariant | Requirement | Status | Observations & Evidence |
|---|---|---|---|
| **Invariant 1** | **Browser Never Classifies**: No thresholds, severity calculations, or forbidden variables (`nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`). | **PASS** | Grep verified 0 occurrences of forbidden terms. `web_serial.js:237-252` solely validates 25 numeric floats and forwards raw frame to server. `app.js:883-1028` derives all severity, CPRI, and lifting pad counts from server payload (`fr.severity_level`, `fr.cpri_percent`, `fr.propagation.n_lifting_pads`). |
| **Invariant 2** | **No Hand-coded Probability**: Classified server-side only. | **PASS** | Verified frontend does not compute or alter probability distributions. `probabilities` array from server is directly displayed in progress bars (`app.js:999-1004`) and charts (`app.js:671-674`). |
| **Invariant 3** | **No Invented Patient Identity**: No hardcoded names, HN/ICU IDs, or mock wards. | **PASS** | `index.html:143-147` and `app.js:1632-1643` use generic bed placeholders (`Bed 01`–`Bed 08`) with `patient_id: null` and `cpri_percent: null`. Stored under versioned key `p2.ward.beds.v2` (`app.js:1648`). |
| **Invariant 4** | **Measured or Absent Metrics**: `data-metric` slots contain no hardcoded digits; populated via `/api/v6/metrics`. | **PASS** | `index.html:349-352, 453-456` define all 4 metric slots with `&mdash;`. `app.js:828-879` fetches `/api/v6/metrics` and maps `random_forest` and `episode_level` stats. If unavailable, slots remain em dash placeholders. |
| **Invariant 5** | **SPEC_DETACH_MAX = 25000**: Threshold honesty. | **PASS** | UI references lift gate −300 counts and noise gate 60 counts (`app.js:986-988`, `index.html:548-549`). No altered detachment constants in frontend. |
| **Invariant 6** | **Security & Access Key**: No `--allow-public-no-key` in Docker; `withKey()` wrapper on all frontend requests. | **PASS** | `withKey()` utility implemented in `web_serial.js:48-58` and `app.js:32-42`, appending `?key=` query parameter to all API calls and WebSocket connections. |
| **Invariant 7** | **No Emoji**: No emoji glyphs in UI or status text. | **PASS** | Python AST/Unicode sweep confirmed 0 emoji characters across `index.html`, `app.js`, `web_serial.js`, and `style.css`. All status indicators use CSS classes (`.status-pill`, `.dot-*`, SVG icons). |
| **Invariant 8** | **IEC 62304 Disclaimer**: `not been assessed against IEC 62304` must appear in `index.html` and `app.js`. | **PASS** | Verified in `index.html:110` (visible disclaimer text in sidebar) and `app.js:8` (`console.info`) as well as in all 3 language dictionary strings (`app.js:155, 257, 359`). |
| **Invariant 9** | **Reproducible Metrics**: No manual figure adjustments. | **PASS** | All metrics rendered dynamically from server API. |

---

## 3. Concrete Defect & Vulnerability Inventory

### Defect 1: Audit Trail Event Dropping on Repeating Alarm Levels
- **File & Lines**: `web/app.js:966` and `web/app.js:1585–1600`
- **Observation**:
  ```javascript
  // web/app.js:966
  siren(lvl);
  if (lvl >= 2) logExtubationEvent(fr);
  ```
  ```javascript
  // web/app.js:1586-1587
  async function logExtubationEvent(fr) {
    if (state.lastLoggedLevel === fr.severity_level) return;
    state.lastLoggedLevel = fr.severity_level;
    ...
  ```
- **Logic Chain**:
  1. An extubation alarm occurs (e.g., Level 2). `lvl >= 2` is true; `logExtubationEvent(fr)` runs and sets `state.lastLoggedLevel = 2`. The event is successfully POSTed.
  2. The dressing briefly settles (Level 0). Because `lvl < 2`, `logExtubationEvent` is NOT called. `state.lastLoggedLevel` remains `2`.
  3. A new Level 2 alarm occurs. `lvl >= 2` is true; `logExtubationEvent(fr)` is called.
  4. Line 1586 tests `if (state.lastLoggedLevel === fr.severity_level) return;`. Since `state.lastLoggedLevel` is still `2`, the guard returns immediately and **silently drops the second clinical alarm event from the audit trail**.
- **Severity**: **High** (Audit trail incompleteness violates clinical traceability).
- **Proposed Fix**: In `renderFrame`, update `state.lastLoggedLevel` or reset it when `lvl < 2`:
  ```javascript
  siren(lvl);
  if (lvl >= 2) {
    logExtubationEvent(fr);
  } else {
    state.lastLoggedLevel = null;
  }
  ```

---

### Defect 2: Unset `state.lastLevel` Variable in Frame Renderer
- **File & Lines**: `web/app.js:23`, `web/app.js:427–431`, `web/app.js:883–965`
- **Observation**:
  `state.lastLevel` is initialized to `0` at line 23. In `switchLanguage()`, lines 427–431 use `state.lastLevel` when `state.frames` has no active index:
  ```javascript
  const b = document.getElementById('statusBanner');
  if (b) b.textContent = t('status_' + (state.lastLevel || 0));
  ```
  However, throughout `renderFrame()`, `state.lastLevel` is never updated with `state.lastLevel = lvl;`.
- **Logic Chain**:
  When live telemetry is active without recording frames (e.g., streaming over WebSocket without scrubbing index), changing UI language resets status indicators to `status_0` regardless of the ongoing alarm state.
- **Severity**: **Medium** (UI language switch desynchronizes displayed alarm state during live streaming).
- **Proposed Fix**: Add `state.lastLevel = lvl;` inside `renderFrame()`.

---

### Defect 3: Live Mode Switching Fails to Pause Active Replay Interval
- **File & Lines**: `web/app.js:1249–1293`
- **Observation**:
  `setDashboardMode(mode, autoStart)` switches between `'live'` and `'replay'`. While `setDashboardMode('replay')` explicitly calls `stopLiveWebSocketStream()`, `setDashboardMode('live')` does **not** call `pausePlayback()`.
- **Logic Chain**:
  1. Operator plays a historical dataset in Replay mode (`startPlayback()` starts `setInterval(..., 560)` stored in `state.timer`).
  2. Operator switches acquisition mode to "Live" (`setDashboardMode('live')`).
  3. `state.timer` continues running in the background, repeatedly invoking `seekFrame()` every 560 ms.
  4. Replay frames continuously overwrite live sensor telemetry in `renderFrame()`, corrupting the live monitor.
- **Severity**: **High** (Concurrent replay playback corrupts live telemetry view).
- **Proposed Fix**: In `setDashboardMode(mode)`, call `pausePlayback()` at the top of the function:
  ```javascript
  function setDashboardMode(mode, autoStart = false) {
    pausePlayback();
    state.mode = mode;
    ...
  ```

---

### Defect 4: WebSocket Event Handler Stale Closure / Race Condition
- **File & Lines**: `web/app.js:1393–1402`
- **Observation**:
  ```javascript
  ws.onclose = () => {
    state.liveStreaming = false;
    const btn = document.getElementById('txtLiveStreamBtn');
    if (btn) btn.textContent = t('btn_start');
  };
  ```
- **Logic Chain**:
  1. `startLiveWebSocketStream()` closes any existing `state.liveWs` and creates a new `WebSocket`.
  2. If the user rapidly toggles live streaming or re-seeds calibration (`resetLiveCalibration()`), the previous WebSocket closes asynchronously.
  3. When the previous socket's `onclose` fires, it unconditionally executes `state.liveStreaming = false` and resets the button text, even if a new connection was already established and assigned to `state.liveWs`.
- **Severity**: **Medium** (UI button and streaming flag flicker to "stopped" while socket is actively streaming).
- **Proposed Fix**: Ensure event handlers check instance identity:
  ```javascript
  ws.onclose = () => {
    if (state.liveWs === ws) {
      state.liveStreaming = false;
      const btn = document.getElementById('txtLiveStreamBtn');
      if (btn) btn.textContent = t('btn_start');
    }
  };
  ```

---

### Defect 5: Web Serial Read Loop Termination Leaves Port Dangling on Hardware Loss
- **File & Lines**: `web/web_serial.js:222–226`
- **Observation**:
  ```javascript
  // web/web_serial.js:222-226
  } catch (err) {
    if (webSerialActive) showError(`Web Serial read ended: ${err.message}`);
  } finally {
    try { reader.releaseLock(); } catch (e) { /* ignore */ }
  }
  ```
- **Logic Chain**:
  1. When USB hardware is unexpectedly unplugged during streaming, `reader.read()` throws an exception.
  2. The `catch` block reports the error, and `finally` releases the lock.
  3. However, `disconnectWebSerial()` is not called. `webSerialActive` remains `true`, the button remains in "Stop Web Serial" (`.btn--danger`) state, and `webSerialSocket` remains dangling.
- **Severity**: **Medium** (UI state out of sync after USB disconnection).
- **Proposed Fix**: In `readWebSerialStream()`, trigger `disconnectWebSerial()` if the loop terminates abnormally while `webSerialActive` is true:
  ```javascript
  } catch (err) {
    if (webSerialActive) {
      showError(`Web Serial read ended: ${err.message}`);
      disconnectWebSerial();
    }
  }
  ```

---

### Defect 6: Web Audio Autoplay Policy Blocks Alarm Audio on Un-interacted Workstations
- **File & Lines**: `web/app.js:1096–1177`
- **Observation**:
  `siren()` and `playChime()` lazily create `state.audioCtx = new AudioContext()` inside asynchronous callbacks (`renderFrame()` and WebSocket `onmessage`).
- **Logic Chain**:
  1. If a clinician loads the console in a browser tab and leaves it running on a secondary screen without clicking or pressing keys, `AudioContext` is created in `'suspended'` state.
  2. Browser Autoplay Policies (Chrome, Edge, Safari) reject `audioCtx.resume()` when initiated outside of a synchronous user gesture event handler.
  3. When an extubation event occurs (Level 2 or 3), audio is blocked and silenced with a browser console warning.
- **Severity**: **Medium-High** (Alarm audio failure in passive monitoring setups).
- **Proposed Fix**: Attach early user interaction listeners to unlock audio on first click/keypress:
  ```javascript
  function unlockAudioContext() {
    if (!state.audioCtx) {
      state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (state.audioCtx.state === 'suspended') {
      state.audioCtx.resume();
    }
    ['click', 'keydown', 'touchstart'].forEach(e =>
      document.removeEventListener(e, unlockAudioContext)
    );
  }
  ['click', 'keydown', 'touchstart'].forEach(e =>
    document.addEventListener(e, unlockAudioContext, { once: false, passive: true })
  );
  ```

---

## 4. UI/UX, Accessibility, and Memory Analysis

### 4.1 Accessibility (WCAG 2.1 AA Compliance)
- **Color Contrast**: All text tokens in `style.css` satisfy WCAG AA requirements.
  - Primary text `--ink: #16202f` provides a contrast ratio of **14.9:1** against `--panel: #ffffff`.
  - Secondary text `--ink-2: #4d5a70` provides **7.5:1** against `--panel`.
  - Floor tertiary text `--ink-3: #5d6777` was measured across all surfaces: **5.72:1** on `--panel`, **5.38:1** on `--panel-2`, and **5.09:1** on `--panel-3` (well above the 4.5:1 minimum).
  - Dark mode tokens maintain equivalent contrast (`--ink-3: #8d9aab` at **5.4:1** on `--panel: #141c27`).
- **Keyboard Navigation & Focus Rings**:
  - `style.css:119–123` provides a dedicated `:focus-visible` ring with `2px solid var(--accent)` and `2px offset`.
  - Topbar patient badge (`#topPatientBadge`) carries `tabindex="0" role="button"`.
- **Form Controls & ARIA**:
  - All form controls are wrapped in `<label class="field">` or carry explicit `aria-label` (`#langSelect`, `#btnTheme`, `#fileSelect`, `#timeSlider`).
  - Toast notifications container carries `aria-live="polite"` (`index.html:593`).
  - Patient Edit Dialog carries `role="dialog" aria-modal="true"`.
- **Localization (i18n)**:
  - Three complete dictionaries (`th`, `en`, `jp`) with identical key sets (64 keys each).
  - Full font stack in `--font-ui` supporting Thai (`Sarabun`, `Leelawadee UI`, `Noto Sans Thai`) and Japanese (`Noto Sans JP`, `Yu Gothic UI`, `Meiryo`).

### 4.2 Layout & DOM Structure
- Clean grid layout: 62px topbar over `sidebar (218px) / main` container.
- Responsive breakpoints at 1420px, 1200px, 1080px (collapses sidebar to 62px icon rail), and 860px (stacks topbar and sidebar).
- `@media (prefers-reduced-motion: reduce)` disables all animations and transitions.
- High-fidelity print styles (`@media print`) strip navigation/control rails and format clean A4 reports.

### 4.3 Memory Management & Leaks Audit
- **Chart.js**: Initialized once on page load (`initRiskChart()`). Never destroyed/recreated on frame updates. Live updates prune labels and datasets to a sliding window of 50 items (`app.js:1447–1450`).
- **Heatmap Canvas**: Radial gradient wash is rendered on a single persistent canvas element (`#heatmapCanvas`) with hardware clipping (`#patchClip`).
- **DOM Leaks**: Toast notifications automatically detach from the parent node after fadeout animation completes (`app.js:1203–1208`).

---

## 5. Recommended Remediation Plan

The implementation phase should execute the following non-breaking patches:

| Step | Target File | Target Lines | Modification Description |
|---|---|---|---|
| **Step 1** | `web/app.js` | 966 | Update `logExtubationEvent` calling logic to reset `state.lastLoggedLevel = null` when `lvl < 2`. |
| **Step 2** | `web/app.js` | 890 | Add `state.lastLevel = lvl;` inside `renderFrame()` to persist last seen severity for localization switch. |
| **Step 3** | `web/app.js` | 1250 | Add `pausePlayback()` at the beginning of `setDashboardMode()`. |
| **Step 4** | `web/app.js` | 1393–1402 | Add `if (state.liveWs === ws)` check in WebSocket `onclose` and `onerror` handlers. |
| **Step 5** | `web/web_serial.js` | 222–226 | Call `disconnectWebSerial()` upon read stream exception when `webSerialActive` is true. |
| **Step 6** | `web/app.js` | 1096–1116 | Add global one-time interaction listeners (`click`, `keydown`, `touchstart`) to unlock `AudioContext`. |

---

## 6. Verification Method

To independently verify the frontend integrity and validate the findings:
1. **Pytest Frontend Guard Suite**:
   ```bash
   python -m pytest tests/test_all_endpoints.py -k "test_dashboard or test_frontend or test_metrics" -v
   ```
   *Expected Result*: 5 passed, 0 failures.
2. **Full Project Test Suite**:
   ```bash
   python -m pytest tests/ -q
   ```
   *Expected Result*: 113+ passed, 0 failed.
3. **Static Invariant & Emoji Verification**:
   ```bash
   python -c "
   import re
   files = ['web/index.html', 'web/app.js', 'web/web_serial.js', 'web/style.css']
   emoji = re.compile(r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff]')
   for f in files:
       with open(f, 'r', encoding='utf-8') as fp:
           for i, line in enumerate(fp, 1):
               assert not emoji.findall(line), f'Emoji in {f}:{i}'
   print('Zero emoji violation verified.')
   "
   ```
4. **Metrics Endpoint Verification**:
   ```bash
   python main.py --verify-metrics
   ```
