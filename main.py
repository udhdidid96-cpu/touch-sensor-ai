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
import datetime
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
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import (TYPE_CHECKING, Any, Callable, Dict, Iterable, Iterator, List, Literal, Optional,
                    Protocol, Sequence, Set, TextIO, Tuple, TypeGuard)

import joblib
import numpy as np
import pandas as pd
import sklearn.metrics
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import RBFInterpolator
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, auc, confusion_matrix, f1_score, roc_curve
from sklearn.model_selection import LeaveOneGroupOut, StratifiedGroupKFold

if TYPE_CHECKING:
    import torch
    from matplotlib.image import AxesImage


def _console_utf8(stream: TextIO) -> None:
    """Write UTF-8 to the console, replacing what it cannot show, instead of
    raising on a Windows code page."""
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8", errors="replace")


_console_utf8(sys.stdout)
_console_utf8(sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger_loader = logging.getLogger("project2.loader")
logger_model = logging.getLogger("project2.model")
logger_api = logging.getLogger("project2.api")
logger_serial = logging.getLogger("project2.serial")

EVENT_LOG_LOCK = threading.Lock()

AUDIT_GENESIS_HASH = "0" * 64
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


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_CUSTOM_UPLOADS = 50

AUTH_WINDOW_S = 60.0
AUTH_MAX_FAILURES = 10
AUTH_TABLE_MAX_IPS = 10_000

WARD_BED_SLOTS = 8

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.realpath(os.path.join(PROJECT_DIR, "Data"))
RESEARCH_PLOTS_DIR = os.path.join(DATA_ROOT, "research_plots")
WEB_DIR = os.path.join(PROJECT_DIR, "web")
MODEL_PERSISTENCE_PATH = os.path.join(DATA_ROOT, "trained_model.joblib")
MODEL_DIGEST_PATH = MODEL_PERSISTENCE_PATH + ".sha256.json"

BASELINE_COUNTS = 28000.0
COUNTS_PER_PF = 59.85
NOMINAL_BASELINE_PF = 30.0


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


SAMPLE_PERIOD_S = 0.560
DELTA_THRESHOLD = 300.0

N_PADS = 25
N_CLASSES = 4

PHYSICAL_PAD_COORDS: Dict[int, Tuple[float, float]] = {
    1: (57.0, 90.0),     2: (73.0, 78.0),     3: (58.0, 78.0),     4: (79.0, 64.0),     5: (65.0, 64.0),
    6: (80.0, 50.0),     7: (65.0, 50.0),     8: (80.0, 36.0),     9: (65.0, 36.0),     10: (74.0, 24.0),
    11: (58.0, 22.0),     12: (50.0, 64.0),     13: (50.0, 50.0),     14: (50.0, 35.0),     15: (41.0, 90.0),
    16: (40.0, 78.0),     17: (26.0, 78.0),     18: (35.0, 64.0),     19: (21.0, 64.0),     20: (35.0, 50.0),
    21: (20.0, 50.0),     22: (35.0, 36.0),     23: (20.0, 36.0),     24: (40.0, 22.0),     25: (25.0, 24.0),
}

PAD_TO_SIGNAL: Tuple[int, ...] = (
    20, 21, 19, 22, 18, 23, 17, 24, 16, 25, 15, 14, 13, 12, 6,
    7, 5, 8, 4, 9, 3, 10, 2, 11, 1,
)
PAD_ORDER: np.ndarray = np.array([s - 1 for s in PAD_TO_SIGNAL], dtype=int)

PAD_XY: NDArray[np.float64] = np.array([PHYSICAL_PAD_COORDS[i] for i in range(1, N_PADS + 1)], dtype=float)

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

STATUS_TEXT_MAP: Dict[int, str] = {
    0: "Normal - baseline (ปกติ)",
    1: "Contact - hand press or touch (สัมผัส/กดทับ)",
    2: "Warning - dressing peeling or partial pull (เริ่มลอก/ดึงบางส่วน)",
    3: "Critical - full detachment (หลุดทั้งแผ่น)",
}

MIN_FRAMES_PER_FILE = 5
KALMAN_WARMUP = 5

NOISE_GATE_COUNTS = 60.0
LIFT_GATE_COUNTS = -300.0

JITTER_ACTIVATE_COUNTS = 44.0
JITTER_TAPS = 3
JITTER_WINDOW_FRAMES = 30

QUIESCENT_RECOVERY_SECONDS = 3.0
QUIESCENT_RECOVERY_SD = 15.0
QUIESCENT_P_GROWTH = 1.6
QUIESCENT_P_CAP = 4.0

SEED_CHANNEL_OUTLIER_COUNTS = 575.0
SEED_RESTING_SHAPE: NDArray[np.float64] = np.array([
    27955.4, 27913.2, 27938.0, 28208.8, 28156.2, 27769.6, 28193.4, 28196.4,
    28114.6, 27705.2, 27993.8, 27896.8, 28414.4, 27911.4, 27882.0, 27806.4,
    27493.2, 28206.2, 28228.2, 28202.0, 28457.6, 28381.2, 28156.6, 27861.2,
    27521.6], dtype=float)

PEEL_MIN_PADS = 3
PEEL_MEAN_GATE = -150.0
PEEL_PERSIST_FRAMES = 3


@dataclass
class AlarmConfig:
    """Annunciator operating point.

    A dataclass rather than three module-level constants: main() rebound
    uppercase names through `global`, which every type checker flags as
    redefining a constant, and which left the effective operating point
    invisible to anything importing this module instead of running it.
    """

    window: int = 7
    min_votes: int = 6
    hold: int = 9

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

    q: float = 0.05
    r: float = 40.0
    gate: float = 120.0
    warmup: int = KALMAN_WARMUP

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

        valid_mask = np.isfinite(raw_b) & (raw_b >= 10000.0) & (raw_b <= 45000.0)
        if not np.all(valid_mask):
            fallback = float(np.median(raw_b[valid_mask])) if np.any(valid_mask) else BASELINE_COUNTS
            raw_b = np.where(valid_mask, raw_b, fallback)
        self.b = raw_b.astype(float)

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

        p_pred = self.p + self.q
        innovation = z - self.b

        if not np.isfinite(innovation).all():
            return z - self.b

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
        kal = KalmanBaseline().seed(arr)
        rows: List[np.ndarray] = []
        for row in arr:
            delta = kal.step(row)
            c0 = kal.b if kal.b is not None else np.full(arr.shape[1], BASELINE_COUNTS, dtype=float)
            safe_c0 = np.where(c0 > 1000.0, c0, BASELINE_COUNTS)
            rows.append(compute_fractional_deltas(delta, safe_c0) * BASELINE_COUNTS)
        return np.vstack(rows)
    return static_baseline(arr) - BASELINE_COUNTS


class PatchSpatialField:
    """Thin-plate-spline reconstruction over the true pad coordinates.

    FIX F1: v5.0 built the grid with meshgrid(x[60], y[80]) -> shape (80, 60)
    and then reshaped the result to (60, 80). Element count matched, so numpy
    stayed silent and the rendered patch came out transposed - a hotspot on the
    left edge appeared on the right. Rows are now y, columns are x, explicitly.
    """

    def __init__(self, n_rows: int = 80, n_cols: int = 60, smoothing: float = 1e-2) -> None:
        self.n_rows = n_rows
        self.n_cols = n_cols
        self.smoothing = smoothing
        self.points = PAD_XY
        gx = np.linspace(10.0, 90.0, n_cols)
        gy = np.linspace(10.0, 95.0, n_rows)
        grid_x, grid_y = np.meshgrid(gx, gy)
        assert grid_x.shape == (n_rows, n_cols)
        self.grid_coords = np.column_stack([grid_x.ravel(), grid_y.ravel()])

        d = np.linalg.norm(self.points[:, None, :] - self.points[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        self.neighbours = np.argsort(d, axis=1)[:, :5]

    def interpolate(self, pad_values: ArrayLike) -> np.ndarray:
        """pad_values must already be in physical pad order. Returns (rows, cols)."""
        vals = np.asarray(pad_values, dtype=float)
        rbf = RBFInterpolator(self.points, vals, smoothing=self.smoothing, kernel="thin_plate_spline")
        return rbf(self.grid_coords).reshape(self.n_rows, self.n_cols)

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
            dv: NDArray[np.float64] = v[idx] - v[i]
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
        centroid = (self.points * w[:, None]).sum(axis=0)
        origin_pad = int(np.argmin(v)) + 1

        vec: NDArray[np.float64] = centroid - self.points[origin_pad - 1]
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

    @property
    def history(self) -> Tuple[int, ...]:
        """The raw levels in the current vote window, oldest first."""
        return tuple(self._history)

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

        supported = self._supported()
        if supported >= 2:
            self._held_level = supported
            self._held = self.hold
            self.level = supported
        elif self._held > 0:
            self._held -= 1
            self.level = self._held_level
        else:
            self._held_level = 0
            self.level = min(raw_level, 1)
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


SESSION_DIR_RE = __import__("re").compile(r"^S\d+$")
VACUUM_STATION_DIR = "data new vaccum"   # sic: the folder name on disk

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
            arr = df[SENSOR_COLS].to_numpy(dtype=float)
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
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: non-numeric value ({exc})")
        return None
    if arr is None:
        if strict:
            raise CsvProblem(f"{os.path.basename(path)}: missing the 25 sensor columns")
        return None

    if arr.size and not np.isfinite(arr).all():
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
    groups: np.ndarray
    sessions: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    session_names: List[str] = field(default_factory=list[str])
    files: List[str] = field(default_factory=list[str])
    labels: List[int] = field(default_factory=list[int])
    frames: List[np.ndarray] = field(default_factory=list[np.ndarray])
    skipped: List[Tuple[str, str]] = field(default_factory=list[Tuple[str, str]])
    unknown_folders: List[Tuple[str, int, str]] = field(default_factory=list[Tuple[str, int, str]])
    conventions: Dict[str, int] = field(default_factory=dict[str, int])
    min_raw_by_label: Dict[int, float] = field(default_factory=dict[int, float])

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
        if parts[0] == "Custom_Uploads":
            stray.append((rel, n_csv,
                          "dashboard uploads - reviewable via /api/v5/dataset, and "
                          "deliberately NOT training data (they carry no class label)"))
            continue
        if parts[0] == VACUUM_STATION_DIR:   # one note for the whole station, not one per class folder
            prev = next((i for i, x in enumerate(stray) if x[0] == VACUUM_STATION_DIR), None)
            if prev is not None:
                stray[prev] = (VACUUM_STATION_DIR, stray[prev][1] + n_csv, stray[prev][2])
                continue
            stray.append((VACUUM_STATION_DIR, n_csv,
                          "vacuum demo station - scored separately by "
                          "scripts/evaluate_vacuum_station.py, and deliberately NOT training "
                          "data: its labels are confounded with the attachment (CLAUDE.md). "
                          "Do not rename it to S1"))
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

    session_ids: List[np.ndarray] = []
    session_names: List[str] = []

    def _session_of(rel: str) -> int:
        head = rel.split("/")[0]
        name = head if SESSION_DIR_RE.match(head) else "S0"
        if name not in session_names:
            session_names.append(name)
        return session_names.index(name)

    known, unknown = scan_csv_dirs(DATA_ROOT)
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
            if raw is None or len(raw) < MIN_FRAMES_PER_FILE:
                skipped.append((rel, describe_csv_problem(fpath) or "unusable"))
                continue

            lab = int(meta["label"])
            min_raw[lab] = min(min_raw.get(lab, float("inf")), float(raw.min()))

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

    def _warn_stray() -> None:
        """Report unloaded CSVs, loudly for the ones that look like mistakes.

        Custom_Uploads/ is expected to be here and expected not to load, so it is
        listed as a note. Everything else in this bucket is probably a mis-typed
        folder name, which costs a whole recording session, so it keeps the
        banner. Splitting them stops the alarm firing every single run and
        training people to ignore it.
        """
        expected = [x for x in unknown if x[0].split("/")[0] in ("Custom_Uploads", VACUUM_STATION_DIR)]
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

        pos_deltas = d_row[d_row >= NOISE_GATE_COUNTS]
        n_pos = len(pos_deltas)
        max_pos = float(pos_deltas.max()) if n_pos > 0 else 0.0

        lift_deltas = d_row[d_row <= LIFT_GATE_COUNTS]
        n_lift = len(lift_deltas)
        max_lift = float(abs(lift_deltas.min())) if n_lift > 0 else 0.0

        pad_factor = min(1.0, n_pos / 10.0)
        int_factor = float(np.clip((max_pos - NOISE_GATE_COUNTS) / 1200.0, 0.0, 1.0))
        r_touch = 15.0 + 20.0 * pad_factor + 20.0 * int_factor

        lift_pad_factor = min(1.0, n_lift / 8.0)
        lift_depth_factor = float(np.clip((max_lift - abs(LIFT_GATE_COUNTS)) / 1500.0, 0.0, 1.0))
        r_peel = 60.0 + 15.0 * lift_pad_factor + 10.0 * lift_depth_factor

        pull_intensity = float(np.clip(np.max(np.abs(d_row)) / 2500.0, 0.0, 1.0))
        r_pull = 85.0 + 15.0 * pull_intensity

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

    proba[:, 0] = 1.0
    active = np.max(np.abs(d), axis=1) >= NOISE_GATE_COUNTS
    if model is not None and bool(active.any()):
        proba[active] = full_proba(model, extract_features(d[active], use_gradient))

    raw_level = proba.argmax(axis=1).astype(int)
    risk = cpri(proba, d)
    risk[~active] = 0.0
    return proba, raw_level, risk


class GroupSplitter(Protocol):
    """The call the cross-validation loops make on an sklearn group splitter.

    LeaveOneGroupOut.split() has no return annotation in the sklearn stubs, so
    the folds it yields would be untyped; this names them as (train, test)
    index arrays. Pyright checks LeaveOneGroupOut against it where assigned.
    """

    def split(self, X: np.ndarray, y: np.ndarray,
              groups: np.ndarray) -> Iterator[Tuple[np.ndarray, np.ndarray]]: ...


class _ClassificationReports(Protocol):
    """sklearn.metrics.classification_report, called the way this module calls it.

    The stubs give the function one return type for both output forms,
    `str | dict` with the dict untyped. Reports here are always text; the
    module is assigned to this below, so pyright still checks it.
    """

    def classification_report(self, y_true: Sequence[int], y_pred: Sequence[int], *,
                              labels: Sequence[int], target_names: Sequence[str],
                              zero_division: int) -> str | Dict[str, Any]: ...


_SKLEARN_METRICS: _ClassificationReports = sklearn.metrics
LEAVE_ONE_GROUP_OUT: GroupSplitter = LeaveOneGroupOut()


def new_rf(seed: int = 42) -> HistGradientBoostingClassifier:
    """THE production estimator. Named `new_rf` for call-site compatibility only.

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


def file_vote(frame_preds: np.ndarray) -> int:
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
        return 0
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
        logo = list(LEAVE_ONE_GROUP_OUT.split(ds.X, ds.y, groups=ds.sessions))
    else:
        logo = list(LEAVE_ONE_GROUP_OUT.split(ds.X, ds.y, groups=ds.groups))
    runs: List[Dict[str, Any]] = []
    oof_proba = np.zeros((len(ds.X), N_CLASSES), dtype=float)

    for si, seed in enumerate(seeds):
        clf = new_rf(seed)
        y_true: List[int] = []
        y_pred: List[int] = []
        for tr, te in logo:
            clf.fit(ds.X[tr], ds.y[tr])
            preds = clf.predict(ds.X[te])
            if si == 0:
                oof_proba[te] = full_proba(clf, ds.X[te])
            for f in np.unique(ds.groups[te]):
                m = ds.groups[te] == f
                y_true.append(int(ds.y[te][m][0]))
                y_pred.append(file_vote(preds[m]))
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
    present: List[int] = sorted(set(res["y_true"]) | set(res["y_pred"]))
    print(_SKLEARN_METRICS.classification_report(
        res["y_true"], res["y_pred"], labels=present,
        target_names=[CLASS_LABEL_NAMES[i] for i in present], zero_division=0))


WINDOW_FRAMES = 6
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
            xs.append(delta[s:s + WINDOW_FRAMES].T)
            ys.append(lab)
            gs.append(fi)
    return np.stack(xs).astype(np.float32), np.array(ys, dtype=np.int64), np.array(gs, dtype=int)


def _torch():
    try:
        return __import__("torch")
    except ImportError:
        return None


def make_temporal_model() -> type[torch.nn.Module]:
    """The network class. Call only once PyTorch is known to import."""
    from torch import nn

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

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h = self.conv(x)
            h = h.transpose(1, 2)
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

    file_label = np.array(ds.labels)
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)

    TemporalNet = make_temporal_model()
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

        rf = new_rf(seed)
        frame_tr = np.isin(ds.groups, np.unique(gw[tr]))
        frame_te_files = np.unique(gw[te])
        rf.fit(ds.X[frame_tr], ds.y[frame_tr])

        for f in frame_te_files:
            files_seen.append(int(f))
            file_true.append(int(file_label[f]))
            file_pred_nn.append(file_vote(win_pred[gw[te] == f]))
            m = ds.groups == f
            file_pred_rf.append(file_vote(rf.predict(ds.X[m])))

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
    accs: List[float] = []
    f1s: List[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(t), len(t))
        accs.append(float((t[idx] == p[idx]).mean()))
        f1s.append(float(f1_score(t[idx], p[idx], average="macro", zero_division=0)))
    return {"accuracy": (float(np.percentile(accs, 2.5)), float(np.percentile(accs, 97.5))),
            "macro_f1": (float(np.percentile(f1s, 2.5)), float(np.percentile(f1s, 97.5)))}


def compute_oof(ds: Dataset, seed: int = 42,
                served: Optional[List[np.ndarray]] = None,
                use_gradient: bool = False) -> np.ndarray:
    """Leave-one-file-out frame predictions.

    Split out so callers can share one pass: --report ran a full LOFO for the
    stream evaluation and another for every RF seed - six ~30 s passes per report.

    Pass a list as `served` to score the detector the server runs as well: each
    fold's model also streams its held-out recording through LivePipeline
    (replay_levels) and the annunciated levels are appended in file order. Same
    fit, so the served figure costs a replay, not a second pass.
    """
    clf = new_rf(seed)
    oof = np.zeros(len(ds.X), dtype=int)
    for tr, te in LEAVE_ONE_GROUP_OUT.split(ds.X, ds.y, groups=ds.groups):
        clf.fit(ds.X[tr], ds.y[tr])
        oof[te] = clf.predict(ds.X[te])
        if served is not None:
            fi = int(ds.groups[te[0]])
            if fi != len(served):
                raise RuntimeError("served levels must be collected in file order")
            raw = read_raw_csv(os.path.join(DATA_ROOT, ds.files[fi]))
            if raw is None:
                raise CsvProblem(f"{ds.files[fi]}: loaded for training, unreadable for replay")
            served.append(replay_levels(clf, raw, use_gradient))
    return oof


def replay_levels(model: Optional[Any], raw: np.ndarray,
                  use_gradient: bool = False) -> np.ndarray:
    """The level the server annunciates on every frame of `raw`.

    Streams the recording through LivePipeline, the object the websocket and
    --replay serve: Kalman seeded from frame 0, quiescent recovery, F10, the
    noise gate inside classify_deltas, then the debouncer. compute_oof() +
    evaluate_stream() exercise none of that - they score the model on the offline
    delta, every frame - so the report publishes this path next to it
    (docs/ML_ENHANCEMENT_PLAN.md, measured 2026-09-23).
    """
    pipe = LivePipeline(model, use_gradient)
    return np.asarray([int(pipe.process(row)["severity_level"])
                       for row in np.asarray(raw, dtype=float)], dtype=int)


def count_onsets(levels: np.ndarray) -> int:
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

    What it replays is the model's vote on the OFFLINE delta, every frame. Only
    the debouncer is the live one; for the whole served path see
    evaluate_served().
    """
    votes: np.ndarray = compute_oof(ds, seed) if oof is None else oof

    levels_by_file: List[np.ndarray] = []
    for fi in range(ds.n_files):
        deb = AlarmDebouncer()
        levels_by_file.append(np.array(
            [0 if k < KALMAN_WARMUP else deb.update(int(p))
             for k, p in enumerate(votes[ds.groups == fi])], dtype=int))
    out = _episode_figures(ds, levels_by_file)
    for fi, row in enumerate(out["per_file"]):
        row["file_vote"] = file_vote(votes[ds.groups == fi])
    out["seed"] = seed
    out["curve"] = operating_curve(ds, votes)
    if verbose:
        print_stream_report(out)
    return out


def _episode_figures(ds: Dataset, levels_by_file: Sequence[np.ndarray]) -> Dict[str, Any]:
    """Episode metrics from each recording's annunciated levels.

    ONE definition for both paths. The offline replay (evaluate_stream) and the
    served replay (evaluate_served) differ only in where the levels come from;
    computing sensitivity, false alarms and alarms/hour twice is how two
    headline figures for "the same" thing drift apart (see A7 in count_onsets).
    """
    if len(levels_by_file) != ds.n_files:
        raise ValueError(f"{len(levels_by_file)} level streams for {ds.n_files} recordings")
    per_file: List[Dict[str, Any]] = []
    for fi, label in enumerate(ds.labels):
        arr = np.asarray(levels_by_file[fi], dtype=int)
        hits = np.nonzero(arr >= 2)[0]
        per_file.append({
            "file": ds.files[fi], "label": label,
            "max_level": int(arr.max(initial=0)),
            "annunciated": bool(arr.max(initial=0) >= 2),
            "onsets": count_onsets(arr),
            "latency_s": float(hits[0] * SAMPLE_PERIOD_S) if hits.size else None,
            "frames": int(len(arr)),
        })

    normal = [r for r in per_file if r["label"] <= 1]
    anomaly = [r for r in per_file if r["label"] >= 2]
    fa_files = [r for r in normal if r["annunciated"]]
    missed = [r for r in anomaly if not r["annunciated"]]
    normal_hours = sum(r["frames"] for r in normal) * SAMPLE_PERIOD_S / 3600.0
    lat = [r["latency_s"] for r in anomaly if r["latency_s"] is not None]
    return {
        "per_file": per_file,
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
    }


def evaluate_served(ds: Dataset, served_levels: Sequence[np.ndarray],
                    verbose: bool = True) -> Dict[str, Any]:
    """Episode metrics for the detector the server runs, out of fold.

    `served_levels` comes from compute_oof(..., served=[...]): every recording
    streamed through LivePipeline by the model that never saw it. Measured on
    the round-1 corpus (docs/ML_ENHANCEMENT_PLAN.md section 9) this path and
    evaluate_stream() disagree - one more missed event and a later median
    alarm - because the served path seeds its baseline from frame 0 and never
    asks the model about a frame under the noise gate, while the offline path
    votes on every frame, sub-gate ones included. Both are published; neither
    is allowed to stand in for the other.
    """
    out = _episode_figures(ds, served_levels)
    if verbose:
        print_stream_report(out, "SERVED PATH (out-of-fold, every recording streamed "
                                 "through LivePipeline)")
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
                onsets += count_onsets(arr)
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


def print_stream_report(st: Dict[str, Any],
                        title: str = "EPISODE-LEVEL PERFORMANCE (out-of-fold, "
                                     "offline delta, through the live annunciator)") -> None:
    print("\n" + "=" * 70)
    print(title)
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

    def run(self, capacitive_risk: Iterable[float], imu: Sequence[IMUFrame]) -> np.ndarray:
        self._recent = []
        return np.array([self.step(float(r), imu[i] if i < len(imu) else None)["fused_risk"]
                         for i, r in enumerate(capacitive_risk)])


def lead_time_gain(risk_a: ArrayLike, risk_b: ArrayLike, threshold: float = 50.0,
                   period_s: float = SAMPLE_PERIOD_S) -> Optional[float]:
    """Seconds by which series b crosses `threshold` earlier than series a."""
    def first_cross(r: ArrayLike) -> Optional[int]:
        arr = np.asarray(r, dtype=float)
        hits = np.nonzero(arr >= threshold)[0]
        return int(hits[0]) if len(hits) else None

    a, b = first_cross(risk_a), first_cross(risk_b)
    if a is None or b is None:
        return None
    return round((a - b) * period_s, 3)


class FrameSource:
    """Common interface for anything that yields 25-channel frames."""

    name = "base"

    def frames(self) -> Iterator[np.ndarray]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialPort(Protocol):
    """The part of pyserial's Serial that SerialFrameSource uses."""

    def readline(self) -> bytes: ...
    def close(self) -> None: ...


class SerialFrameSource(FrameSource):
    """Read comma/whitespace separated 25-value lines from a USB COM port.

    The firmware emits Signal-1..25 in electrical order; frames are converted
    to physical pad order here so everything downstream shares one convention.
    """

    name = "serial"

    IDLE_TIMEOUT_S = 1.2
    EMPTY_READ_SLEEP_S = 0.02

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.2, permute: bool = True,
                 *, ser: Optional[SerialPort] = None) -> None:
        """Open `port` with pyserial, or read from `ser` when one is given.

        `ser` is a port that is already open - in practice a scripted test
        double, which is how the parser below is exercised without hardware.
        """
        self.port = port
        self.baudrate = baudrate
        self.permute = permute
        self._stop = threading.Event()
        if ser is not None:
            self._ser: SerialPort = ser
            return
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial streaming: pip install pyserial") from exc
        self._serial_mod = serial

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
                    break
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
            yield signals_to_pads(vals) if self.permute else vals

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

    permute = False

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
        from serial.tools import list_ports
    except ImportError:
        return []
    return [{"device": p.device, "description": p.description or "",
             "hwid": p.hwid or ""} for p in list_ports.comports()]


# --- Operator-console indicators (server side; the browser only renders them) ----------

ALARM_SIGNAL_STANDARD = ("IEC 60601-1-8 visual alarm-signal conventions (colour, flash rate). "
                         "Not assessed against IEC 60601-1-8 or IEC 62304.")

# Priority, colour and flash rate follow the alarm-indicator-light characteristics in
# IEC 60601-1-8: high = red, flashing 1.4-2.8 Hz; medium = yellow, flashing 0.4-0.8 Hz;
# low = cyan or yellow, constant. Duty cycle 20-60 % on. Level 1 (touch / press) is
# expected patient activity, so it is an information signal, not an alarm condition:
# making it an alarm would add to the burden the 7-of-6 vote window exists to keep down.
# Sounds (played by web/app.js siren()): info = one two-note chime when contact begins, never
# repeated; medium = 3-pulse beep every 5 s; high = 5-pulse buzzer every 2 s. "low" is not emitted.
ALARM_SIGNALS: Dict[str, Dict[str, Any]] = {
    "high":   {"colour": "red", "flash_hz": 2.0, "duty_cycle": 0.5, "sound": "high_pulse_buzzer"},
    "medium": {"colour": "yellow", "flash_hz": 0.6, "duty_cycle": 0.5, "sound": "medium_caution_beep"},
    "low":    {"colour": "cyan", "flash_hz": 0.0, "duty_cycle": 1.0, "sound": "none"},
    "info":   {"colour": None, "flash_hz": 0.0, "duty_cycle": 1.0, "sound": "tactile_contact_chime"},
    "none":   {"colour": None, "flash_hz": 0.0, "duty_cycle": 0.0, "sound": "none"},
}


def alarm_signal(level: int, disconnected: bool = False, warming: bool = False) -> Dict[str, Any]:
    """Map the debounced severity level onto an alarm-signal priority.

    Takes the level AlarmDebouncer already decided; it decides nothing about the
    patient itself. Loss of signal is a technical alarm condition: the patch is no
    longer being monitored, which during an extubation watch is not low priority.
    """
    if disconnected:
        priority, condition, text = "medium", "technical", "Sensor signal lost - monitoring interrupted"
    elif warming:
        priority, condition, text = "none", None, "Baseline calibrating - no alarm conditions evaluated"
    elif level >= 3:
        priority, condition, text = "high", "patient", "Full detachment pattern"
    elif level == 2:
        priority, condition, text = "medium", "patient", "Dressing peel or partial pull pattern"
    elif level == 1:
        priority, condition, text = "info", None, "Contact on the dressing - tactile alert chime"
    else:
        priority, condition, text = "none", None, "No alarm condition"
    return {"priority": priority, "condition": condition, "text": text,
            **ALARM_SIGNALS[priority], "reference": ALARM_SIGNAL_STANDARD}


DRIFT_RATE_WINDOW_FRAMES = 108  # 60 s at 560 ms


def signal_quality(baseline: Optional[np.ndarray], seed: Optional[np.ndarray],
                   jitter_counts: float, mean_drift_history: Sequence[float] = (),
                   disconnected: bool = False) -> Dict[str, Any]:
    """Per-pad baseline drift and a Contact Quality Index (CQI), from measured counts.

    drift      = Kalman baseline now minus the baseline it was seeded with, per pad.
    CQI        = 100 x geometric mean of three fractions, each in [0, 1]:
                 seated  - pads whose baseline sits inside ATTACHED_SEED_BAND (the
                           bench-measured attached-at-rest range);
                 quiet   - 1 - frame-to-frame jitter / NOISE_GATE_COUNTS;
                 stable  - pads whose |drift| is within NOISE_GATE_COUNTS.
    A geometric mean, so any one failing component pulls the index down.

    This is an engineering indicator of whether the numbers on screen are worth
    reading. It has not been validated against any clinical outcome, and the
    seated band comes from the round-1 bench, not from skin.
    """
    if disconnected or baseline is None or seed is None:
        return {"cqi": 0.0 if disconnected else None, "components": None, "drift": None,
                "note": "no signal" if disconnected else "baseline not seeded"}
    b = np.asarray(baseline, dtype=float)
    drift = b - np.asarray(seed, dtype=float)
    lo, hi = ATTACHED_SEED_BAND
    seated = float(np.mean((b >= lo) & (b <= hi)))
    quiet = float(np.clip(1.0 - float(jitter_counts) / NOISE_GATE_COUNTS, 0.0, 1.0))
    stable = float(np.mean(np.abs(drift) <= NOISE_GATE_COUNTS))
    cqi = 100.0 * float(np.cbrt(seated * quiet * stable))
    hist = [float(x) for x in mean_drift_history]
    rate = None
    if len(hist) >= 2:
        rate = (hist[-1] - hist[0]) / ((len(hist) - 1) * SAMPLE_PERIOD_S / 60.0)
    worst = int(np.argmax(np.abs(drift)))
    return {
        "cqi": round(cqi, 1),
        "components": {"seated": round(seated, 3), "quiet": round(quiet, 3), "stable": round(stable, 3)},
        "drift": {
            "per_pad": [round(float(v), 1) for v in drift],
            "mean": round(float(drift.mean()), 1),
            "max_abs": round(float(np.abs(drift[worst])), 1),
            "max_abs_pad": worst + 1,
            "n_over_noise_gate": int(np.sum(np.abs(drift) > NOISE_GATE_COUNTS)),
            "rate_counts_per_min": None if rate is None else round(rate, 1),
            "noise_gate": NOISE_GATE_COUNTS,
        },
        "note": "engineering indicator; not clinically validated",
    }


class LivePipeline:
    """Calibrate -> classify -> summarise, one frame at a time.

    Uses the Kalman baseline (LOOP 4) rather than a frozen 5-frame offset, so a
    session that drifts with sweat over an hour stays correctly zeroed.
    """

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
        self.topography: Optional[Dict[str, Any]] = None
        self.adaptive_lift_gates: Optional[np.ndarray] = None
        self._quiescent_frames = max(2, int(math.ceil(
            QUIESCENT_RECOVERY_SECONDS / SAMPLE_PERIOD_S)))
        self._raw_history: collections.deque[np.ndarray] = collections.deque(
            maxlen=self._quiescent_frames)
        self._delta_history: collections.deque[np.ndarray] = collections.deque(maxlen=JITTER_TAPS)
        self._jitter_window: collections.deque[float] = collections.deque(
            maxlen=JITTER_WINDOW_FRAMES)
        self.quiescent_recovery: Dict[str, Any] = {
            "active_pads": [], "note": "not engaged"}
        self._quiescent_latched = np.zeros(N_PADS, dtype=bool)
        self.jitter_active = False
        self.jitter_noise_counts = 0.0
        self._seed_baseline: Optional[np.ndarray] = None
        self._mean_drift: collections.deque[float] = collections.deque(maxlen=DRIFT_RATE_WINDOW_FRAMES)
        self._rest_jitter: collections.deque[float] = collections.deque(maxlen=JITTER_WINDOW_FRAMES)

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
        self._seed_baseline = None
        self._mean_drift.clear()
        self._rest_jitter.clear()

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
            self._release_quiescent()
            return

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
        if not np.isfinite(pad_frame).all() or np.any(pad_frame < 0.0) or np.all(pad_frame <= 0.0):
            disconnected = True
            is_cdc = self.cdc_mode
            working_frame = pad_frame
        else:
            is_cdc = self.cdc_mode or (np.all(pad_frame < 500.0) and np.any(pad_frame > 0.05))
            if is_cdc:
                disconnected = np.all(pad_frame < 1.0) or np.all(pad_frame > 500.0) or np.all(pad_frame == 0.0)
                if not disconnected:
                    if self._cdc_initial_baseline is None:
                        self._cdc_initial_baseline = pad_frame.copy()
                    working_frame = convert_absolute_cdc_to_counts(pad_frame, baseline_c_pf=self._cdc_initial_baseline) + BASELINE_COUNTS
                    surge_mask = working_frame > 50000.0
                    if np.any(surge_mask):
                        repl = self.kalman.b[surge_mask] if self.kalman.b is not None else BASELINE_COUNTS
                        working_frame[surge_mask] = repl
                else:
                    working_frame = pad_frame
            else:
                disconnected = np.all(pad_frame < 3000.0) or np.all(pad_frame > 50000.0) or np.all(pad_frame == 0.0)
                if not disconnected:
                    working_frame = pad_frame.copy()
                    surge_mask = working_frame > 50000.0
                    if np.any(surge_mask):
                        repl = self.kalman.b[surge_mask] if self.kalman.b is not None else BASELINE_COUNTS
                        working_frame[surge_mask] = repl
                else:
                    working_frame = pad_frame

        if disconnected:
            idx = self.index
            self.index += 1
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
                "alarm_signal": alarm_signal(held, disconnected=True),
                "signal_quality": signal_quality(None, None, 0.0, disconnected=True),
            }

        reconnected = (getattr(self, "_disconnected_run", 0) >= self.RESEED_AFTER_LOST_FRAMES)
        if not self._seeded or reconnected:
            self.kalman.seed(working_frame[None, :])
            self._seeded = True
            self._seed_baseline = None if self.kalman.b is None else self.kalman.b.copy()
            self._mean_drift.clear()
            self.seed_plausibility = seed_plausibility(
                self.kalman.b if self.kalman.b is not None else working_frame)
        self._disconnected_flag = False
        self._disconnected_run = 0

        delta = self.kalman.step(working_frame)

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

        if self.kalman.b is not None and (self.topography is None or self.index == self.warmup_frames):
            if is_cdc and self._cdc_initial_baseline is not None:
                self.topography = analyze_surface_topography(self._cdc_initial_baseline, is_cdc_pf=True)
            else:
                self.topography = analyze_surface_topography(self.kalman.b, is_cdc_pf=False)

            counts_topo = analyze_surface_topography(self.kalman.b, is_cdc_pf=False)
            if counts_topo.get("valid", False):
                self.adaptive_lift_gates = np.array(counts_topo["adaptive_lift_gates"], dtype=float)
                self.peel.set_adaptive_gates(self.adaptive_lift_gates)

        c0 = self.kalman.b if self.kalman.b is not None else np.full(N_PADS, BASELINE_COUNTS, dtype=float)
        safe_c0 = np.where(c0 > 1000.0, c0, BASELINE_COUNTS)
        norm_delta = compute_fractional_deltas(delta, safe_c0) * BASELINE_COUNTS

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
        out["alarm_signal"] = alarm_signal(level, warming=warming)
        if self.kalman.b is not None and self._seed_baseline is not None:
            self._mean_drift.append(float((self.kalman.b - self._seed_baseline).mean()))
        # Noise is sampled only on frames the model called baseline, so a real event
        # moving the deltas does not read as poor contact.
        if not warming and raw_level == 0 and len(self._delta_history) >= 2:
            self._rest_jitter.append(float(np.median(np.abs(self._delta_history[-1] - self._delta_history[-2]))))
        out["signal_quality"] = signal_quality(
            self.kalman.b, self._seed_baseline,
            float(np.median(self._rest_jitter)) if self._rest_jitter else 0.0, self._mean_drift)
        if self.topography is not None:
            out["topography"] = self.topography
        if fused is not None:
            out["fusion"] = {k: round(float(v), 4) for k, v in fused.items()}
        self.index += 1
        return out


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

    mad = float(np.median(np.abs(arr - median_cap)))
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

    tenting_threshold = med - 1.2 * iqr
    flush_threshold = med - 0.4 * iqr

    tenting_pads = [int(i + 1) for i, val in enumerate(arr) if val <= tenting_threshold]
    flush_pads = [int(i + 1) for i, val in enumerate(arr) if val >= flush_threshold]
    contoured_pads = [
        int(i + 1) for i, val in enumerate(arr)
        if tenting_threshold < val < flush_threshold
    ]

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


try:
    from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    _fastapi_error: Optional[str] = None
except ImportError as _fastapi_exc:
    _fastapi_error = str(_fastapi_exc)
    if TYPE_CHECKING:
        raise


def _is_json_object(value: object) -> TypeGuard[Dict[str, Any]]:
    """True for a decoded JSON object, typed as one (isinstance alone leaves
    the keys and values unknown to the type checker)."""
    return isinstance(value, dict)


def _is_json_array(value: object) -> TypeGuard[List[Any]]:
    """True for a decoded JSON array, typed as one."""
    return isinstance(value, list)


def _key_ok(supplied: str, expected: str) -> bool:
    """Constant-time secret comparison that tolerates any input.

    hmac.compare_digest refuses non-ASCII *str* with a TypeError, so a request
    carrying ?key=e-acute used to escape the gate as an unhandled 500 rather
    than a 401 (B2). Encoding both sides first makes every input comparable.
    """
    return hmac.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                               expected.encode("utf-8", "surrogatepass"))


LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
LINE_BOT_INFO_URL = "https://api.line.me/v2/bot/info"   # proves a token without spending a message
LINE_MESSAGE_MAX = 5000       # LINE text message limit, characters
LINE_TIMEOUT_S = 3.5          # per attempt
LINE_ATTEMPTS = 3             # 5xx / 429 / network errors retry after 0.5 s, then 1 s
LINE_BACKOFF_S = 0.5
LINE_WARN_COOLDOWN_S = 60.0   # a Level 2 push waits this long after any push for the bed
LINE_TOUCH_COOLDOWN_S = 60.0  # a Level 1 notice waits this long per bed
LINE_CRIT_REPEAT_S = 30.0     # Level 3 repeats this often while it persists
LINE_CLEAR_AFTER_S = 15.0     # Level 0 held this long after an alarm sends one all-clear
LINE_AUDIT_FILE = "line_alert_audit.jsonl"
LINE_AUDIT_LOCK = threading.Lock()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a public webhook answering 302 -> 169.254.169.254 would
    otherwise carry the request past validate_webhook_url. A 3xx surfaces as HTTPError."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


PUSH_OPENER = urllib.request.build_opener(NoRedirect)


def validate_webhook_url(url: str) -> Optional[str]:
    """None if `url` is an HTTPS URL whose host resolves only to public addresses,
    else the reason it is refused. Blocks loopback, private, link-local and other
    non-global targets so /api/v6/notify/line cannot reach the server's own network.
    """
    import ipaddress
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return "must be an https:// URL with a host"
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return "host does not resolve"
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            return "host resolves to a non-public address"
    return None


