"""LeoPatch v4 board, step 1 (placement). KiCad python:
  PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
  kicad-cli sch export netlist --format kicadxml -o net.xml LeoPatch_v4.kicad_sch
  $PY layout/build_v4_pcb.py LeoPatch_v4.kicad_pcb net.xml
Then dump_geom.py -> route_new.py -> apply_new_routes.py -> refill.py -> DRC.

1. Rips up every track of the v3 MAX30003 front end (the v3 hand routing had shorts) - its nets, +1V8, and the GND / +3V3
   stubs and vias inside its area. Parts stay, a few nudged apart (courtyard overlaps in v3).
2. Board 26 mm taller (70 x 71 mm): bottom edge, corner arcs and the four copper zones move down.
3. Every pad net is set from the netlist (v3's module pads still had the old AD8232 nets).
4. MAX30003 jack J201 turns to face the left edge; mounting hole H4 moves to the new bottom-right corner, H5 is added
   bottom-left.
5. The AD8232 block of LeoPatch v2 (DRC-clean there) is copied 26 mm lower with all its internal tracks and vias:
   U201->U601, R2xx->R6xx, C2xx->C6xx, J201->J601, J202->J602, TP3->TP601. Its links to the module are routed new.
"""
import re, sys, uuid
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
MM, T = pcbnew.FromMM, pcbnew.ToMM
P = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
DY = 26.0                                   # AD8232 block shift and board growth
OLD_BOTTOM, NEW_BOTTOM = 145.0, 145.0 + DY
FPLIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
ROOT = "7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90"
SHEET_B = "1d6c4f87-bd9a-573e-bd57-1bf4989b18b5"          # ECG AD8232 sheet (add_ad8232_sheet.py)
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c004")
assert b.FindFootprintByReference("U601") is None, "already built"

xml = open(sys.argv[2]).read()
VALUE = dict(re.findall(r'<comp ref="([^"]+)">\s*<value>([^<]*)</value>', xml))
PIN_NET = {}
for name, body in re.findall(r'<net code="\d+" name="([^"]+)"[^>]*>(.*?)</net>', xml, re.S):
    for ref, pin in re.findall(r'ref="([^"]+)" pin="([^"]+)"', body):
        PIN_NET[(ref, pin)] = name


def net(name):
    n = b.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(b, name); b.Add(n)
    return n


# ---------------------------------------------------------------- 1. rip up the v3 MAX30003 routing
MAX_BOX = (119.5, 117.8, 141.0, 137.6)
inbox = lambda x, y, bx: bx[0] <= x <= bx[2] and bx[1] <= y <= bx[3]
doomed = []
for t in b.GetTracks():
    n = t.GetNetname()
    pts = [t.GetPosition()] if t.GetClass() == "PCB_VIA" else [t.GetStart(), t.GetEnd()]
    if n.startswith("/ECG front end/") or n.startswith("ECG_") or n == "+1V8":
        doomed.append(t)
    elif n in ("GND", "+3V3") and all(inbox(T(p.x), T(p.y), MAX_BOX) for p in pts):
        doomed.append(t)
for d in doomed:
    b.Remove(d)
print("ripped up", len(doomed), "tracks/vias")

# ---------------------------------------------------------------- 2. taller board
for d in b.GetDrawings():
    if d.GetLayer() != pcbnew.Edge_Cuts:
        continue
    s, e = d.GetStart(), d.GetEnd()
    if d.GetShapeStr() == "Arc":
        if T(s.y) >= OLD_BOTTOM - 1.01 and T(e.y) >= OLD_BOTTOM - 1.01:
            d.Move(P(0, DY))
    elif T(s.y) >= OLD_BOTTOM - 0.01 and T(e.y) >= OLD_BOTTOM - 0.01:
        d.Move(P(0, DY))
    else:
        for setter, p in ((d.SetStart, s), (d.SetEnd, e)):
            if abs(T(p.y) - (OLD_BOTTOM - 1.0)) < 0.01:
                setter(P(T(p.x), NEW_BOTTOM - 1.0))
for z in b.Zones():
    o = z.Outline()
    for i in range(o.TotalVertices()):
        v = o.CVertex(i)
        if abs(T(v.y) - OLD_BOTTOM) < 0.01:
            o.SetVertex(i, P(T(v.x), NEW_BOTTOM))

