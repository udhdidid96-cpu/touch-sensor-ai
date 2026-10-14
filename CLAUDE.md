# CLAUDE.md - Master Engineering Instructions for Project2

You are working on **Project2 — Smart Extubation Early Warning** with a 25-channel capacitive touch sensor.
The Antigravity Godmode Supervisor has audited, benchmarked, and verified this codebase. You must strictly follow these rules:

## 1. Core Invariants (DO NOT BREAK)
1. **Never delete or move the 81 legacy benchmark recordings** in `Data/<class>/*.csv`.
2. **Never self-seed baseline on early frames of Pull/Press recordings**:
   - The files in `Data/data new vaccum/` (`A_HPull`, `A_VPull`, `A_OPull`) were started *after* displacement began.
   - Self-seeding on frames 0..4 subtracts out the pull effect and falsely makes HPull appear "quiet".
   - Reference deltas to the settled, attached state of the **same attachment**. `N_base1.csv` frames 20..99 ($C_0$ mean 28,568 counts) is that state only for files recorded before the patch was re-attached; it came off in both `A_VPulldown` files, and the HPull/OPull/VPull5 attachment rests -380..-630 on Signal-12/13 against $C_0$ while attached and still.
   - Measured 2026-09-26: against its own settled attachment the held HPull dip is -283 / -306 / -336 (deepest channel), so it straddles the -300 gate (1-2 of 3 files). Against $C_0$ all 13 pulls cross -300, but so do 9 of 12 non-pull items (mostly an unattached patch), so a crossing against $C_0$ is not a detection claim. See `.claude/findings.md` (2026-09-26).
3. **Channel Ingestion**:
   - Files in `data new vaccum/` have 25 channels (`Signal-1`..`Signal-25`) plus an empty trailing `Signal-26` (NaN). Always drop `Signal-26`.
4. **Guard Suite**:
   - `python run.py test` must always stay green.
   - `python run.py verify` checks `Data/metrics.json`.
5. **No Clutter & No Invented Identities**:
   - Do not generate slide decks, presentations, or clutter files in `Data/`.
   - Never invent patient IDs (`HN-#####`, Thai names, etc.).

## 2. Standard Evaluation
To run the automated vacuum station ML benchmark:
```bash
python scripts/evaluate_vacuum_station.py
```
It prints the 25-item LOFO headline (N_base1 split in two chunks, 40 features: 25/25) together with three controls: strict 24-file LOFO (23/24), settled tails (45/45 still, attached frames of pull files called "pull") and leave-the-last-attachment-out (4/7 pull votes). Quote the headline only with the controls: file labels plus recording order let the model recognise the attachment instead of the pull. The 6 "spatial shear" features are edge-row/column contrasts, not shear.

## 3. Workflow Protocol
- Refer to `.claude/task_plan.md` and `.claude/findings.md` for latest discoveries and milestones.
- Keep the pipeline robust, reproducible, and grounded in measured physics.

## 4. Claude Desktop Skills Protocol
- **Recommended slash commands & skills in prompts**:
  - `/brainstorm` (explores requirements, design, and intent discovery before creative planning)
  - `/write-plan` / `/execute-plan`
  - `/ponytail`
  - `/caveman`
  - `/find-skills`
  - `/using-superpowers`
- **DO NOT use `/goal`** as a slash command in Claude Desktop (it is not a recognized slash command and causes an `Unknown skill: goal` error).


