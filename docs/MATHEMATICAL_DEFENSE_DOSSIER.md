# Technical Monograph and Mathematical Defense Dossier

## 25-channel capacitive smart dressing for early warning of accidental extubation

| | |
|---|---|
| **Date** | 2026-09-25 |
| **Status** | Working draft for supervisor review. It is not a regulatory document, and the software has not been assessed against IEC 62304. |
| **Scope** | The supervisor's four challenges: (1) electrodynamics and learning theory, (2) the five-scenario decomposition, (3) relative versus absolute sensing, (4) contours and step heights. |
| **Reproduction** | `python scripts/defense_dossier_checks.py` reproduces every computed number here in about 20 s. `python scripts/translation_plan_checks.py` covers the CDC-seed, adaptive-gate, Kalman-ramp and pad-fault figures. Headline metrics are generated from `Data/metrics.json` by `scripts/sync_metrics_blocks.py`. |
| **Companion** | `docs/TRANSLATION_PLAN_24M.md` is the 24-month plan these results feed. |

### How to read this dossier

The brief asked for proofs of a list of statements.

- Statements that are true are proved here.
- Statements that are false on the stated parameters get the derivation or the data that refutes them, followed by what is true instead.
- A statement is marked *proven* only when the proof is written out in the text or a script reproduces the number.
- **ASSUMED** marks a value taken from the brief or the documents that has never been measured on this patch.

Four assumed quantities matter most: the pad area, the dielectric stack, the absolute C₀, and the counts-per-pF transfer. These are exactly the quantities the LCR protocol in §4.7 measures. Section 0 is a one-page verdict for every claim. The rest of the document is the evidence.

### Headline figures (generated, do not edit)

<!-- metrics:episode_headline_en -->
Episode-level, out-of-fold, 7-of-6 hold 9: sensitivity **100.0%** [91.2–100.0], false alarm **4.9%** per recording [1.3–16.1] = **7.8 alarms/hour**, median time-to-alarm **5.60 s** (worst 17.36 s), 0 missed events. Source: `Data/metrics.json` (2026-09-25, v6.2).
<!-- /metrics:episode_headline_en -->

<!-- metrics:served_headline_en -->
Served path (every recording streamed through LivePipeline), out-of-fold, 7-of-6 hold 9: sensitivity **97.5%** [87.1–99.6], false alarm **4.9%** per recording [1.3–16.1] = **5.2 alarms/hour**, median time-to-alarm **7.28 s** (worst 17.36 s), 1 missed (Vertical Pull NO G/A_VPull_06.csv). Source: `Data/metrics.json` (2026-09-25, v6.2).
<!-- /metrics:served_headline_en -->

---

## 0. Verdict ledger

| # | Claim (brief or project documents) | Verdict | § |
|---|---|---|---|
| C1 | Dermis acts as a dielectric layer of εr ≈ 50–80 | **Corrected.** At the sensing frequency tissue behaves as a conductor. It is 0.59% of the series impedance at 250 kHz, and wet skin has εr′ ≈ 7,200 there. The 50–80 range is the value at roughly 100–300 MHz. | 2.2 |
| C2 | ΔC_peel < 0 and ΔC_press > 0 (polarity asymmetry) | **Proven** for the physical capacitance, mechanism by mechanism (Theorem 1). **Not true of the recorded deltas**, which are measured from a relative zero (Proposition 1). | 2.4–2.5 |
| C3 | Extubation and benign contact occupy non-overlapping manifolds in delta space | **Refuted.** Horizontal pull lies in the contact region by symmetry, and 15.8% of touch frames match peel frames by sign. What holds is that peel is separated from every other class (Mahalanobis ≈ 7.7). | 2.6 |
| C4 | VC and Rademacher analysis shows that HGB beats deep sequence networks | **Refuted as a proof.** Every capacity bound is vacuous for both model classes at n = 3,349 frames, and more so at n_eff ≈ 81 recordings. | 2.7 |
| C5 | Deep models show "6× seed variance" | **Corrected.** The ratio is 6.05× in standard deviation and 36.6× in variance. It is significant one-sided from 3 seeds and two-sided from 5 (the seed count is not recorded). The mean difference is not significant (p ≈ 0.9). | 2.7.7 |
| C6 | Axis-aligned trees model step gates natively | **Proven** (Theorem 2): exact representation, and invariance to any monotone transform of a feature. | 2.7.9 |
| C7 | A ground plane converts planar shear into a steep capacitance drop | **Refuted for a continuous plane** (Theorem 3, translation invariance). It holds only within about ±3.5 mm of a plane edge, or with a patterned shear cell, which gives about 4 counts per 10 N on the assumed stack. | 3.3 |
| C8 | The causal 3-tap median fails on noise and so drops sensitivity from 87.5% to 72.5% | **Mechanism corrected.** All six extra misses are short vertical pulls (11–15 frames; four have 0–1 frames of slack). The median shifts every onset by one frame, which pushes a supporting frame past the end of the clip, and the k-of-n vote does the rest. | 3.5 |
| C9 | ≤ 25,000 counts is unreachable | **Proven, conditional on the transfer function** (Theorem 4). With the repository's constants the floor is 26,204.5 counts. The transfer itself has never been measured, and a CapSense auto-calibration would change the conclusion. | 4.6 |
| C10 | The tube casts a "dielectric shadow" (εr 2.8 vs 50–80) that a MAD threshold localises | **Mechanism corrected, detector refuted.** The shadow comes from lift-off geometry, not a permittivity contrast. The shipped detector reports a diagonal tube on the patch's own resting shape. A matched filter works when pad-to-pad spread is ≲ 1 pF. | 4.5 |
| C11 | The draped profile is w(x) = h₀e^(−x/λ)cos(x/λ) | **Derived** (Hetényi, hinged edge), then **shown inapplicable** to millimetre steps: the slope h₀/λ is 2–40 and the adhesive strain is ≫ 1. | 5.2 |
| C12 | Pads over the ridge drop from 35 pF to 12–18 pF | **Refuted on the stated stack.** Body coupling is about 4 pF per pad, so no pad can lose 17–23 pF. The claim needs d/ε ≤ 15–20 µm; the stated stack is 86–93 µm. | 5.4 |
| C13 | A fixed −300-count gate misses detachment on tented pads (z ≥ 1.5 mm) | **Proven, and stronger:** such a pad is blind to *every* gate (Theorem 5). The remedy is mechanical, not a threshold. | 5.5 |
| C14 | Gate_i = min(−150, −α·C₀,ᵢ) with α = 0.011, and δᵢ = ΔCᵢ/C₀,ᵢ, are optimal | **Refuted.** The gate is not unit-consistent. In counts it is inert (−298 to −311). In pF mode it gives 13% false lifts per pad-frame at 15 pF, and δ is not invariant. The provably invariant statistic is the detachment fraction (Theorems 6–7). | 5.6 |
| C15 | The absolute-CDC path removes power-on zeroing | **Not true of the code today.** Live CDC mode re-zeroes on its first frame, so every seed check passes and every gate is −308. | 4.4 |
| C16 | Progress report §1.2 feature list (ΣΔC⁺, Σ\|ΔC⁻\|, N_pressed ≥ +60, S_spread, …) | **Does not match the code.** The 9 statistics are min, max, mean, std and five threshold counts at −300, −600, −1000, +300 and +1000. | 1.4 |

---

## 1. System model, notation and parameters

### 1.1 Signal chain

For pad $i$ and frame $t$ (period $T_s = 0.56$ s), the served path (`LivePipeline.process`, `main.py` l.2723–2927) computes:

$$
N_i(t)\;\xrightarrow{\text{Kalman}}\;b_i(t),\qquad
d_i(t)=N_i(t)-b_i(t),\qquad
\tilde d_i(t)=\frac{d_i(t)}{b_i(t)}\,N_{\mathrm{nom}}\ \ (\text{F10}),\qquad N_{\mathrm{nom}}=28{,}000 .
\tag{1.1}
$$

The rest of the chain runs in this order:

1. **Noise gate.** A frame is Level 0 unless $\max_i|\tilde d_i|\ge 60$ (`classify_deltas`, l.1596).
2. **Features.** The feature map $\varphi:\mathbb R^{25}\to\mathbb R^{34}$ (l.1052).
3. **Classifier.** The four-class HistGradientBoosting classifier.
4. **Annunciator.** Window 7, 6 votes, hold 9.

Two side paths do not feed the alarm:

- `PeelTracker` / `propagation` receive the raw $d_i$ and the adaptive gates (l.2919). Their output is descriptive only.
- The adaptive gates never reach `classify_deltas`.

**Readout model.** This model is used throughout. Its transfer is the unknown that the LCR protocol measures.

$$
N_i=a_i+\beta_i\,C_i,\qquad C_i=C_{\mathrm{par},i}+C_{\mathrm{body},i}\,g_i(z),\qquad g_i(0)=1,\ \ g_i(\infty)=0 .
\tag{1.2}
$$

- $C_{\mathrm{par},i}$ is the part of pad $i$'s capacitance that does not depend on the patient: traces, board, shield and surroundings.
- $C_{\mathrm{body},i}$ is the part that couples to the patient.
- $g_i(z)$ is the fraction of $C_{\mathrm{body},i}$ that remains when the pad is lifted by $z$.

The repository fixes $\beta=59.85$ counts/pF (**MEASURED**, `docs/Hardware_Deck_Spec.md`). It also implies $a=28{,}000-30\times59.85=26{,}204.5$ counts, but only if $C_0=30$ pF (**ASSUMED**).

### 1.2 Constants in the code

**Table 1.** Constants of the shipped pipeline (`main.py`).

| Symbol | Value | Line | Status |
|---|---|---|---|
| $N_{\mathrm{nom}}$ (`BASELINE_COUNTS`) | 28,000 counts | 183 | nominal, KES 2025 §2.1 |
| $\beta$ (`COUNTS_PER_PF`) | 59.85 counts/pF | 184 | MEASURED |
| $C_0$ (`NOMINAL_BASELINE_PF`) | 30 pF | 185 | ASSUMED, never measured |
| $T_s$ (`SAMPLE_PERIOD_S`) | 0.56 s | 246 | measured frame period |
| Noise gate / lift gate | 60 / −300 counts | 368 / 369 | |
| Warm-up | 5 frames (2.8 s) | 360 | |
| Kalman $q$, $r$, innovation gate | 0.05, 40, 120 counts | 593–595 | |
| Annunciator | window 7, 6 votes, hold 9 | 534–554 | clinical choice, 2026-08-19 |
| Seed band | 27,500–28,600 counts (median of 25 pads) | 4211 | round-1 specific |
| Seed shape gate | 575 counts per pad, offset-corrected | 478 | advisory only |
| Quiescent recovery | 3.0 s, raw sd < 15 counts, $P\times1.6$ per frame, cap $4r$ | 416–419 | |
| Peel gate | ≥ 3 pads, grid mean < −150, 3 frames | 486–488 | |
| Adaptive gate | $\alpha=0.011$; floor −150 counts or −0.15 pF | 3070–3071 | |
| Tube shadow | $1.4826\cdot\mathrm{MAD}\cdot1.5$ clamped to [0.35, 1.5] pF; ≥ 3 pads | 2984–2988 | |
| `SPEC_DETACH_MAX` | 25,000 counts | 4190 | pinned by `tests/test_spec_reachability.py` |

### 1.3 Assumed physical stack

**Table 2.** Physical parameters used where absolute numbers are needed. All are ASSUMED unless stated.

| Quantity | Value | Source |
|---|---|---|
| Pad | disk, $r=3.5$ mm, $A=38.5$ mm² | progress report §1.1. Pad diameter is still [FILL] in `Hardware_Deck_Spec.md` |
| Hydrocolloid | 0.30 mm, εr 3.5 | brief |
| Polyimide flex | 25 µm, εr 3.4 | brief |
| Top film (finger model) | 50 µm, εr 3.0 | assumed |
| Finger | grounded disk, $r=6$ mm | assumed |
| Endotracheal tube (ETT) | OD 9.0–11.5 mm ($a=4.5$–5.75 mm); wall εr 2.8 | brief |
| Tape | 1–3 mm | brief |
| Per-pad noise | σ = 8.4–8.6 counts | `translation_plan_checks.py` (8.4); `PHYSICS_TO_FEATURE_MAP.md` (8.6 [7.7–9.9]) |
| Sensing frequency | 250 kHz, swept 32 kHz–5 MHz | assumed; the CapSense scan settings are [FILL] |
| Tissue | Gabriel four-Cole-Cole fits. Gabriel has no stratum-corneum or dermis fits, so the "Skin (Dry)" fit stands in for stratum corneum (20 µm) and "Skin (Wet)" for dermis (2 mm); muscle 10 mm | Gabriel, Lau & Gabriel 1996 |

### 1.4 The feature map, as coded

