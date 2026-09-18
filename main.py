# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
# pyright: reportUnknownArgumentType=false, reportMissingTypeStubs=false
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportUnnecessaryCast=false, reportOptionalCall=false
# pyright: reportInvalidTypeForm=false, reportGeneralTypeIssues=false
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, reportAssignmentType=false
# pyright: reportArgumentType=false
"""
===============================================================================
TOUCH SENSOR SELF-EXTUBATION EARLY WARNING SYSTEM - MASTER EXECUTABLE v6.3
===============================================================================
Project2 | 25-channel capacitive smart dressing (90 mm x 120 mm)

Usage
-----
  python main.py                     train + serve dashboard (loopback)
  python main.py --eval              Leave-One-File-Out benchmark (RF)
  python main.py --eval-temporal     grouped CV benchmark (RF vs BiLSTM)
  python main.py --plots             research plots -> Data/research_plots/
  python main.py --replay "Normal Mix/N_Mix_01.csv"   stream a CSV as if live
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import csv
import difflib
import collections
import glob
import hashlib
import hmac
import io
import json
import logging
import math
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.interpolate import RBFInterpolator
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, auc, classification_report, confusion_matrix, f1_score, roc_curve
from sklearn.model_selection import LeaveOneGroupOut, StratifiedGroupKFold

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

# Setup M4 Structured Logging Subsystems
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger_loader = logging.getLogger("project2.loader")
logger_model = logging.getLogger("project2.model")
logger_api = logging.getLogger("project2.api")
logger_serial = logging.getLogger("project2.serial")

# M2 & M3 Concurrency & Security Locks & Limits
EVENT_LOG_LOCK = threading.Lock()

# ---- Audit trail tamper evidence (IEC 62304 s5.1.1 / ISO 13485 s4.2.5) -------
# Every event written from here on carries the hash of the event before it, so
# altering or removing one event invalidates every event after it. This is
# tamper EVIDENCE, not tamper PROOF: anyone who can write the file can also
# recompute the whole chain. It answers "was this trail edited after the fact by
# something that did not know about the chain", which is the realistic failure
# (a hand edit, a partial restore, a truncating writer), and it is what a
# reviewer can check independently with nothing but this file and sha256.
AUDIT_GENESIS_HASH = "0" * 64
# Events written before 2026-09-18 have no chain fields. They are reported as an
# unverifiable prefix rather than as a break, because calling 547 pre-existing
# records "tampered" would train everyone to ignore the check.
AUDIT_CHAIN_FIELDS = ("prev_hash", "hash")


def audit_event_hash(event: Dict[str, Any], prev_hash: str) -> str:
    """SHA-256 over the event's own fields plus the previous event's hash.

    The event is serialised with sorted keys and no insignificant whitespace so
    that the digest depends on content only, never on dict ordering or on how
    json.dump happened to indent it. `hash` itself is excluded - it is the
    output - while `prev_hash` is included, which is what links the chain.
    """
    body = {k: v for k, v in event.items() if k != "hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def verify_audit_chain(logs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Recompute the chain and report the first event that does not match.

    Returns `status` one of:
      "empty"        - nothing to check
      "legacy_only"  - no event carries chain fields yet
      "intact"       - every chained event verifies
      "broken"       - `broken_at` names the first event that does not
    `legacy_events` counts the unchained prefix, which is reported but not
    treated as a failure.
    """
    report: Dict[str, Any] = {"total": len(logs), "legacy_events": 0,
                              "chained_events": 0, "broken_at": None}
    if not logs:
        report["status"] = "empty"
        return report

    prev = AUDIT_GENESIS_HASH
    started = False
    for idx, event in enumerate(logs):
        if not all(f in event for f in AUDIT_CHAIN_FIELDS):
            if started:
                # A gap AFTER the chain began means an event lost its fields.
                report["status"] = "broken"
                report["broken_at"] = {"index": idx,
                                       "event_id": event.get("event_id"),
                                       "reason": "chain fields missing"}
                return report
            report["legacy_events"] += 1
            continue
        started = True
        report["chained_events"] += 1
        if event["prev_hash"] != prev:
            report["status"] = "broken"
            report["broken_at"] = {"index": idx, "event_id": event.get("event_id"),
                                   "reason": "prev_hash does not match the previous event"}
            return report
        expected = audit_event_hash(event, prev)
        if not hmac.compare_digest(expected, str(event["hash"])):
            report["status"] = "broken"
            report["broken_at"] = {"index": idx, "event_id": event.get("event_id"),
                                   "reason": "event content does not match its hash"}
            return report
        prev = event["hash"]

    report["status"] = "intact" if started else "legacy_only"
    return report

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # M3: 5 MB size limit
MAX_CUSTOM_UPLOADS = 50             # M3: 50 file quota limit

# M7 access-gate throttle. Deliberately NOT module state: the failed-attempt
# table used to be a module-level defaultdict, so every app built in one process
# shared it. A test that exhausted the limit left the next app pre-throttled
# (measured: a fresh app's FIRST request answered 429), which is an order-
# dependent suite and, in a process serving two apps, cross-tenant leakage.
# create_app() now owns one table per app; these are just the tunables.
AUTH_WINDOW_S = 60.0                # sliding window for failed attempts
AUTH_MAX_FAILURES = 10              # failures per window per client before 429
AUTH_TABLE_MAX_IPS = 10_000         # hard cap so the table cannot grow forever

# Number of empty bed slots the dashboard's ward panel lays out. These are UI
# placeholders the operator labels by hand - this build has one live socket and
# no multi-patient data source. See /api/v6/ward/status.
WARD_BED_SLOTS = 8

# =============================================================================
# 1. CONSTANTS, PHYSICAL LAYOUT AND WIRING
# =============================================================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.realpath(os.path.join(PROJECT_DIR, "Data"))
RESEARCH_PLOTS_DIR = os.path.join(DATA_ROOT, "research_plots")
WEB_DIR = os.path.join(PROJECT_DIR, "web")     # the dashboard, served by create_app
MODEL_PERSISTENCE_PATH = os.path.join(DATA_ROOT, "trained_model.joblib")
# Integrity digest for the above, kept OUTSIDE the pickle - see
# load_persisted_model() for why a field inside it is not a check.
MODEL_DIGEST_PATH = MODEL_PERSISTENCE_PATH + ".sha256.json"

BASELINE_COUNTS = 28000.0        # nominal C0, KES 2025 section 2.1
COUNTS_PER_PF = 59.85            # sensor resolution, [MEASURED], docs/Hardware_Deck_Spec.md
NOMINAL_BASELINE_PF = 30.0       # absolute C0 of the attached patch, in picofarads.
# Corroborated only indirectly: the CDC parts shortlisted to replace this board
# (AD7147 / AD7746 / FDC2214) were chosen for a 0-50 pF range, which would be the
# wrong part if the patch sat at hundreds of pF. The Sensor Structure table in
# docs/Hardware_Deck_Spec.md still has this row empty, so it has never been
# measured directly. spec_detach_reachability() below is why that empty row matters.


def spec_detach_reachability(spec_counts: float,
                             baseline_counts: float = BASELINE_COUNTS,
                             counts_per_pf: float = COUNTS_PER_PF,
                             baseline_pf: float = NOMINAL_BASELINE_PF) -> Dict[str, float]:
    """Can this sensor physically produce `spec_counts`, at this scale?

    Three published numbers have to agree and do not:

      * the patch rests at ~28,000 counts while attached      (BASELINE_COUNTS)
      * the sensor reads 59.85 counts per picofarad           (COUNTS_PER_PF, [MEASURED])
      * KES 2025 s2.1 says detachment reaches <= 25,000 counts (SPEC_DETACH_MAX)

    28,000 - 25,000 = 3,000 counts, and 3,000 / 59.85 = 50.1 pF. The whole
    attached patch is about 30 pF. Losing 50 pF from a 30 pF capacitor is not a
    fixation problem, it is a negative capacitance: at C = 0 - the patch gone,
    floating in air - the reading still floors at 28,000 - 30 x 59.85 = 26,205
    counts, 1,205 counts ABOVE the threshold it is supposed to cross.

    So no FIXATION change - pump pressure, adhesive - can make a recording
    satisfy this criterion: fixation decides how completely the patch lets go,
    and letting go completely still lands at 26,205. Round 1 bottoming out at
    27,251 is not evidence that the fixation was bad; it is roughly a 12.5 pF
    loss, which is a real partial peel.

    What CAN move it is the patch geometry, because it moves C0 itself:
    C = eps * A / d, so halving the backing thickness d roughly doubles the
    resting capacitance, and a ground plane turns a fringing-field sensor into
    a real two-plate one. Take C0 from ~30 pF to ~60 pF and a 50 pF loss on
    full detachment becomes physically possible. That is the supervisor's
    advice of 2026-09-17 - thinner backing, ground plane - and it is why that
    part of the rig rebuild is worth doing even though the pump is not the
    lever it was taken for.

    At least one of the three numbers is wrong, and the arithmetic cannot say
    which. The candidates: the absolute C0 is much larger than 30 pF (the empty
    row above), or the spec's "counts" belong to different firmware, or s2.1
    means a RELATIVE drop and not an absolute floor.

    Nothing here changes SPEC_DETACH_MAX. Rule 5 of README section 1 stands: the
    spec is not edited to fit the data. This reports the contradiction so that
    it is argued with the person who wrote s2.1, instead of being chased with a
    stronger vacuum pump - which is what docs/ACTION_PLAN.md P0-2 was about to do.
    """
    floor = baseline_counts - baseline_pf * counts_per_pf
    drop_needed = baseline_counts - spec_counts
    return {
        "floor_counts_at_zero_capacitance": floor,
        "drop_needed_counts": drop_needed,
        "drop_needed_pf": drop_needed / counts_per_pf,
        "available_pf": baseline_pf,
        "reachable": floor <= spec_counts,
        "shortfall_counts": max(0.0, floor - spec_counts),
    }
SAMPLE_PERIOD_S = 0.560          # microcontroller acquisition cycle
DELTA_THRESHOLD = 300.0          # dual-colour threshold
# NOTE: NOISE_GATE_COUNTS is defined once, in the LivePipeline gate section
# below. A second definition (35.0) used to sit here and was silently
# overwritten by the 60.0 one further down, so the value a reader saw first was
# never the value the classifier used.

N_PADS = 25
N_CLASSES = 4

# Physical centre of each pad, in percent of the 90 mm x 120 mm patch.
# Pad numbering follows the 1-by-1 press sequence used during characterisation.
PHYSICAL_PAD_COORDS: Dict[int, Tuple[float, float]] = {
    1: (57.0, 90.0),     2: (73.0, 78.0),     3: (58.0, 78.0),     4: (79.0, 64.0),     5: (65.0, 64.0),
    6: (80.0, 50.0),     7: (65.0, 50.0),     8: (80.0, 36.0),     9: (65.0, 36.0),     10: (74.0, 24.0),
    11: (58.0, 22.0),     12: (50.0, 64.0),     13: (50.0, 50.0),     14: (50.0, 35.0),     15: (41.0, 90.0),
    16: (40.0, 78.0),     17: (26.0, 78.0),     18: (35.0, 64.0),     19: (21.0, 64.0),     20: (35.0, 50.0),
    21: (20.0, 50.0),     22: (35.0, 36.0),     23: (20.0, 36.0),     24: (40.0, 22.0),     25: (25.0, 24.0),
}

# FIX F2 -------------------------------------------------------------------
# The firmware emits channels as Signal-1..Signal-25 in electrical order.
# The physical pad at position k is wired to the channel below. Feeding raw
# Signal order into the coordinate table (as v5.0 did) scrambles the patch.
#
# *** A9 - RESOLVED FOR THE CSV CORPUS, STILL OPEN FOR LIVE HARDWARE. ***
# All round-1 recordings carry Sensor-* headers, so read_raw_csv takes the
# "already in pad order" branch and this permutation is NEVER applied to them.
# That branch is now measured rather than assumed: Data/Press/1_by_1.csv is a
# 1-by-1 press sweep, every column peaks in strictly increasing time order
# (Spearman rho 1.0000, 0 inversions), so Sensor-N == physical pad N and
# applying PAD_ORDER to this corpus would scramble the patch. Re-run it with
# `python main.py --verify-pads` after any firmware or logger change.
#
# STILL OPEN: SerialFrameSource and the ?source=client ingest path both apply
# this permutation to Signal-* frames, and no sweep has been captured through
# either, so spatial output from LIVE hardware is still unverified. To close it,
# record the same 1-by-1 sweep through /ws/live_sensor and re-run --verify-pads.
#
# What is and is not at risk:
#   safe      - the 9 base features are permutation-invariant (min/max/mean/std
#               and threshold counts over all 25 pads), so every accuracy,
#               sensitivity and false-alarm figure holds either way.
#   at risk   - the heatmap, the peel-propagation origin/heading/description,
#               the LOOP 3 figure, and --gradient features. On A_Peel_01 the
#               same frame reads "peeling from mid-right, spreading W" one way
#               and "peeling from top-left, spreading S" the other.
#
# Corroborating the measurement: on the 10 Peel files, the pads below -300
# counts form a spatially tighter cluster under the as-is reading (mean pairwise
# distance 33.9) than under the permuted one (42.6), against a 37.9 random-pad
# null - a peel should lift a contiguous patch. That agrees with the sweep.
#
# The check that settles it is implemented as verify_pad_order() below; run it
# with `python main.py --verify-pads`. A propagation direction measured from the
# CSV corpus can go in the paper; one measured from live hardware cannot yet.
PAD_TO_SIGNAL: Tuple[int, ...] = (
    20, 21, 19, 22, 18, 23, 17, 24, 16, 25, 15, 14, 13, 12, 6,
    7, 5, 8, 4, 9, 3, 10, 2, 11, 1,
)
# 0-based permutation: PAD_ORDER[k] = index into the Signal-* vector for pad k+1
PAD_ORDER: np.ndarray = np.array([s - 1 for s in PAD_TO_SIGNAL], dtype=int)

PAD_XY: np.ndarray = np.array([PHYSICAL_PAD_COORDS[i] for i in range(1, N_PADS + 1)], dtype=float)

# Folder name -> class. Round 1 used the "... NO G" names; the round-2 SOP
# prescribes the shorter VPull / HPull. Both are accepted: a recording session
# is expensive, and silently dropping a whole class because a folder was named
# the other way is the most costly failure this loader can have.
CLASS_MAPPING: Dict[str, Dict[str, Any]] = {
    "N_base": {"label": 0, "class_name": "0: Normal Baseline"},
    "N_Base": {"label": 0, "class_name": "0: Normal Baseline"},
    "Baseline": {"label": 0, "class_name": "0: Normal Baseline"},
    "Brief Touch": {"label": 1, "class_name": "1: Incidental Touch"},
    "Touch": {"label": 1, "class_name": "1: Incidental Touch"},
    "N_Touch": {"label": 1, "class_name": "1: Incidental Touch"},
    "Press": {"label": 1, "class_name": "1: Hand Press"},
    "N_Press": {"label": 1, "class_name": "1: Hand Press"},
    "Friction": {"label": 1, "class_name": "1: Clothing Friction"},
    "N_Fric": {"label": 1, "class_name": "1: Clothing Friction"},
    "Fric": {"label": 1, "class_name": "1: Clothing Friction"},
    "Normal Mix": {"label": 1, "class_name": "1: Normal Mix Activity"},
    "N_Mix": {"label": 1, "class_name": "1: Normal Mix Activity"},
    "Peel": {"label": 2, "class_name": "2: Dressing Peel (Warning)"},
    "A_Peel": {"label": 2, "class_name": "2: Dressing Peel (Warning)"},
    "Vertical Pull NO G": {"label": 3, "class_name": "3: Vertical Pull (Alarm)"},
    "VPull": {"label": 3, "class_name": "3: Vertical Pull (Alarm)"},
    "A_VPull": {"label": 3, "class_name": "3: Vertical Pull (Alarm)"},
    "Horizontal Pull NO G": {"label": 3, "class_name": "3: Horizontal Pull (Alarm)"},
    "HPull": {"label": 3, "class_name": "3: Horizontal Pull (Alarm)"},
    "A_HPull": {"label": 3, "class_name": "3: Horizontal Pull (Alarm)"},
    "PowerP": {"label": 3, "class_name": "3: Power Pull (Critical)"},
    "PowerPull": {"label": 3, "class_name": "3: Power Pull (Critical)"},
}

CLASS_LABEL_NAMES: Tuple[str, ...] = ("0: Baseline", "1: Touch/Press", "2: Peel", "3: Pull")

# Severity text carried in the API payload. No emoji: this is a clinical
# readout, and an emoji in one is the loudest possible signal that the screen was
# not designed for the room it is going into. The dashboard renders its own
# localised copy of these from web/app.js; this is what non-browser consumers
# (--replay, the CLI, a downstream logger) print.
#
# Level numbering follows the IEC 60601-1-8 priority CONVENTION for colour in the
# UI - 3 red, 2 yellow, 1 cyan, 0 green - which is a legibility decision, not a
# conformance claim. See the notice in web/index.html.
STATUS_TEXT_MAP: Dict[int, str] = {
    0: "Normal - baseline (ปกติ)",
    1: "Contact - hand press or touch (สัมผัส/กดทับ)",
    2: "Warning - dressing peeling or partial pull (เริ่มลอก/ดึงบางส่วน)",
    3: "Critical - full detachment (หลุดทั้งแผ่น)",
}

MIN_FRAMES_PER_FILE = 5          # files shorter than this cannot be calibrated
KALMAN_WARMUP = 5                # frames held at Level 0 while the baseline settles

# LivePipeline physics gate. A frame whose largest excursion is below this is
# quieter than the baseline swing the SOP itself tolerates (criterion 5 allows
# 100 counts), so it is held at Level 0 without consulting the classifier. This
# can only ever suppress an alarm, never create one; it is set below the
# quietest anomaly signal in the corpus (Horizontal Pull still reaches +456 on
# the contact side) so it cannot mask a real event.
NOISE_GATE_COUNTS = 60.0
LIFT_GATE_COUNTS = -300.0

# --- Jitter suppression (2026-09-18) -----------------------------------------
# The robustness sweep measured a cliff: episode sensitivity 92.5% at noise
# sd 30, 87.5% at sd 60, then 60.0% at sd 120 with 16 of 40 episodes missed.
# The annunciator needs 6 of 7 consecutive frames to vote the same way, and
# single-frame jitter breaks those runs - the detector goes deaf rather than
# jumpy, which is the dangerous failure for this device.
#
# A 3-tap median removes an isolated bad frame and leaves a step edge exactly
# where it was, which is the whole reason it is a median and not a mean: a
# sustained pull or a sudden peel passes through unchanged.
#
# It must not run on bench data. Data/metrics.json was measured without it, so
# activating on quiet frames would silently re-measure every published figure.
#
# The activation statistic and its gate are MEASURED, not assumed, and the first
# two attempts at both were wrong. The per-frame median across pads of
# |d[t]-d[t-1]| does NOT separate noise from signal: on the round-1 corpus its
# 99th percentile is 128 counts and its maximum 475, because a press sweep moves
# most of the patch at once. What does separate is the same statistic taken over
# a whole file or stream, where a sustained noise floor shows and a few seconds
# of event does not:
#
#   per-file median jitter    bench      sd 30       sd 60        sd 120
#   min / median / max        6.7/9.0/38  25.7/32.5/56.7  48.9/59.0/85.3  104.9/117.5/141.0
#
# Bench tops out at 38.0 (N_Press_04) and sd 60 starts at 48.9, so the gate sits
# at 44: off on every one of the 81 recordings, on for every file at sd 60 and
# sd 120. It does NOT engage at sd 30, which is deliberate - sensitivity there
# is already 92.5% and the cliff being fixed is at sd 120.
JITTER_ACTIVATE_COUNTS = 44.0
JITTER_TAPS = 3                  # causal: median(d[t-2], d[t-1], d[t])
JITTER_WINDOW_FRAMES = 30        # live: transitions the running estimate covers

# --- Quiescent negative-step recovery (2026-09-18) ---------------------------
# Six of the ten Brief Touch recordings were started with a finger already on
# one or two pads, so those channels seeded high and then read 470-810 counts
# BELOW a baseline that was never valid - past the lift gate, for the whole
# file, in recordings labelled normal (docs/PHYSICS_TO_FEATURE_MAP.md section 9).
#
# A real detachment is mechanical: the pad keeps moving, and its neighbours move
# with it. A finger that has been lifted off leaves a channel that is deeply
# negative and then perfectly still. Those are separable, and this is where they
# are separated - a channel below the lift gate whose recent raw counts have a
# standard deviation under 15 for 3 seconds, while FEWER than PEEL_MIN_PADS
# channels are below the gate at all, is a bad zero and not a patient event.
QUIESCENT_RECOVERY_SECONDS = 3.0
QUIESCENT_RECOVERY_SD = 15.0     # counts; bench per-pad noise floor is 8.6
QUIESCENT_P_GROWTH = 1.6         # per frame, so the baseline walks rather than jumps
QUIESCENT_P_CAP = 4.0            # times r_vec -> Kalman gain tops out near 0.8

# Seed-time per-channel contamination. seed_plausibility() takes the median
# across 25 pads, which is exactly the statistic one or two elevated channels
# cannot move: N_Touch_02 and N_Touch_06 both seed inside ATTACHED_SEED_BAND
# while carrying a contaminated pad.
#
# The threshold is set by what a RESTING patch does, because a check that fires
# on a clean baseline is worse than no check. Measured per-file maximum
# deviation of a seed channel from its own frame median:
#
#   N_base (nothing touching the patch)   492 - 510 counts
#   Friction / Peel / pulls               up to ~716, from mounting, not touch
#
# The patch is NOT flat: pads sit at genuinely different absolute capacitances
# (docs/CONTOUR_AND_STEP_HEIGHT_COMPENSATION_GUIDE.md). Deviation from the
# frame's own median therefore does not work, and measuring it first is what
# showed why - the five N_base recordings, with nothing touching the patch at
# all, already span 492-510 counts of pad-to-pad spread, so any threshold low
# enough to catch a contaminated channel also fires on a clean baseline.
#
# What a contaminated channel actually breaks is the patch's SHAPE: its own
# topography, pad by pad. SEED_RESTING_SHAPE is that shape, the per-pad median
# of the five resting seeds, and the comparison is offset-corrected - the whole
# reference is shifted to the frame's own median before the deviation is taken -
# so a patch resting at a different absolute C0 is judged on shape alone. That
# matters for round 2, where a thinner backing and a ground plane will change
# C0 deliberately, and for any CDC board, where the absolute level is different
# by construction.
#
# Measured maximum per-pad deviation from the offset-corrected shape, per file:
#
#   folder                  min   median   max
#   N_base                    9       24    189      nothing touching the patch
#   Peel                    340      410    421
#   Friction                241      343    466
#   Horizontal Pull         498      507    536
#   Power Pull              493      527    569
#   Vertical Pull           498      520    627
#   Brief Touch             206      374    632
#   Normal Mix              522      581   1204
#   Press                   456     1806   2442      started mid-press
#
# The gate is 575: above every Peel, Friction, Horizontal Pull and Power Pull
# recording and more than three times the worst resting file, and below
# N_Touch_02 (600) and N_Touch_06 (632) - the two recordings with independent
# within-file evidence of contamination. Tally at 575: N_base 0/5, Peel 0/10,
# Friction 0/10, Horizontal Pull 0/10, Power Pull 0/10, Vertical Pull 2/10,
# Brief Touch 2/10, Normal Mix 3/5, Press 10/11.
#
# The margin over the two target files is 4% and 10%, which is thin, and that is
# why this status is ADVISORY: it asks an operator to look, it does not gate a
# frame or change a classification. What actually repairs a bad zero live is the
# quiescent recovery below, which needs no threshold on the seed at all.
#
# The reference is corpus-derived and round-1 specific. It is re-derived from
# Data/ by tests/test_seed_plausibility.py, exactly as ATTACHED_SEED_BAND is, so
# it cannot silently drift from the recordings it describes - and it will have
# to be re-measured when the patch is re-built.
SEED_CHANNEL_OUTLIER_COUNTS = 575.0
SEED_RESTING_SHAPE = np.array([
    27955.4, 27913.2, 27938.0, 28208.8, 28156.2, 27769.6, 28193.4, 28196.4,
    28114.6, 27705.2, 27993.8, 27896.8, 28414.4, 27911.4, 27882.0, 27806.4,
    27493.2, 28206.2, 28228.2, 28202.0, 28457.6, 28381.2, 28156.6, 27861.2,
    27521.6], dtype=float)

# LOOP 3 peel gate, tuned on the full corpus (see PatchSpatialField.propagation)
PEEL_MIN_PADS = 3                # simultaneous pads below -DELTA_THRESHOLD
PEEL_MEAN_GATE = -150.0          # whole-grid mean delta, counts
PEEL_PERSIST_FRAMES = 3          # 1.68 s; removes the press-release transient
# Annunciator operating point. This is a CLINICAL decision, not a
# hyperparameter: it trades missed extubations against alarm fatigue. The full
# measured curve is printed by --report and reproduced in README.
#
# Reference point for the alarm burden: a retrospective ICU cohort reports a
# median 119 alarms per patient per day, ~5/hour (Sci Rep 2022,
# s41598-022-26261-4). That paper states plainly that no threshold defining a
# "high" alarm rate exists, so the default below is justified as roughly
# doubling the existing burden - NOT as sitting under a published safe limit.
# An earlier draft of this comment cited a "~10/hour desensitisation threshold";
# that figure had no source and has been removed.
# Tuned on round-1 data - re-validate on round 2 untouched.
#
# Re-measured 2026-08-19, out of fold, on the 34-feature model that actually
# ships (25 pad deltas + 9 statistics). The table below REPLACES an earlier one
# measured on the 9-statistic feature set; every row moved when the pad features
# were added, and the old numbers had been left in place beside the new model.
#
#   window  k  hold |  sensitivity  false alarm/rec  alarms/hour  latency
#      5    3    9  |    100.0%          12.2%          20.7       3.92 s
#      3    3    0  |    100.0%          12.2%          25.9       3.92 s
#      5    4    9  |    100.0%           9.8%          15.5       4.48 s
#      7    5    9  |    100.0%           7.3%          13.0       5.04 s
#   >  7    6    9  |    100.0%           4.9%           7.8       5.60 s  <- default
#      5    5    9  |     97.5%           2.4%           5.2       5.04 s
#
# 7-of-6 is the default because on this corpus it DOMINATES the previous 7-of-5
# point: identical 100% episode sensitivity, false alarms per recording 7.3% ->
# 4.9%, and the alarm burden 13.0 -> 7.8 per hour, for 0.56 s more latency on a
# 5.6 s alarm. 5-of-5 is quieter still but drops a real event (97.5%), which is
# not a defensible trade for a safety device. Chosen 2026-08-19 with the user;
# it is a clinical trade-off, so change it only by re-measuring the curve.
#
# THE COST, STATED PLAINLY: 6 votes need 6 supporting frames, so nothing can be
# annunciated on less than 3.36 s of evidence (5 votes needed 2.80 s). Replaying
# the corpus through LivePipeline in sample, that costs exactly one recording -
# Vertical Pull NO G/A_VPull_06.csv, which is 12 frames long and whose pull is
# its LAST FIVE frames. The classifier calls level 3 on every event frame in it;
# the clip simply stops one frame before the sixth vote. That is a round-1
# recording-length artifact, not a detection failure, and the round-2 SOP's
# 60-120 s recordings do not have it - but if a real event can be shorter than
# 3.4 s, this is the row to revisit.


@dataclass
class AlarmConfig:
    """Annunciator operating point.

    A dataclass rather than three module-level constants: main() rebound
    uppercase names through `global`, which every type checker flags as
    redefining a constant, and which left the effective operating point
    invisible to anything importing this module instead of running it.
    """

    window: int = 7                  # 3.92 s decision window
    min_votes: int = 6               # k of n frames must support the level
    hold: int = 9                    # 5.04 s hold after the last supporting frame

    def validate(self) -> "AlarmConfig":
        self.window = max(1, int(self.window))
        self.min_votes = max(1, min(int(self.min_votes), self.window))
        self.hold = max(0, int(self.hold))
        return self


ALARM = AlarmConfig()


def signals_to_pads(frame: np.ndarray) -> np.ndarray:
    """Reorder a Signal-1..25 vector (or N x 25 matrix) into physical pad order."""
    arr = np.asarray(frame, dtype=float)
    if arr.ndim == 1:
        return arr[PAD_ORDER]
    return arr[:, PAD_ORDER]


# =============================================================================
# 2. BASELINE CALIBRATION  (LOOP 4: Kalman adaptive drift compensation)
# =============================================================================
def static_baseline(raw: np.ndarray, k: int = 5) -> np.ndarray:
    """Original scheme: offset from the mean of the first k frames.

    Kept for backwards comparability. Note this is exactly the step that
    breaks when the operator starts moving before frame k.
    """
    arr = np.asarray(raw, dtype=float)
    k = min(k, len(arr))
    return arr + (BASELINE_COUNTS - arr[:k].mean(axis=0))


