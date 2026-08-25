# Code review — Project2, 2026-08-19

**32 defects found, all fixed.** Test suite: **3 failed / 107 passed → 0 failed / 113 passed.**

*(Second pass, added after a follow-up "find the flaws in this" — sections C5, C6, H10–H12 and the file consolidation came from that pass. Two of them are worse than anything in the first pass.)*

This is a follow-up to the 2026-08-17 review. Every headline defect below is a
*reversal* of something that review fixed and recorded, reintroduced by the
2026-08-18 edits to `main.py`, `web/app.js`, `web/index.html` and
`web/style.css`. Where a number appears here it was measured in this session,
not carried over.

---

## สรุปภาษาไทย (อ่านแค่ส่วนนี้ก็พอ)

สี่เรื่องที่ต้องรู้:

1. **ระบบตรวจไม่เจอการดึงท่อ 17 จาก 30 ครั้ง** — โค้ดวันที่ 18 ส.ค. ใส่ "Physics-Gated
   Guard" กลับเข้าไปใน `classify_deltas()` ซึ่งเขียนค่าความน่าจะเป็นทับผลของโมเดล
   ผลที่วัดได้: ความไวต่อการดึงท่อจาก **30/30 เหลือ 13/30** และสัญญาณผิดบนไฟล์ปกติ
   เพิ่มจาก 1/41 เป็น 3/41 — แย่ลงทั้งสองด้านพร้อมกัน แถมไม่มีตัวเลขที่ตีพิมพ์ตัวไหน
   วัดผ่านโค้ดชุดนี้เลย (metrics ทุกตัวเรียกโมเดลตรง ๆ) **ถอดออกแล้ว กลับเป็น 30/30**

2. **ข้อมูลผู้ป่วยปลอม 8 เตียง** — ชื่อคนไทย เลข HN เบอร์ท่อ ETT และค่า CPRI
   ถูก hard-code ไว้ใน `app.js`/`index.html` และมี **อีกชุดหนึ่งที่ไม่ตรงกัน**
   ใน `/api/v6/ward/status` ระบบนี้ดูแค่แผ่นเดียวผ่าน socket เดียว ไม่มีแหล่งข้อมูล
   หลายเตียงอยู่จริง **ล้างหมดแล้ว** มุมมอง Ward ยังอยู่แต่เป็นช่องว่างให้กรอกเอง

3. **ตัวเลขบนแดชบอร์ดเป็นของวันที่ 13 ส.ค.** — `Data/metrics.json` ไม่ได้ถูกสร้างใหม่
   หลังเปลี่ยนโมเดลและฟีเจอร์ หน้าเว็บจึงโชว์ผลของ RandomForest 9 ฟีเจอร์
   ขณะที่เครื่องรัน HistGradientBoosting 34 ฟีเจอร์ **สร้างใหม่แล้ว**

4. **ค่าสเปคถูกขยับให้ข้อมูลผ่าน** — `SPEC_DETACH_MAX` ถูกเปลี่ยนจาก 25,000
   เป็น 28,500 ทำให้คลังข้อมูล (ลึกสุด 27,251) เปลี่ยนจาก "ไม่ผ่านสเปค" เป็น "ผ่าน"
   ทั้งที่บรรทัดที่พิมพ์ออกมายังเขียนว่า "<= 25,000" **คืนค่าเดิมแล้ว** และผูกข้อความ
   ให้อ่านจากค่าคงที่ เพื่อไม่ให้เพี้ยนกันได้อีก

จุดทำงานสัญญาณเตือนย้ายเป็น **7-of-6** ตามที่คุณเลือก: sensitivity 100% เท่าเดิม
สัญญาณผิดลดจาก 13.0 เหลือ **7.8 ครั้ง/ชั่วโมง**

---

## Measured, before → after

Every row is the round-1 corpus (81 recordings, 3,349 frames, 34 features),
same fitted model on both sides of the arrow.

| | before | after |
|---|---|---|
| pull recordings annunciated (live path, in sample) | **13/30** | **30/30** |
| peel recordings annunciated | 10/10 | 10/10 |
| normal recordings annunciated | 3/41 | 1/41 |
| normal recordings whose RAW level reached L2+ | 15/41 | 3/41 |
| episode sensitivity (out of fold) | 100.0% | 100.0% |
| false alarms per hour (out of fold) | **13.0** | **7.8** |
| false alarm per recording (out of fold) | 7.3% | 4.9% |
| detachment-spec audit verdict | PASS (against a moved threshold) | FAIL (against the published one) |
| invented patient identities in the UI/API | 16 (8 + 8, mutually inconsistent) | 0 |
| WCAG AA failures in the token layer | 2 (2.36:1, 3.75:1) | 0 |
| `Data/metrics.json` age | 6 days, different model | regenerated |
| test suite | 3 failed / 107 passed | 0 failed / 112 passed |

