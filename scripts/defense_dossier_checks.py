#!/usr/bin/env python3
"""Reproduce every computed number in docs/MATHEMATICAL_DEFENSE_DOSSIER.md.

    python scripts/defense_dossier_checks.py           # compact JSON to stdout (2-4 min)
    python scripts/defense_dossier_checks.py --quick   # coarser sweeps, fewer trials

Read-only: it fits one in-memory model for a noise-only experiment and writes
nothing. Every assumed constant is named where it is used, marked ASSUMED.

  field_*   finite-volume solutions of div(eps grad phi) = 0 (quasi-static)
  tissue_*  why tissue behaves as a conductor at kHz, not as an eps_r 50-80 layer
  data_*    feature distributions, sign regimes, Mahalanobis, KL, nearest neighbours
  learning_*  VC and margin-bound arithmetic (shows the bounds are vacuous)
  annunciator_*  k-of-n vote arithmetic, lost onset frame, seed-variance F test
  noise_*   noise-gate leak, k-of-n amplification, causal median, noise-only alarms
  seed_*    power-on contamination against seed_plausibility(); recovery timing
  tube_*    shipped localiser against a matched-filter (Radon-style) estimator
  spec_*    the <= 25,000 count proof and the calibration-target hypothesis
  mech_*    bending and adhesion length scales, tent geometry, pad coupling map
  norm_*    unit consistency of the adaptive gates, affine invariance, NP pad budget

Companion: scripts/translation_plan_checks.py computes the CDC seed, adaptive-gate,
Kalman-ramp and pad-fault numbers that the dossier also cites.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from typing import Any, Dict, Sequence, Tuple

import numpy as np
from scipy import sparse, stats
from scipy.sparse.linalg import spsolve

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import main as m  # noqa: E402  (path set above on purpose)

EPS0 = 8.854187817e-12
RNG = np.random.default_rng(20260925)

# Stack named in the supervisor's brief (ASSUMED values, as stated there)
PAD_RADIUS = 3.5e-3            # 38.5 mm^2 per pad (progress report)
T_ADH, EPS_ADH = 0.30e-3, 3.5  # hydrocolloid
T_PI, EPS_PI = 25e-6, 3.4      # polyimide flex
EPS_AIR = 1.0


# ============================================================================
# Finite-volume field solver: cell-based permittivity, node-based potential
# ============================================================================
def _graded(a: float, b: float, h_min: float, growth: float, h_max: float) -> np.ndarray:
    pts, h = [a], h_min
    while pts[-1] + h < b:
        pts.append(pts[-1] + h)
        h = min(h * growth, h_max)
    pts.append(b)
    return np.array(pts)


def _merge(*arrays: np.ndarray, tol: float = 1e-9) -> np.ndarray:
    x = np.unique(np.concatenate(arrays))
    return x[np.concatenate([[True], np.diff(x) > tol])]


def _solve(gx: np.ndarray, gz: np.ndarray, eps_cell: np.ndarray, fixed: np.ndarray,
           value: np.ndarray, axisym: bool) -> Tuple[np.ndarray, Dict[Tuple[int, int, int, int], float]]:
    """eps_cell[i, j] is the permittivity of the cell between nodes (i, j) and
    (i+1, j+1). Returns node potentials and the face conductances (per eps0)."""
    nx, nz = len(gx), len(gz)
    idx = np.arange(nx * nz).reshape(nx, nz)
    xh = np.concatenate([[gx[0]], 0.5 * (gx[1:] + gx[:-1]), [gx[-1]]])
    zh = np.concatenate([[gz[0]], 0.5 * (gz[1:] + gz[:-1]), [gz[-1]]])
    rows, cols, vals, cond = [], [], [], {}

    def eps(i: int, j: int) -> float:
        return float(eps_cell[i, j]) if (0 <= i < nx - 1 and 0 <= j < nz - 1) else 0.0

    for i in range(nx):
        for j in range(nz):
            if i + 1 < nx:
                dx = gx[i + 1] - gx[i]
                span = eps(i, j - 1) * (gz[j] - zh[j]) + eps(i, j) * (zh[j + 1] - gz[j])
                g = (2 * math.pi * 0.5 * (gx[i] + gx[i + 1]) if axisym else 1.0) * span / dx
                if g > 0:
                    a, b = idx[i, j], idx[i + 1, j]
                    rows += [a, b, a, b]
                    cols += [a, b, b, a]
                    vals += [g, g, -g, -g]
                    cond[(i, j, i + 1, j)] = g
            if j + 1 < nz:
                dz = gz[j + 1] - gz[j]
                if axisym:
                    g = (eps(i - 1, j) * math.pi * (gx[i] ** 2 - xh[i] ** 2)
                         + eps(i, j) * math.pi * (xh[i + 1] ** 2 - gx[i] ** 2)) / dz
                else:
                    g = (eps(i - 1, j) * (gx[i] - xh[i]) + eps(i, j) * (xh[i + 1] - gx[i])) / dz
                if g > 0:
                    a, b = idx[i, j], idx[i, j + 1]
                    rows += [a, b, a, b]
                    cols += [a, b, b, a]
                    vals += [g, g, -g, -g]
                    cond[(i, j, i, j + 1)] = g
    n = nx * nz
    lap = sparse.csr_matrix((vals, (rows, cols)), shape=(n, n))
    fx = fixed.ravel()
    free = ~fx
    phi = value.ravel().astype(float).copy()
    phi[free] = spsolve(lap[free][:, free].tocsc(), -lap[free][:, fx] @ phi[fx])
    return phi.reshape(nx, nz), cond


def _charge(phi: np.ndarray, cond: Dict, mask: np.ndarray) -> float:
    """Net flux (per eps0) leaving a set of Dirichlet nodes."""
    q = 0.0
    for (i, j, k, l), g in cond.items():
        a_in, b_in = mask[i, j], mask[k, l]
        if a_in and not b_in:
            q += g * (phi[i, j] - phi[k, l])
        elif b_in and not a_in:
            q += g * (phi[k, l] - phi[i, j])
    return q


def axisym_pad(gap_air: float = 0.0, t_adh: float = T_ADH, finger_gap: float | None = None,
               finger_radius: float = 6e-3, film: float = 50e-6, eps_film: float = 3.0,
               r_max: float = 25e-3, z_max: float = 25e-3) -> Dict[str, float]:
    """Disk electrode on a PI flex; hydrocolloid below it, then an optional air gap,
    then the body surface as a grounded conductor at z = 0. Optional grounded
    finger (a conductor disk) resting on the top film."""
    z_e = gap_air + t_adh
    z_pi = z_e + T_PI
    z_top = z_pi + film
    r = _merge(_graded(0, PAD_RADIUS, 40e-6, 1.0, 40e-6), _graded(PAD_RADIUS, r_max, 10e-6, 1.18, 1.2e-3),
               np.array([finger_radius]))
    parts = [np.array([0.0])] if gap_air == 0 else [_graded(0, gap_air, 10e-6, 1.25, 0.25e-3)]
    parts += [_graded(gap_air, z_e, 10e-6, 1.2, 30e-6), _graded(z_e, z_pi, 5e-6, 1.0, 5e-6),
              _graded(z_pi, z_top, 10e-6, 1.0, 10e-6), _graded(z_top, z_max, 10e-6, 1.2, 1.5e-3)]
    z = _merge(*parts)
    nx, nz = len(r), len(z)
    zc = 0.5 * (z[1:] + z[:-1])
    eps_cell = np.full((nx - 1, nz - 1), EPS_AIR)
    eps_cell[:, (zc >= gap_air) & (zc < z_e)] = EPS_ADH
    eps_cell[:, (zc >= z_e) & (zc < z_pi)] = EPS_PI
    eps_cell[:, (zc >= z_pi) & (zc < z_top)] = eps_film
    fixed = np.zeros((nx, nz), dtype=bool)
    val = np.zeros((nx, nz))
    fixed[:, 0] = fixed[-1, :] = fixed[:, -1] = True
    elec = np.zeros_like(fixed)
    elec[r <= PAD_RADIUS + 1e-12, int(np.argmin(np.abs(z - z_e)))] = True
    fixed |= elec
    val[elec] = 1.0
    finger = np.zeros_like(fixed)
    if finger_gap is not None:
        finger[np.ix_(r <= finger_radius, z >= z_top + finger_gap - 1e-12)] = True
        finger &= ~elec
        fixed |= finger
    phi, cond = _solve(r, z, eps_cell, fixed, val, axisym=True)
    body = np.zeros_like(fixed)
    body[:, 0] = True
    return {"c_total_pf": _charge(phi, cond, elec) * EPS0 * 1e12,
            "c_body_pf": -_charge(phi, cond, body) * EPS0 * 1e12,
            "c_finger_pf": (-_charge(phi, cond, finger) * EPS0 * 1e12) if finger_gap is not None else 0.0,
            "c_parallel_plate_pf": EPS0 * math.pi * PAD_RADIUS ** 2 / (gap_air + t_adh / EPS_ADH) * 1e12}


def field_axisym(quick: bool) -> Dict[str, Any]:
    gaps = [0.0, 0.5e-3, 1.5e-3] if quick else [0.0, 0.05e-3, 0.1e-3, 0.25e-3, 0.5e-3, 1.0e-3, 1.5e-3, 3.0e-3]
    sweep = [{"gap_mm": g * 1e3, **{k: round(v, 4) for k, v in axisym_pad(gap_air=g).items()}} for g in gaps]
    press = axisym_pad(t_adh=0.8 * T_ADH)
    touch = axisym_pad(finger_gap=0.0)
    d_e = T_ADH / EPS_ADH
    s0 = EPS0 * math.pi * PAD_RADIUS ** 2 / d_e ** 2 * 1e9            # pF per mm
    s15 = EPS0 * math.pi * PAD_RADIUS ** 2 / (d_e + 1.5e-3) ** 2 * 1e9
    return {"lift_sweep": sweep,
            "press_20pct_body_pf": round(press["c_body_pf"], 4),
            "delta_body_press_pf": round(press["c_body_pf"] - sweep[0]["c_body_pf"], 4),
            "finger_total_pf": round(touch["c_total_pf"], 4), "finger_share_pf": round(touch["c_finger_pf"], 4),
            "delta_total_touch_pf": round(touch["c_total_pf"] - sweep[0]["c_total_pf"], 4),
            "dCdz_pp_at_0_pf_per_mm": round(-s0, 3), "dCdz_pp_at_1p5mm_pf_per_mm": round(-s15, 5),
            "sensitivity_ratio_1p5mm_vs_0": round(s15 / s0, 5)}


def planar_edge(x0: float, w: float = 7e-3, h: float = T_ADH) -> float:
    """2-D strip (width w) at height h over a grounded plane that exists only for
    x < 0; capacitance to the plane per metre of strip length."""
    x = _merge(np.linspace(-40e-3, 40e-3, 801), np.array([x0 - w / 2, x0 + w / 2, 0.0]))
    z = _merge(_graded(0, h, 10e-6, 1.15, 25e-6), _graded(h, 20e-3, 10e-6, 1.2, 1e-3))
    nx, nz = len(x), len(z)
    eps_cell = np.full((nx - 1, nz - 1), EPS_AIR)
    eps_cell[:, 0.5 * (z[1:] + z[:-1]) < h] = EPS_ADH
    fixed = np.zeros((nx, nz), dtype=bool)
    val = np.zeros((nx, nz))
    plane = np.zeros_like(fixed)
    plane[x <= 0, 0] = True
    fixed |= plane
    fixed[0, :] = fixed[-1, :] = fixed[:, -1] = True
    elec = np.zeros_like(fixed)
    elec[(x >= x0 - w / 2 - 1e-12) & (x <= x0 + w / 2 + 1e-12), int(np.argmin(np.abs(z - h)))] = True
    fixed |= elec
    val[elec] = 1.0
    phi, cond = _solve(x, z, eps_cell, fixed, val, axisym=False)
    return -_charge(phi, cond, plane) * EPS0


def field_ground_plane(quick: bool) -> Dict[str, Any]:
    offs = [-15e-3, -8e-3, 0.0] if quick else [-15e-3, -8e-3, -5e-3, -3.5e-3, -2e-3, 0.0, 2e-3, 3.5e-3, 6e-3]
    rows = [{"offset_mm": x0 * 1e3, "c_pf": round(planar_edge(x0) * 7e-3 * 1e12, 4)} for x0 in offs]
    for row in rows:
        row["fraction"] = round(row["c_pf"] / rows[0]["c_pf"], 4)
    return {"model": "2-D strip 7 mm wide over 0.3 mm hydrocolloid; plane only for x < 0; x 7 mm length",
            "rows": rows}


def shear_cell(offsets_mm: Sequence[float] = (0.0, 0.1, 0.25, 0.5), w: float = 5e-3, gap_b: float = 0.2e-3,
               h: float = 0.5e-3, eps_soft: float = 3.0, length: float = 5e-3) -> Dict[str, Any]:
    """Top electrode (width w) over two bottom electrodes; mutual capacitance to each
    receiver as the top slides by x. Differential = C_left - C_right."""
    out = []
    xl, xr = (-gap_b / 2 - w, -gap_b / 2), (gap_b / 2, gap_b / 2 + w)
    for dx in offsets_mm:
        xt = (-w / 2 - dx * 1e-3, w / 2 - dx * 1e-3)
        x = _merge(np.linspace(-12e-3, 12e-3, 961), np.array([*xl, *xr, *xt]))
        z = _merge(_graded(0, h, 10e-6, 1.1, 20e-6), _graded(h, 10e-3, 10e-6, 1.2, 0.8e-3))
        nx, nz = len(x), len(z)
        eps_cell = np.full((nx - 1, nz - 1), EPS_AIR)
        eps_cell[:, 0.5 * (z[1:] + z[:-1]) < h] = eps_soft
        fixed = np.zeros((nx, nz), dtype=bool)
        val = np.zeros((nx, nz))
        fixed[0, :] = fixed[-1, :] = fixed[:, -1] = True
        left, right, top = (np.zeros_like(fixed) for _ in range(3))
        left[(x >= xl[0] - 1e-12) & (x <= xl[1] + 1e-12), 0] = True
        right[(x >= xr[0] - 1e-12) & (x <= xr[1] + 1e-12), 0] = True
        top[(x >= xt[0] - 1e-12) & (x <= xt[1] + 1e-12), int(np.argmin(np.abs(z - h)))] = True
        fixed |= left | right | top
        val[top] = 1.0
        phi, cond = _solve(x, z, eps_cell, fixed, val, axisym=False)
        cl = -_charge(phi, cond, left) * EPS0 * length * 1e15
        cr = -_charge(phi, cond, right) * EPS0 * length * 1e15
        out.append({"shift_mm": dx, "c_left_ff": round(cl, 2), "c_right_ff": round(cr, 2),
                    "diff_ff": round(cl - cr, 2)})
    slope = (out[-1]["diff_ff"] - out[0]["diff_ff"]) / (offsets_mm[-1] - offsets_mm[0])
    g_mod, anchor = 100e3, 20e-3 * 20e-3        # ASSUMED: soft silicone G, 20 x 20 mm anchor
    shift = 10.0 / anchor / g_mod * h
    return {"rows": out, "slope_ff_per_mm": round(slope, 1), "shift_10N_mm": round(shift * 1e3, 4),
            "signal_10N_ff": round(slope * shift * 1e3, 2),
            "signal_10N_counts": round(slope * shift * 1e3 * 1e-3 * m.COUNTS_PER_PF, 3)}


# ============================================================================
# Tissue: conductor or dielectric at the sensing frequency?
# ============================================================================
# Four-Cole-Cole fits of Gabriel, Lau and Gabriel, Phys Med Biol 41:2271 (1996),
# Table 1 - the same table scripts/translation_plan_checks.py tissue() uses.
# (eps_inf, [(delta_eps, tau_s, alpha), ...], sigma_ionic S/m)
GABRIEL_1996 = {
    "stratum corneum (dry skin)": (4.0, [(32.0, 7.23e-12, 0.0), (1100.0, 32.48e-9, 0.20)], 0.0002),
    "dermis (wet skin)": (4.0, [(39.0, 7.96e-12, 0.10), (280.0, 79.58e-9, 0.0),
                                (3.0e4, 1.59e-6, 0.16), (3.0e4, 1.592e-3, 0.20)], 0.0004),
    "muscle": (4.0, [(50.0, 7.23e-12, 0.10), (7000.0, 353.68e-9, 0.10),
                     (1.2e6, 318.31e-6, 0.10), (2.5e7, 2.274e-3, 0.0)], 0.2),
}
TISSUE_STACK = (("stratum corneum (dry skin)", 20e-6), ("dermis (wet skin)", 2e-3), ("muscle", 10e-3))  # ASSUMED


def _eps_tissue(name: str, f: float) -> complex:
    """Complex relative permittivity eps' - j sigma/(w eps0) at frequency f."""
    einf, terms, sig = GABRIEL_1996[name]
    w = 2 * math.pi * f
    eps = complex(einf, 0.0)
    for d, tau, a in terms:
        eps += d / (1.0 + (1j * w * tau) ** (1.0 - a))
    return eps + sig / (1j * w * EPS0)


