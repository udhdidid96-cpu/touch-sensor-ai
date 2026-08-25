# Frontend and Client Invariants Investigation Report

**Agent**: Explorer 2 (Frontend & Client Invariants)  
**Date**: 2026-08-24  
**Target Scope**: `web/index.html`, `web/style.css`, `web/app.js`, `web/web_serial.js`, `tests/`  

---

## 1. Observation

### 1.1 Invariants Compliance Verification

- **Invariant 1 (Browser Never Classifies)**:
  - `web/web_serial.js:119-125`: Receives server messages and passes them directly to `renderFrame(msg, 0)`.
  - `web/web_serial.js:213-228`: `sendFrameLine(line)` parses 25 float values from the serial buffer and sends `{ raw_frame: vals }` directly to `/ws/live_sensor?source=client`.
  - `web/app.js:839-856`: Reads `fr.severity_level`, `fr.cpri_percent`, `fr.deltas`, and `fr.propagation.n_lifting_pads` from the server frame.
  - Search for forbidden classification keywords (`nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`): **0 matches** found.
  - **Verdict**: Fully Compliant.

- **Invariant 3 (No Invented Patient Identity)**:
  - `web/app.js:1576-1588`: `DEFAULT_WARD_BEDS` initializes all 8 bed slots with `patient_id: null`, `patient_name: null`, `tube_type: null`, `notes: ''`, `status: null`, `severity_level: 0`, `cpri_percent: null`, `attached_nodes: null`.
  - `web/app.js:1593-1605`: Reads key `'p2.ward.beds.v2'` and deletes obsolete legacy storage key `'icu_ward_beds'`.
  - Search for mock patterns (`HN-\d+`, `ICU-[A-D]-\d+`, `ETT #`, `bed-unit`): **0 matches** found in `web/` markup and logic.
  - **Verdict**: Fully Compliant.

- **Invariant 4 (Measured or Absent Metrics in UI)**:
  - `web/index.html:349-352` (Dashboard Model Validation):
    ```html
    <b class="tile__v" data-metric="accuracy">&mdash;</b>
    <b class="tile__v" data-metric="macro_f1">&mdash;</b>
    <b class="tile__v" data-metric="peel_f1">&mdash;</b>
    <b class="tile__v tile__v--warn" data-metric="false_alarm_rate">&mdash;</b>
    ```
  - `web/index.html:453-456` (Model Performance View):
    ```html
    <b class="tile__v" data-metric="accuracy">&mdash;</b>
    <b class="tile__v" data-metric="macro_f1">&mdash;</b>
    <b class="tile__v" data-metric="peel_f1">&mdash;</b>
    <b class="tile__v tile__v--warn" data-metric="false_alarm_rate">&mdash;</b>
    ```
  - No hardcoded numerals in any `data-metric` slot. No `style="display:none"` wrapper enclosing the metric slots.
  - `web/app.js:777-828`: `renderMetrics()` fetches `/api/v6/metrics`, extracts `random_forest` and `episode_level` figures, and populates `data-metric` elements. If the API fails or returns null, `setMetricSlots(null, 'metrics unavailable')` sets slots to `\u2014` (`&mdash;`).
  - **Verdict**: Fully Compliant.

- **Invariant 7 (No Emojis)**:
  - Full regex sweep (`[\U0001F300-\U0001FAFF☀-➿️]`) over `index.html`, `style.css`, `app.js`, `web_serial.js`: **0 emojis found**.
  - **Verdict**: Fully Compliant.

- **Invariant 8 (IEC 62304 Regulatory Disclaimer & Negated Certified Context)**:
  - `web/index.html:110`: `<p id="txt-provenance">This prototype has not been assessed against IEC 62304. It is a screening aid and does not replace clinical judgement by qualified staff.</p>`
  - `web/app.js:8`: `console.info('This system has not been assessed against IEC 62304.');`
  - `web/app.js:142, 243, 344`: Included in TH, EN, JP translation dictionaries.
  - Search for `certified`: **0 matches** across `web/`.
  - **Verdict**: Fully Compliant.

---

### 1.2 Identified Frontend Defects & Logic Bugs