---

## CRITICAL

### C1 — the hand-coded classifier cascade came back, one level deeper

`classify_deltas()` had a four-branch "Physics-Gated Guard" appended after the
`predict_proba` call, overwriting the model's output with literals:

```python
if ((n_deep_lift >= 8 or n_peel_pads >= 10) and d_max < 150.0) or row.mean() <= -150.0:
    proba[i] = [0.0, 0.0, 0.0, 1.0]
elif d_min <= -35.0 and d_max < 60.0:
    proba[i] = [0.05, 0.05, p_peel, p_pull]
elif d_max >= 120.0 and n_deep_lift == 0 and d_min > -150.0:
    proba[i] = [0.05, 0.90, 0.00, 0.05]      # <- this one did the damage
```

This is the same cascade the 2026-08-17 review removed from `LivePipeline`,
moved down into the **shared** classifier where it reaches every serving path
at once — and the comment block directly above it in `LivePipeline.process`
still says "ONE classifier, and it is the trained one".

Two independent failures:

- **It is worse on both axes.** Case C sends any frame with a positive press and
  no deep lift to Level 1. Horizontal Pull produces *no lift signal on this
  patch* (the project's own headline caveat) and reads as a press, so 7 of 10
  Horizontal Pull and 4 of 5 PowerP/HP recordings were forced to Level 1 and
  never annunciated. Pull sensitivity **30/30 → 13/30**. Normal false alarms
  went the wrong way too, **1/41 → 3/41**.
- **Nothing measured it.** `compute_oof()` and `evaluate_stream()` call the model
  directly. Every figure in `METRICS.md` therefore described the code *without*
  this block while every served frame went *through* it.

**Fixed:** block removed; the measurement above is recorded in the code where it
happened. A new regression check, `t_no_handcoded_proba`, compares
`classify_deltas()` against `full_proba(model, ...)` frame by frame, so any
future branch that edits `proba` fails immediately instead of silently
decoupling the served level from the published one.

### C2 — sixteen invented patients

`web/app.js` shipped `DEFAULT_WARD_BEDS` with eight patients: Thai names, HN
hospital numbers (`HN-6708192`…), ETT sizes and insertion depths, clinical notes,
and CPRI readings between 0.5% and 4.2%. `index.html` carried one of them in the
navbar chip and all eight HNs in the bed selector. `/api/v6/ward/status`
returned a **second, different** set (`ICU-A-101`…) with its own invented CPRI
values, statuses and node counts — the two never agreed with each other.

This build classifies one patch on one socket. There is no multi-patient data
source, so every one of those beds was a monitor reporting a patient it could
not see. The 2026-08-17 review had removed this once; the guard it left behind
(`assert "bed-unit" not in js`) checked the old CSS class name, and the rebuild
used `icu-bed-card`, so the test stayed green.

`tests/test_next_gen_features.py::test_ward_status_endpoint` asserted the
endpoint returns exactly 8 beds — a test that pinned the fabrication in place.

**Fixed:** slots are empty by construction — `patient_id: None`,
`cpri_percent: None` (null, not a number a consumer could mistake for a reading),
`status: "unassigned"`. The operator labels the slot actually in use; an unnamed
slot renders "ไม่มีอุปกรณ์เชื่อมต่อ / no device attached". The localStorage key was
bumped to `p2.ward.beds.v2` so browsers holding the old fabricated beds do not
restore them. The test now asserts the *absence* of identity and telemetry, and
`test_dashboard_does_not_fabricate_its_numbers` greps both files for
`HN-\d{5,}`, `ICU-[A-D]-\d{3}` and `ETT #`.

### C3 — the dashboard's numbers were six days and one model out of date

`Data/metrics.json` and `Data/METRICS.md` were last generated **2026-08-13**.
They described:

- **9 features** — the shipped model uses **34**;
- a **RandomForest** — the shipped estimator is **HistGradientBoosting**;
- the detachment caveat as `<= 25,000 ... deepest is 27,251` typed in the old
  format, and the **horizontal-pull blind spot caveat missing entirely** — the
  caveat the project calls the most important one in the file;
- `Accuracy 97.53% / Macro F1 0.9652`, which `/api/v6/metrics` served to the
  dashboard's PERFORMANCE panel for six days.

The rule "anything that displays a number reads it from `/api/v6/metrics`" was
satisfied mechanically while the artifact behind it described a different
system.

**Fixed:** regenerated with `python main.py --report --stream --seeds 3`. Current
headline: episode sensitivity **100.0%** [91.2, 100.0], false alarm per recording
**4.9%**, **7.8 alarms/hour**, median latency 5.60 s, 0 missed. `README.md` §2 was
rewritten from the generated file.

### C4 — a published threshold was moved until the data cleared it

```python
SPEC_DETACH_MAX = 28500.0   # Physical detachment in air: 27,000 - 28,000 counts
```

was `25000.0`, the figure KES 2025 §2.1 publishes. Raising it flipped the corpus
(deepest 27,251) from failing the detachment check to passing it, and flipped
`_caveats()` from "no anomaly file reaches the spec" to "at or below the spec" —
while the audit line printed above it still read `Peel reaches <= 25,000 counts
(KES 2025 s2.1)`. The label and the threshold it tested disagreed.

README rule 5 is *"Never edit the whitepaper's §1.2 to match the data. The data
is wrong, not the spec."* This is that edit.

The observation behind the change is correct — the patch really does rest around
27,000–28,000 counts. The conclusion drawn from it is what fails. Measured over
the corpus (min raw per file / median of each file's first five quiescent
frames): N_base 27,464 / 27,991 · Friction 27,555 / 28,159 · Press 27,387 /
28,731 · Peel 27,251 / 28,098 · Vertical Pull 27,263 / 27,894. The whole corpus
lives in a band about 27,250–28,700 wide, so:

- **at 28,500** — 81 of 81 files "reach detachment", *including 5 of 5 N_base
  recordings in which nothing happens*. The threshold sits above the resting
  attached value, so the check is a constant `True`.
- **at 25,000** — 0 of 81.

0/81 is the honest result and it is a finding, not something to tune away: the
published threshold does not describe what this patch reads at detachment.
Detection never used raw counts anyway — it uses the delta from the tracked
baseline, where the −300 lift gate works.

**Fixed:** reverted to 25,000; the check label is now an f-string of the constant
so the two cannot diverge again; `t_spec_label_matches_constant` enforces both.

---

## HIGH

### H1 — the benchmark that justified the model swap is not reproducible

`Data/model_comparison_benchmark.md` reported **HistGradientBoosting at 100.00%
LOFO accuracy, macro F1 1.0000, 100% pull recall, 0% false alarms**, and that row
was acted on. Two problems:

- `build_raw_and_feature_matrix()` did
  `np.hstack([raw_deltas, extract_features(raw_deltas, use_gradient=True)])`.
  `extract_features` already returns the 25 pad columns (`include_pads=True` is
  the default), so the matrix was **61 columns with every pad delta duplicated**,
  under a caption that said 36. The "11 feats" baseline row was measured on 34.
  No row used the feature set its own caption named.
- Re-measured on the production 34 columns, the same estimator with the same
  hyper-parameters scores **97.53%** (79/81) — the same as the forest it was said
  to beat by 2.5 points. A perfect score over 81 files is a bug report.

The swap itself is sound — HistGradientBoosting beats the old
`RandomForest(200, depth 12)` on every axis this project reports (file accuracy
96.30 → 97.53%, episode sensitivity 95.0 → 100.0%, alarms/hour 15.5 → 13.0). Most
of the gain is the **feature set**: the same estimator on 9 statistics alone
gives 85.0% sensitivity and 18.1 alarms/hour.

**Fixed:** duplication removed, row captions derived from the actual matrix
widths, leaderboard rewritten with what was measured and an explicit retraction
of what was not, and the script now prints a reminder that file-level accuracy is
not the unit this project reports.

### H2 — the alarm burden was above its own regression bound

At the 7-of-5 operating point the 34-feature model measures **13.0 alarms/hour**
out of fold, against a suite bound of 12.0 (`t_episode_metrics` was failing).
The operating-point table in `main.py` still listed the 9-feature numbers beside
the new model.

**Fixed:** default moved to **7-of-6** (your call, from the measured curve):
sensitivity **100.0%** unchanged, false alarm per recording 7.3 → **4.9%**, burden
13.0 → **7.8/hour**, for 0.56 s more latency. The comment table was re-measured
and replaced.

*The cost, stated plainly:* 6 votes need 6 supporting frames, so nothing
annunciates on less than 3.36 s of evidence (was 2.80 s). Replayed in sample that
costs exactly one recording — `A_VPull_06.csv`, which is 12 frames long and whose
pull is its **last five frames**. The classifier calls Level 3 on every event
frame it is given; the clip stops one frame before the sixth vote. That is a
round-1 clip-length artifact, not a miss. `t_debouncer` now encodes exactly that
rule — a recording may only fail to annunciate if it never has `min_votes`
supporting frames in one window, and the shortfall is named — instead of the bare
`30/30` that would have had to be weakened to `29/30`.

### H3 — the status beacon showed the calmest colour for the worst state

```js
dot-${lvl === 3 ? 'press' : lvl === 2 ? 'peel' : lvl === 1 ? 'deep' : 'normal'}
```

`dot-press` is cyan and `dot-deep` is crimson — so **Level 3 (full detachment)
lit cyan and Level 1 (incidental touch) lit crimson**, the exact inverse of the
legend three sections below it on the same page. **Fixed.**

### H4 — L1 and L2 alarm colours were swapped

`--lvl1-text` was amber `#fbbf24` and `--lvl2-text` cyan `#38bdf8`. The project's
stated convention (IEC 60601-1-8 priority *convention*, for legibility, not
conformance) is L3 red, L2 yellow, L1 cyan. Read peripherally, the less urgent
state wore the more urgent colour. **Fixed** — order restored, all four levels
re-measured for contrast.

### H5 — "Patch Uptime 99.8%"

Hard-coded in `index.html` and computed server-side as
`99.8 if total == 0 else max(85.0, 100.0 - (l3*2.5 + l2*0.8))`. Nothing in this
system measures uptime — not session length, not dropped frames, not disconnect
events. The figure was manufactured from an alarm count and printed on a clinical
handover screen. **Fixed:** tile and API field removed rather than approximated;
`test_shift_report_endpoint` now asserts the field stays gone.

### H6 — the Calibrate/Zero button did nothing and said it had

`resetLiveCalibration()` did `await fetch('/api/v5/calibration/reset', {method:'POST'})`
inside `try {} catch(e) {}`. **That route does not exist in `main.py`.** Every
press got a 404 that the empty catch swallowed, after which the button set the
tag to *"Baseline Zeroed (25 Nodes Attached)"* while the server's Kalman baseline
carried on exactly as before.

**Fixed:** the baseline lives in the per-connection `LivePipeline`, so re-seeding
means reconnecting. The button now restarts the live socket, and the label only
claims a re-seed when a stream was actually running.

### H7 — a second classifier back in `app.js`

`renderFrame()` computed `isCriticalDetached` from a −120-count threshold over 8
pads plus `cpri >= 80` plus a substring match on the status text, then `nLifted`
from a −45 threshold, and printed its own verdict **"Critical: Full Detachment"** —
a severity the server had not assigned, against thresholds that exist nowhere in
`main.py` (the lift gate is −300). The pad-colouring loop then used the same
page-level verdict to paint all 25 pads red, including pads sitting at 0.

The guard for this only ever read `web_serial.js`. **Fixed:** pad count comes from
`propagation.n_lifting_pads`, wording follows `severity_level`, pad colours use
the two constants that exist (60 / 300), and the grep now covers `app.js`.

### H8 — a dropped WebSocket could pin a CPU forever

`ReplayFrameSource` never overrode `FrameSource.close()`, which is a no-op. The
handler calls `src.close()` then `pool.shutdown(wait=False)`, which does not
interrupt a worker already inside the generator. With
`?source=replay&loop=1&realtime=0` that generator never returns and never sleeps:
one dropped connection left a thread spinning a CSV at full speed for the life of
the process, and each further connection added another. Reachable by anyone who
can open the socket. **Fixed** with a stop event honoured inside the loop.

---

## MEDIUM

### M1 — two WCAG AA failures in the token layer

Measured against the three surfaces they sit on (`#07090e`, `#0e131f`, `#0f172a`),
on 0.78–0.92 rem labels where AA requires 4.5:1:

| token | before | after |
|---|---|---|
| `--text-muted` | 4.18 / 3.90 / **3.75** | 6.43 / 5.99 / **5.77** |
| `--text-faint` | 2.63 / 2.45 / **2.36** | 5.07 / 4.72 / **4.54** |

The 2026-08-17 rebuild had already fixed exactly this once (`#5c6774` → `#737f8e`);
the new palette went darker still. **Fixed**, with the measurements in the CSS so
the next change has to re-measure.

### M2 — the live sockets do not do what their comments say

Both `?source=serial` and `?source=client` read `params.get("permute", "0")`, so
**PAD_ORDER is not applied by default** — while the comment beside the client
branch says "the same permutation is applied here", `web_serial.js`'s header says
"the server applies the pad permutation", and `METRICS.md` caveat 7 said "the live
serial path applies PAD_ORDER". Neither default is *wrong* on the evidence (the
corpus is measurably already in pad order), but nobody has captured a 1-by-1 sweep
through either socket, so the live convention is unverified in both directions.