def _stack(f: float) -> Tuple[list, float, float]:
    """Series impedance of each layer under one pad; tissue share of |Z| and the
    change in apparent (parallel-equivalent) capacitance that the tissue causes."""
    area, w = math.pi * PAD_RADIUS ** 2, 2 * math.pi * f
    z_h = T_ADH / (1j * w * EPS0 * EPS_ADH * area)
    rows = [{"layer": "hydrocolloid", "eps_r": EPS_ADH, "sigma_S_per_m": 0.0,
             "abs_Z_ohm": round(abs(z_h), 1), "conduction_over_displacement": 0.0}]
    z_t = 0j
    for name, t in TISSUE_STACK:
        e = _eps_tissue(name, f)
        z = t / (1j * w * EPS0 * e * area)
        z_t += z
        rows.append({"layer": name, "eps_r": round(e.real), "sigma_S_per_m": round(-e.imag * w * EPS0, 4),
                     "abs_Z_ohm": round(abs(z), 1), "conduction_over_displacement": round(-e.imag / e.real, 3)})
    cp = (1.0 / (z_h + z_t)).imag / w           # parallel-equivalent capacitance of the whole stack
    return rows, 100.0 * abs(z_t) / abs(z_h + z_t), 100.0 * (cp / (1.0 / (z_h.imag * -w)) - 1.0)


