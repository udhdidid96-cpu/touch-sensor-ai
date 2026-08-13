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
import difflib
import collections
import glob
import hashlib
import hmac
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.interpolate import RBFInterpolator
from sklearn.ensemble import RandomForestClassifier
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
AUTH_RATE_LIMIT_LOCK = threading.Lock()
AUTH_FAILED_ATTEMPTS: Dict[str, List[float]] = collections.defaultdict(list)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # M3: 5 MB size limit
MAX_CUSTOM_UPLOADS = 50             # M3: 50 file quota limit

# =============================================================================
# 1. CONSTANTS, PHYSICAL LAYOUT AND WIRING
# =============================================================================
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.realpath(os.path.join(PROJECT_DIR, "Data"))
RESEARCH_PLOTS_DIR = os.path.join(DATA_ROOT, "research_plots")
WEB_DIR = os.path.join(PROJECT_DIR, "web")     # the dashboard, served by create_app
MODEL_PERSISTENCE_PATH = os.path.join(DATA_ROOT, "trained_model.joblib")

BASELINE_COUNTS = 28000.0        # nominal C0, KES 2025 section 2.1
COUNTS_PER_PF = 59.85            # sensor resolution
SAMPLE_PERIOD_S = 0.560          # microcontroller acquisition cycle
DELTA_THRESHOLD = 300.0          # dual-colour threshold

N_PADS = 25
N_CLASSES = 4

# Physical centre of each pad, in percent of the 90 mm x 120 mm patch.
# Pad numbering follows the 1-by-1 press sequence used during characterisation.
PHYSICAL_PAD_COORDS: Dict[int, Tuple[float, float]] = {
    1: (57.0, 90.0), 2: (73.0, 78.0), 3: (58.0, 78.0), 4: (79.0, 64.0), 5: (65.0, 64.0),
    6: (80.0, 50.0), 7: (65.0, 50.0), 8: (80.0, 36.0), 9: (65.0, 36.0), 10: (74.0, 24.0),
    11: (58.0, 22.0), 12: (50.0, 35.0), 13: (50.0, 50.0), 14: (50.0, 64.0), 15: (40.0, 22.0),
    16: (25.0, 24.0), 17: (35.0, 36.0), 18: (20.0, 36.0), 19: (35.0, 50.0), 20: (20.0, 50.0),
    21: (35.0, 64.0), 22: (21.0, 64.0), 23: (40.0, 78.0), 24: (26.0, 78.0), 25: (41.0, 90.0),
}

# FIX F2 -------------------------------------------------------------------
# The firmware emits channels as Signal-1..Signal-25 in electrical order.
# The physical pad at position k is wired to the channel below. Feeding raw
# Signal order into the coordinate table (as v5.0 did) scrambles the patch.
#
# *** UNVERIFIED ASSUMPTION - A9, read before quoting any spatial result. ***
# All 80 round-1 recordings carry Sensor-* headers, so read_raw_csv takes the
# "already in pad order" branch and this permutation is NEVER applied to them.
# SerialFrameSource, the live hardware path, always applies it. The two paths
# therefore assume opposite conventions for the same 25 numbers, and nothing
# in this repo records which one the firmware's UART stream actually uses.
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
# Weak evidence for the current CSV branch: on the 10 Peel files, the pads
# below -300 counts form a spatially tighter cluster under the as-is reading
# (mean pairwise distance 33.9) than under the permuted one (42.6), against a
# 37.9 random-pad null - a peel should lift a contiguous patch. n=10, so treat
# that as a hint, not a proof.
#
# The bench check that settles it: press pad 1, then pad 25, record both, and
# confirm which column moves. Until that is on record, do not put a
# propagation direction in the paper.
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

STATUS_TEXT_MAP: Dict[int, str] = {
    0: "🟢 ปกติ (Baseline / Normal)",
    1: "✋ คนไข้เอามือทับ / สัมผัส (Hand Press / Touch)",
    2: "⚠️ คนไข้เริ่มลอกพลาสเตอร์ (Unpeel / Peel Warning)",
    3: "🚨 คนไข้กำลังดึงพลาสเตอร์/ท่อหลุด! (Critical Pull Alarm)",
}