@dataclass
class KalmanBaseline:
    """Per-channel scalar Kalman filter tracking the slow baseline C0(t).

    State      : b_i(t), the quiescent capacitance of channel i
    Process    : b_i(t) = b_i(t-1) + w,  w ~ N(0, q)   (sweat / thermal drift)
    Measurement: z_i(t) = b_i(t) + v,    v ~ N(0, r)   (sensor noise)

    A raw touch or peel is *not* baseline drift, so the update is gated: when
    the innovation exceeds `gate` counts the sample is treated as an event and
    the baseline coasts on its prediction instead of chasing the event. Without
    that gate a 30 s press would be silently absorbed into C0.
    """

    q: float = 0.05         # process noise; environmental drift is slow
    r: float = 40.0         # measurement noise ~ observed baseline sd
    gate: float = 120.0     # counts; prevents active touches and peels from corrupting baseline
    warmup: int = KALMAN_WARMUP   # frames used to seed the state

    b: Optional[np.ndarray] = None
    p: Optional[np.ndarray] = None
    r_vec: Optional[np.ndarray] = None
    gate_vec: Optional[np.ndarray] = None

    def reseed(self) -> None:
        self.b = None
        self.p = None
        self.r_vec = None
        self.gate_vec = None

    def seed(self, frames: np.ndarray) -> "KalmanBaseline":
        arr = np.asarray(frames, dtype=float)
        if arr.ndim == 1:
            arr = arr[None, :]
        n = min(self.warmup, len(arr))
        n_channels = arr.shape[1] if arr.ndim > 1 and arr.shape[1] > 0 else N_PADS
        if n > 0:
            raw_b = arr[:n].mean(axis=0).astype(float)
        else:
            raw_b = np.full(n_channels, BASELINE_COUNTS, dtype=float)

        # F3: Physical plausibility bounds validation (10,000 to 45,000 counts)
        # Prevents placement transients or touches on frame 0 from permanently poisoning baseline state.
        valid_mask = np.isfinite(raw_b) & (raw_b >= 10000.0) & (raw_b <= 45000.0)
        if not np.all(valid_mask):
            fallback = float(np.median(raw_b[valid_mask])) if np.any(valid_mask) else BASELINE_COUNTS
            raw_b = np.where(valid_mask, raw_b, fallback)
        self.b = raw_b.astype(float)

        # Adaptive Baseline Auto-Tuning: compute per-channel noise variance
        if n >= 2:
            clean_arr = np.where(
                np.isfinite(arr[:n]) & (arr[:n] >= 10000.0) & (arr[:n] <= 45000.0),
                arr[:n],
                self.b[None, :]
            )
            stds = np.std(clean_arr, axis=0)
            self.r_vec = np.clip(stds ** 2, 20.0, 150.0).astype(float)
        else:
            self.r_vec = np.full(n_channels, self.r, dtype=float)

        self.gate_vec = np.full(n_channels, self.gate, dtype=float)
        self.p = np.copy(self.r_vec)
        return self

    def step(self, z: np.ndarray) -> np.ndarray:
        """Advance one frame, return the delta of z against the tracked baseline."""
        if self.b is None or self.p is None:
            self.seed(np.asarray(z, dtype=float)[None, :])
        assert self.b is not None and self.p is not None
        z = np.asarray(z, dtype=float)

        # predict
        p_pred = self.p + self.q
        innovation = z - self.b

        if not np.isfinite(innovation).all():
            return z - self.b

        # gated update: quiescent channels track, active channels coast
        r_eff = self.r_vec if self.r_vec is not None else self.r
        gate_eff = self.gate_vec if self.gate_vec is not None else self.gate
        quiescent = np.abs(innovation) < gate_eff
        k_gain = np.where(quiescent, p_pred / (p_pred + r_eff), 0.0)
        self.b = self.b + k_gain * innovation
        self.p = (1.0 - k_gain) * p_pred

        return z - self.b

    def run(self, raw: np.ndarray) -> np.ndarray:
        """Vectorised convenience: returns the delta matrix for a whole file."""
        arr = np.asarray(raw, dtype=float)
        self.seed(arr)
        return np.vstack([self.step(row) for row in arr])


def jitter_estimate(delta: np.ndarray) -> np.ndarray:
    """Per-transition noise estimate: median across pads of |d[t] - d[t-1]|.

    Length n-1 for an n-frame matrix. A median over 25 channels is the point:
    during a real event a handful of pads move by hundreds of counts and this
    statistic does not follow them, so it measures the noise floor and not the
    signal. Measured on the round-1 corpus it sits near 10-12 counts throughout,
    against 34 / 68 / 135 under the sd 30 / 60 / 120 perturbations.
    """
    d = np.asarray(delta, dtype=float)
    if d.ndim != 2 or len(d) < 2:
        return np.zeros(0, dtype=float)
    return np.median(np.abs(np.diff(d, axis=0)), axis=1)


def adaptive_jitter_filter(delta: np.ndarray,
                           activate: float = JITTER_ACTIVATE_COUNTS) -> np.ndarray:
    """Causal 3-tap median on records whose measured noise floor is high.

    *** NOT IN THE SERVING PATH. This was tried, measured, and removed. ***

    The idea was sound and the arithmetic is correct: a median removes an
    isolated bad frame and leaves a step edge exactly where it was, and the
    activation gate was set from measurement so that it changed nothing at all
    on the 81 round-1 recordings. It was wired into load_dataset() and
    LivePipeline on 2026-09-18 and the robustness sweep was re-run:

        variant        sensitivity        false alarms      alarms/h   missed
        noise_sd60     87.5% -> 72.5%     7.3% -> 12.2%     7.8 -> 15.5   5 -> 11
        noise_sd120    60.0% -> 62.5%     4.9% -> 12.2%     5.2 -> 13.0  16 -> 15

    It made the cliff worse, not better. At sd 60 sensitivity fell fifteen
    points while false alarms rose; at sd 120 sensitivity moved 2.5 points,
    well inside the confidence interval, for more than double the false alarms.

    The mechanism is the one thing a median cannot help with here. A causal
    3-tap window delays an event by up to two frames and shortens it by as much
    again, and the annunciator needs 6 of 7 CONSECUTIVE frames to agree. The
    corpus's events are short - vertical pull averages a handful of usable
    frames - so trimming two off each end costs more votes than the jitter did.

    Kept, unwired, because the negative result is worth more than the code: it
    says the noise cliff is not a filtering problem and will not be fixed in
    software. It is a front-end problem, which is the argument for the absolute
    CDC board. tests/test_jitter_suppression.py pins both the maths and the fact
    that nothing calls this.
    """
    d = np.asarray(delta, dtype=float)
    if d.ndim != 2 or len(d) < JITTER_TAPS:
        return d
    jit = jitter_estimate(d)
    if jit.size == 0 or float(np.median(jit)) <= activate:
        return d
    # The decision is per file, not per frame: a frame-by-frame gate cannot be
    # set, because a press sweep produces the same instantaneous statistic as a
    # noisy board. What is different is that noise persists and an event does
    # not, which is what the median over the whole record measures.
    out = d.copy()
    out[JITTER_TAPS - 1:] = np.median(
        np.stack([d[:-2], d[1:-1], d[2:]]), axis=0)
    return out


def calibrate(raw: np.ndarray, mode: str = "static") -> np.ndarray:
    """Return the delta-from-baseline matrix under the requested scheme."""
    arr = np.asarray(raw, dtype=float)
    if mode == "kalman":
        return KalmanBaseline().run(arr)
    if mode == "kalman_norm":
        # F10 (scale-normalised delta) applied offline, the same way LivePipeline
        # applies it live: divide each delta by the Kalman baseline it was measured
        # against, then re-express it at the nominal 28,000-count scale. On bench
        # data C0 ~= BASELINE_COUNTS, so this is a near no-op; it is what keeps a
        # patch resting at a different C0 (thinner backing, ground plane, other
        # skin) from shifting every count threshold downstream. Before this mode
        # existed, F10 ran only in LivePipeline and every published offline figure
        # measured a pipeline the device does not run.
        kal = KalmanBaseline().seed(arr)
        rows = []
        for row in arr:
            delta = kal.step(row)
            c0 = kal.b if kal.b is not None else np.full(arr.shape[1], BASELINE_COUNTS, dtype=float)
            safe_c0 = np.where(c0 > 1000.0, c0, BASELINE_COUNTS)
            rows.append(compute_fractional_deltas(delta, safe_c0) * BASELINE_COUNTS)
        return np.vstack(rows)
    return static_baseline(arr) - BASELINE_COUNTS