def tissue_regime() -> Dict[str, Any]:
    """Is tissue a dielectric or a conductor at the sensing frequency? 250 kHz is
    ASSUMED (the CapSense scan settings are [FILL] in docs/Hardware_Deck_Spec.md),
    so the share is also reported across 32 kHz - 5 MHz."""
    area = math.pi * PAD_RADIUS ** 2
    rows, share, dcap = _stack(250e3)
    sweep = {}
    for f in (32e3, 100e3, 250e3, 1e6, 5e6):
        _, s, dc = _stack(f)
        sweep[f"{f / 1e3:g} kHz"] = {"tissue_share_of_Z_pct": round(s, 3), "apparent_C_change_pct": round(dc, 3)}
    return {"layers": rows, "tissue_share_pct": round(share, 3), "apparent_C_change_pct": round(dcap, 3),
            "by_frequency": sweep,
            "if_dermis_were_3mm_eps65_pf": round(EPS0 * area / (T_ADH / EPS_ADH + 3e-3 / 65) * 1e12, 3),
            "tissue_as_conductor_pf": round(EPS0 * area / (T_ADH / EPS_ADH) * 1e12, 3)}


# ============================================================================
# Data: distributions, distances, overlap
# ============================================================================
SCEN = {"N_base": "Baseline", "Brief Touch": "Touching", "Press": "Touching", "Friction": "Friction",
        "Vertical Pull NO G": "Pulling", "Horizontal Pull NO G": "Pulling", "PowerP": "Pulling",
        "Peel": "Peeling", "Normal Mix": "Normal Mix (ref)"}
