"""Move every via that sits inside a surface-mount pad to a free spot just next to that pad.

A via inside a pad lets solder run down the hole during reflow, which starves the joint. This script finds
those vias, picks the nearest position that keeps 0.16 mm to everything else on both outer layers and is not
underneath any component, moves the via there, and adds a short top-layer stub (pad -> via) and bottom-layer stub (old spot -> via).
The two ground vias in the AD8232 centre pad are left alone (thermal-pad vias are the normal exception).

Run with KiCad's python, then layout/refill.py, then DRC:
  .../python3 layout/move_vias_out_of_pads.py LeoPatch_v2.kicad_pcb
"""
import math, sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
MM, mm = pcbnew.FromMM, pcbnew.ToMM
F, B = pcbnew.F_Cu, pcbnew.B_Cu
CL, VR, STUB_W = 0.16, 0.225, 0.2          # clearance to keep, via radius, stub width
SKIP_FOOTPRINTS = {"U201"}

pads, tracks, vias = [], [], []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        pads.append(dict(ref=f.GetReference(), num=p.GetNumber(), net=p.GetNetname(), obj=p,
                         rect=(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())),
                         f=p.IsOnLayer(F), b=p.IsOnLayer(B), smd=p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD))
for t in b.GetTracks():
    if t.Type() == pcbnew.PCB_VIA_T:
        vias.append(dict(obj=t, net=t.GetNetname(), x=mm(t.GetPosition().x), y=mm(t.GetPosition().y)))
    else:
        tracks.append(dict(net=t.GetNetname(), layer=t.GetLayer(), w=mm(t.GetWidth()),
                           a=(mm(t.GetStart().x), mm(t.GetStart().y)), b=(mm(t.GetEnd().x), mm(t.GetEnd().y))))


# one box per component around all its pads: a moved via must not end up under a component body
boxes = {}
for p in pads:
    if p["smd"]:
        r0 = boxes.get(p["ref"], p["rect"]); r1 = p["rect"]
        boxes[p["ref"]] = (min(r0[0], r1[0]), min(r0[1], r1[1]), max(r0[2], r1[2]), max(r0[3], r1[3]))


def d_rect(x, y, r):
    dx = max(r[0] - x, 0, x - r[2]); dy = max(r[1] - y, 0, y - r[3])
    return math.hypot(dx, dy)


def d_seg(x, y, a, c):
    vx, vy = c[0] - a[0], c[1] - a[1]; L2 = vx * vx + vy * vy
    u = 0 if L2 == 0 else max(0, min(1, ((x - a[0]) * vx + (y - a[1]) * vy) / L2))
    return math.hypot(x - (a[0] + u * vx), y - (a[1] + u * vy))


def samples(a, c, step=0.04):
    n = max(1, int(math.hypot(c[0] - a[0], c[1] - a[1]) / step))
    return [(a[0] + (c[0] - a[0]) * i / n, a[1] + (c[1] - a[1]) * i / n) for i in range(n + 1)]


def copper_ok(x, y, radius, net, layers, me=None, own_pad=None):
    """True if a round piece of copper (radius) at x,y on the given layers clears everything of other nets."""
    for p in pads:
        if p is own_pad or not ((p["f"] and F in layers) or (p["b"] and B in layers)):
            continue
        need = radius + (CL if p["net"] != net else (0.1 if radius == VR else -1))   # no new via-in-pad on the same net
        if d_rect(x, y, p["rect"]) < need:
            return False
    for t in tracks:
        if t["net"] != net and t["layer"] in layers and d_seg(x, y, t["a"], t["b"]) < radius + t["w"] / 2 + CL:
            return False
    for v in vias:
        if v is me:
            continue
        if math.hypot(x - v["x"], y - v["y"]) < (radius + VR + CL if v["net"] != net else (0.5 if radius == VR else 0)):
            return False
    return 101.0 < x < 169.0 and 101.0 < y < 144.0


def add_track(net, layer, a, c):
    t = pcbnew.PCB_TRACK(b)
    t.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1]))); t.SetEnd(pcbnew.VECTOR2I(MM(c[0]), MM(c[1])))
    t.SetWidth(MM(STUB_W)); t.SetLayer(layer); t.SetNet(b.FindNet(net)); b.Add(t)
    tracks.append(dict(net=net, layer=layer, w=STUB_W, a=a, b=c))


moved, stuck, leftovers = 0, [], []
for v in vias:
    hit = [p for p in pads if p["smd"] and p["f"] and p["ref"] not in SKIP_FOOTPRINTS
           and d_rect(v["x"], v["y"], p["rect"]) < VR - 0.02]          # via copper overlaps the pad
    hit = [p for p in hit if p["net"] == v["net"]]
    if not hit:
        continue
    pad = hit[0]; r = pad["rect"]; p0 = (v["x"], v["y"])
    cands = []
    for off in (0.45, 0.55, 0.7, 0.9, 1.1, 1.4, 1.8):
        x0, y0, x1, y1 = r[0] - off, r[1] - off, r[2] + off, r[3] + off
        n = int((x1 - x0) / 0.05); m = int((y1 - y0) / 0.05)
        ring = [(x0 + i * 0.05, yy) for i in range(n + 1) for yy in (y0, y1)] + [(xx, y0 + j * 0.05) for j in range(m + 1) for xx in (x0, x1)]
        cands += sorted(ring, key=lambda c: math.hypot(c[0] - p0[0], c[1] - p0[1]) + off)
    best = None
    for c in cands:
        if not copper_ok(c[0], c[1], VR, v["net"], (F, B), me=v, own_pad=pad):
            continue
        if d_rect(c[0], c[1], r) < VR + 0.2:                           # leave a solder-mask dam to the pad
            continue
        if any(d_rect(c[0], c[1], box) < VR + 0.05 for box in boxes.values()):   # not under any component
            continue
        anchor = (min(max(c[0], r[0] + 0.15), r[2] - 0.15), min(max(c[1], r[1] + 0.15), r[3] - 0.15))
        if all(copper_ok(x, y, STUB_W / 2, v["net"], (F,), me=v, own_pad=pad) for x, y in samples(anchor, c)) and \
           all(copper_ok(x, y, STUB_W / 2, v["net"], (B,), me=v) for x, y in samples(p0, c)):
            best = (c, anchor); break
    if best is None:
        stuck.append(f'{pad["ref"]}.{pad["num"]} {v["net"]} at {p0}')
        continue
    c, anchor = best
    c = (round(c[0], 3), round(c[1], 3))
    v["obj"].SetPosition(pcbnew.VECTOR2I(MM(c[0]), MM(c[1]))); v["x"], v["y"] = c
    add_track(v["net"], F, anchor, c); add_track(v["net"], B, p0, c)
    # a top-layer stub that only led from the pad to the old via position would now end in mid-air
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() == F and t.GetNetname() == v["net"] and d_rect(p0[0], p0[1], r) > 0.01:
            ends = [(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]
            for e, o in (ends, ends[::-1]):
                if math.hypot(e[0] - p0[0], e[1] - p0[1]) < 0.02 and d_rect(o[0], o[1], r) < 0.01 and t not in leftovers:
                    leftovers.append(t)
    moved += 1
    print(f'{pad["ref"]}.{pad["num"]:3s} {v["net"]:28s} {p0} -> {c}')

for t in leftovers:      # removals last: KiCad 9 python lookups break once something is removed
    b.Remove(t)
b.Save(sys.argv[1])
print("moved", moved, "| could not move:", stuck)