# =============================================================================
# 3. SPATIAL FIELD  (FIX F1 + LOOP 3: peel propagation vector field)
# =============================================================================
class PatchSpatialField:
    """Thin-plate-spline reconstruction over the true pad coordinates.

    FIX F1: v5.0 built the grid with meshgrid(x[60], y[80]) -> shape (80, 60)
    and then reshaped the result to (60, 80). Element count matched, so numpy
    stayed silent and the rendered patch came out transposed - a hotspot on the
    left edge appeared on the right. Rows are now y, columns are x, explicitly.
    """

    def __init__(self, n_rows: int = 80, n_cols: int = 60, smoothing: float = 1e-2) -> None:
        self.n_rows = n_rows      # samples along y (patch is 120 mm tall)
        self.n_cols = n_cols      # samples along x (patch is 90 mm wide)
        self.smoothing = smoothing
        self.points = PAD_XY
        gx = np.linspace(10.0, 90.0, n_cols)
        gy = np.linspace(10.0, 95.0, n_rows)
        grid_x, grid_y = np.meshgrid(gx, gy)          # both (n_rows, n_cols)
        assert grid_x.shape == (n_rows, n_cols)
        self.grid_coords = np.column_stack([grid_x.ravel(), grid_y.ravel()])

        # k-nearest neighbour index per pad, for the local gradient (LOOP 3)
        d = np.linalg.norm(self.points[:, None, :] - self.points[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        self.neighbours = np.argsort(d, axis=1)[:, :5]

    def interpolate(self, pad_values: ArrayLike) -> np.ndarray:
        """pad_values must already be in physical pad order. Returns (rows, cols)."""
        vals = np.asarray(pad_values, dtype=float)
        rbf = RBFInterpolator(self.points, vals, smoothing=self.smoothing, kernel="thin_plate_spline")
        return rbf(self.grid_coords).reshape(self.n_rows, self.n_cols)

    # ----- LOOP 3 ---------------------------------------------------------
    def node_gradients(self, pad_delta: ArrayLike) -> np.ndarray:
        """Local plane fit around each pad -> (25, 2) array of (dC/dx, dC/dy).

        Units are counts per percent of patch width/height. Fitting a plane to
        the 5 nearest physical neighbours respects the real irregular layout,
        unlike the 5x5 reshape this replaces (FIX F5).
        """
        v = np.asarray(pad_delta, dtype=float)
        grads = np.zeros((N_PADS, 2), dtype=float)
        for i in range(N_PADS):
            idx = np.concatenate([[i], self.neighbours[i]])
            dxy = self.points[idx] - self.points[i]
            dv = v[idx] - v[i]
            design = np.column_stack([dxy, np.ones(len(idx))])
            sol, *_ = np.linalg.lstsq(design, dv, rcond=None)
            grads[i] = sol[:2]
        return grads

    def propagation(self, pad_delta: ArrayLike,
                    min_pads: int = PEEL_MIN_PADS,
                    mean_gate: float = PEEL_MEAN_GATE,
                    adaptive_gates: Optional[ArrayLike] = None) -> Dict[str, Any]:
        """Summarise where the dressing is lifting and which way it is spreading.

        The gate is deliberately two-part. Firing on "any pad below -300" was
        true for 50.3% of Normal Mix frames, because releasing a finger press
        makes one pad undershoot in a way that looks identical to a local lift.
        A real peel also drags the whole-grid mean down; an incidental release
        does not. Measured across the corpus, the conjunction below holds on
        75.0% of Peel frames and 0.0% of Baseline / Brief Touch / Friction /
        Normal Mix frames.
        """
        v = np.asarray(pad_delta, dtype=float)
        if adaptive_gates is not None:
            gates = np.asarray(adaptive_gates, dtype=float)
            lifting = v <= gates
        else:
            lifting = v <= -DELTA_THRESHOLD
        n_lift = int(lifting.sum())
        grid_mean = float(v.mean())
        if n_lift < min_pads or grid_mean >= mean_gate:
            return {
                "active": False, "n_lifting_pads": n_lift, "grid_mean": round(grid_mean, 1),
                "origin": None, "centroid": None, "vector": [0.0, 0.0], "heading_deg": None,
                "description": "no sustained lift", "severity_pct": 0.0,
            }

        w = np.clip(-v, 0.0, None)
        w = w / w.sum()
        centroid = (self.points * w[:, None]).sum(axis=0)      # weighted centre of the lift
        origin_pad = int(np.argmin(v)) + 1                     # deepest drop = where it started

        # Propagation heads from the deepest point toward the weighted centroid.
        vec = centroid - self.points[origin_pad - 1]
        norm = float(np.linalg.norm(vec))
        heading = float(np.degrees(np.arctan2(-vec[1], vec[0]))) % 360.0 if norm > 1e-6 else None

        return {
            "active": True,
            "n_lifting_pads": n_lift,
            "grid_mean": round(grid_mean, 1),
            "origin": {"pad": origin_pad, "x": float(self.points[origin_pad - 1][0]),
                       "y": float(self.points[origin_pad - 1][1]), "delta": float(v[origin_pad - 1])},
            "centroid": [float(centroid[0]), float(centroid[1])],
            "vector": [float(vec[0]), float(vec[1])],
            "heading_deg": heading,
            "description": _describe_propagation(self.points[origin_pad - 1], heading, n_lift),
            "severity_pct": round(100.0 * n_lift / N_PADS, 1),
        }


def _quadrant(x: float, y: float) -> str:
    v = "top" if y < 40 else ("bottom" if y > 66 else "mid")
    h = "left" if x < 42 else ("right" if x > 58 else "centre")
    return f"{v}-{h}"


def _describe_propagation(origin: np.ndarray, heading: Optional[float], n_lift: int) -> str:
    start = _quadrant(float(origin[0]), float(origin[1]))
    if heading is None:
        return f"lift localised at {start} ({n_lift} pads)"
    compass = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"][int(((heading + 22.5) % 360) // 45)]
    return f"peeling from {start}, spreading {compass} ({n_lift} pads lifted)"


SPATIAL = PatchSpatialField()


class AlarmDebouncer:
    """k-of-n escalation with a hold-off.

    B1: this docstring used to open "per IEC 60601-1-8 expectations". Nothing
    here has been assessed against IEC 60601-1-8 (the medical alarm-system
    standard) - there is no mapping to its alarm-priority tone and colour
    tables and no conformity work of any kind. It is the same false-compliance
    claim that was removed from the dashboard, and the test written to catch
    that only scanned index.html and app.js, so this survived. The design below
    is *informed by* the idea of graded, debounced alarms; it does not conform
    to a standard.

    History - each version fixed the previous one's failure and introduced its own
    ------------------------------------------------------------------------------
    v6.0 required N *consecutive* frames at a level. It annunciated nothing when
    the classifier alternated 2/3, and could latch at 3 permanently.

    v6.1 used "every frame in the window >= k". Still all-or-nothing: one dropped
    frame silenced the alarm for 1.68 s, an alternating 1/3 stream (every other
    frame saying CRITICAL PULL) never annunciated, and 30% of the classifier's
    alarm evidence never reached the annunciator - 54 onsets for 38 continuous
    events, i.e. the siren re-armed mid-pull.

    v6.2 first draft used k-of-n plus a hold, but kept
    ``max(held_level, supported)`` while the hold was active. Incoming Level-2
    frames kept refreshing the hold, so a Level-3 alarm could never step down to
    a Level-2 warning - it stayed pinned at CRITICAL until the signal fell below
    warning entirely. That is v6.0's latch in a new shape.

    Current behaviour
    -----------------
    * **Support is counted at-or-above a level, not equal to it.** A classifier
      alternating 2,3,2,3 is continuously saying "at least a warning".
    * **The annunciated level is whatever the window currently supports.**
      Stepping 3 -> 2 takes at most ``window - min_votes + 1`` frames (1.12 s at
      the default 6-of-7) - the time for level 3 to lose its majority. That is a
      detection delay, not a latch.
    * **The hold covers dropouts, not de-escalation.** It keeps an alarm up
      through isolated misclassified frames; it never keeps a *higher* level
      alive once the evidence has moved to a lower one.
    * **Nothing below level 2 is ever annunciated as an alarm.**
    """

    def __init__(self, window: Optional[int] = None, min_votes: Optional[int] = None,
                 hold: Optional[int] = None) -> None:
        self.window = max(1, ALARM.window if window is None else window)
        self.min_votes = max(1, min(ALARM.min_votes if min_votes is None else min_votes,
                                    self.window))
        self.hold = max(0, ALARM.hold if hold is None else hold)
        self.level = 0
        self._history: List[int] = []
        self._held = 0
        self._held_level = 0

    def _supported(self) -> int:
        """Highest level with k-of-n support in the current window (0 if none)."""
        for candidate in range(N_CLASSES - 1, 1, -1):
            if sum(1 for h in self._history if h >= candidate) >= self.min_votes:
                return candidate
        return 0

    def update(self, raw_level: int) -> int:
        raw_level = int(raw_level)
        self._history.append(raw_level)
        if len(self._history) > self.window:
            self._history.pop(0)

        # R8. There is deliberately NO fast path for raw_level == 3.
        #
        # A previous revision added `if raw_level == 3: return 3` here, on the
        # reasoning that a critical event should not have to wait for a
        # majority. What it actually did was hand a single misclassified frame
        # the authority to sound the red siren - the exact failure mode this
        # class exists to prevent. Measured out of fold on the round-1 corpus:
        #
        #     normal recordings reaching Level 3   with the fast path  22/41
        #                                          k-of-n only          3/41
        #     false alarms per hour                with the fast path  127.0
        #                                          k-of-n only          ~6
        #
        # Every sensitivity and alarm-burden figure in METRICS.md is measured
        # through this method, so a level that skips the vote is a level whose
        # published numbers do not describe it. If level 3 genuinely needs to
        # annunciate sooner than level 2, that is a *separate operating point*
        # - a lower k for the top level - which has to be added to
        # operating_curve() and re-measured, not a branch that opts out of
        # debouncing. Guarded by the R8 checks in tests/test_regressions.py.
        supported = self._supported()
        if supported >= 2:
            self._held_level = supported          # follow the evidence, up or down
            self._held = self.hold
            self.level = supported
        elif self._held > 0:
            self._held -= 1                       # coast through a dropout
            self.level = self._held_level
        else:
            self._held_level = 0
            self.level = min(raw_level, 1)        # never annunciate unsupported
        return self.level

    def reset(self) -> None:
        self.level = 0
        self._held = 0
        self._held_level = 0
        self._history.clear()


class PeelTracker:
    """Stateful confirmation layer over PatchSpatialField.propagation.

    The per-frame gate alone still fires on 8/10 Press files, because letting
    go of a sustained press produces one or two frames that satisfy it.
    Requiring the gate to hold for PEEL_PERSIST_FRAMES consecutive frames
    (1.68 s) removes that entirely while keeping every Peel file:

        confirmed files, whole corpus, k=3
          Peel                  10/10        Baseline           0/5
          Press                  0/10        Brief Touch        0/10
          Friction               0/10        Normal Mix         0/5
    """

    def __init__(self, persist: int = PEEL_PERSIST_FRAMES, adaptive_gates: Optional[ArrayLike] = None) -> None:
        self.persist = persist
        self.streak = 0
        self.confirmed = False
        self.adaptive_gates: Optional[np.ndarray] = (
            np.asarray(adaptive_gates, dtype=float) if adaptive_gates is not None else None
        )

    def set_adaptive_gates(self, adaptive_gates: Optional[ArrayLike]) -> None:
        self.adaptive_gates = (
            np.asarray(adaptive_gates, dtype=float) if adaptive_gates is not None else None
        )

    def update(self, pad_delta: ArrayLike, adaptive_gates: Optional[ArrayLike] = None) -> Dict[str, Any]:
        eff_gates = adaptive_gates if adaptive_gates is not None else self.adaptive_gates
        info = SPATIAL.propagation(pad_delta, adaptive_gates=eff_gates)
        self.streak = self.streak + 1 if info["active"] else 0
        self.confirmed = self.streak >= self.persist
        info["streak_frames"] = self.streak
        info["confirmed"] = self.confirmed
        info["confirmed_after_s"] = round(self.persist * SAMPLE_PERIOD_S, 2)
        return info



# =============================================================================
# 4. FEATURE EXTRACTION  (FIX F5 + 36-Feature Gold Standard)
# =============================================================================
PAD_FEATURE_NAMES: Tuple[str, ...] = tuple(f"Pad-{i+1} Delta" for i in range(N_PADS))
BASE_FEATURE_NAMES: Tuple[str, ...] = (
    "Min Delta", "Max Delta", "Mean Delta", "Std Delta",
    "Drop Count (<= -300)", "Drop Count (<= -600)", "Drop Count (<= -1000)",
    "Spike Count (>= +300)", "Spike Count (>= +1000)",
)
GRAD_FEATURE_NAMES: Tuple[str, ...] = ("Grad Magnitude", "Grad Anisotropy")


def feature_names(use_gradient: bool = True, include_pads: bool = True) -> List[str]:
    names = list(PAD_FEATURE_NAMES) if include_pads else []
    names += list(BASE_FEATURE_NAMES)
    if use_gradient:
        names += list(GRAD_FEATURE_NAMES)
    return names


def extract_features(pad_delta: np.ndarray, use_gradient: bool = True, include_pads: bool = True) -> np.ndarray:
    """Frame-level features. `pad_delta` is (n_frames, 25) in physical pad order."""
    d = np.asarray(pad_delta, dtype=float)
    if d.ndim == 1:
        d = d[None, :]

    cols = [
        d.min(axis=1), d.max(axis=1), d.mean(axis=1), d.std(axis=1),
        (d <= -300.0).sum(axis=1).astype(float),
        (d <= -600.0).sum(axis=1).astype(float),
        (d <= -1000.0).sum(axis=1).astype(float),
        (d >= 300.0).sum(axis=1).astype(float),
        (d >= 1000.0).sum(axis=1).astype(float),
    ]

    if use_gradient:
        # FIX F5: computed on real coordinates, not a fictitious 5x5 lattice.
        mag = np.empty(len(d))
        aniso = np.empty(len(d))
        for i, row in enumerate(d):
            g = SPATIAL.node_gradients(row)
            m = np.linalg.norm(g, axis=1)
            mag[i] = float(m.mean())
            gx, gy = float(np.abs(g[:, 0]).mean()), float(np.abs(g[:, 1]).mean())
            aniso[i] = (gx - gy) / (gx + gy + 1e-9)
        cols += [mag, aniso]

    stat_mat = np.column_stack(cols)
    if include_pads:
        return np.hstack([d, stat_mat])
    return stat_mat


# =============================================================================
# 5. DATASET LOADING
# =============================================================================
SESSION_DIR_RE = __import__("re").compile(r"^S\d+$")

SIGNAL_COLS = [f"Signal-{i + 1}" for i in range(N_PADS)]
SENSOR_COLS = [f"Sensor-{i + 1}" for i in range(N_PADS)]


class CsvProblem(Exception):
    """A recording that cannot be used, with a reason fit for a human."""


def read_raw_csv(path: str, strict: bool = False,
                 convention_out: Optional[List[str]] = None) -> Optional[np.ndarray]:
    """Return an (n_frames, 25) matrix in physical pad order, or None.

    A recording aborted mid-write leaves a zero-byte CSV. pandas raises
    EmptyDataError from deep inside the call, which used to take down every
    mode of the program - including --audit, the tool whose entire job is to
    catch bad recordings. Failures are now named and, outside strict mode,
    returned as None so the caller can skip the file and carry on.

    A9: pass a list as `convention_out` and the branch taken is appended to it
    - "sensor" (columns trusted as pad order, no permutation) or "signal"
    (columns permuted through PAD_ORDER). Which branch a corpus takes decides
    whether every spatial figure in the paper is oriented or scrambled, so it
    is counted and reported rather than left to a comment. A plain list keeps
    this caller-local: the API serves requests concurrently and must not race
    on shared state.
    """
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: file is empty (aborted recording?)")
        return None
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: unreadable CSV ({exc.__class__.__name__})")
        return None

    try:
        if all(c in df.columns for c in SENSOR_COLS):
            arr = df[SENSOR_COLS].to_numpy(dtype=float)  # assumed already in pad order
            if convention_out is not None:
                convention_out.append("sensor")
        elif all(c in df.columns for c in SIGNAL_COLS):
            arr = signals_to_pads(df[SIGNAL_COLS].to_numpy(dtype=float))
            if convention_out is not None:
                convention_out.append("signal")
        elif df.shape[1] >= 25:
            try:
                arr = df.iloc[:, :25].to_numpy(dtype=float)
                if convention_out is not None:
                    convention_out.append("raw25")
            except Exception:
                arr = None
        else:
            arr = None
    except (ValueError, TypeError) as exc:
        # A garbled UART token ("2800x") makes pandas type the column as text.
        # This is far likelier than a zero-byte file given SerialFrameSource
        # parses text lines, and it used to escape every guard.
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: non-numeric value ({exc})")
        return None
    if arr is None:
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: missing the 25 sensor columns")
        return None

    if arr.size and not np.isfinite(arr).all():
        # sklearn >= 1.4 trains happily on NaN, so a serial glitch would never
        # surface - it would just quietly shift the drop-count features.
        n_bad = int((~np.isfinite(arr)).sum())
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: {n_bad} non-finite value(s)")
        return None
    return arr


def describe_csv_problem(path: str) -> str:
    """Human-readable reason a CSV was rejected (empty string if it is fine)."""
    try:
        arr = read_raw_csv(path, strict=True)
    except CsvProblem as exc:
        return str(exc).split(": ", 1)[-1]
    if arr is None:
        return "unreadable"
    if len(arr) < MIN_FRAMES_PER_FILE:
        return f"only {len(arr)} frames (< {MIN_FRAMES_PER_FILE})"
    return ""


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    groups: np.ndarray                       # one id per file
    sessions: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    session_names: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    labels: List[int] = field(default_factory=list)
    frames: List[np.ndarray] = field(default_factory=list)   # per-file pad deltas
    skipped: List[Tuple[str, str]] = field(default_factory=list)
    # (relative dir, csv count, actionable hint) for every CSV folder NOT loaded
    unknown_folders: List[Tuple[str, int, str]] = field(default_factory=list)
    # A9: how many files came in under each column convention. "sensor" files
    # are trusted as pad order and NOT permuted; "signal" files go through
    # PAD_ORDER. A corpus that mixes the two is mixing two patch orientations.
    conventions: Dict[str, int] = field(default_factory=dict)
    # A5: lowest RAW count seen per class label, captured at load time. The
    # detachment-spec caveat in METRICS.md used to be a typed-in literal
    # ("deepest is 27,251"); it is measured from this instead, so it updates
    # itself the day round-2 data lands.
    min_raw_by_label: Dict[int, float] = field(default_factory=dict)

    @property
    def n_lost_files(self) -> int:
        """CSVs on disk that no class folder claimed. Must be 0 before analysis."""
        return sum(n for _, n, _ in self.unknown_folders)

    @property
    def classes_present(self) -> List[int]:
        return sorted(set(self.labels))

    @property
    def complete(self) -> bool:
        return len(self.classes_present) == N_CLASSES

    @property
    def n_files(self) -> int:
        return len(self.files)

    @property
    def n_sessions(self) -> int:
        return len(self.session_names)


def scan_csv_dirs(root: str) -> Tuple[List[Tuple[str, str, str]], List[Tuple[str, int, str]]]:
    """FIX D3: find every directory under `root` that holds CSVs, and say which
    ones the loader will actually read.

    A recording folder is recognised at exactly two depths:

        <class>/            e.g. Data/Peel/
        S<n>/<class>/       e.g. Data/S1/Peel/

    Anything else holding CSVs is a stray. The previous version globbed
    ``*.csv`` non-recursively over the immediate children of the search roots,
    so it could not see a mis-typed *session* directory - the exact failure the
    session layout introduces. ``Data/Session1/{Peel,N_base}/*.csv`` loaded
    zero files, reported zero unknown folders, and printed no warning; so did
    ``Data/Peel/retake/*.csv``. On a collection day that is a silently lost
    session, discovered days later.

    Returns ``(known, stray)``:
        known = [(relative dir, class folder name, absolute path), ...]
        stray = [(relative dir, csv count, actionable hint), ...]

    The loader reads `known` directly, so the warning and the load can no
    longer disagree about what counts as a recording folder.
    """
    known: List[Tuple[str, str, str]] = []
    stray: List[Tuple[str, int, str]] = []
    if not os.path.isdir(root):
        return known, stray

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        n_csv = sum(1 for f in filenames if f.lower().endswith(".csv"))
        if not n_csv:
            continue
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel == ".":
            stray.append((".", n_csv,
                          "CSVs sitting loose in Data/ - move them into a class folder"))
            continue
        parts = rel.split("/")
        # Custom_Uploads/ holds unlabelled files the dashboard's own upload
        # endpoint wrote. They are for review, not for training, so they are
        # deliberately not loaded - but they must still be ACCOUNTED FOR.
        #
        # An earlier attempt at quieting this simply `continue`d here, which made
        # 50 CSVs disappear from the loader's arithmetic entirely. The D3
        # regression check (`every CSV on disk is loaded, skipped, or reported -
        # none vanish`) caught it immediately, which is the whole point of that
        # invariant: a file the loader neither reads nor mentions is a file nobody
        # notices is missing. So it stays in the reported bucket, with a hint that
        # says it is expected instead of telling the user to rename a directory
        # the application creates itself.
        if parts[0] == "Custom_Uploads":
            stray.append((rel, n_csv,
                          "dashboard uploads - reviewable via /api/v5/dataset, and "
                          "deliberately NOT training data (they carry no class label)"))
            continue
        leaf = parts[-1]
        if len(parts) == 1 and leaf in CLASS_MAPPING:
            known.append((rel, leaf, dirpath))
            continue
        if len(parts) == 2 and SESSION_DIR_RE.match(parts[0]) and leaf in CLASS_MAPPING:
            known.append((rel, leaf, dirpath))
            continue
        stray.append((rel, n_csv, _stray_hint(parts)))

    return known, stray


SOP_CLASS_FOLDERS = ("N_base", "Brief Touch", "Press", "Friction",
                     "Peel", "VPull", "HPull", "PowerP")


def _stray_hint(parts: Sequence[str]) -> str:
    """Turn a rejected path into the one sentence that fixes it.

    Ordered by root cause, not by depth: a CSV buried inside a class folder is
    lost because of the class folder above it, whatever the sub-folder is
    called, so that case is diagnosed before any spell-check on the leaf name.
    """
    parts = list(parts)
    leaf, head = parts[-1], parts[0]
    ancestors = parts[:-1]

    for i, a in enumerate(ancestors):
        if a in CLASS_MAPPING and not (i == 0 and SESSION_DIR_RE.match(a)):
            return (f"'{a}' is a class folder and the loader never reads sub-folders "
                    f"inside one - move these CSVs up into '{'/'.join(parts[:i + 1])}/'")

    if leaf in CLASS_MAPPING:
        if len(parts) == 2:
            return (f"rename '{head}' to 'S1' (or S2/S3) - session folders must match "
                    f"S<number> exactly, so '{head}' is invisible to the loader")
        return ("nested too deep - class folders live at Data/<class> or "
                "Data/S<n>/<class>, nothing below that is read")

    near = difflib.get_close_matches(leaf, list(CLASS_MAPPING), n=1, cutoff=0.6)
    if near:
        return f"'{leaf}' is not a class folder - did you mean '{near[0]}'?"
    return (f"'{leaf}' is not a known class folder - expected one of: "
            f"{', '.join(SOP_CLASS_FOLDERS)}")


def load_dataset(calibration: str = "static", use_gradient: bool = False,
                 verbose: bool = True) -> Optional[Dataset]:
    X_all: List[np.ndarray] = []
    y_all: List[np.ndarray] = []
    g_all: List[np.ndarray] = []
    files: List[str] = []
    labels: List[int] = []
    per_file: List[np.ndarray] = []
    skipped: List[Tuple[str, str]] = []
    idx = 0

    # A session is a distinct sensor mounting. Round 1 was a single session, so
    # leave-one-file-out could not tell whether the model had learned the
    # physics of pulling or the signature of one particular attachment. When
    # recordings live under Data/S1/, Data/S2/, ... each prefix is one session
    # and --cv session holds an entire mounting out of training.
    session_ids: List[np.ndarray] = []
    session_names: List[str] = []

    def _session_of(rel: str) -> int:
        head = rel.split("/")[0]
        name = head if SESSION_DIR_RE.match(head) else "S0"
        if name not in session_names:
            session_names.append(name)
        return session_names.index(name)

    known, unknown = scan_csv_dirs(DATA_ROOT)
    # Root-level folders first, then S1, S2, ...; within each, CLASS_MAPPING
    # order. Group ids and CV folds depend on this order, so it is pinned.
    class_order = list(CLASS_MAPPING)
    known.sort(key=lambda k: (k[0].count("/"),
                              k[0].rsplit("/", 1)[0] if "/" in k[0] else "",
                              class_order.index(k[1])))

    conventions: List[str] = []
    min_raw: Dict[int, float] = {}
    for _rel_dir, folder, folder_path in known:
        meta = CLASS_MAPPING[folder]
        for fpath in sorted(glob.glob(os.path.join(folder_path, "*.csv"))):
            rel = os.path.relpath(fpath, DATA_ROOT).replace("\\", "/")
            raw = read_raw_csv(fpath, convention_out=conventions)
            # A 1-row file calibrates to an all-zero delta, indistinguishable
            # from a perfect baseline; empty and NaN files are rejected upstream.
            if raw is None or len(raw) < MIN_FRAMES_PER_FILE:
                skipped.append((rel, describe_csv_problem(fpath) or "unusable"))
                continue

            lab = int(meta["label"])
            min_raw[lab] = min(min_raw.get(lab, float("inf")), float(raw.min()))

            # NOT filtered. adaptive_jitter_filter() was wired in here on
            # 2026-09-18 and measured worse, so it came back out - see the
            # negative result recorded in its docstring.
            delta = calibrate(raw, calibration)
            feats = extract_features(delta, use_gradient)
            X_all.append(feats)
            y_all.append(np.full(len(feats), meta["label"], dtype=int))
            g_all.append(np.full(len(feats), idx, dtype=int))
            files.append(rel)
            labels.append(int(meta["label"]))
            per_file.append(delta)
            session_ids.append(np.full(len(feats), _session_of(rel), dtype=int))
            idx += 1

    # Any directory holding CSVs that the loop above did not read is almost
    # certainly a typo in a folder name, and silently dropping it costs a whole
    # session. This is loud on purpose - and since `unknown` comes from the same
    # scan that produced `known`, it cannot disagree with what was loaded.

    def _warn_stray() -> None:
        """Report unloaded CSVs, loudly for the ones that look like mistakes.

        Custom_Uploads/ is expected to be here and expected not to load, so it is
        listed as a note. Everything else in this bucket is probably a mis-typed
        folder name, which costs a whole recording session, so it keeps the
        banner. Splitting them stops the alarm firing every single run and
        training people to ignore it.
        """
        expected = [x for x in unknown if x[0].split("/")[0] == "Custom_Uploads"]
        suspect = [x for x in unknown if x not in expected]
        if suspect:
            n_suspect = sum(n for _, n, _ in suspect)
            print(f"  {'!' * 70}")
            print(f"  WARNING: {n_suspect} CSV file(s) in {len(suspect)} folder(s) were NOT loaded")
            for name, n, hint in suspect:
                print(f"    - {name}/  ({n} csv)  ->  {hint}")
            print(f"  {'!' * 70}")
        for name, n, hint in expected:
            print(f"  note: {name}/ ({n} csv) not loaded - {hint}")

    if not X_all:
        if verbose:
            print(f"  no usable recordings under {DATA_ROOT}")
            _warn_stray()
            print(f"  known class folders: {', '.join(sorted(CLASS_MAPPING))}")
        return None

    if verbose:
        if skipped:
            print(f"  skipped {len(skipped)} file(s):")
            for name, why in skipped:
                print(f"    - {name}: {why}")
        _warn_stray()
        present = sorted(set(labels))
        if len(present) < N_CLASSES:
            missing = [CLASS_LABEL_NAMES[c] for c in range(N_CLASSES) if c not in present]
            print(f"  WARNING: only {len(present)}/{N_CLASSES} classes present. "
                  f"Missing: {', '.join(missing)}. Any accuracy reported below is "
                  f"not comparable to a full-class run.")

    conv = {k: conventions.count(k) for k in ("sensor", "signal") if conventions.count(k)}
    if verbose:
        n_sen, n_sig = conv.get("sensor", 0), conv.get("signal", 0)
        print(f"  column convention: {n_sen} Sensor-* (used as-is), "
              f"{n_sig} Signal-* (permuted through PAD_ORDER)")
        if n_sen and n_sig:
            print("  WARNING: the corpus MIXES both conventions. Half the recordings are "
                  "being read in a different pad orientation from the other half - every "
                  "spatial result below pools two patch layouts. Fix the logger first.")
        elif n_sen and not n_sig:
            print("  NOTE: PAD_ORDER is not exercised by any recording; the heatmap and "
                  "peel direction rest on Sensor-N == pad N, which the 1-by-1 press sweep "
                  "confirms for this corpus (python main.py --verify-pads). Accuracy "
                  "figures are unaffected either way - the base features are "
                  "permutation-invariant. The LIVE serial path is still unverified.")

    ds = Dataset(np.vstack(X_all), np.hstack(y_all), np.hstack(g_all),
                 np.hstack(session_ids), session_names,
                 files, labels, per_file, skipped)
    ds.unknown_folders = unknown
    ds.conventions = conv
    ds.min_raw_by_label = min_raw
    return ds


def full_proba(clf: Any, X: np.ndarray) -> np.ndarray:
    """FIX F7: expand predict_proba to a fixed 4-column matrix.

    RandomForest only emits columns for classes it saw during fit. v5.0 indexed
    probs[i][2] and probs[i][3] unconditionally, so any run missing a class
    folder crashed the API with an IndexError.
    """
    out = np.zeros((len(X), N_CLASSES), dtype=float)
    if len(X) == 0:
        return out
    p = clf.predict_proba(X)
    for col, cls in enumerate(clf.classes_):
        c = int(cls)
        if 0 <= c < N_CLASSES:
            out[:, c] = p[:, col]
    return out


def cpri(proba: np.ndarray, delta: Optional[np.ndarray] = None) -> np.ndarray:
    """Composite Patient Risk Index matching clinical escalation:
    - Class 0 (Normal): 0%
    - Class 1 (Touch / Incidental activity): Dynamic 15% - 55% based on pad count & intensity
    - Class 2 (Peel / Partial peeling): Dynamic 60% - 85% based on lifted pads & peel depth
    - Class 3 (Pull / Full tube displacement): Dynamic 85% - 100% based on pull displacement

    When delta is omitted or None (e.g. theoretical probability tests), returns
    the nominal linear projection [0, 35, 70, 100] preserving mathematical invariants.
    """
    p = np.atleast_2d(np.asarray(proba, dtype=float))
    if delta is None:
        risk = p[:, 1] * 35.0 + p[:, 2] * 70.0 + p[:, 3] * 100.0
        return np.clip(risk, 0.0, 100.0)

    d = np.atleast_2d(np.asarray(delta, dtype=float))
    n_frames = min(len(p), len(d))
    out = np.zeros(len(p), dtype=float)

    for i in range(n_frames):
        p_row = p[i]
        d_row = d[i]

        # 1. Positive deltas (touch / press)
        pos_deltas = d_row[d_row >= NOISE_GATE_COUNTS]
        n_pos = len(pos_deltas)
        max_pos = float(pos_deltas.max()) if n_pos > 0 else 0.0

        # 2. Negative deltas (peel / lift)
        lift_deltas = d_row[d_row <= LIFT_GATE_COUNTS]
        n_lift = len(lift_deltas)
        max_lift = float(abs(lift_deltas.min())) if n_lift > 0 else 0.0

        # Dynamic risk components for each class
        # Class 1 (Touch / Press): scales smoothly between 15% and 55%
        pad_factor = min(1.0, n_pos / 10.0)
        int_factor = float(np.clip((max_pos - NOISE_GATE_COUNTS) / 1200.0, 0.0, 1.0))
        r_touch = 15.0 + 20.0 * pad_factor + 20.0 * int_factor

        # Class 2 (Peel): scales smoothly between 60% and 85%
        lift_pad_factor = min(1.0, n_lift / 8.0)
        lift_depth_factor = float(np.clip((max_lift - abs(LIFT_GATE_COUNTS)) / 1500.0, 0.0, 1.0))
        r_peel = 60.0 + 15.0 * lift_pad_factor + 10.0 * lift_depth_factor

        # Class 3 (Pull): scales smoothly between 85% and 100%
        pull_intensity = float(np.clip(np.max(np.abs(d_row)) / 2500.0, 0.0, 1.0))
        r_pull = 85.0 + 15.0 * pull_intensity

        # Weighted composite risk
        risk_val = p_row[1] * r_touch + p_row[2] * r_peel + p_row[3] * r_pull
        out[i] = risk_val

    if len(p) > n_frames:
        out[n_frames:] = (p[n_frames:, 1] * 35.0 +
                          p[n_frames:, 2] * 70.0 +
                          p[n_frames:, 3] * 100.0)

    return np.clip(out, 0.0, 100.0)


def round_proba(proba: Sequence[float], places: int = 4) -> List[float]:
    """Round a probability vector for the wire WITHOUT breaking its sum.

    Per-element `round(p, 4)` is not sum-preserving: on A_Peel_01 it produced
    [0.0, 0.0001, 0.9756, 0.0244] summing to 1.0001, which is what
    `test_live_pipeline_output_contract` was failing on, and which makes any
    consumer that renders the four values as a stacked 100% bar disagree with
    itself. Measured over the whole corpus, 644 frames round to something other
    than 1.0.

    The residual is pushed into the largest element, where it is smallest in
    relative terms and cannot flip an argmax.
    """
    vals = [round(float(p), places) for p in proba]
    if not vals:
        return vals
    residual = round(1.0 - sum(vals), places + 2)
    if residual:
        big = max(range(len(vals)), key=lambda i: vals[i])
        vals[big] = round(vals[big] + residual, places)
    return vals


def classify_deltas(model: Optional[Any], delta: np.ndarray,
                    use_gradient: bool = False) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """THE frame classifier. Both serving paths call this and nothing else.

    Returns ``(proba, raw_level, risk)`` for an (n_frames, 25) delta matrix, or
    for a single frame passed as a 25-vector.

    Why this function exists
    -----------------------
    There were four implementations of "given a delta frame, what level is
    this": LivePipeline.process, this endpoint's inline argmax, a JavaScript
    copy in web/web_serial.js, and a fourth in a stray root-level test file.
    They disagreed - the same Peel recording read Level 3 through the socket and
    Level 2 through REST - and each drifted separately as it was edited. Every
    path disagreement found in the 2026-08-17 review traced back to that.

    There is now one. `LivePipeline` adds streaming state (Kalman baseline,
    debouncer, peel tracker) around it; the REST view adds its own debouncer
    over a whole file; the browser adds nothing at all, it just renders what
    the socket sends. None of them decides a level themselves.
    """
    d = np.atleast_2d(np.asarray(delta, dtype=float))
    proba = np.zeros((len(d), N_CLASSES), dtype=float)
    if len(d) == 0:
        return proba, np.zeros(0, dtype=int), np.zeros(0, dtype=float)

    # Below the physics gate nothing is asked of the classifier: the frame is
    # quieter than the baseline swing the SOP tolerates, so it is Level 0 by
    # construction. With no model loaded every frame takes this branch, which is
    # what keeps an untrained server silent rather than alarming on argmax of a
    # zero vector.
    proba[:, 0] = 1.0
    active = np.max(np.abs(d), axis=1) >= NOISE_GATE_COUNTS
    if model is not None and bool(active.any()):
        proba[active] = full_proba(model, extract_features(d[active], use_gradient))

    # R8b. NOTHING hand-codes a probability below this line, and nothing may be
    # added that does.
    #
    # A revision dated 2026-08-18 inserted a four-branch "Physics-Gated Guard"
    # here that overwrote `proba` with literals - [0,0,0,1] when eight pads were
    # deep, [0.05,0.90,0,0.05] whenever the frame had a positive press and no
    # deep lift, and so on. It was the same hand-tuned cascade that had already
    # been removed from LivePipeline on 2026-08-17, moved one level down into
    # the shared classifier, where it reached every serving path at once.
    #
    # Measured in sample on the round-1 corpus, replaying every recording
    # through LivePipeline with the same fitted model, guard on vs guard off:
    #
    #     pull recordings annunciated       13/30   ->   30/30
    #     peel recordings annunciated       10/10   ->   10/10
    #     normal recordings annunciated      3/41   ->    1/41
    #     normal recordings whose RAW level
    #       reached 2 or 3                  15/41   ->    3/41
    #
    # It was worse on both axes at once. Case C ("positive press, no deep lift
    # -> touch") is what did the damage: Horizontal Pull produces no lift signal
    # on this patch and shows up as a press (see the HPull caveat), so the guard
    # forced 7 of 10 Horizontal Pull and 4 of 5 PowerP/HP recordings down to
    # Level 1 and the siren never sounded.
    #
    # It is also unmeasurable where it matters: compute_oof() and
    # evaluate_stream() call the model directly, so every figure in METRICS.md
    # describes the code WITHOUT this block. A branch that changes the served
    # level but not the published number is a branch whose behaviour nobody can
    # quote. If a physics rule is genuinely needed, it belongs in the feature
    # vector or in a separate operating point that operating_curve() measures.
    #
    # The one physics rule that survives is the noise gate above, because it can
    # only ever suppress a frame quieter than the baseline swing the SOP itself
    # tolerates - it cannot invent an alarm.
    raw_level = proba.argmax(axis=1).astype(int)
    risk = cpri(proba, d)
    risk[~active] = 0.0
    return proba, raw_level, risk


# =============================================================================
# 6. HISTGRADIENTBOOSTING MODEL (36 FEATS) + HONEST EVALUATION
# =============================================================================
def _new_rf(seed: int = 42) -> HistGradientBoostingClassifier:
    """THE production estimator. Named `_new_rf` for call-site compatibility only.

    The shipped model is a HistGradientBoostingClassifier, not a forest, and it
    is fitted on 34 features (25 pad deltas + 9 statistics; 36 with --gradient).
    Docstrings, printed headings and METRICS.md said "Random Forest" and
    "36 features" for a while after the swap - see print_rf_report() for the
    heading fix. Re-measured 2026-08-19, leave-one-file-out over the 81
    recordings, this estimator beats the RandomForest(200, depth 12,
    balanced_subsample) it replaced on every axis that is reported:

        file-level accuracy   96.30% -> 97.53%
        episode sensitivity    95.0% -> 100.0%
        false alarm/recording   9.8% ->   7.3%
        alarms per hour         15.5 ->   13.0   (7.8 at the 7-of-6 default)

    so the swap itself is sound. What was NOT sound was leaving the previous
    model's numbers in the documents beside it.
    """
    return HistGradientBoostingClassifier(
        max_iter=150,
        max_depth=8,
        class_weight="balanced",
        random_state=seed,
    )


def _file_vote(frame_preds: np.ndarray) -> int:
    """Majority vote over a file's frames, ties broken toward the higher class.

    np.argmax returns the lowest index on a tie, which sent two Vertical Pull
    files (votes [2,6,1,6] and [3,4,1,4], both truly class 3) to class 1.
    Breaking the other way is both clinically right - a tie between "incidental
    touch" and "tube being pulled" should not resolve to the benign reading -
    and measurably better: accuracy 92.50% -> 95.00%, class-3 recall
    0.800 -> 0.867, with the false-alarm rate unchanged at 0.0%.
    """
    arr = np.asarray(frame_preds, dtype=int)
    if arr.size == 0:
        return 0                                   # no evidence is not an alarm
    arr = arr[(arr >= 0) & (arr < N_CLASSES)]
    if arr.size == 0:
        return 0
    counts = np.bincount(arr, minlength=N_CLASSES)
    return int(len(counts) - 1 - int(np.argmax(counts[::-1])))


def evaluate_rf(ds: Dataset, seeds: Sequence[int] = (42,), verbose: bool = True,
                cv: str = "file") -> Dict[str, Any]:
    """Leave-One-File-Out CV. Returns file-level metrics and out-of-fold probabilities.

    FIX F6: the out-of-fold frame probabilities collected here are what the ROC
    curves are drawn from. v5.0 called predict_proba on the same matrix the
    model had just been fit on, which makes every AUC approach 1.0 by
    construction.
    """
    if cv == "session":
        if ds.n_sessions < 2:
            raise RuntimeError(
                f"--cv session needs at least 2 sessions; found {ds.n_sessions} "
                f"({ds.session_names}). Put each mounting under Data/S1, Data/S2, ...")
        logo = list(LeaveOneGroupOut().split(ds.X, ds.y, groups=ds.sessions))
    else:
        logo = list(LeaveOneGroupOut().split(ds.X, ds.y, groups=ds.groups))
    runs: List[Dict[str, Any]] = []
    oof_proba = np.zeros((len(ds.X), N_CLASSES), dtype=float)

    for si, seed in enumerate(seeds):
        clf = _new_rf(seed)
        y_true: List[int] = []
        y_pred: List[int] = []
        for tr, te in logo:
            clf.fit(ds.X[tr], ds.y[tr])
            preds = clf.predict(ds.X[te])
            if si == 0:
                oof_proba[te] = full_proba(clf, ds.X[te])
            # Vote per FILE even when the fold holds out a whole session, so the
            # unit of the reported metric is the same in both CV modes.
            for f in np.unique(ds.groups[te]):
                m = ds.groups[te] == f
                y_true.append(int(ds.y[te][m][0]))
                y_pred.append(_file_vote(preds[m]))
        runs.append({
            "seed": seed,
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "macro_f1": float(f1_score(y_true, y_pred, average="macro")),
            "weighted_f1": float(f1_score(y_true, y_pred, average="weighted")),
            "y_true": y_true, "y_pred": y_pred,
        })
        if verbose:
            print(f"  seed {seed:>3}: acc {runs[-1]['accuracy']*100:6.2f}%  "
                  f"macroF1 {runs[-1]['macro_f1']:.4f}")

    accs = np.array([r["accuracy"] for r in runs])
    mf1 = np.array([r["macro_f1"] for r in runs])

    # Pool every seed's file-level predictions. The previous version returned
    # runs[0] here while the headline quoted the mean, so METRICS.md carried a
    # "93.00% +/- 0.61" heading above a confusion matrix worth 92.50% - the
    # exact document/code divergence --report exists to prevent. Pooling makes
    # the two agree by construction: each seed contributes the same file count,
    # so accuracy over the pool equals the mean of the per-seed accuracies.
    y_true_pooled = [v for r in runs for v in r["y_true"]]
    y_pred_pooled = [v for r in runs for v in r["y_pred"]]

    return {
        "cv": cv,
        "runs": runs,
        "oof_proba": oof_proba,
        "n_seeds": len(runs),
        "accuracy_mean": float(accs.mean()), "accuracy_sd": float(accs.std(ddof=1)) if len(accs) > 1 else 0.0,
        "macro_f1_mean": float(mf1.mean()), "macro_f1_sd": float(mf1.std(ddof=1)) if len(mf1) > 1 else 0.0,
        "y_true": y_true_pooled, "y_pred": y_pred_pooled,
        "y_true_first": runs[0]["y_true"], "y_pred_first": runs[0]["y_pred"],
    }


def print_rf_report(ds: Dataset, res: Dict[str, Any]) -> None:
    n = res["n_seeds"]
    print("\n" + "=" * 62)
    print(f"HISTGRADIENTBOOSTING - leave-one-{res.get('cv', 'file')}-out cross validation")
    print("=" * 62)
    print(f"Files              : {ds.n_files}   Frames: {len(ds.X)}")
    if n > 1:
        print(f"File-Level Accuracy: {res['accuracy_mean']*100:.2f}% +/- {res['accuracy_sd']*100:.2f}  (n={n} seeds)")
        print(f"Macro F1           : {res['macro_f1_mean']:.4f} +/- {res['macro_f1_sd']:.4f}")
    else:
        print(f"File-Level Accuracy: {res['accuracy_mean']*100:.2f}%")
        print(f"Macro F1           : {res['macro_f1_mean']:.4f}")
    if n > 1:
        print(f"  (report below pools all {n} seeds: {len(res['y_true'])} file-level predictions)")
    print()
    present = sorted(set(res["y_true"]) | set(res["y_pred"]))
    print(classification_report(res["y_true"], res["y_pred"], labels=present,
                                target_names=[CLASS_LABEL_NAMES[i] for i in present],
                                zero_division=0))


# =============================================================================
# 7. LOOP 2 - TEMPORAL SEQUENCE MODEL (1D-CNN + BiLSTM)
# =============================================================================
WINDOW_FRAMES = 6                      # 6 x 0.56 s = 3.36 s, the spec's ~3 s window
WINDOW_STRIDE = 1


def build_windows(ds: Dataset) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Slice each file's pad-delta matrix into overlapping temporal windows.

    Returns (n_windows, 25, WINDOW_FRAMES), labels, and file-group ids so the
    CV split can keep every window of a file on the same side of the fold.
    """
    xs: List[np.ndarray] = []
    ys: List[int] = []
    gs: List[int] = []
    for fi, delta in enumerate(ds.frames):
        lab = ds.labels[fi]
        if len(delta) < WINDOW_FRAMES:
            pad = np.repeat(delta[:1], WINDOW_FRAMES - len(delta), axis=0)
            delta = np.vstack([pad, delta])
        for s in range(0, len(delta) - WINDOW_FRAMES + 1, WINDOW_STRIDE):
            xs.append(delta[s:s + WINDOW_FRAMES].T)      # (25, T)
            ys.append(lab)
            gs.append(fi)
    return np.stack(xs).astype(np.float32), np.array(ys, dtype=np.int64), np.array(gs, dtype=int)


def _torch():
    try:
        return __import__("torch")
    except ImportError:
        return None


def make_temporal_model(torch_mod: Any) -> Any:
    nn = torch_mod.nn

    class TemporalNet(nn.Module):
        """Conv1d front end extracts local shape, BiLSTM carries it over time."""

        def __init__(self, n_ch: int = N_PADS, hidden: int = 48, n_classes: int = N_CLASSES) -> None:
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv1d(n_ch, 64, kernel_size=3, padding=1), nn.BatchNorm1d(64), nn.ReLU(),
                nn.Conv1d(64, 64, kernel_size=3, padding=1), nn.BatchNorm1d(64), nn.ReLU(),
            )
            self.lstm = nn.LSTM(64, hidden, batch_first=True, bidirectional=True)
            self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(hidden * 2, n_classes))

        def forward(self, x):
            h = self.conv(x)                 # (B, 64, T)
            h = h.transpose(1, 2)            # (B, T, 64)
            out, _ = self.lstm(h)
            return self.head(out.mean(dim=1))

    return TemporalNet


def evaluate_temporal_multi(ds: Dataset, seeds: Sequence[int] = (0, 1, 2),
                            n_splits: int = 5, epochs: int = 40,
                            verbose: bool = True) -> Optional[Dict[str, Any]]:
    """Repeat the grouped CV over several seeds and report mean +/- sd.

    A single seed is not a result. With seed 0 the BiLSTM scored macro F1
    0.9730 against the RF's 0.9328 and that number went into the README; across
    seeds 0-3 the BiLSTM averaged 0.9306 +/- 0.0316 against the RF's
    0.9350 +/- 0.0119, i.e. the RF is marginally *better* and roughly three
    times more stable. The seed had been hard-coded, so nothing could reveal
    that. Always quote the spread.
    """
    runs: List[Dict[str, Any]] = []
    for s in seeds:
        r = evaluate_temporal(ds, n_splits=n_splits, epochs=epochs, seed=s, verbose=False)
        if r is None:
            return None
        runs.append(r)
        if verbose:
            print(f"  seed {s}: BiLSTM macroF1 {r['nn_macro_f1']:.4f}   "
                  f"RF macroF1 {r['rf_macro_f1']:.4f}")
    nn_f1 = np.array([r["nn_macro_f1"] for r in runs])
    rf_f1 = np.array([r["rf_macro_f1"] for r in runs])
    nn_ac = np.array([r["nn_accuracy"] for r in runs])
    rf_ac = np.array([r["rf_accuracy"] for r in runs])
    wins = int((nn_f1 > rf_f1).sum())
    return {
        "seeds": list(seeds), "runs": runs, "n_windows": runs[0]["n_windows"],
        "nn_accuracy_mean": float(nn_ac.mean()), "nn_accuracy_sd": float(nn_ac.std(ddof=1)) if len(nn_ac) > 1 else 0.0,
        "nn_macro_f1_mean": float(nn_f1.mean()), "nn_macro_f1_sd": float(nn_f1.std(ddof=1)) if len(nn_f1) > 1 else 0.0,
        "rf_accuracy_mean": float(rf_ac.mean()), "rf_accuracy_sd": float(rf_ac.std(ddof=1)) if len(rf_ac) > 1 else 0.0,
        "rf_macro_f1_mean": float(rf_f1.mean()), "rf_macro_f1_sd": float(rf_f1.std(ddof=1)) if len(rf_f1) > 1 else 0.0,
        "bilstm_wins": wins, "n_seeds": len(runs),
        "verdict": ("BiLSTM better" if wins == len(runs) else
                    "RF better" if wins == 0 else
                    f"inconclusive - BiLSTM wins {wins}/{len(runs)} seeds"),
    }


def evaluate_temporal(ds: Dataset, n_splits: int = 5, epochs: int = 40,
                      seed: int = 0, verbose: bool = True) -> Optional[Dict[str, Any]]:
    """One grouped-CV run of the BiLSTM, with a Random Forest under the
    identical split so the two numbers are comparable.

    Prefer evaluate_temporal_multi: a single seed of this is not a result."""
    torch = _torch()
    if torch is None:
        print("  [skip] PyTorch not installed - LOOP 2 unavailable (pip install torch)")
        return None

    torch.manual_seed(seed)
    np.random.seed(seed)
    Xw, yw, gw = build_windows(ds)

    # standardise per channel using training folds only (fit inside the loop)
    file_label = np.array(ds.labels)
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    TemporalNet = make_temporal_model(torch)
    file_true: List[int] = []
    file_pred_nn: List[int] = []
    file_pred_rf: List[int] = []
    files_seen: List[int] = []

    for fold, (tr, te) in enumerate(splitter.split(Xw, yw, groups=gw)):
        mu = Xw[tr].mean(axis=(0, 2), keepdims=True)
        sd = Xw[tr].std(axis=(0, 2), keepdims=True) + 1e-6
        Xtr = (Xw[tr] - mu) / sd
        Xte = (Xw[te] - mu) / sd

        model = TemporalNet()
        opt = torch.optim.Adam(model.parameters(), lr=2e-3, weight_decay=1e-4)
        counts = np.bincount(yw[tr], minlength=N_CLASSES).astype(float)
        weights = torch.tensor(np.where(counts > 0, counts.sum() / np.maximum(counts, 1), 0.0),
                               dtype=torch.float32)
        lossf = torch.nn.CrossEntropyLoss(weight=weights)

        xt = torch.tensor(Xtr)
        yt = torch.tensor(yw[tr])
        n = len(xt)
        model.train()
        for _ in range(epochs):
            perm = torch.randperm(n)
            for b in range(0, n, 64):
                idx = perm[b:b + 64]
                opt.zero_grad()
                loss = lossf(model(xt[idx]), yt[idx])
                loss.backward()
                opt.step()

        model.eval()
        with torch.no_grad():
            logits = model(torch.tensor(Xte))
            win_pred = logits.argmax(dim=1).numpy()

        # RF under the same split AND the same seed, so both models' spreads
        # capture the same sources of variation. Pinning the RF to seed 42
        # while re-seeding the network made the RF look ~6x more stable; under
        # a genuinely identical protocol the ratio is ~1.2x.
        rf = _new_rf(seed)
        frame_tr = np.isin(ds.groups, np.unique(gw[tr]))
        frame_te_files = np.unique(gw[te])
        rf.fit(ds.X[frame_tr], ds.y[frame_tr])

        for f in frame_te_files:
            files_seen.append(int(f))
            file_true.append(int(file_label[f]))
            file_pred_nn.append(_file_vote(win_pred[gw[te] == f]))
            m = ds.groups == f
            file_pred_rf.append(_file_vote(rf.predict(ds.X[m])))

        if verbose:
            print(f"  fold {fold + 1}/{n_splits}: {len(frame_te_files)} test files")

    return {
        "files": files_seen, "y_true": file_true,
        "y_pred_nn": file_pred_nn, "y_pred_rf": file_pred_rf,
        "nn_accuracy": float(accuracy_score(file_true, file_pred_nn)),
        "nn_macro_f1": float(f1_score(file_true, file_pred_nn, average="macro")),
        "rf_accuracy": float(accuracy_score(file_true, file_pred_rf)),
        "rf_macro_f1": float(f1_score(file_true, file_pred_rf, average="macro")),
        "n_windows": int(len(Xw)),
    }


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval - correct for the small n and 0%/100% rates here."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (float(max(0.0, (c - h) / d)), float(min(1.0, (c + h) / d)))


def bootstrap_ci(y_true: Sequence[int], y_pred: Sequence[int], n_boot: int = 4000,
                 seed: int = 0) -> Dict[str, Tuple[float, float]]:
    """Resample FILES, not frames - the file is the independent unit."""
    t = np.asarray(y_true)
    p = np.asarray(y_pred)
    rng = np.random.default_rng(seed)
    accs, f1s = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, len(t), len(t))
        accs.append(float((t[idx] == p[idx]).mean()))
        f1s.append(float(f1_score(t[idx], p[idx], average="macro", zero_division=0)))
    return {"accuracy": (float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))),
            "macro_f1": (float(np.percentile(f1s, 2.5)), float(np.percentile(f1s, 97.5)))}


# =============================================================================
# 6b. EPISODE-LEVEL EVALUATION  (the unit the device actually decides on)
# =============================================================================
def compute_oof(ds: Dataset, seed: int = 42) -> np.ndarray:
    """Leave-one-file-out frame predictions.

    Split out so callers can share one pass: --report ran a full LOFO for the
    stream evaluation and another for every RF seed - six ~30 s passes per report.
    """
    clf = _new_rf(seed)
    oof = np.zeros(len(ds.X), dtype=int)
    for tr, te in LeaveOneGroupOut().split(ds.X, ds.y, groups=ds.groups):
        clf.fit(ds.X[tr], ds.y[tr])
        oof[te] = clf.predict(ds.X[te])
    return oof


def _count_onsets(levels: np.ndarray) -> int:
    """Number of times the annunciator rises into alarm (level >= 2).

    Single definition shared by evaluate_stream and operating_curve so the
    headline alarms/hour and the operating-curve row for the same operating
    point can never be computed two different ways (A7).
    """
    arr = np.asarray(levels)
    if arr.size == 0:
        return 0
    return int(((arr[1:] >= 2) & (arr[:-1] < 2)).sum())


def evaluate_stream(ds: Dataset, seed: int = 42, verbose: bool = True,
                    oof: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Replay every recording through the live annunciator, out of fold.

    Why this exists
    ---------------
    Two problems with the file-level majority vote that was the headline metric:

    1. **It is an artifact of clip length.** Round-1 pull recordings are 6-21 s
       and roughly half event, so a majority of frames are event frames. The
       round-2 SOP in this repo prescribes 60-120 s recordings with three pull
       cycles - a duty cycle near 7%. Re-voting the same model on the same
       events padded to SOP length takes pull recall from 0.567 to **0.000**,
       while any-frame detection stays at 1.000. The metric would have
       collapsed the day the new data was recorded, and the detector would have
       been blamed.
    2. **It was measured in sample.** Every streaming test fit the forest on the
       whole corpus and then replayed files from it. In-sample: 0 of 40 normal
       recordings annunciate. Out of fold: 5 of 40, including bare N_base
       recordings reaching Level 3.

    An episode metric - did the alarm fire at all during this recording, and how
    often does it fire on normal activity per hour - is invariant to clip
    length, is what a ward actually experiences, and is what this function
    reports. The file vote is kept alongside it for comparability only.
    """
    if oof is None:
        oof = compute_oof(ds, seed)

    per_file: List[Dict[str, Any]] = []
    for fi, label in enumerate(ds.labels):
        mask = ds.groups == fi
        preds = oof[mask]
        deb = AlarmDebouncer()
        levels: List[int] = []
        for k, p in enumerate(preds):
            levels.append(0 if k < KALMAN_WARMUP else deb.update(int(p)))
        arr = np.array(levels)
        # A7: this used to add 1 when arr[0] >= 2, which operating_curve never
        # did - so the headline alarms/hour and its own curve row were computed
        # by two different rules. Unreachable today (the warmup pins frame 0 to
        # level 0) but it is exactly the kind of latent split that shows up as
        # an unexplainable mismatch once the warmup constant changes. One
        # definition now, shared with operating_curve via _count_onsets.
        onsets = _count_onsets(arr)
        hits = np.nonzero(arr >= 2)[0]
        per_file.append({
            "file": ds.files[fi], "label": label,
            "max_level": int(arr.max(initial=0)),
            "annunciated": bool(arr.max(initial=0) >= 2),
            "onsets": onsets,
            "latency_s": float(hits[0] * SAMPLE_PERIOD_S) if hits.size else None,
            "frames": int(mask.sum()),
            "file_vote": _file_vote(preds),
        })

    normal = [r for r in per_file if r["label"] <= 1]
    anomaly = [r for r in per_file if r["label"] >= 2]
    fa_files = [r for r in normal if r["annunciated"]]
    missed = [r for r in anomaly if not r["annunciated"]]
    normal_hours = sum(r["frames"] for r in normal) * SAMPLE_PERIOD_S / 3600.0
    lat = [r["latency_s"] for r in anomaly if r["latency_s"] is not None]

    out = {
        "seed": seed, "per_file": per_file,
        "n_normal": len(normal), "n_anomaly": len(anomaly),
        "sensitivity": (len(anomaly) - len(missed)) / max(len(anomaly), 1),
        "sensitivity_ci": wilson(len(anomaly) - len(missed), len(anomaly)),
        "false_alarm_files": len(fa_files),
        "false_alarm_rate": len(fa_files) / max(len(normal), 1),
        "false_alarm_ci": wilson(len(fa_files), len(normal)),
        "alarms_per_hour": (sum(r["onsets"] for r in normal) / normal_hours
                            if normal_hours > 0 else 0.0),
        "normal_hours": normal_hours,
        "median_latency_s": float(np.median(lat)) if lat else None,
        "max_latency_s": float(np.max(lat)) if lat else None,
        "missed": [r["file"] for r in missed],
        "false_alarm_list": [(r["file"], r["max_level"]) for r in fa_files],
        "onsets_per_anomaly": (sum(r["onsets"] for r in anomaly) /
                               max(len(anomaly) - len(missed), 1)),
        "operating_point": {"window": ALARM.window, "votes": ALARM.min_votes,
                            "hold": ALARM.hold},
        "curve": operating_curve(ds, oof),
    }
    if verbose:
        print_stream_report(out)
    return out


def operating_curve(ds: Dataset, oof: np.ndarray,
                    points: Sequence[Tuple[int, int, int]] = (
                        (5, 3, 9), (3, 3, 0), (5, 4, 9), (7, 5, 9), (7, 6, 9), (5, 5, 9))
                    ) -> List[Dict[str, Any]]:
    """Sensitivity vs alarm burden across annunciator settings.

    Publishing this instead of a single point is the difference between a
    tuned number and a stated design decision. Every row is out of fold.
    """
    rows: List[Dict[str, Any]] = []
    for win, k, hold in points:
        det = fa = n_a = n_n = onsets = frames_n = 0
        lat: List[float] = []
        for fi, label in enumerate(ds.labels):
            preds = oof[ds.groups == fi]
            deb = AlarmDebouncer(win, k, hold)
            lv = [0 if j < KALMAN_WARMUP else deb.update(int(x)) for j, x in enumerate(preds)]
            arr = np.array(lv)
            hit = bool(arr.max(initial=0) >= 2)
            if label >= 2:
                n_a += 1
                det += hit
                h = np.nonzero(arr >= 2)[0]
                if h.size:
                    lat.append(float(h[0] * SAMPLE_PERIOD_S))
            else:
                n_n += 1
                fa += hit
                onsets += _count_onsets(arr)
                frames_n += len(arr)
        hours = frames_n * SAMPLE_PERIOD_S / 3600.0
        rows.append({
            "window": win, "votes": k, "hold": hold,
            "sensitivity": det / max(n_a, 1),
            "false_alarm_rate": fa / max(n_n, 1),
            "alarms_per_hour": onsets / hours if hours else 0.0,
            "median_latency_s": float(np.median(lat)) if lat else None,
            "is_default": (win, k, hold) == (ALARM.window, ALARM.min_votes, ALARM.hold),
        })
    return rows


def print_stream_report(st: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("EPISODE-LEVEL PERFORMANCE (out-of-fold, through the live annunciator)")
    print("=" * 70)
    lo, hi = st["sensitivity_ci"]
    print(f"  Sensitivity (episode detected) : {st['sensitivity']*100:5.1f}%  "
          f"95% CI [{lo*100:.1f}, {hi*100:.1f}]   n={st['n_anomaly']}")
    lo, hi = st["false_alarm_ci"]
    print(f"  False-alarm rate (per recording): {st['false_alarm_rate']*100:5.1f}%  "
          f"95% CI [{lo*100:.1f}, {hi*100:.1f}]   n={st['n_normal']}")
    print(f"  False alarms per hour          : {st['alarms_per_hour']:5.1f}  "
          f"over {st['normal_hours']*60:.0f} min of normal activity")
    if st["median_latency_s"] is not None:
        print(f"  Time to alarm                  : median {st['median_latency_s']:.2f} s, "
              f"worst {st['max_latency_s']:.2f} s")
    print(f"  Alarm onsets per detected event: {st['onsets_per_anomaly']:.2f}  (1.00 = no re-arming)")
    if st["missed"]:
        print(f"  MISSED ({len(st['missed'])}): {st['missed']}")
    if st["false_alarm_list"]:
        print(f"  FALSE ALARMS: {st['false_alarm_list']}")
    if st.get("curve"):
        print("\n  Operating curve (out-of-fold):")
        print(f"    {'win':>4}{'k':>3}{'hold':>5}{'sens':>9}{'FA/rec':>9}{'alarms/h':>10}{'latency':>10}")
        for r in st["curve"]:
            # A6: `if r[...]` treated a latency of exactly 0.00 s - an alarm on
            # the first frame after warmup, the best possible result - as "not
            # measured". Test the sentinel, not the truthiness.
            lat = f"{r['median_latency_s']:.2f}s" if r["median_latency_s"] is not None else "-"
            print(f"    {r['window']:>4}{r['votes']:>3}{r['hold']:>5}{r['sensitivity']*100:>8.1f}%"
                  f"{r['false_alarm_rate']*100:>8.1f}%{r['alarms_per_hour']:>10.1f}{lat:>10}"
                  + ("  <- default" if r["is_default"] else ""))


def print_temporal_report(tr: Dict[str, Any]) -> None:
    n = tr["n_seeds"]
    print("\n" + "=" * 70)
    print(f"RF (single frame)  vs  1D-CNN+BiLSTM ({WINDOW_FRAMES*SAMPLE_PERIOD_S:.2f} s window)")
    print(f"grouped 5-fold, {n} seed(s), {tr['n_windows']} windows")
    print("=" * 70)
    print(f"  {'model':<10}{'accuracy':>22}{'macro F1':>22}")
    print(f"  {'RF':<10}{tr['rf_accuracy_mean']*100:>15.2f}% +/-{tr['rf_accuracy_sd']*100:>5.2f}"
          f"{tr['rf_macro_f1_mean']:>16.4f} +/-{tr['rf_macro_f1_sd']:>5.4f}")
    print(f"  {'BiLSTM':<10}{tr['nn_accuracy_mean']*100:>15.2f}% +/-{tr['nn_accuracy_sd']*100:>5.2f}"
          f"{tr['nn_macro_f1_mean']:>16.4f} +/-{tr['nn_macro_f1_sd']:>5.4f}")
    print(f"\n  BiLSTM wins {tr['bilstm_wins']}/{n} seeds  ->  {tr['verdict']}")
    if n < 3:
        print("  NOTE: fewer than 3 seeds. Do not quote this comparison.")


def false_alarm_rate(y_true: Sequence[int], y_pred: Sequence[int]) -> float:
    """Fraction of normal files (class 0/1) escalated to a warning or alarm."""
    t = np.asarray(y_true)
    p = np.asarray(y_pred)
    normal = t <= 1
    if normal.sum() == 0:
        return 0.0
    return float((p[normal] >= 2).sum() / normal.sum())


# =============================================================================
# 8. LOOP 5 - MULTI-MODAL FUSION (CAPACITANCE + IMU)
# =============================================================================
@dataclass
class IMUFrame:
    ax: float = 0.0
    ay: float = 0.0
    az: float = 0.0
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0

    @property
    def motion_energy(self) -> float:
        """High-pass proxy: gravity-free acceleration magnitude + rotation rate."""
        lin = float(np.hypot(np.hypot(self.ax, self.ay), self.az) - 1.0)
        rot = float(np.hypot(np.hypot(self.gx, self.gy), self.gz))
        return abs(lin) + rot / 180.0


def synthesise_imu(pad_delta: np.ndarray, seed: int = 0) -> List[IMUFrame]:
    """Derive a stand-in IMU stream from the capacitance record.

    The dataset carries no IMU channel, so real fusion cannot be validated on
    it. This produces a physically-plausible surrogate - frame-to-frame
    capacitance change is treated as evidence of tube motion - purely so the
    fusion path can be exercised end to end. Every number it returns is
    synthetic and must not appear in a results table.
    """
    rng = np.random.default_rng(seed)
    d = np.asarray(pad_delta, dtype=float)
    rate = np.vstack([np.zeros((1, d.shape[1])), np.diff(d, axis=0)])
    drive = np.abs(rate).mean(axis=1) / 400.0
    out: List[IMUFrame] = []
    for mag in drive:
        noise = rng.normal(0.0, 0.01, 6)
        out.append(IMUFrame(
            ax=float(mag * 0.6 + noise[0]), ay=float(mag * 0.3 + noise[1]),
            az=float(1.0 + mag * 0.2 + noise[2]),
            gx=float(mag * 25.0 + noise[3]), gy=float(mag * 12.0 + noise[4]),
            gz=float(mag * 6.0 + noise[5]),
        ))
    return out


class FusionEngine:
    """Combine capacitive risk with IMU motion into a single lead indicator.

    Rationale: a pull event couples tube tension (capacitance drop) with bulk
    motion. Motion alone is a patient turning over; a drop alone may be sweat
    or slow adhesive creep. Requiring both raises the alarm earlier than either
    channel crossing its own threshold.
    """

    def __init__(self, motion_gain: float = 35.0, window: int = 4) -> None:
        self.motion_gain = motion_gain
        self.window = window
        self._recent: List[float] = []

    def step(self, capacitive_risk: float, imu: Optional[IMUFrame]) -> Dict[str, float]:
        motion = imu.motion_energy if imu is not None else 0.0
        self._recent.append(motion)
        if len(self._recent) > self.window:
            self._recent.pop(0)
        sustained = float(np.mean(self._recent))
        coupling = float(np.clip(sustained * self.motion_gain, 0.0, 1.0))
        fused = float(np.clip(capacitive_risk + coupling * (100.0 - capacitive_risk) * 0.35, 0.0, 100.0))
        return {"motion_energy": motion, "sustained_motion": sustained,
                "coupling": coupling, "fused_risk": fused}

    def run(self, capacitive_risk: Sequence[float], imu: Sequence[IMUFrame]) -> np.ndarray:
        self._recent = []
        return np.array([self.step(float(r), imu[i] if i < len(imu) else None)["fused_risk"]
                         for i, r in enumerate(capacitive_risk)])


def lead_time_gain(risk_a: Sequence[float], risk_b: Sequence[float], threshold: float = 50.0,
                   period_s: float = SAMPLE_PERIOD_S) -> Optional[float]:
    """Seconds by which series b crosses `threshold` earlier than series a."""
    def first_cross(r: Sequence[float]) -> Optional[int]:
        arr = np.asarray(r, dtype=float)
        hits = np.nonzero(arr >= threshold)[0]
        return int(hits[0]) if len(hits) else None

    a, b = first_cross(risk_a), first_cross(risk_b)
    if a is None or b is None:
        return None
    return round((a - b) * period_s, 3)


# =============================================================================
# 9. LOOP 1 - LIVE SOURCES: USB SERIAL AND CSV REPLAY
# =============================================================================
class FrameSource:
    """Common interface for anything that yields 25-channel frames."""

    name = "base"

    def frames(self) -> Iterator[np.ndarray]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialFrameSource(FrameSource):
    """Read comma/whitespace separated 25-value lines from a USB COM port.

    The firmware emits Signal-1..25 in electrical order; frames are converted
    to physical pad order here so everything downstream shares one convention.
    """

    name = "serial"

    # A10. pyserial returns b"" from readline() on a read timeout, and the loop
    # below used to `continue` on it forever - no backoff, no disconnect
    # detection, no way for the caller to learn the sensor had gone away.
    # Two consequences, both bad on demo day:
    #   * a port that returns immediately (an unplugged USB device on Windows,
    #     or any port opened with timeout=0) span at ~7M reads/second, pinning
    #     the asyncio executor thread the WebSocket runs the generator on;
    #   * a knocked-loose cable froze the dashboard on its last frame with no
    #     error, forever, because the generator never ended.
    # Empty reads are now counted against a wall-clock budget and the stream
    # ends cleanly, which the WebSocket already reports as {"event":"finished"}.
    IDLE_TIMEOUT_S = 1.2         # F4: clean transition to disconnected within 1.5s
    EMPTY_READ_SLEEP_S = 0.02    # floor on the poll rate if reads return at once

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.2, permute: bool = True) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial streaming: pip install pyserial") from exc
        self._serial_mod = serial
        self.port = port
        self.baudrate = baudrate
        self.permute = permute
        self._stop = threading.Event()
        
        last_exc = None
        for attempt in range(4):
            try:
                self._ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    time.sleep(0.35)
        if last_exc is not None:
            raise last_exc

    def frames(self) -> Iterator[np.ndarray]:
        buf = self._ser
        last_frame_at = time.monotonic()
        consecutive_errors = 0
        while not self._stop.is_set():
            try:
                line = buf.readline().decode("utf-8", errors="replace").strip()
                consecutive_errors = 0
            except Exception as exc:
                if self._stop.is_set():
                    break
                consecutive_errors += 1
                if consecutive_errors > 10:
                    logger_serial.warning(f"Serial port {self.port} encountered repeated read errors: {exc}")
                    break
                time.sleep(0.05)
                continue
            if not line:
                if time.monotonic() - last_frame_at > self.IDLE_TIMEOUT_S:
                    break                       # A10: device silent - end the stream
                time.sleep(self.EMPTY_READ_SLEEP_S)
                continue
            parts = [p for p in line.replace(",", " ").split() if p]
            if len(parts) < N_PADS:
                continue
            try:
                vals = np.array([float(p) for p in parts[:N_PADS]], dtype=float)
            except ValueError:
                continue
            if not np.isfinite(vals).all():
                continue
            last_frame_at = time.monotonic()
            yield signals_to_pads(vals) if getattr(self, "permute", True) else vals

    def close(self) -> None:
        self._stop.set()
        try:
            self._ser.close()
        except Exception:
            pass


class ReplayFrameSource(FrameSource):
    """Replay a recorded CSV at true acquisition speed.

    This is how the live path is exercised without hardware: the WebSocket,
    the calibrator, the classifier and the siren all run on real recorded
    signals rather than on a synthetic pattern.
    """

    name = "replay"

    permute = False      # recorded Sensor-* frames are already in pad order

    def __init__(self, rel_path: str, realtime: bool = True, loop: bool = False) -> None:
        full = safe_data_path(rel_path)
        raw = read_raw_csv(full)
        if raw is None:
            raise RuntimeError(f"{rel_path}: missing 25 sensor columns")
        self.raw = raw
        self.rel_path = rel_path
        self.realtime = realtime
        self.loop = loop
        self._stop = threading.Event()

    def frames(self) -> Iterator[np.ndarray]:
        while not self._stop.is_set():
            for row in self.raw:
                if self._stop.is_set():
                    return
                yield row
                if self.realtime:
                    time.sleep(SAMPLE_PERIOD_S)
            if not self.loop:
                return

    def close(self) -> None:
        """Stop the generator. This class inherited the base no-op close().

        The WebSocket handler runs next(gen) on a private worker and, on
        disconnect, calls src.close() then pool.shutdown(wait=False) - which
        does not interrupt a worker already inside the generator. With
        ?source=replay&loop=1&realtime=0 that generator never returns and never
        sleeps, so one dropped connection left a thread spinning a CSV at full
        speed for the lifetime of the process, and every further connection
        added another. Cheap to reach from outside on a public deploy.
        """
        self._stop.set()


class SimulatorFrameSource(FrameSource):
    """Continuous quiescent baseline, for the standby view.

    The base level used to be 45,200 counts, described in this docstring as
    "realistic". The measured corpus spans 27,251 - 32,024 counts and rests
    around 28,000 (BASELINE_COUNTS), so the standby screen was showing pad
    values roughly 17,000 counts above anything this hardware has ever produced,
    and two tests were written against 45,000/46,000 as if those were normal
    readings. Deltas are relative so nothing misclassified, but the raw numbers
    on the face were wrong, which is the sort of thing an operator calibrates
    their intuition on. It now sits at BASELINE_COUNTS.
    """
    def __init__(self, sample_period_s: float = SAMPLE_PERIOD_S) -> None:
        self.period = sample_period_s
        self._running = True

    @property
    def name(self) -> str:
        return "Live-Hardware (Standby)"

    def frames(self) -> Iterator[np.ndarray]:
        base = np.array([BASELINE_COUNTS] * N_PADS, dtype=float)
        while self._running:
            noise = np.random.normal(0.0, 0.6, N_PADS)
            yield base + noise
            time.sleep(self.period)

    def close(self) -> None:
        self._running = False


def list_serial_ports() -> List[Dict[str, str]]:
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        return []
    return [{"device": p.device, "description": p.description or "",
             "hwid": p.hwid or ""} for p in list_ports.comports()]


class LivePipeline:
    """Calibrate -> classify -> summarise, one frame at a time.

    Uses the Kalman baseline (LOOP 4) rather than a frozen 5-frame offset, so a
    session that drifts with sweat over an hour stays correctly zeroed.
    """

    # Consecutive lost frames after which a returning signal is treated as a new
    # attachment and the baseline is re-taken. One dropped frame is a glitch;
    # KALMAN_WARMUP frames (2.8 s) of nothing is the sensor having gone away.
    RESEED_AFTER_LOST_FRAMES = KALMAN_WARMUP

    def __init__(self, model: Optional[Any], use_gradient: bool = False,
                 fuse_imu: bool = False, warmup_frames: int = KALMAN_WARMUP,
                 cdc_mode: bool = False) -> None:
        self.model = model
        self.use_gradient = use_gradient
        self.kalman = KalmanBaseline()
        self.peel = PeelTracker()
        self.alarm = AlarmDebouncer()
        self.fusion = FusionEngine() if fuse_imu else None
        # The Kalman state is seeded from the first frame, so the first few
        # deltas are identically zero - a feature vector the classifier never
        # sees during training. Left unguarded that produced a spurious
        # Level 3 (siren) on frame 0 of every stream. Hold the output at
        # Level 0 until the baseline has settled.
        self.warmup_frames = max(1, warmup_frames)
        self.cdc_mode = cdc_mode
        self.index = 0
        self._seeded = False
        self.seed_plausibility: Dict[str, Any] = {
            "status": "unseeded", "seed_median": None,
            "band": list(ATTACHED_SEED_BAND), "note": "no frame yet"}
        self._disconnected_flag = False
        self._disconnected_run = 0
        self._prev: Optional[np.ndarray] = None
        self._cdc_initial_baseline: Optional[np.ndarray] = None
        # F11/F12: Real-time surface topography and adaptive lift gates
        self.topography: Optional[Dict[str, Any]] = None
        self.adaptive_lift_gates: Optional[np.ndarray] = None
        # Quiescent negative-step recovery and jitter suppression state.
        self._quiescent_frames = max(2, int(math.ceil(
            QUIESCENT_RECOVERY_SECONDS / SAMPLE_PERIOD_S)))
        self._raw_history: collections.deque = collections.deque(
            maxlen=self._quiescent_frames)
        self._delta_history: collections.deque = collections.deque(maxlen=JITTER_TAPS)
        self._jitter_window: collections.deque = collections.deque(
            maxlen=JITTER_WINDOW_FRAMES)
        self.quiescent_recovery: Dict[str, Any] = {
            "active_pads": [], "note": "not engaged"}
        self._quiescent_latched = np.zeros(N_PADS, dtype=bool)
        self.jitter_active = False
        self.jitter_noise_counts = 0.0

    @property
    def warming_up(self) -> bool:
        return self.index < self.warmup_frames

    def reseed(self) -> None:
        self.kalman = KalmanBaseline()
        self.peel = PeelTracker()
        self.alarm = AlarmDebouncer()
        self._seeded = False
        self.index = 0
        self._prev = None
        self._disconnected_flag = False
        self._disconnected_run = 0
        self._cdc_initial_baseline = None
        self.topography = None
        self.adaptive_lift_gates = None
        self._raw_history.clear()
        self._delta_history.clear()
        self._jitter_window.clear()
        self.quiescent_recovery = {"active_pads": [], "note": "not engaged"}
        self._quiescent_latched = np.zeros(N_PADS, dtype=bool)
        self.jitter_active = False
        self.jitter_noise_counts = 0.0

    # ----- quiescent negative-step recovery ---------------------------------
    def _release_quiescent(self) -> None:
        """Put the per-channel gates back and report the recovery as idle."""
        k = self.kalman
        if k.gate_vec is not None:
            k.gate_vec = np.full(len(k.gate_vec), k.gate, dtype=float)
        self._quiescent_latched = np.zeros(N_PADS, dtype=bool)
        if self.quiescent_recovery["active_pads"]:
            self.quiescent_recovery = {"active_pads": [], "note": "not engaged"}

    def _apply_quiescent_recovery(self, delta: np.ndarray) -> None:
        """Let the baseline re-converge on a channel that is deep but motionless.

        A channel below the lift gate is either a patient event or a bad zero.
        The two are separable by motion: a detachment keeps moving and drags its
        neighbours with it, while a finger that has already been lifted off
        leaves a channel that is deeply negative and then perfectly still.

        Three conditions, all required:
          * the channel is below LIFT_GATE_COUNTS;
          * FEWER than PEEL_MIN_PADS channels are below it at all, so nothing
            that looks like a peel front can ever qualify;
          * that channel's raw counts have a standard deviation under
            QUIESCENT_RECOVERY_SD over the last QUIESCENT_RECOVERY_SECONDS.

        Residual risk, stated rather than hidden: a single pad that genuinely
        detaches and then lies perfectly still for three seconds while no other
        pad is lifting would also be recovered. That is one channel out of 25
        with no spatial corroboration - which is below PEEL_MIN_PADS and would
        not have raised a peel alarm either way.
        """
        k = self.kalman
        if (k.b is None or k.p is None or k.r_vec is None or k.gate_vec is None
                or self.warming_up or len(self._raw_history) < self._quiescent_frames):
            self._release_quiescent()
            return

        d = np.asarray(delta, dtype=float)
        lifting = d < LIFT_GATE_COUNTS
        n_lifting = int(lifting.sum())
        if n_lifting >= PEEL_MIN_PADS:
            # A peel front, latched or not. Recovery stays out of it.
            self._release_quiescent()
            return

        # Hysteresis, and it is not cosmetic. Engaging below the lift gate and
        # releasing at the same threshold left the channel parked just under it:
        # measured -797 recovering to -282, which clears the gate but leaves a
        # standing offset that the ordinary 60-count innovation gate can never
        # close. Engage at the lift gate, release at the noise gate.
        holding = self._quiescent_latched & (d < -NOISE_GATE_COUNTS)
        below = lifting | holding
        if not below.any():
            self._release_quiescent()
            return

        sd = np.asarray(self._raw_history, dtype=float).std(axis=0)
        quiet = below & (sd < QUIESCENT_RECOVERY_SD)
        self._quiescent_latched = quiet
        if not quiet.any():
            self._release_quiescent()
            return

        # Inflating P alone cannot move anything. step() sets the Kalman gain to
        # zero whenever |innovation| >= gate, and the innovation here is several
        # hundred counts against a 60-count gate - so the gate, not the
        # covariance, is what is holding the bad zero in place. Both are opened,
        # for these channels only, and only while they stay still: P grows by a
        # bounded factor per frame so the baseline walks toward the resting skin
        # over a couple of seconds instead of snapping to it.
        k.p = np.where(quiet, np.minimum(k.p * QUIESCENT_P_GROWTH,
                                         QUIESCENT_P_CAP * k.r_vec), k.p)
        base_gate = np.full(len(k.gate_vec), k.gate, dtype=float)
        k.gate_vec = np.where(quiet, np.abs(delta) + 1.0, base_gate)
        pads = [int(i) + 1 for i in np.nonzero(quiet)[0]]
        self.quiescent_recovery = {
            "active_pads": pads,
            "note": (f"Pad {', '.join(str(p) for p in pads)} sits below the lift gate but "
                     f"has not moved for {QUIESCENT_RECOVERY_SECONDS:.0f} s and no other "
                     f"pad is lifting - treating it as a released touch, not a detachment, "
                     f"and re-converging its baseline")}

    def process(self, pad_frame: np.ndarray, imu: Optional[IMUFrame] = None) -> Dict[str, Any]:
        pad_frame = np.asarray(pad_frame, dtype=float)
        # F2: Reject non-finite values, signed 16-bit underflow (<0 counts), or all zeros
        if not np.isfinite(pad_frame).all() or np.any(pad_frame < 0.0) or np.all(pad_frame <= 0.0):
            disconnected = True
            is_cdc = self.cdc_mode
            working_frame = pad_frame
        else:
            # Unit detection: CDC absolute mode (values in pF < 500) vs raw PSoC counts (> 3000)
            is_cdc = self.cdc_mode or (np.all(pad_frame < 500.0) and np.any(pad_frame > 0.05))
            if is_cdc:
                # CDC disconnected: open circuit (< 1 pF), short/rail saturation (> 500 pF), or all zeros
                disconnected = np.all(pad_frame < 1.0) or np.all(pad_frame > 500.0) or np.all(pad_frame == 0.0)
                if not disconnected:
                    if self._cdc_initial_baseline is None:
                        self._cdc_initial_baseline = pad_frame.copy()
                    working_frame = convert_absolute_cdc_to_counts(pad_frame, baseline_c_pf=self._cdc_initial_baseline) + BASELINE_COUNTS
                    # Filter any extreme surges (>50,000 counts) in converted counts
                    surge_mask = working_frame > 50000.0
                    if np.any(surge_mask):
                        repl = self.kalman.b[surge_mask] if self.kalman.b is not None else BASELINE_COUNTS
                        working_frame[surge_mask] = repl
                else:
                    working_frame = pad_frame
            else:
                # Raw counts mode: reject full disconnect (<3000) or all-pad saturation (>50000)
                disconnected = np.all(pad_frame < 3000.0) or np.all(pad_frame > 50000.0) or np.all(pad_frame == 0.0)
                if not disconnected:
                    working_frame = pad_frame.copy()
                    # F2: Filter extreme electrical surges (>50,000 counts) so noise spikes do not trigger false alarms
                    surge_mask = working_frame > 50000.0
                    if np.any(surge_mask):
                        repl = self.kalman.b[surge_mask] if self.kalman.b is not None else BASELINE_COUNTS
                        working_frame[surge_mask] = repl
                else:
                    working_frame = pad_frame

        if disconnected:
            # The frame index is read BEFORE the increment, exactly as the
            # normal path below does it. Incrementing first made a dropout at
            # frame 5 report index 6, and the next good frame report 6 as well
            # - duplicate indices in the stream and in the audit trail.
            idx = self.index
            self.index += 1
            # A dropout is not evidence that the patient is fine, so the alarm
            # state is neither cleared nor advanced: the debouncer keeps its
            # history and its hold, and whatever level it was holding is what
            # this frame reports. A cable knocked loose mid-pull must not read
            # as Level 0.
            held = self.alarm.level
            self._disconnected_flag = True
            self._disconnected_run = getattr(self, "_disconnected_run", 0) + 1
            return {
                "index": idx,
                "time_sec": round(idx * SAMPLE_PERIOD_S, 3),
                "pad_values": [0.0] * N_PADS,
                "deltas": [0.0] * N_PADS,
                "normalized_deltas": [0.0] * N_PADS,
                "baseline": [round(v, 1) for v in (self.kalman.b if self.kalman.b is not None else [0.0]*N_PADS)],
                "severity_level": held,
                "raw_level": 0,
                "status": "Sensor disconnected - no signal (เซนเซอร์หลุด)",
                "warming_up": False,
                "probabilities": round_proba([1.0, 0.0, 0.0, 0.0]),
                "cpri_percent": 0.0,
                "propagation": {"confirmed": False, "active": False,
                                "n_lifting_pads": 0, "description": "sensor disconnected"},
                "disconnected": True,
                "mode": "cdc" if is_cdc else "raw_counts",
            }

        # Re-seed on first frame, or after a REAL disconnect.
        reconnected = (getattr(self, "_disconnected_run", 0) >= self.RESEED_AFTER_LOST_FRAMES)
        if not self._seeded or reconnected:
            self.kalman.seed(working_frame[None, :])
            self._seeded = True
            # Item 2: a relative board zeroes on whatever it sees first. Say
            # where that was, so a bad zero is visible instead of silent. In
            # CDC mode the seed is already absolute pF, so the counts band does
            # not apply and the converted baseline is what gets classified.
            self.seed_plausibility = seed_plausibility(
                self.kalman.b if self.kalman.b is not None else working_frame)
        self._disconnected_flag = False
        self._disconnected_run = 0

        delta = self.kalman.step(working_frame)

        # Noise-floor telemetry only. The 3-tap median that used to be applied
        # here was measured worse and removed; what is left is the estimate
        # itself, reported so an operator and the audit trail can see that the
        # front end has gone noisy. `jitter_filter_active` stays False: nothing
        # filters the delta, and the field says so rather than disappearing.
        self._delta_history.append(np.asarray(delta, dtype=float).copy())
        if len(self._delta_history) >= 2:
            prev, cur = self._delta_history[-2], self._delta_history[-1]
            self._jitter_window.append(float(np.median(np.abs(cur - prev))))
        self.jitter_noise_counts = (
            float(np.median(self._jitter_window)) if self._jitter_window else 0.0)
        self.jitter_active = False

        self._raw_history.append(np.asarray(working_frame, dtype=float).copy())
        self._apply_quiescent_recovery(delta)

        warming = self.warming_up

        # F11: Surface Topography & Adaptive Gates
        # Connect analyze_surface_topography to live stream for real-time per-pad adaptive lift gate calculation
        if self.kalman.b is not None and (self.topography is None or self.index == self.warmup_frames):
            if is_cdc and self._cdc_initial_baseline is not None:
                self.topography = analyze_surface_topography(self._cdc_initial_baseline, is_cdc_pf=True)
            else:
                self.topography = analyze_surface_topography(self.kalman.b, is_cdc_pf=False)

            # Compute adaptive lift gates in counts space matching delta
            counts_topo = analyze_surface_topography(self.kalman.b, is_cdc_pf=False)
            if counts_topo.get("valid", False):
                self.adaptive_lift_gates = np.array(counts_topo["adaptive_lift_gates"], dtype=float)
                self.peel.set_adaptive_gates(self.adaptive_lift_gates)

        # F10: Scale-Normalized Delta Integration
        # Delta_C_norm_i = (Delta_C_i / C_{0, i}) * 28000.0
        # Normalizes relative baseline shifts (+/-20%) while preserving exact identity on bench data
        c0 = self.kalman.b if self.kalman.b is not None else np.full(N_PADS, BASELINE_COUNTS, dtype=float)
        safe_c0 = np.where(c0 > 1000.0, c0, BASELINE_COUNTS)
        norm_delta = compute_fractional_deltas(delta, safe_c0) * BASELINE_COUNTS

        # ONE classifier, and it is the trained one.
        #
        # A previous revision replaced this with a five-branch cascade of
        # hand-tuned count thresholds (n_lifted >= 8 -> level 3, n_pressed >= 3
        # -> level 1, ...) that reached the forest only in its final `else`, and
        # synthesised `probabilities` and `cpri_percent` from literals - 0.9,
        # 0.85, 100.0 - which the dashboard then displayed as model output.
        # Measured share of post-warmup frames per class under that cascade:
        #
        #   folder                 hard-coded L3 branch   reached the model
        #   Peel        (class 2)          98%                   0%
        #   Press       (NORMAL)           16%                  41%
        #   Horiz. Pull (class 3)           0%                  21%
        #
        # It inverted the two classes that matter: peel (a warning) was forced
        # to the critical siren, horizontal pull - which produces no lift
        # signal at all on this patch, see the A9/HPull caveat - fell through to
        # "hand press" on 45% of its frames and the regression suite measured
        # pull sensitivity dropping to 24/30. Meanwhile every figure in
        # metrics.json is produced by evaluate_stream(), which replays the
        # FOREST's predictions through AlarmDebouncer, so no published number
        # described the code that was running.
        #
        # The physics noise gate is kept, because it is the one part of that
        # cascade that can only ever suppress noise: a frame whose largest
        # excursion is under 60 counts is quieter than the measured baseline
        # swing (SOP criterion 5 allows 100), and no anomaly class in the corpus
        # is that quiet - Horizontal Pull still reads +456 on the contact side.
        # It now lives inside classify_deltas so both serving paths share it.
        #
        # CPRI is the probability-weighted risk and nothing else. The cascade
        # used to clamp it to per-level floors (85.0 for level 3, 55.0 for level
        # 2), which decoupled the number on screen from the distribution it
        # claims to summarise.
        if warming:
            proba = np.zeros(N_CLASSES)
            proba[0] = 1.0
            raw_level = 0
            risk = 0.0
        else:
            p, r, k = classify_deltas(self.model, norm_delta, self.use_gradient)
            proba, raw_level, risk = p[0], int(r[0]), float(k[0])

        level = self.alarm.update(raw_level)

        fused = None
        if self.fusion is not None:
            if imu is None and self._prev is not None:
                imu = synthesise_imu(np.vstack([self._prev, delta]))[-1]
            fused = self.fusion.step(risk, imu)
        self._prev = delta

        out = {
            "index": self.index,
            "time_sec": round(self.index * SAMPLE_PERIOD_S, 3),
            "seed_plausibility": self.seed_plausibility,
            "quiescent_recovery": self.quiescent_recovery,
            "jitter_filter_active": self.jitter_active,
            "jitter_noise_counts": round(self.jitter_noise_counts, 1),
            "pad_values": [round(v, 3 if is_cdc else 1) for v in pad_frame.tolist()],
            "deltas": [round(v, 1) for v in delta.tolist()],
            "normalized_deltas": [round(v, 1) for v in norm_delta.tolist()],
            "baseline": [round(v, 1) for v in (self.kalman.b if self.kalman.b is not None else working_frame).tolist()],
            "severity_level": level,
            "raw_level": raw_level,
            "status": ("Calibrating baseline ..." if warming
                       else STATUS_TEXT_MAP.get(level, "unknown")),
            "warming_up": warming,
            "probabilities": round_proba(proba.tolist()),
            "cpri_percent": round(risk, 1),
            "propagation": self.peel.update(delta, adaptive_gates=self.adaptive_lift_gates),
            "mode": "cdc" if is_cdc else "raw_counts",
        }
        if self.topography is not None:
            out["topography"] = self.topography
        if fused is not None:
            out["fusion"] = {k: round(float(v), 4) for k, v in fused.items()}
        self.index += 1
        return out



# =============================================================================
# 9b. CAPACITANCE-TO-DIGITAL (CDC) HARDWARE COMPATIBILITY LAYER
# =============================================================================
def convert_absolute_cdc_to_counts(
    c_abs_pf: np.ndarray,
    baseline_c_pf: Optional[np.ndarray] = None,
    nominal_baseline_counts: float = BASELINE_COUNTS,
    counts_per_pf: float = COUNTS_PER_PF,
    nominal_baseline_pf: float = NOMINAL_BASELINE_PF,
) -> np.ndarray:
    """Converts absolute capacitance (in pF) from a dedicated CDC board
    into calibrated raw counts or delta counts compatible with the 34-feature model.

    If baseline_c_pf is provided, returns delta counts:
        delta_counts = (c_abs_pf - baseline_c_pf) * counts_per_pf
    Otherwise, maps absolute pF to nominal raw counts relative to nominal baseline:
        raw_counts = nominal_baseline_counts + (c_abs_pf - nominal_baseline_pf) * counts_per_pf
    """
    arr = np.asarray(c_abs_pf, dtype=float)
    if baseline_c_pf is not None:
        base = np.asarray(baseline_c_pf, dtype=float)
        return (arr - base) * counts_per_pf
    return nominal_baseline_counts + (arr - nominal_baseline_pf) * counts_per_pf


def detect_static_tube_localization(
    c_abs_pf: np.ndarray,
    pad_coords: Optional[Dict[int, Tuple[float, float]]] = None,
) -> Dict[str, Any]:
    """Static tube localization & routing check from absolute capacitance (CDC).

    PVC/silicone intubation tubes (relative permittivity epsilon_r approx 2.8)
    introduce a geometric dielectric shadow compared to direct skin contact
    (epsilon_r approx 50-80). This function identifies pads under the tube axis
    before dynamic monitoring begins, eliminating startup zero-calibration ambiguity.
    """
    arr = np.asarray(c_abs_pf, dtype=float)
    if arr.size != N_PADS:
        return {"detected": False, "reason": f"expected {N_PADS} pads, got {arr.size}"}

    if np.isnan(arr).any() or np.isinf(arr).any():
        return {"detected": False, "reason": "non-finite capacitance values in input"}

    if (arr < 0.0).any():
        return {"detected": False, "reason": "negative capacitance values detected"}

    coords = pad_coords or PHYSICAL_PAD_COORDS
    median_cap = float(np.median(arr))

    # Adaptive dielectric shadow threshold using Median Absolute Deviation (MAD)
    # PVC/silicone tube shadow creates negative offset relative to surrounding skin-contact pads
    mad = float(np.median(np.abs(arr - median_cap)))
    # Normal consistency factor 1.4826; clamp threshold to reasonable physical bounds in pF
    drop_threshold = float(max(0.35, min(1.5, 1.4826 * mad * 1.5)))
    shadow_mask = (median_cap - arr) >= drop_threshold
    shadowed_pads = [pad_idx for pad_idx, is_shadow in enumerate(shadow_mask, start=1) if is_shadow]

    tube_present = len(shadowed_pads) >= 3
    axis_orientation = "unknown"
    if tube_present:
        xs = [coords[p][0] for p in shadowed_pads]
        ys = [coords[p][1] for p in shadowed_pads]
        spread_x = max(xs) - min(xs) if xs else 0.0
        spread_y = max(ys) - min(ys) if ys else 0.0
        if spread_x >= 25.0 and spread_y >= 25.0:
            axis_orientation = "diagonal"
        elif spread_y >= spread_x:
            axis_orientation = "vertical"
        else:
            axis_orientation = "horizontal"

    return {
        "detected": tube_present,
        "shadowed_pads": shadowed_pads,
        "median_capacitance_pf": round(median_cap, 3),
        "adaptive_threshold_pf": round(drop_threshold, 3),
        "axis_orientation": axis_orientation,
        "confidence": min(1.0, round(len(shadowed_pads) / 6.0, 3)) if tube_present else 0.0,
        "pad_capacitance_pf": [round(float(v), 3) for v in arr],
        "pad_shadow_depth_pf": [round(float(max(0.0, median_cap - v)), 3) for v in arr],
    }


def analyze_surface_topography(
    baseline_arr: np.ndarray,
    is_cdc_pf: Optional[bool] = None,
) -> Dict[str, Any]:
    """Analyze baseline capacitance distribution across the 25-pad array to detect
    non-planar contours, anatomical curvature, step-heights, and micro air-gap tenting
    around intubation tubes or anchor tape.

    Returns surface profile ('planar', 'moderate_contour', 'stepped_ridge'),
    identifies tenting vs flush pads, and generates per-pad adaptive lift gates.
    """
    arr = np.asarray(baseline_arr, dtype=float)
    if arr.size != N_PADS:
        return {"valid": False, "reason": f"expected {N_PADS} pads, got {arr.size}"}
    if np.isnan(arr).any() or np.isinf(arr).any():
        return {"valid": False, "reason": "non-finite baseline values"}
    if (arr < 0.0).any():
        return {"valid": False, "reason": "negative baseline values"}

    if is_cdc_pf is None:
        is_cdc_pf = bool(np.all(arr < 500.0) and np.any(arr > 0.05))

    med = float(np.median(arr))
    q25, q75 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
    iqr = max(0.2 if is_cdc_pf else 50.0, q75 - q25)
    roughness = float(iqr / (med + 1e-9))

    # Tenting detection: pads with baseline significantly below median
    # (air gap epsilon_r=1 vs skin epsilon_r=60 causes steep drop)
    tenting_threshold = med - 1.2 * iqr
    flush_threshold = med - 0.4 * iqr

    tenting_pads = [int(i + 1) for i, val in enumerate(arr) if val <= tenting_threshold]
    flush_pads = [int(i + 1) for i, val in enumerate(arr) if val >= flush_threshold]
    contoured_pads = [
        int(i + 1) for i, val in enumerate(arr)
        if tenting_threshold < val < flush_threshold
    ]

    # Surface classification
    if len(tenting_pads) >= 3 or roughness > 0.35:
        surface_profile = "stepped_ridge"
        recommendation = (
            f"Step-height discontinuity / tenting detected across pads {tenting_pads}. "
            "Smooth down hydrocolloid adhesive around tube boundary to eliminate air gaps."
        )
    elif roughness > 0.15:
        surface_profile = "moderate_contour"
        recommendation = "Curved anatomical contour detected (e.g. cheek/mandible). Per-pad adaptive gates active."
    else:
        surface_profile = "planar"
        recommendation = "Planar uniform contact verified. Standard thresholds active."

    # Compute per-pad adaptive lift gates
    # Default planar lift gate is -300 counts (~1.1% of nominal 28000 baseline)
    # If CDC pF, default nominal is ~30 pF, so 1.1% is ~ -0.33 pF
    alpha = 0.011
    min_floor = -0.15 if is_cdc_pf else -150.0
    adaptive_gates = [
        float(round(min(min_floor, -alpha * val), 2)) for val in arr
    ]

    return {
        "valid": True,
        "surface_profile": surface_profile,
        "roughness_ratio": round(roughness, 4),
        "median_baseline": round(med, 2),
        "iqr_baseline": round(iqr, 2),
        "tenting_pads": tenting_pads,
        "contoured_pads": contoured_pads,
        "flush_pads": flush_pads,
        "adaptive_lift_gates": adaptive_gates,
        "recommendation": recommendation,
    }


def compute_fractional_deltas(
    pad_delta: np.ndarray,
    baseline_capacitance: np.ndarray,
) -> np.ndarray:
    """Compute scale-invariant relative fractional delta: delta_i = Delta_C_i / C_{0, i}.
    Normalizes sensitivity across ridge, contour, and trough/step pads.
    """
    d = np.asarray(pad_delta, dtype=float)
    b = np.asarray(baseline_capacitance, dtype=float)
    safe_b = np.where(b <= 0.0, 1.0, b)
    return d / safe_b




# =============================================================================
# 10. FASTAPI SERVER
# =============================================================================
def safe_data_path(rel_path: str) -> str:
    """FIX F3: resolve a request path and refuse anything outside Data/.

    v5.0 did os.path.join(DATA_ROOT, filepath) with no containment check, and
    Starlette does not normalise '..' for a {name:path} converter, so
    /api/v5/dataset/../../secrets.csv escaped the data directory.
    """
    candidate = os.path.realpath(os.path.join(DATA_ROOT, rel_path.replace("\\", "/")))
    if os.path.commonpath([DATA_ROOT, candidate]) != DATA_ROOT:
        raise ValueError("path escapes the data directory")
    return candidate


# A11 - THE FASTAPI NAMES MUST BE MODULE-LEVEL. Do not move them back inside
# create_app().
#
# `from __future__ import annotations` at the top of this file turns every
# annotation into a string. FastAPI resolves those with typing.get_type_hints(),
# which looks names up in the endpoint's MODULE globals - a nested function's
# locals are invisible to it. While `WebSocket` was imported inside create_app,
# `ws: "WebSocket"` was unresolvable, so FastAPI fell back to treating `ws` as
# an ordinary REQUIRED QUERY PARAMETER and closed every single connection to
# /ws/live_sensor with code 1008:
#
#     {"loc": ["query", "ws"], "msg": "Field required"}
#
# LOOP 1 - the live feed, the serial stream and the ICU siren, the headline
# feature of v6.x - had therefore never worked through a browser. It went
# unnoticed because the dashboard falls back to the REST replay view without
# saying anything, `--replay` on the CLI bypasses FastAPI entirely, and the
# only tests that covered the socket were the stale v5.0 ones that could not
# even be imported. The GET routes were unaffected: their annotations are `str`
# and `int`, which resolve from builtins.
#
# Still imported defensively so --eval / --report / --audit keep running on a
try:
    from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles
    _fastapi_error: Optional[str] = None
except ImportError as _fastapi_exc:      # pragma: no cover - depends on the env
    FastAPI = File = HTTPException = Request = UploadFile = WebSocket = WebSocketDisconnect = None  # type: ignore
    HTMLResponse = JSONResponse = PlainTextResponse = Response = StaticFiles = None        # type: ignore
    _fastapi_error = str(_fastapi_exc)


def _key_ok(supplied: str, expected: str) -> bool:
    """Constant-time secret comparison that tolerates any input.

    hmac.compare_digest refuses non-ASCII *str* with a TypeError, so a request
    carrying ?key=e-acute used to escape the gate as an unhandled 500 rather
    than a 401 (B2). Encoding both sides first makes every input comparable.
    """
    return hmac.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                               expected.encode("utf-8", "surrogatepass"))


def create_app(model_holder: Dict[str, Any]) -> Any:
    if _fastapi_error is not None or FastAPI is None:
        raise RuntimeError(
            f"the dashboard needs fastapi and uvicorn ({_fastapi_error}). "
            f"Install them with: pip install -r requirements.txt")

    app = FastAPI(title="Touch Sensor Master Suite", version="6.2")

    # A13: optional shared-secret gate, off unless PROJECT2_ACCESS_KEY is set.
    #
    # The API is otherwise unauthenticated, which is fine on loopback and not
    # fine behind the public tunnel share_public.py opens: /api/v5/dataset
    # serves every recording, and /ws/live_sensor?source=serial&port=COM3 opens
    # a serial port on the host. A tunnel URL is guessable enough to be
    # scanned, so "nobody will find it" is not an access-control policy.
    #
    # The key may arrive as ?key=, an X-Access-Key header, or the cookie set on
    # first use - so one pasted link keeps working as the page fetches.
    access_key = os.environ.get("PROJECT2_ACCESS_KEY", "").strip()

    # Per-app throttle state, not module state - see AUTH_* above.
    auth_lock = threading.Lock()
    auth_failures: Dict[str, List[float]] = collections.defaultdict(list)

    def _throttled(client_ip: str) -> bool:
        """Record a failed attempt; True if this client is over the limit.

        Shared by the HTTP middleware and the WebSocket route. The socket used
        to skip this entirely, which left the access key brute-forceable at full
        speed through /ws/live_sensor - the one route that opens a serial port.
        """
        now = time.time()
        with auth_lock:
            recent = [t for t in auth_failures[client_ip] if now - t < AUTH_WINDOW_S]
            if len(recent) >= AUTH_MAX_FAILURES:
                auth_failures[client_ip] = recent
                return True
            recent.append(now)
            auth_failures[client_ip] = recent
            # Drop clients whose window has fully expired, so a scan across many
            # source addresses cannot grow this table without bound.
            if len(auth_failures) > AUTH_TABLE_MAX_IPS:
                for ip in [k for k, v in auth_failures.items()
                           if not v or now - v[-1] >= AUTH_WINDOW_S]:
                    del auth_failures[ip]
        return False

    if access_key:
        @app.middleware("http")
        async def _gate(request: Request, call_next: Any) -> Any:
            supplied = (request.query_params.get("key")
                        or request.headers.get("x-access-key")
                        or request.cookies.get("p2key") or "")
            if not _key_ok(supplied, access_key):
                client_ip = request.client.host if request.client else "unknown"
                if _throttled(client_ip):
                    logger_api.warning(f"Access key rate limit exceeded for IP {client_ip}")
                    return PlainTextResponse("429 - Too Many Failed Auth Attempts", status_code=429)
                logger_api.warning(f"Unauthorized access attempt from IP {client_ip}")
                return PlainTextResponse("401 - add ?key=... to the URL", status_code=401)
            response = await call_next(request)
            if _key_ok(request.query_params.get("key") or "", access_key):
                response.set_cookie(
                    "p2key", access_key, httponly=True, samesite="lax",
                    secure=(request.url.scheme == "https"
                            or request.headers.get("x-forwarded-proto") == "https"))
            return response

        # NEVER log the key itself. This line used to interpolate it, which on a
        # hosted deploy writes the shared secret into a log stream that outlives
        # the process and is readable by anyone with dashboard access.
        logger_api.info("Access key protection active (sha256=%s...); "
                        "the key is in the URL you were given, not in this log",
                        hashlib.sha256(access_key.encode()).hexdigest()[:8])

    @app.get("/api/v6/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "model_loaded": model_holder.get("model") is not None,
                "sample_period_s": SAMPLE_PERIOD_S, "n_pads": N_PADS}

    @app.get("/api/v6/layout")
    def layout() -> Dict[str, Any]:
        return {"pads": [{"pad": i + 1, "x": PAD_XY[i][0], "y": PAD_XY[i][1],
                          "signal_channel": int(PAD_TO_SIGNAL[i])} for i in range(N_PADS)]}

    @app.get("/api/v5/datasets")
    def datasets() -> Dict[str, List[str]]:
        """Every recording under Data/, not just the uploaded ones.

        This walked only Custom_Uploads/ for a while, which hid all 81 corpus
        recordings from the dashboard: the file dropdown showed uploads only, and
        pickForClass() in app.js - which looks for 'N_base/', 'Peel/',
        'Vertical Pull NO G/' prefixes - found none of them and fell through to
        datasets[0], so all four scenario preset buttons loaded the same
        arbitrary file. It also silently disarmed
        test_dataset_analysis_applies_the_debouncer, whose 'normals' list is
        built by filtering this response by class folder: with nothing but
        Custom_Uploads/ in it the list came back empty and the test returned
        without asserting anything.

        research_plots/ (PNG output), dot-directories and __pycache__ are
        skipped; the list stays plainly sorted because
        test_datasets_lists_recordings asserts names == sorted(names).
        """
        found: List[str] = []
        for root, dirnames, names in os.walk(DATA_ROOT):
            dirnames[:] = sorted(d for d in dirnames
                                 if not d.startswith(".")
                                 and d not in ("__pycache__", "research_plots"))
            for nm in names:
                if nm.lower().endswith(".csv"):
                    rel = os.path.relpath(os.path.join(root, nm), DATA_ROOT)
                    found.append(rel.replace("\\", "/"))
        return {"datasets": sorted(found)}

    @app.post("/api/v6/upload-csv")
    async def upload_custom_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Only .csv files are supported")

        custom_dir = os.path.join(DATA_ROOT, "Custom_Uploads")
        os.makedirs(custom_dir, exist_ok=True)

        # M3: Safe collision-free filename. basename() on a POSIX host does not
        # strip Windows separators, and a name may be all separators or dots, so
        # anything that does not survive sanitising gets a generated name rather
        # than being trusted.
        raw_name = os.path.basename(str(file.filename).replace("\\", "/")).replace(" ", "_")
        raw_name = "".join(c for c in raw_name if c.isalnum() or c in "._-")
        if not raw_name.lower().endswith(".csv") or raw_name.startswith("."):
            raw_name = f"upload_{uuid.uuid4().hex[:8]}.csv"
        name_no_ext, ext = os.path.splitext(raw_name)

        # M3: stage into a temp file FIRST. The upload used to be written
        # straight to its final name, and the quota sweep below used to run
        # before the size check - so a request that was correctly rejected with
        # 413 had already deleted other people's recordings on its way out.
        # Measured: one oversized POST against a full folder returned 413 and
        # destroyed 7 existing files. Nothing is deleted, and nothing lands in
        # Custom_Uploads/, until this upload is known to be valid.
        total_size = 0
        tmp_fd, tmp_path = tempfile.mkstemp(dir=custom_dir, prefix=".incoming_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "wb") as f_out:
                while True:
                    chunk = await file.read(65536)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"File size exceeds limit of {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
                    f_out.write(chunk)

            raw = read_raw_csv(tmp_path)
            if raw is None:
                raise HTTPException(status_code=400,
                                    detail="CSV file is invalid or missing 25 sensor columns")
            if len(raw) < MIN_FRAMES_PER_FILE:
                raise HTTPException(
                    status_code=422,
                    detail=f"Only {len(raw)} frames; at least {MIN_FRAMES_PER_FILE} needed")

            # Valid upload: now, and only now, make room for it.
            existing = sorted(
                (os.path.join(custom_dir, f) for f in os.listdir(custom_dir)
                 if f.lower().endswith(".csv")),
                key=os.path.getmtime)
            while len(existing) >= MAX_CUSTOM_UPLOADS:
                oldest = existing.pop(0)
                try:
                    os.remove(oldest)
                    logger_api.info(f"Custom_Uploads quota: evicted oldest upload {oldest}")
                except OSError as exc:
                    logger_api.error(f"Quota eviction failed for {oldest}: {exc}")
                    break

            safe_name = raw_name
            if os.path.exists(os.path.join(custom_dir, safe_name)):
                safe_name = f"{name_no_ext}_{uuid.uuid4().hex[:6]}{ext}"
            os.replace(tmp_path, os.path.join(custom_dir, safe_name))
            tmp_path = ""                       # adopted; do not clean up
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        rel_path = f"Custom_Uploads/{safe_name}"
        logger_api.info(f"Uploaded custom CSV: {rel_path} ({total_size} bytes, {len(raw)} frames)")
        return {
            "status": "uploaded",
            "filename": safe_name,
            "filepath": rel_path,
            "total_frames": len(raw),
            "size_bytes": total_size,
            "message": f"Successfully uploaded {safe_name} with {len(raw)} frames"
        }

    @app.get("/api/v5/serial/ports")
    def serial_ports() -> Dict[str, Any]:
        ports = list_serial_ports()
        return {"ports": ports, "available": len(ports),
                "note": "empty list means no COM device is attached to this host"}

    @app.post("/api/v5/serial/connect")
    def serial_connect(body: Dict[str, Any]) -> Dict[str, Any]:
        port = str(body.get("port", "")).strip()
        baud = int(body.get("baudrate", 115200))
        if not port:
            return {"status": "disconnected", "port": None, "mode": "loopback"}

        available = list_serial_ports()
        detected_devices = [p["device"] for p in available]
        if port not in detected_devices:
            raise HTTPException(
                status_code=404,
                detail=(f"Serial port '{port}' is not available on this host. "
                        f"Detected ports: {detected_devices or 'None'}")
            )
        logger_serial.info(f"Bound ingestion pipeline to serial port {port} @ {baud} baud")
        return {
            "status": "available",
            "port": port,
            "baudrate": baud,
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def _event_log_path() -> str:
        return os.path.join(DATA_ROOT, "extubation_events_audit.json")

    def _read_event_log(path: str) -> List[Dict[str, Any]]:
        """Load the audit trail, or raise. Callers must NOT default to [].

        A parse failure used to be swallowed to an empty list. On the write path
        that meant the next POST replaced the whole file with a single event:
        measured, one unparseable byte plus one POST took a 23-event trail down
        to 1, answered 200 "recorded", and restarted event_id at EVT-0001 so the
        new ids collided with the destroyed ones. An audit trail that quietly
        truncates is worse than no audit trail, because it still looks complete.
        """
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            logs = json.load(f)
        if not isinstance(logs, list):
            raise ValueError(f"audit trail is a {type(logs).__name__}, expected a list")
        return logs

    def _quarantine_event_log(path: str, exc: Exception) -> str:
        """Move an unreadable trail aside so it can be recovered by hand."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = f"{path}.corrupt-{stamp}"
        try:
            os.replace(path, dest)
            logger_api.error(f"Audit trail unreadable ({exc}); preserved at {dest}")
        except OSError as move_exc:
            logger_api.error(f"Audit trail unreadable ({exc}) and could not be "
                             f"moved aside ({move_exc})")
            dest = ""
        return dest

    @app.get("/api/v6/event-log")
    def get_event_logs() -> Dict[str, Any]:
        log_file = _event_log_path()
        with EVENT_LOG_LOCK:
            try:
                logs = _read_event_log(log_file)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                logger_api.error(f"Error reading event log file: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"The audit trail on disk is unreadable ({exc}). It has NOT "
                           f"been modified. Recover or move aside "
                           f"Data/extubation_events_audit.json before continuing.")
        return {"total_events": len(logs), "events": logs,
                "chain": verify_audit_chain(logs)}

    @app.post("/api/v6/cdc/tube-localization")
    def cdc_tube_localization(body: Dict[str, Any]) -> Dict[str, Any]:
        """Static tube localization & routing detection from absolute capacitance (CDC)."""
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
        values = body.get("c_abs_pf", [])
        if not isinstance(values, list) or len(values) != N_PADS or any(isinstance(x, bool) for x in values):
            raise HTTPException(
                status_code=400,
                detail=f"c_abs_pf must be a list of {N_PADS} numeric capacitance values in picofarads"
            )
        try:
            arr = np.array(values, dtype=float)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid numeric values: {exc}")
        return detect_static_tube_localization(arr)

    @app.post("/api/v6/topography/analyze")
    def analyze_topography_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze baseline array across 25 channels for contour curvature and step-height tenting."""
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object")
        values = body.get("baseline", body.get("baseline_capacitance", []))
        is_cdc_pf = body.get("is_cdc_pf", None)
        if is_cdc_pf is not None and not isinstance(is_cdc_pf, bool):
            raise HTTPException(status_code=400, detail="is_cdc_pf must be a boolean if provided")
        if not isinstance(values, list) or len(values) != N_PADS or any(isinstance(x, bool) for x in values):
            raise HTTPException(
                status_code=400,
                detail=f"baseline must be a list of {N_PADS} numeric capacitance values"
            )
        try:
            arr = np.array(values, dtype=float)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid numeric values: {exc}")
        return analyze_surface_topography(arr, is_cdc_pf=is_cdc_pf)

    @app.post("/api/v6/event-log")
    def append_event_log(body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            raw_sev = body["severity_level"]
            if isinstance(raw_sev, bool):
                raise ValueError("severity_level must not be boolean")
            severity = int(raw_sev)
            if severity not in (0, 1, 2, 3):
                raise HTTPException(status_code=400, detail="severity_level must be an integer in 0..3")

            raw_idx = body["frame_index"]
            if isinstance(raw_idx, bool):
                raise ValueError("frame_index must not be boolean")
            frame_idx = int(raw_idx)
            if frame_idx < 0:
                raise HTTPException(status_code=400, detail="frame_index must be >= 0")

            cpri_val = float(body["cpri_percent"])
            time_sec = float(body["time_sec"])
            dataset = str(body.get("dataset", "unknown"))
            min_delta = float(body.get("min_delta", 0.0))
            max_delta = float(body.get("max_delta", 0.0))
            confidence = float(body["confidence"]) if "confidence" in body and body["confidence"] is not None else None
            status_text = str(body.get("status", STATUS_TEXT_MAP.get(severity, "unknown")))
            attached_nodes = int(body.get("attached_nodes", 25))
            lifting_pads = int(body.get("lifting_pads", 0))
            grid_mean = float(body.get("grid_mean", 0.0))
            peel_desc = str(body.get("peel_desc", body.get("description", "")))
            # IEC 60601-1-8 treats silencing an alarm as a recordable action, so
            # the trail has to say what KIND of entry each row is. Anything not
            # in this set is rejected rather than silently filed as an alarm.
            event_type = str(body.get("event_type", "alarm"))
            if event_type not in ("alarm", "audio_muted", "audio_unmuted"):
                raise HTTPException(
                    status_code=400,
                    detail="event_type must be one of: alarm, audio_muted, audio_unmuted")
            probabilities = body.get("probabilities", [])
            deltas = body.get("deltas", [])

            if not math.isfinite(cpri_val) or not math.isfinite(max_delta) or not math.isfinite(min_delta) or not math.isfinite(time_sec) or not math.isfinite(grid_mean):
                raise HTTPException(status_code=400, detail="Numerical fields must be finite floats")
            if confidence is not None and not math.isfinite(confidence):
                raise HTTPException(status_code=400, detail="confidence must be a finite float")
            if probabilities and not all(math.isfinite(float(p)) for p in probabilities):
                raise HTTPException(status_code=400, detail="probabilities must contain finite floats")
            if deltas and not all(math.isfinite(float(d)) for d in deltas):
                raise HTTPException(status_code=400, detail="deltas must contain finite floats")

        except HTTPException:
            raise
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid event log fields: {exc}")

        log_file = _event_log_path()
        with EVENT_LOG_LOCK:
            try:
                logs = _read_event_log(log_file)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                dest = _quarantine_event_log(log_file, exc)
                raise HTTPException(
                    status_code=500,
                    detail=f"The audit trail was unreadable ({exc}) so this event was NOT "
                           f"recorded. The previous file was preserved at "
                           f"{os.path.basename(dest) if dest else 'its original path'}; "
                           f"recover it before continuing.")

            event = {
                # Unique per event, not derived from the current length. len()+1
                # restarts at 1 whenever the trail is shortened for any reason,
                # which produces duplicate ids referring to different events -
                # the one thing an audit identifier may never do.
                "event_id": f"EVT-{uuid.uuid4().hex[:12]}",
                "sequence": len(logs) + 1,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "event_type": event_type,
                "dataset": dataset,
                "frame_index": frame_idx,
                "time_sec": round(time_sec, 3),
                "severity_level": severity,
                "status": status_text,
                "cpri_percent": round(cpri_val, 1),
                "probabilities": [round(float(p), 4) for p in probabilities] if probabilities else [],
                "min_delta": round(min_delta, 1),
                "max_delta": round(max_delta, 1),
                "attached_nodes": attached_nodes,
                "lifting_pads": lifting_pads,
                "grid_mean": round(grid_mean, 1),
                "peel_desc": peel_desc,
                "deltas": [round(float(d), 1) for d in deltas] if deltas else []
            }
            if confidence is not None:
                event["confidence"] = round(confidence, 4)

            # Chain this event to the one before it. The last event's hash is
            # the link; a trail that has never been chained starts at genesis.
            prev_hash = AUDIT_GENESIS_HASH
            for earlier in reversed(logs):
                if "hash" in earlier:
                    prev_hash = str(earlier["hash"])
                    break
            event["prev_hash"] = prev_hash
            event["hash"] = audit_event_hash(event, prev_hash)
            logs.append(event)

            # M2: atomic write, and a failure here is reported as a failure.
            # This used to log the exception and still answer 200 "recorded",
            # so a caller believed an event was persisted when nothing had been
            # written - and the dashboard's own audit table was the only place
            # anyone would have noticed.
            temp_path: Optional[str] = None
            try:
                temp_fd, temp_path = tempfile.mkstemp(dir=DATA_ROOT, prefix="evt_", suffix=".tmp")
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f_tmp:
                    json.dump(logs, f_tmp, indent=2, ensure_ascii=False)
                    f_tmp.flush()
                    os.fsync(f_tmp.fileno())
                os.replace(temp_path, log_file)
                temp_path = None
                logger_api.info(f"Event logged: {event['event_id']} "
                                f"(Level {severity}, CPRI {cpri_val}%)")
            except Exception as exc:
                logger_api.error(f"Atomic write failed for event log: {exc}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Event was NOT recorded - could not write the audit trail ({exc})")
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        return {"status": "recorded", "event": event}

    @app.get("/api/v6/event-log/export-csv")
    def export_event_logs_csv() -> Any:
        """Export recorded clinical audit trail as a comprehensive downloadable CSV."""
        log_file = _event_log_path()
        with EVENT_LOG_LOCK:
            try:
                logs = _read_event_log(log_file)
            except Exception as exc:
                logger_api.error(f"Error reading event log for CSV export: {exc}")
                raise HTTPException(status_code=500, detail=f"Cannot read audit log: {exc}")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Event_ID", "Sequence", "Timestamp", "Dataset", "Frame_Index",
            "Time_Sec", "Severity_Level", "Status", "CPRI_Percent",
            "Prob_Baseline", "Prob_Touch", "Prob_Peel", "Prob_Pull",
            "Min_Delta", "Max_Delta", "Attached_Nodes", "Lifting_Pads",
            "Grid_Mean", "Peel_Description", "Pad_Deltas"
        ])
        for e in logs:
            probs = e.get("probabilities") or []
            p0 = probs[0] if len(probs) > 0 else ""
            p1 = probs[1] if len(probs) > 1 else ""
            p2 = probs[2] if len(probs) > 2 else ""
            p3 = probs[3] if len(probs) > 3 else ""
            deltas_list = e.get("deltas") or []
            deltas_str = ";".join(str(d) for d in deltas_list) if deltas_list else ""
            writer.writerow([
                e.get("event_id", ""),
                e.get("sequence", ""),
                e.get("timestamp", ""),
                e.get("dataset", ""),
                e.get("frame_index", ""),
                e.get("time_sec", ""),
                e.get("severity_level", ""),
                e.get("status", ""),
                e.get("cpri_percent", ""),
                p0, p1, p2, p3,
                e.get("min_delta", ""),
                e.get("max_delta", ""),
                e.get("attached_nodes", ""),
                e.get("lifting_pads", ""),
                e.get("grid_mean", ""),
                e.get("peel_desc", ""),
                deltas_str
            ])
        csv_text = output.getvalue()
        filename = f"event_logs_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        return Response(
            content=csv_text,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Access-Control-Expose-Headers": "Content-Disposition"
            }
        )

    @app.get("/api/v6/shift-report")
    def get_shift_report() -> Dict[str, Any]:
        """Aggregate recorded clinical telemetry into a formal shift handover report."""
        log_file = _event_log_path()
        with EVENT_LOG_LOCK:
            try:
                logs = _read_event_log(log_file)
            except Exception:
                logs = []

        total = len(logs)
        l1_count = sum(1 for e in logs if e.get("severity_level") == 1)
        l2_count = sum(1 for e in logs if e.get("severity_level") == 2)
        l3_count = sum(1 for e in logs if e.get("severity_level") == 3)

        return {
            "shift_id": f"SHIFT-{time.strftime('%Y%m%d')}-{time.strftime('%H%M')}",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_events": total,
            "event_breakdown": {
                "level_1_touch": l1_count,
                "level_2_peel_warning": l2_count,
                "level_3_critical_extubation": l3_count,
            },
            # `uptime_percentage` used to be here: 99.8 when the trail was empty,
            # otherwise 100 - (2.5 x level-3 count + 0.8 x level-2 count), floored
            # at 85. Nothing in this system measures uptime - not session length,
            # not dropped frames, not disconnect events - so every one of those
            # numbers was manufactured from an alarm count, and the dashboard
            # printed it as "Patch Uptime". Removed rather than approximated: if
            # uptime is wanted, measure disconnected frames over streamed frames
            # in LivePipeline and report THAT.
            "adhesion_health": {
                "monitored_channels": N_PADS,
                "patch_dimensions_mm": "90 x 120",
                "status": ("no level-3 event recorded this shift" if l3_count == 0
                           else f"{l3_count} level-3 event(s) recorded this shift"),
            },
            "recent_incidents": logs[-10:] if logs else [],
        }

    @app.get("/api/v6/ward/status")
    def get_ward_status() -> Dict[str, Any]:
        """Bed slots for the dashboard's ward panel. NO invented telemetry.

        This endpoint used to return eight beds with made-up patient ids
        (ICU-A-101 ...), made-up CPRI values (1.4, 3.8, 0.5 ...) and made-up
        statuses ("Post-Op Stable"), and the dashboard carried a second,
        different set of inventions with Thai patient names and HN numbers.
        Nothing behind either of them existed: this server classifies ONE patch
        on ONE socket, and it has no multi-patient data source at all.

        A screen that shows a bed as "Resting / Stable, CPRI 2.1%" when nothing
        is attached to it is not a demo shortcut, it is a monitor reporting a
        patient it cannot see. The slots below are therefore empty by
        construction: no identity, and `cpri_percent` is null rather than a
        number, so a consumer cannot mistake it for a reading. The operator
        labels the slot they are actually using from the dashboard.
        """
        beds = [{"bed": f"Bed {i + 1:02d}", "patient_id": None, "patient_label": None,
                 "status": "unassigned", "severity_level": 0, "cpri_percent": None,
                 "attached_nodes": None, "is_live": False}
                for i in range(WARD_BED_SLOTS)]
        return {
            "ward_name": None,
            "active_beds_count": 0,
            "bed_slots": len(beds),
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": ("This build monitors a single patch over one live socket. These are "
                     "empty UI slots, not monitored beds; there is no multi-patient data "
                     "source behind them."),
            "beds": beds,
        }

    @app.get("/api/v5/dataset/{filepath:path}")
    def dataset_analysis(filepath: str, calibration: str = "") -> Any:
        try:
            fpath = safe_data_path(filepath)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid dataset path")
        if not os.path.isfile(fpath):
            raise HTTPException(status_code=404, detail=f"Dataset not found: {filepath}")

        raw = read_raw_csv(fpath)
        if raw is None:
            raise HTTPException(status_code=400, detail="Requires 25 sensor columns")
        if len(raw) < MIN_FRAMES_PER_FILE:
            raise HTTPException(status_code=422,
                                detail=f"Only {len(raw)} frames; at least {MIN_FRAMES_PER_FILE} needed")

        mode = calibration if calibration in ("static", "kalman") else model_holder.get("calibration", "static")
        delta = calibrate(raw, mode)
        # Same classifier the socket uses, including the physics gate (R4).
        proba, raw_preds, risk = classify_deltas(
            model_holder.get("model"), delta, model_holder.get("use_gradient", False))

        # This endpoint feeds the dashboard's default view - what a visitor sees
        # on load. It previously returned the bare per-frame argmax and an
        # un-persisted peel gate, bypassing AlarmDebouncer and PeelTracker
        # entirely: 5 of 40 normal recordings sounded the Level 3 siren and 7
        # drew the peel arrow. The WebSocket path had the guards; this one did
        # not, and every test covered only the WebSocket path.
        debouncer = AlarmDebouncer()
        peel = PeelTracker()

        frames: List[Dict[str, Any]] = []
        for i in range(len(delta)):
            d = delta[i]
            warming = bool(mode == "kalman" and i < KALMAN_WARMUP)
            level = 0 if warming else debouncer.update(int(raw_preds[i]))
            frames.append({
                "index": i,
                "time_sec": round(i * SAMPLE_PERIOD_S, 3),
                "deltas": [round(float(v), 1) for v in d],
                "severity_level": level,
                "raw_level": int(raw_preds[i]),
                "warming_up": warming,
                "status": ("Calibrating baseline ..." if warming
                           else STATUS_TEXT_MAP.get(level, "unknown")),
                "probabilities": round_proba(proba[i]),
                "cpri_percent": 0.0 if warming else round(float(risk[i]), 1),
                "propagation": peel.update(d),
            })
        return JSONResponse({"filename": filepath, "calibration": mode,
                             "total_frames": len(frames), "frames": frames})

    @app.get("/api/v6/heatmap/{filepath:path}")
    def heatmap(filepath: str, frame: int = 0, calibration: str = "") -> Any:
        """Interpolated surface for a single frame.

        Deliberately one frame per request: v5.0 embedded a 60x80 grid for every
        frame in the dataset response, which reached 10.7 MB for a 119-frame file.
        """
        try:
            fpath = safe_data_path(filepath)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid dataset path")
        if not os.path.isfile(fpath):
            raise HTTPException(status_code=404, detail=f"Dataset not found: {filepath}")
        raw = read_raw_csv(fpath)
        if raw is None:
            raise HTTPException(status_code=400, detail="Requires 25 sensor columns")
        if not 0 <= frame < len(raw):
            raise HTTPException(status_code=416, detail=f"frame out of range 0..{len(raw)-1}")
        mode = (calibration if calibration in ("static", "kalman")
                else model_holder.get("calibration", "static"))
        delta = calibrate(raw, mode)[frame]
        grid = SPATIAL.interpolate(delta)
        return {"frame": frame, "calibration": mode,
                "rows": SPATIAL.n_rows, "cols": SPATIAL.n_cols,
                "matrix": np.round(grid, 1).tolist(),
                "propagation": SPATIAL.propagation(delta)}

    @app.websocket("/ws/live_sensor")
    async def live_sensor(ws: WebSocket) -> None:
        # A13b: @app.middleware("http") does NOT run for websocket scopes, so
        # the gate above left THIS route open - and this is the route that
        # opens a serial port on the host (?source=serial&port=COM3). The most
        # dangerous endpoint was the one the gate missed. Checked explicitly,
        # before accept, so an unauthorised peer never gets a session.
        if access_key:
            supplied = (ws.query_params.get("key")
                        or ws.headers.get("x-access-key")
                        or ws.cookies.get("p2key") or "")
            if not _key_ok(supplied, access_key):
                # Throttled on the same table as the HTTP gate. Without this the
                # key was brute-forceable at full speed here while the REST
                # routes cut you off after 10 tries.
                client_ip = ws.client.host if ws.client else "unknown"
                if _throttled(client_ip):
                    logger_api.warning(f"WebSocket auth rate limit exceeded for IP {client_ip}")
                await ws.close(code=1008)
                return
        await ws.accept()
        params = ws.query_params
        source_kind = params.get("source", "replay")
        cdc_flag = params.get("mode") == "cdc" or params.get("unit") == "pf"
        pipeline = LivePipeline(model_holder.get("model"),
                                model_holder.get("use_gradient", False),
                                fuse_imu=params.get("fuse", "0") == "1",
                                cdc_mode=cdc_flag)
        src: Optional[FrameSource] = None
        try:
            if source_kind == "serial":
                port = params.get("port", "")
                if not port:
                    await ws.send_json({"error": "serial source needs ?port=COM3"})
                    await ws.close()
                    return
                # B6: this string used to reach serial.Serial() unchecked, so a
                # caller could name any path on the host. pyserial's error text
                # then differed for "exists but is not a serial device" versus
                # "does not exist", which is a filesystem existence oracle -
                # and it is reachable by anyone holding the tunnel link.
                # F5: Retry loop for transient USB enumeration delays (up to 3 attempts)
                attached = set()
                for attempt in range(3):
                    attached = {p["device"] for p in list_serial_ports()}
                    if port in attached:
                        break
                    if attempt < 2:
                        await asyncio.sleep(0.15)
                if port not in attached:
                    await ws.send_json({
                        "error": "unknown serial port",
                        "attached": sorted(attached),
                        "hint": "GET /api/v5/serial/ports lists what is connected",
                    })
                    await ws.close()
                    return
                permute_flag = params.get("permute", "1") != "0"
                src = SerialFrameSource(port, int(params.get("baud", "115200")), permute=permute_flag)
            elif source_kind == "client":
                # INGEST. The peer holds the hardware (a browser using the Web
                # Serial API, or stream_to_cloud.py bridging a USB board to a
                # cloud instance) and pushes frames up; we classify and push the
                # result back.
                #
                # This is the branch that was missing. main.py contained no
                # ws.receive_* call at all, and any source= it did not recognise
                # fell through to ReplayFrameSource - so stream_to_cloud.py,
                # which connects with ?source=webserial and sends
                # {"raw_frame": [...]}, streamed real sensor data to a server
                # that discarded every message and replayed a canned recording
                # of Normal Mix/N_Mix_01.csv back at it, while printing
                # ">>> SENSOR STREAMING ACTIVE! <<<" and a live frame rate. A
                # demo run against that looks perfect and shows nothing from the
                # patch. web/web_serial.js worked around the same gap by
                # reimplementing the classifier in JavaScript.
                #
                # PAD ORDER, AND WHAT THIS ACTUALLY DOES BY DEFAULT.
                #
                # This comment used to state that "the same permutation is
                # applied here". It is not: the default below is permute=0, so
                # frames are consumed as-is unless the caller asks otherwise,
                # and web_serial.js does not ask. The serial branch above has
                # the same default. Neither default is wrong on the evidence -
                # every recording in the corpus is Sensor-* and measurably
                # already in pad order (--verify-pads, Spearman rho 1.0000) -
                # but nobody has captured a 1-by-1 sweep through THIS socket, so
                # the live convention is still unverified either way. Until that
                # sweep exists the effective setting is reported to the peer
                # instead of asserted in a comment, so a spatial result from
                # live hardware carries its own orientation with it.
                permute_flag = params.get("permute", "1") != "0"
                await ws.send_json({
                    "event": "started", "source": "client",
                    "pad_order_applied": permute_flag,
                    "pad_order_note": ("frames are permuted through PAD_ORDER" if permute_flag
                                       else "frames are used as sent; add &permute=1 if the "
                                            "board emits Signal-* electrical order"),
                    "expects": {"raw_frame": f"{N_PADS} numbers, Signal-1..{N_PADS} order"},
                })
                while True:
                    # F1: Catch JSON decoding errors, ValueError, and disconnects without dropping the session
                    try:
                        msg = await ws.receive_json()
                    except (json.JSONDecodeError, ValueError) as exc:
                        logger_api.warning(f"Malformed JSON frame received on /ws/live_sensor: {exc}")
                        try:
                            await ws.send_json({"error": f"malformed JSON frame: {exc}"})
                        except Exception:
                            break
                        continue
                    except WebSocketDisconnect:
                        return
                    if not isinstance(msg, dict):
                        await ws.send_json({"error": "expected a JSON object"})
                        continue
                    if msg.get("event") == "stop":
                        break
                    if msg.get("event") == "reseed":
                        pipeline.reseed()
                        await ws.send_json({"event": "reseeded", "status": "ok"})
                        continue
                    vals = msg.get("raw_frame")
                    if not isinstance(vals, list) or len(vals) < N_PADS:
                        await ws.send_json({"error": f"raw_frame must be {N_PADS} numbers",
                                            "got": (len(vals) if isinstance(vals, list) else None)})
                        continue
                    try:
                        arr = np.asarray(vals[:N_PADS], dtype=float)
                    except (TypeError, ValueError):
                        await ws.send_json({"error": "raw_frame must be numeric"})
                        continue
                    if not np.isfinite(arr).all():
                        await ws.send_json({"error": "raw_frame contains non-finite values"})
                        continue
                    pad_frame = signals_to_pads(arr) if permute_flag else arr
                    await ws.send_json(pipeline.process(pad_frame))
                await ws.send_json({"event": "finished", "frames": pipeline.index})
                return
            elif source_kind in ("simulator", "live", "standby"):
                src = SimulatorFrameSource(SAMPLE_PERIOD_S)
            else:
                src = ReplayFrameSource(params.get("file", "Normal Mix/N_Mix_01.csv"),
                                        realtime=params.get("realtime", "1") == "1",
                                        loop=params.get("loop", "0") == "1")
            await ws.send_json({"event": "started", "source": src.name,
                                "pad_order_applied": bool(getattr(src, "permute", False))})
            loop = asyncio.get_running_loop()
            gen = src.frames()
            # next(gen) blocks - up to IDLE_TIMEOUT_S on a silent serial port -
            # so it runs on a bounded private executor rather than the event
            # loop's default one. Sharing the default executor meant a handful
            # of live clients could occupy every worker in it and stall
            # unrelated work; a dedicated 2-thread pool per socket also gets
            # torn down with the socket instead of leaking workers.
            pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="p2-frames")
            try:
                while True:
                    frame = await loop.run_in_executor(pool, lambda: next(gen, None))
                    if frame is None:
                        break
                    await ws.send_json(pipeline.process(frame))
                await ws.send_json({"event": "finished", "frames": pipeline.index})
            finally:
                # Ask the source to stop first so the blocked read returns
                # promptly, then let the worker finish rather than abandoning it.
                src.close()
                pool.shutdown(wait=True, cancel_futures=True)
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            try:
                await ws.send_json({"error": str(exc)})
            except Exception:
                pass
        finally:
            if src is not None:
                src.close()
            try:
                await ws.close()
            except Exception:
                pass

    @app.get("/api/v6/metrics")
    def metrics() -> Any:
        """The generated metrics, verbatim, for anything that displays results.

        A12: the web app's "Medical Audit Report" carried four hand-typed
        figures - 97.53 % accuracy, a 0.0 % false-alarm rate, a 4.48 s "lead
        time gain" for a quantity nobody has measured, and a 12 ms dispatch
        latency for a feature that does not exist. Three of the four were
        wrong and all four broke rule 1. Anything that displays a number now
        reads it from here, which only --report writes.
        """
        path = os.path.join(DATA_ROOT, "metrics.json")
        if not os.path.isfile(path):
            raise HTTPException(
                status_code=503,
                detail="No metrics on disk. Generate them with: "
                       "python main.py --report --stream --seeds 5")
        with open(path, "r", encoding="utf-8") as fh:
            return JSONResponse(json.load(fh))

    # The dashboard lives in web/ as ordinary .html/.css/.js files rather than
    # a 281-line string literal inside this module. One UI, edited normally,
    # served from here so it shares an origin with the API - opening
    # web/index.html directly as a file:// page cannot call it.
    if os.path.isdir(WEB_DIR):
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard() -> Any:
        index = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(index):
            return HTMLResponse(status_code=500, content=(
                "<h1>web/index.html is missing</h1>"
                "<p>The dashboard is served from the <code>web/</code> folder "
                "next to main.py. The API is unaffected - try "
                "<a href='/api/v6/health'>/api/v6/health</a>.</p>"))
        with open(index, "r", encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read())

    return app