NAMES5 = ["Baseline", "Touching", "Friction", "Pulling", "Peeling"]


def _lw(Z: np.ndarray) -> np.ndarray:
    from sklearn.covariance import LedoitWolf
    return LedoitWolf().fit(Z).covariance_


def _gauss_kl(mu0, s0, mu1, s1) -> float:
    s1i = np.linalg.inv(s1)
    d = mu1 - mu0
    return 0.5 * (np.trace(s1i @ s0) + d @ s1i @ d - len(mu0)
                  + np.linalg.slogdet(s1)[1] - np.linalg.slogdet(s0)[1])


def _knn_kl(P: np.ndarray, Q: np.ndarray, k: int = 5) -> float:
    """Wang, Kulkarni, Verdu (2009) k-NN estimator of D(P||Q)."""
    from scipy.spatial import cKDTree
    n, d = P.shape
    rho = np.maximum(cKDTree(P).query(P, k=k + 1)[0][:, -1], 1e-9)
    nu = np.maximum(cKDTree(Q).query(P, k=k)[0][:, -1], 1e-9)
    return float(d * np.mean(np.log(nu / rho)) + math.log(len(Q) / (n - 1)))


def data_geometry(ds: Any) -> Dict[str, Any]:
    from scipy.spatial import cKDTree
    X = np.asarray(ds.X, dtype=float)
    scen, fidx, active = [], [], []
    for fi, (fname, d) in enumerate(zip(ds.files, ds.frames)):
        folder = fname.replace("\\", "/").split("/")[0]
        scen += [SCEN.get(folder, folder)] * len(d)
        fidx += [fi] * len(d)
        active += list(np.max(np.abs(d), axis=1) >= m.NOISE_GATE_COUNTS)
    scen, fidx, active = np.array(scen), np.array(fidx), np.array(active)
    assert len(scen) == len(X)
    summary = {}
    for s in NAMES5 + ["Normal Mix (ref)"]:
        sel = scen == s
        summary[s] = {"files": int(len(set(fidx[sel]))), "frames": int(sel.sum()),
                      "active": int((sel & active).sum()),
                      "median_min": round(float(np.median(X[sel, 25])), 1),
                      "median_max": round(float(np.median(X[sel, 26])), 1),
                      "frac_any_pad_le_-300": round(float(np.mean(X[sel, 29] > 0)), 3),
                      "frac_any_pad_ge_+300": round(float(np.mean(X[sel, 32] > 0)), 3)}
    Z = (X - X.mean(0)) / (X.std(0) + 1e-9)
    use = {s: (scen == s) & (active | (s == "Baseline")) for s in NAMES5}
    pooled = np.vstack([Z[use[s]] - Z[use[s]].mean(0) for s in NAMES5])
    inv34 = np.linalg.inv(_lw(pooled))
    st = list(range(25, 34))
    inv9 = np.linalg.inv(_lw(pooled[:, st]))
    maha34, maha9, kl, knn = {}, {}, {}, {}
    for i, a in enumerate(NAMES5):
        for b in NAMES5[i + 1:]:
            da = Z[use[a]].mean(0) - Z[use[b]].mean(0)
            key = f"{a}|{b}"
            maha34[key] = round(float(math.sqrt(da @ inv34 @ da)), 2)
            maha9[key] = round(float(math.sqrt(da[st] @ inv9 @ da[st])), 2)
            A, B = Z[use[a]][:, st], Z[use[b]][:, st]
            kl[key] = [round(_gauss_kl(A.mean(0), _lw(A), B.mean(0), _lw(B)), 1),
                       round(_gauss_kl(B.mean(0), _lw(B), A.mean(0), _lw(A)), 1)]
            pa = Z[use[a]][:, 25:29] + RNG.normal(0, 1e-6, (int(use[a].sum()), 4))
            pb = Z[use[b]][:, 25:29] + RNG.normal(0, 1e-6, (int(use[b].sum()), 4))
            knn[key] = [round(_knn_kl(pa, pb), 2), round(_knn_kl(pb, pa), 2)]
    normal = np.isin(scen, ["Baseline", "Touching", "Friction", "Normal Mix (ref)"])
    anomaly = np.isin(scen, ["Pulling", "Peeling"])
    act = np.where(active)[0]
    tree = cKDTree(Z[act])
    overlap = {}
    for s in ["Pulling", "Peeling", "Touching", "Friction"]:
        sel = np.where((scen == s) & active)[0]
        hits = 0
        for q in sel:
            dd, ii = tree.query(Z[q], k=60)
            for j in act[ii]:
                if fidx[j] != fidx[q]:
                    hits += int((s in ("Pulling", "Peeling") and normal[j])
                                or (s in ("Touching", "Friction") and anomaly[j]))
                    break
        overlap[s] = {"active": int(len(sel)), "nn_opposite": hits, "rate": round(hits / max(len(sel), 1), 3)}
    ctx = {}
    for folder in ("Vertical Pull NO G", "Peel", "Horizontal Pull NO G"):
        lens = [len(d) for fn, d in zip(ds.files, ds.frames) if fn.replace("\\", "/").startswith(folder)]
        ctx[folder] = {"median_frames": int(np.median(lens)),
                       "median_s": round(float(np.median(lens)) * m.SAMPLE_PERIOD_S, 2),
                       "windows6_after_warmup": int(sum(max(0, n - m.KALMAN_WARMUP - 5) for n in lens)),
                       "slack_frames_median": int(np.median(lens)) - m.KALMAN_WARMUP - 6}
    # Sign regimes: which frames carry a deep negative pad, a strong positive pad, both, neither.
    folders = np.array([fn.replace("\\", "/").split("/")[0] for fn, d in zip(ds.files, ds.frames) for _ in range(len(d))])

    def regimes(sel: np.ndarray) -> Dict[str, Any]:
        neg, pos = X[sel, 29] > 0, X[sel, 32] > 0
        return {"frames": int(sel.sum()), "neg_only": round(float(np.mean(neg & ~pos)), 3),
                "pos_only": round(float(np.mean(pos & ~neg)), 3), "mixed": round(float(np.mean(neg & pos)), 3),
                "neither": round(float(np.mean(~neg & ~pos)), 3),
                "files_with_a_neg_only_frame": f"{len(set(fidx[sel][neg & ~pos]))}/{len(set(fidx[sel]))}"}
    polarity = {s: regimes(use[s]) for s in NAMES5}
    polarity_folder = {f: regimes((folders == f) & active) for f in sorted(set(folders)) if f != "N_base"}
    bayes = {k: round(float(stats.norm.cdf(-v / 2.0)), 4) for k, v in maha34.items()}
    return {"summary": summary, "maha34": maha34, "bayes_err_equal_cov_gauss": bayes, "maha9": maha9,
            "gauss_kl9": kl, "knn_kl4": knn, "nn_overlap": overlap, "context": ctx,
            "polarity": polarity, "polarity_by_folder": polarity_folder}


