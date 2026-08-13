## 2026-08-03T01:19:45Z
You are a Worker subagent for Project2: Touch Sensor Self-Extubation Early Warning System.
Your working directory is C:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m8_2.
Project root is C:\Users\denpo\OneDrive\Desktop\Project2.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Your objective is to implement all missing features, fix UI aesthetics, correct type errors, fix test collection, and ensure 100% test pass and zero lint/type errors.

Tasks:
1. Update Web Dashboard UI in `main.py`:
   - Change HTML tag to `<html lang="en">`.
   - Update CSS palette to use Japanese Torii Red `#D7000F`, Imperial Gold `#FFD700`, and Indigo Navy `#0F172A` / `#1E293B`.
   - Add Interactive Competition Demo Toolbar with 4 scenario buttons (`Normal`, `Touch`, `Peel`, `Extubation Alarm`). Clicking each button must instantly simulate the scenario and trigger live predictions and audio-visual sirens (960Hz / 770Hz).
   - Add 8-Bed ICU Central Nurse Station Grid View (Bed 1 through Bed 8 status grid).
   - Add 1-Click Printable Medical PDF Audit Chart endpoint/modal for patient audit summaries.
   - Add Tele-Nursing LINE / Telegram Settings Panel in Web UI & API routes (`GET /api/tele-nursing/config`, `POST /api/tele-nursing/config`, `POST /api/tele-nursing/test-alert`).
2. Expose `get_app()` in `main.py`:
   - Define `def get_app(): return app` in `main.py` so `tests/test_all_endpoints.py` and `tests/test_serial_streaming.py` import `get_app` cleanly.
3. Fix all Pyright / Pylance type errors:
   - Fix `zero_division` type mismatch in `main.py` for sklearn calls.
   - Fix type annotations, imports, and subscriptings in `test_normal_mix.py` and `tests/`.
   - Verify `npx pyright` returns 0 errors and 0 warnings.
4. Verify Flake8 compliance:
   - Ensure `python -m flake8 main.py test_normal_mix.py tests/` returns 0 errors.
5. Verify pytest and model metrics:
   - Run `python -m pytest` -> 100% pass.
   - Run `python test_normal_mix.py` -> 100% pass.
   - Run `python main.py --report` -> LOFO-CV accuracy >= 95.0%, FAR = 0.0%.

Write a detailed handoff report in C:\Users\denpo\OneDrive\Desktop\Project2\.agents\worker_m8_2\handoff.md documenting all modified files, test outputs, and verification commands. Send a summary message when complete.