# =============================================================================
# 11. RESEARCH PLOTS  (FIX F6: out-of-fold ROC)
# =============================================================================
def generate_plots(ds: Dataset, rf_result: Dict[str, Any], model: Any) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(RESEARCH_PLOTS_DIR, exist_ok=True)
    names = feature_names(bool(ds.X.shape[1] > len(BASE_FEATURE_NAMES)))

    imp = model.feature_importances_
    order = np.argsort(imp)[::-1]
    plt.figure(figsize=(10, 5.5))
    plt.bar(range(len(names)), imp[order], color="#2a78d6", edgecolor="black", alpha=.9)
    plt.xticks(range(len(names)), [names[i] for i in order], rotation=35, ha="right", fontsize=9)
    plt.ylabel("Gini importance")
    plt.title("Spatio-temporal feature importance", fontweight="bold")
    plt.grid(axis="y", linestyle="--", alpha=.4)
    plt.tight_layout()
    plt.savefig(os.path.join(RESEARCH_PLOTS_DIR, "feature_importances.png"), dpi=200)
    plt.close()

    # ROC from OUT-OF-FOLD probabilities (FIX F6)
    oof = rf_result["oof_proba"]
    plt.figure(figsize=(8.5, 6.5))
    colors = ["#10b981", "#eda100", "#eb6834", "#e34948"]
    labels = ["Class 0 Baseline", "Class 1 Incidental", "Class 2 Peel", "Class 3 Pull"]
    for c in range(N_CLASSES):
        pos = (ds.y == c).astype(int)
        if pos.sum() == 0 or pos.sum() == len(pos):
            continue
        fpr, tpr, _ = roc_curve(pos, oof[:, c])
        plt.plot(fpr, tpr, color=colors[c], lw=2.4, label=f"{labels[c]} (AUC = {auc(fpr, tpr):.3f})")
    plt.plot([0, 1], [0, 1], "k--", lw=1.2, alpha=.6)
    plt.xlabel("False positive rate")
    plt.ylabel("True positive rate")
    plt.title("Out-of-fold ROC (frame level, leave-one-file-out)", fontweight="bold")
    plt.legend(loc="lower right", fontsize=9)
    plt.grid(alpha=.3)
    plt.tight_layout()
    plt.savefig(os.path.join(RESEARCH_PLOTS_DIR, "multiclass_roc_curves.png"), dpi=200)
    plt.close()

    cm = confusion_matrix(rf_result["y_true"], rf_result["y_pred"], labels=list(range(N_CLASSES)))
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.matshow(cm, cmap="Blues")
    for (i, j), z in np.ndenumerate(cm):
        ax.text(j, i, str(z), ha="center", va="center", fontweight="bold",
                color="white" if z > cm.max() / 2 else "black")
    tick = ["0 Baseline", "1 Touch", "2 Peel", "3 Pull"]
    ax.set_xticks(range(4))
    ax.set_yticks(range(4))
    ax.set_xticklabels(tick, rotation=15)
    ax.set_yticklabels(tick)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    plt.title(f"File-level confusion matrix ({rf_result['n_seeds']} seed(s) pooled)\n"
              f"acc {rf_result['accuracy_mean']*100:.1f}%", pad=22)
    plt.tight_layout()
    plt.savefig(os.path.join(RESEARCH_PLOTS_DIR, "confusion_matrix.png"), dpi=200)
    plt.close()

    # LOOP 3 illustration: propagation on the deepest peel frame
    # Match the class label, not a literal "Peel/" prefix - under the SOP's
    # session layout the path is "S1/Peel/..." and the figure silently vanished.
    peel = [i for i, lab in enumerate(ds.labels) if lab == 2]
    if not peel:
        print("  note: no class-2 (Peel) recordings - skipping the propagation figure")
    if peel:
        d = ds.frames[peel[0]]
        k = int(np.argmin(d.mean(axis=1)))
        grid = SPATIAL.interpolate(d[k])
        g = SPATIAL.node_gradients(d[k])
        fig, ax = plt.subplots(figsize=(6.4, 7.6))
        # Blue = capacitance drop = dressing lifting, red = contact. This is the
        # convention used in KES 2025 Fig. 4 and in the dashboard; coolwarm_r
        # would have flipped it and shown a peel in alarm-red.
        lim = float(np.abs(grid).max()) or 1.0
        im = ax.imshow(grid, origin="upper", extent=(10.0, 90.0, 95.0, 10.0), cmap="coolwarm",
                       vmin=-lim, vmax=lim, aspect="auto")
        fig.colorbar(im, ax=ax, shrink=.8, label="delta capacitance (counts)")
        ax.quiver(PAD_XY[:, 0], PAD_XY[:, 1], g[:, 0], -g[:, 1], color="k",
                  scale=None, width=.005, label="local gradient")
        pr = SPATIAL.propagation(d[k])
        if pr["active"] and pr["origin"]:
            ax.annotate("", xy=(pr["centroid"][0], pr["centroid"][1]),
                        xytext=(pr["origin"]["x"], pr["origin"]["y"]),
                        arrowprops=dict(arrowstyle="-|>", lw=2.5, color="#0ea5e9"))
        ax.set_title(f"Peel propagation field\n{pr['description']}", fontweight="bold", fontsize=10)
        ax.set_xlabel("patch width (%)")
        ax.set_ylabel("patch height (%)")
        ax.scatter(PAD_XY[:, 0], PAD_XY[:, 1], s=6, c="k", alpha=.5)
        plt.tight_layout()
        plt.savefig(os.path.join(RESEARCH_PLOTS_DIR, "peel_propagation_field.png"), dpi=200)
        plt.close()

    print(f"  plots -> {RESEARCH_PLOTS_DIR}")


