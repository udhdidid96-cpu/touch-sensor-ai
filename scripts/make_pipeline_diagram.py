#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regenerate the Project2 training-to-inference pipeline diagram.

    python scripts/make_pipeline_diagram.py

Writes docs/Project2_Pipeline_Diagram.drawio (editable in diagrams.net or the
VS Code extension) and .svg (editable in Illustrator / Figma / Inkscape).
Install cairosvg to also get a PNG.

Scope: from preparing the training data through to the model running on live
frames.  It deliberately stops at the served output and does NOT cover the web
console.  Every figure is copied from Data/METRICS.md or read out of main.py.
"""
import os, textwrap, html

# ----------------------------------------------------------------- palette
# One hue family (desaturated blue-grey) in three values, plus one warm accent.
# Nothing else on the sheet is coloured.
H1, H2, H3 = '#17323E', '#2F5B6D', '#4C8299'
ACC  = '#9C3B2E'
INK, MUTED, SID = '#16202A', '#65717B', '#9BA6AE'
PAGE, SHEET, FRAME = '#FFFFFF', '#FFFFFF', '#1E3A4C'
PANEL, PANEL_S = '#F5F7F8', '#E3E8EB'
ARROW, ELAB = '#45565F', '#65717B'
FEED = '#94A3AB'

C = {
 'step' : dict(fill='#FFFFFF', stroke='#54707F', title=INK),
 'c1'   : dict(fill='#FFFFFF', stroke=H1, title=H1),
 'c2'   : dict(fill='#FFFFFF', stroke=H2, title=H2),
 'c3'   : dict(fill='#FFFFFF', stroke=H3, title='#4E7near'),
 'warn' : dict(fill='#FFFFFF', stroke=ACC, title=ACC),
 'grey' : dict(fill='#FAFBFB', stroke='#98A4AC', title='#45565F'),
}
C['c3']['title'] = '#3F6F84'
HDR = {'c1': H1, 'c2': H2, 'c3': H3}

PAD_TOP, PAD_BOT = 12, 14
SID_FS, SID_LH = 9.5, 13.0
T_FS, T_LH = 14.0, 18.0
D_FS, D_LH = 10.4, 13.8

def esc(s): return html.escape(s, quote=True)
def thai(s): return any('฀' <= ch <= '๿' for ch in s)
def fam(s, ital=False, mono=False):
    a = ' font-family="Loma, Tahoma, sans-serif"' if thai(s) else (
        ' font-family="DejaVu Sans Mono, monospace"' if mono else '')
    return a + (' font-style="italic"' if ital else '')

def wrap(text, w, fs, factor):
    cpl = max(6, int(w / (fs * factor)))
    out = []
    for para in text.split('\n'):
        out += textwrap.wrap(para, cpl) if para.strip() else ['']
    return out

# ------------------------------------------------------------------ shapes
class Node:
    kind = 'box'
    def __init__(self, nid, w):
        self.id, self.w, self.x, self.y = nid, w, 0.0, 0.0
    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2
    @property
    def r(self): return self.x + self.w
    @property
    def b(self): return self.y + self.h

class Step(Node):
    def __init__(self, nid, sid, title, desc='', style='step', w=400):
        super().__init__(nid, w)
        self.sid, self.style = sid, style
        inner = w - 26
        self.tl = wrap(title, inner, T_FS, 0.60)
        self.dl = wrap(desc, inner, D_FS, 0.545) if desc else []
        self.h = (PAD_TOP + (SID_LH if sid else 0) + len(self.tl) * T_LH +
                  ((6 + len(self.dl) * D_LH) if self.dl else 0) + PAD_BOT)

class Pill(Node):
    kind = 'pill'
    def __init__(self, nid, text, fill, w=300, h=44, fs=13.5):
        super().__init__(nid, w)
        self.text, self.fill, self.h, self.fs = text, fill, h, fs

class Hdr(Node):
    kind = 'hdr'
    def __init__(self, nid, text, key, w=400, h=30):
        super().__init__(nid, w)
        self.text, self.fill, self.h = text, HDR[key], h

class Dia(Node):
    kind = 'diamond'
    def __init__(self, nid, text, w=360, h=96):
        super().__init__(nid, w)
        self.text, self.h = text, h
        self.tl = wrap(text, w * 0.62, 12.0, 0.58)

class Lane:
    HEAD = 10
    ROW_GAP, COL_GAP, PAD = 30, 22, 20
    def __init__(self, badge, label, rows):
        self.badge, self.label, self.rows = badge, label, rows
        self.x = self.y = self.w = self.h = 0.0
    def place(self, x, y, w):
        self.x, self.y, self.w = x, y, w
        cur = y + self.PAD
        for row in self.rows:
            tot = sum(n.w for n in row) + self.COL_GAP * (len(row) - 1)
            bx = x + (w - tot) / 2
            rh = max(n.h for n in row)
            for n in row:
                n.x = bx; n.y = cur + (rh - n.h) / 2
                bx += n.w + self.COL_GAP
            cur += rh + self.ROW_GAP
        self.h = (cur - self.ROW_GAP + self.PAD) - y
        return self.h
    def nodes(self):
        return [n for row in self.rows for n in row]

# ------------------------------------------------------------------ canvas
class Sheet:
    def __init__(self):
        self.lanes, self.edges = [], []
    def edge(self, a, b, side='TB', label='', color=None, dashed=False, via=None,
             bx=None, mid=None):
        self.edges.append(dict(a=a, b=b, side=side, label=label, color=color or ARROW,
                               dashed=dashed, via=via, bx=bx, mid=mid))
    def nodes(self):
        out = []
        for l in self.lanes: out += l.nodes()
        return out

def pts_for(e):
    a, b, s = e['a'], e['b'], e['side']
    if e['via'] is not None:               # route around at a fixed x
        vx = e['via']
        return [(a.r if vx > a.cx else a.x, a.cy), (vx, a.cy),
                (vx, b.cy), (b.r if vx > b.cx else b.x, b.cy)]
    if s == 'TB':
        x1, y1 = a.cx, a.b
        x2, y2 = (b.cx if e['bx'] is None else e['bx']), b.y
        if abs(x1 - x2) < 4: return [(x1, y1), (x2, y2)]
        my = (y1 + y2) / 2 if e['mid'] is None else e['mid']
        return [(x1, y1), (x1, my), (x2, my), (x2, y2)]
    if s == 'BT':
        x1, y1, x2, y2 = a.cx, a.y, b.cx, b.b
        if abs(x1 - x2) < 4: return [(x1, y1), (x2, y2)]
        my = (y1 + y2) / 2
        return [(x1, y1), (x1, my), (x2, my), (x2, y2)]
    if s == 'RL':
        x1, y1, x2, y2 = a.r, a.cy, b.x, b.cy
        if abs(y1 - y2) < 4: return [(x1, y1), (x2, y2)]
        mx = (x1 + x2) / 2
        return [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
    if s == 'LR':
        x1, y1, x2, y2 = a.x, a.cy, b.r, b.cy
        if abs(y1 - y2) < 4: return [(x1, y1), (x2, y2)]
        mx = (x1 + x2) / 2
        return [(x1, y1), (mx, y1), (mx, y2), (x2, y2)]
    raise ValueError(s)

def to_svg(sh, W, H, title, sub, footer):
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Loma, Tahoma, sans-serif">',
         '<defs>']
    for name, col in [('a', ARROW), ('f', FEED), ('r', '#B3241F')]:
        p.append(f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" '
                 f'markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">'
                 f'<path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
    p.append('</defs>')
    p.append(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')
    p.append(f'<rect x="14" y="14" width="{W-28}" height="{H-28}" fill="none" '
             f'stroke="{FRAME}" stroke-width="1.6"/>')
    p.append(f'<text x="{W/2}" y="66" font-size="29" font-weight="bold" fill="{INK}" '
             f'text-anchor="middle">{esc(title)}</text>')
    p.append(f'<text x="{W/2}" y="90" font-size="12.5" fill="{MUTED}" font-style="italic" '
             f'text-anchor="middle">{esc(sub)}</text>')

    for l in sh.lanes:
        if not l.badge:
            continue
        p.append(f'<rect x="{l.x}" y="{l.y}" width="{l.w}" height="{l.h}" rx="12" '
                 f'fill="{PANEL}" stroke="{PANEL_S}" stroke-width="1"/>')
        bx, by = l.x - 46, l.y + 34
        p.append(f'<circle cx="{bx}" cy="{by}" r="15" fill="{INK}"/>')
        p.append(f'<text x="{bx}" y="{by+5}" font-size="14" font-weight="bold" '
                 f'fill="#FFFFFF" text-anchor="middle">{l.badge}</text>')
        ly = l.y + l.h / 2
        p.append(f'<text x="{l.x-84}" y="{ly}" font-size="11.5" font-weight="bold" '
                 f'fill="{MUTED}" text-anchor="middle" letter-spacing="1.6" '
                 f'transform="rotate(-90 {l.x-84} {ly})"{fam(l.label)}>{esc(l.label)}</text>')

    labels = []
    for e in sh.edges:
        pts = pts_for(e)
        col = e['color']
        mk = 'f' if col == FEED else ('r' if col == '#B3241F' else 'a')
        d = 'M ' + ' L '.join(f'{x:.1f},{y:.1f}' for x, y in pts)
        dash = ' stroke-dasharray="7 5"' if e['dashed'] else ''
        p.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="1.7"{dash} '
                 f'marker-end="url(#{mk})"/>')
        if e['label'] and e['via'] is not None:
            vx = e['via']
            vy = (pts[1][1] + pts[2][1]) / 2
            labels.append(f'<text x="{vx+8:.1f}" y="{vy:.1f}" font-size="10" fill="{col}" '
                          f'font-style="italic" text-anchor="middle" '
                          f'transform="rotate(-90 {vx+8:.1f} {vy:.1f})">{esc(e["label"])}</text>')
        elif e['label']:
            if len(pts) == 2:
                mx, my = (pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2
            else:
                (x0, y0), (x1, y1) = pts[0], pts[1]
                seg = ((x1-x0)**2 + (y1-y0)**2) ** 0.5 or 1.0
                t = min(30.0, seg * 0.5) / seg
                mx, my = x0 + (x1-x0)*t, y0 + (y1-y0)*t
            vertical = abs(pts[0][0] - pts[1][0]) < 4 and len(pts) == 2
            ax, anc = (mx + 9, 'start') if vertical else (mx, 'middle')
            labels.append(f'<text x="{ax:.1f}" y="{my-6:.1f}" font-size="10" fill="{col}" '
                          f'font-style="italic" text-anchor="{anc}">{esc(e["label"])}</text>')

    for n in sh.nodes():
        if n.kind == 'pill':
            p.append(f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" '
                     f'rx="{n.h/2}" fill="{n.fill}"/>')
            p.append(f'<text x="{n.cx}" y="{n.cy+n.fs*0.36:.1f}" font-size="{n.fs}" '
                     f'font-weight="bold" fill="#FFFFFF" text-anchor="middle" '
                     f'letter-spacing="0.8"{fam(n.text)}>{esc(n.text)}</text>')
        elif n.kind == 'hdr':
            p.append(f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" rx="5" '
                     f'fill="{n.fill}"/>')
            p.append(f'<text x="{n.cx}" y="{n.cy+4.5:.1f}" font-size="11.5" '
                     f'font-weight="bold" fill="#FFFFFF" text-anchor="middle" '
                     f'letter-spacing="1.4">{esc(n.text)}</text>')
        elif n.kind == 'diamond':
            pth = (f'M {n.cx},{n.y} L {n.r},{n.cy} L {n.cx},{n.b} L {n.x},{n.cy} Z')
            p.append(f'<path d="{pth}" fill="#FFFFFF" stroke="{ACC}" stroke-width="1.6"/>')
            ty = n.cy - (len(n.tl) - 1) * 7 + 4
            for ln in n.tl:
                p.append(f'<text x="{n.cx}" y="{ty:.1f}" font-size="12" fill="{ACC}" '
                         f'text-anchor="middle"{fam(ln)}>{esc(ln)}</text>')
                ty += 14
        else:
            st = C[n.style]
            p.append(f'<rect x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" rx="7" '
                     f'fill="{st["fill"]}" stroke="{st["stroke"]}" stroke-width="1.6"/>')
            ty = n.y + PAD_TOP
            if n.sid:
                p.append(f'<text x="{n.cx}" y="{ty+9:.1f}" font-size="{SID_FS}" fill="{SID}" '
                         f'text-anchor="middle" letter-spacing="1.2">{esc(n.sid)}</text>')
                ty += SID_LH
            ty += T_FS
            for ln in n.tl:
                p.append(f'<text x="{n.cx}" y="{ty:.1f}" font-size="{T_FS}" font-weight="bold" '
                         f'fill="{st["title"]}" text-anchor="middle"{fam(ln)}>{esc(ln)}</text>')
                ty += T_LH
            if n.dl:
                ty += 6 - T_LH + D_LH
                for ln in n.dl:
                    p.append(f'<text x="{n.cx}" y="{ty:.1f}" font-size="{D_FS}" fill="{MUTED}" '
                             f'text-anchor="middle"{fam(ln)}>{esc(ln)}</text>')
                    ty += D_LH
    p += labels
    fy = H - 78
    for i, line in enumerate(footer):
        p.append(f'<text x="{W/2}" y="{fy + i*15:.1f}" font-size="10.5" fill="{MUTED}" '
                 f'text-anchor="middle"{fam(line)}>{esc(line)}</text>')
    p.append('</svg>')
    return '\n'.join(p)

# ------------------------------------------------------------- draw.io out
def to_drawio(sh, W, H, title, sub, footer):
    c = ['<mxfile host="app.diagrams.net" type="device">',
         '<diagram id="p2pipeline" name="Training to Inference">',
         f'<mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" guides="1" tooltips="1" '
         f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{W}" '
         f'pageHeight="{H}" math="0" shadow="0"><root>',
         '<mxCell id="0"/><mxCell id="1" parent="0"/>']
    n = [1000]
    def nid():
        n[0] += 1; return f'p{n[0]}'
    def cell(val, style, x, y, w, h, i=None):
        c.append(f'<mxCell id="{i or nid()}" value="{esc(val)}" style="{style}" vertex="1" '
                 f'parent="1"><mxGeometry x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" '
                 f'height="{h:.0f}" as="geometry"/></mxCell>')
    F = 'fontFamily=Tahoma;'
    cell(f'<b>{esc(title)}</b>', f'text;html=1;fontSize=29;align=center;fontColor={INK};{F}',
         0, 40, W, 36)
    cell(f'<i>{esc(sub)}</i>', f'text;html=1;fontSize=12;align=center;fontColor={MUTED};{F}',
         0, 78, W, 20)
    for l in sh.lanes:
        if not l.badge:
            continue
        cell('', f'rounded=1;arcSize=6;html=1;fillColor={PANEL};strokeColor={PANEL_S};'
                 f'container=0;', l.x, l.y, l.w, l.h)
        cell(f'<b>{l.badge}</b>', f'ellipse;html=1;fillColor={INK};strokeColor=none;'
             f'fontColor=#FFFFFF;fontSize=14;{F}', l.x - 61, l.y + 19, 30, 30)
        cell(f'<b>{esc(l.label)}</b>', f'text;html=1;horizontal=0;align=center;fontSize=11;'
             f'fontColor={MUTED};{F}', l.x - 104, l.y, 40, l.h)
    for nd in sh.nodes():
        if nd.kind == 'pill':
            cell(f'<b>{esc(nd.text)}</b>',
                 f'rounded=1;arcSize=50;html=1;fillColor={nd.fill};strokeColor=none;'
                 f'fontColor=#FFFFFF;fontSize=13;{F}', nd.x, nd.y, nd.w, nd.h, nd.id)
        elif nd.kind == 'hdr':
            cell(f'<b>{esc(nd.text)}</b>',
                 f'rounded=1;arcSize=18;html=1;fillColor={nd.fill};strokeColor=none;'
                 f'fontColor=#FFFFFF;fontSize=11;{F}', nd.x, nd.y, nd.w, nd.h, nd.id)
        elif nd.kind == 'diamond':
            cell(esc(nd.text), f'rhombus;whiteSpace=wrap;html=1;fillColor=#FFFFFF;'
                 f'strokeColor={ACC};strokeWidth=1.6;fontSize=12;fontColor={ACC};{F}',
                 nd.x, nd.y, nd.w, nd.h, nd.id)
        else:
            st = C[nd.style]
            v = ''
            if nd.sid:
                v += f'<font color="{SID}" style="font-size:9px">{esc(nd.sid)}</font><br>'
            v += f'<b>{esc(" ".join(nd.tl))}</b>'
            if nd.dl:
                v += (f'<br><font color="{MUTED}" style="font-size:10px">'
                      f'{esc(" ".join(nd.dl))}</font>')
            cell(v, f'rounded=1;arcSize=9;whiteSpace=wrap;html=1;fillColor={st["fill"]};'
                    f'strokeColor={st["stroke"]};strokeWidth=1.6;align=center;'
                    f'verticalAlign=middle;fontSize=13;fontColor={st["title"]};{F}',
                 nd.x, nd.y, nd.w, nd.h, nd.id)
    EX = {'TB': (0.5, 1, 0.5, 0), 'BT': (0.5, 0, 0.5, 1),
          'RL': (1, 0.5, 0, 0.5), 'LR': (0, 0.5, 1, 0.5)}
    for e in sh.edges:
        ex, ey, nx, ny = EX[e['side']]
        dash = 'dashed=1;dashPattern=7 5;' if e['dashed'] else 'dashed=0;'
        c.append(f'<mxCell id="{nid()}" value="{esc(e["label"])}" '
                 f'style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;'
                 f'strokeColor={e["color"]};strokeWidth=1.7;{dash}exitX={ex};exitY={ey};'
                 f'entryX={nx};entryY={ny};fontSize=10;fontStyle=2;fontColor={e["color"]};'
                 f'labelBackgroundColor=#FFFFFF;{F}" edge="1" parent="1" '
                 f'source="{e["a"].id}" target="{e["b"].id}">'
                 f'<mxGeometry relative="1" as="geometry"/></mxCell>')
    cell('<i>' + '<br>'.join(esc(f) for f in footer) + '</i>',
         f'text;html=1;fontSize=10;align=center;fontColor={MUTED};{F}',
         0, H - 62, W, 50)
    c.append('</root></mxGraphModel></diagram></mxfile>')
    return '\n'.join(c)


# ==========================================================================
#  CONTENT
# ==========================================================================
W, LX, LW = 1460, 126, 1300
TOP, LANE_GAP = 112, 34
S, P, D, HH = Step, Pill, Dia, Hdr
sh = Sheet()

# ---- 1  DATA -------------------------------------------------------------
start = P('start', 'A RECORDING SESSION', '#3B4750', 268, 44, 12)
s1 = S('s1', 'S1', 'Record Known Behaviour',
       'the patch is worn while nine known things happen to it, from lying still to a '
       'full pull; 81 recordings in all', w=460)
s2 = S('s2', 'S2', 'Sort into Four Levels',
       'normal, someone touching it, the dressing peeling, the tube being pulled', w=460)
stop1 = P('stop1', 'STOP - set the recording aside', ACC, 400, 42, 12)
d1 = D('d1', 'is the recording usable ?', 330, 90)
s0 = S('s0', 'S0', 'Check a New Recording',
       'does the patch lift as far as the design says it should, before this recording '
       'is allowed to teach anything', 'warn', 460)
s3 = S('s3', 'S3', 'Remember Which Data This Came From',
       'so the system can tell later whether the model still matches the data behind it',
       w=460)
lane1 = Lane(1, 'LEARNING FROM DATA', [[start, s1, s2], [stop1, d1], [s0, s3]])

# ---- 2  WHAT THE MODEL SEES ----------------------------------------------
s4 = S('s4', 'S4', 'Cancel the Slow Drift',
       'sweat and body heat move the reading over hours; only a sudden change means '
       'something is happening', w=470)
s5 = S('s5', 'S5', 'Describe Each Moment',
       'how far each of the 25 pads moved, how many moved together, and how deep', w=470)
lane2 = Lane(2, 'WHAT THE MODEL SEES', [[s4, s5]])

# ---- 3  MEASURE ----------------------------------------------------------
hA = HH('hA', 'PER RECORDING', 'c1', 400)
hB = HH('hB', 'PER REAL EVENT', 'c2', 400)
hC = HH('hC', 'ALARM BURDEN', 'c3', 400)
a1 = S('a1', 'S6', 'Test on a Recording It Never Saw',
       'learn from the other 80, then judge the one held back, and repeat for all 81',
       'c1', 400)
a2 = S('a2', 'S7', 'How Often the Clip Is Called Right',
       '79 of 81, and the honest range around that is 91 to 99 per cent', 'c1', 400)
b1 = S('b1', 'S8', 'Judge Every Moment Blind',
       'each moment is scored by a model that never learned from its own recording',
       'c2', 400)
b2 = S('b2', 'S9', 'How Many Real Events Are Caught',
       'every one of them, and the warning comes about six seconds in', 'c2', 400)
c1 = S('c1', 'S10', 'Try Every Alarm Setting',
       'how many agreeing moments before it sounds, and how long it keeps sounding',
       'c3', 400)
c2 = S('c2', 'S11', 'Choose What a Ward Can Live With',
       'catches every event, at the cost of roughly eight false alarms an hour', 'c3', 400)
lane3 = Lane(3, 'HOW WELL IT WORKS', [[hA, hB, hC], [a1, b1, c1], [a2, b2, c2]])

# ---- 4  RELEASE ----------------------------------------------------------
s12 = S('s12', 'S12', 'Write the Measured Numbers Down',
        'one report, and it is the only place any figure may be quoted from', w=660)
d2 = D('d2', 'same numbers, everything still passes ?', 380, 96)
stop2 = P('stop2', 'STOP - then the work is wrong, not the report', ACC, 470, 42, 12)
lane4 = Lane(4, 'BEFORE IT IS ALLOWED OUT', [[s12], [stop2, d2]])

# ---- 5  MODEL ------------------------------------------------------------
s13 = S('s13', 'S13', 'Train the Model That Will Be Used',
        'a gradient-boosted decision-tree model, learning from every recording at once',
        w=470)
s14 = S('s14', 'S14', 'Seal It',
        'stored with a fingerprint, so a swapped or damaged model is refused rather than '
        'quietly used', 'warn', 470)
lane5 = Lane(5, 'THE MODEL THAT SHIPS', [[s13, s14]])

# ---- 6  SERVING ----------------------------------------------------------
r1 = S('r1', 'S15', 'A Reading Arrives',
       'all 25 pads, about twice a second', w=400)
r2 = S('r2', 'S16', 'Distrust a Broken Reading',
       'if the sensor drops out, hold the last level rather than report that all is well',
       w=400)
r3 = S('r3', 'S17', 'Cancel the Drift',
       'exactly as it was done while learning', w=400)
r4 = S('r4', 'S18', 'Describe the Moment',
       'exactly the same description as while learning', w=400)
r5 = S('r5', 'S19', 'Decide What Is Happening',
       'too small to matter, a touch, peeling, or a pull, with a risk score alongside',
       w=400)
r6 = S('r6', 'S20', 'Wait for Agreement',
       'one odd moment is not an alarm; several in a row is', w=400)
lane6 = Lane(6, 'AT THE BEDSIDE', [[r1, r2, r3], [r4, r5, r6]])

out_bar = P('out', 'OUTPUT     how serious it is,  how risky,  and where the patch is lifting',
            H1, 1020, 50, 13)
lane_out = Lane('', '', [[out_bar]])
lane_out.PAD = 0

sh.lanes = [lane1, lane2, lane3, lane4, lane5, lane6, lane_out]
y = TOP
for l in sh.lanes:
    y += l.place(LX, y, LW) + LANE_GAP
H = int(y - LANE_GAP + 108)

E = sh.edge
E(start, s1, 'RL');   E(s1, s2, 'RL');   E(s2, d1, 'TB')
E(d1, stop1, 'LR', 'no', ACC);  E(d1, s3, 'TB', 'yes')
E(s3, s0, 'LR', 'at the same time', FEED, dashed=True)
E(s0, d2, 'TB', 'what the check found', FEED, dashed=True, via=108)
E(s3, s4, 'TB');      E(s4, s5, 'RL')
E(s5, hA, 'TB'); E(s5, hB, 'TB'); E(s5, hC, 'TB')
E(hA, a1, 'TB'); E(hB, b1, 'TB'); E(hC, c1, 'TB')
E(a1, a2, 'TB'); E(b1, b2, 'TB'); E(c1, c2, 'TB')
E(a2, s12, 'TB', 'how often a clip is right', H1, bx=s12.x + 130, mid=s12.y - 46)
E(b2, s12, 'TB', 'how many events are caught', H2)
E(c2, s12, 'TB', 'the chosen alarm setting', H3, bx=s12.r - 130, mid=s12.y - 46)
E(s12, d2, 'TB')
E(d2, stop2, 'LR', 'no', ACC);  E(d2, s13, 'TB', 'yes')
E(s13, s14, 'RL');    E(s14, r1, 'TB')
E(r1, r2, 'RL');      E(r2, r3, 'RL');   E(r3, r4, 'TB')
E(r4, r5, 'RL');      E(r5, r6, 'RL');   E(r6, out_bar, 'TB')

TITLE = 'How the Smart Dressing Learns, and How It Decides'
SUB = ('each block says what that stage does; the labels on the arrows say what is handed '
       'to the next stage')
FOOT = [
 'At the bedside the drift is cancelled and each moment described exactly as it was during learning, which is why the measured figures describe what a ward would actually see.',
 'Measured on one round of bench recordings with a single patch mounting. The patch does not yet lift as far as the design requires, and a sideways pull does not lift it at all.',
]

here = os.path.dirname(os.path.abspath(__file__))
out = os.path.join(here, '..', 'docs') if os.path.basename(here) == 'scripts' else here
os.makedirs(out, exist_ok=True)
svgp = os.path.join(out, 'Project2_Pipeline_Diagram.svg')
open(svgp, 'w', encoding='utf-8').write(to_svg(sh, W, H, TITLE, SUB, FOOT))
open(os.path.join(out, 'Project2_Pipeline_Diagram.drawio'), 'w', encoding='utf-8').write(
    to_drawio(sh, W, H, TITLE, SUB, FOOT))
try:
    import cairosvg
    cairosvg.svg2png(url=svgp, write_to=os.path.join(out, 'Project2_Pipeline_Diagram.png'),
                     output_width=2200)
except ImportError:
    print('cairosvg missing - PNG skipped')
print(f'{W} x {H}  nodes={len(sh.nodes())} edges={len(sh.edges)}')
