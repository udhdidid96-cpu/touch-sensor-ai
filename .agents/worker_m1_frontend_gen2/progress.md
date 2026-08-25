# Progress: Milestone 1 (Frontend & WebSerial Hardening)

Last visited: 2026-08-24T21:12:00+09:00

## Status: IN_PROGRESS

### Tasks
- [ ] FE-01: Reset `state.lastLoggedLevel = null` on `lvl < 2` in `web/app.js`
- [ ] FE-02: Track `state.lastLevel = lvl` in `renderFrame()` in `web/app.js`
- [ ] FE-03: Add `pausePlayback()` at start of `setDashboardMode()` in `web/app.js`
- [ ] FE-04: Guard `onclose`/`onerror` in `startLiveWebSocketStream()` in `web/app.js`
- [ ] FE-05: Call `disconnectWebSerial()` in catch block of `readWebSerialStream()` in `web/web_serial.js`
- [ ] FE-06: Implement Web Audio autoplay unlock on user gesture in `web/app.js`
- [ ] Invariant checks: No classification tokens, no emojis, maintain IEC 62304 disclaimer
- [ ] Run test suite (`pytest tests/test_all_endpoints.py`)
- [ ] Write handoff report and notify parent orchestrator
