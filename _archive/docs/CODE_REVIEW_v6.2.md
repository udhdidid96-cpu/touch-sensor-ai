# Code Review — Project2 `main.py` v6.1 → v6.2

**Scope:** `main.py` (2,798 lines), `tests/`, `test_normal_mix.py`, `requirements.txt`, `start.bat`
**Method:** full read, then reproduced every finding by running the code against the real 80-file corpus in the cloud sandbox. Nothing below is inferred from reading alone.

**Verdict: Request changes — now applied.** Two defects would have shown up on stage. Both are fixed, all 32 API tests and 51 harness checks pass, and **no reported metric moved.**

---

## Critical

### C1 — The live WebSocket has never worked through a browser

`/ws/live_sensor` rejected **every** connection with close code 1008:

```
{"loc": ["query", "ws"], "msg": "Field required"}
```

`from __future__ import annotations` turns every annotation into a string. FastAPI resolves those with `typing.get_type_hints()`, which looks names up in the endpoint's **module** globals. `WebSocket` was imported *inside* `create_app`, so it was a function-local — invisible. FastAPI could not tell `ws: "WebSocket"` was the socket and treated it as a required **query parameter**.

Verified against the untouched original:

```
get_type_hints(handler) -> NameError: name 'WebSocket' is not defined
'WebSocket' in main module globals: False
websocket_connect(...) -> WebSocketDisconnect (1008)
```

So **LOOP 1 — live stream, serial feed, ICU siren — the headline feature of v6.x, was dead.** It hid because the dashboard silently falls back to the REST replay view, `--replay` on the CLI bypasses FastAPI entirely, and the only tests covering the socket were the stale v5.0 ones that could not be imported. The GET routes were fine: their annotations are `str`/`int`, which resolve from builtins.

**Fixed:** FastAPI symbols moved to module scope behind a `try/except ImportError`, so batch modes still run without fastapi installed. Now streams: `{'event':'started'}` then 20 frames, levels `[0,1,2]`.

### C2 — `requirements.txt` omitted `pandas`

`main.py` imports pandas at module scope. `start.bat` runs `pip install -r requirements.txt` then `python main.py` → **ImportError on any clean machine.** `matplotlib` (`--plots`) was missing too. Both added, plus `pytest`; `torch` documented as optional.

---

## High

### H1 — `pytest tests/` ran zero assertions

Both files imported `from main import get_app` — removed in v6.0. They errored **at collection**, so the suite reported errors and tested nothing, while the module header claimed *"14 defects, all with tests."* They also asserted against `/ws/sensor`, `/api/v5/serial/connect`, `/api/tele-nursing/*`, an 11-feature vector and a 60×80 matrix — none of which exist (FIX F1 changed the grid to 80×60).

**Fixed:** both rewritten against the real v6.2 API — 32 tests, session-scoped fixtures so the model trains once. Covers warmup silence, debouncer on the REST path, path traversal on both file endpoints, 404/416 handling, the grid orientation, serial parsing against a fake port, and the live socket.

### H2 — `--report` crashed when no episode was detected

`write_report` formats `median_latency_s` / `max_latency_s` with `:.2f` unguarded. Both are `None` when no anomaly episode fires (no class 2/3 recordings, or all missed). `print_stream_report` guards it; `write_report` did not.

```
TypeError: unsupported format string passed to NoneType.__format__
```

Reachable — the loader warns about missing classes and continues. Fixed; prints "no episode detected".

### H3 — Hand-typed numbers inside the generated METRICS.md

`write_report` emitted these as **string literals**:

> "deepest is 27,251" · "Class 0 n=5 and class 2 n=10"

Both happen to be right for round 1 (I confirmed 27,251.0 in `A_Peel_03.csv`). They would have stayed on the page unchanged after round 2 — inside the one file whose stated purpose is that paper numbers are never typed by hand.

**Fixed:** `_caveats(ds)` computes everything from the loaded corpus, and the Wilson CI is derived rather than quoted. The small-class caveat is now correct too: the old text gave 0.72–1.00 for 10/10, but the *smallest* class is n=5, whose CI is **0.57–1.00**.

### H4 — Unplugged sensor froze the dashboard forever

`SerialFrameSource.frames()` did `if not line: continue`. pyserial returns `b""` on read timeout, so an idle or unplugged device looped with no backoff, no disconnect detection and no way to end the stream. Measured against a port returning immediately: **6,838,304 reads/second**, pinning the asyncio executor thread the socket runs the generator on. On demo day a knocked USB cable = frozen dashboard, no error, no recovery.

**Fixed:** empty reads counted against a 10 s wall-clock budget with a 20 ms floor; the stream ends cleanly and the socket reports `{"event":"finished"}`. Two regression tests added.

---

## Medium — needs your bench, not a patch

### M1 — The pad-order convention is unverified, and the two paths disagree

All 80 recordings carry `Sensor-*` headers, so `read_raw_csv` takes the *"already in pad order"* branch and **never applies `PAD_ORDER`**. The live `SerialFrameSource` **always** applies it. The two paths assume opposite conventions for the same 25 numbers, and nothing in the repo records which one the firmware's UART stream uses.