#### Defect 1: Undefined Function `withKey()` in `web/web_serial.js:103` (Critical)
- **Location**: `web/web_serial.js:103`
- **Code**:
  ```javascript
  ws = new WebSocket(withKey(`${proto}//${window.location.host}/ws/live_sensor?source=client`));
  ```
- **Error**: `withKey` is not defined anywhere in the repository. Calling `toggleWebSerial()` triggers `openIngestSocket()`, which immediately encounters `ReferenceError: withKey is not defined` and fails to establish the WebSocket connection.

#### Defect 2: Undefined Error Handlers `showError()` and `clearError()` in `web/web_serial.js` (High)
- **Location**: `web/web_serial.js:62, 71, 105, 110, 111, 115, 129, 199`
- **Code**: Calls `showError(...)` (7 locations) and `clearError()` (1 location).
- **Error**: Neither `showError` nor `clearError` is defined in `web_serial.js`, `app.js`, or `index.html`. Whenever a serial error or port disconnect occurs, a `ReferenceError: showError is not defined` is thrown rather than displaying an informative notification.

#### Defect 3: Missing Implementation of `uploadSelectedCSV()` in `web/app.js` (High)
- **Location**: `web/index.html:192` and `web/app.js`
- **Code**:
  ```html
  <input type="file" id="csvFileInput" accept=".csv" style="display:none" onchange="uploadSelectedCSV(this)">
  ```
- **Error**: Clicking "Upload CSV" invokes `uploadSelectedCSV(this)` on file selection. However, `uploadSelectedCSV` was completely omitted from `app.js`, throwing `Uncaught ReferenceError: uploadSelectedCSV is not defined`.

#### Defect 4: Inline Color Styling Violations (`rules/frontend.md`) (Medium)
- **Location**:
  - `web/web_serial.js:52`: `btn.style.background = active ? '#dc2626' : '';`
  - `web/app.js:1431`: `calibTag.style.color = wasStreaming ? '#38bdf8' : '#94a3b8';`
- **Error**: `rules/frontend.md` specifies: *"Every value is a token in :root in style.css, with a full [data-theme="dark"] override. Never inline a colour, in CSS or in a JS style.color = assignment."*

#### Defect 5: Hardcoded Thai Strings in Button State Updates (Medium)
- **Location**:
  - `web/app.js:1289`: `btn.textContent = '2. กำลังเฝ้าระวังสด (Live Active - Pause)';`
  - `web/app.js:1343, 1362`: `btn.textContent = '2. เริ่มการเฝ้าระวังสด (Live Stream)';`
- **Error**: When the UI is switched to English (`en`) or Japanese (`jp`), toggling live streaming overwrites the button text with hardcoded Thai text rather than using `t('btn_start')` or internationalized button state keys.

#### Defect 6: Toast/Chime Storm on `resetLiveCalibration()` (Low)
- **Location**: `web/app.js:1412-1450`
- **Error**: When streaming is active, `resetLiveCalibration()` calls `stopLiveWebSocketStream()` (triggers toast + chime), then `startLiveWebSocketStream()` (triggers toast + chime), followed by its own calibration toast and chime in rapid succession within milliseconds.

---

## 2. Logic Chain

1. **Web Serial Connection Failure**:
   - `web/index.html:157` has button `<button id="btnWebSerial" onclick="toggleWebSerial()">`.
   - `toggleWebSerial()` calls `openIngestSocket()` (`web_serial.js:76`).
   - `openIngestSocket()` attempts to evaluate `withKey(...)` (`web_serial.js:103`).
   - Because `withKey` does not exist in any loaded script or global scope, JavaScript throws a `ReferenceError`.
   - Inside `catch (e)`, `showError(...)` is called (`web_serial.js:105`).
   - Because `showError` also does not exist, a secondary `ReferenceError` is thrown, crashing the handler and preventing USB Serial operation.

2. **Custom CSV Upload Failure**:
   - `web/index.html:193` button clicks `#csvFileInput`.
   - On selecting a `.csv` file, the DOM dispatches `change` event calling `uploadSelectedCSV(this)`.
   - The global scope in `app.js` lacks `uploadSelectedCSV`, resulting in `Uncaught ReferenceError`.
   - The file is never sent to backend endpoint `/api/v6/upload-csv`.

3. **Invariants Robustness**:
   - All server communication pathways (`/api/v6/metrics`, `/api/v6/layout`, `/api/v5/dataset/`, `/ws/live_sensor`) maintain a clean separation of concerns: server computes/classifies; frontend strictly renders.
   - Regulatory notices and absence of mock patient data are maintained in both markup and running state.

---

## 3. Caveats

- **Live Physical Hardware**: Web Serial and physical COM port UART communication require physical hardware and browser user gesture to test end-to-end; verified via static code analysis, mock frame sources, and endpoint unit tests.
- **Leave-One-File-Out Test Duration**: Pytest execution running 81 folds takes ~1.5-2 minutes due to leave-one-out model evaluation, which is expected per `rules/verifying.md`.

---

## 4. Conclusion

The frontend console (`web/index.html`, `web/style.css`, `web/app.js`, `web/web_serial.js`) adheres strictly to all core architectural invariants:
1. **Invariant 1**: No client-side classification or forbidden heuristics.
2. **Invariant 3**: No invented patient identities or mock ward structures.
3. **Invariant 4**: All `data-metric` slots contain placeholders (`&mdash;`) and populate dynamically from `/api/v6/metrics`.
4. **Invariant 7**: Zero emojis present.
5. **Invariant 8**: Visible and executable IEC 62304 non-certification disclaimer present.

Six concrete implementation defects must be resolved:
1. Fix `withKey` undefined call in `web_serial.js:103`.
2. Implement `showError` and `clearError` in `web_serial.js`.
3. Implement `uploadSelectedCSV(input)` in `app.js`.
4. Replace inline color style assignments with CSS classes in `web_serial.js` and `app.js`.
5. Localize live streaming button text in `app.js`.
6. Streamline calibration reset notifications to prevent toast/chime storm.

---

## 5. Verification Method

To independently verify these findings:
1. **Invariant & Guard Test Suite**:
   ```bash
   python -m pytest tests/test_all_endpoints.py -k "dashboard or metric or compliance or ward" -v
   python -m pytest tests/ -q
   ```
2. **Static Invariant Grep Verification**:
   ```bash
   # Invariant 1: No forbidden classifier keywords
   rg "nLifted|rawLevel|liveKalman|isCriticalDetached" web/
   # Invariant 3: No mock patient records
   rg "HN-\d+|ICU-[A-D]|ETT #" web/
   # Invariant 4: No hardcoded metric numerals in markup
   rg 'data-metric="[^"]+">\d+' web/index.html
   # Invariant 8: IEC 62304 disclaimer
   rg "not been assessed against IEC 62304" web/
   ```
3. **Defect Verification**:
   - Inspect `web_serial.js:103` for `withKey` definition.
   - Inspect `app.js` for missing `uploadSelectedCSV` definition.