MIN_FRAMES_PER_FILE = 5          # files shorter than this cannot be calibrated
KALMAN_WARMUP = 5                # frames held at Level 0 while the baseline settles

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
#   window  k  hold |  sensitivity  false alarm/rec  alarms/hour  latency
#      5    3    9  |     97.5%          22.5%          27.1       4.48 s
#      3    3    0  |     95.0%          12.5%          18.0       4.48 s
#      5    4    9  |     90.0%           7.5%           9.0       5.04 s
#   >  7    5    9  |     87.5%           5.0%           6.0       5.60 s  <- default
#      7    6    9  |     72.5%           2.5%           3.0       6.16 s
#      5    5    9  |     75.0%           0.0%           0.0       5.60 s
#
# 5-of-5 reaches 0 false alarms but drops 25% of real events - not a defensible
# trade for a safety device. 5-of-4 buys +2.5 pp sensitivity for +50% alarm
# burden; the default keeps the burden nearer the measured ICU baseline.


@dataclass
class AlarmConfig:
    """Annunciator operating point.

    A dataclass rather than three module-level constants: main() rebound
    uppercase names through `global`, which every type checker flags as
    redefining a constant, and which left the effective operating point
    invisible to anything importing this module instead of running it.
    """

    window: int = 7                  # 3.92 s decision window
    min_votes: int = 5               # k of n frames must support the level
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

    q: float = 0.5          # process noise; drift is slow
    r: float = 40.0         # measurement noise ~ observed baseline sd
    gate: float = 250.0     # counts; below DELTA_THRESHOLD so events never leak in
    warmup: int = KALMAN_WARMUP   # frames used to seed the state

    b: Optional[np.ndarray] = None
    p: Optional[np.ndarray] = None

    def seed(self, frames: np.ndarray) -> "KalmanBaseline":
        arr = np.asarray(frames, dtype=float)
        n = min(self.warmup, len(arr))
        self.b = arr[:n].mean(axis=0).astype(float)
        self.p = np.full(arr.shape[1], self.r, dtype=float)
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

        # gated update: quiescent channels track, active channels coast
        quiescent = np.abs(innovation) < self.gate
        k_gain = np.where(quiescent, p_pred / (p_pred + self.r), 0.0)
        self.b = self.b + k_gain * innovation
        self.p = (1.0 - k_gain) * p_pred

        return z - self.b

    def run(self, raw: np.ndarray) -> np.ndarray:
        """Vectorised convenience: returns the delta matrix for a whole file."""
        arr = np.asarray(raw, dtype=float)
        self.seed(arr)
        return np.vstack([self.step(row) for row in arr])


def calibrate(raw: np.ndarray, mode: str = "static") -> np.ndarray:
    """Return the delta-from-baseline matrix under the requested scheme."""
    arr = np.asarray(raw, dtype=float)
    if mode == "kalman":
        return KalmanBaseline().run(arr)
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
                    mean_gate: float = PEEL_MEAN_GATE) -> Dict[str, Any]:
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
      Stepping 3 -> 2 takes at most ``window - min_votes + 1`` frames (1.68 s at
      the default 5-of-7) - the time for level 3 to lose its majority. That is a
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

    def __init__(self, persist: int = PEEL_PERSIST_FRAMES) -> None:
        self.persist = persist
        self.streak = 0
        self.confirmed = False

    def update(self, pad_delta: ArrayLike) -> Dict[str, Any]:
        info = SPATIAL.propagation(pad_delta)
        self.streak = self.streak + 1 if info["active"] else 0
        self.confirmed = self.streak >= self.persist
        info["streak_frames"] = self.streak
        info["confirmed"] = self.confirmed
        info["confirmed_after_s"] = round(self.persist * SAMPLE_PERIOD_S, 2)
        return info