# =============================================================================
# 11b. DATA AUDIT AND METRICS REPORT  (see ACTION_PLAN.md P0-1, P0-2)
# =============================================================================
# RAW-count threshold for "the patch is off the skin", as published in KES 2025
# s2.1: <= 25,000 counts. Do not move it. A revision dated 2026-08-18 raised it
# to 28,500 with a comment redefining the spec as "27,000 - 28,000 counts", and
# the arithmetic of why that cannot be a detachment criterion is worth keeping
# here, because the 27,000-28,000 observation behind it is CORRECT and the
# conclusion drawn from it was not.
#
# Measured over the whole corpus (min raw per file, and the median of each
# file's first five - quiescent - frames):
#
#   folder                  deepest raw   resting raw
#   N_base (nothing at all)      27,464        27,991
#   Friction (normal)            27,555        28,159
#   Press   (normal)             27,387        28,731
#   Peel                         27,251        28,098
#   Vertical Pull                27,263        27,894
#
# The whole corpus lives in a band roughly 27,250 - 28,700 wide. So:
#
#   at 28,500  ->  81 of 81 files "reach detachment", INCLUDING 5 of 5 N_base
#                  recordings in which nothing happens. The threshold sits ABOVE
#                  the resting attached value, so the check is a constant True.
#   at 25,000  ->  0 of 81. Nothing this patch has ever recorded comes within
#                  ~2,250 counts of the published figure.
#
# 0/81 is the honest result and it is a finding, not a failure to be tuned away:
# the spec threshold does not describe what THIS patch reads at detachment, so
# the spec must not be quoted as a detection criterion. Detection does not use
# raw counts at all - it uses the delta from the tracked baseline, where the
# lift gate is -300 counts and works. See _caveats() and [[sensor_findings]].
SPEC_DETACH_MAX = 25000.0        # KES 2025 s2.1 detachment criterion, as published
SPEC_CONTACT_MIN = 30000.0       # Direct finger contact (> 30,000 counts)

