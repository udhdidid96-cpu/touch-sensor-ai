# Defense deck: transition build spec (Canva, PowerPoint, web)

The source of truth for content is `docs/presentation_deck.html`. It holds every headline, bullet, callout and speaker note (press N), and every figure names its generated source. This file says how to rebuild the motion in Canva or PowerPoint so that all three versions move the same way.

**Disclaimer, on slides 1 and 15:** "This prototype has not been assessed against IEC 62304. It is a screening aid and not a medical device."

## Global motion settings

| | Web (HTML) | Canva | PowerPoint |
|---|---|---|---|
| Camera move (pan, zoom) | `transform: scale(1/s) translate(-x,-y)`, 1.1 s, `cubic-bezier(.2,.7,.2,1)` | Match & Move, 1.1 s | Morph (Objects), 1.10 s; Summary/Section Zoom for the hub |
| Shared element | `data-morph="name"` (FLIP), 1.1 s | Same element copied to the next page, same layer order | Shape named `!!name` on both slides |
| Fade of the rest | 0.55 s opacity | Match & Move fades unmatched layers on its own | Morph fades unmatched shapes on its own |
| Metric card | Click to flip; the value counts up on arrival | Flip: two pages, card face then card back, Match & Move 0.6 s | Morph between a face slide and a back slide, or a Flip transition 0.6 s |
| Entrance | Rise 16 px, 0.7 s, staggered 0.15 s | Animate: Rise, "on page enter", 0.7 s | Fly In (from bottom, short), 0.7 s, With Previous plus 0.15 s delay |

### Rules that keep Match & Move and Morph clean

1. **One element per name.** If two shapes on a slide share `!!rule`, Morph pairs the wrong ones.
2. **Group before matching.** A card is one group (background, label and value). Match the group, not its parts.
3. **Keep the layer order identical** on both pages for every matched element. Canva pairs by type and position when names are absent, so duplicate the page rather than rebuilding it.
4. **Text that changes inside a matched card** morphs by character in PowerPoint. Set Morph to "Words" on the slides where a number changes (8 → 9, 11 → 12 → 13).

## Canvas layout (shared by all three versions)

```
row 1   [1 title]   [2 problem]   [3 physics]   [4 HUB: portals 5 | 6 | 7]
row 2   [14 timeline, 2 screens wide]   [stack B: 11/12/13]   [stack A: 8/9/10]
row 3   [15 close]
```

Step order: 1, 2, 3, 4, 5, 6, 7, 4 (zoom out), 8, 9, 10, 11, 12, 13, 14a, 14b, 15. That is 17 steps over 15 slides.

## Per-slide build

| # | Archetype | Headline | Into this slide | Canva | PowerPoint |
|---|---|---|---|---|---|
| 1 | White & Black, inverted | A dressing that warns before the tube comes out. | Open | Rise on 3 stat columns, staggered | Fly In, staggered |
| 2 | White & Black | 6.69% hero number (pooled meta-analysis) | Pan right | Match & Move: keep the 2 px black rule in the same spot | `!!rule` on both slides, Morph |
| 3 | White & Black | Contact adds capacitance. Lift replaces skin with air and removes it. | Pan right | Match & Move on `rule` | `!!rule` |
| 4 | Brand, modular cards | One dressing, one pipeline, one alarm. Zoom in. | Pan right | Three cards linked to pages 5-7 (Canva link to page) | **Summary Zoom** or Slide Zoom ×3, "Return to Zoom" ticked |
| 5 | Brand | 25 pads, and proof the channels are in pad order | Zoom into card 1 | Card 1 group scaled to full page, Match & Move 1.1 s | Slide Zoom, or Morph with the card named `!!card1` scaled up |
| 6 | Infographic | Five stages, twice a second, one code path | Pan across inside the hub | Match & Move; the 5 stage tiles stay in one row | Morph, `!!stage1`..`!!stage5` |
| 7 | Brand | The server picks the priority; the lamp only shows it | Pan | Lamps: Pulse animation on loop (high 0.5 s, medium 1.67 s) | Lamps: Emphasis > Blink; high 0.25 s on and 0.25 s off, medium 0.83 s / 0.83 s, repeat until next click |
| 4 again | Brand | (hub) | Zoom out | Match & Move from page 7 back to the hub copy | Zoom "Return to Zoom" |
| 8 | Red & Black | Every episode caught offline; one short pull missed when served | Camera drops to row 2 | Duplicate a page that holds the red rule; cards rise | `!!rule` (red bar, 120 px), `!!acc` (File accuracy card) |
| 9 | Red & Black | Two of 81 files misread, both toward the benign side | Morph in place | Same rule, wider (420 px); the accuracy card moves next to the matrix | `!!rule` 420 px, `!!acc` |
| 10 | Red & Black | File accuracy rose while the alarm burden doubled | Morph in place | Rule 760 px; the accuracy card becomes the "Shipped" chip | `!!rule` 760 px, `!!acc` |
| 11 | Red & Black | 25 of 25 measures the attachment, not the pull | Pan left to stack B | Fresh stack: rule 200 px; red alert card "-380 to -630" | `!!rule`, `!!gate` |
| 12 | Red & Black | Sliding does not lift the patch, so the lift gate cannot see it | Morph in place | `gate` card moves top-left, number becomes -283 / -306 / -336 | `!!gate` (Morph: Words) |
| 13 | Red & Black | ≤ 25,000 counts is unreachable on paper, before any experiment | Morph in place | `gate` card moves right, number becomes 50.1 pF | `!!gate` (Morph: Words) |
| 14 | Infographic | From one bench session to a first ICU feasibility study | Pan left, then scroll | Canva page twice as wide is not possible: use two pages with the timeline group offset by one screen, Match & Move 1.2 s | One slide with a 2-screen-wide group; Morph to a copy shifted left by one slide width |
| 15 | White & Black | Standards, milestones, three-line synthesis, disclaimer | Camera drops to row 3 | Match & Move on `rule` | `!!rule` |

## Numbers on the slides that differ from the brief

| Brief said | Slide says | Why |
|---|---|---|
| Served-path episode sensitivity 100% | Served 97.5% (39/40); offline 100% (40/40) | `Data/metrics.json`: the served path misses A_VPull_06 |
| "Served Path 97.53%" | 97.53% is file accuracy (79/81) | A different unit from episode sensitivity |
| 9 spatial statistics | 9 statistics | min, max, mean, sd and five threshold counts; none is spatial (`main.extract_features`) |
| UE 4.8-10.9% | 6.69% (95% CI 5.29-8.24), 1.06 per 100 ventilator-days, 84.2% self-extubation | Pooled meta-analysis (Intensive Crit Care Nurs 2022). The 4.8-10.9% range could not be sourced. |
| 7.8 alarms/h | 7.8/h offline, 5.2/h served | Both are in `metrics.json`; the served path is the device |

Random Forest appears on slide 10 from the 2026-08-19 measurement (96.30% file accuracy, 95.0% episode sensitivity) in the `main.new_rf` docstring. It was measured at an earlier operating point and is not in this round's benchmark.
