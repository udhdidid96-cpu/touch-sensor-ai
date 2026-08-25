# Verifying work in this repo

Scope: `tests/**`, and any change you are about to call finished.
Set this rule to **Model Decision** with the description
"how to verify a change in Project2 before reporting it as done".

## The suite

```bash
python -m pytest tests/ -q          # 113 tests, 0 failed is the bar
python main.py --verify-metrics     # re-measure the headline figures
python main.py --audit Data         # corpus audit incl. the lift-gate criterion
python main.py --verify-pads        # PAD_ORDER against the 1-by-1 sweep
```

`pytest.ini` sets `testpaths=tests`. Root-level `test_*.py` files are stubs that
never ran — do not add more.

A leave-one-file-out fold costs 1.5–1.9 s in a fresh process and about 10 s in
the same process after `tests/test_all_endpoints.py` has run. That is known and
unexplained; it is most of the suite runtime on a 2-core box, not a hang.

## Why the guards are shaped the way they are

Every guard in `test_all_endpoints.py` exists because something got past its
predecessor. When you add one, make it fail on the *behaviour*, not on a name:

- The ward fabrication came back under a new CSS class, because the guard
  grepped the old one.
- The metrics guard passed on four em dashes sitting inside a
  `display:none` wrapper, with the renderer deleted — its own docstring had
  warned about exactly that hole.
- The regulatory-disclaimer check read `app.js` and nothing else, so it stayed
  green through the whole period `index.html` had no visible disclaimer.
- `test_ward_status_endpoint` asserted 8 beds: a test pinning a fabrication.

`_strip_comments()` exists so these checks test what a viewer sees — the source
carries comments naming the removed claims, and without stripping, the tests
fail on their own documentation.

## Reporting

State what you ran and what it printed. "Tests pass" without the output is not
a result. If you could not run something — no hardware, no corpus, no daemon —
say which check you skipped and why, rather than implying coverage you do not
have.

## What cannot be verified here

- **The live serial path.** Both sockets default to `permute=0`, so the pad
  convention is unverified in both directions on live hardware. The socket
  reports `pad_order_applied` in its `started` message; capture a 1-by-1 sweep
  through `/ws/live_sensor` and run `--verify-pads` to settle it.
- **Generalisation.** One session (S0), one sensor mounting. No figure here can
  show it transfers to a new mounting.