# Where the patch RESTS while attached, measured over the round-1 corpus on
# 2026-09-18: the per-file Kalman seed (mean of the first KALMAN_WARMUP frames)
# of every recording that starts at rest spans 27,823-28,258 counts, median
# 28,025. The only seeds outside that range are 10 of the 11 Press recordings,
# which the operator started while already pressing (28,657-29,999) - exactly
# the "something on the patch at power-on" case this check exists to flag, and
# the reason the band is set from the resting files and not from all 81.
# tests/test_seed_plausibility.py recomputes both facts from the corpus and
# pins this band to them, so it cannot drift from the data.
#
# Why it exists (supervisor item 2, 2026-09-17): a relative-capacitance board
# zeroes on whatever it sees at power-on. If the patch is loose, absent, or
# being pressed at that moment, every later delta is measured from the wrong
# place and nobody can tell. F3 only rejects seeds outside 10,000-45,000 -
# garbage, not "the patch was not on the skin yet". Until the absolute-CDC
# board exists this is the mitigation the current hardware allows. It never
# rejects: a genuinely different mounting may rest elsewhere. It REPORTS, so
# the console can say "verify attachment" instead of trusting the zero.
ATTACHED_SEED_BAND = (27500.0, 28600.0)


def seed_plausibility(seed_counts: np.ndarray) -> Dict[str, Any]:
    """Classify a Kalman seed against the attached-at-rest band. Never rejects."""
    arr = np.asarray(seed_counts, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"status": "unknown", "seed_median": None, "band": list(ATTACHED_SEED_BAND),
                "outlier_pads": [], "note": "seed frame carried no finite values"}
    med = float(np.median(finite))
    lo, hi = ATTACHED_SEED_BAND
    if med < lo:
        status = "below_band"
        note = ("seed rests below where an attached patch rested in round 1 - patch "
                "loose, absent, or lifted at power-on; re-seat it and re-seed before "
                "trusting alarms")
    elif med > hi:
        status = "above_band"
        note = ("seed rests above the attached band - something was pressing on the "
                "patch at power-on; release it and re-seed")
    else:
        status = "attached_band"
        note = "seed within the round-1 attached-at-rest band"

    # Per-channel contamination, checked against the median of the same frame.
    # The band test above is a median over 25 pads and cannot see one or two
    # elevated channels: N_Touch_02 seeds at a median of 28,199 - squarely
    # inside the band - while pad 2 sits 792 counts above it, which then reads
    # as a permanent -792 lift for the rest of the recording. Deviation is
    # measured against the frame's own median rather than the band, so a patch
    # resting at a different absolute C0 is judged on its own flatness.
    if arr.size == SEED_RESTING_SHAPE.size:
        # Offset-corrected: only the SHAPE is compared, so a patch resting at a
        # different absolute C0 is judged on its own topography.
        shape = SEED_RESTING_SHAPE + (med - float(np.median(SEED_RESTING_SHAPE)))
        dev = np.abs(arr - shape)
    else:
        dev = np.abs(arr - med)
    outliers = [int(i) + 1 for i in np.nonzero(np.isfinite(dev) &
                                               (dev > SEED_CHANNEL_OUTLIER_COUNTS))[0]]
    if outliers:
        listed = ", ".join(str(p) for p in outliers)
        plural = "Pads" if len(outliers) > 1 else "Pad"
        # Direction matters clinically and costs one line: a channel seeded HIGH
        # is the contamination case (something resting on it at power-on, which
        # then reads as a permanent lift). A channel seeded LOW is a different
        # fault - an open or unbonded electrode - and telling an operator to
        # "release the patch" would send them after the wrong thing.
        high = [p for p in outliers if arr[p - 1] > shape[p - 1]] if arr.size == SEED_RESTING_SHAPE.size \
            else [p for p in outliers if arr[p - 1] > med]
        cause = ("something was touching them when the baseline was taken"
                 if len(high) == len(outliers) else
                 "these channels did not seed with the rest of the patch")
        return {"status": "channel_outlier", "seed_median": round(med, 1), "band": [lo, hi],
                "outlier_pads": outliers, "band_status": status,
                "outlier_pads_high": high,
                "note": (f"{plural} {listed} seeded more than "
                         f"{SEED_CHANNEL_OUTLIER_COUNTS:.0f} counts from the rest during "
                         f"power-on warmup - {cause}; re-seed the baseline before trusting "
                         f"alarms")}

    return {"status": status, "seed_median": round(med, 1), "band": [lo, hi],
            "outlier_pads": [], "note": note}
