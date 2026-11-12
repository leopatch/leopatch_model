"""Phase 2 (KiCad 9 python on the PC): load the placed board, add router tracks/vias, planes, pours,
antenna keep-out, fix the BM20BC 3D model transform, fill zones and save."""
import wx
app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import os, json
import pcbnew
from pcbnew import FromMM as MM

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
PCB = os.path.join(PRJ, "LeoPatch_v3.kicad_pcb")
R = json.load(open(os.path.join(HERE, "routes.json")))
b = pcbnew.LoadBoard(PCB)

for t in list(b.GetTracks()):
    b.Delete(t)
for z in list(b.Zones()):
    b.Delete(z)

def net(name):
    n = b.FindNet(name)
    if n is None:
        raise RuntimeError("no net " + name)
    return n

L = {'F': pcbnew.F_Cu, 'B': pcbnew.B_Cu}
for t in R['tracks']:
    if abs(t['x1'] - t['x2']) < 1e-6 and abs(t['y1'] - t['y2']) < 1e-6:
        continue
    tr = pcbnew.PCB_TRACK(b)
    tr.SetStart(pcbnew.VECTOR2I(MM(t['x1']), MM(t['y1']))); tr.SetEnd(pcbnew.VECTOR2I(MM(t['x2']), MM(t['y2'])))
    tr.SetWidth(MM(t['w'])); tr.SetLayer(L[t['layer']]); tr.SetNet(net(t['net'])); b.Add(tr)
seen = set()
for v in R['vias']:
    k = (round(v['x'], 3), round(v['y'], 3))
    if k in seen:
        continue
    seen.add(k)
    via = pcbnew.PCB_VIA(b)
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetPosition(pcbnew.VECTOR2I(MM(v['x']), MM(v['y'])))
    via.SetWidth(MM(0.45)); via.SetDrill(MM(0.2)); via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetNet(net(v['net'])); b.Add(via)

X0, Y0, X1, Y1 = 100.0, 100.0, 170.0, 145.0
def outline(z, x0, y0, x1, y1):
    o = z.Outline(); o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(MM(x), MM(y))

def pour(layer, netname, prio):
    z = pcbnew.ZONE(b)
    z.SetLayer(layer); z.SetNet(net(netname)); z.SetAssignedPriority(prio)
    outline(z, X0, Y0, X1, Y1)
    z.SetLocalClearance(MM(0.2)); z.SetMinThickness(MM(0.2))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.25)); z.SetThermalReliefSpokeWidth(MM(0.3))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetZoneName(f"{netname}_{b.GetLayerName(layer)}")
    b.Add(z)

pour(pcbnew.In1_Cu, "GND", 0)
pour(pcbnew.In2_Cu, "+3V3", 0)
pour(pcbnew.F_Cu, "GND", 0)
pour(pcbnew.B_Cu, "GND", 0)

# antenna keep-out: no copper on any layer under / around the BM20BC chip antenna
ka = pcbnew.ZONE(b)
ka.SetIsRuleArea(True)
ls = pcbnew.LSET(); [ls.AddLayer(l) for l in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)]
ka.SetLayerSet(ls)
outline(ka, 143.3, 99.0, 156.8, 106.6)
ka.SetDoNotAllowCopperPour(True); ka.SetDoNotAllowTracks(True); ka.SetDoNotAllowVias(True)
ka.SetDoNotAllowPads(False); ka.SetDoNotAllowFootprints(False)
ka.SetZoneName("ANTENNA_KEEPOUT")
b.Add(ka)

# BM20BC STEP: model is Y-up, length along +X (shield end at x=0), width along Z
for f in b.GetFootprints():
    if f.GetReference() == "U1":
        for m in f.Models():
            m.m_Rotation = pcbnew.VECTOR3D(90, 0, -90)
            m.m_Offset = pcbnew.VECTOR3D(0, -5.0, 0)

nc = b.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
nc.SetTrackWidth(MM(0.2))

# SW301: the two pin-1 pads are not internally tied in the footprint -> tie them on F.Cu
sw = [f for f in b.GetFootprints() if f.GetReference() == "SW301"][0]
p1 = [p for p in sw.Pads() if p.GetNumber() == "1"]
if len(p1) == 2:
    tr = pcbnew.PCB_TRACK(b); tr.SetStart(p1[0].GetPosition()); tr.SetEnd(p1[1].GetPosition())
    tr.SetWidth(MM(0.3)); tr.SetLayer(pcbnew.F_Cu); tr.SetNet(p1[0].GetNet()); b.Add(tr)