def _iso_now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _http_once(req: urllib.request.Request) -> Dict[str, Any]:
    """One outbound call through the no-redirect opener: ok, HTTP code, error text."""
    try:
        with PUSH_OPENER.open(req, timeout=LINE_TIMEOUT_S) as resp:
            return {"ok": True, "code": resp.getcode()}
    except urllib.error.HTTPError as err:
        return {"ok": False, "code": err.code,
                "error": err.read().decode("utf-8", errors="replace")[:300] or str(err.reason)}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def _append_line_audit(record: Dict[str, Any]) -> None:
    """Append one delivery attempt to Data/line_alert_audit.jsonl.

    Hash-chained with audit_event_hash like the event trail, so a deleted or edited
    line breaks verify_audit_chain. Kept apart from extubation_events_audit.json so
    pushes never count as clinical events in the shift report. A failed write is
    logged, not raised: losing an audit line must not cost the alert itself.
    ponytail: reads the whole file for the last hash; keep the tail hash in memory
    if this log ever grows past a few MB.
    """
    path = os.path.join(DATA_ROOT, LINE_AUDIT_FILE)
    with LINE_AUDIT_LOCK:
        prev = AUDIT_GENESIS_HASH
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            if lines:
                prev = str(json.loads(lines[-1])["hash"])
        except (OSError, ValueError, KeyError):
            pass
        record["prev_hash"] = prev
        record["hash"] = audit_event_hash(record, prev)
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger_api.error(f"LINE audit write failed: {exc}")


