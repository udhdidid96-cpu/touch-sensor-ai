"""Feature F16: Synthetic Domain Generalization & Contour Compensation Suite.

Tests:
  1. Scale-invariant fractional delta normalization across +-20% baseline perturbations
  2. Stepped ridge and contour topography profiling (analyze_surface_topography)
  3. Adaptive per-pad lift gates for tented and contoured anatomical profiles
  4. Static tube dielectric shadow localization across vertical, horizontal, and diagonal orientations
  5. Mathematical identity preservation (zero drift on nominal 28,000 count bench data)
"""
from __future__ import annotations

import numpy as np
import pytest

import main as M
from main import (
    N_PADS,
    BASELINE_COUNTS,
    DELTA_THRESHOLD,
    compute_fractional_deltas,
    analyze_surface_topography,
    detect_static_tube_localization,
)


def test_scale_normalized_deltas_nominal_identity():
    """F10/F16: On nominal bench baselines (28,000 counts), scale-normalized deltas

    produce an exact mathematical identity (0.00% drift).
    """
    baseline = np.full(N_PADS, 28000.0)
    raw_delta = np.array([-308.0, -650.0, 0.0, 450.0, 1200.0] * 5)

    frac_delta = compute_fractional_deltas(raw_delta, baseline)
    norm_delta = frac_delta * 28000.0

    np.testing.assert_allclose(norm_delta, raw_delta, rtol=1e-6, atol=1e-6)


def test_scale_normalized_deltas_negative_20pct_baseline():
    """F10/F16: Under -20% baseline shift (22,400 counts, e.g. dry skin / edema),

    scale-normalized deltas restore the -300 count gate for early detachment.
    """
    shifted_baseline = np.full(N_PADS, 22400.0)  # -20%
    # A 1.1% detachment air-gap on this shifted baseline produces -246.4 counts
    physical_lift_delta = -0.011 * shifted_baseline  # -246.4 counts

    # Under raw unnormalized threshold (-300.0), this physical lift FAILS to trigger
    assert np.all(physical_lift_delta > -DELTA_THRESHOLD), "Physical lift unnormalized is shallower than -300"

    # Under scale normalization:
    frac_delta = compute_fractional_deltas(physical_lift_delta, shifted_baseline)
    norm_delta = frac_delta * 28000.0

    # Must cleanly reach -308.0 counts and cross the -300 count gate!
    assert np.all(norm_delta <= -DELTA_THRESHOLD), f"Normalized delta {norm_delta[0]} failed to cross -300 gate"
    assert np.isclose(norm_delta[0], -308.0, atol=0.1)


def test_scale_normalized_deltas_positive_20pct_baseline():
    """F10/F16: Under +20% baseline shift (33,600 counts, e.g. diaphoresis / sweat),

    scale-normalized deltas prevent over-sensitisation.
    """
    shifted_baseline = np.full(N_PADS, 33600.0)  # +20%
    # A 1.1% detachment lift produces -369.6 counts
    physical_lift_delta = -0.011 * shifted_baseline

    frac_delta = compute_fractional_deltas(physical_lift_delta, shifted_baseline)
    norm_delta = frac_delta * 28000.0

    # Normalized delta scales back to exact -308.0 counts
    np.testing.assert_allclose(norm_delta, np.full(N_PADS, -308.0), atol=0.1)


def test_analyze_surface_topography_planar():
    """F11/F16: Uniform planar baseline is correctly classified as planar."""
    base = np.full(N_PADS, 28000.0)
    res = analyze_surface_topography(base, is_cdc_pf=False)

    assert res["valid"] is True
    assert res["surface_profile"] == "planar"
    assert len(res["tenting_pads"]) == 0
    assert len(res["flush_pads"]) == N_PADS
    assert len(res["adaptive_lift_gates"]) == N_PADS
    # Nominal adaptive gate is min(-150, -0.011 * 28000) = -308.0
    assert np.isclose(res["adaptive_lift_gates"][0], -308.0, atol=0.1)


def test_analyze_surface_topography_stepped_ridge_tenting():
    """F11/F16: Stepped ridge with micro air-gap tenting under ETT is detected

    and assigned sensitive adaptive lift gates.
    """
    base = np.full(N_PADS, 28000.0)
    # Pads 11, 12, 13 bridge the ETT tube and experience tenting (baseline drops to 14,000 counts)
    base[10] = 14000.0
    base[11] = 14000.0
    base[12] = 14000.0

    res = analyze_surface_topography(base, is_cdc_pf=False)

    assert res["valid"] is True
    assert res["surface_profile"] == "stepped_ridge"
    assert 11 in res["tenting_pads"]
    assert 12 in res["tenting_pads"]
    assert 13 in res["tenting_pads"]

    # Check adaptive lift gates:
    gates = res["adaptive_lift_gates"]
    # Tented pads should have sensitive gates: -0.011 * 14000 = -154.0
    assert np.isclose(gates[10], -154.0, atol=0.5)
    assert np.isclose(gates[11], -154.0, atol=0.5)
    # Flush pads remain at -308.0
    assert np.isclose(gates[0], -308.0, atol=0.5)

    # Verify that a detachment lift of -160 counts on a tented pad
    # triggers the adaptive gate (-154) whereas it would miss the fixed -300 gate
    assert -160.0 <= gates[10], "Adaptive gate did not detect early detachment on tented pad"
    assert -160.0 > -DELTA_THRESHOLD, "Fixed -300 gate would have missed this lift"


def test_static_tube_localization_orientations():
    """R3/F16: Adaptive MAD tube shadow detection accurately identifies

    vertical, horizontal, and diagonal tube axis orientations.
    """
    # 1. Planar / uniform profile (no tube)
    c_uniform = np.full(N_PADS, 30.0)
    res_uni = detect_static_tube_localization(c_uniform)
    assert res_uni["detected"] is False

    # 2. Vertical tube shadow: centerline pads (1, 12, 13, 14, 11) along x ≈ 50-58, y from 22 to 90
    c_vert = np.full(N_PADS, 30.0)
    for p in [1, 12, 13, 14, 11]:
        c_vert[p - 1] = 27.5
    res_vert = detect_static_tube_localization(c_vert)
    assert res_vert["detected"] is True
    assert res_vert["axis_orientation"] == "vertical"

    # 3. Horizontal tube shadow: transverse row (6, 7, 13, 20, 21) along y = 50, x from 20 to 80
    c_horiz = np.full(N_PADS, 30.0)
    for p in [6, 7, 13, 20, 21]:
        c_horiz[p - 1] = 27.5
    res_horiz = detect_static_tube_localization(c_horiz)
    assert res_horiz["detected"] is True
    assert res_horiz["axis_orientation"] == "horizontal"

    # 4. Diagonal tube shadow: diagonal pads (2, 5, 13, 22, 25) spanning both x and y >= 25mm
    c_diag = np.full(N_PADS, 30.0)
    for p in [2, 5, 13, 22, 25]:
        c_diag[p - 1] = 27.5
    res_diag = detect_static_tube_localization(c_diag)
    assert res_diag["detected"] is True
    assert res_diag["axis_orientation"] == "diagonal"