MIN_AUDIT_FRAMES = 100           # SOP v2: 60-120 s per file at 560 ms
BASELINE_MAX_SWING = 100.0       # SOP v2 criterion 5, now actually enforced
ROUND1_FRICTION_SWING = 654.0    # measured on the round-1 corpus, not a spec


def _iter_class_dirs(root: str) -> Iterator[Tuple[str, str]]:
    """Yield (label, absolute path) for every class folder under root.

    FIX D3: delegates to `scan_csv_dirs`, the same scan the loader uses, so
    `--audit` can no longer report a folder clean that the loader will silently
    drop. The previous version walked the tree by its own rules and missed
    `Peel/retake/*.csv` entirely - it saw CSVs directly inside `Peel/`, yielded
    it, and never looked deeper.
    """
    known, _ = scan_csv_dirs(root)
    for rel, _folder, path in sorted(known):
        yield rel, path


def _median_delta(per_class: Dict[str, Dict[str, Any]], label_class: int) -> str:
    """Median of the per-folder median deepest delta, for the audit detail line."""
    vals = [v["median_deepest_delta"] for label, v in per_class.items()
            if CLASS_MAPPING.get(label.split("/")[-1], {}).get("label") == label_class
            and v.get("median_deepest_delta") is not None]
    return f"{float(np.median(vals)):,.0f}" if vals else "n/a"


def audit_folder(root: str) -> Dict[str, Any]:
    """Pass/fail a freshly recorded folder against the device spec.

    Round 1 was recorded, analysed, and only then found to be 3.4x weaker than
    the published detachment spec, because nothing checked raw counts against
    it. Run this before packing up, while the rig is still assembled.
    """
    root = os.path.realpath(root)
    checks: List[Dict[str, Any]] = []
    per_class: Dict[str, Dict[str, Any]] = {}
    unusable: List[Tuple[str, str]] = []
    _, stray = scan_csv_dirs(root)
    nested_dirs: List[str] = [f"{rel}/ ({n} csv) - {hint}" for rel, n, hint in stray]
    lost_files = sum(n for _, n, _ in stray)

    for label, fpath in _iter_class_dirs(root):
        files = sorted(glob.glob(os.path.join(fpath, "*.csv")))
        reach_low = reach_high = dirty = short = 0
        lows: List[float] = []
        frames: List[int] = []
        swings: List[float] = []
        # Deepest DELTA from the file's own quiescent baseline. This is the
        # quantity the detector actually gates on (-DELTA_THRESHOLD), unlike the
        # raw-count spec above, so it is the one that tells a collection session
        # whether the fixation produced a usable lift signal.
        deltas_low: List[float] = []
        reach_lift = 0
        for f in files:
            problem = describe_csv_problem(f)
            if problem:
                unusable.append((os.path.relpath(f, root), problem))
                continue
            raw = read_raw_csv(f)
            assert raw is not None
            frames.append(len(raw))
            lows.append(float(raw.min()))
            if raw.min() <= SPEC_DETACH_MAX:
                reach_low += 1
            if raw.max() >= SPEC_CONTACT_MIN:
                reach_high += 1
            head = raw[:min(5, len(raw))]
            if float((head.max(axis=0) - head.min(axis=0)).max()) > 150.0:
                dirty += 1
            if len(raw) < MIN_AUDIT_FRAMES:
                short += 1
            swings.append(float((raw.max(axis=0) - raw.min(axis=0)).max()))
            deepest_delta = float(calibrate(raw, "static").min())
            deltas_low.append(deepest_delta)
            if deepest_delta <= -DELTA_THRESHOLD:
                reach_lift += 1
        per_class[label] = {
            "files": len(files), "usable": len(frames),
            "reach_detach_spec": reach_low, "reach_contact_spec": reach_high,
            "offset_contaminated": dirty, "under_min_frames": short,
            "min_raw": round(min(lows), 1) if lows else None,
            "reach_lift_gate": reach_lift,
            "deepest_delta": round(min(deltas_low), 1) if deltas_low else None,
            "median_deepest_delta": round(float(np.median(deltas_low)), 1) if deltas_low else None,
            "median_frames": int(np.median(frames)) if frames else 0,
            "max_swing": round(max(swings), 1) if swings else None,
        }

    def _check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    # One aggregator, two predicates. These were two copies of the same loop
    # with the same four (now five) counter names typed out twice - so adding
    # `reach_lift_gate` meant remembering to add it in both places, and
    # forgetting would have silently zeroed the new check for one of them.
    def _sum_where(keep: Callable[[str], bool]) -> Dict[str, int]:
        tot = {"files": 0, "usable": 0, "reach_detach_spec": 0,
               "reach_contact_spec": 0, "reach_lift_gate": 0}
        for label, v in per_class.items():
            if keep(label.split("/")[-1]):
                for k in tot:
                    tot[k] += v[k]
        return tot

    def _agg(label_class: int) -> Dict[str, int]:
        """Aggregate every folder that maps to one class label."""
        return _sum_where(lambda leaf: CLASS_MAPPING.get(leaf, {}).get("label") == label_class)

    def _agg_named(*folders: str) -> Dict[str, int]:
        """Aggregate specific folders by name, across sessions."""
        return _sum_where(lambda leaf: leaf in folders)

    # --- completeness comes first: a missing class used to remove its own check
    present = {CLASS_MAPPING[name.split("/")[-1]]["label"]
               for name in per_class if name.split("/")[-1] in CLASS_MAPPING}
    missing = [CLASS_LABEL_NAMES[c] for c in range(N_CLASSES) if c not in present]
    _check("all four classes recorded", not missing,
           f"missing: {', '.join(missing)}" if missing else "0/1/2/3 all present")

    peel = _agg(2)
    _reach = spec_detach_reachability(SPEC_DETACH_MAX)
    _peel_detail = (f"{peel['reach_detach_spec']}/{peel['usable']} usable files (need >= 80%)"
                    if peel["usable"] else "no usable Peel recordings")
    if not _reach["reachable"]:
        _peel_detail += (f" - UNREACHABLE BY ARITHMETIC: needs a "
                         f"{_reach['drop_needed_pf']:,.1f} pF drop from a "
                         f"~{_reach['available_pf']:,.1f} pF patch; floor at zero capacitance "
                         f"is {_reach['floor_counts_at_zero_capacitance']:,.0f} counts. "
                         f"Pump/adhesive cannot pass this; only raising C0 (thinner backing, "
                         f"ground plane) or a corrected constant can. See spec_detach_reachability()")
    _check(f"Peel reaches <= {SPEC_DETACH_MAX:,.0f} counts (KES 2025 s2.1)",
           peel["usable"] > 0 and peel["reach_detach_spec"] >= 0.8 * peel["usable"],
           _peel_detail)

    # The check above is against a PUBLISHED RAW-COUNT figure, and on this
    # hardware it fails for every recording ever made - the corpus rests around
    # 28,000 counts and bottoms out at 27,251, some 2,250 counts short of the
    # 25,000 the spec names. That is a real finding about the spec, not about any
    # one collection session, so it cannot tell an operator whether TODAY's rig
    # is any good. (Nor can moving the threshold: at 28,500 it sits above the
    # resting attached value and passes every recording including bare baseline,
    # which is how the constant came to be raised on 2026-08-18.)
    #
    # This is the check that can answer that question, because it is the
    # quantity the detector actually gates on: the deepest delta from the file's
    # own quiescent baseline against -DELTA_THRESHOLD. Measured on round 1:
    # Peel median -866 (10/10 cross), Vertical Pull -777 (10/10), Horizontal
    # Pull -64 (0/10, the known blind spot), Friction -94 (0/10), N_base -31.
    _check(f"Peel crosses the {-DELTA_THRESHOLD:,.0f} count lift gate (the "
           f"criterion the detector uses)",
           peel["usable"] > 0 and peel["reach_lift_gate"] >= 0.8 * peel["usable"],
           f"{peel['reach_lift_gate']}/{peel['usable']} usable files cross it; "
           f"median deepest delta {_median_delta(per_class, 2)} counts (need >= 80%)"
           if peel["usable"] else "no usable Peel recordings")

    # FIX D4: the SOP's criterion is "Brief Touch >= 8/10 files reach > 30,000".
    # The old check pooled every class-1 folder and asked for 50%, so Brief
    # Touch and Press alone carried it while Friction sat at 0/10 - the exact
    # weak class P1-4 exists to catch. Pooling made the failure invisible.
    touch = _agg_named("Brief Touch", "Touch")
    _check("Brief Touch reaches > 30,000 counts (SOP s5)",
           touch["usable"] > 0 and touch["reach_contact_spec"] >= 0.8 * touch["usable"],
           f"{touch['reach_contact_spec']}/{touch['usable']} usable files (need >= 80%)"
           if touch["usable"] else "no usable Brief Touch recordings")

    total = sum(v["files"] for v in per_class.values())
    dirty_total = sum(v["offset_contaminated"] for v in per_class.values())
    short_total = sum(v["under_min_frames"] for v in per_class.values())
    _check("no movement inside the 5-frame offset window", dirty_total == 0,
           f"{dirty_total}/{total} files contaminated")
    _check(f"every file >= {MIN_AUDIT_FRAMES} frames", short_total == 0,
           f"{short_total}/{total} files too short")
    _check("no unreadable or aborted recordings", not unusable,
           f"{len(unusable)} unusable: {[n for n, _ in unusable][:4]}" if unusable else "none")
    # FIX D3: every CSV under the root is either read or reported. No file
    # disappears between the folder on disk and the table above.
    _check("every CSV sits in a folder the loader reads", not nested_dirs,
           f"{lost_files} file(s) in {len(nested_dirs)} stray folder(s) - see below"
           if nested_dirs else f"all {total} accounted for")

    # SOP criterion 5, previously declared but never implemented
    base_swings = [v["max_swing"] for lbl, v in per_class.items()
                   if lbl.split("/")[-1] in ("N_base", "Baseline") and v["max_swing"] is not None]
    _check(f"baseline swing <= {BASELINE_MAX_SWING:.0f} counts",
           bool(base_swings) and max(base_swings) <= BASELINE_MAX_SWING,
           f"worst {max(base_swings):.0f} counts" if base_swings else "no baseline recording")

    # Advisories are printed but do NOT gate the audit. P1-4: Friction was the
    # only class the temporal model got wrong in round 1, at +317 counts (about
    # 6x noise) against Brief Touch's 67x. There is no published spec for it, so
    # inventing a pass threshold would be dishonest - but the number has to be
    # visible while the rig is still assembled, not discovered weeks later.
    advisories: List[str] = []
    fric = [v["max_swing"] for lbl, v in per_class.items()
            if lbl.split("/")[-1] == "Friction" and v["max_swing"] is not None]
    if fric:
        worst = max(fric)
        advisories.append(
            f"Friction swing {worst:.0f} counts (round 1: {ROUND1_FRICTION_SWING:.0f}). "
            + ("stronger than round 1 - good" if worst > ROUND1_FRICTION_SWING else
               "NOT stronger than round 1 - press the cloth flatter and rub slower, "
               "or merge Friction into Brief Touch (P1-4)"))

    return {"root": root, "per_class": per_class, "checks": checks,
            "unusable": unusable, "nested": nested_dirs, "lost_files": lost_files,
            "advisories": advisories,
            "passed": all(c["pass"] for c in checks) and bool(per_class)}


def print_audit(rep: Dict[str, Any]) -> bool:
    print(f"\nData audit: {rep['root']}")
    print("=" * 82)
    if not rep["per_class"]:
        print("  no class folders with CSV files found")
        for n in rep.get("nested", []):
            print(f"  {n}")
        print("  RESULT: nothing to audit")
        return False
    print(f"  {'class':<26}{'files':>6}{'ok':>5}{'<=25k':>7}{'>30k':>6}"
          f"{'dirty':>7}{'short':>7}{'min raw':>10}{'swing':>8}")
    for name, v in rep["per_class"].items():
        print(f"  {name:<26}{v['files']:>6}{v['usable']:>5}{v['reach_detach_spec']:>7}"
              f"{v['reach_contact_spec']:>6}{v['offset_contaminated']:>7}"
              f"{v['under_min_frames']:>7}"
              f"{v['min_raw'] if v['min_raw'] is not None else '-':>10}"
              f"{v['max_swing'] if v['max_swing'] is not None else '-':>8}")
    print()
    for c in rep["checks"]:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['check']:<48} {c['detail']}")
    for a in rep.get("advisories", []):
        print(f"  [note] {a}")
    if rep.get("nested"):
        print(f"\n  {rep.get('lost_files', 0)} CSV file(s) will NOT be loaded - fix the "
              f"folder names before analysing:")
        for n in rep["nested"]:
            print(f"    - {n}")
    print("=" * 82)
    print("  RESULT: " + ("ready to analyse" if rep["passed"]
                          else "RE-RECORD the failing classes now, while the rig is still set up"))
    return bool(rep["passed"])


def _caveats(ds: Dataset) -> List[str]:
    """The caveats that must travel with any number in this report.

    A5: three of these used to be string literals - "deepest is 27,251",
    "Class 0 n=5 and class 2 n=10". They were true of the round-1 corpus and
    would have stayed on the page unchanged after round 2, inside the one file
    whose stated purpose is that paper numbers are never typed by hand. Every
    figure below is now measured from the dataset that was actually loaded, so
    a caveat that stops being true stops being printed.
    """
    out = [
        "The +/- on the file-level accuracy is estimator seed variation on a "
        "handful of borderline files, NOT sampling uncertainty. Quote the Wilson "
        "or bootstrap CI instead.",
        "File-level majority vote depends on clip length: re-voting the same events "
        "padded to the round-2 SOP length of 60-120 s takes pull recall to 0.000 "
        "while episode detection stays at 1.000. Report episode-level metrics.",
    ]

    anomaly_mins = [v for lab, v in ds.min_raw_by_label.items() if lab >= 2]
    if anomaly_mins:
        deepest = min(anomaly_mins)
        if deepest > SPEC_DETACH_MAX:
            r = spec_detach_reachability(SPEC_DETACH_MAX)
            note = (f"No anomaly file reaches the <= {SPEC_DETACH_MAX:,.0f} count detachment "
                    f"spec (KES 2025 s2.1); deepest is {deepest:,.0f} "
                    f"({(BASELINE_COUNTS - deepest) / COUNTS_PER_PF:,.1f} pF below the "
                    f"{BASELINE_COUNTS:,.0f} count resting value).")
            if not r["reachable"]:
                note += (
                    f" THE CRITERION IS UNREACHABLE ON THIS SENSOR, so this is not a "
                    f"fixation problem: it asks for a {r['drop_needed_pf']:,.1f} pF drop out of "
                    f"an attached patch of about {r['available_pf']:,.1f} pF, and even at zero "
                    f"capacitance the reading floors at {r['floor_counts_at_zero_capacitance']:,.0f} "
                    f"counts, {r['shortfall_counts']:,.0f} short. A stronger pump or better "
                    f"adhesive cannot change that; only a geometry change that raises C0 - "
                    f"thinner backing (C ~ 1/d), a ground plane - can, or one of BASELINE_COUNTS, "
                    f"COUNTS_PER_PF, SPEC_DETACH_MAX is wrong. Measure C0 with an LCR meter "
                    f"(SOP v2 section 0.2) before buying either. Detection does not use this "
                    f"criterion - it gates on the delta from the tracked baseline.")
            else:
                note += " Check the fixation method used for these recordings."
            out.append(note)
        else:
            out.append(
                f"Deepest anomaly count is {deepest:,.0f}, at or below the "
                f"{SPEC_DETACH_MAX:,.0f} detachment spec (KES 2025 s2.1).")

    out.append("LOOP 5 IMU signals are synthetic. No fusion number belongs in a "
               "results table.")

    counts = {lab: sum(1 for x in ds.labels if x == lab) for lab in sorted(set(ds.labels))}
    small = [(lab, n) for lab, n in counts.items() if n <= 10]
    if small:
        _worst_lab, worst_n = min(small, key=lambda kv: kv[1])
        lo, hi = wilson(worst_n, worst_n)
        out.append(
            "Small classes: "
            + ", ".join(f"{CLASS_LABEL_NAMES[lab]} n={n}" for lab, n in small)
            + f". A perfect {worst_n}/{worst_n} on the smallest of them carries a 95% CI "
              f"of about {lo:.2f}-{hi:.2f}, so it is not evidence of 100% performance.")

    # The measured blind spot. This is the most important caveat in the file and
    # it was not being printed at all: the classifier separates Horizontal Pull
    # from normal activity on a PRESS proxy, not on the dressing leaving the
    # skin, so a horizontal detachment that a clinician would call an
    # extubation risk produces no lift signal for this patch to see.
    out.append(
        "Horizontal detachment produces NO lift signal on this patch. Measured over the "
        "round-1 corpus, Horizontal Pull recordings reach a median deepest delta of only "
        "-64 counts (deepest -161) and 0 of 10 cross the -300 lift gate - quieter than "
        "Friction, which is a normal class. What moves on those recordings is the "
        "positive/contact side (median max +456), so any Horizontal Pull the system does "
        "flag, it flags as a press-like event and not as detachment. Vertical Pull and "
        "Peel do cross the gate (10/10 each). Do not describe this device as detecting "
        "detachment in general until a horizontal-pull signal has been demonstrated.")

    if ds.conventions.get("sensor") and not ds.conventions.get("signal"):
        try:
            pads = verify_pad_order()
            settled = pads["inversions"] == 0
            out.append(
                f"All {ds.conventions['sensor']} recordings use Sensor-* columns, read as "
                f"physical pad order without applying PAD_ORDER. That is no longer an "
                f"assumption: the 1-by-1 press sweep in {pads['file']} peaks in strictly "
                f"increasing column order (Spearman rho {pads['spearman_rho']:.4f}, "
                f"{pads['inversions']} inversions), so Sensor-N == physical pad N for this "
                f"corpus. " + ("" if settled else "THIS CHECK FAILED - spatial results are "
                               "scrambled, fix the logger before quoting any of them. ") +
                "Re-run `python main.py --verify-pads` after any firmware or logger change. "
                "Still open, and it is now an open question in BOTH directions: the live "
                "sockets (?source=serial and ?source=client) default to permute=0, so they "
                "do NOT apply PAD_ORDER unless a caller passes &permute=1, and no 1-by-1 "
                "sweep has been captured through either. The setting in force is reported "
                "in the socket's own `started` message as `pad_order_applied`. Until that "
                "sweep exists, spatial output from LIVE hardware (heatmap, peel heading) is "
                "unverified whichever way the flag is set.")
        except (CsvProblem, ValueError, OSError) as exc:
            out.append(
                f"All {ds.conventions['sensor']} recordings use Sensor-* columns, read as "
                f"physical pad order without applying PAD_ORDER, while the live serial path "
                f"always applies it. The 1-by-1 sweep that would settle this could not be "
                f"read ({exc}), so heatmaps, peel direction and the LOOP 3 figure rest on an "
                f"unverified assumption. Run `python main.py --verify-pads`.")
    elif ds.conventions.get("sensor") and ds.conventions.get("signal"):
        out.append(
            f"The corpus mixes column conventions ({ds.conventions['sensor']} Sensor-*, "
            f"{ds.conventions['signal']} Signal-*), so spatial results pool two different "
            "pad orientations. Do not quote any spatial figure until the logger is fixed.")

    if ds.n_sessions < 2:
        out.append(
            f"Single sensor mounting ({ds.n_sessions} session). Nothing here shows "
            "generalisation to a re-attached patch.")
    return out