# kind -> (headline EN/JA/TH, action directive EN/JA/TH)
_LINE_KIND_TEXT: Dict[str, Tuple[str, str]] = {
    "critical": ("🚨 LEVEL 3 CRITICAL - tube pull / detachment\n"
                 "レベル3 緊急 - チューブ抜去・剥離\n"
                 "ระดับ 3 วิกฤต - ท่อถูกดึง / แผ่นหลุด",
                 "Immediate bedside verification required / 直ちにベッドサイドで確認 / ตรวจสอบที่ข้างเตียงทันที"),
    "warning": ("⚠️ LEVEL 2 WARNING - dressing peeling\n"
                "レベル2 警告 - ドレッシング剥がれ\n"
                "ระดับ 2 เตือน - แผ่นปิดเริ่มลอก",
                "Check the dressing at the bedside / ベッドサイドでドレッシングを確認 / ตรวจแผ่นปิดที่ข้างเตียง"),
    "touch": ("ℹ️ LEVEL 1 NOTICE - touch / press detected\n"
              "レベル1 通知 - 接触検知\n"
              "ระดับ 1 แจ้งเตือน - ตรวจพบการสัมผัสแผ่นปิด",
              "Incidental touch or routine care / 偶発的な接触またはケア / การสัมผัสจากการดูแลตามปกติ"),
    "cleared": ("✅ ALARM CLEARED - patient restabilized\n"
                "アラーム解除 - 安定\n"
                "ยกเลิกการเตือน - กลับสู่ภาวะปกติ",
                "None: normal for 15 s / 対応不要（15秒間正常） / ไม่ต้องดำเนินการ ปกติต่อเนื่อง 15 วินาที"),
}


