# 📋 Project Handover & Architecture Guide
**Project2: Smart Extubation Early Warning System**

Version: **v6.2 (Production Ready)**  
Repository: `https://github.com/udhdidid96-cpu/touch-sensor-ai`

---

## 1. Executive Summary

This repository contains the software and clinical algorithm pipeline for the **25-Channel Capacitive Smart Dressing System**, engineered to provide automated early warning before an intubated intensive care unit (ICU) patient pulls their endotracheal tube (ETT) out.

### Key Clinical Capabilities:
1. **Transduction Physics & Polarity Separation**:
   - Dielectric permittivity separation: Skin/tissue ($\varepsilon_{\text{skin}} \approx 50-80$), ETT tube ($\varepsilon_{\text{ETT}} \approx 2.8$), and atmospheric air gap ($\varepsilon_{\text{air}} \approx 1.0$).
   - **Peel / Extubation**: Replaces tissue contact with air ($\varepsilon_r \rightarrow 1.0$) $\rightarrow$ Deep negative delta ($\Delta C \le -300\text{ counts}$).
   - **Touch / Mass Coupling**: Body contact $\rightarrow$ High positive delta ($\Delta C \gg 0$).
   - **Friction / Rubbing**: Safe envelope ($\pm 60\text{ counts}$).
2. **Deterministic Tree Ensemble Pipeline**:
   - **HistGradientBoosting** (`max_iter=150, max_depth=8, class_weight="balanced"`).
   - **34 Load-Bearing Features**: 25 spatial pad deltas (preserves 2D propagation vector $\vec{v}_{\text{peel}}$) + 9 macro statistics (energy ratio, lift counts, extrema).
   - **Clinical Annunciator**: 7-of-6 majority vote with 9-frame hold window to suppress contact transients while catching detachment.
3. **Clinical Benchmark Performance (81 Bench Recordings, LOFO Out-of-Fold)**:
   - **Episode Sensitivity**: 100.0% (30/30 pull & peel episodes detected)
   - **False Alarm Rate**: 4.9% (7.8 alarms/hour)
   - **Median Warning Lead Time**: 5.60 seconds before full tube dislodgement
   - **Leave-One-File-Out (LOFO) File Accuracy**: 97.53%
4. **Operator Console & Web Telemetry**:
   - Single server-side classifier (`classify_deltas()`).
   - 3-Tier Visual & Audio Alarm Escalation Widget (Tier 3 Red 2.0 Hz buzzer, Tier 2 Yellow 0.6 Hz beep, Tier 1 Cyan steady chime).
   - Real-time 2D spatial heatmap (5x5 matrix) and cryptographic audit log.

---

## 2. Directory Structure & File Inventory

The project structure is organized cleanly for deployment and handover:

```
D:\Projects\Project2\
├── main.py                     # Unified FastAPI server: model, WebSocket telemetry, REST API & CLI (~257 KB)
├── run.py                      # Single official entrypoint / command dispatcher
├── share_public.py             # Authenticated public HTTPS tunnel (via tools/cloudflared.exe)
├── stream_to_cloud.py          # USB serial bridge forwarding frames to cloud instances
├── benchmark_ml_architectures.py # Offline ML/DL architecture comparison suite
│
├── Data/                       # 81 bench recordings & ground-truth metrics:
│   ├── Brief Touch/            # Transient contact recordings
│   ├── Friction/               # Dressing rubbing recordings
│   ├── Horizontal Pull NO G/   # Horizontal pull test recordings
│   ├── N_base/                 # Resting baseline recordings
│   ├── Normal Mix/             # Complex combined movement files
│   ├── Peel/                   # Deliberate adhesive peeling recordings
│   ├── PowerP/                 # High-velocity dislodgement recordings
│   ├── Press/                  # Direct sustained compression recordings
│   ├── Vertical Pull NO G/     # Vertical pull extubation recordings
│   ├── data new vaccum/        # Vacuum station benchmark data
│   ├── metrics.json            # Measured ground truth figures (checked by --verify-metrics)
│   ├── extubation_events_audit.json # Cryptographic audit trail
│   └── trained_model.joblib    # Serialized model checkpoint
│
├── web/                        # Web dashboard operator console:
│   ├── index.html              # Clinical dashboard layout (3-tier alarm beacon, 5x5 heatmap, telemetry)
│   ├── style.css               # Styling and keyframe blink animations (2.0 Hz, 0.6 Hz)
│   ├── app.js                  # Frontend client (renders server decisions; NEVER classifies)
│   ├── web_serial.js           # Browser Web Serial API bridge
│   └── chart.min.js            # Vendored Chart.js library
│
├── tests/                      # Automated guard suite (264 unit, contract & regression tests):
│   ├── conftest.py             # Test fixtures & sandboxed Data/ root
│   ├── test_all_endpoints.py   # REST, WebSocket, upload, and presentation endpoints
│   ├── test_invariants.py      # Hard guard tests for the 9 core safety invariants
│   ├── test_regressions.py     # 51 regression guards driven by Normal Mix corpus
│   ├── test_line_notify.py     # LINE alert webhook and escalation tests
│   ├── test_console_indicators.py # 3-Tier alarm indicators and priority contracts
│   └── ...                     # Additional fuzzing, streaming, framing, and reachability tests
│
├── scripts/                    # Research, figures, and evaluation tools:
│   ├── evaluate_5_scenarios.py # 5-scenario evaluation runner
│   ├── evaluate_robustness.py  # Noise/gain perturbation evaluation
│   ├── evaluate_vacuum_station.py # Vacuum demo station scoring
│   ├── benchmark_served_path.py # Live pipeline validation runner
│   ├── sync_metrics_blocks.py  # Synchronizes metric blocks in markdown docs
│   └── make_defense_figures.py # Generates defense figures and confusion matrices
│
├── docs/                       # Specifications, clinical protocols, and slide deck:
│   ├── presentation_deck.html  # Interactive slide deck served at /slides and /deck
│   ├── SUPERVISOR_DEFENSE_EXECUTIVE_DECK.md # Executive presentation script
│   ├── MATHEMATICAL_DEFENSE_DOSSIER.md # Transduction physics mathematical proofs
│   ├── ACTION_PLAN.md          # Project roadmap and priority checklist
│   ├── ALGORITHM_JUSTIFICATION.md # Algorithmic design decisions & model justification
│   ├── DATA_COLLECTION_SOP_v2.md # Bench recording standard operating procedure
│   ├── Hardware_Deck_Spec.md   # Hardware sensor specification
│   ├── ML_ENHANCEMENT_PLAN.md  # Machine learning roadmap and benchmarks
│   ├── DEPLOY_GOOGLE.md        # Google Cloud Run deployment guide
│   ├── figures/                # Publication-ready figures & confusion matrices
│   │   └── diagrams/           # Visual diagrams, PPTX slide masters, and SVG assets
│   └── ...                     # Protocols and documentation
│
├── tools/                      # External support binaries:
│   └── cloudflared.exe         # Cloudflare Tunnel binary for authenticated remote demos
│
├── Dockerfile                  # Production container definition (secure loopback default)
├── requirements.txt            # Pinned dependency stack
└── pytest.ini                  # Pytest configuration
```

