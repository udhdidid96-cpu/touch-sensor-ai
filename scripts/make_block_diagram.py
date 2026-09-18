#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project2 - system block diagram: signal path, and the offline branch that
identifies the classifier parameters.

    python scripts/make_block_diagram.py

Writes docs/Project2_Block_Diagram.{drawio,svg} (+ .png with cairosvg).
Edit BLOCKS / LINKS below and re-run.  Do not hand-edit the .drawio.
Figures come from Data/METRICS.md and constants in main.py.
"""
import os, html

INK, SPEC, FAINT = '#1B1B1B', '#6E6E6E', '#9A9A9A'
STROKE, ACC, RULE = '#333333', '#9C3B2E', '#C7C7C7'
W, H = 1258, 880

def esc(s): return html.escape(s, quote=True)

class B:
    def __init__(self, i, x, y, w, h, title, spec='', accent=False, dash=False):
        self.id, self.x, self.y, self.w, self.h = i, x, y, w, h
        self.title, self.spec, self.accent, self.dash = title, spec, accent, dash
    cx = property(lambda s: s.x + s.w / 2)
    cy = property(lambda s: s.y + s.h / 2)
    r  = property(lambda s: s.x + s.w)
    b  = property(lambda s: s.y + s.h)

# ------------------------------------------------------------------ geometry
SX, SW, SH, SG = 548, 396, 58, 48          # signal path column
PX, PW, PG     = 104, 340, 30              # parameter branch column
Y0 = 132
sig = lambda k: Y0 + k * (SH + SG)

p1 = B('p1', SX, sig(0), SW, SH, 'Capacitive patch', '25 channels, 90 x 120 mm')
p2 = B('p2', SX, sig(1), SW, SH, 'Frame guard', 'dropout holds level, warm-up 5')
p3 = B('p3', SX, sig(2), SW, SH, 'Baseline estimator', 'Kalman, q = 0.05')
p4 = B('p4', SX, sig(3), SW, SH, 'Feature map', '25 deltas + 9 statistics')
p5 = B('p5', SX, sig(4), SW, SH, 'Classifier', 'HistGradientBoosting')
p6 = B('p6', SX, sig(5), SW, SH, 'Debouncer', '6 of 7 votes, hold 9')
out = B('out', SX, sig(6), SW, 40, 'severity level 0 - 3   +   risk %', '', accent=True)

cpri = B('cpri', SX + SW + 66, sig(4), 176, SH, 'CPRI', 'risk 0 - 100%')

qy = p5.y - 4 * (SH + PG)
q = [B(f'q{k+1}', PX, qy + k * (SH + PG), PW, SH, t, s, dash=True) for k, (t, s) in enumerate([
    ('Recorded corpus',  '81 clips, 3,349 frames'),
    ('Baseline + feature map', 'the same two blocks'),
    ('Fit',              '150 iter, depth 8, balanced'),
    ('Validation',       'LOFO 97.5%, episode 100%'),
    ('Release gate',     'metrics reproduce, 113 tests'),
])]
BLOCKS = [p1, p2, p3, p4, p5, p6, out, cpri] + q

# (from, to, label, side)
LINKS = [
    (p1, p2, 'x[n]   25 raw counts, 1.79 Hz', 'v'),
    (p2, p3, 'gated frame', 'v'),
    (p3, p4, 'delta[n] = x[n] - b[n]', 'v'),
    (p4, p5, 'f[n]   34 features', 'v'),
    (p5, p6, 'p[n]   P(class 0..3)', 'v'),
    (p6, out, '', 'v'),
    (p5, cpri, '', 'h'),
]
QLINKS = [(q[i], q[i+1]) for i in range(len(q)-1)]

TITLE = 'Smart dressing  -  system block diagram'
META  = ('Project2  |  main.py v6.2  |  signal path on the right, parameter identification '
         'on the left  |  figures from Data/METRICS.md')
NOTES = [
 'The offline branch runs once and re-uses the same baseline and feature blocks as the signal path, so its figures describe the running system.',
 'Round-1 corpus, one sensor mounting.  No recording reaches the 25,000-count detachment spec; horizontal pull shows no lift signal.',
]

def svg():
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Tahoma, sans-serif">', '<defs>']
    for k, c in [('a', STROKE), ('c', ACC)]:
        p.append(f'<marker id="{k}" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="5.5" '
                 f'markerHeight="5.5" orient="auto-start-reverse">'
                 f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>')
    p.append('</defs>')
    p.append(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
    p.append(f'<text x="{PX}" y="54" font-size="19.5" font-weight="bold" fill="{INK}">'
             f'{esc(TITLE)}</text>')
    p.append(f'<text x="{PX}" y="73" font-size="9.6" fill="{SPEC}">{esc(META)}</text>')
    p.append(f'<line x1="{PX}" y1="86" x2="{W-PX}" y2="86" stroke="{INK}" stroke-width="1.4"/>')

    # column captions
    p.append(f'<text x="{PX}" y="{qy-16}" font-size="9.6" font-weight="bold" fill="{FAINT}" '
             f'letter-spacing="2">PARAMETER IDENTIFICATION  -  offline, once</text>')
    p.append(f'<text x="{SX}" y="{Y0-16}" font-size="9.6" font-weight="bold" fill="{FAINT}" '
             f'letter-spacing="2">SIGNAL PATH  -  every 560 ms</text>')

    def arrow(x1, y1, x2, y2, col=STROKE, dash=False):
        d = ' stroke-dasharray="5 4"' if dash else ''
        mk = 'c' if col == ACC else 'a'
        p.append(f'<path d="M {x1:.1f},{y1:.1f} L {x2:.1f},{y2:.1f}" stroke="{col}" '
                 f'stroke-width="1.2" fill="none"{d} marker-end="url(#{mk})"/>')

    for a, b, lab, kind in LINKS:
        if kind == 'v':
            arrow(a.cx, a.b + 1, b.cx, b.y - 4)
            if lab:
                p.append(f'<text x="{a.cx+11:.1f}" y="{(a.b+b.y)/2+4:.1f}" font-size="9.6" '
                         f'fill="{SPEC}">{esc(lab)}</text>')
        else:
            arrow(a.r + 1, a.cy, b.x - 4, b.cy)
    p.append(f'<path d="M {cpri.cx:.1f},{cpri.b+1:.1f} L {cpri.cx:.1f},{out.cy:.1f} '
             f'L {out.r+4:.1f},{out.cy:.1f}" fill="none" stroke="{STROKE}" stroke-width="1.2" '
             f'marker-end="url(#a)"/>')
    for a, b in QLINKS:
        arrow(a.cx, a.b + 1, b.cx, b.y - 4, dash=True)
    # parameter hand-off
    arrow(q[-1].r + 1, q[-1].cy, p5.x - 4, p5.cy, ACC)
    p.append(f'<text x="{(q[-1].r+p5.x)/2:.1f}" y="{p5.cy-9:.1f}" font-size="9.6" fill="{ACC}" '
             f'text-anchor="middle">theta</text>')
    p.append(f'<text x="{(q[-1].r+p5.x)/2:.1f}" y="{p5.cy+16:.1f}" font-size="9" fill="{ACC}" '
             f'text-anchor="middle">trained_model.joblib</text>')
    # recursive baseline
    lx = p3.x - 26
    p.append(f'<path d="M {p3.x:.1f},{p3.cy-13:.1f} L {lx:.1f},{p3.cy-13:.1f} '
             f'L {lx:.1f},{p3.cy+13:.1f} L {p3.x-4:.1f},{p3.cy+13:.1f}" fill="none" '
             f'stroke="{STROKE}" stroke-width="1.1" marker-end="url(#a)"/>')
    p.append(f'<text x="{lx-6:.1f}" y="{p3.cy+3:.1f}" font-size="9" fill="{FAINT}" '
             f'text-anchor="end">b[n]</text>')

    for bl in BLOCKS:
        col = ACC if bl.accent else STROKE
        d = ' stroke-dasharray="5 4"' if bl.dash else ''
        p.append(f'<rect x="{bl.x}" y="{bl.y}" width="{bl.w}" height="{bl.h}" rx="3" '
                 f'fill="#FFFFFF" stroke="{col}" stroke-width="1.3"{d}/>')
        if bl.spec:
            p.append(f'<text x="{bl.cx}" y="{bl.cy-3:.1f}" font-size="13" font-weight="bold" '
                     f'fill="{INK}" text-anchor="middle">{esc(bl.title)}</text>')
            p.append(f'<text x="{bl.cx}" y="{bl.cy+13:.1f}" font-size="9.6" fill="{SPEC}" '
                     f'text-anchor="middle">{esc(bl.spec)}</text>')
        else:
            p.append(f'<text x="{bl.cx}" y="{bl.cy+5:.1f}" font-size="13.5" font-weight="bold" '
                     f'fill="{col}" text-anchor="middle" letter-spacing="0.6">'
                     f'{esc(bl.title)}</text>')
    y = H - 44
    for n in NOTES:
        p.append(f'<text x="{PX}" y="{y:.1f}" font-size="9.5" fill="{SPEC}">{esc(n)}</text>')
        y += 13
    p.append('</svg>')
    return '\n'.join(p)

def drawio():
    c = ['<mxfile host="app.diagrams.net" type="device">',
         '<diagram id="p2blk" name="Block diagram">',
         f'<mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" guides="1" connect="1" '
         f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}">'
         '<root><mxCell id="0"/><mxCell id="1" parent="0"/>']
    k = [0]
    def nid(): k[0] += 1; return f'e{k[0]}'
    F = 'fontFamily=Helvetica;'
    def cell(v, st, x, y, w, h, i=None):
        c.append(f'<mxCell id="{i or nid()}" value="{esc(v)}" style="{st}" vertex="1" '
                 f'parent="1"><mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                 f'height="{h:.0f}" as="geometry"/></mxCell>')
    cell(f'<b>{esc(TITLE)}</b>', f'text;html=1;fontSize=19;fontColor={INK};align=left;{F}',
         PX, 36, W - 2*PX, 26)
    cell(esc(META), f'text;html=1;fontSize=9;fontColor={SPEC};align=left;{F}', PX, 62, W-2*PX, 16)
    cell('<b>PARAMETER IDENTIFICATION - offline, once</b>',
         f'text;html=1;fontSize=9;fontColor={FAINT};align=left;{F}', PX, qy-32, PW+60, 16)
    cell('<b>SIGNAL PATH - every 560 ms</b>',
         f'text;html=1;fontSize=9;fontColor={FAINT};align=left;{F}', SX, Y0-32, SW, 16)
    for bl in BLOCKS:
        col = ACC if bl.accent else STROKE
        v = f'<b>{esc(bl.title)}</b>'
        if bl.spec:
            v += f'<br><font color="{SPEC}" style="font-size:9px">{esc(bl.spec)}</font>'
        cell(v, f'rounded=1;arcSize=6;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor={col};'
                f'strokeWidth=1.3;{"dashed=1;dashPattern=5 4;" if bl.dash else ""}'
                f'fontSize=12;fontColor={INK};{F}', bl.x, bl.y, bl.w, bl.h, bl.id)
    def edge(a, b, lab, ex, ey, nx, ny, col=STROKE, dash=False):
        c.append(f'<mxCell id="{nid()}" value="{esc(lab)}" style="edgeStyle=orthogonalEdgeStyle;'
                 f'html=1;strokeColor={col};strokeWidth=1.2;endArrow=block;endSize=5;'
                 f'{"dashed=1;dashPattern=5 4;" if dash else ""}exitX={ex};exitY={ey};'
                 f'entryX={nx};entryY={ny};fontSize=9;fontColor={SPEC};'
                 f'labelBackgroundColor=#FFFFFF;{F}" edge="1" parent="1" source="{a.id}" '
                 f'target="{b.id}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    for a, b, lab, kind in LINKS:
        if kind == 'v': edge(a, b, lab, .5, 1, .5, 0)
        else:           edge(a, b, lab, 1, .5, 0, .5)
    edge(cpri, out, '', .5, 1, 1, .5)
    for a, b in QLINKS: edge(a, b, '', .5, 1, .5, 0, dash=True)
    edge(q[-1], p5, 'theta - trained_model.joblib', 1, .5, 0, .5, ACC)
    cell('<br>'.join(esc(n) for n in NOTES),
         f'text;html=1;fontSize=9;fontColor={SPEC};align=left;{F}', PX, H-54, W-2*PX, 40)
    c.append('</root></mxGraphModel></diagram></mxfile>')
    return '\n'.join(c)

here = os.path.dirname(os.path.abspath(__file__))
out_dir = os.path.join(here, '..', 'docs') if os.path.basename(here) == 'scripts' else here
os.makedirs(out_dir, exist_ok=True)
sp = os.path.join(out_dir, 'Project2_Block_Diagram.svg')
open(sp, 'w', encoding='utf-8').write(svg())
open(os.path.join(out_dir, 'Project2_Block_Diagram.drawio'), 'w', encoding='utf-8').write(drawio())
try:
    import cairosvg
    cairosvg.svg2png(url=sp, write_to=os.path.join(out_dir, 'Project2_Block_Diagram.png'),
                     output_width=2360)
except ImportError:
    print('cairosvg missing - PNG skipped')
print(f'{W} x {H}, blocks={len(BLOCKS)}')
