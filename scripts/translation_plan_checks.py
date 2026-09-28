#!/usr/bin/env python3
"""Reproduce every computed number in docs/TRANSLATION_PLAN_24M.md.

    python scripts/translation_plan_checks.py            # human-readable report
    python scripts/translation_plan_checks.py --json     # same numbers as JSON

Read-only. It trains nothing and writes nothing. It imports main.py for the
constants and classes that ship (KalmanBaseline, LivePipeline,
analyze_surface_topography, spec_detach_reachability) so that a check here
describes the running code, not a re-implementation of it.

Sections, in the order the plan uses them:
  1. timing floor of the annunciator      (why "5.60 s" is not a lead time)
  2. Kalman slow-ramp blind spot          (events slower than this are drift)
  3. CDC seed-plausibility check          (what the CDC path can and cannot see)
  4. per-pad adaptive lift gates          (how far they actually adapt)
  5. horizontal-pull depth by calibration (why two documents quote -64 and -71)
  6. ICU trial arithmetic                 (events, power, false-alarm precision)
  7. tissue permittivity at 32-250 kHz    (why "skin eps_r 50-80" is the wrong band)
  8. pad-to-body coupling, order of size  (what 869 counts of peel implies)
  9. rig suction force                    (what -15 / -40 / -60 kPa hold down)
 10. volunteer pilot precision            (what N = 20 can and cannot show)
 11. single-pad fault                     (how a failed electrode is absorbed)

External rates in section 6 and tissue parameters in section 7 are published
figures, cited where they are used. Change them only together with the
citation in the plan. Sections 8 and 9 are order-of-magnitude estimates from
stated geometry, not measurements.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from typing import Any, Dict, List

import numpy as np
from scipy import stats

from _root import ROOT
import main as m

UE_PER_100_VD = {"meta_2022": 1.06, "safe_icu_2024": 1.0}
SELF_FRACTION = {"meta_2022": 0.842, "safe_icu_2024": 0.88}
PLANNED_MONITORING_HOURS = 4800.0
PLANNED_PATIENTS = 100
TARGET_FA_PER_BED_DAY = 5.0


def _csv_frames(path: str) -> np.ndarray:
    import pandas as pd
    df = pd.read_csv(path)
    cols = [c for c in m.SENSOR_COLS if c in df.columns] or \
        [c for c in m.SIGNAL_COLS if c in df.columns]
    return df[cols].to_numpy(dtype=float)


def timing() -> Dict[str, Any]:
    a, t = m.ALARM, m.SAMPLE_PERIOD_S
    first_alarm_index = m.KALMAN_WARMUP + a.min_votes - 1
    out: Dict[str, Any] = {
        "sample_period_s": t,
        "window": a.window, "min_votes": a.min_votes, "hold": a.hold,
        "evidence_needed_s": round(a.min_votes * t, 2),
        "earliest_alarm_from_file_start_s": round(first_alarm_index * t, 2),
        "evidence_needed_s_at_rate": {f"{hz} Hz": round(a.min_votes / hz, 3)
                                      for hz in (10, 20, 50)},
    }
    bench = os.path.join(ROOT, "Data", "served_path_benchmark.json")
    if os.path.exists(bench):
        with open(bench, encoding="utf-8") as fh:
            folds = json.load(fh)["folds"]
        for path in ("C0_offline", "C0_served"):
            lat = [f["scores"][path]["identity"]["latency_s"] for f in folds
                   if f["label"] >= 2 and f["scores"][path]["identity"]["latency_s"] is not None]
            floor = out["earliest_alarm_from_file_start_s"]
            out[f"{path}_anomaly_files_alarmed"] = len(lat)
            out[f"{path}_at_floor"] = sum(1 for x in lat if abs(x - floor) < 1e-6)
            out[f"{path}_median_s"] = round(float(np.median(lat)), 2) if lat else None
    return out


def _k_steady(q: float, r: float) -> float:
    """Steady-state gain of the scalar random-walk Kalman filter."""
    prior = (q + math.sqrt(q * q + 4.0 * q * r)) / 2.0
    return prior / (prior + r)


def _deepest_peel_delta() -> float:
    """Deepest per-pad delta over the Peel recordings, offline Kalman calibration."""
    deepest = 0.0
    for path in sorted(glob.glob(os.path.join(ROOT, "Data", "Peel", "*.csv"))):
        deepest = min(deepest, float(m.KalmanBaseline().run(_csv_frames(path)).min()))
    return deepest


def _live_ramp_deepest(v_per_frame: float, frames: int = 3000) -> float:
    """Stream a noise-free ramp on every pad through the device path (LivePipeline).

    LivePipeline seeds its tracker from frame 0 alone, so r = KalmanBaseline.r on
    every pad whatever the bench noise - which is why the device figure differs
    from the offline one."""
    lp = m.LivePipeline(model=None)
    deepest = 0.0
    for i in range(frames):
        out = lp.process(np.full(m.N_PADS, m.BASELINE_COUNTS - v_per_frame * i))
        deepest = min(deepest, float(np.min(out["deltas"])))
    return deepest


def kalman_ramp() -> Dict[str, Any]:
    kb = m.KalmanBaseline()
    q, gate, t = kb.q, kb.gate, m.SAMPLE_PERIOD_S
    sds: List[float] = []
    for path in sorted(glob.glob(os.path.join(ROOT, "Data", "N_base", "*.csv"))):
        raw = _csv_frames(path)
        sds.extend((np.std(np.diff(raw, axis=0), axis=0) / math.sqrt(2.0)).tolist())
    noise_sd = float(np.median(sds)) if sds else float("nan")
    peel_counts = abs(_deepest_peel_delta())
    rows: List[Dict[str, Any]] = []
    cases = (("device path: seeded from frame 0, r fixed", kb.r, "live"),
             ("offline path: r floor (20)", 20.0, "offline"),
             ("offline path: measured N_base noise", noise_sd ** 2, "offline"),
             ("offline path: r ceiling (150)", 150.0, "offline"))
    for label, r, path in cases:
        r_eff = float(np.clip(r, 20.0, 150.0))
        k = _k_steady(q, r_eff)
        v_star = gate * k
        sims = {}
        for f in (0.8, 1.2):
            if path == "live":
                sims[f"{f}x"] = round(_live_ramp_deepest(f * v_star), 1)
                continue
            kf = m.KalmanBaseline()
            kf.seed(np.full((m.KALMAN_WARMUP, 1), m.BASELINE_COUNTS))
            kf.r_vec = np.array([r_eff])
            kf.p = np.array([r_eff])
            deepest = 0.0
            for i in range(3000):
                deepest = min(deepest, float(kf.step(np.array([m.BASELINE_COUNTS - f * v_star * i]))[0]))
            sims[f"{f}x"] = round(deepest, 1)
        rows.append({
            "case": label, "r": round(r_eff, 1), "k_steady": round(k, 4),
            "max_invisible_counts_per_frame": round(v_star, 2),
            "max_invisible_counts_per_s": round(v_star / t, 2),
            "max_invisible_pf_per_s": round(v_star / t / m.COUNTS_PER_PF, 3),
            "time_to_absorb_deepest_peel_s": round(peel_counts / (v_star / t), 0),
            "deepest_delta_3000_frames": sims,
        })
    return {"q": q, "innovation_gate_counts": gate, "lift_gate_counts": m.LIFT_GATE_COUNTS,
            "nbase_noise_sd_counts": round(noise_sd, 1),
            "deepest_peel_delta_counts": round(-peel_counts, 1),
            "deepest_peel_delta_pf": round(peel_counts / m.COUNTS_PER_PF, 1),
            "cases": rows}


def cdc_seed() -> Dict[str, Any]:
    out: Dict[str, Any] = {"cdc_power_on_pf": {}, "counts_power_on": {}}
    for pf in (3.0, 5.0, 12.0, 30.0, 45.0):
        lp = m.LivePipeline(model=None, cdc_mode=True)
        for _ in range(m.KALMAN_WARMUP):
            lp.process(np.full(m.N_PADS, pf))
        res = lp.process(np.full(m.N_PADS, pf))
        out["cdc_power_on_pf"][f"{pf:g} pF"] = res["seed_plausibility"]["status"]
    floor = m.spec_detach_reachability(m.SPEC_DETACH_MAX)["floor_counts_at_zero_capacitance"]
    for pf in (5.0, 30.0, 45.0):
        counts = floor + pf * m.COUNTS_PER_PF
        lp = m.LivePipeline(model=None)
        for _ in range(m.KALMAN_WARMUP):
            lp.process(np.full(m.N_PADS, counts))
        res = lp.process(np.full(m.N_PADS, counts))
        out["counts_power_on"][f"{pf:g} pF ({counts:,.0f} counts)"] = res["seed_plausibility"]["status"]
    lp = m.LivePipeline(model=None, cdc_mode=True)
    for _ in range(m.KALMAN_WARMUP + 1):
        lp.process(np.full(m.N_PADS, 5.0))
    res = lp.process(np.full(m.N_PADS, 30.0))
    out["applied_after_air_boot_delta_counts"] = round(float(np.median(res["deltas"])), 1)
    return out


def adaptive_gates() -> Dict[str, Any]:
    floor = m.spec_detach_reachability(m.SPEC_DETACH_MAX)["floor_counts_at_zero_capacitance"]
    flush_pf, tent_pf = 35.0, 15.0
    base_pf = np.array([flush_pf] * 20 + [tent_pf] * 5)
    base_counts = floor + base_pf * m.COUNTS_PER_PF
    g_counts = m.analyze_surface_topography(base_counts, is_cdc_pf=False)["adaptive_lift_gates"]
    g_pf = m.analyze_surface_topography(base_pf, is_cdc_pf=True)["adaptive_lift_gates"]
    lp = m.LivePipeline(model=None, cdc_mode=True)
    for _ in range(m.KALMAN_WARMUP + 1):
        lp.process(base_pf)
    live = lp.adaptive_lift_gates
    return {
        "offset_model_counts_at_zero_pf": floor,
        "counts_mode_gate_flush_35pf": g_counts[0], "counts_mode_gate_tented_15pf": g_counts[-1],
        "pf_mode_gate_flush_35pf": g_pf[0], "pf_mode_gate_tented_15pf": g_pf[-1],
        "pf_mode_gates_in_counts": [round(g_pf[0] * m.COUNTS_PER_PF, 1),
                                    round(g_pf[-1] * m.COUNTS_PER_PF, 1)],
        "lift_gate_counts_in_pf": round(m.LIFT_GATE_COUNTS / m.COUNTS_PER_PF, 2),
        "noise_gate_counts_in_pf": round(m.NOISE_GATE_COUNTS / m.COUNTS_PER_PF, 2),
        "live_cdc_gates_unique": sorted({round(float(x), 1) for x in live}) if live is not None else None,
    }


def hpull_depth() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    files = sorted(glob.glob(os.path.join(ROOT, "Data", "Horizontal Pull NO G", "*.csv")))
    for name in ("static", "kalman", "served"):
        mins: List[float] = []
        maxs: List[float] = []
        for path in files:
            raw = _csv_frames(path)
            if name == "static":
                d = m.static_baseline(raw) - m.BASELINE_COUNTS
            elif name == "kalman":
                d = m.KalmanBaseline().run(raw)
            else:
                lp = m.LivePipeline(model=None)
                d = np.array([lp.process(row)["deltas"] for row in raw])
            mins.append(float(d.min()))
            maxs.append(float(d.max()))
        out[name] = {"median_deepest": round(float(np.median(mins)), 1),
                     "deepest": round(float(min(mins)), 1),
                     "median_max": round(float(np.median(maxs)), 1),
                     "files_crossing_lift_gate": int(sum(x <= m.LIFT_GATE_COUNTS for x in mins))}
    return out


def _cp_lower(x: int, n: int, alpha: float = 0.05) -> float:
    return 0.0 if x == 0 else float(stats.beta.ppf(alpha / 2.0, x, n - x + 1))


def _power(n: int, lower_target: float, true_se: float) -> float:
    x_min = next((x for x in range(n + 1) if _cp_lower(x, n) >= lower_target), None)
    return 0.0 if x_min is None else float(stats.binom.sf(x_min - 1, n, true_se))


def _events_needed(lower_target: float, true_se: float, power: float = 0.8) -> int:
    """First n that reaches the power. Exact-binomial power saw-tooths, so see
    _events_needed_stable for the n a protocol should actually plan on."""
    for n in range(5, 2000):
        if _power(n, lower_target, true_se) >= power:
            return n
    return -1


def _events_needed_stable(lower_target: float, true_se: float, power: float = 0.8,
                          horizon: int = 60) -> int:
    """Smallest n from which power stays at or above the target for the next
    `horizon` values of n (a sample-size choice that cannot fall into a dip)."""
    ok = [_power(n, lower_target, true_se) >= power for n in range(5, 800 + horizon)]
    for i in range(len(ok) - horizon):
        if all(ok[i:i + horizon]):
            return i + 5
    return -1


def trial() -> Dict[str, Any]:
    vd = PLANNED_MONITORING_HOURS / 24.0
    out: Dict[str, Any] = {"ventilator_days": vd, "sources": {}}
    for key in UE_PER_100_VD:
        rate = UE_PER_100_VD[key] / 100.0 * SELF_FRACTION[key]
        lam = vd * rate
        lo, hi = stats.poisson.ppf(0.025, lam), stats.poisson.ppf(0.975, lam)
        out["sources"][key] = {
            "self_extubations_per_100_vd": round(rate * 100, 3),
            "expected_events": round(lam, 2),
            "p_zero_events": round(float(stats.poisson.pmf(0, lam)), 3),
            "central_95_range": [int(lo), int(hi)],
        }
    out["lower_bound_if_all_detected"] = {f"{x}/{x}": round(_cp_lower(x, x), 3)
                                          for x in (1, 2, 3, 5, 10, 30, 59)}
    need = {}
    rate = UE_PER_100_VD["meta_2022"] / 100.0 * SELF_FRACTION["meta_2022"]
    for lower, se in ((0.80, 0.95), (0.90, 0.97), (0.90, 0.99), (0.95, 0.99)):
        n = _events_needed(lower, se)
        n_stable = _events_needed_stable(lower, se)
        vd_needed = n / rate
        vd_stable = n_stable / rate
        need[f"lower>={lower:.2f} if true Se={se:.2f}"] = {
            "events_first": n, "events_stable": n_stable,
            "ventilator_days_first": int(round(vd_needed)),
            "ventilator_days_stable": int(round(vd_stable)),
            "multiple_of_plan_first": round(vd_needed / vd, 1),
            "multiple_of_plan_stable": round(vd_stable / vd, 1)}
    out["events_needed_80pct_power"] = need
    fa_rate_h = TARGET_FA_PER_BED_DAY / 24.0
    k = int(round(fa_rate_h * PLANNED_MONITORING_HOURS))
    lo = stats.chi2.ppf(0.025, 2 * k) / 2.0
    hi = stats.chi2.ppf(0.975, 2 * k + 2) / 2.0
    out["false_alarms_at_target"] = {
        "rate_per_hour": round(fa_rate_h, 4), "expected_count": k,
        "poisson_95ci_per_bed_day": [round(lo / PLANNED_MONITORING_HOURS * 24, 2),
                                     round(hi / PLANNED_MONITORING_HOURS * 24, 2)],
        "note": "Poisson only; alarms cluster within patients, so fit per-patient "
                "negative-binomial rates - the interval widens."}
    return out


def tissue() -> Dict[str, Any]:
    """Relative permittivity and conductivity of skin and muscle at the sensing
    frequencies, from the four-Cole-Cole fits of Gabriel, Lau and Gabriel,
    Phys Med Biol 41:2271 (1996), Table 1."""
    e0 = 8.854e-12
    params = {
        "skin_dry": (4.0, [(32.0, 7.23e-12, 0.0), (1100.0, 32.48e-9, 0.20)], 0.0002),
        "skin_wet": (4.0, [(39.0, 7.96e-12, 0.10), (280.0, 79.58e-9, 0.0),
                           (3.0e4, 1.59e-6, 0.16), (3.0e4, 1.592e-3, 0.20)], 0.0004),
        "muscle": (4.0, [(50.0, 7.23e-12, 0.10), (7000.0, 353.68e-9, 0.10),
                         (1.2e6, 318.31e-6, 0.10), (2.5e7, 2.274e-3, 0.0)], 0.2),
    }
    out: Dict[str, Any] = {}
    for f in (32e3, 100e3, 250e3, 5e6, 100e6, 300e6, 1e9):
        w = 2.0 * math.pi * f
        row = {}
        for name, (einf, terms, sig) in params.items():
            eps = complex(einf, 0.0)
            for d, tau, a in terms:
                eps += d / (1.0 + (1j * w * tau) ** (1.0 - a))
            eps += sig / (1j * w * e0)
            row[name] = {"eps_r": round(eps.real), "sigma_S_per_m": round(-eps.imag * w * e0, 4)}
        out[f"{f / 1e3:g} kHz"] = row
    return out


def pad_coupling() -> Dict[str, Any]:
    """Parallel-plate order of magnitude for one pad against a conductor."""
    e0, area = 8.854e-12, 38.5e-6
    out: Dict[str, Any] = {"pad_area_mm2": 38.5, "coupling_pf": {}}
    for d_mm in (0.5, 0.1, 0.05):
        out["coupling_pf"][f"{d_mm} mm at eps_r 3"] = round(e0 * 3.0 * area / (d_mm * 1e-3) * 1e12, 2)
    c0 = e0 * area / (0.5e-3 / 3.0)
    c1 = e0 * area / (0.5e-3 / 3.0 + 0.5e-3)
    out["lift_0p5mm_on_0p5mm_backing_pf"] = round((c1 - c0) * 1e12, 2)
    out["lift_0p5mm_on_0p5mm_backing_counts"] = round((c1 - c0) * 1e12 * m.COUNTS_PER_PF, 0)
    peel_pf = 869.3 / m.COUNTS_PER_PF
    d_over_eps = e0 * area / (peel_pf * 1e-12)
    out["median_peel_pf"] = round(peel_pf, 1)
    out["implied_d_over_eps_um"] = round(d_over_eps * 1e6, 1)
    out["implied_d_at_eps_r3_um"] = round(d_over_eps * 3.0 * 1e6, 0)
    return out


def rig_force() -> Dict[str, Any]:
    """Holding force if suction acts over the whole 90 x 120 mm footprint."""
    area = 0.090 * 0.120
    return {f"{kpa} kPa": {"newton": round(kpa * 1e3 * area), "kgf": round(kpa * 1e3 * area / 9.81, 1)}
            for kpa in (15, 40, 60)}


def volunteer_precision() -> Dict[str, Any]:
    """What a 20-person pilot can and cannot show (independent-trial bounds;
    repeated trials within one person are correlated, so these are optimistic)."""
    out: Dict[str, Any] = {}
    for x, n in ((100, 100), (97, 100), (95, 100)):
        out[f"tugs detected {x}/{n}"] = [round(_cp_lower(x, n), 3),
                                         round(float(stats.beta.ppf(0.975, x + 1, n - x)) if x < n else 1.0, 3)]
    for fa, n in ((0, 200), (2, 200), (5, 200)):
        hi = float(stats.beta.ppf(0.975, fa + 1, n - fa))
        out[f"false alarms {fa}/{n} activity trials"] = [round(_cp_lower(fa, n), 4), round(hi, 4)]
    return out


def pad_fault() -> Dict[str, Any]:
    """One electrode fails open mid-session and then reads a steady low value.

    By design (see _apply_quiescent_recovery) a single still channel below the
    lift gate is treated as a released touch and re-zeroed. The check records how
    long coverage over that pad lasts and whether anything is flagged."""
    rng = np.random.default_rng(0)
    lp = m.LivePipeline(model=None)
    base = np.full(m.N_PADS, m.BASELINE_COUNTS)
    fault_frame, pad = 12, 6
    first_recovery = back_inside_noise_gate = None
    disconnected_flagged = False
    for i in range(60):
        frame = base + rng.normal(0.0, 8.4, m.N_PADS)
        if i >= fault_frame:
            frame[pad] = m.BASELINE_COUNTS - 1500.0 + rng.normal(0.0, 2.0)
        out = lp.process(frame)
        disconnected_flagged |= bool(out.get("disconnected", False))
        if i >= fault_frame and first_recovery is None and (pad + 1) in out["quiescent_recovery"]["active_pads"]:
            first_recovery = i
        if (i > fault_frame and back_inside_noise_gate is None
                and abs(out["deltas"][pad]) < m.NOISE_GATE_COUNTS):
            back_inside_noise_gate = i
    t = m.SAMPLE_PERIOD_S
    return {"fault_step_counts": -1500.0, "pad": pad + 1,
            "recovery_engaged_after_s": round((first_recovery - fault_frame) * t, 2)
            if first_recovery is not None else None,
            "delta_back_inside_noise_gate_after_s": round((back_inside_noise_gate - fault_frame) * t, 2)
            if back_inside_noise_gate is not None else None,
            "disconnected_flagged": disconnected_flagged}


def main_cli() -> int:
    doc = __doc__ or ""
    ap = argparse.ArgumentParser(description=doc.splitlines()[0] if doc else "")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args()
    report = {"timing": timing(), "kalman_ramp": kalman_ramp(), "cdc_seed": cdc_seed(),
              "adaptive_gates": adaptive_gates(), "hpull_depth": hpull_depth(),
              "trial": trial(), "tissue": tissue(), "pad_coupling": pad_coupling(),
              "rig_force": rig_force(), "volunteer_precision": volunteer_precision(),
              "pad_fault": pad_fault()}
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for section, body in report.items():
        print(f"\n== {section} ==")
        print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
