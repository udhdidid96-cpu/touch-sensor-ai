## 2026-08-23T17:05:01Z
<USER_REQUEST>
You are Explorer 2 focusing on Frontend and Client Invariants for Project2 (Smart Extubation Early Warning).

Please read the authoritative requirements in:
- `c:\Users\denpo\OneDrive\Desktop\Project2\.agents\ORIGINAL_REQUEST.md`
- `c:\Users\denpo\OneDrive\Desktop\Project2\AGENTS.md`
- `c:\Users\denpo\OneDrive\Desktop\Project2\.agents\rules\`

Your task:
1. Conduct an in-depth investigation of `web/index.html`, `web/style.css`, `web/app.js`, and `web/web_serial.js`.
2. Check all Invariants related to the frontend:
   - Invariant 1: Does the browser ever classify? Search `app.js` and `web_serial.js` for forbidden terms: `nLifted`, `rawLevel`, `liveKalman`, `isCriticalDetached`, or any client-side severity / CPRI / pad count calculation.
   - Invariant 3: Are there any invented patient identities, fake names, HN-*, ICU-*, ETT #, or fabricated ward structures in `index.html` or `app.js`?
   - Invariant 4: Are `data-metric` elements in `index.html` free of hardcoded digits in markup? Are they visible (never in hidden containers)? Does `app.js` fetch them from `/api/v6/metrics` at runtime and leave them blank if API fails?
   - Invariant 7: Search for any emojis in `index.html`, `style.css`, `app.js`, or `web_serial.js`.
   - Invariant 8: Check for the exact phrase "not been assessed against IEC 62304" — is it visible in `index.html` and present in running code in `app.js`? Is "certified" only used in a negated context?
3. Identify any UI bugs, CSS layout defects, WebSocket reconnection bugs, WebSerial streaming issues, or state handling defects in the frontend.
4. Compile a comprehensive, structured report detailing all findings, exact line numbers, verified evidence, and recommended fixes.

Deliver your complete report back via send_message to the orchestrator.
</USER_REQUEST>