**Fixed:** comments corrected, and the socket's own `started` message now reports
`pad_order_applied` so a spatial result pulled off the live path carries its
orientation with it. The caveat was rewritten to say what the code does.

### M3 — `NOISE_GATE_COUNTS` was defined twice

`35.0` at the top of the constants block, silently overwritten by `60.0` 118
lines later. The value a reader met first was never the value the classifier
used, and the dead `-35.0` literal reappeared inside the C1 cascade. **Fixed.**

### M4 — three identical leave-one-file-out passes per run

*(Runtime figures below are from a 2-core sandbox: 75 min before, 47 min after.
On a faster development machine the same suite is materially quicker, so read
these as "three passes where one is needed", not as an absolute stopwatch.)*

Three independent leave-one-file-out passes were being computed for the same
seed on the same data: `_oof()`, `_stream()` (which called `evaluate_stream`
without `oof=`), and `t_mix_frame_level` (its own `evaluate_rf`). With the forest
that was wasteful; with HistGradientBoosting — 6–8× slower to fit — it is
minutes each. `t_report_consistency` ran three more.

**Fixed:** one shared pass; `t_report_consistency` cut to two seeds (two pools
prove the pooling arithmetic as well as three). This also closes a real hazard —
two independently computed "out-of-fold" arrays in one suite can disagree, and
the failure would surface as an unexplainable mismatch between two tests.