def format_line_alert(fields: Dict[str, Any]) -> str:
    """The text a phone shows. Built only from `fields` (bed, kind, metrics), which
    the callers assemble themselves, so no patient identity can reach it."""
    headline, action = _LINE_KIND_TEXT[str(fields["kind"])]
    now = datetime.datetime.now().astimezone()
    lines = [headline, "", f"Bed / ベッド / เตียง: {fields['bed']}"]
    if fields.get("cpri_percent") is not None:
        lines.append(f"CPRI: {float(fields['cpri_percent']):.1f}%")
    if fields.get("max_delta") is not None:
        lines.append(f"Deepest pad delta / 最大変化 / ค่าลดลงสูงสุด: {float(fields['max_delta']):+.0f} counts")
    if fields.get("lifting_pads") is not None:
        lines.append(f"Lifting pads / 浮きパッド / แผ่นที่ยก: {int(fields['lifting_pads'])}/{N_PADS}")
    lines += [f"Time / 時刻 / เวลา: {now:%Y-%m-%d %H:%M:%S} ({now.isoformat(timespec='seconds')})",
              f"Action / 対応 / การดำเนินการ: {action}",
              "Research prototype - not been assessed against IEC 62304"]
    return "\n".join(lines)[:LINE_MESSAGE_MAX]


class LineAlerter:
    """Server-side LINE dispatch for the live sources (USB serial, browser serial).

    One per process, so the headless --monitor loop, the WebSocket loop and the
    dashboard's /api/v6/notify/line share one escalation state per bed: whichever
    handler sees an event first sends it, and the others are told it is already
    out. That shared state is the idempotency lock. Delivery runs on one worker
    thread, so a slow or dead gateway costs the frame loop a dict update, never a
    frame. The token comes from LINE_CHANNEL_ACCESS_TOKEN or the dashboard and is
    held in memory only.
    """

    def __init__(self, token: str = "", bed: str = "Bed 01") -> None:
        self.lock = threading.Lock()
        self.token, self.webhook_url, self.bed, self.min_level = token, "", bed, 2
        self.enabled = bool(token)
        self.token_source = "env" if token else ""
        self.beds: Dict[str, Dict[str, Any]] = {}
        self.last: Dict[str, Any] = {}
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="p2-line")

    def decide(self, bed: str, level: int, now: float) -> Optional[str]:
        """'critical' | 'warning' | 'cleared' | None for one frame of `bed`.

        L0/L1 never push. L2 pushes unless any push for the bed went out in the last
        LINE_WARN_COOLDOWN_S. L3 pushes at once when the open alarm is below L3 and
        then every LINE_CRIT_REPEAT_S. After a push, LINE_CLEAR_AFTER_S of
        uninterrupted L0 sends one all-clear and re-arms the bed.
        """
        with self.lock:
            s = self.beds.setdefault(bed, {"level": 0, "t": -math.inf, "calm": None})
            if level >= 3:
                s["calm"] = None
                if s["level"] < 3 or now - s["t"] >= LINE_CRIT_REPEAT_S:
                    s.update(level=3, t=now)
                    return "critical"
            elif level == 2:
                s["calm"] = None
                if now - s["t"] >= LINE_WARN_COOLDOWN_S:
                    s.update(level=2, t=now)
                    return "warning"
            elif level == 1:
                s["calm"] = None
                if (self.min_level == 1 and s.get("level", 0) < 2
                        and now - s.get("t_touch", -math.inf) >= LINE_TOUCH_COOLDOWN_S):
                    s["t_touch"] = now
                    return "touch"
            elif s["level"]:
                s["calm"] = now if s["calm"] is None else s["calm"]
                if now - s["calm"] >= LINE_CLEAR_AFTER_S:
                    s.update(level=0, t=-math.inf, calm=None)
                    return "cleared"
            return None

    def observe(self, out: Dict[str, Any], now: Optional[float] = None) -> Optional["concurrent.futures.Future[Dict[str, Any]]"]:
        """Feed one LivePipeline frame. Returns at once; any push runs on the worker."""
        if not self.enabled or out.get("warming_up"):
            return None
        level = int(out.get("severity_level") or 0)
        kind = self.decide(self.bed, level if level >= self.min_level else min(level, 1),
                           time.monotonic() if now is None else now)
        if kind is None:
            return None
        prop: Dict[str, Any] = out.get("propagation") or {}
        deltas: List[float] = out.get("deltas") or [0.0]
        fields: Dict[str, Any] = {"bed": self.bed, "kind": kind, "level": level,
                                  "cpri_percent": out.get("cpri_percent"), "max_delta": min(deltas),
                                  "lifting_pads": prop.get("n_lifting_pads")}
        return self.pool.submit(self.send, format_line_alert(fields), fields, self.token, self.webhook_url)

    def send(self, message: str, fields: Dict[str, Any], token: str = "", webhook_url: str = "") -> Dict[str, Any]:
        """POST one alert with retries, audit it, keep the outcome for the status badge."""
        headers = {"User-Agent": "SmartExtubation-EarlyWarning/1.0", "Content-Type": "application/json"}
        if webhook_url:
            url, channel = webhook_url, "webhook"
            payload: Dict[str, Any] = {**fields, "message": message, "timestamp": _iso_now(),
                                       "source": "SmartExtubation"}
        else:
            url, channel = LINE_BROADCAST_URL, "line_messaging_api"
            headers["Authorization"] = f"Bearer {token}"
            payload = {"messages": [{"type": "text", "text": message}]}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        t0 = time.monotonic()
        res: Dict[str, Any] = {}
        attempt = 0
        for attempt in range(1, LINE_ATTEMPTS + 1):
            res = _http_once(req)
            code = res.get("code")
            if res["ok"] or (code is not None and code < 500 and code != 429):
                break
            if attempt < LINE_ATTEMPTS:
                time.sleep(LINE_BACKOFF_S * 2 ** (attempt - 1))
        res.update(status="sent" if res["ok"] else "error", channel=channel, attempts=attempt,
                   latency_ms=round(1000 * (time.monotonic() - t0)))
        if not res["ok"]:
            logger_api.warning(f"{channel} {fields.get('kind')} push failed: {res.get('code')} {res.get('error')}")
        _append_line_audit({"at": _iso_now(), "kind": fields.get("kind"), "bed": fields.get("bed"),
                            "level": fields.get("level"), "channel": channel, "ok": res["ok"],
                            "http_status": res.get("code"), "latency_ms": res["latency_ms"],
                            "attempts": attempt, "error": res.get("error")})
        with self.lock:
            self.last = {**res, "at": _iso_now()}
        return res

    def configure(self, enabled: bool, token: str = "", webhook_url: str = "",
                  min_level: int = 2, bed: str = "") -> None:
        with self.lock:
            self.enabled, self.webhook_url, self.min_level, self.last = enabled, webhook_url, min_level, {}
            if token:
                self.token, self.token_source = token, "dashboard"
            if bed:
                self.bed = bed

    def verify(self) -> None:
        """GET /v2/bot/info with the token: 'Connected' then means the gateway took it."""
        res = _http_once(urllib.request.Request(LINE_BOT_INFO_URL, headers={
            "Authorization": f"Bearer {self.token}", "User-Agent": "SmartExtubation-EarlyWarning/1.0"}))
        with self.lock:
            self.last = {**res, "status": "verified" if res["ok"] else "error", "at": _iso_now()}

    def status(self) -> Dict[str, Any]:
        """For the dashboard badge. Never includes the token."""
        with self.lock:
            if not (self.enabled and (self.token or self.webhook_url)):
                state, detail = "disconnected", ""
            elif self.last and not self.last.get("ok"):
                state = "error"
                detail = f"HTTP {self.last['code']}: " if self.last.get("code") else ""
                detail += str(self.last.get("error") or "")
            else:
                state, detail = "connected", ("" if self.last else "not verified yet")
            return {"state": state, "detail": detail,
                    "channel": "webhook" if self.webhook_url else "line_messaging_api",
                    "token_source": self.token_source or None, "min_level": self.min_level,
                    "bed": self.bed, "last": dict(self.last)}


LINE_ALERTS = LineAlerter(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip(),
                          os.environ.get("LINE_BED_LABEL", "").strip() or "Bed 01")