# =============================================================================
# 4. FEATURE EXTRACTION  (FIX F5)
# =============================================================================
BASE_FEATURE_NAMES: Tuple[str, ...] = (
    "Min Delta", "Max Delta", "Mean Delta", "Std Delta",
    "Drop Count (<= -300)", "Drop Count (<= -600)", "Drop Count (<= -1000)",
    "Spike Count (>= +300)", "Spike Count (>= +1000)",
)
GRAD_FEATURE_NAMES: Tuple[str, ...] = ("Grad Magnitude", "Grad Anisotropy")


def feature_names(use_gradient: bool) -> List[str]:
    return list(BASE_FEATURE_NAMES) + (list(GRAD_FEATURE_NAMES) if use_gradient else [])


def extract_features(pad_delta: np.ndarray, use_gradient: bool = False) -> np.ndarray:
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

    return np.column_stack(cols)


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
    lost = sum(n for _, n, _ in unknown)

    def _warn_stray() -> None:
        if not unknown:
            return
        print(f"  {'!' * 70}")
        print(f"  WARNING: {lost} CSV file(s) in {len(unknown)} folder(s) were NOT loaded")
        for name, n, hint in unknown:
            print(f"    - {name}/  ({n} csv)  ->  {hint}")
        print(f"  {'!' * 70}")

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
            print("  NOTE: PAD_ORDER is not exercised by any recording. Accuracy figures "
                  "are unaffected (base features are permutation-invariant), but the "
                  "heatmap, peel direction and LOOP 3 figure rest on Sensor-N == pad N, "
                  "which no bench measurement in this repo confirms.")

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


def cpri(proba: np.ndarray) -> np.ndarray:
    """Composite Patient Risk Index, clamped per whitepaper section 6.2."""
    p = np.atleast_2d(np.asarray(proba, dtype=float))
    return np.minimum(100.0, p[:, 2] * 70.0 + p[:, 3] * 100.0)  # type: ignore[no-any-return]