# ---------------------------------------------------------------- 3. pad nets from the netlist
for f in b.GetFootprints():
    ref = f.GetReference()
    for p in f.Pads():
        key = (ref, p.GetNumber())
        if key in PIN_NET:
            if PIN_NET[key].startswith("unconnected-") and p.GetNetname().startswith("unconnected-"):
                continue                                  # keep KiCad's own name for unconnected pins
            p.SetNet(net(PIN_NET[key]))
    if ref in VALUE and f.GetValue() != VALUE[ref]:
        f.SetValue(VALUE[ref])

# ---------------------------------------------------------------- 4. moves
def move(ref, x, y, rot=None):
    f = b.FindFootprintByReference(ref)
    if rot is not None:
        f.SetOrientationDegrees(rot)
    f.SetPosition(P(x, y))
    return f


j = move("J201", 107.5, 133.5, 270)                      # MAX30003 jack, plug enters from the left edge
r = j.GetBoundingBox(False, False)
print("J201 bbox x %.1f-%.1f y %.1f-%.1f" % (T(r.GetLeft()), T(r.GetRight()), T(r.GetTop()), T(r.GetBottom())))
move("C211", 140.2, 129.4)                               # off the U202 courtyard
move("C212", 135.2, 132.9)
move("X201", 133.6, 124.5)                               # off C203
move("H4", 166.0, 167.0)
h5 = pcbnew.FOOTPRINT(b.FindFootprintByReference("H4"))
h5.SetReference("H5"); b.Add(h5); h5.SetPosition(P(104.0, 147.5))

# silkscreen
for d in list(b.GetDrawings()):
    if d.GetClass() == "PCB_TEXT" and d.GetText() == "LeoPatch v2":
        d.SetText("LeoPatch v4"); d.SetPosition(P(155.0, 160.0))
    elif d.GetClass() == "PCB_TEXT" and d.GetText() == "MAX30003":
        d.SetPosition(P(108.0, 141.0))
u = b.FindFootprintByReference("U201").Reference(); u.SetPosition(P(122.6, 126.9)); u.SetTextAngle(pcbnew.EDA_ANGLE(0, pcbnew.DEGREES_T))
# C204's GND pad is boxed in by tracks (one thermal spoke); it has its own plane via, so pour it solid
b.FindFootprintByReference("C204").FindPadByNumber("2").SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)


def silk(txt, x, y, size=1.0):
    t = pcbnew.PCB_TEXT(b); t.SetText(txt); t.SetLayer(pcbnew.F_SilkS); t.SetPosition(P(x, y))
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size))); t.SetTextThickness(MM(0.15)); b.Add(t)


silk("AD8232", 107.0, 150.6)
silk("ECG", 143.5, 152.0, 0.8)                         # TP601 = AD8232 output

# ---------------------------------------------------------------- 4b. flash U2 -> 208-mil SOIC-8
# GD25WQ64ESIGR is the 208-mil SOP-8 (the S); v2/v3 had the 150-mil SOIC-8 footprint. The wider part sits 0.6 mm
# further left (its right pads would touch C1/C2), C4 moves 1 mm left, and the flash stubs near it are ripped up
# for route_new.py to reconnect.
old = b.FindFootprintByReference("U2")
u2nets = {p.GetNetname() for p in old.Pads()} - {"GND", "+3V3"}
FLASH_BOX = (131.0, 108.6, 142.3, 115.6)
rip = []
for t in b.GetTracks():
    n = t.GetNetname()
    pts = [t.GetPosition()] if t.GetClass() == "PCB_VIA" else [t.GetStart(), t.GetEnd()]
    ins = [inbox(T(p.x), T(p.y), FLASH_BOX) for p in pts]
    if (n in u2nets and any(ins)) or (n in ("GND", "+3V3") and all(ins)):
        rip.append(t)
for t in rip:
    b.Remove(t)