---

## 3. How to Run & Operate

The only launcher is `run.py`.

### 1. Start Local Dashboard
```bash
python run.py
```
Open browser at `http://127.0.0.1:8081`.

### 2. Run Test Suite (Must Stay 100% Green)
```bash
python run.py test
```
All 264 automated tests must pass.

### 3. Verify Metrics Reproducibility
```bash
python run.py verify
```
Re-measures out-of-fold figures and asserts difference against `Data/metrics.json` is $\le 2\%$.

### 4. Audit Data Corpus
```bash
python run.py audit Data
```
Verifies pad counts, session integrity, lift-gate thresholds, and reports any stray CSV files.

### 5. Verify Sensor Pad Wiring
```bash
python run.py pads
```
Confirms physical 1-by-1 pad sweep matches `Data/Press/1_by_1.csv`.

### 6. Start Authenticated Remote Demo Tunnel
```bash
python run.py share
```
Generates a random access key and prints the shareable HTTPS Cloudflare URL.

---

## 4. Invariants (Safety & Architecture Contracts)

These contracts must **never be broken**:

1. **Browser Never Classifies**: Severity level, CPRI, and lifted pad counts originate exclusively on the server (`classify_deltas()`). `app.js` and `web_serial.js` only render.
2. **No Handcoded Probabilities**: Probabilities returned by `classify_deltas()` match model `predict_proba()` directly.
3. **No Invented Patient Identity**: No hardcoded fake names, hospital numbers (`HN-#####`), or ICU beds.
4. **Displayed Numbers Are Measured or Absent**: `index.html` `data-metric` attributes contain no hardcoded digits and are filled dynamically via `/api/v6/metrics`.
5. **SPEC_DETACH_MAX is 25000**: Threshold constant is derived honestly from the physical capacitive floor ($C_0$).
6. **Dockerfile Security**: Never run `--allow-public-no-key` in production containers.
7. **Zero Emoji**: No emoji characters in UI, logs, or status strings.
8. **IEC 62304 Disclaimer**: The notice `not been assessed against IEC 62304` must be visible on the console and present in slide decks.
9. **Metrics Reproducibility**: `Data/metrics.json` must always reproduce exactly from the 81 bench files.

---

## 5. Summary of Organization Done
- Created dedicated `tools/` folder for `cloudflared.exe` (removing 55 MB binary clutter from root).
- Moved `DEPLOY_GOOGLE.md` and `RELATED_RESEARCH_PAPER_SUMMARY.md` into `docs/`.
- Organized all loose `.pptx`, `.drawio`, `.svg`, and `.png` diagram files into `docs/figures/diagrams/`.
- Added `docs/presentation_deck.html` matching the supervisor defense executive deck (making `test_presentation_deck_endpoint` pass).
- Verified `python run.py verify` passes with 0 drift.
- Verified test suite: **264 tests passed 100%**.