# =============================================================================
# 6. RANDOM FOREST MODEL + HONEST EVALUATION  (FIX F6)
# =============================================================================
def _new_rf(seed: int = 42) -> RandomForestClassifier:
    """Class-balanced forest.

    Frame counts are [589, 1549, 216, 652]: the Peel warning class is 7.2% of
    frames and Touch/Press is 51.5%. An unweighted forest was quietly paying
    for that. balanced_subsample lifts LOFO accuracy 95.0 -> 96.8% (5-seed
    mean; a single seed can read 97.5%) and pull recall 0.867 -> 0.920 at an
    unchanged false-alarm rate, and it is a principled correction rather than
    another tuned knob. Quote the 5-seed figure - it is what METRICS.md
    reports and what the README carries.

    n_estimators=200 measured against 100/200/300/500 on the full LOFO sweep:
    accuracy sits at 96.2-97.5% and the seed-to-seed sd at 0.72 pp for every
    one of them, while runtime scales linearly (29 s -> 140 s per LOFO run).
    More trees buy nothing here. (An earlier draft claimed 500 removed the seed
    variance; that came from three seeds that happened to agree and does not
    hold - the sd is 0.72 pp at 500 as well.)
    """
    return RandomForestClassifier(n_estimators=200, max_depth=12,
                                  class_weight="balanced_subsample",
                                  random_state=seed, n_jobs=-1)


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
    print(f"RANDOM FOREST - leave-one-{res.get('cv', 'file')}-out cross validation")
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
    for k, mag in enumerate(drive):
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
    IDLE_TIMEOUT_S = 10.0        # silence this long means the device is gone
    EMPTY_READ_SLEEP_S = 0.02    # floor on the poll rate if reads return at once

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 2.0) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial is required for serial streaming: pip install pyserial") from exc
        self._serial_mod = serial
        self.port = port
        self.baudrate = baudrate
        self._ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        self._stop = threading.Event()

    def frames(self) -> Iterator[np.ndarray]:
        buf = self._ser
        last_frame_at = time.monotonic()
        while not self._stop.is_set():
            try:
                line = buf.readline().decode("utf-8", errors="replace").strip()
            except Exception:
                break
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
            last_frame_at = time.monotonic()
            yield signals_to_pads(vals)

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

    def __init__(self, rel_path: str, realtime: bool = True, loop: bool = False) -> None:
        full = safe_data_path(rel_path)
        raw = read_raw_csv(full)
        if raw is None:
            raise RuntimeError(f"{rel_path}: missing 25 sensor columns")
        self.raw = raw
        self.rel_path = rel_path
        self.realtime = realtime
        self.loop = loop

    def frames(self) -> Iterator[np.ndarray]:
        while True:
            for row in self.raw:
                yield row
                if self.realtime:
                    time.sleep(SAMPLE_PERIOD_S)
            if not self.loop:
                return


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

    def __init__(self, model: Optional[Any], use_gradient: bool = False,
                 fuse_imu: bool = False, warmup_frames: int = KALMAN_WARMUP) -> None:
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
        self.index = 0
        self._seeded = False
        self._prev: Optional[np.ndarray] = None

    @property
    def warming_up(self) -> bool:
        return self.index < self.warmup_frames

    def process(self, pad_frame: np.ndarray, imu: Optional[IMUFrame] = None) -> Dict[str, Any]:
        pad_frame = np.asarray(pad_frame, dtype=float)
        if not self._seeded:
            # Seed from the first frame only - live, there is nothing else yet.
            # KalmanBaseline.run() seeds from the mean of the first 5 frames, so
            # offline and online deltas differ slightly (max 43.5 counts measured
            # on A_Peel_01, well under the 300-count decision threshold). The
            # warmup window below hides the transient either way.
            self.kalman.seed(pad_frame[None, :])
            self._seeded = True

        delta = self.kalman.step(pad_frame)
        feats = extract_features(delta, self.use_gradient)

        warming = self.warming_up
        if self.model is not None and not warming:
            proba = full_proba(self.model, feats)[0]
            raw_level = int(np.argmax(proba))
        else:
            proba = np.zeros(N_CLASSES)
            proba[0] = 1.0
            raw_level = 0
        level = self.alarm.update(raw_level)
        risk = 0.0 if warming else float(cpri(proba[None, :])[0])

        fused = None
        if self.fusion is not None:
            if imu is None and self._prev is not None:
                imu = synthesise_imu(np.vstack([self._prev, delta]))[-1]
            fused = self.fusion.step(risk, imu)
        self._prev = delta

        out = {
            "index": self.index,
            "time_sec": round(self.index * SAMPLE_PERIOD_S, 3),
            "pad_values": [round(v, 1) for v in pad_frame.tolist()],
            "deltas": [round(v, 1) for v in delta.tolist()],
            "baseline": [round(v, 1) for v in (self.kalman.b if self.kalman.b is not None else pad_frame).tolist()],
            "severity_level": level,
            "raw_level": raw_level,
            "status": ("Calibrating baseline ..." if warming
                       else STATUS_TEXT_MAP.get(level, "unknown")),
            "warming_up": warming,
            "probabilities": [round(float(p), 4) for p in proba.tolist()],
            "cpri_percent": round(risk, 1),
            "propagation": self.peel.update(delta),
        }
        if fused is not None:
            out["fusion"] = {k: round(float(v), 4) for k, v in fused.items()}
        self.index += 1
        return out


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
    from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    _FASTAPI_ERROR: Optional[str] = None
except ImportError as _fastapi_exc:      # pragma: no cover - depends on the env
    FastAPI = File = HTTPException = Request = UploadFile = WebSocket = WebSocketDisconnect = None  # type: ignore
    HTMLResponse = JSONResponse = PlainTextResponse = StaticFiles = None        # type: ignore
    _FASTAPI_ERROR = str(_fastapi_exc)