nf = pcbnew.FootprintLoad(FPLIB + "Package_SO.pretty", "SOIC-8_5.3x5.3mm_P1.27mm")
nf.SetFPID(pcbnew.LIB_ID("Package_SO", "SOIC-8_5.3x5.3mm_P1.27mm"))
nf.SetReference("U2"); nf.SetValue(old.GetValue()); nf.SetPath(old.GetPath())
nf.SetSheetname(old.GetSheetname()); nf.SetSheetfile(old.GetSheetfile()); nf.SetAttributes(old.GetAttributes())
b.Add(nf); nf.SetOrientationDegrees(180); nf.SetPosition(P(137.4, 111.6))
nr, orf = nf.Reference(), old.Reference()
nr.SetLayer(orf.GetLayer()); nr.SetTextSize(orf.GetTextSize()); nr.SetTextThickness(orf.GetTextThickness())
nr.SetPosition(P(T(orf.GetPosition().x) - 0.6, T(orf.GetPosition().y) + 0.5)); nr.SetTextAngle(orf.GetTextAngle())
for p in nf.Pads():
    p.SetNet(net(PIN_NET[("U2", p.GetNumber())]))
b.Remove(old)
move("C4", 131.9, 113.3)
print("U2 -> SOIC-8 208 mil; ripped", len(rip), "flash tracks/vias")

# ---------------------------------------------------------------- 4c. MAX30003 input filter (datasheet Figure 11)
# 1k pulse-proof 1206 resistors (R201 LA->ECGP, R202 RA->ECGN), C201 10 nF across ECGP-ECGN right under the pins,
# C213 / C214 1 nF ECGP / ECGN -> GND. All MAX30003 tracks were ripped in step 1, the router wires these.
MAX_SHEET = "/f0d23f52-e0d2-5d2d-be47-e1184c1697c7/"
NS5 = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c005")


def new_fp(lib, name, ref, value, x, y, rot, path, like=None):
    f = pcbnew.FootprintLoad(FPLIB + lib + ".pretty", name)
    f.SetFPID(pcbnew.LIB_ID(lib, name)); f.SetReference(ref); f.SetValue(value)
    f.SetPath(pcbnew.KIID_PATH(path)); f.SetSheetname("ECG front end"); f.SetSheetfile("LeoPatch_ECG.kicad_sch")
    if like is not None:
        f.SetAttributes(like.GetAttributes())
        lr, fr = like.Reference(), f.Reference()
        fr.SetLayer(lr.GetLayer()); fr.SetTextSize(lr.GetTextSize()); fr.SetTextThickness(lr.GetTextThickness())
        fr.SetVisible(lr.IsVisible())
    b.Add(f); f.SetOrientationDegrees(rot); f.SetPosition(P(x, y))
    for p in f.Pads():
        if (ref, p.GetNumber()) in PIN_NET:
            p.SetNet(net(PIN_NET[(ref, p.GetNumber())]))
    return f


for ref, x in (("R201", 126.0), ("R202", 132.5)):
    old = b.FindFootprintByReference(ref)
    new_fp("Resistor_SMD", "R_1206_3216Metric", ref, old.GetValue(), x, 137.5, 90, old.GetPath().AsString(), like=old)
    b.Remove(old)
move("C201", 129.25, 134.6, 0)
like = b.FindFootprintByReference("C203")
for ref, x in (("C213", 128.0), ("C214", 130.5)):
    new_fp("Capacitor_SMD", "C_0603_1608Metric", ref, "1nF C0G", x, 136.9, 90, MAX_SHEET + str(uuid.uuid5(NS5, ref)), like=like)
print("MAX30003 input filter placed")