def create_app(model_holder: Dict[str, Any]) -> FastAPI:
    if _fastapi_error is not None:
        raise RuntimeError(
            f"the dashboard needs fastapi and uvicorn ({_fastapi_error}). "
            f"Install them with: pip install -r requirements.txt")

    app = FastAPI(title="Touch Sensor Master Suite", version="6.2")

    access_key = os.environ.get("PROJECT2_ACCESS_KEY", "").strip()

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
            if len(auth_failures) > AUTH_TABLE_MAX_IPS:
                for ip in [k for k, v in auth_failures.items()
                           if not v or now - v[-1] >= AUTH_WINDOW_S]:
                    del auth_failures[ip]
        return False

    if access_key:
        async def _gate(request: Request, call_next: RequestResponseEndpoint) -> Response:
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

        app.add_middleware(BaseHTTPMiddleware, dispatch=_gate)

        logger_api.info("Access key protection active (sha256=%s...); "
                        "the key is in the URL you were given, not in this log",
                        hashlib.sha256(access_key.encode()).hexdigest()[:8])

    def health() -> Dict[str, Any]:
        return {"status": "ok", "model_loaded": model_holder.get("model") is not None,
                "sample_period_s": SAMPLE_PERIOD_S, "n_pads": N_PADS}

    app.add_api_route("/api/v6/health", health, methods=["GET"])

    def layout() -> Dict[str, Any]:
        return {"pads": [{"pad": i + 1, "x": PAD_XY[i][0], "y": PAD_XY[i][1],
                          "signal_channel": int(PAD_TO_SIGNAL[i])} for i in range(N_PADS)]}

    app.add_api_route("/api/v6/layout", layout, methods=["GET"])

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

    app.add_api_route("/api/v5/datasets", datasets, methods=["GET"])

    async def upload_custom_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Only .csv files are supported")

        custom_dir = os.path.join(DATA_ROOT, "Custom_Uploads")
        os.makedirs(custom_dir, exist_ok=True)

        raw_name = os.path.basename(str(file.filename).replace("\\", "/")).replace(" ", "_")
        raw_name = "".join(c for c in raw_name if c.isalnum() or c in "._-")
        if not raw_name.lower().endswith(".csv") or raw_name.startswith("."):
            raw_name = f"upload_{uuid.uuid4().hex[:8]}.csv"
        name_no_ext, ext = os.path.splitext(raw_name)

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
            tmp_path = ""
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

    app.add_api_route("/api/v6/upload-csv", upload_custom_csv, methods=["POST"])

    def serial_ports() -> Dict[str, Any]:
        ports = list_serial_ports()
        return {"ports": ports, "available": len(ports),
                "note": "empty list means no COM device is attached to this host"}

    app.add_api_route("/api/v5/serial/ports", serial_ports, methods=["GET"])

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

    app.add_api_route("/api/v5/serial/connect", serial_connect, methods=["POST"])

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
        if not _is_json_array(logs):
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

    app.add_api_route("/api/v6/event-log", get_event_logs, methods=["GET"])

    def cdc_tube_localization(body: Dict[str, Any]) -> Dict[str, Any]:
        """Static tube localization & routing detection from absolute capacitance (CDC)."""
        values = body.get("c_abs_pf", [])
        if not _is_json_array(values) or len(values) != N_PADS or any(isinstance(x, bool) for x in values):
            raise HTTPException(
                status_code=400,
                detail=f"c_abs_pf must be a list of {N_PADS} numeric capacitance values in picofarads"
            )
        try:
            arr = np.array(values, dtype=float)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid numeric values: {exc}")
        return detect_static_tube_localization(arr)

    app.add_api_route("/api/v6/cdc/tube-localization", cdc_tube_localization, methods=["POST"])

    def analyze_topography_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze baseline array across 25 channels for contour curvature and step-height tenting."""
        values = body.get("baseline", body.get("baseline_capacitance", []))
        is_cdc_pf = body.get("is_cdc_pf", None)
        if is_cdc_pf is not None and not isinstance(is_cdc_pf, bool):
            raise HTTPException(status_code=400, detail="is_cdc_pf must be a boolean if provided")
        if not _is_json_array(values) or len(values) != N_PADS or any(isinstance(x, bool) for x in values):
            raise HTTPException(
                status_code=400,
                detail=f"baseline must be a list of {N_PADS} numeric capacitance values"
            )
        try:
            arr = np.array(values, dtype=float)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid numeric values: {exc}")
        return analyze_surface_topography(arr, is_cdc_pf=is_cdc_pf)

    app.add_api_route("/api/v6/topography/analyze", analyze_topography_endpoint, methods=["POST"])

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

            prev_hash = AUDIT_GENESIS_HASH
            for earlier in reversed(logs):
                if "hash" in earlier:
                    prev_hash = str(earlier["hash"])
                    break
            event["prev_hash"] = prev_hash
            event["hash"] = audit_event_hash(event, prev_hash)
            logs.append(event)

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

    app.add_api_route("/api/v6/event-log", append_event_log, methods=["POST"])

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
            probs: List[Any] = e.get("probabilities") or []
            p0 = probs[0] if len(probs) > 0 else ""
            p1 = probs[1] if len(probs) > 1 else ""
            p2 = probs[2] if len(probs) > 2 else ""
            p3 = probs[3] if len(probs) > 3 else ""
            deltas_list: List[Any] = e.get("deltas") or []
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

    app.add_api_route("/api/v6/event-log/export-csv", export_event_logs_csv, methods=["GET"])

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
            "adhesion_health": {
                "monitored_channels": N_PADS,
                "patch_dimensions_mm": "90 x 120",
                "status": ("no level-3 event recorded this shift" if l3_count == 0
                           else f"{l3_count} level-3 event(s) recorded this shift"),
            },
            "recent_incidents": logs[-10:] if logs else [],
        }

    app.add_api_route("/api/v6/shift-report", get_shift_report, methods=["GET"])

    def notify_line(body: Dict[str, Any]) -> Dict[str, Any]:
        """Relay an operator message to LINE (Messaging API broadcast) or to an HTTPS webhook.

        The console's Test Alert uses this (level 0, never throttled). A level above
        0 goes through LINE_ALERTS.decide for the bed, so a push the live pipeline
        already sent is answered "throttled" instead of going out twice. LINE Notify
        was shut down on 2025-03-31, so it is not offered. Webhook targets must be
        public HTTPS hosts (validate_webhook_url) and redirects are refused, so this
        endpoint cannot be used to probe the network the server sits on. The webhook
        body is LineAlerter.send's allowlist (bed, kind, level, cpri_percent,
        message, timestamp); identity fields a caller adds never leave the server.
        ponytail: resolve-then-connect leaves a DNS-rebinding window; pin the resolved
        address in the connection if this endpoint is ever exposed beyond the ward LAN.
        """
        token = str(body.get("token") or "").strip()
        webhook_url = str(body.get("webhook_url") or "").strip()
        message = str(body.get("message") or "").strip()[:LINE_MESSAGE_MAX]
        if not message:
            raise HTTPException(status_code=400, detail="Missing 'message' in request body")
        if not token and not webhook_url:
            raise HTTPException(status_code=400, detail="Either 'token' or 'webhook_url' is required")
        try:
            level = int(body.get("level") or 0)
            cpri = None if body.get("cpri_percent") is None else round(float(body["cpri_percent"]), 1)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="'level' must be an integer and 'cpri_percent' a number")
        bed = str(body.get("bed") or "")[:64]
        if webhook_url:
            problem = validate_webhook_url(webhook_url)
            if problem:
                raise HTTPException(status_code=400, detail=f"webhook_url rejected: {problem}")
        if level > 0 and LINE_ALERTS.decide(bed, level, time.monotonic()) is None:
            return {"ok": False, "status": "throttled",
                    "channel": "webhook" if webhook_url else "line_messaging_api"}
        fields = {"bed": bed, "kind": "manual" if level else "test", "level": level, "cpri_percent": cpri}
        return LINE_ALERTS.send(message, fields, token, webhook_url)

    app.add_api_route("/api/v6/notify/line", notify_line, methods=["POST"])

    def line_alert_config(body: Dict[str, Any]) -> Dict[str, Any]:
        """Dashboard -> server sync of the LINE settings the browser keeps in localStorage,
        so the server dispatches even when no dashboard is open. A token is verified
        against /v2/bot/info, held in memory only and never echoed back."""
        enabled = bool(body.get("enabled"))
        token = str(body.get("token") or "").strip()
        webhook_url = str(body.get("webhook_url") or "").strip()
        min_level = body.get("min_level", 2)
        if min_level not in (1, 2, 3):
            raise HTTPException(status_code=400, detail="'min_level' must be 1, 2 or 3")
        if enabled and webhook_url:
            problem = validate_webhook_url(webhook_url)
            if problem:
                raise HTTPException(status_code=400, detail=f"webhook_url rejected: {problem}")
        if enabled and not (token or webhook_url or LINE_ALERTS.token):
            raise HTTPException(status_code=400, detail="Either 'token' or 'webhook_url' is required")
        LINE_ALERTS.configure(enabled, token, webhook_url, int(min_level), str(body.get("bed") or "")[:64])
        if enabled and not webhook_url:
            LINE_ALERTS.verify()
        return LINE_ALERTS.status()

    app.add_api_route("/api/v6/alerts/line/config", line_alert_config, methods=["POST"])
    def line_alert_status() -> Dict[str, Any]:
        return LINE_ALERTS.status()

    app.add_api_route("/api/v6/alerts/line/status", line_alert_status, methods=["GET"])

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

    app.add_api_route("/api/v6/ward/status", get_ward_status, methods=["GET"])

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
        proba, raw_preds, risk = classify_deltas(
            model_holder.get("model"), delta, model_holder.get("use_gradient", False))

        debouncer = AlarmDebouncer()
        peel = PeelTracker()
        # Under the Kalman scheme delta = raw - b(t), so the baseline trajectory is
        # raw - delta. The static scheme has no tracked baseline and so no drift.
        track = np.asarray(raw, dtype=float) - delta if mode == "kalman" else None
        drift_hist: collections.deque[float] = collections.deque(maxlen=DRIFT_RATE_WINDOW_FRAMES)
        jit: collections.deque[float] = collections.deque(maxlen=JITTER_WINDOW_FRAMES)

        frames: List[Dict[str, Any]] = []
        for i in range(len(delta)):
            d = delta[i]
            warming = bool(mode == "kalman" and i < KALMAN_WARMUP)
            level = 0 if warming else debouncer.update(int(raw_preds[i]))
            quality: Dict[str, Any] = {"cqi": None, "components": None, "drift": None,
                                       "note": "no tracked baseline under static calibration"}
            if track is not None:
                if i and not warming and int(raw_preds[i]) == 0:
                    jit.append(float(np.median(np.abs(delta[i] - delta[i - 1]))))
                drift_hist.append(float((track[i] - track[0]).mean()))
                quality = signal_quality(track[i], track[0],
                                         float(np.median(jit)) if jit else 0.0, drift_hist)
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
                "alarm_signal": alarm_signal(level, warming=warming),
                "signal_quality": quality,
            })
        return JSONResponse({"filename": filepath, "calibration": mode,
                             "total_frames": len(frames), "frames": frames})

    app.add_api_route("/api/v5/dataset/{filepath:path}", dataset_analysis, methods=["GET"])

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

    app.add_api_route("/api/v6/heatmap/{filepath:path}", heatmap, methods=["GET"])

    async def live_sensor(ws: WebSocket) -> None:
        if access_key:
            supplied = (ws.query_params.get("key")
                        or ws.headers.get("x-access-key")
                        or ws.cookies.get("p2key") or "")
            if not _key_ok(supplied, access_key):
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
                attached: Set[str] = set()
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
                    if not _is_json_object(msg):
                        await ws.send_json({"error": "expected a JSON object"})
                        continue
                    if msg.get("event") == "stop":
                        break
                    if msg.get("event") == "reseed":
                        pipeline.reseed()
                        await ws.send_json({"event": "reseeded", "status": "ok"})
                        continue
                    vals = msg.get("raw_frame")
                    if not _is_json_array(vals) or len(vals) < N_PADS:
                        await ws.send_json({"error": f"raw_frame must be {N_PADS} numbers",
                                            "got": (len(vals) if _is_json_array(vals) else None)})
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
                    out = pipeline.process(pad_frame)
                    LINE_ALERTS.observe(out)
                    await ws.send_json(out)
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
            pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="p2-frames")
            try:
                while True:
                    frame = await loop.run_in_executor(pool, lambda: next(gen, None))
                    if frame is None:
                        break
                    out = pipeline.process(frame)
                    if source_kind == "serial":
                        LINE_ALERTS.observe(out)
                    await ws.send_json(out)
                await ws.send_json({"event": "finished", "frames": pipeline.index})
            finally:
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

    app.add_api_websocket_route("/ws/live_sensor", live_sensor)

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

    app.add_api_route("/api/v6/metrics", metrics, methods=["GET"])

    if os.path.isdir(WEB_DIR):
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    def dashboard() -> Any:
        index = os.path.join(WEB_DIR, "index.html")
        if not os.path.isfile(index):
            return HTMLResponse(status_code=500, content=(
                "<h1>web/index.html is missing</h1>"
                "<p>The dashboard is served from the <code>web/</code> folder "
                "next to main.py. The API is unaffected - try "
                "<a href='/api/v6/health'>/api/v6/health</a>.</p>"))
        with open(index, "r", encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read(), headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            })

    app.add_api_route("/", dashboard, methods=["GET"], response_class=HTMLResponse)

    def presentation_deck() -> Any:
        deck_path = os.path.join(PROJECT_DIR, "docs", "presentation_deck.html")
        if not os.path.isfile(deck_path):
            return HTMLResponse(status_code=404, content=(
                "<h1>docs/presentation_deck.html is missing</h1>"
                "<p>Presentation slide deck file not found.</p>"))
        with open(deck_path, "r", encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read())

    app.add_api_route("/slides", presentation_deck, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/deck", presentation_deck, methods=["GET"], response_class=HTMLResponse)

    return app


class _Axes(Protocol):
    """The Axes calls the research plots make, with complete signatures.

    matplotlib annotates these methods apart from their **kwargs, and strict
    pyright reports every use of a partly annotated method. _pyplot() hands
    out matplotlib.pyplot typed through these protocols; pyright checks the
    module, its Figure and its Axes against them there.
    """

    def matshow(self, Z: np.ndarray, /, *, cmap: str) -> object: ...
    def text(self, x: float, y: float, s: str, /, *, ha: str, va: str, fontweight: str, color: str) -> object: ...
    def set_xticks(self, ticks: Sequence[int], /) -> object: ...
    def set_yticks(self, ticks: Sequence[int], /) -> object: ...
    def set_xticklabels(self, labels: Sequence[str], /, *, rotation: float) -> object: ...
    def set_yticklabels(self, labels: Sequence[str], /) -> object: ...
    def set_xlabel(self, xlabel: str, /) -> object: ...
    def set_ylabel(self, ylabel: str, /) -> object: ...
    def set_title(self, label: str, /, *, fontweight: str, fontsize: float) -> object: ...
    def imshow(self, X: np.ndarray, /, *, origin: Literal["upper", "lower"], extent: Tuple[float, float, float, float], cmap: str, vmin: float, vmax: float, aspect: Literal["equal", "auto"]) -> AxesImage: ...
    def quiver(self, *args: np.ndarray, color: str, scale: Optional[float], width: float, label: str) -> object: ...
    def annotate(self, text: str, /, *, xy: Tuple[float, float], xytext: Tuple[float, float], arrowprops: Dict[str, Any]) -> object: ...
    def scatter(self, x: np.ndarray, y: np.ndarray, /, *, s: float, c: str, alpha: float) -> object: ...


class _Figure(Protocol):
    """The Figure call the research plots make; see _Axes."""

    def colorbar(self, mappable: AxesImage, /, *, shrink: float, label: str) -> object: ...


class _Pyplot(Protocol):
    """The matplotlib.pyplot functions the research plots call; see _Axes."""

    def figure(self, *, figsize: Tuple[float, float]) -> object: ...
    def subplots(self, *, figsize: Tuple[float, float]) -> Tuple[_Figure, _Axes]: ...
    def bar(self, x: Sequence[int], height: np.ndarray, /, *, color: str, edgecolor: str, alpha: float) -> object: ...
    def plot(self, *args: ArrayLike | str, color: str = ..., lw: float = ..., label: str = ..., alpha: float = ...) -> object: ...
    def xticks(self, ticks: Sequence[int], labels: Sequence[str], /, *, rotation: float, ha: str, fontsize: float) -> object: ...
    def xlabel(self, xlabel: str, /) -> object: ...
    def ylabel(self, ylabel: str, /) -> object: ...
    def title(self, label: str, /, *, fontweight: str = ..., pad: float = ...) -> object: ...
    def legend(self, *, loc: str, fontsize: float) -> object: ...
    def grid(self, *, axis: Literal["both", "x", "y"] = ..., linestyle: str = ..., alpha: float = ...) -> None: ...
    def tight_layout(self) -> None: ...
    def savefig(self, fname: str, /, *, dpi: int) -> None: ...
    def close(self) -> None: ...


def _pyplot() -> _Pyplot:
    """matplotlib.pyplot on the off-screen Agg backend, imported on first use."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot
    return matplotlib.pyplot