$$
\varphi(\mathbf d)=\Big[d_1,\dots,d_{25},\ \min_i d_i,\ \max_i d_i,\ \bar d,\ s_d,\ \#\{d_i\le-300\},\ \#\{d_i\le-600\},\ \#\{d_i\le-1000\},\ \#\{d_i\ge300\},\ \#\{d_i\ge1000\}\Big].
\tag{1.3}
$$

**Table 3.** Feature indices (`extract_features`, l.1052–1082). `ALGORITHM_JUSTIFICATION.md` §3.4 matches this.

| Index | Feature | Index | Feature |
|---|---|---|---|
| 0–24 | pad deltas $d_1..d_{25}$ | 29 | #{d ≤ −300}, the lift gate |
| 25 | min | 30 | #{d ≤ −600} |
| 26 | max | 31 | #{d ≤ −1000} |
| 27 | mean | 32 | #{d ≥ +300} |
| 28 | std | 33 | #{d ≥ +1000} |

`SMART_DRESSING_PROGRESS_REPORT_BIOMEDICAL_AI.md` §1.2 describes a different vector: μ, σ, min, max, $\sum\Delta C^+$, $\sum|\Delta C^-|$, $N_{\text{lifted}}$, $N_{\text{pressed}}$ (at ≥ +60), $S_{\text{spread}}$. Three of those are computed nowhere in the code, and $N_{\text{pressed}}$ uses +300, not +60. That equation should be replaced by (1.3).

---

## 2. Module 1: electrodynamic grounding

### 2.1 Governing equations and their range of validity

**Why quasi-static holds.** At 250 kHz the patch (0.12 m) is four orders of magnitude smaller than the free-space wavelength ($c/f=1.2$ km). The magnetic skin depth in muscle, $\delta=\sqrt{2/(\omega\mu_0\sigma)}\approx1.6$ m at σ = 0.40 S/m, is far larger than any tissue layer. Induction is therefore negligible, and the potential obeys the quasi-static complex Laplace equation:

$$
\nabla\cdot\big(\varepsilon^*(\mathbf r)\,\nabla\Phi\big)=0,\qquad
\varepsilon^*=\varepsilon_0\Big(\varepsilon_r'-j\,\frac{\sigma}{\omega\varepsilon_0}\Big),
\tag{2.1}
$$

The boundary conditions are:

- $\Phi=V$ on the electrode;
- $\Phi=0$ on grounded conductors;
- continuity of $\Phi$ and of $\varepsilon^*\partial_n\Phi$ at every interface.

**Variational form.** In lossless regions, the self-capacitance of the electrode (all other conductors grounded, $V=1$) is given by the Dirichlet principle:

$$
C=\min_{\Phi\in\mathcal A}\ \int_{\Omega}\varepsilon(\mathbf r)\,\lvert\nabla\Phi\rvert^{2}\,dV,
\qquad
\mathcal A=\{\Phi:\ \Phi=1\ \text{on the electrode},\ \Phi=0\ \text{on the grounded set } G\}.
\tag{2.2}
$$

The minimiser is the Laplace solution, and the minimum equals $2W$, twice the stored energy. Equation (2.2) is what makes the polarity theorem of §2.4 a two-line argument.

### 2.2 Lemma 1: at the sensing frequency, tissue is a conductor

The series impedance that each layer presents under one pad is

$$
Z_j=\frac{t_j}{j\omega\varepsilon_0\varepsilon^*_{r,j}A} .
$$

The tissue values below come from the Gabriel four-Cole-Cole model.

**Table 4.** Layer impedances under one pad at 250 kHz (`tissue` in `defense_dossier_checks.py`).

| Layer | $t$ | εr′ | σ (S/m) | σ/(ωε₀εr′) | \|Z\| (Ω) |
|---|---|---|---|---|---|
| Hydrocolloid | 0.30 mm | 3.5 | 0 | 0 | 160,140 |
| Stratum corneum ("Skin (Dry)" fit) | 20 µm | 1,098 | 0.0015 | 0.096 | 33.9 |
| Dermis ("Skin (Wet)" fit) | 2 mm | 7,189 | 0.1312 | 1.31 | 315.0 |
| Muscle | 10 mm | 5,763 | 0.3956 | 4.94 | 643.7 |

Taking the complex sum, the tissue is **0.59%** of $|Z_{\text{total}}|$. Treating the tissue as a perfect conductor changes the apparent (parallel-equivalent) capacitance by **−0.22%**.

**Table 5.** The same quantities across the plausible CapSense band.

| Frequency | 32 kHz | 100 kHz | 250 kHz | 1 MHz | 5 MHz |
|---|---|---|---|---|---|
| Tissue share of \|Z\| | 0.14% | 0.29% | 0.59% | 1.79% | 7.21% |
| Apparent C change | −0.11% | −0.14% | −0.22% | −0.52% | −1.89% |

> **Lemma 1.** Take the stack of Table 2 and any frequency from 32 kHz to 5 MHz. Replacing all tissue by a perfect conductor at the skin surface changes the apparent pad capacitance by less than 2%.
>
> *Proof.* The ratio of a tissue layer's impedance to the adhesive's is $(t_j/t_h)\,(\varepsilon_h/|\varepsilon^*_{r,j}|)$. Here $|\varepsilon^*_{r,j}|\ge\varepsilon'_{r,j}$, which is $10^2$–$10^4$ times $\varepsilon_h=3.5$ across the band (Gabriel 1996), while $t_j/t_h\le33$. Table 5 evaluates the complex sum exactly. ∎

Three consequences follow.

1. **The brief's "dermis εr 50–80" is a radio-frequency value.** Gabriel's fits give 66 for wet skin at 100 MHz and 46 at 1 GHz; they give 7,189 at 250 kHz, where conduction exceeds displacement current (σ/ωε₀εr′ = 1.31).
2. **The tissue-as-dielectric model has a large error.** Modelling the dermis as a 3-mm, εr-65 dielectric gives 2.58 pF for the flush pad instead of 3.98 pF, a −35% error. That is larger than most of the effects it is used to explain.
3. **The problem reduces to geometry.** The boundary-value problem becomes: an electrode, above a dielectric stack (hydrocolloid, possibly air), above a grounded conductor (the skin surface). Tissue permittivity drops out entirely. What changes $C$ is geometry: how much low-permittivity material lies between the electrode and the skin.

**Remark 2.1 (return path).** The body is not circuit ground. It is a conductor coupled to the board's reference through the human-body capacitance $C_{hb}$, which is of order 100 pF (the ESD human-body model uses 100 pF). The pad sees

$$
\left(C_{\mathrm{pad}}^{-1}+C_{hb}^{-1}\right)^{-1}\approx C_{\mathrm{pad}}\,(1-C_{\mathrm{pad}}/C_{hb}),
$$

a reduction of about 5% for a few-pF pad.

This matters for the bench. The round-1 surface was flat acrylic (`CONTOUR_AND_STEP_HEIGHT_COMPENSATION_GUIDE.md` §1), which is a dielectric, not a conductor. On acrylic, lifting a pad modulates fringing fields into a low-εr half-space. On skin, it modulates coupling to a conductor. These two transfer functions differ.

### 2.3 Solution of the stratified boundary-value problem

#### 2.3.1 Exact spectral-domain formulation

Consider a disk electrode of radius $R$ above laterally uniform layers $j=1..J$ (thickness $t_j$, permittivity $\varepsilon_j$, with $\varepsilon_0$ included), terminated below by the grounded conductor, with a half-space $\varepsilon_{\text{top}}$ above. Write

$$
\Phi(r,z)=\int_0^\infty \hat\Phi(k,z)\,J_0(kr)\,k\,dk .
$$

Each Hankel mode obeys $\hat\Phi''=k^2\hat\Phi$. This is a lossless transmission line with propagation constant $k$ and characteristic admittance $\varepsilon_j k$. The downward input admittance at the top of layer $j$ therefore follows the transmission-line recursion:

$$
Y_0=\infty,\qquad
Y_j(k)=\varepsilon_j k\,\frac{Y_{j-1}(k)+\varepsilon_j k\tanh(kt_j)}{\varepsilon_j k+Y_{j-1}(k)\tanh(kt_j)},
\qquad Y_{\uparrow}(k)=\varepsilon_{\text{top}}\,k .
\tag{2.3}
$$

The Hankel transforms of the electrode's surface charge and potential satisfy $\hat\sigma(k)=[Y_J(k)+Y_\uparrow(k)]\,\hat\Phi(k)$. Imposing $\Phi=V$ on $r\le R$ and zero charge outside gives a pair of dual integral equations of Sneddon type, whose solution gives $C=Q/V$.

Two limits check the recursion:

- **One layer.** $Y_1=\varepsilon_1k\coth(kt_1)$.
- **Low-$k$ (parallel-plate) limit.** $Y_J\to\big(\sum_j t_j/\varepsilon_j\big)^{-1}$, which recovers the series formula
  $$
  C_{pp}=\frac{\varepsilon_0A}{\sum_j t_j/\varepsilon_{r,j}} .
  \tag{2.4}
  $$

For the stack of Table 2, $\sum t/\varepsilon_r$ is:

- 85.7 µm for the hydrocolloid alone (electrode facing the skin);
- 93.1 µm if the polyimide also lies between the electrode and the skin.

At 85.7 µm, $C_{pp}=3.975$ pF.

#### 2.3.2 Finite-volume solution with fringing, air gap, press and finger

`axisym_pad()` solves (2.1) in cylindrical coordinates:

- cell-based permittivity on a graded mesh;
- charge computed from face fluxes;
- a grounded box of 25 mm × 25 mm;
- the body as a grounded plane below the stack.

$C_{\text{body}}$ is the flux reaching the body. $C_{\text{total}}$ is all flux leaving the electrode, and the difference between them belongs to $C_{\text{par}}$.

**Table 6.** One pad lifted by an air gap $z$.

| $z$ (mm) | $C_{\text{body}}$ FV (pF) | $C_{pp}$ (pF) | $C_{\text{total}}$ FV (pF) |
|---|---|---|---|
| 0 | 4.61 | 3.98 | 4.63 |
| 0.05 | 3.10 | 2.51 | 3.12 |
| 0.10 | 2.38 | 1.83 | 2.41 |
| 0.25 | 1.49 | 1.02 | 1.52 |
| 0.50 | 0.99 | 0.58 | 1.03 |
| 1.0 | 0.66 | 0.31 | 0.71 |
| 1.5 | 0.53 | 0.21 | 0.58 |
| 3.0 | 0.36 | 0.11 | 0.44 |

- **Fringing** adds 16% at contact (4.61 against 3.98 pF) and dominates at large gaps.
- **Press.** Compressing the hydrocolloid by 20% raises $C_{\text{body}}$ to 5.63 pF: **+1.02 pF, +61 counts**.
- **Finger.** A grounded 6-mm disk on the 50-µm top film raises $C_{\text{total}}$ by **+14.24 pF (+852 counts)**, with 14.75 pF of the electrode's flux ending on the finger.

**The measured data contradict the stated stack.** The corpus has a median touch maximum of +3,037 counts (≈ 50.7 pF) and a median peel minimum of −869 counts (≈ 14.5 pF) (`Data/five_scenarios_evaluation.json`). Both are 3–4× beyond what the stated stack can produce: at most +14.2 pF for a finger, and 4.6 pF of total body coupling for a peel. With the measured β, the corpus implies an effective d/ε ≈ 23.5 µm if a peel removes all body coupling (`translation_plan_checks.py`, `pad_coupling`), against 85.7 µm in the brief.

So the stated stack is not the bench stack. Or the pad area differs from 38.5 mm², or β is wrong. This is a measured inconsistency, not a modelling nuance. Later sections use the stated stack where they need absolute numbers, and each time they flag it. Ratios that depend only on the geometry of the gap remain valid.

### 2.4 Theorem 1: polarity of the physical capacitance

> **Theorem 1 (monotonicity of self-capacitance).** Let $C(\varepsilon,G)$ be the self-capacitance of the sensing electrode in a domain with permittivity field $\varepsilon(\mathbf r)>0$ and grounded conductor set $G$.
>
> **(a)** If $\varepsilon_1\ge\varepsilon_2$ pointwise, then $C(\varepsilon_1,G)\ge C(\varepsilon_2,G)$.
>
> **(b)** If $G_1\supseteq G_2$, then $C(\varepsilon,G_1)\ge C(\varepsilon,G_2)$.
>
> The inequalities are strict when the change occupies a set of positive measure on which $\nabla\Phi\neq0$.
>
> *Proof.* (a) Let $\Phi_1$ minimise (2.2) for $\varepsilon_1$. Then $C(\varepsilon_1)=\int\varepsilon_1|\nabla\Phi_1|^2\ge\int\varepsilon_2|\nabla\Phi_1|^2\ge\min_\Phi\int\varepsilon_2|\nabla\Phi|^2=C(\varepsilon_2)$.
> (b) Any function admissible for $G_1$ vanishes on $G_1\supseteq G_2$, so it is admissible for $G_2$ with the same energy ($\nabla\Phi=0$ where $\Phi\equiv0$). The minimum over the smaller admissible set is therefore no smaller. ∎

**Corollary 1.1 (sign of each mechanism, self-capacitance sensing).**

| Mechanism | What changes | Theorem part | Sign of ΔC |
|---|---|---|---|
| Lift or peel | Air ($\varepsilon_0$) replaces adhesive, and the skin (part of $G$) recedes | (a) and (b), both decreasing | **ΔC < 0** |
| Press (adhesive compressed) | The skin surface advances into former adhesive, so $G$ grows | (b); lateral bulging neglected | **ΔC > 0** |
| Finger or other grounded object | $G$ grows | (b) | **ΔC > 0** |
| Tube wall, cloth or sweat film replacing air | ε grows; a conductive film bridging to the skin also grows $G$ | (a), (b) | **ΔC > 0** |

In self-capacitance sensing, the only mechanisms that can make ΔC negative are those that remove permittivity or pull a grounded conductor away. Lift, peel and loss of contact are exactly those mechanisms. This proves claim C2 **for the physical capacitance**. ∎

**Remark 2.2 (mutual-capacitance sensing reverses the touch sign).** In CSX (mutual) mode, a grounded finger diverts field lines away from the receiver and *lowers* the transcapacitance. Theorem 1 covers self-capacitance only. The corpus reads touches as large positive deltas (median max +3,037 counts), which is consistent with self-capacitance (CSD) sensing. That observation fills one of the [FILL] rows of `Hardware_Deck_Spec.md` by inference; confirm it in the firmware.

### 2.5 Proposition 1: the relative zero breaks the polarity of the recorded deltas

The classifier never sees ΔC. It sees $d_i=N_i-b_i$. Offline, $b_i$ is seeded from the mean of the first five frames. The device (`LivePipeline`) seeds from frame 0 alone and fixes $r=40$ (l.2796–2804).

> **Proposition 1.** Suppose pad $i$ carries an extra $\Delta C_{s,i}$ while the baseline is being seeded. Then after that load is removed, and with no mechanical change at all, the pad reads $d_i=-\beta\,\Delta C_{s,i}<0$. Conversely, a pad seeded loose reads $d_i>0$ when it is pressed into place.
>
> *Proof.* Substitute (1.2) into $d_i=N_i-b_i$ with $b_i=N_i(\text{seed})=a_i+\beta(C_i+\Delta C_{s,i})$. ∎

Theorem 1 therefore constrains ΔC measured against the true attached state, not $d$. The corpus shows the consequence directly.

**Table 7.** Sign regimes of active frames ($\max_i|d_i|\ge60$; all frames for Baseline). *neg-only*: some pad ≤ −300 and none ≥ +300. *pos-only*: the reverse. *mixed*: both.

| Scenario | Frames | neg-only | pos-only | mixed | neither | Files with a neg-only frame |
|---|---|---|---|---|---|---|
| Baseline | 589 | 0 | 0 | 0 | 1.000 | 0/5 |
| **Touching** | 1,168 | **0.158** | 0.421 | 0.318 | 0.102 | **14/21** |
| — Brief Touch | 594 | 0.249 | 0.283 | 0.359 | 0.109 | 6/10 |
| — Press | 574 | 0.064 | 0.564 | 0.277 | 0.094 | 8/11 |
| Friction | 277 | 0 | 0.025 | 0 | 0.975 | 0/10 |
| **Pulling** | 381 | 0.139 | 0.499 | 0.031 | 0.331 | 13/30 |
| — Vertical Pull | 81 | 0.296 | 0.370 | 0.148 | 0.185 | 10/10 |
| — Horizontal Pull | 172 | **0** | 0.494 | 0 | 0.506 | **0/10** |
| — Power Pull | 128 | 0.227 | 0.586 | 0 | 0.188 | 3/10 |
| **Peeling** | 185 | **0.924** | 0.011 | 0 | 0.065 | 10/10 |
| Normal Mix (reference) | 276 | 0.293 | 0.257 | 0.297 | 0.152 | 3/5 |

What Table 7 shows:

- **Touch frames that look like peels.** 15.8% of touch frames, and 24.9% of brief-touch frames, cannot be told apart from peel frames by sign. 14 of 21 touch files contain such frames. The code documents why:
  - six of ten Brief Touch recordings were started with a finger already on a pad (`main.py` l.405–408);
  - ten of eleven Press recordings were started mid-press (l.4196–4198).

  Both are relative-zero artefacts, exactly as Proposition 1 predicts.
- **Horizontal pull never enters the negative regime** (0 of 10 files). On a flat substrate it cannot (Theorem 3, §3.3).
- **Peel** is 92.4% neg-only and never mixed.

### 2.6 Claim C3 (non-overlapping manifolds): refuted, and what holds instead

**The claim, stated formally:** $\operatorname{supp}P(\mathbf x\mid\text{anomaly})\cap\operatorname{supp}P(\mathbf x\mid\text{benign})=\varnothing$ in $\mathbb R^{25}$ (or in $\mathbb R^{34}$). There are two independent refutations.

**Refutation 1 (physics).** On a flat substrate, horizontal pull produces no lift (Theorem 3). Its only signal is contact on the tube side, which Corollary 1.1 classes as a benign-type mechanism. Its frames therefore lie in the closed non-negative regime that touches also occupy. Table 7 confirms this. Of horizontal-pull frames, 49.4% are pos-only and 50.6% have no pad beyond ±300. No frame has a pad below −300; the deepest single value in the 10 files is −201.5.

**Refutation 2 (data).** Table 8 gives:

- class-mean Mahalanobis distances, computed on standardised features with the pooled within-class covariance (Ledoit–Wolf shrinkage);
- the Bayes error the same separation would give for two equal-covariance Gaussians, $\Phi(-D/2)$.

**Table 8.** Pairwise separation (active frames; Baseline all frames).

| Pair | $D_M$ (34 features) | $D_M$ (9 statistics) | $\Phi(-D/2)$ |
|---|---|---|---|
| Baseline–Touching | 3.01 | 3.02 | 0.066 |
| Baseline–Friction | 0.44 | 0.38 | 0.413 |
| Baseline–Pulling | 1.66 | 1.49 | 0.203 |
| Baseline–Peeling | 7.70 | 7.70 | < 0.001 |
| Touching–Friction | 2.79 | 2.79 | 0.082 |
| Touching–Pulling | 2.31 | 2.18 | 0.124 |
| Touching–Peeling | 7.69 | 7.69 | < 0.001 |
| Friction–Pulling | 1.54 | 1.31 | 0.221 |
| Friction–Peeling | 7.78 | 7.75 | < 0.001 |
| Pulling–Peeling | 7.70 | 7.60 | < 0.001 |

**Cross-file nearest neighbours.** Take each active frame, standardised in 34-D, and find its nearest active frame from a *different* recording. That neighbour belongs to the opposite group (anomaly against benign) for:

- 4.7% of Pulling frames (18/381);
- 2.7% of Peeling frames (5/185);
- 10.9% of Touching frames (127/1,168);
- 7.2% of Friction frames (20/277).

**Divergences.** The Gaussian KL divergence on the 9 statistics is degenerate: values up to 1.7 × 10⁷ nats. The threshold-count features have almost no within-class variance in some classes (#{d ≤ −1000} is identically 0 in Baseline), so a Gaussian model assigns vanishing density. This is a direct argument against parametric modelling of these features.

The nonparametric k-NN estimator of Wang, Kulkarni and Verdú (k = 5, on min/max/mean/std) is finite:

**Table 9.** k-NN KL divergence, in nats.

| $D(P\Vert Q)$ | Baseline | Touching | Friction | Pulling | Peeling |
|---|---|---|---|---|---|
| **Baseline** | — | 10.89 | 8.28 | 11.17 | 12.58 |
| **Touching** | 10.10 | — | 8.34 | 6.49 | 8.03 |
| **Friction** | 5.75 | 3.97 | — | 2.67 | 5.52 |
| **Pulling** | 10.44 | 5.18 | 6.94 | — | 7.93 |
| **Peeling** | 16.30 | 13.95 | 14.89 | 11.58 | — |

Rows are $P$, columns are $Q$. Baseline divergences are inflated because resting frames are near-duplicates. The estimator is sensitive to that, so read the Baseline row and column as ordinal only.

> **Proposition 2 (what does hold).**
>
> - **Peeling is separated from every other class at the frame level.** $D_M\ge7.69$. 92.4% of peel frames are neg-only, against 15.8% of Touching frames overall (24.9% for Brief Touch alone, 29.3% for the Normal Mix reference). The nearest-neighbour overlap is 2.7%.
> - **Pulling is not.** Its frames overlap Friction ($D_M=1.54$), Baseline (1.66) and Touching (2.31).
>
> The measured 100% episode sensitivity for pulls (headline block above) is achieved by the temporal layer, through persistence over ≥ 6 of 7 frames, together with the pad-level features. It is not evidence of frame-level separability. The defensible geometric statement is about **trajectories**, not points.

### 2.7 Statistical learning theory (claims C4–C6)

#### 2.7.1 Setting

- $n=3{,}349$ frames from 81 recordings.
- Labels are constant within a recording, and frames within a recording are strongly dependent.
- The generalisation unit that a clinical claim needs is the recording (ultimately the patient, or at minimum the mounting session).

The effective sample size therefore lies between 81 and 3,349, much nearer 81.

#### 2.7.2 Capacity of the shipped model

HistGradientBoosting, as shipped, fits one regression tree per class per iteration: 150 × 4 = 600 trees, each with at most $L=31$ leaves (the scikit-learn default) and depth ≤ 8.

**One tree, lower bound.** On a single feature, $L-1$ thresholds cut the line into $L$ intervals with arbitrary labels, so $\mathrm{VC}\ge L=31$.

**One tree, upper bound.** Count the dichotomies. Take at most $4^{L-1}$ tree shapes, $d(m+1)$ choices of feature and threshold at each of the $L-1$ internal nodes, and $2^L$ leaf labellings. Then $\Pi(m)\le4^{L-1}(d(m+1))^{L-1}2^L$, and $2^m\le\Pi(m)$ gives $m\le 91+30\log_2(34(m+1))$. So $\mathrm{VC}\le513$.

**One class score.** A class score is a sum of $T=150$ trees. On one feature it is piecewise constant with up to $T(L-1)$ breakpoints, so it realises every labelling of $T(L-1)+1$ points: $\mathrm{VC}\ge4{,}501>n$.

#### 2.7.3 Vapnik's bound

With probability $\ge1-\delta$:

$$
R(h)\le\hat R(h)+\sqrt{\frac{8}{n}\Big(h\ln\frac{2en}{h}+\ln\frac4\delta\Big)} .
\tag{2.5}
$$

At δ = 0.05:

- $h=31$ (one tree): the gap term is **0.695** at $n=3{,}349$ and **2.93** at $n=81$.
- $h=4{,}501$: vacuous, because $h\ge n$.

Even a single component tree carries a 70-percentage-point bound at the frame level.

#### 2.7.4 Margin bound for voting classifiers

For $f\in\operatorname{conv}(H)$, Schapire, Freund, Bartlett and Lee (1998) give

$$
P(yf\le0)\le P_S(yf\le\theta)+O\!\Big(\sqrt{d\log^2(n/d)/(n\theta^2)+\log(1/\delta)/n}\Big).
$$

The table evaluates the complexity term as $\sqrt{d\,\log^2(1+n/d)/(n\theta^2)}$ with $d=31$. The $1+n/d$ keeps the logarithm positive at small $n$; with plain $n/d$ the $n=81$ column would read 1.19, 1.98 and 5.94, and is still vacuous.

| θ | $n=3{,}349$ | $n=81$ |
|---|---|---|
| 0.5 | 0.903 | 1.59 |
| 0.3 | 1.51 | 2.65 |
| 0.1 | 4.51 | 7.95 |

These values drop the constants, so they are optimistic, and they are still vacuous.

#### 2.7.5 Rademacher complexity

The Rademacher complexity of a convex hull equals that of its base class, and $\mathfrak R_n(H)\le\sqrt{2d\ln(en/d)/n}$ (Bartlett & Mendelson 2002). With $d=31$ and $n=3{,}349$ this gives $\mathfrak R_n\le0.324$, so the margin term $2\mathfrak R_n/\theta$ is 1.30 at θ = 0.5. Vacuous.

#### 2.7.6 Deep sequence models

Take BiLSTM, 1-D ResNet or Transformer with $W=10^5$–$10^6$ parameters.

- **Piecewise-linear networks** (ReLU MLPs and ResNets): $\mathrm{VC}=\Theta(W\bar L\log W)$, where $\bar L$ is the depth (Bartlett, Harvey, Liaw & Mehrabian 2019).
- **LSTMs and attention networks** use smooth nonlinearities (sigmoid, tanh, softmax). For such networks, the known upper bounds grow at least quadratically in $W$ (Karpinski & Macintyre 1997).

Either way the capacity is at least $10^5\gg n$, so these bounds are vacuous too.

> **Proposition 3.** At this sample size, no capacity-based guarantee (VC, margin or Rademacher) separates boosted trees from deep sequence networks. The bounds are vacuous for both.
>
> A defence that says "VC theory proves trees are better here" would be mathematically wrong. What can be defended is:
>
> 1. the inductive-bias theorem (Theorem 2);
> 2. the measured leave-one-file-out comparison among *tree* models on identical folds (`ALGORITHM_JUSTIFICATION.md` §4). No deep sequence model has been run on those folds; the BiLSTM figure comes from a separate multi-seed run (§2.7.7);
> 3. stability across seeds (§2.7.7);
> 4. the context arithmetic (§2.7.8).

#### 2.7.7 Seed variance (claim C5)

`docs/ACTION_PLAN.md` gives BiLSTM 0.9531 ± 0.0230 against RandomForest 0.9518 ± 0.0038, under one protocol. The standard-deviation ratio is **6.05** and the variance ratio **36.6**.

**Table 10.** Tests on those two summaries. The number of seeds is not recorded in the repository, so three cases are shown. The F test assumes normal seed-to-seed spread.

| Seeds per model | $F=36.6$ against $F_{0.95}$ | $p$, one-sided (BiLSTM more variable) | $p$, two-sided | Welch $t$ | $p$ (equal means) |
|---|---|---|---|---|---|
| 3 | 19.0 | 0.027 | 0.053 | 0.10 | 0.93 |
| 5 | 6.39 | 0.0021 | 0.0042 | 0.12 | 0.91 |
| 10 | 3.18 | 5 × 10⁻⁶ | 1 × 10⁻⁵ | 0.18 | 0.86 |

The sequence model is less stable across seeds. That is significant one-sided from 3 seeds, and two-sided from 5 seeds. It is also no more accurate. Three corrections follow:

1. "6× the variance" should read **"6× the standard deviation (37× the variance)"**.
2. The comparison is BiLSTM against *RandomForest*, not against the shipped HGB.
3. HGB's seed spread is exactly zero because HGB without subsampling is deterministic. That is reproducibility, not generalisation. Its data-resampling spread is 0.9844 ± 0.0062 over 100 grouped 5-fold repeats, under a different protocol (progress report §1.3).

#### 2.7.8 Context starvation, quantified

**Table 11.** Recording lengths against the context the models and the annunciator need.

| Folder | Median length | 6-frame windows after warm-up (all files) | Slack for 7-of-6 (median file) |
|---|---|---|---|
| Vertical Pull | 12 frames = 6.72 s | 26 | **1 frame** |
| Peel | 21 frames = 11.76 s | 116 | 10 frames |
| Horizontal Pull | 29.5 frames = 16.52 s | 187 | 18 frames |

A sequence model on 3.36-s windows sees about 26 overlapping vertical-pull examples, from 10 independent episodes. Fitting $10^5$ or more parameters to about 10 independent sequences produces high variance across seeds; that is the expected consequence.

The same arithmetic constrains the annunciator. A 7-of-6 vote needs 6 supporting frames, and the median vertical-pull clip leaves exactly one frame of slack after warm-up. §3.5 shows why that single frame decides the median-filter result.

#### 2.7.9 Theorem 2: trees represent gates exactly and ignore monotone warping

> **Theorem 2.** Let $g_k(\mathbf x)=\mathbb 1[x_{j_k}\le\tau_k]$, $k=1..K$, be gate indicators, and $F=B(g_1,\dots,g_K)$ for any Boolean function $B$.
>
> **(a) Representation.** An axis-aligned tree of depth ≤ K represents $F$ exactly. A single gate needs one split.
>
> **(b) Invariance.** Let $\psi_j$ be strictly increasing maps applied coordinatewise. A tree grown by exhaustive threshold search on $\psi(\mathbf X)$ induces the same partition of the training sample as on $\mathbf X$, so it gives the same fitted values on the training sample. The same holds for HistGradientBoosting, whose bins are quantile-based.
>
> The cut points are midpoints of adjacent $\psi$-values, not $\psi$ of the original midpoints. So a *new* sample falling strictly between two adjacent training values can be routed differently. The invariance is exact on the training partition, and approximate in the gaps between training values.
>
> **(c) The shipped gates.** The lift gate "some pad ≤ −300" is $x_{29}\ge1$: one split. The noise gate $\max_i|d_i|\ge60$ is $x_{26}\ge60\ \lor\ x_{25}\le-60$: two splits.
>
> *Proof.* (a) Split on $g_1$ at the root, on $g_2$ at depth 2, and so on. Each leaf is one assignment of $(g_1,\dots,g_K)$ and is labelled $B(\cdot)$.
>
> (b) Which samples a split sends left or right depends only on each feature's order statistics. $\psi_j$ preserves order, so candidate splits correspond one-to-one, with identical child sets and identical gains, and the greedy choices coincide (ties broken identically). HGB bin edges are sample quantiles (midpoints between distinct values when there are ≤ 255 of them), so bin membership is also order-determined.
>
> (c) Read directly from (1.3). ∎

**Consequence.** Rescaling, normalising or "warping" the heavy-tailed count features has no effect on the fitted trees' partition of the data. Listing 7.1 confirms identical predictions on all 3,349 frames. This is not true of gradient-trained networks, whose optimisation depends on the scale of every input. A network can represent a threshold only approximately, as a steep sigmoid or a ReLU pair, and the learned slope depends on the input scale.

**Limit of the theorem.** Theorem 2 establishes representability and invariance. It does not say which thresholds the booster learns: those are fitted from data and need not sit at −300.

---

## 3. Module 2: five-scenario boundary and sensitivity decomposition

### 3.1 Per-scenario distributions

**Table 12.** Per-file extremes, out-of-fold (`Data/five_scenarios_evaluation.json`, Kalman calibration).

| Scenario | Files | Frames | Median deepest Δ | Median max Δ | Files crossing −300 | Files annunciated |
|---|---|---|---|---|---|---|
| 1. Baseline | 5 | 589 | −33.8 | +42.0 | 0/5 | 0/5 |
| 2. Touching | 21 | 1,224 | −806.8 | +3,037.0 | 18/21 | 1/21 |
| — Brief Touch | 10 | 634 | −572.6 | +3,333.8 | 7/10 | 1/10 |
| — Sustained Press | 11 | 590 | −1,786.8 | +1,540.4 | 11/11 | 0/11 |
| 3. Friction | 10 | 362 | −76.2 | +304.8 | 0/10 | 0/10 |
| 4. Pulling | 30 | 652 | −214.8 | +508.5 | 13/30 | 30/30 |
| — Vertical | 10 | 126 | −770.9 | +555.3 | 10/10 | 10/10 |
| — Horizontal | 10 | 287 | −71.2 | +451.9 | 0/10 | 10/10 |
| — Power | 10 | 239 | −159.7 | +608.0 | 3/10 | 10/10 |
| 5. Peeling | 10 | 216 | −869.3 | +43.7 | 10/10 | 10/10 |
| Ref. Normal Mix | 5 | 306 | −544.3 | +2,784.8 | 3/5 | 1/5 |

**Table 13.** Frame-level summary (`data.summary`).

| Class | Frames | Active (≥ 60) | Median frame min | Median frame max | P(any pad ≤ −300) | P(any pad ≥ +300) |
|---|---|---|---|---|---|---|
| Baseline | 589 | 7 | −14.7 | +19.4 | 0 | 0 |
| Touching | 1,224 | 1,168 | −228.9 | +1,305.6 | 0.455 | 0.706 |
| Friction | 362 | 277 | −35.7 | +102.5 | 0 | 0.019 |
| Pulling | 652 | 381 | −16.3 | +19.2 | 0.100 | 0.310 |
| Peeling | 216 | 185 | −837.4 | −11.9 | 0.792 | 0.009 |
| Normal Mix | 306 | 276 | −326.0 | +305.3 | 0.533 | 0.500 |

**Much of each pull recording is quiet.** 271 of the 652 pull frames (42%) sit below the noise gate, and most active frames are small, so the median frame is close to zero. The event occupies a minority of each clip, and every frame carries the file's label. This frame-level label noise is why episode metrics, not frame metrics, are the reporting unit (`ALGORITHM_JUSTIFICATION.md` §7.5).

**How $P(\mathbf x\mid s)$ is modelled.** The features mix two kinds of variable:

- five integer counts in 0..25, with heavy point masses at 0;
- heavy-tailed continuous extremes.

A Gaussian model is ruled out by §2.6: its KL divergences are degenerate. The density model used here is therefore non-parametric. The k-nearest-neighbour estimate is

$$
\hat p(\mathbf x)=\frac{k}{n\,V_d\,\rho_k(\mathbf x)^d},
$$

where $\rho_k(\mathbf x)$ is the distance to the $k$-th neighbour and $V_d$ the unit-ball volume. It underlies the divergence estimator of Wang, Kulkarni and Verdú (2009):

$$
\hat D(P\Vert Q)=\frac dn\sum_{i=1}^{n}\log\frac{\nu_k(i)}{\rho_k(i)}+\log\frac{m}{n-1},
\tag{3.1}
$$

- $\rho_k(i)$: the distance from $\mathbf x_i\in P$ to its $k$-th neighbour in $P$, excluding itself;
- $\nu_k(i)$: the distance from $\mathbf x_i$ to its $k$-th neighbour in $Q$, which has $m$ points.

The Mahalanobis distances of Table 8 use class means and the pooled within-class covariance:

$$
D^2_{ab}=(\boldsymbol\mu_a-\boldsymbol\mu_b)^{\!\top}\hat\Sigma_{\text{LW}}^{-1}(\boldsymbol\mu_a-\boldsymbol\mu_b),
$$

where $\hat\Sigma_{\text{LW}}$ is the Ledoit–Wolf shrinkage estimate from the class-centred data. The shrinkage is needed because several count features are nearly constant within some classes.

### 3.2 Class geometry, scenario by scenario

Reading Tables 7, 8, 9, 12 and 13 together:

| Scenario | Signature | Separable at frame level from | Not from |
|---|---|---|---|
| Peeling | Deep negative, no positive (92.4% neg-only) | everything ($D_M\ge7.69$) | — |
| Vertical Pull | Mixed: lift at the trailing edge, compression at the leading edge | Friction, Baseline | Touching (by sign) |
| Horizontal Pull | Positive only (49.4%), or no pad beyond ±300 (50.6%); never below −300 | Peeling | Touching, Friction, Baseline |
| Power Pull | Mostly positive; 3 of 10 files cross −300 | Peeling | Touching |
| Touching | Positive, plus relative-zero negatives | Peeling | Pulling |
| Friction | Low amplitude: 97.5% of active frames have no pad beyond ±300 | Peeling, Touching | Baseline, Pulling |

The hardest pairs are Friction–Pulling ($D_M=1.54$, k-NN KL 2.67 nats), Baseline–Pulling (1.66) and Baseline–Friction (0.44). The detector reaches 30/30 on pulls through the temporal layer and the pad pattern, with a margin that this geometry shows is thin.

### 3.3 The horizontal-pull anomaly and ground-plane transduction

#### 3.3.1 Observation

Median deepest delta over the 10 horizontal-pull files, under each calibration (`translation_plan_checks.py`, `hpull_depth`):

| Calibration | Median deepest Δ | Deepest single | Median max | Files over −300 |
|---|---|---|---|---|
| static | −111.4 | −212.4 | +442.9 | 0/10 |
| Kalman (offline) | −71.2 | −201.5 | +451.9 | 0/10 |
| served (LivePipeline) | −74.8 | −202.5 | +452.2 | 0/10 |

These are the same finding under three zeros. METRICS caveat 6 quotes a fourth set of numbers (−64 / −161 / +456) as a hard-coded string; it should be generated from the data and name its calibration (see `TRANSLATION_PLAN_24M.md`).

#### 3.3.2 Theorem 3: pure shear over a laterally uniform substrate leaves capacitance unchanged

> **Theorem 3 (translation invariance).** Suppose the permittivity field and the grounded set outside the moving electrode assembly are invariant under the in-plane translation $\mathbf r\mapsto\mathbf r+s\mathbf e$. Translate the electrode assembly rigidly by $s\mathbf e$. Then $C(s)=C(0)$ for every $s$.
>
> *Proof.* Let $\Phi_0$ solve (2.1) at $s=0$. The field $\Phi_s(\mathbf r)=\Phi_0(\mathbf r-s\mathbf e)$ satisfies (2.1) with the translated permittivity, which by hypothesis equals the original. It takes the value 1 on the translated electrode and 0 on the grounded set, which is invariant. By uniqueness it is the solution. Its energy integral equals that of $\Phi_0$ by the change of variables $\mathbf r\to\mathbf r-s\mathbf e$. ∎

**Corollary 3.1.** Sliding the dressing over a flat, laterally uniform substrate gives ΔC = 0 exactly, to every order in $s$. This holds for acrylic, for skin, and for skin over a *continuous* ground plane. A continuous ground plane under the artificial skin preserves the symmetry, so **it cannot convert shear into a capacitance change**. This refutes claim C7 as written.

**Corollary 3.2.** Any capacitance signal from a horizontal pull must come from something that breaks the symmetry:

1. **Normal displacement:** lift at the trailing edge or compression at the leading edge, signed by Theorem 1.
2. **Contact:** the tube or its tape pressing on the dressing, which reads as a press (ΔC > 0).
3. **Lateral non-uniformity:** plane edges, the tube, or patterned electrodes.
4. **In-plane strain of the dressing.** Under tension the adhesive thins, which is a second-order ΔC > 0.

The corpus matches mechanism 2: the positive side moves (+452) and the negative side does not.

#### 3.3.3 A finite plane responds only near its edge

This is a 2-D finite-volume model (`planar_edge`): a 7-mm strip electrode, 0.3 mm of hydrocolloid (εr 3.5) above a grounded plane that exists only for $x<0$, and a 7-mm strip length. $x_0$ is the position of the strip centre.

**Table 14.** Edge response.

| $x_0$ (mm) | −15 | −8 | −5 | −3.5 | −2 | 0 | +2 | +3.5 | +6 |
|---|---|---|---|---|---|---|---|---|---|
| $C$ (pF) | 5.44 | 5.44 | 5.43 | 5.33 | 4.29 | 2.84 | 1.39 | 0.32 | 0.07 |
| $C/C_\infty$ | 1.000 | 0.999 | 0.998 | 0.980 | 0.788 | 0.522 | 0.256 | 0.059 | 0.012 |

- The response is confined to $|x_0|\lesssim w/2$ around the edge. Beyond −3.5 mm it is 98–100% flat.
- The steepest slope, between −2 and +2 mm, is 0.72 pF/mm, or about 43 counts/mm.
- A patterned plane could therefore transduce shear, but only for pads that sit on an edge, and only in proportion to the displacement. §3.3.4 shows that displacement is a fraction of a millimetre.

#### 3.3.4 A differential shear cell, and the size of the signal

This is a 2-D finite-volume model (`shear_cell`): a 5-mm top electrode on the dressing, over two 5-mm receivers on the substrate with a 0.2-mm gap between them, 0.5 mm of soft εr-3 layer, and a 5-mm length.

**Table 15.** Mutual capacitance to each receiver as the top electrode slides by $s$.

| $s$ (mm) | 0 | 0.10 | 0.25 | 0.50 |
|---|---|---|---|---|
| $C_L$ (fF) | 755.7 | 782.1 | 821.6 | 887.3 |
| $C_R$ (fF) | 755.7 | 729.3 | 689.8 | 623.8 |
| $C_L-C_R$ (fF) | 0 | 52.7 | 131.8 | 263.5 |

The differential output is linear to 0.5 mm, at a slope of **527 fF/mm**.

What displacement does a 10 N pull produce? Assume a soft-silicone layer (G = 100 kPa), 20 × 20 mm of anchor and h = 0.5 mm (all ASSUMED). Then $s=Fh/(GA)=0.125$ mm, which gives **66 fF, or 3.9 counts**. That is below the 60-count noise gate and about 0.5σ per frame.

Shear is observable, but only with a dedicated differential cell read by a converter with femtofarad-level noise, or with a force or strain sensor in the tube anchor. A ground plane does not provide it.

#### 3.3.5 What the round-2 ground plane does do

- **It defines the return path.** It makes the bench "body" a conductor, so round-2 transfer functions resemble the patient's (Lemma 1, Remark 2.1).
- **It can raise $C_{\text{body}}$** (thinner or closer: $C=\varepsilon_0A/\sum t/\varepsilon_r$). That enlarges the span $S$ available to lift and peel, which helps vertical pull and peel (Theorem 5).
- **It moves the ≤ 25,000 question only through $C_{\text{body}}$** (Theorem 4).
- **It does nothing for pure shear** (Theorem 3).

### 3.4 Sensitivity to modelled sensor perturbations

**Table 16.** Leave-one-file-out, 40 anomaly and 41 normal recordings, 7-of-6 hold 9. The perturbation is applied to raw counts.

- *kalman*: `Data/robustness_evaluation.json`. The copy on the project machine is stamped 2026-09-25 00:18:42 by the nightly run, and its figures are identical to the 2026-09-18 run.
- *kalman_norm* (adds F10): `Data/robustness_evaluation_kalman_norm.json` and `Data/rob_kn_jitter.json`.

| Variant | Sens. (kalman) | FA files | Alarms/h | Missed (kalman) | Sens. (kalman_norm) | FA files | Alarms/h |
|---|---|---|---|---|---|---|---|
| identity | 100% | 2 | 7.8 | — | 100% | 2 | 7.8 |
| gain ×1.10 | 100% | 3 | 10.4 | — | 100% | 3 | 10.4 |
| gain ×0.90 | 95.0% | 3 | 10.4 | VPull 01, 04 | 100% | 3 | 10.4 |
| gain ×1.20 | 97.5% | 4 | 13.0 | VPull 01 | 97.5% | 3 | 13.0 |
| gain ×0.80 | 97.5% | 3 | 7.8 | VPull 04 | 100% | 3 | 10.4 |
| per-pad gain ±10% | 100% | 2 | 7.8 | — | 100% | 2 | 7.8 |
| noise σ 30 | 92.5% | 3 | 10.4 | VPull 01, 04, 06 | 92.5% | 2 | 7.8 |
| noise σ 60 | 85.0% | 3 | 13.0 | VPull 04, 06; HPull 02, 07, 09; VP_3 | 87.5% | 3 | 7.8 |
| noise σ 120 | 62.5% | 2 | 5.2 | 7 VPull, 6 HPull, 2 PowerP | 60.0% | 2 | 5.2 |
| frame drop 10% | 95.0% | 2 | 5.7 | VPull 01, 04 | 95.0% | 2 | 5.7 |
| spike +5,000 on 1% of frames | 95.0% | 3 | 10.4 | VPull 08, 09 | 95.0% | 3 | 10.4 |
| noise σ 60 + causal median-3 | — | — | — | — | **72.5%** | 5 | 15.5 |

**(a) Gain: F10 is aligned with this test, but only partly.** The perturbation multiplies the whole raw count, offset included: $N\to gN$. F10 divides $d$ by $b=gN_0$ and multiplies by 28,000, which cancels $g$ in the ratio.

The Kalman stage runs before F10, and its thresholds do not scale with $g$: the 120-count innovation gate (l.595) and $r$ clipped to [20, 150] (l.636). So the cancellation is partial:

- sensitivity recovers at ×0.9 and ×0.8, but not at ×1.2;
- every global-gain row keeps 3 false-alarm files, against 2 at identity.

A physical change of mounting does not act like this. Under (1.2):

- a change in $C_{\text{par}}$ or in $a$ shifts $N$ additively and leaves every count delta unchanged;
- a change in $C_{\text{body}}$ changes the delta itself. F10 cannot correct this, because $b$ is 94% offset: $a=26{,}204.5$ of 28,000 counts under the repository's constants.

So the gain rows test F10 against the one perturbation it was built to invert, and even there the Kalman stage limits it. They are not evidence of robustness to a new mounting (§5.6 gives the invariant that is).

**(b) Noise, through the gate leak and the vote.** A noise-only frame passes the 60-count gate if any of the 25 pads exceeds it:

$$
P_{\text{leak}}(\sigma)=1-\big(1-2Q(60/\sigma)\big)^{25}.
$$

| σ (counts) | 8.4 | 15 | 20 | 30 | 45 | 60 |
|---|---|---|---|---|---|---|
| $P_{\text{leak}}$ | 0.000 | 0.002 | 0.065 | 0.688 | 0.994 | 1.000 |

The leak reaches 5% at σ = 19.5 counts. Beyond that, noise frames reach the classifier and the per-frame vote probability $p$ on event frames falls. The k-of-n vote then amplifies the loss (Table 17).

The misses concentrate in:

- the short vertical-pull clips (one frame of slack);
- horizontal pull, whose only signal is the weak positive contact (+452).

**(c) Noise alone does not raise alarms.** Synthetic Gaussian noise streams (6,000 frames, about 56 min, at each of σ = 30, 60, 120) produce **0.0 alarms/h**, raw and median-filtered (`noise.noise_only_alarms`). Noise makes the device deaf, not jumpy. The measured false-alarm increases come from noise interacting with real touch recordings.

**(d) Frame drops** shorten clips. The two misses, VPull 01 and 04, are among the shortest.

**(e) Spikes.** A +5,000 spike takes a pad to about 33,000 counts, below the 50,000 surge filter (l.2741–2756). It exceeds the 120-count innovation gate, so the Kalman baseline does not absorb it. The spiked frame no longer resembles the event. In a short clip, one non-supporting vote loses the episode: the two misses, VPull 08 and 09, have 2 and 0 frames of clip slack.

- Probability of a spike within a 7-frame window: $1-0.99^7=6.8\%$.
- Observed: 2/40 = 5%.

A 3-tap median removes an isolated spike exactly, which is its textbook use. It was evaluated only on Gaussian noise.

### 3.5 Why the causal median lowered sensitivity from 87.5% to 72.5%

**Status of the filter.** The filter (`adaptive_jitter_filter`, l.690–735) was wired in on 2026-09-18, measured, and removed. It is not in the serving path, and `tests/test_jitter_suppression.py` pins that. Its docstring blames a delay of "up to two frames" plus shortening. Proposition 4 below sharpens that: for a step-like event the delay is exactly one frame and the duration is preserved. The event is *shifted*, not shortened. Because vertical-pull events run to the end of their clips, the shift pushes one supporting frame past the last sample. The listing in §7.2 checks this on the shipped function.

**The data** (kalman_norm, noise σ 60, `Data/rob_kn_jitter.json`):

- **Without the median:** 35/40 detected. Missed: VPull 06; HPull 02, 07, 09; VP_3.
- **With the median:** 29/40 detected. Missed: VPull 01, 02, 04, 06, 07, 08, 09; HPull 02, 07, 09; VP_3.
- **The six extra misses are VPull 01, 02, 04, 07, 08 and 09, all vertical pulls.** No horizontal-pull or power-pull outcome changed.
- **Their clips are 11–15 frames long.** Clip slack after warm-up and six votes is 1, 1, 0, 4, 2 and 0 frames respectively. The pull itself occupies only the last few frames of each clip, so the slack available to the event is smaller still.

> **Proposition 4 (causal 3-tap median, $y_t=\operatorname{med}(x_{t-2},x_{t-1},x_t)$).**
>
> (a) **Step response.** For a step at $t_0$, $y_{t_0}$ still equals the old level and $y_t$ equals the new level for $t\ge t_0+1$. Onset is delayed by exactly one frame, and a falling edge is extended by one frame.
>
> (b) **Gaussian input.** For i.i.d. $\mathcal N(0,\sigma^2)$ input, $\operatorname{Var}(y)\approx0.45\,\sigma^2$, so $\sigma_y\approx0.67\,\sigma$. The output is correlated, with $\rho_1=0.55$ and $\rho_2=0.26$.
>
> (c) **Impulses.** An isolated impulse of any amplitude is removed completely.
>
> *Proof.* (a) At $t_0$ the window holds two old samples and one new one, so the median is old. At $t_0+1$ it holds two new samples. (c) follows the same way. (b) is the variance of the median of three normals, confirmed by simulation (`noise.median3`). The correlations come from consecutive windows sharing two samples (lag 1) or one sample (lag 2). ∎

> **Proposition 5 (one lost frame in a k-of-n vote).** Suppose an event offers $m$ post-warm-up frames, each voting with probability $p$ independently. Table 17 gives $P(\text{alarm})$ for the 7-of-6 annunciator, computed by exact enumeration (`annunciator`).

**Table 17.** $P(\text{alarm})$ without → with a one-frame onset loss.

| $p$ | $m=6$ | $m=7$ | $m=8$ | $m=10$ |
|---|---|---|---|---|
| 0.99 | 0.941 → **0** | 0.998 → 0.941 | 0.999 → 0.998 | 0.999 → 0.999 |
| 0.95 | 0.735 → **0** | 0.956 → 0.735 | 0.967 → 0.956 | 0.984 → 0.976 |
| 0.90 | 0.531 → **0** | 0.850 → 0.531 | 0.882 → 0.850 | 0.932 → 0.909 |
| 0.80 | 0.262 → **0** | 0.577 → 0.262 | 0.640 → 0.577 | 0.742 → 0.694 |

**The mechanism, assembled.** At σ = 60 the median lowers the noise standard deviation by only a third (Proposition 4b). The filtered noise, at about 40 counts, still leaks through the gate on 97% of frames, so $p$ barely improves. Meanwhile the median removes one supporting frame from every onset (Proposition 4a).

- In the long clips (peel, horizontal pull: 10–18 frames of slack) that costs at most a few points.
- In the vertical pulls, whose median clip leaves one frame of slack (Table 11), it is decisive. At $p=0.9$, $P(\text{alarm})$ falls from 0.85 to 0.53. At $m=6$ it falls to exactly zero.

The failure is therefore not that the median "cannot handle high-frequency noise". It is a latency cost charged to a vote that has no latency to spare, on a corpus whose shortest clips end within one frame of the minimum evidence.

**Open item: the false-alarm rise.** False alarms rose from 3 to 5 normal files (7.8 → 15.5 alarms/h). Noise alone produces none (§3.4c), so the rise must come from the filter interacting with real touch transients. Plausible causes are the trailing extension and the correlated output lengthening vote runs. `rob_kn_jitter.json` does not record which files alarmed, so the mechanism is open.

**Design consequences.**

1. **Use the median on impulsive faults** (spikes, single-frame glitches), where it is exact.
2. **Give the vote slack.** The round-2 SOP's 60–120 s recordings remove the clip-length artefact. A real event with less than 3.36 s of evidence stays invisible at 7-of-6 (`main.py` l.522–530).
3. **Treat Gaussian noise at the front end.** Scan resolution and averaging are the levers, and so is frame rate: at 10 Hz the six votes take 0.6 s instead of 3.36 s. A filter after the fact is not.

---

## 4. Module 3: relative offset versus absolute capacitance

### 4.1 A model of start-up zeroing bias

**The bias.** Under (1.2), the Kalman seed is taken from the first frame on the device, or the mean of the first five frames offline:

$$
b_i(0)=a_i+\beta\big(C_{\mathrm{par},i}+C_{\mathrm{body},i}\,g_i(z_0)+\Delta C_{s,i}\big).
$$

- $\Delta C_{s,i}$ is any transient load present during seeding (a finger, pressure).
- $z_0$ is the lift of the pad at power-on.

The correct zero is the attached reading $N_i^{\text{att}}=a_i+\beta(C_{\mathrm{par},i}+C_{\mathrm{body},i})$, so the bias is

$$
e_i=b_i(0)-N_i^{\text{att}}=\beta\Big[\Delta C_{s,i}-C_{\mathrm{body},i}\big(1-g_i(z_0)\big)\Big].
\tag{4.1}
$$

**What the pad reads afterwards.** Until the baseline adapts,

$$
d_i(t)=\beta\,C_{\mathrm{body},i}\big(g_i(z(t))-1\big)-e_i .
$$

The Kalman filter cannot remove a standing $|e_i|>120$ counts, because its gain is zero whenever the innovation exceeds its gate (l.595, l.644).

**Table 18.** Power-on conditions and their consequences.

| Power-on condition | $e_i$ | What the pad reads afterwards | Effect on detection |
|---|---|---|---|
| Clean, attached | 0 | true deltas | nominal |
| Finger or pressure on pad $i$ | $+\beta\Delta C_s$ | $-\beta\Delta C_s$ after release: a **phantom lift** | false lift until quiescent recovery (§4.3). If ≥ 3 pads, a phantom peel that recovery never touches |
| Patch loose or lifted | $-\beta C_{\text{body}}(1-g(z_0))$ | $+\beta C_{\text{body}}(1-g)$ once seated: a **phantom press**. A later detachment returns only to the boot zero | the detection margin shrinks by the fraction lost at boot |
| Booted in air ($g(z_0)\approx0$), then applied | $-\beta C_{\text{body}}$ | a standing positive offset: +276 counts on the stated stack, or +1,496 in the `cdc_seed` scenario (5 pF in air, 30 pF attached, i.e. 25 pF of body coupling). A full detachment then brings $d$ back to ≈ 0 and **never crosses −300** | **detachment invisible to the lift gate** |
| Tube pre-taped under some pads | those pads start with $C_{\text{body}}\approx0$ | no span to lose | blind pads (Theorem 5) |

The fourth row is the most serious.

- Quiescent recovery only acts below the lift gate, so it never removes a positive offset.
- The seed band catches a boot in air only if $\beta C_{\text{body}}>525$ counts (28,025 − 27,500), i.e. $C_{\text{body}}>8.8$ pF. On the stated stack (4.6 pF) the boot median stays inside the band, so the bad zero is silent.

### 4.2 `seed_plausibility()`: what it can and cannot see

The function makes two tests (l.4214–4274). Both are advisory: they change no classification (l.469–472).

**(a) Band test on the 25-pad median.** A median has a breakdown point of 50%, so the band moves only if 13 or more pads move. For a uniform shift of the five `N_base` seeds, simulated (`seed.loose_detect`):

- −400 counts is flagged in 0 of 5;
- −500 counts is flagged in 5 of 5.

**(b) Shape test.** Each pad is compared with the offset-corrected `SEED_RESTING_SHAPE` at 575 counts, about 9.6 pF. Pads pressed by $+P$ during seeding, 200 trials per cell (`seed.press_detect`):

**Table 19.** Detection rate of the shape test.

| Pads pressed | +200 | +400 | +500 | +600 | +800 | +1,200 |
|---|---|---|---|---|---|---|
| 1 | 0% | 0% | 0% | 53.5% | 100% | 100% |
| 2 | 0% | 0% | 0% | 28.5% | 100% | 100% |
| 5 | 0% | 0% | 0% | 4% | 100% | 100% |

Detection falls as more pads are pressed at +600. The pressed pads raise the frame median, which shifts the offset-corrected reference and eats the 25-count margin above the gate.

On the stated stack, a firm finger (+852 counts in the finite-volume model) is caught. A light touch of 8 pF or less is not.

**The gate cannot be set lower.** The resting shape itself varies by 249.7 counts (4.17 pF) from pad to pad. The five untouched `N_base` recordings already reach 189 counts of deviation (l.449–452).

### 4.3 Quiescent baseline recovery: dynamics and limits

**Conditions** (`_apply_quiescent_recovery`, l.2651–2721). All must hold:

- the pad is below −300 counts;
- fewer than 3 pads are below −300;
- the pad's raw standard deviation is under 15 counts over the last $\lceil3.0/0.56\rceil=6$ frames.

**Action.** The pad's covariance grows as $P\leftarrow\min(1.6P,\,4r)$, and its innovation gate opens to $|d|+1$. Recovery engages at −300 and releases at −60 (hysteresis).

**Dynamics.** In normal tracking with $q=0.05$ and $r=40$, the steady-state prior covariance solves $P^2-qP-qr=0$:

$$
P^-=\tfrac12\big(q+\sqrt{q^2+4qr}\big)=1.44,\qquad K_{ss}=\frac{P^-}{P^-+r}=0.035 .
$$

**Under recovery the covariance does not reach its cap.** `step()` first applies the posterior update $P\leftarrow(1-K)(P+q)$ (l.664), and recovery then multiplies by 1.6. While the pad's gate is open, one frame therefore maps

$$
P\ \mapsto\ 1.6\,(1-K)(P+q),\qquad K=\frac{P+q}{P+q+r} .
$$

Its fixed point is $P\approx0.6r=24$, i.e. $K\approx0.375$. The $4r$ cap binds only after runs of gate-closed frames. In the simulation $K$ stays between about 0.1 and 0.7, and the offset decays by $(1-K)$ per frame.

The comment at `main.py` l.419 ("Kalman gain tops out near 0.8") assumes the cap is reached, which it is not.

**Table 20.** Simulated recovery: σ = 8.4, pad 4 seeded high, released at frame 12 (`seed.recovery`).

| Seed contamination | Recovery engaged after release | Pad back inside ±60 |
|---|---|---|
| +400 | 2.8 s | 7.84 s |
| +800 | 2.8 s | 8.40 s |
| +1,500 | 2.8 s | 9.52 s |
| −1,500 single-pad fault (`pad_fault`) | 2.8 s | 8.96 s; `disconnected` never set |

**Limits.**

1. **A genuine single-pad detachment or electrode fault is absorbed silently within about 9 s.** The code states this as its residual risk (l.2666–2670). The fault is invisible to the operator.
2. **Contamination on three or more pads is never recovered.** A palm resting on the patch at power-on leaves a phantom peel front after release, until a manual re-seed.
3. **Slow ramps are invisible (the Kalman blind zone).** A ramp of $v$ counts per frame is tracked with a steady-state error of about $v/K_{ss}$. It stays inside the 120-count innovation gate, and so never reaches −300, when
   $$
   v<K_{ss}\cdot120=4.17\ \text{counts/frame}=7.44\ \text{counts/s}\approx0.124\ \text{pF/s}.
   $$
   A peel slower than that is absorbed into the baseline. Absorbing the deepest recorded peel (−902 counts) takes 121 s (`translation_plan_checks.py`, `kalman_ramp`).

### 4.4 The absolute-CDC path, as coded today

Three findings.

**(a) The seed check is blind in CDC mode.** In CDC mode, `LivePipeline` converts every frame relative to the *first* frame: `working = (c − c_init)·β + 28,000` (l.2737–2739). So $b_i(0)=28{,}000$ exactly on every pad, and `seed_plausibility` sees a flat, in-band patch whatever the absolute capacitances were. Simulated power-on frames (`translation_plan_checks.py`, `cdc_seed`):

| Power-on frame | CDC path | Counts path |
|---|---|---|
| 3, 5, 12, 30 or 45 pF | `attached_band` in every case | — |
| 5 pF (26,504 counts) | — | `below_band` |
| 45 pF (28,898 counts) | — | `above_band` |

**(b) The adaptive gates are uniform.** They are computed from the counts-mode Kalman baseline, which is 28,000 on every pad. Every pad therefore gets **−308** (`adaptive_gates.live_cdc_gates_unique`).

**(c) Tube localisation is not on the live path.** It exists only as the REST endpoint `/api/v6/cdc/tube-localization` (l.3449–3464). `LivePipeline` never calls it.

So in the live CDC path, the absolute measurement, which is the reason to buy a converter, is discarded after the first frame. Claim C15 does not hold for the code today.

**The fix is structural:**

1. Seed from the absolute map.
2. Compare it against a per-pad attached reference $C_i^{\text{ref}}$ and an air map $C_i^{\text{air}}$ taken before application.
3. Carry the per-pad span $S_i=\beta(C_i^{\text{ref}}-C_i^{\text{air}})$ into the gates (§5.6) and into tube localisation (§4.5).

### 4.5 Static tube localisation

#### 4.5.1 Physics of the shadow

By Lemma 1, a pad's absolute capacitance is $C_i=C_{\mathrm{par},i}+C_{\mathrm{body},i}\,g(h_i)$, where $h_i$ is the pad's height above the skin.

**A tube under pad $i$.** It lifts the pad by between $a$ and $2a$ (4.5–11.5 mm).

- Parallel-plate coupling at those heights is 0.03–0.06 pF, against 3.975 pF flush.
- Fringing raises the residual, but not above the finite-volume value at 3 mm (0.36 pF of 4.61 pF).

So the pad loses at least 92% of its body coupling, about −3.9 pF on the stated stack (§5.3).

**The tube's own permittivity plays a secondary role.** The height comes from the tube's full diameter, and most of that height is the air lumen, not the εr-2.8 wall. How much the wall's permittivity changes $g$ would need a 2-D model with wall and lumen, which is not computed here. The "dielectric shadow" is therefore primarily a **lift-off shadow**. The εr 2.8 against 50–80 contrast invoked in `main.py` (l.2962–2964) and `ALGORITHM_JUSTIFICATION.md` §8 is not the mechanism.

**A tube on top of the dressing** (outside it) adds dielectric above the electrode. By Theorem 1(a) that makes ΔC slightly *positive*. The sign of the "shadow" depends on which side of the dressing the tube lies.

**The shadow model:**

$$
\Delta C_i^{\text{shadow}}=C_i^{\text{ref}}-C_i=C_{\mathrm{body},i}\big(1-g(h_i)\big),
\tag{4.2}
$$

where $h_i$ follows from the pad's distance to the tube axis. The simulations below use a band of half-width 6 mm, a 7-mm pad footprint and a depth of 3.7 pF.

#### 4.5.2 The shipped detector

**Algorithm** (`detect_static_tube_localization`, l.2956–3011):

1. Compute the median $m$ and $\mathrm{MAD}$ of the 25 pads.
2. Set $\tau=\operatorname{clip}(1.5\cdot1.4826\cdot\mathrm{MAD},\,0.35,\,1.5)$ pF.
3. Mark as shadowed every pad with $m-C_i\ge\tau$. A tube is declared if at least 3 pads are shadowed.
4. Choose the axis from the max−min spread of the shadowed pads in percent coordinates: *diagonal* if both spreads are ≥ 25, otherwise *vertical* if $\text{spread}_y\ge\text{spread}_x$, otherwise *horizontal*.

**Findings.**

1. **It fires on the patch's own shape.** Fed the resting shape (`SEED_RESTING_SHAPE`/β about 30 pF; pad-to-pad SD 4.17 pF) with **no tube**, it reports `detected=True`, pads [6, 10, 12, 15, 16, 17, 24, 25], `diagonal`.
2. **A fixed-quantile threshold on 25 pads fires by chance.** At τ ≈ 1.5σ each pad crosses with probability $\Phi(-1.5)\approx6.7\%$, so three or more pads cross about a quarter of the time. Above 1 pF of spread the clamp at 1.5 pF makes this worse, which Table 21 shows.
3. **The coordinates are anisotropic.** Coordinates are percent of a 90 × 120 mm patch. A true 45° line appears at 36.9°, and the "25-unit" diagonal rule means 22.5 mm in x but 30 mm in y.
4. **The spread statistic is fragile.** Max−min is decided by the two extreme shadowed pads, so one spurious pad can flip the axis.

**Table 21.** Localisation, 60 trials per cell (`tube.sim`). Tube depth 3.7 pF; pad noise 0.05 pF.

| Pad-to-pad SD | Truth | Shipped: "detected" | Shipped: axis correct | Matched filter: detected (p < 0.01) | Matched filter: median angle error |
|---|---|---|---|---|---|
| 0.2 pF | none | 13% | — | **0%** | — |
| 0.2 pF | vertical | 100% | 100% | 100% | 0° |
| 0.2 pF | horizontal | 100% | 87% | 100% | 0° |
| 0.2 pF | diagonal 45° | 100% | 100% | 100% | 0° |
| 1.0 pF | none | 38% | — | **0%** | — |
| 1.0 pF | vertical | 97% | 86% | 68% | 0° |
| 1.0 pF | horizontal | 100% | 65% | 95% | 5° |
| 1.0 pF | diagonal 45° | 92% | 100% | 53% | 0° |
| 3.0 pF | none | **100%** | — | **0%** | — |
| 3.0 pF | vertical | 100% | 3% | 7% | 2.5° |
| 3.0 pF | horizontal | 100% | 2% | 10% | 10° |
| 3.0 pF | diagonal 45° | 100% | 100% | 3% | 45° |

At 3 pF of spread the shipped detector "detects" every case, including no tube, and calls nearly all of them diagonal. Its 100% axis accuracy on the diagonal case is an artefact of that.

#### 4.5.3 A matched-filter (discrete Radon) localiser

**Templates.** Let the pad centres be $\mathbf p_i$ in millimetres. For a line with unit normal $\mathbf n_\theta$ and offset $\rho$, the template is the fraction of pad $i$ (radius $r_p=3.5$ mm) inside a band of half-width $w=6$ mm:

$$
t_i(\theta,\rho)=\operatorname{clip}\!\Big(\frac{w-|\mathbf p_i\!\cdot\!\mathbf n_\theta-\rho|+r_p}{2r_p},\,0,\,1\Big).
\tag{4.3}
$$

**Statistic.** Take the shadow depths $v_i=\operatorname{med}(C)-C_i$ and standardise both vectors to unit norm: $\hat z=(v-\bar v)/\lVert v-\bar v\rVert$ and $\hat t=(t-\bar t)/\lVert t-\bar t\rVert$. Then

$$
S(\theta,\rho)=\langle\hat z,\hat t(\theta,\rho)\rangle\in[-1,1],\qquad
(\hat\theta,\hat\rho)=\arg\max_{\theta,\rho}S .
\tag{4.4}
$$

The grid is 5° in θ and 2 mm in ρ. $S$ is the discrete Radon transform of the shadow map sampled at the pads, correlated with the band profile. Equivalently, it is a Hough accumulator in which each pad votes with weight $\hat z_i$ for every line crossing its footprint.

**Optimality.** Suppose $C_i=\mu-A\,t_i(\theta,\rho)+\varepsilon_i$ with i.i.d. Gaussian $\varepsilon_i$ and unknown $A>0$. Then the generalised likelihood-ratio test is monotone in $\max S$. So (4.4) is the GLRT, and $(\hat\theta,\hat\rho)$ are the maximum-likelihood estimates.

**Calibration.** Under $H_0$ (no tube, exchangeable pad deviations), the null distribution of $\max S$ comes from permuting $\hat z$ across pads 300 times:

$$
p=\frac{1+\#\{S^{\text{perm}}_{\max}\ge S_{\max}\}}{1+300}.
$$

A tube is declared when $p<0.01$. This holds the false-positive rate at 1% whatever the spread: 0% was observed in every no-tube row of Table 21.

**Identifiability.** Detection power depends on the ratio of shadow depth to pad-to-pad spread:

| Spread | Detection |
|---|---|
| 0.2 pF | ≥ 95% |
| 1 pF | 53–95% |
| 3 pF | ≤ 10% |

The spread cannot be removed statistically. It has to be removed by measurement: store the per-pad reference $C_i^{\text{ref}}$ (the same patch on skin with no tube, taken at application), and localise on $C_i^{\text{ref}}-C_i$. What remains is then measurement noise plus re-attachment repeatability.

SOP v2 accepts 20% variation between re-attachments. On a coupling of about 4 pF that is 0.8 pF: borderline for localisation, so that tolerance has to tighten. The listing is in §7.4.

### 4.6 Theorem 4: the ≤ 25,000-count criterion

> **Theorem 4.** Let a pad's readout $N=f(C)$ be strictly increasing. On complete detachment the pad's capacitance is $C_{\mathrm{par}}\ge0$, which includes its free-space capacitance (Theorem 1). Therefore $N_{\text{det}}=f(C_{\mathrm{par}})\ge f(0)$.
>
> (a) **Under the repository's constants,** $f(C)=a+\beta C$ with $a=26{,}204.5$ and $\beta=59.85$, so $N_{\text{det}}\ge26{,}204.5>25{,}000$. The criterion is unreachable by at least 1,204.5 counts, even at $C=0$.
>
> (b) **Stated exactly,** $N_{\text{det}}\le25{,}000$ requires a drop of $\beta\,C_{\mathrm{body}}\ge3{,}000$ counts, i.e. $C_{\mathrm{body}}\ge50.13$ pF. This is a condition on the **body-coupled part** of $C_0$, not on $C_0$ itself as `main.py`'s docstring frames it. On the stated stack, $C_{\mathrm{body}}\approx4.6$ pF, so $N_{\text{det}}\approx27{,}724$: short by about 2,724 counts, not 1,205.
>
> (c) **As a relative criterion,** the spec asks for $3{,}000/28{,}000=10.71\%$ of the resting count. The deepest recorded peel reached $902.4/28{,}000=3.22\%$.
>
> *Proof.* $f$ is monotone, and $C_{\text{det}}=C_{\mathrm{par}}\le C_{\text{att}}$ by Theorem 1. ∎

**Everything rests on $f$, which has never been measured.**

**Table 22.** Two hypotheses for the transfer.

| | H1: affine with a fixed offset (repository) | H2: per-channel auto-calibration to 85% of full scale |
|---|---|---|
| Transfer | $N=a+\beta C$ | $N=0.85N_{FS}+\beta_i(C-C_{0,i})$; $\beta_i$ set by the calibrated IDAC |
| What the resting count encodes | $C_0$, given $a$ | nothing about $C_0$: every channel is steered to the target |
| Reading on full detachment | $a+\beta C_{\mathrm{par}}$ | $27{,}852-\beta_iC_{\mathrm{body},i}$ |
| ≤ 25,000 reachable iff | $C_{\mathrm{body}}\ge50.1$ pF | $\beta_iC_{\mathrm{body},i}\ge2{,}852$ |

For H2, $0.85\times(2^{15}-1)=27{,}852$ counts. The corpus's resting median, 28,025, is +0.62% from that value. This is suggestive, not evidence; the 16-bit equivalent would be 55,705.

- The board is a PSoC 5LP (CY8CKIT-059), and its CapSense configuration is [FILL] in `Hardware_Deck_Spec.md`.
- The 85% target is how Infineon's SmartSense auto-tuning is described in Infineon's community forum (source list). Whether it is enabled on this board is unknown.

**If H2 holds:**

1. 28,000 is a calibration target, not a capacitance.
2. 26,205 is not a floor.
3. β can differ by channel and by power cycle, so a single 59.85 counts/pF measurement may not transfer.
4. F10's division by $b$ normalises nothing.

**If H1 holds,** the constants imply $C_0=30$ pF only because that value was assumed.

The measurement that decides between them is cheap (§4.7, step 0).

### 4.7 LCR protocol for the absolute $C_0$ (formalises SOP v2 §0.2)

**Objective.** Measure the transfer $f$, the per-pad $C_{\mathrm{body},i}$ and $C_{\mathrm{par},i}$, and per-channel β, before any converter's dynamic range is frozen.

**Equipment:**

- an LCR meter with ≤ 0.1 pF resolution and test frequencies of 100 kHz and 1 MHz, plus the CapSense excitation frequency if it can be read from the firmware;
- shielded leads;
- NP0/C0G reference capacitors of 10, 22 and 47 pF (±1%);
- a hydrogel ECG electrode (forearm) or the phantom's conductive contact, as the body terminal;
- the board, logging.

**Step 0: transfer identification.** About 15 minutes, no patch; decides H1 against H2.

- (a) Board running, pad in air: add 10, 22 and 47 pF in parallel from one sense line to board ground. Record ΔN for each. This gives slope $\beta^{(0)}$ and its linearity.
- (b) Power-cycle with each capacitor attached and record the resting count:
  - **H2** if it returns to about the same value (≈ 27,852) each time;
  - **H1** if it steps by $\beta^{(0)}\Delta C$.
- (c) Repeat on three channels.

**Step 1: two-state pad coupling.**

- Measure pad electrode to body terminal, attached ($C_i^{\text{att}}$) and fully lifted by ≥ 30 mm ($C_i^{\text{air}}$).
- Cp–D mode, with open and short compensation done in the measuring geometry.
- At least 5 pads (4 corners and the centre), 3 attach–detach cycles each.
- Record D.
- $C_{\mathrm{body},i}=C_i^{\text{att}}-C_i^{\text{air}}$. The hydrogel–skin interface has nF-scale capacitance, thousands of times the pad's, so it does not load the reading.

**Step 2: the same event on the board.** Log $N_i^{\text{att}}$ and $N_i^{\text{air}}$ in the same session. Then $\beta_i=(N_i^{\text{att}}-N_i^{\text{air}})/C_{\mathrm{body},i}$. Compare with 59.85 and with step 0.

**Step 3: parasitic capacitance.** Under H1, $C_{\mathrm{par},i}=(N_i^{\text{air}}-a)/\beta_i$ with $a$ from step 0.

**Table 23.** Decision table.

| Result | Meaning | Action |
|---|---|---|
| Resting count returns to ≈ 27,852 after each power cycle | H2: auto-calibration | Stop quoting 26,205 as a floor. For absolute work, disable auto-calibration or log the IDAC code |
| Resting count steps by $\beta^{(0)}\Delta C$, and $\beta^{(0)}\approx59.85$ | H1 confirmed | Use steps 1–3 |
| $\beta_i$ differs from 59.85 by more than 10% | `COUNTS_PER_PF` is wrong for this board and patch | Regenerate every pF figure. Change the constant only together with the report, because tests pin it |
| H1 and $C_{\mathrm{body}}\ge50.1$ pF | the spec is reachable | 0/81 becomes a fixation finding after all |
| H1 and $C_{\mathrm{body}}<50.1$ pF | the spec is unreachable on this patch (Theorem 4) | Take the numbers to the author of KES 2025 §2.1. Do not edit `SPEC_DETACH_MAX` |
| $C_{\mathrm{body}}$ spread across pads > 1 pF | localisation needs a reference map (§4.5.3) | Store per-pad $C_i^{\text{ref}}$ at application |
| D > 0.5, or large 100 kHz–1 MHz dispersion | a lossy interface (sweat, gel), since tissue itself disperses by < 2% (Table 5) | Report it. C is frequency-dependent here |

**Uncertainty budget.** Record each of these:

- instrument accuracy, from the LCR datasheet at each frequency;
- open-compensation residual;
- re-attachment repeatability, measured over the 3 cycles;
- frequency dispersion;
- temperature, because the hydrocolloid's permittivity drifts with it.

**Deliverable.** Fill the empty rows of `Hardware_Deck_Spec.md`: pad area, substrate stack, CapSense technique and scan frequency, $C^{\text{att}}$ and $C^{\text{air}}$ per pad, and β per channel. Then regenerate the report.

---

## 5. Module 4: anatomical contours and step heights

### 5.1 Bending and adhesion length scales

**Flexural rigidity.** $D=Et^3/\big(12(1-\nu^2)\big)$. The material constants are ASSUMED.

| Layer | $E$ | $t$ | ν | $D$ (N·m) |
|---|---|---|---|---|
| Polyimide | 2.5 GPa | 25 µm | 0.34 | 3.68 × 10⁻⁶ |
| Copper, solid (worst case) | 117 GPa | 18 µm | 0.34 | 6.43 × 10⁻⁵ |
| Silicone backing | 1 MPa | 0.5 mm | 0.49 | 1.37 × 10⁻⁵ |

**Elasto-adhesive length.** $L_{ea}=\sqrt{D/(2\Gamma)}$. At this length the bending energy per unit area of a sheet curved to radius $R$, $D/(2R^2)$, equals the adhesion energy Γ. A sheet can stay bonded around a curvature radius $R\ge L_{ea}$. This is the adhesive analogue of the elastocapillary length (Py et al. 2007).

**Corner fillet.** Where the sheet bridges the concave 90° corner between tube and skin with an arc of radius $R$:

- the bending energy per unit length along the tube is $\frac{D}{2R^2}\cdot\frac{\pi R}{2}=\frac{\pi D}{4R}$;
- about $R$ of skin is left unbonded, costing $\Gamma R$.

Minimising the sum gives $R^*=\sqrt{\pi D/(4\Gamma)}$. This is a scaling estimate that assumes the tube side stays bonded.

**Table 24.** Adhesion length scales, in mm. Γ in J/m² is ASSUMED, covering a plausible skin-adhesive range.

| Layer | $L_{ea}$, Γ = 10 | Γ = 50 | Γ = 200 | $R^*$, Γ = 10 | Γ = 50 | Γ = 200 |
|---|---|---|---|---|---|---|
| Polyimide | 0.43 | 0.19 | 0.10 | 0.54 | 0.24 | 0.12 |
| Copper | 1.79 | 0.80 | 0.40 | 2.25 | 1.00 | 0.50 |
| Silicone | 0.83 | 0.37 | 0.19 | 1.04 | 0.46 | 0.23 |

**The tube radius is far above every $L_{ea}$.** $a=4.5$–5.75 mm against $L_{ea}\le1.8$ mm, so a bonded dressing *can* wrap the tube. Adhesion, not stiffness, decides conformity.

- **Bonded case.** What remains unbonded is a fillet of area $R^{*2}(1-\pi/4)=0.003$–1.08 mm² per corner.
- **Worst case.** With no adhesion near the tube (a non-adhesive tape edge, say), the sheet drops vertically from the tube's widest point. That leaves a wedge of $a^2(1-\pi/4)=5.91$ mm² per side at $a=5.25$ mm, or about 41 mm³ per side along one 7-mm pad.

### 5.2 Hetényi's profile: derivation, and why it does not apply here

**Derivation.** Model the dressing as a strip on a Winkler foundation: the adhesive and soft tissue act as springs of modulus $k=E_{\text{adh}}/t_{\text{adh}}$ per unit area.

$$
D\,w''''+k\,w=q,\qquad \lambda=(4D/k)^{1/4}.
\tag{5.1}
$$

For $q=0$ and $x>0$, the bounded solution is $w=e^{-x/\lambda}\big(A\cos\frac x\lambda+B\sin\frac x\lambda\big)$. Using

$$
\frac{d^2}{dx^2}\big[e^{-x/\lambda}\cos\tfrac x\lambda\big]=\frac{2}{\lambda^2}e^{-x/\lambda}\sin\tfrac x\lambda,\qquad
\frac{d^2}{dx^2}\big[e^{-x/\lambda}\sin\tfrac x\lambda\big]=-\frac{2}{\lambda^2}e^{-x/\lambda}\cos\tfrac x\lambda,
$$

impose a prescribed edge deflection $w(0)=h_0$ and zero edge moment $w''(0)=0$ (hinged at the tube edge). This gives $B=0$ and $A=h_0$:

$$
w(x)=h_0\,e^{-x/\lambda}\cos(x/\lambda).
\tag{5.2}
$$

The brief's profile is therefore exactly the hinged-edge solution. A clamped edge ($w'(0)=0$) would give $h_0e^{-x/\lambda}(\cos\frac x\lambda+\sin\frac x\lambda)$ instead.

**Table 25.** λ for $t_{\text{adh}}=0.3$ mm (`mech.hetenyi`).

| $D$ (N·m) | $E_{\text{adh}}=20$ kPa | $E_{\text{adh}}=200$ kPa |
|---|---|---|
| 10⁻⁶ | 0.50 mm | 0.28 mm |
| 10⁻⁵ | 0.88 mm | 0.50 mm |
| 10⁻⁴ | 1.57 mm | 0.88 mm |

> **Proposition 6 (the Winkler profile fails for millimetre steps).** Equation (5.1) assumes two things.
>
> 1. **Small slopes, $|w'|\ll1$.** Here $|w'(0)|=h_0/\lambda=(3$–$11\text{ mm})/(0.28$–$1.57\text{ mm})=1.9$–$40$.
> 2. **A linear foundation that holds in tension.** Wherever $w>0$ the adhesive is stretched. At the edge that means $h_0/t_{\text{adh}}=10$–$37$, i.e. 1,000–3,700% strain. (The negative lobe, $\pi/2<x/\lambda<3\pi/2$, would press the dressing *into* the skin.) Real skin adhesives debond at strains of order one.
>
> Both assumptions fail by one to two orders of magnitude. (5.2) describes the sub-millimetre boundary layer where a bonded dressing meets a *small* bump ($h_0\lesssim0.1\lambda$). It does not describe a dressing over a 3–11 mm step.

**A debonded tent is no better.** Let the dressing lift off over a span ℓ, modelled as a clamped–clamped beam bridging a height $h$, and minimise bending plus lost adhesion:

$$
U(\ell)=\frac{6Dh^2}{\ell^3}+\Gamma\ell
\ \Rightarrow\
\ell^*=\Big(\frac{18Dh^2}{\Gamma}\Big)^{1/4}.
$$

The bending term comes from $w=h(3s^2-2s^3)$ with $s=x/\ell$, for which $\int\frac D2w''^2=6Dh^2/\ell^3$. At Γ = 50 J/m², ℓ* = 1.34–8.12 mm but $h/\ell^*=0.71$–4.28. That is again outside small-slope theory.

**Conclusion.** At these heights the shape is set by the tube and by adhesion at the corners, not by beam bending. A bonded dressing wraps the tube ($a\gg L_{ea}$) and leaves fillets of radius $\sim R^*$. The worst case is the vertical-drop wedge of §5.1.

### 5.3 Pad coupling map for a tube under the dressing

Place a vertical tube along the centre column: axis at $x=45$ mm, $a=5.25$ mm. Pad centres come from `PHYSICAL_PAD_COORDS` scaled by (0.9, 1.2). The *raised fraction* is the share of the pad's 7-mm footprint lying within $a+0.5$ mm of the axis (tube plus fillet). A raised pad is modelled as lifted by at least $a$; a pad on the crown sits at $2a$ and couples even less.

**Table 26.** Body coupling on the stated stack (`mech.pads`). These are parallel-plate values (flush 3.975 pF, raised pads at a lift of $a$). Fringing raises the residual of raised pads, at most to about 0.36 pF (Table 6 at 3 mm), so the losses shown are upper bounds by at most 0.3 pF.

| Pad | $x, y$ (mm) | Raised fraction | $C_{\text{body}}$ (pF) | Loss (pF) |
|---|---|---|---|---|
| 12 | 45.0, 76.8 | 1.00 | 0.064 | 3.91 |
| 13 | 45.0, 60.0 | 1.00 | 0.064 | 3.91 |
| 14 | 45.0, 42.0 | 1.00 | 0.064 | 3.91 |
| 1 | 51.3, 108.0 | 0.42 | 2.33 | 1.65 |
| 3 | 52.2, 93.6 | 0.29 | 2.83 | 1.15 |
| 11 | 52.2, 26.4 | 0.29 | 2.83 | 1.15 |
| 15 | 36.9, 108.0 | 0.16 | 3.33 | 0.64 |
| 16 | 36.0, 93.6 | 0.04 | 3.84 | 0.14 |
| 24 | 36.0, 26.4 | 0.04 | 3.84 | 0.14 |

**Pad numbering.** In `PHYSICAL_PAD_COORDS`, pads 11, 12 and 13 are not a lateral triple across one tube. Pads 12 and 13 lie on the centre column (x = 50%); pad 11 lies at (58%, 22%). The guide's sketch labelled "Pad-11 Pad-12 Pad-13" is schematic. A vertical tube under the centre column covers pads 12, 13 and 14.

### 5.4 Proposition 7: "35 pF → 12–18 pF" is incompatible with the stated stack

> **Proposition 7.** Under (1.2) and Lemma 1, tenting can remove at most $C_{\mathrm{body},i}$ from a pad, because $g\ge0$. On the stated stack that is 3.98 pF (parallel plate) or 4.61 pF (with fringing, Table 6). A pad at 35 pF when flush can therefore fall no lower than 30.4 pF, not to 12–18 pF.
>
> *Converse.* Going from 35 pF to 12–18 pF means losing 17–23 pF. That needs $C_{\mathrm{body}}\ge17$–23 pF, that is $\sum t/\varepsilon_r\le\varepsilon_0A/C_{\mathrm{body}}=20.0$–14.8 µm. The stated stack is 85.7 µm (93.1 µm including the polyimide). The claim therefore needs:
>
> - an effective dielectric 4.3–6.3 times thinner than stated;
> - a parasitic $C_{\mathrm{par}}\approx12$–18 pF, the reading left after the body coupling is gone, which tenting cannot touch. ∎

The corpus points toward something like this. The median peel removes about 14.5 pF (−869 counts). If that is all of the body coupling, the implied $\sum t/\varepsilon_r$ is about 23.5 µm (§2.3.2). So the bench patch may be closer to the 15–20 µm the claim needs than to the brief's stack.

Either way, 35 pF and 12–18 pF are hypotheses about an unmeasured stack, and the two-state LCR measurement (§4.7) settles them. Under the stated stack, a pad tented to 1.5 mm keeps 0.53 pF of body coupling. From a 35-pF flush reading it would sit at about 30.9 pF.

### 5.5 ∂C/∂z and Theorem 5 (blind pads)

**The sensitivity derivative.** For a substrate $d_{\text{sub}}/\varepsilon_{\text{sub}}$ in series with a gap $z$ of permittivity $\varepsilon_{\text{med}}$:

$$
C(z)=\frac{\varepsilon_0A}{d_{\text{sub}}/\varepsilon_{\text{sub}}+z/\varepsilon_{\text{med}}}
\ \Rightarrow\
\frac{\partial C}{\partial z}=-\frac{\varepsilon_0A\,\varepsilon_{\text{med}}}{\big(d_{\text{sub}}\varepsilon_{\text{med}}/\varepsilon_{\text{sub}}+z\big)^2},
\tag{5.3}
$$

This is the formula in the documents, and it is correct for a lossless series stack.

For an air gap and $d_e=85.7$ µm:

- $\partial C/\partial z(0)=-46.4$ pF/mm;
- $\partial C/\partial z(1.5\text{ mm})=-0.136$ pF/mm.

The ratio is $\big(d_e/(d_e+z)\big)^2=0.0029$: a pad tented at 1.5 mm has 0.29% of the flush sensitivity. A thinner effective dielectric makes the ratio *smaller*; at $d_e=23.5$ µm it is 2.4 × 10⁻⁴.

**Table 27.** Lift signals on the stated stack (finite-volume $C_{\text{body}}$; `norm.lift_signal_brief_stack`).

| Event | ΔC_body | Counts |
|---|---|---|
| Flush pad lifted 0 → 0.5 mm | −3.62 pF | −217 |
| Flush pad lifted 0 → 3 mm | −4.25 pF | −254 |
| Flush pad, all body coupling lost | −4.61 pF | −276 |
| Tented pad lifted 1.5 → 3 mm | −0.16 pF | −9.8 |
| Everything a pad tented at 1.5 mm can lose | −0.53 pF | −31.5 |

Two consequences:

1. **Even flush pads cannot reach the gate on this stack.** Complete detachment of a flush pad (−276) does not reach −300.
2. **The documents' numbers do not follow from this stack.** They claim −800 to −1,500 counts for a 0.5-mm lift, which is 4–7× this stack, and −100 to −200 for a tented pad, which is 10–20×. The corpus's peels (median −869) again say the bench's coupling is about three times the stated stack's.

> **Theorem 5 (blind pads).** Let pad $i$ have remaining span $S_i=\beta\,C_{\mathrm{body},i}\,g_i(z_0)$ (the counts it can still lose) and per-frame Gaussian noise $\sigma_i$. A per-frame test of "a fraction ≥ $f^*$ of the remaining coupling lost" at false-alarm probability α and miss probability $\beta_m$ exists if and only if
>
> $$
> f^*S_i\ \ge\ (z_\alpha+z_{\beta_m})\,\sigma_i .
> \tag{5.4}
> $$
>
> *Proof.* $N_i\sim\mathcal N(\mu,\sigma_i^2)$, with $\mu=N^{\text{att}}$ under $H_0$ and $\mu=N^{\text{att}}-f^*S_i$ under $H_1$. By the Neyman–Pearson lemma, the most powerful level-α test rejects when $N_i\le N^{\text{att}}-z_\alpha\sigma_i$. Its power is $\Phi(f^*S_i/\sigma_i-z_\alpha)$, which is ≥ $1-\beta_m$ exactly when (5.4) holds. No other test is more powerful. ∎

**Table 28.** Minimum span for $\sigma=8.6$ counts and $\beta_m=0.05$ (`norm.np_span_budget`).

| | α = 10⁻³ | α = 10⁻⁴ |
|---|---|---|
| $f^*=1$ | 40.7 counts (0.68 pF) | 46.1 counts (0.77 pF) |
| $f^*=0.5$ | 81.4 counts (1.36 pF) | 92.3 counts (1.54 pF) |

**Corollary 5.1.** On the stated stack:

- a pad tented at 1.5 mm has $S=31.5<40.7$ counts, so no test, and therefore no gate, detects even its *complete* detachment at α = 10⁻³ with 95% power;
- a pad on the tube has a span between about 3.8 counts (parallel plate at a lift of $a$) and 21.8 counts (bounded by the 3-mm finite-volume coupling, 0.36 pF). It is blind by a factor of 2–10.

So the false negatives of claim C13 are real, but they are not a thresholding problem: the information is not in the signal. The remedies are:

- **mechanical:** remove the tent, or keep pads off the tube;
- **lower noise:** averaging $k$ frames divides σ by $\sqrt k$ at a cost of $k$ frames of latency;
- **honest reporting:** declare the pad blind and report the reduced coverage.

### 5.6 Adaptive gates and fractional deltas: units, invariance, optimality

**Table 29.** What `analyze_surface_topography` returns. Counts-mode baselines are $N_0=26{,}204.5+59.85\,C_0$, the repository's own transfer (`norm.gate_units`).

| $C_0$ | Counts-mode gate | In pF | pF-mode gate | In counts | False lift per pad-frame (σ = 8.6) | Any of 25 pads |
|---|---|---|---|---|---|---|
| 15 pF | −298.1 | −4.98 | −0.16 pF | −9.6 | 13.3% | 97.2% |
| 30 pF | −308.0 | −5.15 | −0.33 pF | −19.8 | 1.08% | 23.8% |
| 35 pF | −311.3 | −5.20 | −0.38 pF | −22.7 | 0.41% | 9.7% |

> **Proposition 8 (the adaptive gate is not unit-consistent).** α = 0.011 is 300/28,000 (l.3068): a ratio to the raw count, which is 94% offset.
>
> - **In counts,** the gate varies by 4% between a 15-pF and a 35-pF pad. It never reaches its −150 floor, which would need $N_0<13{,}636$, below the 26,205 floor.
> - **In pF,** it is 14–31× tighter than the same pad's count gate (5.15 against 0.33 pF at 30 pF), and it fires on noise.
>
> So one formula means two different things in two unit systems, and neither is a fraction of the pad's detachable coupling. `LivePipeline` evaluates it in counts only (l.2837), and its output reaches only the propagation descriptor (l.2919), never the alarm.

> **Proposition 9 (δ = ΔC/C₀ is not invariant).** From (1.2), losing a fraction $f$ of the body coupling gives
>
> $$
> \delta^{(N)}=\frac{\Delta N}{N_0}=\frac{-\beta C_{\mathrm{body}}f}{a+\beta(C_{\mathrm{par}}+C_{\mathrm{body}})},\qquad
> \delta^{(C)}=\frac{\Delta C}{C_0}=\frac{-C_{\mathrm{body}}f}{C_{\mathrm{par}}+C_{\mathrm{body}}} .
> $$
>
> Both depend on $C_{\mathrm{par}}$, and $\delta^{(N)}$ also depends on $a$ and β.

**Table 30.** The same physical event (half the body coupling lost) under three readout transfers (`norm.affine_invariance`).

| Pad, $C_{\mathrm{par}}+C_{\mathrm{body}}$ | Transfer | $\delta^{(N)}$ | $\delta^{(C)}$ | $\hat f$ |
|---|---|---|---|---|
| 26 + 4 pF | affine (repository) | −0.43% | −6.7% | **0.500** |
| 26 + 4 pF | 85% target | −0.43% | −6.7% | **0.500** |
| 26 + 4 pF | 85% target, gain ×1.3 | −0.56% | −6.7% | **0.500** |
| 10 + 25 pF | affine | −2.64% | −35.7% | **0.500** |
| 10 + 25 pF | 85% target | −2.69% | −35.7% | **0.500** |
| 10 + 25 pF | 85% target, gain ×1.3 | −3.49% | −35.7% | **0.500** |
| 26 + 0.53 pF (tented) | affine | −0.057% | −1.0% | **0.500** |
| 26 + 0.53 pF | 85% target | −0.057% | −1.0% | **0.500** |
| 26 + 0.53 pF | 85% target, gain ×1.3 | −0.074% | −1.0% | **0.500** |

For one physical event, $\delta^{(N)}$ spans a factor of 61 and $\delta^{(C)}$ a factor of 36. The guide's worked example (−7/35 = −3/15 = −20%) holds only if $C_{\mathrm{par}}=0$ on both pads, that is, only if the pad's entire capacitance is body coupling. The stated stack rules that out.

> **Theorem 6 (the detachment fraction is the maximal invariant).** For each pad define
>
> $$
> \hat f_i(t)=\frac{N_i^{\text{att}}-N_i(t)}{N_i^{\text{att}}-N_i^{\text{air}}}.
> \tag{5.5}
> $$
>
> (a) Under (1.2), $\hat f_i=1-g_i(z(t))$ exactly, for every $a_i$, $\beta_i>0$, $C_{\mathrm{par},i}$ and $C_{\mathrm{body},i}>0$.
>
> (b) $\hat f$ is invariant under every affine change of readout $N\mapsto c+kN$ ($k\ne0$). Every statistic of $(N^{\text{att}},N^{\text{air}},N)$ with that invariance is a function of $\hat f$.
>
> *Proof.* (a) Substitute (1.2): the numerator is $\beta C_{\mathrm{body}}(1-g)$ and the denominator is $\beta C_{\mathrm{body}}$.
>
> (b) *Invariance:* $c$ cancels in the differences and $k$ in the ratio.
> *Maximality:* suppose two triples with non-degenerate spans have equal $\hat f$. Take $k=(M^{\text{att}}-M^{\text{air}})/(N^{\text{att}}-N^{\text{air}})$ and $c=M^{\text{air}}-kN^{\text{air}}$. This map sends $N^{\text{air}}\mapsto M^{\text{air}}$ and $N^{\text{att}}\mapsto M^{\text{att}}$, and because $\hat f$ is equal it also sends $N\mapsto M$. The two triples therefore share an orbit, and an invariant statistic is constant on orbits. ∎

Up to relabelling, $\hat f$ is therefore the only normalisation that does not depend on:

- the offset;
- the gain;
- the parasitic capacitance;
- the size of the body coupling.

Those four quantities are exactly what differ between pads, patches, boards and firmware. The cost is one reading of the patch in air per pad, taken before application (or the two LCR states of §4.7).

> **Theorem 7 (Neyman–Pearson gate on the fraction).** Under Gaussian noise $\sigma_i$, the most powerful level-α per-pad test of "attached" against "fraction ≥ $f^*$ detached" rejects when $\hat f_i\ge z_\alpha\sigma_i/S_i$, where $S_i=N_i^{\text{att}}-N_i^{\text{air}}$. It reaches power $1-\beta_m$ exactly when $S_i\ge(z_\alpha+z_{\beta_m})\sigma_i/f^*$ (Theorem 5). In counts:
>
> $$
> \text{Gate}_i=-\max\big(z_\alpha\sigma_i,\ f_{\text{gate}}\,S_i\big),\qquad
> \text{pad } i \text{ is sighted} \iff S_i\ge S_{\min}.
> \tag{5.6}
> $$
>
> *Proof.* $N\sim\mathcal N(N^{\text{att}}-fS,\sigma^2)$, so the likelihood ratio is monotone in $-N$, equivalently in $\hat f$. Neyman–Pearson gives the threshold. The gate adds the physical criterion to that bound. ∎

**Reading (5.6).**

- The first term holds the false-lift rate at α.
- The second term ties the gate to a physical fraction of the pad's own span.
- Pads below $S_{\min}$ are reported as blind instead of failing silently.

At the bench's apparent scale ($S\approx870$ counts, the median peel), the fixed −300 gate is $f_{\text{gate}}\approx0.34$, consistent with a gate that works. On the stated stack ($S\approx276$), no flush pad could reach −300 at all. The listing is in §7.5.

### 5.7 The four-tier architecture, corrected

**Table 31.** The four tiers against the evidence.

| Tier | As written (`CONTOUR_…_GUIDE.md` §3–6) | What the physics and data say | Corrected design | Acceptance test |
|---|---|---|---|---|
| **1. Algorithm** | Fractional deltas δ = ΔC/C₀; gates min(−150, −αC₀); topography profiling | δ is not invariant (Prop. 9). The gates are inert or unit-inconsistent (Prop. 8) and sit off the alarm path. Tented pads are blind (Thm 5) | Detachment fraction $\hat f$ from per-pad $N^{\text{att}}$ and $N^{\text{air}}$ (Thm 6). NP gate with $S_{\min}$ and blind-pad reporting (Thm 7). Topography from the absolute $C_{\text{body}}$ map. A coverage metric: the share of the dressing perimeter watched by sighted pads | Same $\hat f$ across pads for the same lift. False-lift rate ≤ α on resting recordings. Every tube-top pad flagged blind |
| **2. Mechanics** | Hydrocolloid 0.8–1.2 mm flows into gaps in 1–2 min; ≤ 25-µm serpentine FPC; keyhole slits | Thin polyimide wraps the tube anyway ($a\gg L_{ea}$), leaving fillets of $R^*\approx0.1$–0.5 mm. A pad on the tube's crown is lifted 9–11.5 mm, and no adhesive fills that. No rheology data support "1–2 min" | Keep sensing pads off the tube: a keyhole cut-out, plus a layout with no pad centre within $a+r_p$ of the tube path. Strain relief isolates the anchor. Choose hydrocolloid thickness for span (thinner means larger $C_{\text{body}}$), not for gap filling | Phantom with 3/5/8-mm steps: a measured $C_{\text{body}}$ map, with no pad below $S_{\min}$ except those declared blind |
| **3. Absolute CDC and CQI** | True fF baselines with no boot calibration; a Contact Quality Index | The CDC path today discards the absolute frame (§4.4) | $\mathrm{CQI}_i=(C_i-C_i^{\text{air}})/(C_i^{\text{ref}}-C_i^{\text{air}})\in[0,1]$, the absolute counterpart of $\hat f$. Seed from the absolute map. Localise the tube by matched filter on $C^{\text{ref}}-C$ | Boot with a pressed pad, a loose pad, and in air: each flagged. Tube localised with ≤ 1% false positives |
| **4. Bench** | 3-D facial phantom, R = 30 mm; step blocks 3/5/8 mm; Ecoflex with carbon (εr ≈ 50); −40 to −60 kPa suction | By Lemma 1 the phantom must be a **conductor** at the sensing frequency. "εr ≈ 50" is the wrong specification | A conductive phantom (σ ≳ 0.1 S/m, tissue-like) returned to board ground through about 100 pF. A per-pad two-state LCR map. Force-controlled tube pulls at 5, 10 and 20 N | Transfer $f$ identified (step 0). $C_{\mathrm{body},i}$ for every pad. Horizontal pull tested with and without a shear cell |

---

## 6. Failure-mode matrix

Severity is clinical:

- **H**: a missed or silently degraded detachment;
- **M**: false alarms or a misleading display;
- **L**: documentation only.

"Current control" is what `main.py` does today.

**Table 32.** Failure modes.

| ID | Failure mode | Mechanism (§) | Sev. | Current control | Residual risk | Proposed control | Verification |
|---|---|---|---|---|---|---|---|
| F1 | Slow peel absorbed by the baseline | Kalman tracks ramps below 4.17 counts/frame (0.124 pF/s) (§4.3) | H | Innovation gate of 120 counts | Any detachment slower than 7.4 counts/s is invisible | Monitor cumulative baseline drift since seed as a fraction of the span $S_i$ | Ramp-injection test at 0.05–0.5 pF/s |
| F2 | Contamination on 1–2 pads at power-on | Proposition 1; seeded high (§4.1–4.3) | M/H | Shape test at 575 (advisory); quiescent recovery | Loads below 575 counts are not flagged. A genuine single-pad fault is erased within about 9 s | Absolute reference map and air map at application; re-seed prompt | Boot with a finger on 1, 2 or 5 pads |
| F3 | Contamination on ≥ 3 pads (a palm) | Recovery is disabled when ≥ `PEEL_MIN_PADS` pads are below −300 (§4.3) | M | None | Phantom peel front until a manual re-seed | Treat a seed-time shape failure as blocking; absolute reference | Boot with a palm on the patch |
| F4 | Booted in air, or loose, then applied | Standing positive offset; a later detachment only returns to zero (§4.1) | **H** | Band test, effective only if $C_{\text{body}}>8.8$ pF | Silent on the stated stack | Mandatory two-point sequence (air, then attached); refuse to arm if $S_i<S_{\min}$ | Boot-in-air-then-apply test |
| F5 | CDC mode re-zeroes on its first frame | Conversion relative to the first frame (§4.4) | H | None | The CDC gives no power-on benefit; every seed passes | Seed from the absolute map and compare against the reference | `test_cdc_seed_is_blind` (§7.6) inverted once fixed |
| F6 | Pads tented or on the tube ($S_i<S_{\min}$) | Theorem 5 (§5.5) | **H** | Adaptive gates (inert, and off the alarm path) | Silent loss of coverage along the tube | Blind-pad detection and coverage reporting; keep pads off the tube path | Phantom $C_{\text{body}}$ map with 3/5/8-mm steps |
| F7 | Horizontal pull produces no lift | Theorem 3 (§3.3) | **H** | Classifier on the contact proxy plus the temporal vote | Depends on press magnitude (`ALGORITHM_JUSTIFICATION.md` §7.1) | Shear cell or anchor force sensor; round-2 validation | Force-controlled pulls at 5, 10 and 20 N |
| F8 | Event with < 3.36 s of evidence | 7-of-6 needs 6 frames at 0.56 s (§2.7.8, §3.5) | H | None (clinical choice) | Such events cannot be annunciated | Raise the frame rate: at 10 Hz, 6 votes take 0.6 s | Short synthetic events on the served path |
| F9 | Gaussian noise σ ≳ 20 counts | Gate leak, then vote dilution (§3.4b) | H | Noise telemetry only (`jitter_noise_counts`) | Sensitivity 85–92.5% at σ 30–60 | Front-end noise budget ≲ 12 counts; alarm on telemetry above budget | Noise injection |
| F10 | Single-frame spikes below 50,000 | One non-supporting vote breaks a run (§3.4e) | M/H | Surge filter at 50,000 only | 2/40 missed at a 1% spike rate | Impulse-only median (Hampel-type, per pad) | Spike injection |
| F11 | Frame drops | Less evidence (§3.4d) | M/H | Level held through the dropout; re-seed after 5 lost frames | 2/40 missed at 10% drops | Vote over elapsed time rather than frame count | Drop injection |
| F12 | Relative-zero touch artefacts | 15.8% of touch frames are neg-only (§2.5) | M | Temporal vote and classifier | 4.9% false alarms per recording (2/41) | Absolute reference; SOP: seed hands-off | False-alarm rate on round-2 normal recordings |
| F13 | False tube detection | Resting topography exceeds the MAD threshold (§4.5.2) | M | MAD threshold clamped to [0.35, 1.5] pF | 13–100% false positives, depending on spread | Matched filter with permutation test on a reference map | Table 21 simulation, then phantom |
| F14 | Wrong transfer model (H1 vs H2) | §4.6 | H | None | Every pF figure, the 26,205 floor and F10's meaning could be wrong | Step 0 of §4.7 | Reference-capacitor test |
| F15 | Live channel order unverified | `PAD_ORDER` applied on live paths (`main.py` l.280–283) | H (spatial) | None for live data | Heatmap, propagation and tube axis may be scrambled | 1-by-1 sweep through `/ws/live_sensor`, then `--verify-pads` | Live sweep |
| F16 | Protective features that do not act | Adaptive gates and F10 never change an alarm (§5.6, §3.4a) | L | — | Documentation over-claims protection | Implement Theorem 7 on the alarm path, or withdraw the claim | Code review; a test that the alarm depends on the gate |

---

## 7. Algorithmic code proofs

**Status.** Every listing below was run against the shipped code on 2026-09-25 and passes (a scratch pytest run: 8 checks, about 12 s). None has been added to `tests/`, because they are proposals. The property-based ones (7.1, 7.2, 7.5, 7.6) would fit naturally beside `tests/test_domain_generalization.py`.

### 7.1 Theorem 2(b): HistGradientBoosting ignores monotone warping

```python
ds = main.load_dataset(calibration="kalman", verbose=False)
X, y = np.asarray(ds.X, float), np.asarray(ds.y)
psi = np.sign(X) * np.log1p(np.abs(X))          # strictly increasing in every feature
a = main._new_rf(42).fit(X, y).predict(X)
b = main._new_rf(42).fit(psi, y).predict(psi)
assert np.array_equal(a, b)                       # identical on all 3,349 frames
```

### 7.2 Proposition 4(a): the causal median shifts a step by exactly one frame

```python
step = np.r_[np.zeros(10), np.full(8, 900.0), np.zeros(10)]
y = main.adaptive_jitter_filter(np.tile(step[:, None], (1, 25)), activate=-1.0)[:, 0]
assert np.argmax(y > 450) - np.argmax(step > 450) == 1                      # onset +1 frame
assert np.nonzero(y > 450)[0][-1] - np.nonzero(step > 450)[0][-1] == 1      # end +1 frame
end = np.r_[np.zeros(10), np.full(6, 900.0)]      # event running to the end of the clip
ye = main.adaptive_jitter_filter(np.tile(end[:, None], (1, 25)), activate=-1.0)[:, 0]
assert (ye > 450).sum() == (end > 450).sum() - 1  # one supporting frame lost
```

### 7.3 Proposition 5: exact k-of-n arithmetic

```python
def p_alarm(m, p, window=7, votes=6):
    total = 0.0
    for bits in itertools.product((0, 1), repeat=m):
        if any(sum(bits[max(0, t - window + 1):t + 1]) >= votes for t in range(m)):
            total += p ** sum(bits) * (1 - p) ** (m - sum(bits))
    return total
assert round(p_alarm(7, 0.9), 3) == 0.850 and round(p_alarm(6, 0.9), 3) == 0.531
assert p_alarm(5, 0.99) == 0.0                    # five frames can never give six votes
```

### 7.4 The matched-filter tube localiser (§4.5.3)

These are the core of `scripts/defense_dossier_checks.py`: `_templates`, `_mf`.

```python
def templates(xy_mm, half=6.0, r_pad=3.5):
    rows, params = [], []
    for th in np.arange(0, 180, 5.0):
        proj = xy_mm @ np.array([np.cos(np.radians(th)), np.sin(np.radians(th))])
        for rho in np.arange(proj.min() - 3, proj.max() + 3, 2.0):
            t = np.clip((half - np.abs(proj - rho) + r_pad) / (2 * r_pad), 0, 1)   # (4.3)
            if t.sum() >= 2.5 and t.std() > 0:
                rows.append((t - t.mean()) / (t.std() * np.sqrt(len(t))))
                params.append((th, rho))
    return np.array(rows), params

def localise(c_pf, T, params, n_perm=300, rng=np.random.default_rng(0)):
    v = np.median(c_pf) - c_pf                        # shadow depth; use C_ref - C when available
    z = (v - v.mean()) / (v.std() * np.sqrt(len(v)))
    s = T @ z                                         # (4.4): Radon-sampled correlation
    b = int(np.argmax(s))
    null = np.max(T @ np.array([rng.permutation(z) for _ in range(n_perm)]).T, axis=0)
    p = (1 + np.sum(null >= s[b])) / (1 + n_perm)
    return params[b], p                               # declare a tube only if p < 0.01
```

A vertical tube 3.7 pF deep at $x=45$ mm is recovered at θ = 0° with $p<0.01$ (checked).

### 7.5 Theorems 6–7: detachment fraction, NP threshold, blind pads

```python
def detachment_fraction(n_now, n_att, n_air, sigma, z_alpha=3.09, z_beta=1.645):
    """f_hat = (N_att - N) / (N_att - N_air) per pad; threshold on f_hat; blind pads flagged."""
    n_now, n_att, n_air, sigma = (np.asarray(v, dtype=float) for v in (n_now, n_att, n_air, sigma))
    span = n_att - n_air
    sighted = span >= (z_alpha + z_beta) * sigma            # Theorem 5 with f* = 1
    safe = np.where(sighted, span, 1.0)
    f_hat = np.where(sighted, (n_att - n_now) / safe, np.nan)
    tau = np.where(sighted, z_alpha * sigma / safe, np.nan)  # Theorem 7 threshold on f_hat
    return f_hat, tau, sighted

# Property (Theorem 6): invariant under any readout change N -> c + kN, noise scaling with k.
f1, t1, s1 = detachment_fraction(n_now, n_att, n_air, 8.6)
f2, t2, s2 = detachment_fraction(c + k * n_now, c + k * n_att, c + k * n_air, k * 8.6)
assert np.array_equal(s1, s2) and np.allclose(f1, f2, equal_nan=True) and np.allclose(t1, t2, equal_nan=True)
```

The check uses 25 random pads, three of them with spans of 4, 20 and 31.5 counts, all correctly flagged blind.

### 7.6 The CDC seed is blind, and the gates are uniform (§4.4, Proposition 8)

```python
lp = main.LivePipeline(model=None, cdc_mode=True)
out = lp.process(np.full(25, 5.0))                        # booted in air: 5 pF on every pad
assert out["seed_plausibility"]["status"] == "attached_band"
assert set(np.round(lp.adaptive_lift_gates, 1)) == {-308.0}

k, off = main.COUNTS_PER_PF, main.BASELINE_COUNTS - main.NOMINAL_BASELINE_PF * main.COUNTS_PER_PF
for c in (15.0, 30.0, 35.0):
    gc = main.analyze_surface_topography(np.full(25, off + k * c), is_cdc_pf=False)["adaptive_lift_gates"][0]
    gp = main.analyze_surface_topography(np.full(25, c), is_cdc_pf=True)["adaptive_lift_gates"][0]
    assert -312 < gc < -298 and abs(gc / k) > 13 * abs(gp)   # inert in counts, 14-31x tighter in pF
```

### 7.7 Theorem 4 under the repository's constants

```python
r = main.spec_detach_reachability(main.SPEC_DETACH_MAX)
assert r["floor_counts_at_zero_capacitance"] == 26204.5 and r["reachable"] is False
```

`tests/test_spec_reachability.py` already pins this. The dossier's contribution is the sharper condition on $C_{\mathrm{body}}$ (Theorem 4b) and the dependence on the transfer (Table 22).

---

## 8. Assumption register, reproduction and sources

### 8.1 Assumption register

Each assumption below changes an absolute number in this dossier. None changes a theorem.

| Assumption | Used in | Effect if wrong | Settled by |
|---|---|---|---|
| Pad area 38.5 mm² | §2.3, §5 | Every absolute pF scales with $A$ | Measure the pad; fill `Hardware_Deck_Spec.md` |
| Hydrocolloid 0.3 mm, εr 3.5; PI 25 µm | §2.3, §5 | $C_{\text{body}}$, the lift signals and the blind-pad threshold move | LCR two-state map (§4.7, step 1) |
| β = 59.85 counts/pF is universal | throughout | pF ↔ counts conversions | §4.7, step 2 |
| $C_0$ = 30 pF, affine transfer (H1) | Theorem 4(a), Table 29 | The floor and the gate-unit numbers | §4.7, step 0 |
| Sensing frequency 250 kHz | Lemma 1 | None: Lemma 1 holds from 32 kHz to 5 MHz (Table 5) | Firmware scan settings |
| σ = 8.4–8.6 counts, Gaussian, independent across pads | §3.4, Theorem 5 | $S_{\min}$ scales with σ | Resting recordings on the round-2 rig |
| Γ = 10–200 J/m², material moduli | §5.1–5.2 | $L_{ea}$ and $R^*$ scale as $\Gamma^{-1/2}$ | Peel test of the actual adhesive |
| Shear cell: G = 100 kPa, 20 × 20 mm anchor | §3.3.4 | The signal scales as $1/(GA)$ | Bench |

### 8.2 Reproduction

```
python scripts/defense_dossier_checks.py > dossier.json     # every computed number, about 20 s
python scripts/translation_plan_checks.py --json > plan.json   # CDC seed, adaptive gates, Kalman ramp, pad fault, H-pull depth
python scripts/sync_metrics_blocks.py --check               # the generated headline blocks are current
```

JSON keys cited in the text: `field_axisym`, `field_plane_edge`, `field_shear_cell`, `tissue`, `data` (`summary`, `polarity`, `polarity_by_folder`, `maha34`, `bayes_err_equal_cov_gauss`, `knn_kl4`, `nn_overlap`, `context`), `learning`, `annunciator`, `noise`, `seed`, `tube`, `spec`, `mech`, `norm`.

### 8.3 Sources

1. Gabriel S, Lau RW, Gabriel C. The dielectric properties of biological tissues: III. Parametric models for the dielectric spectrum of tissues. *Phys Med Biol* 1996;41:2271–2293.
2. Sneddon IN. *Mixed Boundary Value Problems in Potential Theory.* North-Holland; 1966.
3. Hetényi M. *Beams on Elastic Foundation.* University of Michigan Press; 1946.
4. Py C, Reverdy P, Doppler L, Bico J, Roman B, Baroud CN. Capillary origami: spontaneous wrapping of a droplet with an elastic sheet. *Phys Rev Lett* 2007;98:156103.
5. Neyman J, Pearson ES. On the problem of the most efficient tests of statistical hypotheses. *Phil Trans R Soc A* 1933;231:289–337.
6. Vapnik VN. *Statistical Learning Theory.* Wiley; 1998.
7. Schapire RE, Freund Y, Bartlett P, Lee WS. Boosting the margin: a new explanation for the effectiveness of voting methods. *Ann Stat* 1998;26:1651–1686.
8. Bartlett PL, Mendelson S. Rademacher and Gaussian complexities: risk bounds and structural results. *J Mach Learn Res* 2002;3:463–482.
9. Bartlett PL, Harvey N, Liaw C, Mehrabian A. Nearly-tight VC-dimension and pseudodimension bounds for piecewise linear neural networks. *J Mach Learn Res* 2019;20(63):1–17.
10. Karpinski M, Macintyre A. Polynomial bounds for VC dimension of sigmoidal and general Pfaffian neural networks. *J Comput Syst Sci* 1997;54:169–176.
11. Wang Q, Kulkarni SR, Verdú S. Divergence estimation for multidimensional densities via k-nearest-neighbor distances. *IEEE Trans Inf Theory* 2009;55:2392–2405.
12. Ledoit O, Wolf M. A well-conditioned estimator for large-dimensional covariance matrices. *J Multivar Anal* 2004;88:365–411.
13. David HA, Nagaraja HN. *Order Statistics,* 3rd ed. Wiley; 2003. Source for the variance of the median of three normals, confirmed by simulation in §3.5.
14. Infineon Developer Community. "CapSense SmartSense Auto-Calibration" (forum thread). https://community.infineon.com/t5/PSoC-4/CapSense-SmartSense-Auto-Calibration/td-p/143656. A community source, used only to state hypothesis H2.

**Repository sources:**

- `main.py` (line numbers as cited, as of 2026-09-25)
- `Data/five_scenarios_evaluation.json` (mode `oof`, 2026-09-25 00:33)
- `Data/robustness_evaluation.json`, `Data/robustness_evaluation_kalman_norm.json`, `Data/rob_kn_jitter.json`
- `Data/metrics.json` (through the generated blocks)
- `docs/ALGORITHM_JUSTIFICATION.md`, `docs/CONTOUR_AND_STEP_HEIGHT_COMPENSATION_GUIDE.md`, `docs/SMART_DRESSING_PROGRESS_REPORT_BIOMEDICAL_AI.md`, `docs/DATA_COLLECTION_SOP_v2.md`, `docs/ACTION_PLAN.md`, `docs/Hardware_Deck_Spec.md`