# ---------------------------------------------------------------- 5. the AD8232 block from v2
v2 = pcbnew.LoadBoard("../LeoPatch_v2/LeoPatch_v2.kicad_pcb")
newref = lambda r: {"TP3": "TP601"}.get(r) or re.sub(r"^([A-Z]+)2(\d\d)$", r"\g<1>6\2", r)
newnet = lambda n: n.replace("/ECG front end/", "/ECG AD8232/")
CLUSTER = [f for f in v2.GetFootprints() if (re.fullmatch(r"[RCUJ]2\d\d", f.GetReference()) or f.GetReference() == "TP3")]
for f in CLUSTER:
    ref = newref(f.GetReference())
    fid = f.GetFPID()
    g = pcbnew.FootprintLoad(FPLIB + fid.GetLibNickname().wx_str() + ".pretty", fid.GetLibItemName().wx_str())
    g.SetFPID(fid)
    g.SetReference(ref); g.SetValue(f.GetValue())
    g.SetPath(pcbnew.KIID_PATH(f"/{SHEET_B}/{uuid.uuid5(NS, ref)}"))
    g.SetSheetname("ECG AD8232"); g.SetSheetfile("LeoPatch_ECG_AD8232.kicad_sch")
    g.SetAttributes(f.GetAttributes())
    b.Add(g)
    g.SetOrientation(f.GetOrientation())
    x, y = T(f.GetPosition().x), T(f.GetPosition().y)
    if ref == "R615":
        x, y = 146.5, 147.0                               # SDN pull-up
    elif ref == "TP601":
        x, y = 143.5, 150.0
    else:
        y += DY
    g.SetPosition(P(x, y))
    # reference text: same place relative to the part, same layer / size / visibility
    fr, gr = f.Reference(), g.Reference()
    gr.SetLayer(fr.GetLayer()); gr.SetTextSize(fr.GetTextSize()); gr.SetTextThickness(fr.GetTextThickness())
    gr.SetVisible(fr.IsVisible())
    gr.SetPosition(g.GetPosition() + (fr.GetPosition() - f.GetPosition()))
    gr.SetTextAngle(fr.GetTextAngle())
    for p in g.Pads():
        key = (ref, p.GetNumber())
        if key in PIN_NET:
            p.SetNet(net(PIN_NET[key]))
        elif ref == "U601":                               # exposed-pad paste sub-pads
            p.SetNet(net(PIN_NET[(ref, "21")]))
        if (ref, p.GetNumber()) in PIN_NET:
            # check against v2: same pin, same (renamed) net
            q = f.FindPadByNumber(p.GetNumber())
            assert q is None or newnet(q.GetNetname()) == p.GetNetname() or ref in ("R615", "TP601"), (ref, p.GetNumber(), q.GetNetname(), p.GetNetname())
print("copied", len(CLUSTER), "footprints")

# internal tracks and vias of the block (both ends inside the block's area)
V2_BOX = (112.6, 119.8, 140.5, 146.0)
CL_NETS = lambda n: n.startswith("/ECG front end/") or n in ("GND", "+3V3", "ECG_OUT", "ECG_LO+", "ECG_LO-", "ECG_SDN")
nt = nv = 0
for t in v2.GetTracks():
    n = t.GetNetname()
    if not CL_NETS(n):
        continue
    if t.GetClass() == "PCB_VIA":
        p = t.GetPosition()
        if not inbox(T(p.x), T(p.y), V2_BOX):
            continue
        v = pcbnew.PCB_VIA(b); v.SetPosition(P(T(p.x), T(p.y) + DY)); v.SetWidth(t.GetWidth(pcbnew.F_Cu)); v.SetDrill(t.GetDrill())
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(net(newnet(n))); b.Add(v); nv += 1
    else:
        s, e = t.GetStart(), t.GetEnd()
        if not (inbox(T(s.x), T(s.y), V2_BOX) and inbox(T(e.x), T(e.y), V2_BOX)):
            continue
        u = pcbnew.PCB_TRACK(b); u.SetStart(P(T(s.x), T(s.y) + DY)); u.SetEnd(P(T(e.x), T(e.y) + DY))
        u.SetWidth(t.GetWidth()); u.SetLayer(t.GetLayer()); u.SetNet(net(newnet(n))); b.Add(u); nt += 1
print("copied", nt, "tracks", nv, "vias")

# prune track stubs with a free end left by the rip-ups, so the router never attaches to a spur
stubs = 0
while True:
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    dead = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and conn.TestTrackEndpointDangling(t, False)]
    # signal vias that only connect on one layer (their other side was ripped up); plane vias also reach In1 / In2
    ends = {}
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            for e in (t.GetStart(), t.GetEnd()):
                ends.setdefault((t.GetNetCode(), e.x, e.y), set()).add(t.GetLayer())
    for v in b.GetTracks():
        if v.GetClass() == "PCB_VIA" and v.GetNetname() not in ("GND", "+3V3"):
            p_ = v.GetPosition()
            if len(ends.get((v.GetNetCode(), p_.x, p_.y), set())) < 2:
                dead.append(v)
    if not dead:
        break
    for t in dead:
        b.Remove(t)
    stubs += len(dead)
print("pruned", stubs, "dangling stubs / vias")
b.Save(sys.argv[1])
print("saved")
