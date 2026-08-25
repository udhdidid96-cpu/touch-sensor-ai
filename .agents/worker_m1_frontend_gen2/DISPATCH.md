## 2026-08-24T12:10:19Z
You are a Worker implementing Milestone 1 (Frontend & WebSerial Hardening) for Project2 (Smart Extubation Early Warning).
Your working directory is: c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend_gen2
Your parent orchestrator ID is: 5b6c814d-f91e-4105-ba6b-4934f8cf03b7

MANDATORY: Read the full user request at:
c:\Users\denpo\OneDrive\Desktop\Project2\.agents\ORIGINAL_REQUEST.md
Also read AGENTS.md and PROJECT.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & File Ownership:
You exclusively own: `web/app.js` and `web/web_serial.js`.
Do NOT modify other files.

6 Tasks to implement immediately in `web/app.js` and `web/web_serial.js`:
1. FE-01 (`web/app.js` around line 966): In `renderFrame()`, where `if (lvl >= 2) logExtubationEvent(fr);` is called, add `else { state.lastLoggedLevel = null; }` so that repeating alarm episodes (e.g. L2 -> L0 -> L2) properly log both alarms to the audit trail.
2. FE-02 (`web/app.js` around line 890): In `renderFrame()`, ensure `state.lastLevel = lvl;` is set so that `switchLanguage()` correctly renders the current severity level when changing language during live stream.
3. FE-03 (`web/app.js` around line 1250): In `setDashboardMode(mode, autoStart)`, add `pausePlayback();` at the very beginning of the function so that background replay intervals are cleared when switching modes.
4. FE-04 (`web/app.js` around line 1393-1402): In `startLiveWebSocketStream()`, inside `ws.onclose` and `ws.onerror`, wrap the UI and state reset with `if (state.liveWs === ws) { state.liveStreaming = false; ... }` to prevent stale closure race conditions when rapidly reconnecting.
5. FE-05 (`web/web_serial.js` around line 222-226): In `readWebSerialStream()`, in the `catch (err)` block, if `webSerialActive` is true, call `disconnectWebSerial();` after `showError(...)` to cleanly reset the UI and port state when the USB device is unplugged or fails.
6. FE-06 (`web/app.js`): Implement Web Audio autoplay policy handling by adding one-time interaction listeners (`click`, `keydown`, `touchstart`) to unlock and resume `state.audioCtx` on first user gesture.

Strict Invariant Rules:
- Invariant 1: Browser NEVER classifies. Grep and ensure NO forbidden tokens (`nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`) or heuristics.
- Invariant 7: NO emojis in source code, strings, or comments.
- Invariant 8: `not been assessed against IEC 62304` must remain intact in `app.js`.

Verification Steps:
1. Run `python -m pytest tests/test_all_endpoints.py -k "test_the_browser_never_classifies or test_no_emoji or test_certified" -v`
2. Run `python -m pytest tests/test_all_endpoints.py -q`
3. Write your complete handoff report to `c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend_gen2\handoff.md`.
4. Update `progress.md` before and after. Send a completion message to parent.

## 2026-08-24T12:20:16Z
**Context**: Milestone 1 Frontend Hardening.
**Content**: Please proceed to execute the code edits for FE-01 to FE-06 in `web/app.js` and `web/web_serial.js`, run `pytest tests/test_all_endpoints.py`, and write your handoff report to `c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend_gen2\handoff.md`.
**Action**: Implement the changes, test, and write `handoff.md`.
