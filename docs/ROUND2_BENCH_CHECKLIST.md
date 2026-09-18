# Round 2 Bench Checklist

**One page for the lab team. Three bench actions, in order, each with what to
record and what result would change a decision.**

Everything below is an action, not a finding. The tables have empty cells on
purpose: fill them at the bench, do not pre-fill them from a datasheet. The full
procedures are in `docs/DATA_COLLECTION_SOP_v2.md`; this sheet is the short form
and the reason each step matters.

Standing facts to work against, all **[MEASURED]** on round 1:

| quantity | value | source |
|---|---|---|
| Dressing size | 90 x 120 mm, pads span x 20-80 mm, y 22-90 mm | `PHYSICAL_PAD_COORDS` |
| Conversion | 59.85 raw counts / pF | `docs/Hardware_Deck_Spec.md` |
| Resting baseline | about 28,000 counts | corpus, 81 recordings |
| Lift gate | -300 counts, about -5 pF | `DELTA_THRESHOLD` |
| Noise floor | 8.6 counts sd [7.7, 9.9] | `docs/PHYSICS_TO_FEATURE_MAP.md` |
| Detachment spec | <= 25,000 counts, **unreachable** | `tests/test_spec_reachability.py` |

The spec is unreachable by arithmetic: 28,000 - 25,000 = 3,000 counts, which at
59.85 counts/pF is a **50.1 pF** drop out of a patch believed to hold about
**30 pF**, and at zero capacitance the reading still floors at 26,205. One of
`BASELINE_COUNTS`, `COUNTS_PER_PF` and `SPEC_DETACH_MAX` is wrong. **Step 1 is
the measurement that says which.** Do it before ordering any CDC silicon, because
AD7147 / AD7746 / FDC2214 all assume a 0-50 pF range.

---

## Step 1 — Absolute $C_0$ with an LCR meter (about 15 minutes)

Full procedure and decision table: `DATA_COLLECTION_SOP_v2.md` section 0.2.

1. **OPEN compensation first, with the leads in their measurement geometry.**
   Stray lead capacitance is single-digit pF and the number being measured is
   about 30 pF, so skipping this biases the result by more than 10%. Re-run OPEN
   if the leads are moved or re-clipped.
2. **Cp-D mode** (parallel capacitance and dissipation factor). Parallel, not
   series: the patch is a lossy dielectric between electrodes, and Cs on a lossy
   sample reads low. Record D alongside every C - a D above roughly 0.1 means
   the reading is loss-dominated and the C value should be treated as suspect.
3. **Measure at 100 kHz.** 1 kHz is the meter default and is the wrong point:
   CapSense and the candidate CDC parts excite far above it, and a dielectric
   with any moisture is strongly frequency-dependent. Take **1 MHz as a second
   point if the meter supports it** - two frequencies show whether the dielectric
   is dispersive, which one frequency cannot. **Record the frequency with every
   value.** A capacitance without its test frequency is not a measurement.
4. **Attached and detached, as a pair, in one sitting.** The pair is the point:
   $C_{attached} - C_{detached}$ is the entire signal budget the detector has.
5. Repeat the pair **three times**, re-seating the patch between repeats, so the
   spread from re-mounting is visible rather than assumed.

| repeat | freq | C attached (pF) | D | C detached (pF) | D | difference (pF) |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 2 | | | | | | |
| 3 | | | | | | |

**What the result decides.** If $C_0$ lands near 30 pF, the 50.1 pF drop the spec
demands is physically impossible and `SPEC_DETACH_MAX` is the wrong constant. If
$C_0$ is materially larger, `COUNTS_PER_PF` or `BASELINE_COUNTS` is wrong instead.
Do **not** edit any of the three to make the numbers agree -
`tests/test_spec_reachability.py` pins all three, and the point of the test is
that the contradiction stays visible until the bench resolves it.

**Second, independent check, same visit:** derive counts-per-pF empirically from
one peel event and compare against the published 59.85. Two routes to the same
constant is how a transcription error gets caught.

---

## Step 2 — Copper foil ground plane on the phantom rig