Your own harness was already telling you: `t_reorder_applied` asserts reordering happens on real CSVs and **failed** with a `KeyError` — real signal, sitting unread.

What is and isn't at risk (measured):

| | permutation-invariant? | affected |
|---|---|---|
| 9 base features → all accuracy, sensitivity, FA figures | **yes** | safe |
| `--gradient` features | no | affected |
| heatmap, peel origin/heading/description, LOOP 3 figure | no | affected |

The same frame of `A_Peel_01` reads *"peeling from mid-right, spreading W"* one way and *"peeling from top-left, spreading S"* the other.

**Weak evidence favouring the current CSV branch:** on the 10 Peel files, pads below −300 form a tighter cluster read as-is (mean pairwise distance **33.9**) than permuted (**42.6**), against a **37.9** random-pad null — a peel should lift a contiguous patch. n=10, so a hint, not a proof.

**The bench check that settles it:** press pad 1, then pad 25, record both, confirm which column moves. Until that's on record, don't put a propagation direction in the paper. I did not flip the convention — that's a hardware fact, not a code decision.

**Added meanwhile:** the convention is counted at load, printed at startup, written into `metrics.json` / `METRICS.md`, warns loudly if a corpus ever *mixes* both, and is asserted by a new harness check.

---

## Low — fixed

- **`# flake8: noqa` on line 1** disabled lint for the whole file. It sits directly above the pyright block and reads as part of it, so the repo shipped a `.flake8` config that never ran on its main module. Removed; the 9 findings it hid are fixed. `flake8` is now clean across `main.py`, `tests/`, `test_normal_mix.py`.
- **`test_normal_mix.py` was invisible to pytest.** Its `def test(name)` decorator factory got collected as a test → *"fixture 'name' not found"*, erroring the file. That's why `pytest` said broken while `python test_normal_mix.py` passed 49/50. Marked `test.__test__ = False`; now **51/51**.
- **A 0.00 s latency printed as "not measured"** — `if r['median_latency_s']` instead of `is not None`. An alarm on the first frame after warmup is the *best* possible result and was reported as no data.
- **Two definitions of "onset."** `evaluate_stream` counted a frame-0 alarm; `operating_curve` didn't — so the headline alarms/hour could not match its own curve row. Unreachable today (warmup pins frame 0 to level 0), latent if `KALMAN_WARMUP` changes. Unified into `_count_onsets`.
- **Dead work:** `peel.update(...)` in `evaluate_stream` — result discarded, ~27 ms/run.
- **Dashboard pulled Chart.js from an unpinned CDN**, no integrity hash, no fallback. No network → `Chart is not defined` killed the *whole* dashboard, patch view and siren included, with no message. Pinned to `@4` + `onerror` guard + a visible banner. **Before the competition, vendor `chart.umd.js` and serve it locally** — a clinical dashboard shouldn't execute whatever a CDN ships that morning, and venue wifi is not a dependency you want.

## Low — noted, not changed

- **Peel heading reverses once per file.** 6/151 consecutive active frames flip >90°; median step is 0.5°, so it's stable *within* a peel but snaps once when two pads sit within noise of `argmin`. Cosmetically odd on a live arrow if a judge is watching. Fixing it means smoothing the origin or requiring heading persistence — a design call, so I left it to you.
- `--replay` combined with `--eval`/`--report` is silently ignored (batch modes `return 0` first).
- `SPATIAL.interpolate` rebuilds the `RBFInterpolator` per call (1.6 ms/frame). Fine at 560 ms cadence; cache it if the grid ever grows.

## What looks good

- **The honesty infrastructure is the strongest part of this repo** and it's unusual to see. Out-of-fold ROC (F6), episode-level metrics chosen *because* the file vote is a clip-length artifact, the published operating curve instead of one tuned point, `bootstrap_ci` resampling files rather than frames, the multi-seed BiLSTM comparison that overturned its own published result, and the retracted "10/hour desensitisation threshold" comment — that's real scientific discipline.
- `_stray_hint` turning a mis-named folder into the one sentence that fixes it, and `scan_csv_dirs` guaranteeing the audit and the loader can't disagree about what counts as a recording folder.
- Path containment (F3) is correct. I threw traversal, absolute paths and encoded variants at both file endpoints — all refused.
- `AlarmDebouncer`'s docstring documenting each version's failure *and the one it introduced*. That history is why the current k-of-n-plus-hold is right.
- `full_proba` (F7), the severity-biased tie-break (R5), and the NaN rejection in `read_raw_csv` (R12) are all sound.

## Before the competition

1. **Bench-check the pad order (M1)** — highest value per minute. Two recordings settle whether your spatial story is oriented.
2. **Open the dashboard and click "Live stream"** — it now works; it never did before.
3. `python main.py --audit Data` currently **fails** on baseline swing (worst 234 counts vs the ≤100 SOP criterion). That gate is doing its job; worth resolving before round 2.
4. Vendor Chart.js.
