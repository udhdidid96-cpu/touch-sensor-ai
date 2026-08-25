## 2026-08-24T20:58:35+09:00

You are a Worker implementing Milestone 1 (Frontend & WebSerial Hardening) for Project2 (Smart Extubation Early Warning).
Your working directory is: c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend
Your parent orchestrator ID is: 5b6c814d-f91e-4105-ba6b-4934f8cf03b7

MANDATORY: Read the full user request at:
c:\Users\denpo\OneDrive\Desktop\Project2\.agents\ORIGINAL_REQUEST.md
Also read AGENTS.md, PROJECT.md, and c:\Users\denpo\OneDrive\Desktop\Project2\.agents\explorer_frontend_survey\handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Scope & File Ownership:
You exclusively own: web/app.js and web/web_serial.js.
Do NOT modify other files.

Tasks to implement:
1. FE-01 (web/app.js:966): In enderFrame(), ensure when lvl < 2, reset state.lastLoggedLevel = null; so that repeating alarm episodes (e.g. L2 -> L0 -> L2) are not dropped by logExtubationEvent().
2. FE-02 (web/app.js:890): In enderFrame(), ensure state.lastLevel = lvl; is recorded so switchLanguage() has the correct current severity when frames are streaming.
3. FE-03 (web/app.js:1250): In setDashboardMode(mode, autoStart), call pausePlayback(); at the beginning to ensure background replay timer intervals are cleared when switching modes.
4. FE-04 (web/app.js:1393-1402): In startLiveWebSocketStream(), inside ws.onclose and ws.onerror, guard state updates with if (state.liveWs === ws) to prevent stale closure race conditions when reconnecting.
5. FE-05 (web/web_serial.js:222-226): In eadWebSerialStream(), in the catch (err) block, if webSerialActive is true, call disconnectWebSerial(); after showError(...) to clean up dangling port state and reset the UI on unexpected USB disconnection.
6. FE-06 (web/app.js:1096-1116): Add global one-time interaction listeners (click, keydown, 	ouchstart) to unlock and resume AudioContext on first user gesture, ensuring alarm audio is not blocked by browser autoplay policies.

Strict Invariant Constraints:
- Invariant 1: Browser NEVER classifies. Grep and ensure NO forbidden tokens (
Lifted, awLevel, liveKalman, isCriticalDetached) or heuristics.
- Invariant 7: NO emojis in source code or comments.
- Invariant 8: 
ot been assessed against IEC 62304 must remain in pp.js.

Verification Requirements:
1. Run python -m pytest tests/test_all_endpoints.py -k "test_the_browser_never_classifies or test_no_emoji or test_certified" -v
2. Run python -m pytest tests/test_all_endpoints.py -q
3. Write a comprehensive handoff report to c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend\handoff.md.
4. Update your progress.md before and after. Send a completion message to parent.

## 2026-08-24T12:00:19Z
**Context**: Milestone 1 Implementation (Frontend & WebSerial Hardening).
**Content**: Please proceed with implementing FE-01 through FE-06 in web/app.js and web/web_serial.js, run the tests, and write your complete handoff report to c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend\handoff.md.
**Action**: Implement the 6 changes, verify with tests, write handoff.md, and notify parent.