**Why.** Round 1 has a single electrode layer and no counter-electrode, so the
patch senses only its fringing field. Parallel-plate capacitance varies with plate
**separation**, not lateral position. A horizontal pull slides the patch sideways
at constant separation, so capacitance barely moves. The corpus says exactly that:
horizontal pull has a median Min Delta of **-14.4 counts against a baseline of
-14.7** - the lift channel sees nothing, and the only thing that moves is the
press side, from the hand and tube approaching the pads. Horizontal pull detects
**0 of 10** today.

With a ground plane on the skin side, lateral displacement changes plate **overlap
area**, and capacitance is directly proportional to area. That is what could make
shear detectable at all.

1. Adhesive-backed copper foil on the phantom, skin side, under the full patch
   footprint. Extend it past the 90 x 120 mm outline by about 10 mm on every edge
   so the pads at the border see plane, not an edge discontinuity.
2. **Tie the foil to the sensor board ground at one point only.** One point: a
   second tie makes a loop that will pick up mains hum straight into a
   femtofarad-resolution front end.
3. Foil must be continuous and flat. A wrinkle is a local separation change, which
   is indistinguishable from the signal being measured.
4. **Re-measure $C_0$ from Step 1 with the plane installed, before recording
   anything.** The plane raises $C_0$; how much is the number that says whether
   the detachment floor moved.

**Acceptance criterion (SOP section 8): horizontal pull, at least 5 of 7 files
crossing -300 counts, against 0 of 10 today.** Anything less and the plane has not
solved the blind spot, whatever $C_0$ did.

---

## Step 3 — Thinner backing, $d \rightarrow d/2$

**Why.** $C = \varepsilon A / d$. Halving the backing thickness roughly doubles
$C_0$. At $C_0$ near 60 pF a 50 pF loss becomes physically available, which is the
supervisor's advice restated as capacitor arithmetic. Suction and adhesive cannot
do this - they set how **completely** the patch lets go, not where the floor sits.

1. Target the round-2 membrane already planned: **about 0.5 mm**, with
   medical-grade hydrocolloid adhesive, on the high-suction bench (-40 to -60 kPa).
2. **Change one variable at a time.** Ground plane and thinner backing both raise
   $C_0$. Installed together, neither contribution is attributable. Record a
   $C_0$ pair after each change separately.
3. Check the dissipation factor again after the change. A thinner membrane under
   suction can trap moisture at the interface, and a rising D is the early warning.
4. Expect the **press** side to grow too. Touch is already several thousand counts
   while detachment is several hundred; doubling $C_0$ widens that asymmetry, so
   re-check the false-alarm rate on normal activity rather than assuming the
   sensitivity gain is free.

| configuration | $C_0$ attached (pF) | $C_0$ detached (pF) | counts baseline | notes |
|---|---|---|---|---|
| Round 1, as-is | | | ~28,000 | |
| + ground plane | | | | |
| + thinner backing | | | | |

---

## Step 4 — Recording hygiene, and this one is free

Added 2026-09-18 from a corpus finding, see `docs/PHYSICS_TO_FEATURE_MAP.md`
section 9.

**Start every recording with the patch attached and untouched for a full second
(about two frames at 560 ms, so allow three).** Six of the ten Brief Touch
recordings were started with a finger already resting on one or two pads. The
Kalman baseline seeds from the first five frames, so those pads seeded 470 to 810
counts high and then read that far **below** baseline for the rest of the file -
past the -300 lift gate, in recordings labelled normal. `seed_plausibility()` does
not catch it: it takes the median across all 25 pads, and one or two elevated
channels do not move a 25-channel median.

Costs nothing, removes a phantom signal from the corpus, and some part of the
measured 4.9% false-alarm rate may go with it.

---

## Order and dependencies

Step 1 before any silicon order. Step 1 again after Step 2, and again after
Step 3 - three $C_0$ pairs, one per configuration, or the contributions cannot be
separated. Step 4 applies from the next recording onward and blocks nothing.

Bring back: the filled tables above, the raw LCR readings with their frequencies,
and the horizontal-pull file count against the 5-of-7 criterion. Nothing in this
repository should be edited to match an expected value before those exist.