def generate_plots(ds: Dataset, rf_result: Dict[str, Any], model: Any) -> None:
    plt = _pyplot()

    os.makedirs(RESEARCH_PLOTS_DIR, exist_ok=True)
    names = feature_names(bool(ds.X.shape[1] > len(BASE_FEATURE_NAMES)))

    imp: NDArray[np.float64] = model.feature_importances_
    order: List[int] = np.argsort(imp)[::-1].tolist()
    plt.figure(figsize=(10, 5.5))
    plt.bar(range(len(names)), imp[order], color="#2a78d6", edgecolor="black", alpha=.9)
    plt.xticks(range(len(names)), [names[i] for i in order], rotation=35, ha="right", fontsize=9)
    plt.ylabel("Gini importance")
    plt.title("Spatio-temporal feature importance", fontweight="bold")
    plt.grid(axis="y", linestyle="--", alpha=.4)
    plt.tight_layout()
    plt.savefig(os.path.join(RESEARCH_PLOTS_DIR, "feature_importances.png"), dpi=200)
    plt.close()

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

    peel = [i for i, lab in enumerate(ds.labels) if lab == 2]
    if not peel:
        print("  note: no class-2 (Peel) recordings - skipping the propagation figure")
    if peel:
        d = ds.frames[peel[0]]
        k = int(np.argmin(d.mean(axis=1)))
        grid = SPATIAL.interpolate(d[k])
        g = SPATIAL.node_gradients(d[k])
        fig, ax = plt.subplots(figsize=(6.4, 7.6))
        lim = float(np.abs(grid).max()) or 1.0
        im = ax.imshow(grid, origin="upper", extent=(10.0, 90.0, 95.0, 10.0), cmap="coolwarm",
                       vmin=-lim, vmax=lim, aspect="auto")
        fig.colorbar(im, shrink=.8, label="delta capacitance (counts)")
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


SPEC_DETACH_MAX = 25000.0
SPEC_CONTACT_MIN = 30000.0

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

    if arr.size == SEED_RESTING_SHAPE.size:
        expected = SEED_RESTING_SHAPE + (med - float(np.median(SEED_RESTING_SHAPE)))
    else:
        expected = np.full(arr.shape, med)
    dev = np.abs(arr - expected)
    outliers = [int(i) + 1 for i in np.nonzero(np.isfinite(dev) &
                                               (dev > SEED_CHANNEL_OUTLIER_COUNTS))[0]]
    if outliers:
        listed = ", ".join(str(p) for p in outliers)
        plural = "Pads" if len(outliers) > 1 else "Pad"
        high = [p for p in outliers if arr[p - 1] > expected[p - 1]]
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


MIN_AUDIT_FRAMES = 100
BASELINE_MAX_SWING = 100.0
ROUND1_FRICTION_SWING = 654.0


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

    _check(f"Peel crosses the {-DELTA_THRESHOLD:,.0f} count lift gate (the "
           f"criterion the detector uses)",
           peel["usable"] > 0 and peel["reach_lift_gate"] >= 0.8 * peel["usable"],
           f"{peel['reach_lift_gate']}/{peel['usable']} usable files cross it; "
           f"median deepest delta {_median_delta(per_class, 2)} counts (need >= 80%)"
           if peel["usable"] else "no usable Peel recordings")

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
    _check("every CSV sits in a folder the loader reads", not nested_dirs,
           f"{lost_files} file(s) in {len(nested_dirs)} stray folder(s) - see below"
           if nested_dirs else f"all {total} accounted for")

    base_swings = [v["max_swing"] for lbl, v in per_class.items()
                   if lbl.split("/")[-1] in ("N_base", "Baseline") and v["max_swing"] is not None]
    _check(f"baseline swing <= {BASELINE_MAX_SWING:.0f} counts",
           bool(base_swings) and max(base_swings) <= BASELINE_MAX_SWING,
           f"worst {max(base_swings):.0f} counts" if base_swings else "no baseline recording")

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