# silkscreen tidy-up: passive refs go to the fab layer (dense board), the rest get small text
for f in b.GetFootprints():
    ref = f.Reference(); ref.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8))); ref.SetTextThickness(MM(0.12))
    if f.GetReference()[0] in "RC" or f.GetReference() in ("SW301", "U102", "J102", "D102"):
        ref.SetLayer(pcbnew.F_Fab)
for rname, dx, dy in (("J101", 0, 4.6), ("JP101", 3.6, 0)):
    f = [q for q in b.GetFootprints() if q.GetReference() == rname][0]
    f.Reference().SetPosition(f.GetPosition() + pcbnew.VECTOR2I(MM(dx), MM(dy)))
# function labels
def silk(txt, x, y, size=1.0, angle=0):
    t = pcbnew.PCB_TEXT(b); t.SetTextAngleDegrees(angle); t.SetText(txt); t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y))); t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size))); t.SetTextThickness(MM(0.15))
    b.Add(t)
for t in [d for d in b.Drawings() if d.GetClass() == "PCB_TEXT"]:
    b.Delete(t)
for txt, x in (("PASS", 154.0), ("CHECK", 157.3), ("FAIL", 160.6)):
    silk(txt, x, 126.6, 0.8, 90)
silk("EXPORT", 163.0, 132.4, 1.0)
silk("LeoPatch v2", 140.0, 142.6, 1.2)

# drop signal vias that only have copper on one layer (router start points that were not needed)
import math
def seg_dist(px, py, t):
    ax, ay, bx, by = t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y
    vx, vy = bx - ax, by - ay; L2 = vx * vx + vy * vy
    u = 0 if L2 == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(px - (ax + u * vx), py - (ay + u * vy))
plane = {b.FindNet("GND").GetNetCode(), b.FindNet("+3V3").GetNetCode()}
trk = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
pads = [p for f in b.GetFootprints() for p in f.Pads()]
for v in [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]:
    if v.GetNetCode() in plane:
        continue
    p = v.GetPosition(); layers = set()
    for t in trk:
        if t.GetNetCode() == v.GetNetCode() and seg_dist(p.x, p.y, t) < MM(0.2):
            layers.add(t.GetLayer())
    for q in pads:
        if q.GetNetCode() == v.GetNetCode() and q.HitTest(p):
            layers.update(l for l in (pcbnew.F_Cu, pcbnew.B_Cu) if q.IsOnLayer(l))
    if len(layers) < 2:
        print("drop dangling via", v.GetNetname(), pcbnew.ToMM(p.x), pcbnew.ToMM(p.y))
        touching = [t for t in trk if t.GetNetCode() == v.GetNetCode() and
                    (t.GetStart() == p or t.GetEnd() == p)]
        if len(touching) == 1:          # the fan-out stub that only led to this via
            b.Delete(touching[0]); trk.remove(touching[0])
        b.Delete(v)

# prune dangling track ends left by the grid router (repeat until stable)
while True:
    trk = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
    vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
    def anchored(t, p):
        for o in trk:
            if o is not t and o.GetNetCode() == t.GetNetCode() and o.GetLayer() == t.GetLayer() and seg_dist(p.x, p.y, o) < 1000:
                return True
        for v in vias:
            if v.GetNetCode() == t.GetNetCode() and (v.GetPosition() - p).EuclideanNorm() <= MM(0.225):
                return True
        for q in pads:
            if q.GetNetCode() == t.GetNetCode() and q.IsOnLayer(t.GetLayer()) and q.HitTest(p, t.GetWidth() // 2):
                return True
        return False
    dead = [t for t in trk if t.GetNetCode() not in plane and not (anchored(t, t.GetStart()) and anchored(t, t.GetEnd()))]
    if not dead:
        break
    for t in dead:
        print("prune dangling track", t.GetNetname(), pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y))
        b.Delete(t)

pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(PCB)
print("tracks", len([t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]),
      "vias", len([t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]), "zones", len(list(b.Zones())))
