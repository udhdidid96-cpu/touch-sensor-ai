# S1 recording protocol: an unseen test set for the pull detector

Written 2026-10-05. Purpose: measure the served model and the unified (old bench + vacuum station) model on data neither has seen, so the result cannot come from recognising an attachment or a recording time.

Why this is needed, measured on 2026-10-05 (`scratch/claude_runs/`):

- Trained on the 81 bench files, tested on the 24 vacuum-station files: 0/13 pulls caught.
- On the vacuum station alone, settled end frames of pull files (patch attached and still) are called "pull" 45/45 times, and holding out the last attachment catches 4/7 pulls (95% CI 18-90%).
- Cause: every vacuum pull file was recorded after every non-pull file, and each re-attachment rests at its own level. Labels can be told apart by attachment and time alone.

## Rules

1. **Freeze both models before the first S1 file.** No retuning, no threshold change, no new feature after S1 data exists (tune on old, measure on new).
2. **One attachment = one block.** Peel the patch off and re-apply it before every block. Give each block an id (`A01`, `A02`, ...).
3. **Every block holds all classes**, in an order that changes from block to block (see the schedule). Pulls and non-pulls must never be grouped in time.
4. **Every file starts quiet.** Start recording, wait at least 5 s with nobody touching the patch, then act. This gives each file its own settled baseline. The 2026-09-25 pull files started after the displacement began and could not be referenced to themselves.
5. **End every pull file detached or at maximum displacement**, then stop. Do not let it settle back into the same file.
6. Record C0 for each block (SOP v2 section 0.2) before the first file of the block.

## Surfaces

| Surface | What | Blocks |
|---|---|---|
| flat | the current vacuum station | 5 |
| curved | 3D-printed cheek or mandible phantom, R about 30 mm | 5 |
| step | 5 mm ridge block under the patch (ETT-sized) | 5 |

Fifteen blocks in all. If time is short, cut whole surfaces, not blocks: 5 blocks on one surface beats 2 on each.

## Classes per block (one file each)

| Folder | Action | Label in `main.py` |
|---|---|---|
| `N_base` | patch attached, nobody touches it, 20 s | 0 |
| `N_Press` | hand press on the patch, 3 presses | 1 |
| `N_Fric` | cloth rubbed across the patch, 10 s | 1 |
| `Brief Touch` | 3 short touches | 1 |
| `A_VPull` | tube pulled straight up, 90 degrees | 3 |
| `A_HPull` | tube pulled along the skin, 0-15 degrees | 3 |
| `A_OPull` | tube pulled at 45 degrees | 3, needs one line in `CLASS_MAPPING` (below) |

Seven files per block, 105 files in all, the same size as the current corpus.

## Schedule

Rotate the order so no class sits in the same slot twice in a row. Example for the first three blocks; continue the rotation:

| Block | Order |
|---|---|
| A01 | N_base, A_VPull, N_Press, A_HPull, N_Fric, A_OPull, Brief Touch |
| A02 | A_HPull, N_Fric, A_OPull, N_base, Brief Touch, A_VPull, N_Press |
| A03 | N_Press, A_OPull, Brief Touch, A_VPull, N_base, N_Fric, A_HPull |

## Files

```
Data/S1/<class folder>/<block>_<surface>_<class>.csv     e.g. Data/S1/A_HPull/A04_curved_A_HPull.csv
Data/S1/manifest.csv
```

The loader reads session folders named `S<number>` only; `data new vaccum` is invisible to it. Keep `Signal-1`..`Signal-25`; the empty `Signal-26` is dropped.

`manifest.csv` columns: `file, block, surface, step_mm, angle_deg, c0_counts, start_time, operator, note`.

## Before scoring S1

`A_OPull` is not a class key yet. Add `"A_OPull": {"label": 3, "class_name": "3: Oblique Pull (Alarm)"}` to `CLASS_MAPPING` in `main.py`, then run `python run.py test` and `python run.py verify`: S0 figures must not move.

## Scoring, once, after all files exist

For each model (served S0 model; unified model), report per surface and per pull type:

- pulls caught / pulls recorded, with Clopper-Pearson 95% interval;
- non-pull files called pull / non-pull files;
- the settled-tail control: last 5 still frames of each non-pull file called pull.

Quote only these numbers for S1. Leave-one-file-out inside S1 is a secondary figure, never the headline.