def report_caveats(ds: Dataset) -> List[str]:
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
                 stamp: str, stream: Optional[Dict[str, Any]] = None,
                 served: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """Emit every headline number to disk.

    The v5.0 whitepaper quoted 90.00% / macro F1 0.8791; the script produced
    87.50% / 0.8498. Numbers typed by hand drift from numbers the code
    produces. Paper tables must be copied from METRICS.md, never retyped.
    """
    os.makedirs(DATA_ROOT, exist_ok=True)
    counts = {name: int(sum(1 for lab in ds.labels if lab == i))
              for i, name in enumerate(["baseline", "incidental", "peel", "pull"])}
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
            "column_conventions": ds.conventions,
            "min_raw_count_by_class": ds.min_raw_by_label,
            "skipped": [{"file": f, "reason": r} for f, r in ds.skipped],
        },
        "random_forest": {
            "cv": rf["cv"], "seeds": [r["seed"] for r in rf["runs"]],
            "confusion_matrix_note": f"pooled over {rf['n_seeds']} seed(s); "
                                     f"accuracy over the pool equals the mean above",
            "accuracy_mean": rf["accuracy_mean"], "accuracy_sd": rf["accuracy_sd"],
            "macro_f1_mean": rf["macro_f1_mean"], "macro_f1_sd": rf["macro_f1_sd"],
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
        "served_episode_level": ({
            "path": "LivePipeline replay, out of fold (evaluate_served)",
            "operating_point": served["operating_point"],
            "sensitivity": served["sensitivity"], "sensitivity_ci": served["sensitivity_ci"],
            "false_alarm_rate": served["false_alarm_rate"],
            "false_alarm_ci": served["false_alarm_ci"],
            "alarms_per_hour": served["alarms_per_hour"],
            "median_latency_s": served["median_latency_s"],
            "max_latency_s": served["max_latency_s"],
            "missed": served["missed"],
        } if served else None),
        "caveats": report_caveats(ds),
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
        f"## {type(new_rf(42)).__name__} ({rf['cv']}-level cross validation)", "",
        "| Metric | Value |", "|---|---|",
        f"| Accuracy | {rf['accuracy_mean']*100:.2f}%"
        + (f" ± {rf['accuracy_sd']*100:.2f} (n={n_seeds} seeds)" if n_seeds > 1 else "") + " |",
        f"| Macro F1 | {rf['macro_f1_mean']:.4f}"
        + (f" ± {rf['macro_f1_sd']:.4f}" if n_seeds > 1 else "") + " |",
        "| Tie-break | toward the more severe class |",
        f"| False alarm on normal files | {false_alarm_rate(rf['y_true'], rf['y_pred'])*100:.1f}% |",
        "",
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
    present: List[int] = sorted(set(rf["y_true"]) | set(rf["y_pred"]))
    names = ["0: Baseline", "1: Touch/Press", "2: Peel", "3: Pull"]
    lines.append(str(_SKLEARN_METRICS.classification_report(
        rf["y_true"], rf["y_pred"], labels=present,
        target_names=[names[i] for i in present], zero_division=0)))
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
                   if r["median_latency_s"] is not None else "—")
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

    if served:
        op = served["operating_point"]
        slo, shi = served["sensitivity_ci"]
        flo, fhi = served["false_alarm_ci"]
        lines += ["", "## Episode-level performance, served path (out-of-fold, LivePipeline)", "",
                  "The table above votes the model on the offline Kalman delta, every frame. "
                  "The server does not run that path: LivePipeline seeds its baseline from "
                  "frame 0, repairs quiescent channels, rescales by F10 and never asks the "
                  "model about a frame under the noise gate. Here each fold's model streams "
                  "its held-out recording through LivePipeline itself, so this is the table "
                  "that describes the running system. Why the two differ: "
                  "docs/ML_ENHANCEMENT_PLAN.md section 9.", "",
                  f"Operating point: {op['votes']}-of-{op['window']} frames, "
                  f"hold {op['hold']} frames ({op['hold']*SAMPLE_PERIOD_S:.2f} s).", "",
                  "| Metric | Value | 95% CI |", "|---|---|---|",
                  f"| Sensitivity (episode detected) | {served['sensitivity']*100:.1f}% | "
                  f"[{slo*100:.1f}, {shi*100:.1f}] |",
                  f"| False alarm per recording | {served['false_alarm_rate']*100:.1f}% | "
                  f"[{flo*100:.1f}, {fhi*100:.1f}] |",
                  f"| False alarms per hour | {served['alarms_per_hour']:.1f} | — |",
                  "| Time to alarm (median / worst) | "
                  + (f"{served['median_latency_s']:.2f} s / {served['max_latency_s']:.2f} s"
                     if served["median_latency_s"] is not None
                     else "no episode detected") + " | — |",
                  "", f"Missed events ({len(served['missed'])}): "
                  f"{', '.join(served['missed']) or 'none'}"]

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
        running = __import__("sklearn").__version__
        if recorded.get("sklearn") != running:
            logger_model.info("Cached model was written by scikit-learn %s, this is %s; "
                              "retraining", recorded.get("sklearn"), running)
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
                   oof: Optional[np.ndarray] = None,
                   served_levels: Optional[Sequence[np.ndarray]] = None,
                   use_gradient: bool = False) -> Dict[str, Any]:
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

    if oof is None:
        collected: List[np.ndarray] = []
        votes = compute_oof(ds, 42, served=collected, use_gradient=use_gradient)
        served_levels = collected
    else:
        votes = oof
    st = evaluate_stream(ds, 42, verbose=False, oof=votes)
    y_true = [int(lab) for lab in ds.labels]
    y_pred = [file_vote(votes[ds.groups == i]) for i in range(ds.n_files)]
    measured = {
        "episode_level.sensitivity": st["sensitivity"],
        "episode_level.false_alarm_rate": st["false_alarm_rate"],
        "episode_level.alarms_per_hour": st["alarms_per_hour"],
        "episode_level.median_latency_s": st["median_latency_s"],
        "random_forest.accuracy_mean": float(accuracy_score(y_true, y_pred)),
        "random_forest.macro_f1_mean": float(f1_score(y_true, y_pred, average="macro")),
        "dataset.files": float(ds.n_files),
        "dataset.frames": float(len(ds.X)),
        "dataset.features": float(ds.X.shape[1]),
    }
    if served_levels is not None:
        sv = evaluate_served(ds, served_levels, verbose=False)
        measured.update({
            "served_episode_level.sensitivity": sv["sensitivity"],
            "served_episode_level.false_alarm_rate": sv["false_alarm_rate"],
            "served_episode_level.alarms_per_hour": sv["alarms_per_hour"],
            "served_episode_level.median_latency_s": sv["median_latency_s"],
        })
    report["served_checked"] = served_levels is not None
    measured = {k: float(v) for k, v in measured.items() if v is not None}

    def _dig(key: str) -> Optional[float]:
        node: Any = stored
        for part in key.split("."):
            if not _is_json_object(node) or part not in node:
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
        if key.endswith("latency_s"):
            moved = abs(now - was) > SAMPLE_PERIOD_S + 1e-9
        else:
            moved = abs(now - was) / scale > tolerance
        if moved:
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
    if not rep.get("served_checked", False):
        print("  served path         : NOT re-measured (no LivePipeline replays supplied)")
    if rep["status"] == "current":
        print(f"\n  OK - every headline figure reproduces within "
              f"{2:.0f}% of the file on disk (times to alarm within one frame).")
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
    out: List[str] = []
    for v in np.asarray(delta, dtype=float):
        if v <= -DELTA_THRESHOLD:
            out.append("V")
        elif v <= -NOISE_GATE_COUNTS:
            out.append("v")
        elif v >= DELTA_THRESHOLD:
            out.append("A")
        elif v >= NOISE_GATE_COUNTS:
            out.append("^")
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
    line = LINE_ALERTS.status()
    print(f"  LINE alerts: {line['state']} ({line['bed']}, Level {line['min_level']}+)"
          if line["state"] != "disconnected" else
          "  LINE alerts: off (set LINE_CHANNEL_ACCESS_TOKEN to page the ward from this monitor)")
    print("  legend: V past -300 lift gate  v lifting  ^ contact  A firm contact  . quiet")
    print("  Ctrl-C to stop\n")
    n = 0
    try:
        for frame in src.frames():
            out = pipe.process(frame)
            LINE_ALERTS.observe(out)
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
        return 0 if print_metric_verification(
            verify_metrics(ds, use_gradient=args.gradient)) else 2

    if args.monitor:
        if args.calibration != "kalman":
            print("  WARNING: model trained with --calibration static but the live path "
                  "uses the Kalman baseline; the feature distributions differ.")
        return run_monitor(args.monitor, args.baud, args.permute,
                           new_rf(42).fit(ds.X, ds.y), args.gradient, args.monitor_frames)

    if args.eval or args.plots or args.report or args.eval_temporal or args.stream:
        temporal = None
        served_levels: Optional[List[np.ndarray]] = (
            [] if (args.stream or args.report) else None)
        shared_oof = (compute_oof(ds, 42, served=served_levels, use_gradient=args.gradient)
                      if (args.stream or args.report) else None)
        stream = (evaluate_stream(ds, verbose=True, oof=shared_oof)
                  if (args.stream or args.report) else None)
        served = (evaluate_served(ds, served_levels)
                  if served_levels is not None else None)
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
                model = new_rf(42).fit(ds.X, ds.y)
                generate_plots(ds, res, model)
        if args.report:
            assert res is not None
            jp, mp = write_report(ds, res, temporal, args.stamp or "unstamped", stream, served)
            print(f"  metrics -> {jp}")
            print(f"  metrics -> {mp}")
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
        model = new_rf(42).fit(ds.X, ds.y)
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
        model = new_rf(42).fit(ds.X, ds.y)
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
