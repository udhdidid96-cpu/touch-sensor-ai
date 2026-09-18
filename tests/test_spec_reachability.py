"""The <= 25,000 count detachment criterion cannot be met on this sensor.

Three published numbers do not agree:

    BASELINE_COUNTS     28,000 counts   patch at rest, attached
    COUNTS_PER_PF        59.85 counts/pF  [MEASURED], docs/Hardware_Deck_Spec.md
    SPEC_DETACH_MAX     25,000 counts   KES 2025 s2.1, as published

The spec asks for a 3,000-count drop, which at 59.85 counts/pF is 50.1 pF. The
attached patch is about 30 pF (NOMINAL_BASELINE_PF). Even at zero capacitance
the reading floors at 26,205 counts, still 1,205 counts above the threshold.

That matters because docs/ACTION_PLAN.md P0-2 treats 0/41 files meeting the
criterion as a fixation failure and schedules a rig rebuild (stronger vacuum,
hydrocolloid adhesive, ground plane) to fix it. The rebuild may be worth doing
for other reasons, but it cannot move this number.

These tests pin the arithmetic so the contradiction stays visible, and pin the
three constants so nobody "resolves" it by editing one of them. SPEC_DETACH_MAX
was already raised once, to 28,500 on 2026-08-18, which passed all 81 files
including bare baselines because the resting value sits below it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main  # noqa: E402


def test_the_three_constants_are_unchanged():
    # Rule 5: the spec is not edited to fit the data. Nor is the scale.
    assert main.SPEC_DETACH_MAX == 25000.0
    assert main.BASELINE_COUNTS == 28000.0
    assert main.COUNTS_PER_PF == 59.85
    assert main.NOMINAL_BASELINE_PF == 30.0


def test_detachment_criterion_is_unreachable_at_this_scale():
    r = main.spec_detach_reachability(main.SPEC_DETACH_MAX)
    assert r["reachable"] is False
    # 3,000 counts / 59.85 counts per pF
    assert math.isclose(r["drop_needed_pf"], 50.13, abs_tol=0.01)
    # more pF than the patch has
    assert r["drop_needed_pf"] > r["available_pf"]
    # 28,000 - 30 * 59.85
    assert math.isclose(r["floor_counts_at_zero_capacitance"], 26204.5, abs_tol=0.5)
    assert math.isclose(r["shortfall_counts"], 1204.5, abs_tol=0.5)


def test_reachability_flips_when_the_baseline_is_large_enough():
    # Sanity check on the helper itself: if the absolute C0 really were larger,
    # the criterion would be satisfiable. This is the number to go and measure.
    needed_pf = (main.BASELINE_COUNTS - main.SPEC_DETACH_MAX) / main.COUNTS_PER_PF
    r = main.spec_detach_reachability(main.SPEC_DETACH_MAX, baseline_pf=needed_pf + 1.0)
    assert r["reachable"] is True


def test_the_audit_caveat_says_unreachable_not_check_your_fixation():
    """The wrong diagnosis here costs a whole data-collection day."""
    import inspect
    src = inspect.getsource(main._caveats)
    assert "UNREACHABLE ON THIS SENSOR" in src