# ============================================================================
# Learning-theory arithmetic
# ============================================================================
def learning_bounds() -> Dict[str, Any]:
    leaves, iters = 31, 150

    def vc_gap(vc: int, n: int, delta: float = 0.05) -> Any:
        if vc >= n:
            return "vacuous (VC >= n)"
        return round(math.sqrt((8.0 / n) * (vc * math.log(2 * math.e * n / vc) + math.log(4 / delta))), 3)
    rows = {}
    for label, vc in (("one tree, L=31 (lower bound)", leaves), ("HGB score, 150 trees (lower bound)", iters * (leaves - 1) + 1)):
        rows[label] = {"vc_lower": vc, "gap_n3349": vc_gap(vc, 3349), "gap_n81": vc_gap(vc, 81)}
    margin = {f"theta={t},n={n}": round(math.sqrt(leaves * math.log(n / leaves + 1) ** 2 / (n * t * t)), 3)
              for t in (0.1, 0.3, 0.5) for n in (3349, 81)}
    return {"vc": rows, "margin_term": margin, "trees_total": iters * 4}


def _p_alarm(m_frames: int, p: float, window: int = 7, votes: int = 6) -> float:
    """P(the k-of-n annunciator fires) when an event offers m_frames post-warmup
    frames, each voting independently with probability p. Exact enumeration."""
    total = 0.0
    for mask in range(1 << m_frames):
        bits = [(mask >> i) & 1 for i in range(m_frames)]
        if any(sum(bits[max(0, t - window + 1):t + 1]) >= votes for t in range(m_frames)):
            k = sum(bits)
            total += p ** k * (1 - p) ** (m_frames - k)
    return total


def annunciator_arithmetic() -> Dict[str, Any]:
    cfg = m.AlarmConfig()
    amp = {}
    for p in (0.99, 0.95, 0.9, 0.8):
        amp[str(p)] = {f"m={k}": [round(_p_alarm(k, p, cfg.window, cfg.min_votes), 3),
                                  round(_p_alarm(k - 1, p, cfg.window, cfg.min_votes), 3)]
                       for k in (6, 7, 8, 10)}
    # Seed spread quoted in the docs: BiLSTM 0.9531 +/- 0.0230 vs RF 0.9518 +/- 0.0038
    s_b, s_r, m_b, m_r = 0.0230, 0.0038, 0.9531, 0.9518
    seeds = {}
    for n in (3, 5, 10):
        se = math.sqrt(s_b ** 2 / n + s_r ** 2 / n)
        df = se ** 4 / ((s_b ** 2 / n) ** 2 / (n - 1) + (s_r ** 2 / n) ** 2 / (n - 1))
        seeds[f"n={n}"] = {"F": round((s_b / s_r) ** 2, 1), "F_crit_95": round(float(stats.f.ppf(0.95, n - 1, n - 1)), 2),
                           "p_var": float(f"{stats.f.sf((s_b / s_r) ** 2, n - 1, n - 1):.2g}"),
                           "welch_t": round((m_b - m_r) / se, 3),
                           "p_mean": round(float(2 * stats.t.sf(abs(m_b - m_r) / se, df)), 3)}
    return {"p_alarm_[m, m_minus_1]": amp, "sd_ratio": round(s_b / s_r, 2), "var_ratio": round((s_b / s_r) ** 2, 1),
            "seed_tests": seeds}


