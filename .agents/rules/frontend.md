# The operator console — web/

Scope: `web/**`. Set this rule to **Glob** with pattern `web/**`.

Rebuilt 2026-08-21 as a light clinical assessment console with a dark toggle,
after the user rejected two earlier faces. Layout: full-width topbar over a
`sidebar 218px / main` grid; the dashboard is a control rail followed by
LIVE ANALYSIS + ASSESSMENT SUMMARY, PROCESSING PIPELINE + MODEL VALIDATION,
then ASSESSMENT HISTORY + NOTES.

## Colour and type

**Every value is a token in `:root` in `style.css`, with a full
`[data-theme="dark"]` override. Never inline a colour, in CSS or in a JS
`style.color =` assignment.** The previous build wrote hexes chosen for a dark
canvas directly into SVG attributes; on the light console a quiescent pad came
out as a black blot and several labels measured under 3:1.

- `--ink-3` is `#5d6777`. It must be measured against **`--panel-2` and
  `--panel-3`**, not white — those tinted surfaces are where the 9–11px labels
  actually sit. The previous `#6b7789` passed on white at 4.54:1 and failed at
  4.27:1 where it was used.
- Thai and Japanese faces are named explicitly in the font stack
  (`Sarabun`, `Noto Sans JP`, `Leelawadee UI`, `Noto Sans Thai`, `Yu Gothic UI`,
  `Meiryo`). Drop them and that copy renders as boxes.
- Alarm colour is semantic and separate from the blue accent.
  `body[data-level="2"|"3"]` puts a rule under the topbar so state reads
  peripherally.

## Three languages

Thai, English, Japanese. Translation is by **`data-i18n="key"` attribute**
(`data-i18n-ph` for placeholders), swept by `switchLanguage()`. Do not go back
to a hand-kept map of element ids: the old map named 22 ids, and everything
added afterwards silently stayed English.

- All three dictionaries carry the same key set. Add a key to one, add it to
  all three.
- `renderFrame` keeps the tags in step — it sets `data-i18n` to `status_${lvl}`
  / `desc_${lvl}` / `cat_${lvl}` as it draws, and **removes** it from
  `#patchIntegrityDesc` in the branch whose text interpolates a pad count.
  Without that, switching language mid-alarm relabels a Level 3 as "normal".
- The sweep writes `textContent` only. `#statusBanner` carries
  `status-pill lvl-N`, which the renderer owns.

## Layout traps already paid for

- **`.patch-outline` must be `fill: none`.** Filling it paints an opaque shape
  over `#heatmapCanvas`, which sits behind the SVG — the wash is drawn every
  frame and never reaches the screen.
- **`.chartbox` needs `grid-template-rows: auto minmax(0,1fr)`** and an explicit
  height on `.chartbox__canvas`. Chart.js measures its parent; a flex child
  resolved to zero and the chart drew nothing at all.
- **`.stage__frame` is `width: min(100%, 322px)` + `aspect-ratio: 3/4`** with
  canvas and SVG absolutely positioned inside. A percentage height in an auto
  row feeds back into the width and grows the row without bound.
- **The pipeline is a 5-column grid** whose connectors are `::before`/`::after`
  on each step. Separate arrow elements wrap onto the next row and start it
  with a chevron pointing at nothing.
- `#heatmapCanvas` needs `clip-path: url(#patchClip)` — the interpolation
  extrapolates past the outer pads and paints invented signal outside the
  dressing outline.

## Canvases are painted, not styled

Chart.js resolves its colours once, at construction. `restyleChart()` re-reads
them from the tokens on every theme change, and `drawHeatmapGaussian()`
re-fetches its hues the same way. If you add a dataset or a wash colour, wire it
into both.

## View routing

`showView()` toggles `.view.is-active`. **Never route with an inline
`style="display:none"`** — the metrics guard is a regex over inline style, and
an inline-hidden ancestor near a `data-metric` slot fails the suite.

`live` and `replay` are not separate views: they route to the dashboard and set
the acquisition mode, so the panels cannot drift out of step with a second copy.