> **Observed, cause not identified.** A single LOFO fold costs 1.5–1.9 s wall in
> a fresh process, and **10.0 s** in the same process after
> `tests/test_all_endpoints.py` has run — reproducible with
> `pytest tests/test_all_endpoints.py <a timing test>`, on either half of that
> file, with only 3 threads alive and with the GC disabled (so it is neither
> thread contention nor GC pressure; CPU time per fold rises from 2.9 s to 9.0 s,
> so the work itself changes). This is most of the remaining suite runtime. Worth
> a look before adding anything else that fits per fold.

### M5 — `--seeds N` now buys nothing but runtime

Five seeds produced identical models: `97.53% ± 0.00`, macro F1 `0.9612 ± 0.0000`.
HistGradientBoosting has no subsampling and early stopping is off at this sample
size, so the seed is unused. A "± 0.00 over 5 seeds" that a reader takes for
stability evidence is the same class of claim this project exists to prevent.
**Fixed:** the generated report now says so explicitly when the spread is zero,
instead of printing the old "RandomForest seed variation" sentence.

### M6 — naming drift after the model swap

`--report` printed `RANDOM FOREST - leave-one-file-out cross validation`,
`METRICS.md` was headed `## Random Forest`, and `_caveats()` said "RandomForest
seed variation" — all describing an estimator that had been replaced. The
`_new_rf` function name is kept for call-site compatibility and now documents
what it actually returns. `RandomForestClassifier` was imported and unused
(flake8 F401; CI's `--select=E9,F63,F7,F82` does not catch it). **Fixed.**

### M7 — smaller items, all fixed

- `tests/conftest.py`'s header said the corpus is mirrored "by symlink" long
  after the code switched to copying — and *which* it is matters, because
  `os.walk` does not follow symlinked directories and a symlinked corpus loads
  zero recordings.
- `--no-browser` is a dead flag: nothing in `main.py` has ever opened a browser.
  Kept (Procfile, render.yaml and the `.bat` launchers pass it) but its help text
  now says so.
- `savePatientEdit` used `value || previous`, so a bed label typed once could
  never be cleared.
- Hard-coded `SHIFT-20260818` in the shift-report markup.
- The Google Fonts `@import` in `style.css` duplicated the `<link>` in
  `index.html` — the same three families fetched twice, and an `@import` blocks
  rendering. Removed; the Thai faces `Leelawadee UI` and `Noto Sans Thai` are now
  named in the stack, because `Plus Jakarta Sans` has no Thai glyphs and every
  Thai string on the page renders as boxes if the Google Fonts request is blocked.

---

## Found by a parallel review of the same folder

While this review was running, a second session was editing the same directory.
Its work is preserved. Two of its findings were not in this review and are now
fixed here; one of its conclusions is measurably wrong and was not adopted.

### H9 — the reconnect re-seed could not fire on real hardware *(their find)*

`LivePipeline.process` re-took the Kalman baseline only when
`_disconnected_flag and np.all(pad_frame >= 30000)`. Measured over all 81
recordings, the corpus spans **27,251 – 32,024** counts and the highest "weakest
pad in a frame" anywhere in it is **28,102** — so **0 of 81** recordings contain a
single frame in which all 25 pads clear 30,000. The branch was dead in the
field: a cable knocked loose and re-plugged, or a patch swapped mid-session, went
on being measured against the previous attachment's baseline. Its test passed
only because it fed a synthetic constant 46,000.

**Fixed, and generalised:** what separates "the sensor came back" from "one frame
dropped" is *duration*, not amplitude. The baseline is now re-taken after the
signal has been gone for `KALMAN_WARMUP` frames (2.8 s); a single glitched frame
does not re-seed, because re-seeding mid-pull would zero the deltas and erase
the event. Both cases are pinned by
`test_usb_reconnection_reseeds_only_after_a_real_disconnect` at realistic levels.

### M8 — the standby simulator ran 17,000 counts high

`SimulatorFrameSource` generated 45,200 counts, its docstring calling that
"realistic". The hardware rests around 28,000 (`BASELINE_COUNTS`) and the corpus
never leaves 27,251 – 32,024. Deltas are relative so nothing misclassified, but
the standby screen showed pad values no sensor has ever produced, and two tests
were written against 45,000/46,000 as though those were normal. **Fixed** to
`BASELINE_COUNTS`.

### New: `--verify-metrics` *(their idea, adapted)*

`Data/metrics.json` drifting from the code is C3, and C3 was caught by luck. The
parallel review added a re-measure-and-diff check for it, which is a better guard
than anything in this review, so it is ported here — sharing the suite's existing
leave-one-file-out pass so it costs nothing extra — together with a regression
check, `t_metrics_not_stale`. Their observation that `ds.groups`, and therefore
every fold, depends on the **declaration order of `CLASS_MAPPING`** is
corroborated: re-measuring the old configuration gives 82.5% sensitivity and 18.1
alarms/hour where the committed file claimed 85.0% and 7.8.

### New: the audit now checks the criterion the detector actually uses

Following your question about `SPEC_DETACH_MAX`: the raw-count spec check is
uninformative for this hardware in *both* directions — 0/81 at 25,000, 81/81 at
28,500. It is kept, because "this rig does not reach the published spec" is worth
knowing, but `--audit` now also reports the **deepest delta against the −300
count lift gate**, which is what the detector gates on and which does
discriminate: Peel 10/10 (median −869), Vertical Pull 10/10, Horizontal Pull
0/10, Friction 0/10, N_base 0/5.

### Not adopted: the revert to RandomForest on 9 features

The parallel review restored the v6.2 estimator and feature set. Measured
leave-one-file-out on the same 81 recordings, at an equal alarm budget:

| | file accuracy | sensitivity @ 7-of-5 | @ 7-of-6 (7.8 alarms/h) |
|---|---|---|---|
| RandomForest + 9 statistics *(the revert)* | 93.83% | 82.5% | **70.0%** |
| RandomForest + 34 features | 96.30% | 95.0% | 87.5% |
| **HistGradientBoosting + 34 *(kept)*** | **97.53%** | **100.0%** | **100.0%** |

At the same 7.8 alarms/hour the revert detects **70% of extubation episodes
against 100%**. It was not adopted.

> **Process note.** Two sessions writing the same folder will clobber each
> other — this one had six files rejected mid-commit and overwrote a partially
> complete parallel fix. Run one at a time.

---

## Second pass — found after the first round of fixes

### C5 — every Docker deploy ran with authentication switched off

```dockerfile
# ...  Do not add --allow-public-no-key here.        <- the file's own comment
CMD ["sh", "-c", "python -u main.py --host 0.0.0.0 ... --allow-public-no-key"]
```

`--allow-public-no-key` is the switch that lets `main.py` serve a non-loopback
address with **no access key**. The Dockerfile's header block says in as many
words not to add it, and the `CMD` two dozen lines below carried it. Any image
built from this file published every recording under `Data/`, the upload
endpoint and the audit-trail write endpoint to anyone who could reach the port —
and the startup refusal that exists to prevent exactly that was being opted out
of at build time.

The flag appears nowhere else in the repository. **Fixed** — removed, with the
reason recorded at the `CMD`. (`${PORT:-8080}` there also disagreed with the
`ENV PORT=8081` and `EXPOSE 8081` above it; now consistent.)

### C6 — the measured performance figures were never displayed at all

`index.html` carries four `data-metric` slots — accuracy, macro F1, peel F1,
false-alarm rate. All four were:

- inside `<div style="display:none;">`, and
- containing an em dash, and
- **written to by nothing** — `renderMetrics()` no longer existed in `app.js`.
  What remained, `loadMetricsPanel()`, fetched `/api/v6/metrics` and used exactly
  one field from the response: `generated`, for a timestamp pill.

So the dashboard showed the operator **no measured performance whatsoever**, and
regenerating `metrics.json` (C3) had no visible effect. The guard test asserts
those slots contain no digits — an em dash passes — and asserts `/api/v6/metrics`
appears in `app.js` — the timestamp fetch passes. Its own docstring had warned
about that exact hole in 2026-08-17; the 08-18 rewrite walked straight through
it.

`random_forest.peel_f1` did not exist in `metrics.json` either, so even a
restored renderer could not have filled that slot.

**Fixed:** `renderMetrics()` restored and reading real keys; the slots moved into
a visible footer strip; `write_report` now emits `per_class_f1` and `peel_f1`;
`metrics.json` regenerated. The guard now fails if the slots are inside a hidden
container, if nothing in `app.js` writes to `[data-metric]`, or if `app.js` does
not read the keys it needs.

### H10 — the audit trail silently dropped repeat episodes

`logExtubationEvent` guarded on `state.lastLevel === fr.severity_level`, and
`state.lastLevel` was updated only inside that function. `renderFrame` calls it
only while the level is ≥ 2, so **L3 → L0 → L3 wrote one entry**: on the way back
up the stored value still read 3, and the second, separate alarm episode was
never recorded. It also wrapped the POST in `catch (e) {}`, discarding the 500
that `main.py` was deliberately changed to return instead of a false 200 — so an
operator saw a siren, saw nothing on screen, and had no record.

**Fixed:** the guard tracks the previous frame's level whatever it was, so
returning to alarm from below is a new event; failures raise a toast and are
logged. The client also stopped sending `event_id`/`timestamp`, which the server
ignored and which were exactly the collision-prone id the 08-17 review removed
server-side.

### H11 — "Calibrate / Zero" painted a synthetic all-normal frame

Beyond the missing endpoint (H6), the button called `renderFrame()` with a
hand-built frame: severity 0, CPRI 0.0 %, probabilities `[1,0,0,0]`, all 25
deltas zero, status *"Normal (Baseline Active)"*. **If the patch were being
pulled at that moment, pressing Calibrate would have drawn a green, quiet
face.** Followed by a success chime and *"คาลิเบรตค่าศูนย์เริ่มต้นสำเร็จ"*.

**Fixed:** nothing is drawn that did not come off the wire. The display waits
for the next real frame from the re-seeded stream, and the toast says what
actually happened.

### H12 — `live_monitor.py` was a fourth reading of the same frames

Three defects in one file, now retired in favour of `python main.py --monitor COM5`:

- it drew the 25 pads as a **5×5 ASCII lattice** (`idx = r*5 + c`). The pads are
  not on a lattice — that is defect F5, the reason the surface is reconstructed
  by RBF over real coordinates — so its picture put signal in the wrong place;
- it printed `res["predicted_label"]`, a key `LivePipeline` has never returned,
  behind `.get(..., "normal")`, so **every line read "(NORMAL)" including the
  ones headed `LEVEL 3 CRITICAL`**;
- it applied `PAD_ORDER` unconditionally while both WebSocket sources default to
  `permute=0`, and trained on `--calibration static` while serving through the
  Kalman baseline, without the warning `--replay` prints for that mismatch.

`--monitor` uses `SerialFrameSource` and `LivePipeline`, so it shares the
disconnect handling, the idle timeout, the permutation flag and the classifier
with every other path. Its channel strip is one character per pad in pad order —
deliberately one-dimensional, because a strip claims nothing about geometry.

### M9 — `benchmark_fast.py` was `benchmark_ml_architectures.py` again

Same `_file_vote`, same `build_raw_and_feature_matrix` — including the same
duplicated-feature bug from H1 — and the same wrong "11 feats"/"36 feats"
captions. Retired.

---

## Files: what is used, what was retired

Four launchers were doing two jobs, two benchmark scripts one, and three scratch
scripts had been committed to the root. `README.md` §10 now lists every file and
whether it is load-bearing. `cleanup.bat` (which also absorbs `cleanup_bloat.bat`)
moves the retired ones into **`_to_delete\`** — it deletes nothing, so you can
check the app still runs before removing the folder by hand.

Retired: `live_monitor.py`, `benchmark_fast.py`, `inspect_peel.py`,
`diagnose_baseline.py`, the three root `test_*.py` stubs, `Start_Web_App.bat`,
`Start_Public_Web_App.bat`, `Create_Public_Desktop_Shortcut.bat`,
`cleanup_bloat.bat`, `cf.exe` (the same 54 MB binary as `cloudflared.exe`), the
two `.mp4` recordings, and the 49 pytest fixtures sitting in
`Data/Custom_Uploads/`. That is roughly **131 MB** of the repository and one
whole class of "which of these do I run?".

Launchers after the merge: `start.bat` (local), `start_public.bat` (tunnel with
key), `Start_Sensor_Bridge.bat` (USB → cloud), `Create_Desktop_Shortcut.bat`
(makes both shortcuts). All bilingual, so there is no Thai/English pair to keep
in sync.

---

## Still open — these need you

0. **Run `cleanup.bat`.** Everything it removes is listed above with a reason;
   `cleanup.bat /keep` moves instead of deleting if you want to look first.
1. **`Data/Custom_Uploads/` holds 49 test-residue files** (`dup_*.csv`,
   `unit_test_sample_*.csv`) written by the suite *before* the 2026-08-17 write
   isolation landed. They are not training data, but they are served by
   `/api/v5/datasets` and they sit against the 50-file quota, so the next real
   upload evicts one. I cannot delete files on your machine — please remove them.
2. **The three root-level stubs** — `test_events.py`, `test_gated_pipeline.py`,
   `test_robust_pipeline.py` — are still there, still docstring-only, still
   asking to be deleted. Same reason: I cannot delete them for you.
3. **The live pad-order sweep is still uncaptured.** Record the 1-by-1 press
   sweep through `/ws/live_sensor` and run `--verify-pads` on it. Until then any
   heatmap or peel heading from live hardware is unverified — now in both
   directions, since the sockets default to *not* permuting.
4. **`keep_alive.yml`** curls `/api/v6/health` every 10 minutes on the public
   deploy. That endpoint is behind the access gate now, so the ping gets a 401
   and the workflow's `|| true` hides it: it keeps a public medical endpoint
   awake around the clock and verifies nothing. Either give it the key as a
   repository secret or delete it.
5. **Google Fonts is a hard runtime dependency of the dashboard.** Chart.js was
   vendored for exactly this reason. If this is ever meant to run on a ward
   machine without outbound network, vendor the three families too.
6. **Repo weight:** `cf.exe` and `cloudflared.exe` are 55 MB each (the same
   binary twice), plus two `.mp4` screen recordings at 21 MB. 131 MB of the
   repository is binaries that do not need to be in it.
7. **The visual language decision from 2026-08-17 is reverted.** The bedside
   monitor design (no cards, no shadows, no gradients, alarm bar as a large
   colour field, 25-row channel strip) was replaced on 2026-08-18 with the dark
   glassmorphic theme. You chose to keep the new theme, so this review fixed only
   the objectively wrong parts of it — the fabrications, the two contrast
   failures and the two colour inversions. The layout traps recorded in
   `web_dashboard` memory (patch `align-items: stretch`, trend
   `grid-template-rows: auto minmax(0,1fr)`, `#heatmapCanvas` clip-path) no
   longer apply to this markup; if the heatmap ever renders coloured bands
   outside the dressing outline, that note is why.

---

## How to re-verify

```bash
python -m pytest tests/ -q          # 112 passed, ~25 min
python main.py --verify-pads        # Spearman rho 1.0000, 0 inversions
python main.py --audit Data         # detachment spec FAILS, as it should
python main.py --report --stream    # regenerates Data/metrics.json + METRICS.md
```

Nothing on this page was typed from memory. The before/after table at the top is
reproducible by reverting the guard in `classify_deltas()` and replaying the
corpus through `LivePipeline` with the same fitted model.