# ============================================================================
# Noise, gate, vote, causal median
# ============================================================================
def noise_analysis(model: Any) -> Dict[str, Any]:
    gate = m.NOISE_GATE_COUNTS
    leak = {str(s): round(1 - (1 - 2 * float(stats.norm.sf(gate / s))) ** m.N_PADS, 4)
            for s in (8.4, 15, 20, 30, 45, 60, 120)}
    lo, hi = 1.0, 60.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if 1 - (1 - 2 * float(stats.norm.sf(gate / mid))) ** m.N_PADS < 0.05 else (lo, mid)
    kofn = {str(p): round(float(stats.binom.sf(5, 7, p)), 4) for p in (0.99, 0.95, 0.9, 0.8, 0.7, 0.6)}
    step = np.r_[np.zeros(10), np.ones(8), np.zeros(10)]
    med = np.array([np.median(step[max(0, i - 2):i + 1]) for i in range(len(step))])
    white = RNG.normal(0, 1, 400_000)
    filt = np.median(np.lib.stride_tricks.sliding_window_view(white, 3), axis=1)
    res = {"leak_by_sigma": leak, "sigma_5pct_leak": round(lo, 1), "p_6of7": kofn,
           "median3": {"onset_delay": int(np.argmax(med > .5) - np.argmax(step > .5)),
                       "trail_extension": int(np.where(med > .5)[0][-1] - np.where(step > .5)[0][-1]),
                       "var_ratio": round(float(np.var(filt)), 3),
                       "lag1": round(float(np.corrcoef(filt[:-1], filt[1:])[0, 1]), 3),
                       "lag2": round(float(np.corrcoef(filt[:-2], filt[2:])[0, 1]), 3)}}
    alarms = {}
    frames = 6000
    for sigma in (30.0, 60.0, 120.0):
        noise = RNG.normal(0, sigma, (frames, m.N_PADS))
        medf = noise.copy()
        medf[2:] = np.median(np.stack([noise[:-2], noise[1:-1], noise[2:]]), axis=0)
        row = {}
        for name, d in (("raw", noise), ("median3", medf)):
            lvl = m.classify_deltas(model, d)[1]
            deb = m.AlarmDebouncer()
            ann = np.array([deb.update(int(v)) for v in lvl])
            votes = (lvl >= 2).astype(float)
            onsets = int(np.sum((ann[1:] >= 2) & (ann[:-1] < 2)) + (ann[0] >= 2))
            row[name] = {"vote_ge2": round(float(votes.mean()), 4),
                         "vote_lag1": round(float(np.corrcoef(votes[:-1], votes[1:])[0, 1]), 3) if votes.std() else None,
                         "alarms_per_h": round(onsets / (frames * m.SAMPLE_PERIOD_S / 3600), 2)}
        alarms[str(int(sigma))] = row
    res["noise_only_alarms"] = alarms
    return res


# ============================================================================
# Power-on contamination and the software safety layers
# ============================================================================
def seed_checks() -> Dict[str, Any]:
    import pandas as pd
    seeds = np.array([pd.read_csv(p)[m.SENSOR_COLS].to_numpy(float)[:m.KALMAN_WARMUP].mean(0)
                      for p in sorted(glob.glob(os.path.join(ROOT, "Data", "N_base", "*.csv")))])
    press = {}
    for k in (1, 2, 5):
        for P in (200, 400, 500, 600, 800, 1200):
            hits = 0
            for s in seeds:
                for _ in range(40):
                    c = s.copy()
                    c[RNG.choice(m.N_PADS, k, replace=False)] += P
                    hits += m.seed_plausibility(c)["status"] != "attached_band"
            press[f"k={k},+{P}"] = round(hits / (40 * len(seeds)), 3)
    loose = {f"-{X}": f"{sum(m.seed_plausibility(s - X)['status'] != 'attached_band' for s in seeds)}/{len(seeds)}"
             for X in (200, 400, 500, 600, 800)}
    recov = {}
    for P in (400, 800, 1500):
        lp = m.LivePipeline(model=None)
        eng = back = None
        for i in range(80):
            fr = np.full(m.N_PADS, m.BASELINE_COUNTS) + RNG.normal(0, 8.4, m.N_PADS)
            if i < 12:
                fr[3] += P
            out = lp.process(fr)
            if i >= 12 and eng is None and 4 in out["quiescent_recovery"]["active_pads"]:
                eng = i
            if i > 12 and back is None and abs(out["deltas"][3]) < m.NOISE_GATE_COUNTS:
                back = i
        recov[f"+{P}"] = {"engaged_s": round((eng - 12) * m.SAMPLE_PERIOD_S, 2) if eng else None,
                          "inside_gate_s": round((back - 12) * m.SAMPLE_PERIOD_S, 2) if back else None}
    sd = float(np.std(m.SEED_RESTING_SHAPE - np.median(m.SEED_RESTING_SHAPE)))
    return {"press_detect": press, "loose_detect": loose, "recovery": recov,
            "shape_sd_counts": round(sd, 1), "shape_sd_pf": round(sd / m.COUNTS_PER_PF, 2)}


# ============================================================================
# Static tube localisation
# ============================================================================
def _pads_mm() -> np.ndarray:
    return np.array([[m.PHYSICAL_PAD_COORDS[i][0] * 0.9, m.PHYSICAL_PAD_COORDS[i][1] * 1.2] for i in range(1, 26)])


def _band(theta: float, rho: float, xy: np.ndarray, half: float, depth: float) -> np.ndarray:
    n = np.array([math.cos(math.radians(theta)), math.sin(math.radians(theta))])
    return depth * np.clip((half - np.abs(xy @ n - rho) + 3.5) / 7.0, 0, 1)