def _key_ok(supplied: str, expected: str) -> bool:
    """Constant-time secret comparison that tolerates any input.

    hmac.compare_digest refuses non-ASCII *str* with a TypeError, so a request
    carrying ?key=e-acute used to escape the gate as an unhandled 500 rather
    than a 401 (B2). Encoding both sides first makes every input comparable.
    """
    return hmac.compare_digest(supplied.encode("utf-8", "surrogatepass"),
                               expected.encode("utf-8", "surrogatepass"))


def create_app(model_holder: Dict[str, Any]) -> Any:
    if _FASTAPI_ERROR is not None or FastAPI is None:
        raise RuntimeError(
            f"the dashboard needs fastapi and uvicorn ({_FASTAPI_ERROR}). "
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

    if access_key:
        @app.middleware("http")
        async def _gate(request: Request, call_next: Any) -> Any:
            supplied = (request.query_params.get("key")
                        or request.headers.get("x-access-key")
                        or request.cookies.get("p2key") or "")
            if not _key_ok(supplied, access_key):
                client_ip = request.client.host if request.client else "unknown"
                now = time.time()
                with AUTH_RATE_LIMIT_LOCK:
                    attempts = [t for t in AUTH_FAILED_ATTEMPTS[client_ip] if now - t < 60.0]
                    AUTH_FAILED_ATTEMPTS[client_ip] = attempts
                    if len(attempts) >= 10:
                        logger_api.warning(f"Access key rate limit exceeded for IP {client_ip}")
                        return PlainTextResponse("429 - Too Many Failed Auth Attempts", status_code=429)
                    AUTH_FAILED_ATTEMPTS[client_ip].append(now)
                logger_api.warning(f"Unauthorized access attempt from IP {client_ip}")
                return PlainTextResponse("401 - add ?key=... to the URL", status_code=401)
            response = await call_next(request)
            if request.query_params.get("key") == access_key:
                response.set_cookie(
                    "p2key", access_key, httponly=True, samesite="lax",
                    secure=(request.url.scheme == "https"
                            or request.headers.get("x-forwarded-proto") == "https"))
            return response

        logger_api.info(f"Access key protection active: ?key={access_key}")

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
        found: List[str] = []
        custom_dir = os.path.join(DATA_ROOT, "Custom_Uploads")
        if os.path.exists(custom_dir):
            for root, _, names in os.walk(custom_dir):
                for nm in names:
                    if nm.endswith(".csv"):
                        found.append(os.path.relpath(os.path.join(root, nm), DATA_ROOT).replace("\\", "/"))
        return {"datasets": sorted(found)}

    @app.post("/api/v6/upload-csv")
    async def upload_custom_csv(file: UploadFile = File(...)) -> Dict[str, Any]:
        if not file.filename or not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="Only .csv files are supported")

        custom_dir = os.path.join(DATA_ROOT, "Custom_Uploads")
        os.makedirs(custom_dir, exist_ok=True)

        # M3: Enforce Storage Quota (Max 50 files in Custom_Uploads/)
        existing_files = [os.path.join(custom_dir, f) for f in os.listdir(custom_dir) if f.endswith(".csv")]
        if len(existing_files) >= MAX_CUSTOM_UPLOADS:
            existing_files.sort(key=os.path.getmtime)
            while len(existing_files) >= MAX_CUSTOM_UPLOADS:
                oldest = existing_files.pop(0)
                try:
                    os.remove(oldest)
                    logger_api.info(f"Custom_Uploads quota cleanup: removed oldest file {oldest}")
                except Exception as exc:
                    logger_api.error(f"Quota cleanup failed for {oldest}: {exc}")

        # M3: Safe collision-free filename
        raw_name = os.path.basename(file.filename).replace(" ", "_")
        name_no_ext, ext = os.path.splitext(raw_name)
        dest_path = os.path.join(custom_dir, raw_name)
        if os.path.exists(dest_path):
            safe_name = f"{name_no_ext}_{uuid.uuid4().hex[:6]}{ext}"
            dest_path = os.path.join(custom_dir, safe_name)
        else:
            safe_name = raw_name

        # M3: File Size Limit (Max 5 MB) - Stream in 64 KB chunks
        total_size = 0
        try:
            with open(dest_path, "wb") as f_out:
                while True:
                    chunk = await file.read(65536)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_UPLOAD_BYTES:
                        f_out.close()
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                        raise HTTPException(status_code=413, detail=f"File size exceeds limit of {MAX_UPLOAD_BYTES // (1024*1024)} MB")
                    f_out.write(chunk)
        except HTTPException:
            raise
        except Exception as exc:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise HTTPException(status_code=500, detail=f"Failed to save file: {exc}")

        # Validate CSV format
        raw = read_raw_csv(dest_path)
        if raw is None:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise HTTPException(status_code=400, detail="CSV file is invalid or missing 25 sensor columns")

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
                detail=f"Serial port '{port}' is not available on this host. Detected ports: {detected_devices or 'None'}"
            )
        logger_serial.info(f"Bound ingestion pipeline to serial port {port} @ {baud} baud")
        return {
            "status": "available",
            "port": port,
            "baudrate": baud,
            "connected_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    @app.get("/api/v6/event-log")
    def get_event_logs() -> Dict[str, Any]:
        log_file = os.path.join(DATA_ROOT, "extubation_events_audit.json")
        logs: List[Dict[str, Any]] = []
        with EVENT_LOG_LOCK:
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                except Exception as exc:
                    logger_api.error(f"Error reading event log file: {exc}")
                    logs = []
        return {"total_events": len(logs), "events": logs}

    @app.post("/api/v6/event-log")
    def append_event_log(body: Dict[str, Any]) -> Dict[str, Any]:
        try:
            severity = int(body["severity_level"])
            cpri_val = float(body["cpri_percent"])
            frame_idx = int(body["frame_index"])
            time_sec = float(body["time_sec"])
            dataset = str(body.get("dataset", "unknown"))
            min_delta = float(body.get("min_delta", 0.0))
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid event log fields: {exc}")

        log_file = os.path.join(DATA_ROOT, "extubation_events_audit.json")
        with EVENT_LOG_LOCK:
            logs: List[Dict[str, Any]] = []
            if os.path.exists(log_file):
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        logs = json.load(f)
                except Exception as exc:
                    logger_api.error(f"Error reading event log before append: {exc}")
                    logs = []

            event = {
                "event_id": f"EVT-{len(logs) + 1:04d}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "dataset": dataset,
                "frame_index": frame_idx,
                "time_sec": round(time_sec, 3),
                "severity_level": severity,
                "cpri_percent": round(cpri_val, 1),
                "min_delta": round(min_delta, 1)
            }
            logs.append(event)

            # M2: Atomic File Write using temporary file replace
            temp_path: Optional[str] = None
            try:
                temp_fd, temp_path = tempfile.mkstemp(dir=DATA_ROOT, prefix="evt_", suffix=".tmp")
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f_tmp:
                    json.dump(logs, f_tmp, indent=2, ensure_ascii=False)
                os.replace(temp_path, log_file)
                logger_api.info(f"Event logged cleanly: {event['event_id']} (Level {severity}, CPRI {cpri_val}%)")
            except Exception as exc:
                logger_api.error(f"Atomic write failed for event log: {exc}")
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass

        return {"status": "recorded", "event": event}

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
        feats = extract_features(delta, model_holder.get("use_gradient", False))
        model = model_holder.get("model")
        proba = full_proba(model, feats) if model is not None else np.zeros((len(feats), N_CLASSES))
        raw_preds = (proba.argmax(axis=1) if model is not None
                     else np.zeros(len(feats), dtype=int))
        risk = cpri(proba)

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
            warming = i < KALMAN_WARMUP
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
                "probabilities": [round(float(p), 4) for p in proba[i]],
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
                await ws.close(code=1008)
                return
        await ws.accept()
        params = ws.query_params
        source_kind = params.get("source", "replay")
        pipeline = LivePipeline(model_holder.get("model"),
                                model_holder.get("use_gradient", False),
                                fuse_imu=params.get("fuse", "0") == "1")
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
                # Only ports this machine actually enumerates are accepted.
                attached = {p["device"] for p in list_serial_ports()}
                if port not in attached:
                    await ws.send_json({
                        "error": "unknown serial port",
                        "attached": sorted(attached),
                        "hint": "GET /api/v5/serial/ports lists what is connected",
                    })
                    await ws.close()
                    return
                src = SerialFrameSource(port, int(params.get("baud", "115200")))
            else:
                src = ReplayFrameSource(params.get("file", "Normal Mix/N_Mix_01.csv"),
                                        realtime=params.get("realtime", "1") == "1",
                                        loop=params.get("loop", "0") == "1")
            await ws.send_json({"event": "started", "source": src.name})
            loop = asyncio.get_running_loop()
            gen = src.frames()
            while True:
                frame = await loop.run_in_executor(None, lambda: next(gen, None))
                if frame is None:
                    break
                await ws.send_json(pipeline.process(frame))
            await ws.send_json({"event": "finished", "frames": pipeline.index})
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
SPEC_DETACH_MAX = 25000.0        # KES 2025 section 2.1: full detachment
SPEC_CONTACT_MIN = 30000.0       # KES 2025 section 2.1: direct finger contact
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
        per_class[label] = {
            "files": len(files), "usable": len(frames),
            "reach_detach_spec": reach_low, "reach_contact_spec": reach_high,
            "offset_contaminated": dirty, "under_min_frames": short,
            "min_raw": round(min(lows), 1) if lows else None,
            "median_frames": int(np.median(frames)) if frames else 0,
            "max_swing": round(max(swings), 1) if swings else None,
        }

    def _check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    def _agg(label_class: int) -> Dict[str, int]:
        tot = {"files": 0, "usable": 0, "reach_detach_spec": 0, "reach_contact_spec": 0}
        for label, v in per_class.items():
            leaf = label.split("/")[-1]
            if CLASS_MAPPING.get(leaf, {}).get("label") == label_class:
                for k in tot:
                    tot[k] += v[k]
        return tot

    def _agg_named(*folders: str) -> Dict[str, int]:
        """Aggregate specific folders by name, across sessions."""
        tot = {"files": 0, "usable": 0, "reach_detach_spec": 0, "reach_contact_spec": 0}
        for label, v in per_class.items():
            if label.split("/")[-1] in folders:
                for k in tot:
                    tot[k] += v[k]
        return tot

    # --- completeness comes first: a missing class used to remove its own check
    present = {CLASS_MAPPING[name.split("/")[-1]]["label"]
               for name in per_class if name.split("/")[-1] in CLASS_MAPPING}
    missing = [CLASS_LABEL_NAMES[c] for c in range(N_CLASSES) if c not in present]
    _check("all four classes recorded", not missing,
           f"missing: {', '.join(missing)}" if missing else "0/1/2/3 all present")

    peel = _agg(2)
    _check("Peel reaches <= 25,000 counts (KES 2025 s2.1)",
           peel["usable"] > 0 and peel["reach_detach_spec"] >= 0.8 * peel["usable"],
           f"{peel['reach_detach_spec']}/{peel['usable']} usable files (need >= 80%)"
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
        "The +/- on the file-level accuracy is RandomForest seed variation on a "
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
            out.append(
                f"No anomaly file reaches the <= {SPEC_DETACH_MAX:,.0f} count detachment "
                f"spec (KES 2025 s2.1); deepest is {deepest:,.0f}. Check the fixation "
                f"method used for these recordings before quoting a detachment claim.")
        else:
            out.append(
                f"Deepest anomaly count is {deepest:,.0f}, at or below the "
                f"{SPEC_DETACH_MAX:,.0f} detachment spec (KES 2025 s2.1).")

    out.append("LOOP 5 IMU signals are synthetic. No fusion number belongs in a "
               "results table.")

    counts = {lab: sum(1 for x in ds.labels if x == lab) for lab in sorted(set(ds.labels))}
    small = [(lab, n) for lab, n in counts.items() if n <= 10]
    if small:
        worst_lab, worst_n = min(small, key=lambda kv: kv[1])
        lo, hi = wilson(worst_n, worst_n)
        out.append(
            "Small classes: "
            + ", ".join(f"{CLASS_LABEL_NAMES[lab]} n={n}" for lab, n in small)
            + f". A perfect {worst_n}/{worst_n} on the smallest of them carries a 95% CI "
              f"of about {lo:.2f}-{hi:.2f}, so it is not evidence of 100% performance.")

    if ds.conventions.get("sensor") and not ds.conventions.get("signal"):
        out.append(
            f"All {ds.conventions['sensor']} recordings use Sensor-* columns, which the "
            "loader trusts as physical pad order without applying PAD_ORDER, while the "
            "live serial path always applies it. Accuracy figures are unaffected (the "
            "base features are permutation-invariant) but heatmaps, peel direction and "
            "the LOOP 3 figure depend on this unverified assumption. Confirm it on the "
            "bench before publishing a propagation direction.")
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
        f"## Random Forest ({rf['cv']}-level cross validation)", "",
        "| Metric | Value |", "|---|---|",
        f"| Accuracy | {rf['accuracy_mean']*100:.2f}%"
        + (f" ± {rf['accuracy_sd']*100:.2f} (n={n_seeds} seeds)" if n_seeds > 1 else "") + " |",
        f"| Macro F1 | {rf['macro_f1_mean']:.4f}"
        + (f" ± {rf['macro_f1_sd']:.4f}" if n_seeds > 1 else "") + " |",
        "| Tie-break | toward the more severe class |",
        f"| False alarm on normal files | {false_alarm_rate(rf['y_true'], rf['y_pred'])*100:.1f}% |",
        "",
        "_The ± above is RandomForest seed variation, not sampling uncertainty. "
        "Use the intervals below when quoting a result._",
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
    ap.add_argument("--eval", action="store_true", help="leave-one-file-out RF benchmark")
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

    if args.audit:
        return 0 if print_audit(audit_folder(args.audit)) else 2

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

    ds_hash = hashlib.sha256(f"{ds.n_files}_{len(ds.X)}_{args.calibration}_{args.gradient}".encode()).hexdigest()
    model = None
    if os.path.isfile(MODEL_PERSISTENCE_PATH):
        try:
            p_data = joblib.load(MODEL_PERSISTENCE_PATH)
            if isinstance(p_data, dict) and p_data.get("hash") == ds_hash and p_data.get("model") is not None:
                model = p_data["model"]
                logger_model.info(f"Loaded persisted model from {MODEL_PERSISTENCE_PATH} (hash={ds_hash[:8]})")
        except Exception as exc:
            logger_model.warning(f"Could not load persisted model: {exc}")

    if model is None:
        logger_model.info("Training global model on full dataset...")
        model = _new_rf(42).fit(ds.X, ds.y)
        try:
            joblib.dump({"model": model, "hash": ds_hash, "trained_at": time.time()}, MODEL_PERSISTENCE_PATH)
            logger_model.info(f"Persisted model to {MODEL_PERSISTENCE_PATH} (hash={ds_hash[:8]})")
        except Exception as exc:
            logger_model.error(f"Failed to persist model: {exc}")

    holder: Dict[str, Any] = {"model": model, "use_gradient": args.gradient,
                              "calibration": args.calibration}
    logger_model.info(f"Model active on {len(ds.X)} frames / {ds.n_files} files")

    if args.no_serve:
        return 0

    app = create_app(holder)
    port = pick_port(args.port, args.host)
    if args.host not in ("127.0.0.1", "localhost"):
        print("\n  WARNING: binding %s exposes an unauthenticated dashboard to the network." % args.host)
    print(f"\nDashboard: http://127.0.0.1:{port}")
    import uvicorn
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
