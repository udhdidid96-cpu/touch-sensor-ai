# BRIEFING — 2026-08-24T20:59:00+09:00

## Mission
Implement Milestone 1 (Frontend & WebSerial Hardening) remediating FE-01 through FE-06 in web/app.js and web/web_serial.js while strictly maintaining Invariants 1-9.

## 🔒 My Identity
- Archetype: worker
- Roles: implementer, qa, specialist
- Working directory: c:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m1_frontend
- Original parent: 5b6c814d-f91e-4105-ba6b-4934f8cf03b7
- Milestone: M1 Frontend & WebSerial Hardening

## 🔒 Key Constraints
- Exclusively own and modify: web/app.js and web/web_serial.js. Do not modify other files.
- Invariant 1: Browser NEVER classifies. No forbidden tokens (nLifted, rawLevel, liveKalman, isCriticalDetached).
- Invariant 7: NO emojis in source code or comments.
- Invariant 8: IEC 62304 disclaimer ('not been assessed against IEC 62304') must remain in app.js.
- Minimal change principle.

## Current Parent
- Conversation ID: 5b6c814d-f91e-4105-ba6b-4934f8cf03b7
- Updated: not yet

## Task Summary
- **What to build**: 6 specific frontend/WebSerial hardening fixes (FE-01 to FE-06).
- **Success criteria**: 100% pytest suite pass, zero invariant violations, clean USB disconnection, no stale WS race, no dropped audit events.
- **Interface contracts**: PROJECT.md
- **Code layout**: PROJECT.md

## Change Tracker
- **Files modified**: None yet
- **Build status**: Pending
- **Pending issues**: None

## Quality Status
- **Build/test result**: Pending
- **Lint status**: Pending
- **Tests added/modified**: Target verification tests

## Loaded Skills
- None required for this milestone.

## Key Decisions Made
- Follow explorer survey findings and exact remediation plans for FE-01 to FE-06.

## Artifact Index
- .agents/worker_m1_frontend/DISPATCH.md — Dispatch instructions
- .agents/worker_m1_frontend/progress.md — Liveness & progress tracking
- .agents/worker_m1_frontend/BRIEFING.md — Situational awareness