def _templates(xy: np.ndarray, half: float = 6.0) -> Tuple[np.ndarray, list]:
    rows, params = [], []
    for th in np.arange(0, 180, 5.0):
        proj = xy @ np.array([math.cos(math.radians(th)), math.sin(math.radians(th))])
        for rho in np.arange(proj.min() - 3, proj.max() + 3, 2.0):
            t = np.clip((half - np.abs(proj - rho) + 3.5) / 7.0, 0, 1)
            if t.sum() >= 2.5 and t.std() > 0:
                rows.append((t - t.mean()) / (t.std() * math.sqrt(len(t))))
                params.append((th, rho))
    return np.array(rows), params


def _mf(values: np.ndarray, T: np.ndarray, params: list, n_perm: int = 300) -> Tuple[float, float]:
    v = np.median(values) - values
    z = (v - v.mean()) / (v.std() * math.sqrt(len(v)) + 1e-12)
    sc = T @ z
    b = int(np.argmax(sc))
    perm = np.max(T @ np.array([RNG.permutation(z) for _ in range(n_perm)]).T, axis=0)
    return params[b][0], float((1 + np.sum(perm >= sc[b])) / (1 + n_perm))


def tube_checks(trials: int) -> Dict[str, Any]:
    xy = _pads_mm()
    T, params = _templates(xy)
    shape_pf = (m.SEED_RESTING_SHAPE - np.median(m.SEED_RESTING_SHAPE)) / m.COUNTS_PER_PF
    ship0 = m.detect_static_tube_localization(30.0 + shape_pf)
    diag_rho = float(np.array([45.0, 60.0]) @ np.array([math.cos(math.radians(45)), math.sin(math.radians(45))]))
    cases = {"none": None, "vertical": (0.0, 45.0), "horizontal": (90.0, 60.0), "diagonal45": (45.0, diag_rho)}
    sim = {}
    for sp in (0.2, 1.0, 3.0):
        for cname, cfg in cases.items():
            ds_, dm, axok, errs = 0, 0, 0, []
            for _ in range(trials):
                vals = 30.0 + RNG.normal(0, sp, 25) + RNG.normal(0, 0.05, 25)
                if cfg:
                    vals -= _band(cfg[0], cfg[1], xy, 6.0, 3.7)
                s = m.detect_static_tube_localization(vals)
                ds_ += bool(s["detected"])
                if cfg and s["detected"]:
                    want = {0.0: "vertical", 90.0: "horizontal"}.get(cfg[0], "diagonal")
                    axok += s["axis_orientation"] == want
                th, p = _mf(vals, T, params)
                if p < 0.01:
                    dm += 1
                    if cfg:
                        errs.append(abs(((th - cfg[0]) + 90) % 180 - 90))
            sim[f"sd{sp}|{cname}"] = {"ship": round(ds_ / trials, 2),
                                      "ship_axis_ok": round(axok / max(ds_, 1), 2) if cfg else None,
                                      "mf": round(dm / trials, 2),
                                      "mf_err_deg": round(float(np.median(errs)), 1) if errs else None}
    return {"shipped_on_resting_shape": {"detected": ship0["detected"], "pads": ship0["shadowed_pads"],
                                         "axis": ship0["axis_orientation"], "thr_pf": ship0["adaptive_threshold_pf"]},
            "resting_shape_sd_pf": round(float(np.std(shape_pf)), 2), "sim": sim,
            "true_45deg_in_percent_space_deg": round(math.degrees(math.atan(0.9 / 1.2)), 1)}


# ============================================================================
# Spec and calibration-target hypothesis
# ============================================================================
def spec_checks() -> Dict[str, Any]:
    t15 = 0.85 * (2 ** 15 - 1)
    return {"reach": m.spec_detach_reachability(m.SPEC_DETACH_MAX),
            "c0_needed_pf": round((m.BASELINE_COUNTS - m.SPEC_DETACH_MAX) / m.COUNTS_PER_PF, 2),
            "target_85pct_15bit": round(t15, 1), "target_85pct_16bit": round(0.85 * (2 ** 16 - 1), 1),
            "resting_vs_target_pct": round(100 * (28025.0 - t15) / t15, 2),
            "spec_relative_drop_pct": round(100 * 3000 / m.BASELINE_COUNTS, 2),
            "deepest_peel_relative_pct": round(100 * 902.4 / m.BASELINE_COUNTS, 2)}


# ============================================================================
# Mechanics: bending, adhesion and the tent
# ============================================================================
def mech_checks() -> Dict[str, Any]:
    def D(E: float, t: float, nu: float) -> float:
        return E * t ** 3 / (12 * (1 - nu ** 2))
    Ds = {"PI 25um": D(2.5e9, 25e-6, 0.34), "Cu 18um solid": D(117e9, 18e-6, 0.34),
          "silicone 0.5mm": D(1e6, 0.5e-3, 0.49)}
    ea = [{"layer": k, "D": float(f"{v:.3g}"), "gamma": g, "L_ea_mm": round(math.sqrt(v / (2 * g)) * 1e3, 3),
           "r_land_mm": round(math.sqrt(math.pi * v / (4 * g)) * 1e3, 3)}
          for k, v in Ds.items() for g in (10.0, 50.0, 200.0)]            # ASSUMED gamma range, J/m^2
    het = [{"D": d_, "E_adh_kPa": e / 1e3, "lambda_mm": round((4 * d_ / (e / T_ADH)) ** 0.25 * 1e3, 3)}
           for d_ in (1e-6, 1e-5, 1e-4) for e in (20e3, 200e3)]
    ss = [{"D": d_, "h_mm": h * 1e3, "ell_mm": round((18 * d_ * h * h / 50.0) ** 0.25 * 1e3, 2),
           "h_over_ell": round(h / (18 * d_ * h * h / 50.0) ** 0.25, 2)}
          for d_ in (1e-6, 1e-5, 1e-4) for h in (3e-3, 8e-3, 11e-3)]
    a = 5.25e-3
    xy = _pads_mm()
    c_flush = EPS0 * math.pi * PAD_RADIUS ** 2 / (T_ADH / EPS_ADH) * 1e12
    c_raised = EPS0 * math.pi * PAD_RADIUS ** 2 / (T_ADH / EPS_ADH + a) * 1e12
    pads = []
    for i, (x, y) in enumerate(xy, start=1):
        frac = float(np.clip((a * 1e3 + 0.5 - abs(x - 45.0) + 3.5) / 7.0, 0, 1))
        if frac > 0:
            pads.append({"pad": i, "x": round(x, 1), "y": round(y, 1), "raised": round(frac, 2),
                         "c_body_pf": round(c_flush * (1 - frac) + c_raised * frac, 3)})
    return {"D": {k: float(f"{v:.3g}") for k, v in Ds.items()}, "elastoadhesive": ea, "hetenyi": het,
            "small_slope": ss, "tent_area_one_side_mm2": round(a * a * (1 - math.pi / 4) * 1e6, 2),
            "c_flush_pp_pf": round(c_flush, 3), "c_raised_pp_pf": round(c_raised, 4), "pads": pads,
            "d_over_eps_needed_for_20pf_um": round(EPS0 * math.pi * PAD_RADIUS ** 2 / 20e-12 * 1e6, 1),
            "stack_d_over_eps_um": round((T_ADH / EPS_ADH + T_PI / EPS_PI) * 1e6, 1)}