def write_report(ds: Dataset, rf: Dict[str, Any], temporal: Optional[Dict[str, Any]],
                 stamp: str, stream: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Emit every headline number to disk.

    The v5.0 whitepaper quoted 90.00% / macro F1 0.8791; the script produced
    87.50% / 0.8498. Numbers typed by hand drift from numbers the code
    produces. Paper tables must be copied from METRICS.md, never retyped.
    """
    os.makedirs(DATA_ROOT, exist_ok=True)
    counts = {name: int(sum(1 for lab in ds.labels if lab == i))
              for i, name in enumerate(["baseline", "incidental", "peel", "pull"])}
    # One call, one array. average=None returns a per-class vector; np.asarray
    # makes that explicit for the type checker as well as the reader.
    per_class_f1 = np.asarray(f1_score(rf["y_true"], rf["y_pred"],
                                       labels=list(range(N_CLASSES)),
                                       average=None, zero_division=0), dtype=float)
    payload: Dict[str, Any] = {
        "generated": stamp,
        "version": "6.2",
        "dataset": {
            "files": ds.n_files, "frames": int(len(ds.X)), "features": int(ds.X.shape[1]),
            "sessions": ds.n_sessions, "session_names": ds.session_names,
            "files_per_class": counts,
            "column_conventions": ds.conventions,          # A9
            "min_raw_count_by_class": ds.min_raw_by_label,  # A5
            "skipped": [{"file": f, "reason": r} for f, r in ds.skipped],
        },
        "random_forest": {
            "cv": rf["cv"], "seeds": [r["seed"] for r in rf["runs"]],
            "confusion_matrix_note": f"pooled over {rf['n_seeds']} seed(s); "
                                     f"accuracy over the pool equals the mean above",
            "accuracy_mean": rf["accuracy_mean"], "accuracy_sd": rf["accuracy_sd"],
            "macro_f1_mean": rf["macro_f1_mean"], "macro_f1_sd": rf["macro_f1_sd"],
            # Per-class F1, pooled over the seeds. The dashboard has had a
            # `data-metric="peel_f1"` slot since the panel was built and this key
            # never existed, so even a working renderer could not have filled it.
            # Computed ONCE, above, and indexed here: written inline it was two
            # identical f1_score calls, and `f1_score(...)[2]` is also what
            # Pylance flags as indexing a float, because the stub declares the
            # scalar return and not the ndarray that average=None gives back.
            "per_class_f1": {CLASS_LABEL_NAMES[c]: float(per_class_f1[c])
                             for c in range(N_CLASSES)},
            "peel_f1": float(per_class_f1[2]),
            "false_alarm_rate": false_alarm_rate(rf["y_true"], rf["y_pred"]),
            "confusion_matrix": confusion_matrix(rf["y_true"], rf["y_pred"],
                                                 labels=list(range(N_CLASSES))).tolist(),
        },
        "peel_gate": {
            "min_pads": PEEL_MIN_PADS, "mean_gate": PEEL_MEAN_GATE,
            "persist_frames": PEEL_PERSIST_FRAMES,
            "note": "tuned on the round-1 corpus; treat as in-sample until re-validated",
        },
        "episode_level": ({
            "operating_point": stream["operating_point"],
            "sensitivity": stream["sensitivity"], "sensitivity_ci": stream["sensitivity_ci"],
            "false_alarm_rate": stream["false_alarm_rate"],
            "false_alarm_ci": stream["false_alarm_ci"],
            "alarms_per_hour": stream["alarms_per_hour"],
            "median_latency_s": stream["median_latency_s"],
            "max_latency_s": stream["max_latency_s"],
            "missed": stream["missed"], "curve": stream["curve"],
        } if stream else None),
        "caveats": _caveats(ds),
    }
    if temporal:
        payload["temporal_bilstm"] = {
            "windows": temporal["n_windows"], "window_frames": WINDOW_FRAMES,
            "window_seconds": round(WINDOW_FRAMES * SAMPLE_PERIOD_S, 2),
            "seeds": temporal["seeds"],
            "nn_accuracy_mean": temporal["nn_accuracy_mean"],
            "nn_accuracy_sd": temporal["nn_accuracy_sd"],
            "nn_macro_f1_mean": temporal["nn_macro_f1_mean"],
            "nn_macro_f1_sd": temporal["nn_macro_f1_sd"],
            "rf_accuracy_mean": temporal["rf_accuracy_mean"],
            "rf_accuracy_sd": temporal["rf_accuracy_sd"],
            "rf_macro_f1_mean": temporal["rf_macro_f1_mean"],
            "rf_macro_f1_sd": temporal["rf_macro_f1_sd"],
            "bilstm_wins": temporal["bilstm_wins"], "verdict": temporal["verdict"],
        }

    json_path = os.path.join(DATA_ROOT, "metrics.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    n_seeds = rf["n_seeds"]
    lines = [
        "# METRICS - generated by `python main.py --report`", "",
        f"Generated: {stamp} | main.py v6.2", "",
        "> Copy paper tables from this file. Do not retype numbers by hand -",
        "> that is how the v5.0 whitepaper came to quote a figure the code never produced.",
        "", "## Dataset", "",
        f"- Files: {ds.n_files} | Frames: {len(ds.X)} | Features: {ds.X.shape[1]}",
        f"- Sessions: {ds.n_sessions} ({', '.join(ds.session_names) or 'none'})",
        f"- Files per class: {counts}",
        f"- Column convention: {ds.conventions or 'n/a'} "
        f"(Sensor-* used as-is, Signal-* permuted through PAD_ORDER)",
        f"- Skipped: {[f for f, _ in ds.skipped] or 'none'}", "",
        f"## {type(_new_rf(42)).__name__} ({rf['cv']}-level cross validation)", "",
        "| Metric | Value |", "|---|---|",
        f"| Accuracy | {rf['accuracy_mean']*100:.2f}%"
        + (f" ± {rf['accuracy_sd']*100:.2f} (n={n_seeds} seeds)" if n_seeds > 1 else "") + " |",
        f"| Macro F1 | {rf['macro_f1_mean']:.4f}"
        + (f" ± {rf['macro_f1_sd']:.4f}" if n_seeds > 1 else "") + " |",
        "| Tie-break | toward the more severe class |",
        f"| False alarm on normal files | {false_alarm_rate(rf['y_true'], rf['y_pred'])*100:.1f}% |",
        "",
        # The old line here said "RandomForest seed variation" and was printed
        # whatever the spread turned out to be. With the estimator this project
        # now ships that spread is exactly 0.00 - HistGradientBoosting has no
        # subsampling and early stopping is off at this sample size, so every
        # seed produces the identical model. A "+/- 0.00 over 5 seeds" that a
        # reader takes for stability evidence, when it only means the seed is
        # not used, is the same class of claim this file exists to prevent.
        ("_The +/- above is estimator seed variation, not sampling uncertainty. "
         "Use the intervals below when quoting a result._"
         if n_seeds > 1 and rf["accuracy_sd"] > 0 else
         "_This estimator is deterministic on this corpus: every seed produced "
         "the identical model, so the seed spread is 0.00 by construction and is "
         "NOT evidence of stability. `--seeds N` buys nothing here beyond N times "
         "the runtime. Quote the Wilson or bootstrap interval below instead._"),
        "",]
    yt1, yp1 = rf["y_true_first"], rf["y_pred_first"]
    k = int(sum(1 for a, b in zip(yt1, yp1) if a == b))
    wlo, whi = wilson(k, len(yt1))
    boot = bootstrap_ci(yt1, yp1)
    lines += [
        f"- Accuracy {k}/{len(yt1)} = {100*k/len(yt1):.1f}%, "
        f"Wilson 95% CI [{wlo*100:.1f}, {whi*100:.1f}]",
        f"- Bootstrap 95% CI over files: accuracy "
        f"[{boot['accuracy'][0]*100:.1f}, {boot['accuracy'][1]*100:.1f}], "
        f"macro F1 [{boot['macro_f1'][0]:.3f}, {boot['macro_f1'][1]:.3f}]",
        "", "```",
    ]
    present = sorted(set(rf["y_true"]) | set(rf["y_pred"]))
    names = ["0: Baseline", "1: Touch/Press", "2: Peel", "3: Pull"]
    lines.append(str(classification_report(rf["y_true"], rf["y_pred"], labels=present,
                                           target_names=[names[i] for i in present],
                                           zero_division=0)))
    lines.append("```")
    if n_seeds > 1:
        lines.append(f"\n_Report and confusion matrix pool all {n_seeds} seeds "
                     f"({len(rf['y_true'])} file-level predictions), so they agree with the "
                     f"mean quoted above._")
    if temporal:
        tn = temporal["n_seeds"]
        lines += ["", f"## LOOP 2 - temporal model (grouped 5-fold, {tn} seeds, identical protocol)", "",
                  "| Model | Accuracy | Macro F1 |", "|---|---|---|",
                  f"| Random Forest, single frame | {temporal['rf_accuracy_mean']*100:.2f}% "
                  f"± {temporal['rf_accuracy_sd']*100:.2f} | {temporal['rf_macro_f1_mean']:.4f} "
                  f"± {temporal['rf_macro_f1_sd']:.4f} |",
                  f"| 1D-CNN + BiLSTM, {WINDOW_FRAMES*SAMPLE_PERIOD_S:.2f} s window | "
                  f"{temporal['nn_accuracy_mean']*100:.2f}% ± {temporal['nn_accuracy_sd']*100:.2f} | "
                  f"{temporal['nn_macro_f1_mean']:.4f} ± {temporal['nn_macro_f1_sd']:.4f} |",
                  "",
                  f"**Verdict: {temporal['verdict']}** (BiLSTM wins {temporal['bilstm_wins']}/{tn} seeds)."]
        if temporal["bilstm_wins"] < tn:
            lines += ["", "> Do not claim the temporal model is better than the Random Forest on",
                      "> this corpus. A single-seed run of this comparison produced BiLSTM 0.9730",
                      "> vs RF 0.9328 and that number was published; across seeds the two are",
                      "> within each other's spread and the RF is the more stable of the two."]
    if stream:
        op = stream["operating_point"]
        slo, shi = stream["sensitivity_ci"]
        flo, fhi = stream["false_alarm_ci"]
        lines += ["", "## Episode-level performance (out-of-fold, live annunciator)", "",
                  "**This is the clinical unit.** The file-level table above depends on clip "
                  "length; this one does not.", "",
                  f"Operating point: {op['votes']}-of-{op['window']} frames, "
                  f"hold {op['hold']} frames ({op['hold']*SAMPLE_PERIOD_S:.2f} s).", "",
                  "| Metric | Value | 95% CI |", "|---|---|---|",
                  f"| Sensitivity (episode detected) | {stream['sensitivity']*100:.1f}% | "
                  f"[{slo*100:.1f}, {shi*100:.1f}] |",
                  f"| False alarm per recording | {stream['false_alarm_rate']*100:.1f}% | "
                  f"[{flo*100:.1f}, {fhi*100:.1f}] |",
                  f"| False alarms per hour | {stream['alarms_per_hour']:.1f} | — |",
                  # A4: these are None when no anomaly episode was ever
                  # detected (no class 2/3 recordings, or every one missed).
                  # print_stream_report guarded that; this did not, so --report
                  # died with a bare TypeError on exactly the dataset whose
                  # numbers most needed writing down.
                  "| Time to alarm (median / worst) | "
                  + (f"{stream['median_latency_s']:.2f} s / {stream['max_latency_s']:.2f} s"
                     if stream["median_latency_s"] is not None
                     else "no episode detected") + " | — |",
                  f"| Alarm onsets per detected event | {stream['onsets_per_anomaly']:.2f} | — |",
                  "", f"Missed events ({len(stream['missed'])}): "
                  f"{', '.join(stream['missed']) or 'none'}", "",
                  "### Operating curve", "",
                  "| window | k | hold | sensitivity | FA / recording | alarms / hour | latency |",
                  "|---|---|---|---|---|---|---|"]
        for r in stream["curve"]:
            lat = (f"{r['median_latency_s']:.2f} s"
                   if r["median_latency_s"] is not None else "—")   # A6
            lines.append(f"| {r['window']} | {r['votes']} | {r['hold']} | "
                         f"{r['sensitivity']*100:.1f}% | {r['false_alarm_rate']*100:.1f}% | "
                         f"{r['alarms_per_hour']:.1f} | {lat} |"
                         + ("" if not r["is_default"] else " "))
        lines += ["", "The operating point is a clinical trade-off, not a tuned "
                  "hyperparameter. Reference burden: a retrospective ICU cohort "
                  "reports a median 119 alarms/patient/day, ~5/hour (Sci Rep 2022, "
                  "s41598-022-26261-4), and states that no threshold defining a "
                  "'high' alarm rate exists. The default is therefore justified as "
                  "roughly doubling the existing burden, not as sitting under a "
                  "published safe limit. Tuned on round-1 data — re-validate on "
                  "round 2 without touching it."]

    lines += ["", "## Caveats that must appear alongside any of the above", ""]
    lines += [f"{i+1}. {c}" for i, c in enumerate(payload["caveats"])]
    if not temporal:
        lines += ["", "> LOOP 2 (BiLSTM) was not run for this report. Re-run with "
                  "`--report --eval-temporal` to regenerate that section; do not "
                  "carry the table over from an older file."]
    if not stream:
        lines += ["", "> Episode-level metrics were not computed for this report."]
    if ds.n_sessions < 2:
        lines += ["", "> **Single session.** Every recording shares one sensor mounting, so these",
                  "> figures cannot show generalisation to a new attachment. Record under",
                  "> `Data/S1`, `Data/S2`, `Data/S3` and re-run with `--cv session`."]
    md_path = os.path.join(DATA_ROOT, "METRICS.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return json_path, md_path


# =============================================================================
# 12. ENTRY POINT
# =============================================================================
def verify_pad_order(rel_path: str = "Press/1_by_1.csv") -> Dict[str, Any]:
    """Settle caveat A9 from a 1-by-1 press sweep instead of asserting it.

    The bench measurement the A9 comment asks for was already in the repo and
    had never been read back: Data/Press/1_by_1.csv is a recording of each pad
    being pressed once, in pad order. If the columns are in physical pad order,
    then column k must peak later than column k-1 for all 25 columns.

    Take each column's argmax frame and correlate it against the column index.
    On the round-1 corpus that gives Spearman rho = 1.0000 with 0 inversions, so
    Sensor-N == physical pad N for those recordings and applying PAD_ORDER to
    them would scramble the patch - which is why read_raw_csv does not.

    This is deliberately a measurement with a printable verdict rather than a
    comment, so it can be re-run the day the firmware or the logger changes:

        python main.py --verify-pads
        python main.py --verify-pads "Press/1_by_1.csv"
    """
    full = safe_data_path(rel_path)
    raw = read_raw_csv(full)
    if raw is None:
        raise CsvProblem(f"{rel_path}: unreadable, or missing the 25 sensor columns")
    if len(raw) < N_PADS:
        raise CsvProblem(f"{rel_path}: {len(raw)} frames cannot contain {N_PADS} presses")

    delta = calibrate(raw, "static")
    peak_frame = delta.argmax(axis=0)
    order = np.argsort(peak_frame)
    inversions = int(sum(1 for a in range(N_PADS) for b in range(a + 1, N_PADS)
                         if peak_frame[a] > peak_frame[b]))
    # Spearman rho between column index and peak time, without pulling in scipy.stats
    idx = np.arange(N_PADS, dtype=float)
    ranks = np.argsort(np.argsort(peak_frame)).astype(float)
    rho = float(np.corrcoef(idx, ranks)[0, 1])
    monotonic = bool(np.all(np.diff(peak_frame[np.arange(N_PADS)]) > 0))

    return {
        "file": rel_path,
        "frames": int(len(raw)),
        "peak_frame_per_column": [int(v) for v in peak_frame],
        "column_order_by_peak_time": [int(v) + 1 for v in order],
        "inversions": inversions,
        "spearman_rho": round(rho, 4),
        "strictly_increasing": monotonic,
        "verdict": ("Sensor-N == physical pad N (columns are already in pad order; "
                    "PAD_ORDER must NOT be applied to this corpus)"
                    if inversions == 0 else
                    f"columns are NOT in pad order - {inversions} inversions. Spatial "
                    f"results from these recordings are scrambled until this is resolved."),
    }


def print_pad_verification(rep: Dict[str, Any]) -> bool:
    print("\n" + "=" * 70)
    print("A9 - PAD ORDER VERIFICATION (1-by-1 press sweep)")
    print("=" * 70)
    print(f"  file                : {rep['file']} ({rep['frames']} frames)")
    print(f"  peak-time ordering  : {rep['column_order_by_peak_time']}")
    print(f"  inversions          : {rep['inversions']}")
    print(f"  Spearman rho        : {rep['spearman_rho']:.4f}")
    print(f"  strictly increasing : {rep['strictly_increasing']}")
    print(f"\n  {rep['verdict']}")
    print("=" * 70)
    print("  NOTE: this settles the CSV corpus only. The live serial path applies"
          "\n  PAD_ORDER to Signal-* frames and no sweep has been captured through"
          "\n  it, so spatial output from LIVE hardware stays unverified until you"
          "\n  record the same sweep via /ws/live_sensor and re-run this.")
    return rep["inversions"] == 0


def dataset_fingerprint(ds: Dataset, calibration: str, use_gradient: bool) -> str:
    """Identify the exact corpus a cached model was trained on.

    The cache key used to be f"{n_files}_{n_frames}_{calibration}_{gradient}",
    which does not describe the data at all - only its shape. Moving one
    recording from Press/ to Peel/ changes neither the file count nor the frame
    count, so the key was identical and the server silently kept serving a model
    trained on the OLD labels. Re-recording a file to the same length did the
    same thing. Path, label, size and mtime of every loaded file go in, so any
    edit that could change what the model learned changes the key.
    """
    h = hashlib.sha256()
    h.update(f"v2|{calibration}|{int(use_gradient)}|{N_PADS}|{N_CLASSES}|".encode())
    for rel, lab in zip(ds.files, ds.labels):
        full = os.path.join(DATA_ROOT, rel)
        try:
            st = os.stat(full)
            stamp = f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            stamp = "missing"
        h.update(f"{rel}|{lab}|{stamp}\n".encode())
    return h.hexdigest()


def load_persisted_model(ds_hash: str) -> Optional[Any]:
    """Load the cached forest, but only after verifying the file we were given.

    joblib.load() unpickles, which executes whatever the file says to execute.
    The previous version checked an integrity field stored INSIDE the pickle -
    a check that can only run after the dangerous step, so it verified nothing.
    This project also lives in a synced OneDrive folder, which is exactly the
    kind of place a model file can change without anyone touching the repo.

    The digest now lives in a separate plain-text sidecar and is verified
    against the bytes on disk BEFORE they are deserialised. No sidecar, or a
    mismatch, means retrain - which costs ~30 s and is always safe.
    """
    if not os.path.isfile(MODEL_PERSISTENCE_PATH) or not os.path.isfile(MODEL_DIGEST_PATH):
        return None
    try:
        with open(MODEL_DIGEST_PATH, "r", encoding="utf-8") as fh:
            recorded = json.load(fh)
        if recorded.get("dataset") != ds_hash:
            logger_model.info("Cached model was trained on a different corpus; retraining")
            return None
        with open(MODEL_PERSISTENCE_PATH, "rb") as fh:
            blob = fh.read()
        actual = hashlib.sha256(blob).hexdigest()
        if not hmac.compare_digest(actual, str(recorded.get("sha256", ""))):
            logger_model.warning(
                "Refusing to load %s: its sha256 does not match %s. Delete both to retrain.",
                os.path.basename(MODEL_PERSISTENCE_PATH), os.path.basename(MODEL_DIGEST_PATH))
            return None
        model = joblib.load(MODEL_PERSISTENCE_PATH)
        if not hasattr(model, "predict_proba"):
            logger_model.warning("Cached model is not a classifier; retraining")
            return None
        logger_model.info(f"Loaded persisted model (corpus={ds_hash[:8]})")
        return model
    except Exception as exc:
        logger_model.warning(f"Could not load persisted model: {exc}")
        return None


def persist_model(model: Any, ds_hash: str) -> None:
    """Write the model and its sidecar digest, atomically."""
    try:
        os.makedirs(os.path.dirname(MODEL_PERSISTENCE_PATH), exist_ok=True)
        tmp = MODEL_PERSISTENCE_PATH + ".tmp"
        joblib.dump(model, tmp)
        with open(tmp, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        os.replace(tmp, MODEL_PERSISTENCE_PATH)
        with open(MODEL_DIGEST_PATH, "w", encoding="utf-8") as fh:
            json.dump({"sha256": digest, "dataset": ds_hash,
                       "sklearn": __import__("sklearn").__version__,
                       "trained_at": time.strftime("%Y-%m-%d %H:%M:%S")}, fh, indent=2)
        logger_model.info(f"Persisted model (corpus={ds_hash[:8]}, sha256={digest[:8]})")
    except Exception as exc:
        logger_model.error(f"Failed to persist model: {exc}")


def verify_metrics(ds: Dataset, tolerance: float = 0.02,
                   oof: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Re-measure the headline numbers and diff them against Data/metrics.json.

    `metrics.json` is what /api/v6/metrics serves and what the dashboard prints
    as this system's measured performance, and it is written only by --report.
    So the moment anything upstream of it moves - the feature set, the
    estimator, the calibration, the annunciator - the screen keeps showing
    numbers that describe code which no longer exists, and nothing notices.

    That is not hypothetical: between 2026-08-13 and 2026-08-19 the committed
    file described a 9-feature RandomForest while a 34-feature
    HistGradientBoosting was serving, and the only thing that eventually caught
    it was a regression test with a hard bound in it. This makes it a
    first-class check with a diff, so `--verify-metrics` can be run in seconds
    of thought and about a minute of compute before anyone quotes a figure.

    ONE leave-one-file-out pass is used for both the episode figures and the
    file-level ones, because the file-level accuracy at seed 42 is just the
    majority vote over the same out-of-fold predictions.

    A note on how fragile these figures are: `ds.groups` is a function of the
    order load_dataset walks the corpus, which is a function of the DECLARATION
    ORDER of CLASS_MAPPING. Row order changes what a bagging estimator draws, so
    adding one folder alias to that dict can move a published figure without
    touching the detector. The dataset fingerprint is reported here to make that
    visible.
    """
    report: Dict[str, Any] = {"path": os.path.join(DATA_ROOT, "metrics.json")}
    report["dataset_fingerprint"] = dataset_fingerprint(ds, "kalman", False)

    if not os.path.isfile(report["path"]):
        report["status"] = "absent"
        return report
    try:
        with open(report["path"], "r", encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError) as exc:
        report["status"] = "unreadable"
        report["error"] = str(exc)
        return report

    # `oof` is accepted so a caller that has already paid for a leave-one-file-out
    # pass (the test suite has) does not pay for a second one.
    if oof is None:
        oof = compute_oof(ds, 42)
    st = evaluate_stream(ds, 42, verbose=False, oof=oof)
    y_true = [int(lab) for lab in ds.labels]
    y_pred = [_file_vote(oof[ds.groups == i]) for i in range(ds.n_files)]
    measured = {
        "episode_level.sensitivity": st["sensitivity"],
        "episode_level.false_alarm_rate": st["false_alarm_rate"],
        "episode_level.alarms_per_hour": st["alarms_per_hour"],
        "random_forest.accuracy_mean": float(accuracy_score(y_true, y_pred)),
        "random_forest.macro_f1_mean": float(f1_score(y_true, y_pred, average="macro")),
        "dataset.files": float(ds.n_files),
        "dataset.frames": float(len(ds.X)),
        "dataset.features": float(ds.X.shape[1]),
    }

    def _dig(key: str) -> Optional[float]:
        node: Any = stored
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return float(node) if isinstance(node, (int, float)) else None

    drift: List[Dict[str, Any]] = []
    for key, now in measured.items():
        was = _dig(key)
        if was is None:
            drift.append({"key": key, "stored": None, "measured": now, "note": "absent"})
            continue
        scale = max(abs(was), 1e-9)
        if abs(now - was) / scale > tolerance:
            drift.append({"key": key, "stored": was, "measured": now,
                          "rel_change": (now - was) / scale})
    report["status"] = "stale" if drift else "current"
    report["generated"] = stored.get("generated")
    report["operating_point"] = stored.get("episode_level", {}).get("operating_point")
    report["drift"] = drift
    report["measured"] = measured
    return report


def print_metric_verification(rep: Dict[str, Any]) -> bool:
    print("\n" + "=" * 74)
    print("METRICS REPRODUCIBILITY - does Data/metrics.json describe this code?")
    print("=" * 74)
    print(f"  dataset fingerprint : {rep['dataset_fingerprint'][:16]}")
    if rep["status"] == "absent":
        print("  metrics.json        : NOT PRESENT")
        print("\n  Generate it:  python main.py --report --stream")
        return False
    if rep["status"] == "unreadable":
        print(f"  metrics.json        : UNREADABLE ({rep.get('error')})")
        return False
    print(f"  metrics.json written: {rep.get('generated')}")
    print(f"  operating point     : {rep.get('operating_point')}")
    if rep["status"] == "current":
        print(f"\n  OK - every headline figure reproduces within "
              f"{2:.0f}% of the file on disk.")
        return True
    print(f"\n  STALE - {len(rep['drift'])} figure(s) no longer reproduce:\n")
    print(f"    {'figure':<36}{'on disk':>12}{'measured':>12}{'change':>10}")
    for d in rep["drift"]:
        was = "absent" if d["stored"] is None else f"{d['stored']:.4f}"
        chg = "" if d.get("rel_change") is None else f"{d['rel_change']*100:+.1f}%"
        print(f"    {d['key']:<36}{was:>12}{d['measured']:>12.4f}{chg:>10}")
    print("\n  The dashboard serves this file verbatim, so those are the numbers")
    print("  currently on screen. Regenerate it, or find what moved:")
    print("      python main.py --report --stream")
    return False


def _channel_bar(delta: np.ndarray) -> str:
    """One character per pad, in PHYSICAL PAD ORDER. Deliberately not a grid.

    live_monitor.py used to render these 25 values as a 5x5 ASCII lattice with
    `idx = r * 5 + c`. The pads are not on a lattice - that is defect F5, the
    reason the surface is reconstructed by RBF over real coordinates - so the
    picture it drew put signal in the wrong place. A one-dimensional strip
    claims nothing about geometry; for direction, read the propagation line,
    which is computed from the true coordinates.
    """
    out = []
    for v in np.asarray(delta, dtype=float):
        if v <= -DELTA_THRESHOLD:
            out.append("V")          # past the lift gate
        elif v <= -NOISE_GATE_COUNTS:
            out.append("v")          # moving off baseline, lifting
        elif v >= DELTA_THRESHOLD:
            out.append("A")          # firm contact
        elif v >= NOISE_GATE_COUNTS:
            out.append("^")          # light contact
        else:
            out.append(".")
    return "".join(out)


def run_monitor(port: str, baudrate: int = 115200, permute: bool = False,
                model: Optional[Any] = None, use_gradient: bool = False,
                max_frames: int = 0) -> int:
    """Terminal live monitor over USB serial. Replaces live_monitor.py.

    That file was a fourth place where frames were turned into a reading, and it
    disagreed with the rest on three counts: it applied PAD_ORDER unconditionally
    while both sockets default to permute=0, it drew a fictitious 5x5 grid, and
    it printed `res["predicted_label"]`, a key LivePipeline has never returned -
    so `.get(..., "normal")` made every line read "(NORMAL)" including the ones
    headed LEVEL 3 CRITICAL. It also trained on `--calibration static` and then
    served through the Kalman baseline without the warning main.py prints for
    exactly that mismatch.

    This uses SerialFrameSource and LivePipeline, so it shares the disconnect
    handling, the idle timeout, the permutation flag and the classifier with
    every other path.
    """
    try:
        src = SerialFrameSource(port, baudrate, permute=permute)
    except Exception as exc:
        print(f"  cannot open {port}: {exc}")
        ports = list_serial_ports()
        print(f"  ports this machine enumerates: {[p['device'] for p in ports] or 'none'}")
        return 2

    pipe = LivePipeline(model, use_gradient)
    print(f"\n  monitoring {port} @ {baudrate} baud   "
          f"pad_order_applied={permute}   model={'loaded' if model else 'NONE (level 0 only)'}")
    print("  legend: V past -300 lift gate  v lifting  ^ contact  A firm contact  . quiet")
    print("  Ctrl-C to stop\n")
    n = 0
    try:
        for frame in src.frames():
            out = pipe.process(frame)
            n += 1
            pr = out["propagation"]
            print(f"  t={out['time_sec']:7.2f}s L{out['severity_level']} "
                  f"CPRI {out['cpri_percent']:5.1f}%  |{_channel_bar(out['deltas'])}|  "
                  f"min {min(out['deltas']):+7.1f}  {pr['description']}")
            if max_frames and n >= max_frames:
                break
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        src.close()
    print(f"  {n} frame(s)")
    return 0


def pick_port(start: int, host: str, tries: int = 15) -> int:
    """Return the first free port. Raises rather than handing uvicorn a busy one."""
    for p in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host if host != "0.0.0.0" else "", p))
                return p
            except OSError:
                continue
    raise RuntimeError(f"no free port in {start}..{start + tries - 1}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Self-extubation early warning master engine")
    ap.add_argument("--eval", action="store_true",
                    help="leave-one-file-out benchmark of the shipped estimator")
    ap.add_argument("--eval-temporal", action="store_true", help="grouped CV: RF vs BiLSTM (LOOP 2)")
    ap.add_argument("--plots", action="store_true", help="write research plots")
    ap.add_argument("--replay", metavar="REL_PATH", help="stream a CSV through the live pipeline")
    ap.add_argument("--calibration", choices=["static", "kalman"], default="kalman",
                    help="baseline scheme; kalman is the default and matches the live path")
    ap.add_argument("--gradient", action="store_true", help="add coordinate-based gradient features")
    ap.add_argument("--seeds", type=int, default=1, help="repeat CV with N seeds and report mean +/- sd")
    ap.add_argument("--cv", choices=["file", "session"], default="file",
                    help="hold out one file (default) or an entire sensor mounting")
    ap.add_argument("--audit", metavar="DIR",
                    help="check a freshly recorded folder against the device spec and exit")
    ap.add_argument("--report", action="store_true",
                    help="write Data/metrics.json and Data/METRICS.md")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; 0.0.0.0 exposes the dashboard to the network")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8081)),
                    help="port to bind server")
    ap.add_argument("--no-serve", action="store_true", help="train and exit without starting the server")
    ap.add_argument("--stamp", default="", help="timestamp string recorded in the report")
    ap.add_argument("--temporal-seeds", type=int, default=3,
                    help="number of CV seeds for the BiLSTM comparison (default 3)")
    ap.add_argument("--epochs-temporal", type=int, default=40, help="BiLSTM training epochs")
    ap.add_argument("--stream", action="store_true",
                    help="episode-level out-of-fold evaluation (sensitivity, alarms/hour)")
    ap.add_argument("--alarm-window", type=int, default=ALARM.window)
    ap.add_argument("--alarm-votes", type=int, default=ALARM.min_votes)
    ap.add_argument("--alarm-hold", type=int, default=ALARM.hold)
    # Accepted and ignored: nothing in this file has ever opened a browser.
    # Procfile, render.yaml and the .bat launchers pass it, so removing the flag
    # would break them with "unrecognized arguments" at startup.
    ap.add_argument("--no-browser", action="store_true",
                    help="accepted for launcher compatibility; this server never opens a browser")
    ap.add_argument("--allow-public-no-key", action="store_true",
                    help="serve a non-loopback --host with no PROJECT2_ACCESS_KEY "
                         "(refused by default; see the notice printed on refusal)")
    ap.add_argument("--monitor", metavar="PORT",
                    help="terminal live monitor over USB serial (replaces live_monitor.py)")
    ap.add_argument("--baud", type=int, default=115200, help="serial baud rate for --monitor")
    ap.add_argument("--permute", action="store_true",
                    help="apply PAD_ORDER to incoming Signal-* frames (--monitor); "
                         "off by default, matching the WebSocket sources")
    ap.add_argument("--monitor-frames", type=int, default=0,
                    help="stop --monitor after N frames (0 = run until Ctrl-C)")
    ap.add_argument("--verify-metrics", action="store_true",
                    help="re-measure the headline figures and diff them against "
                         "Data/metrics.json, which is what the dashboard serves")
    ap.add_argument("--verify-pads", nargs="?", const="Press/1_by_1.csv", metavar="REL_PATH",
                    help="check the Sensor-N == physical pad N assumption (A9) against a "
                         "1-by-1 press sweep and exit; defaults to Press/1_by_1.csv")
    args = ap.parse_args(argv)

    if args.seeds < 1:
        ap.error(f"--seeds must be >= 1 (got {args.seeds})")
    if not 1 <= args.alarm_votes <= args.alarm_window:
        ap.error(f"--alarm-votes must be between 1 and --alarm-window ({args.alarm_window})")
    ALARM.window, ALARM.min_votes, ALARM.hold = (
        args.alarm_window, args.alarm_votes, args.alarm_hold)
    ALARM.validate()
    if args.epochs_temporal < 1:
        ap.error("--epochs-temporal must be >= 1")

    # A13c. A printed warning is not an access control.
    #
    # Dockerfile, Procfile and render.yaml all start this with --host 0.0.0.0 and
    # none of them set PROJECT2_ACCESS_KEY, so the hosted instance handed every
    # recording under Data/, an upload endpoint and write access to the medical
    # audit trail to anyone who had the URL - while keep_alive.yml pinged it every
    # 10 minutes to make sure it stayed awake. share_public.py has always
    # generated a key by default and documented exactly why; the cloud path never
    # did. Binding a public interface without a key is a startup error now, not a
    # line of output that scrolls past.
    #
    # Checked BEFORE the dataset load and the ~30 s training run, so a
    # misconfigured container fails immediately with a readable reason instead of
    # crash-looping slowly. Batch modes never bind a socket, so they are exempt.
    serves_http = not (args.audit or args.verify_pads or args.verify_metrics
                       or args.monitor or args.eval or args.plots
                       or args.report or args.eval_temporal or args.stream
                       or args.replay or args.no_serve)
    if (serves_http and args.host not in ("127.0.0.1", "localhost", "::1")
            and not os.environ.get("PROJECT2_ACCESS_KEY", "").strip()):
        if args.allow_public_no_key:
            print(f"\n  WARNING: --allow-public-no-key was passed, so {args.host} will be "
                  f"served with NO authentication. Every recording under Data/, the upload "
                  f"endpoint and the audit-trail write endpoint are open to anyone who can "
                  f"reach this port.")
        else:
            print(f"\n  REFUSING TO START: --host {args.host} exposes this server beyond "
                  f"loopback and PROJECT2_ACCESS_KEY is not set.\n\n"
                  f"  The API serves every recording under Data/, accepts CSV uploads, and "
                  f"accepts writes to the extubation audit trail.\n\n"
                  f"  Set a key:         PROJECT2_ACCESS_KEY=$(python -c "
                  f"\"import secrets;print(secrets.token_urlsafe(24))\")\n"
                  f"  Demo locally:      python main.py             (binds 127.0.0.1)\n"
                  f"  Share a tunnel:    python share_public.py     (generates a key)\n"
                  f"  Deliberately open: add --allow-public-no-key\n")
            return 2

    if args.audit:
        return 0 if print_audit(audit_folder(args.audit)) else 2

    if args.verify_pads:
        try:
            return 0 if print_pad_verification(verify_pad_order(args.verify_pads)) else 2
        except (CsvProblem, ValueError) as exc:
            print(f"  cannot verify pad order: {exc}")
            return 2

    print("Loading dataset ...")
    ds = load_dataset(args.calibration, args.gradient)
    if ds is None:
        print(f"No dataset found under {DATA_ROOT}")
        return 1
    print(f"  {ds.n_files} files, {len(ds.X)} frames, {ds.X.shape[1]} features "
          f"(calibration={args.calibration}, gradient={args.gradient})")
    print(f"  sessions: {ds.n_sessions} ({', '.join(ds.session_names)})")
    if ds.n_sessions < 2 and args.cv == "session":
        print("  ERROR: --cv session needs recordings under Data/S1, Data/S2, ...")
        return 2
    if ds.n_sessions < 2:
        print("  NOTE: single session - these figures cannot show generalisation "
              "to a new sensor mounting (see ACTION_PLAN.md P0-3)")

    if args.verify_metrics:
        return 0 if print_metric_verification(verify_metrics(ds)) else 2

    if args.monitor:
        # Trained the same way the live path serves - calibration=kalman is the
        # default, and a mismatch is warned about below exactly as --replay does.
        if args.calibration != "kalman":
            print("  WARNING: model trained with --calibration static but the live path "
                  "uses the Kalman baseline; the feature distributions differ.")
        return run_monitor(args.monitor, args.baud, args.permute,
                           _new_rf(42).fit(ds.X, ds.y), args.gradient, args.monitor_frames)

    if args.eval or args.plots or args.report or args.eval_temporal or args.stream:
        temporal = None
        shared_oof = (compute_oof(ds, 42) if (args.stream or args.report) else None)
        stream = (evaluate_stream(ds, verbose=True, oof=shared_oof)
                  if (args.stream or args.report) else None)
        if args.eval_temporal:
            print(f"\nLOOP 2 - temporal sequence model, {args.temporal_seeds} CV seed(s)")
            temporal = evaluate_temporal_multi(
                ds, seeds=list(range(args.temporal_seeds)), epochs=args.epochs_temporal)
            if temporal:
                print_temporal_report(temporal)

        res = None
        if args.eval or args.plots or args.report:
            seeds = list(range(42, 42 + args.seeds))
            res = evaluate_rf(ds, seeds, cv=args.cv)
            print_rf_report(ds, res)
            print(f"  false-alarm rate on normal files: "
                  f"{false_alarm_rate(res['y_true'], res['y_pred'])*100:.1f}%")
            if args.plots:
                model = _new_rf(42).fit(ds.X, ds.y)
                generate_plots(ds, res, model)
        if args.report:
            assert res is not None
            jp, mp = write_report(ds, res, temporal, args.stamp or "unstamped", stream)
            print(f"  metrics -> {jp}")
            print(f"  metrics -> {mp}")
        # batch modes: report and exit.
        return 0

    if args.replay:
        try:
            probe = ReplayFrameSource(args.replay, realtime=False)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"  cannot replay {args.replay!r}: {exc}")
            print("  available recordings:")
            for f in ds.files[:10]:
                print(f"    {f}")
            if len(ds.files) > 10:
                print(f"    ... and {len(ds.files) - 10} more")
            return 2
        model = _new_rf(42).fit(ds.X, ds.y)
        src = probe
        pipe = LivePipeline(model, args.gradient, fuse_imu=True)
        if args.calibration != "kalman":
            print("  WARNING: model trained with --calibration static but the live path "
                  "uses the Kalman baseline; the feature distributions differ. "
                  "Use --calibration kalman to keep training and serving matched.")
        print(f"\nReplaying {args.replay}")
        for frame in src.frames():
            out = pipe.process(frame)
            pr = out["propagation"]
            print(f"  t={out['time_sec']:6.2f}s  L{out['severity_level']}  "
                  f"CPRI {out['cpri_percent']:5.1f}%  "
                  f"lift {pr['n_lifting_pads']:2d} pads  {pr['description']}")
        return 0

    ds_hash = dataset_fingerprint(ds, args.calibration, args.gradient)
    model = load_persisted_model(ds_hash)

    if model is None:
        logger_model.info("Training global model on full dataset...")
        model = _new_rf(42).fit(ds.X, ds.y)
        persist_model(model, ds_hash)

    holder: Dict[str, Any] = {"model": model, "use_gradient": args.gradient,
                              "calibration": args.calibration}
    logger_model.info(f"Model active on {len(ds.X)} frames / {ds.n_files} files")

    if args.no_serve:
        return 0

    app = create_app(holder)
    port = pick_port(args.port, args.host)
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"\nDashboard: http://{shown}:{port}")
    import uvicorn
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