# ============================================================================
# Normalisation: gate units, affine invariance, per-pad signal budget
# ============================================================================
def normalisation_checks(sweep: Sequence[Dict[str, float]]) -> Dict[str, Any]:
    k = m.COUNTS_PER_PF
    offset = m.BASELINE_COUNTS - m.NOMINAL_BASELINE_PF * k       # the repo's transfer: N = offset + k * C
    sigma = 8.6                                                   # bench per-pad noise sd, counts (PHYSICS_TO_FEATURE_MAP)
    gates = {}
    for c in (15.0, 30.0, 35.0):
        gc = m.analyze_surface_topography(np.full(m.N_PADS, offset + k * c), is_cdc_pf=False)["adaptive_lift_gates"][0]
        gp = m.analyze_surface_topography(np.full(m.N_PADS, c), is_cdc_pf=True)["adaptive_lift_gates"][0]
        p1 = float(stats.norm.cdf(gp * k / sigma))
        gates[f"{c:g} pF"] = {"counts_mode_gate": gc, "counts_mode_gate_pf": round(gc / k, 2),
                              "pf_mode_gate_pf": gp, "pf_mode_gate_counts": round(gp * k, 1),
                              "pf_mode_false_lift_per_pad_frame": round(p1, 4),
                              "pf_mode_any_of_25_pads": round(1 - (1 - p1) ** m.N_PADS, 3)}
    target = 0.85 * (2 ** 15 - 1)
    transfers = {"affine, repo constants": lambda c, c0: offset + k * c,
                 "per-channel 85% target": lambda c, c0: target + k * (c - c0),
                 "85% target, gain x1.3": lambda c, c0: target + 1.3 * k * (c - c0)}
    pads = {"C_par 26 + C_body 4": (26.0, 4.0), "C_par 10 + C_body 25": (10.0, 25.0), "C_par 26 + C_body 0.53": (26.0, 0.53)}
    invariance = {}
    for pname, (cp, cb) in pads.items():
        c_att, c_air, c_now = cp + cb, cp, cp + 0.5 * cb                  # half of the body coupling lost
        for tname, T in transfers.items():
            n_att, n_air, n_now = T(c_att, c_att), T(c_air, c_att), T(c_now, c_att)
            invariance[f"{pname} | {tname}"] = {
                "delta_counts_over_N0_pct": round(100 * (n_now - n_att) / n_att, 3),
                "delta_pf_over_C0_pct": round(100 * (c_now - c_att) / c_att, 2),
                "detachment_fraction": round((n_att - n_now) / (n_att - n_air), 4)}
    zb = float(stats.norm.isf(0.05))
    budget = {}
    for a in (1e-3, 1e-4):
        for fs in (0.5, 1.0):
            s_min = (float(stats.norm.isf(a)) + zb) * sigma / fs
            budget[f"alpha={a:g}, f*={fs:g}"] = {"S_min_counts": round(s_min, 1), "S_min_pf": round(s_min / k, 2)}
    cb = {row["gap_mm"]: row["c_body_pf"] for row in sweep}
    lift = {"all_body_coupling_counts": round(-cb[0.0] * k, 1)}
    for z0, z1 in ((0.0, 0.5), (0.0, 3.0), (1.5, 3.0)):
        if z0 in cb and z1 in cb:
            lift[f"lift_{z0:g}_to_{z1:g}_mm_counts"] = round(-(cb[z0] - cb[z1]) * k, 1)
    if 1.5 in cb:
        lift["span_of_pad_tented_at_1.5_mm_counts"] = round(cb[1.5] * k, 1)
    return {"sigma_counts": sigma, "gate_units": gates, "floor_binds_below": {"counts": round(150 / 0.011), "pf": round(0.15 / 0.011, 1)},
            "affine_invariance": invariance, "np_span_budget": budget, "lift_signal_brief_stack": lift}


def main_cli() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    ds = m.load_dataset(calibration="kalman", verbose=False)
    model = m._new_rf(42).fit(ds.X, ds.y)
    field = field_axisym(args.quick)
    report = {"field_axisym": field, "field_plane_edge": field_ground_plane(args.quick),
              "field_shear_cell": shear_cell(), "tissue": tissue_regime(), "data": data_geometry(ds),
              "learning": learning_bounds(), "annunciator": annunciator_arithmetic(),
              "noise": noise_analysis(model), "seed": seed_checks(),
              "tube": tube_checks(20 if args.quick else 60), "spec": spec_checks(), "mech": mech_checks(),
              "norm": normalisation_checks(field["lift_sweep"])}
    print(json.dumps(report, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
