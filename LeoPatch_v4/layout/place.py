"""Phase 1 (KiCad 9 python): create the 4-layer LeoPatch v2 board, place every footprint,
assign nets from the netlist, and dump pad geometry to JSON for the router."""
import wx
app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import os, json, math
import xml.etree.ElementTree as ET
import pcbnew
from pcbnew import FromMM as MM, ToMM

HERE = os.path.dirname(os.path.abspath(__file__))
PRJ = os.path.dirname(HERE)
NETLIST = os.path.join(HERE, "LeoPatch_v3.xml")
OUT = os.path.join(PRJ, "LeoPatch_v3.kicad_pcb")
PLACE = os.path.join(HERE, "placement.json")
KIFP = r"C:\Program Files\KiCad\9.0\share\kicad\footprints"
LIBS = {"LeoPatch": os.path.join(PRJ, "LeoPatch.pretty")}
BX, BY, BW, BH = 100.0, 100.0, 70.0, 45.0

nl = ET.parse(NETLIST).getroot()
comps, padnet = {}, {}
for c in nl.iter("comp"):
    props = {p.get("name"): p.get("value") for p in c.iter("property")}
    sp = c.find("sheetpath")
    comps[c.get("ref")] = dict(value=c.findtext("value"), footprint=c.findtext("footprint"),
                               path=sp.get("tstamps") + c.findtext("tstamps"), dnp="dnp" in props,
                               sheetname=props.get("Sheetname", ""), sheetfile=props.get("Sheetfile", ""))
for net in nl.iter("net"):
    for n in net.iter("node"):
        padnet[(n.get("ref"), n.get("pin"))] = net.get("name")

b = pcbnew.NewBoard(OUT)
b.SetCopperLayerCount(4)
b.SetLayerName(pcbnew.In1_Cu, "In1.Cu (GND)")
b.SetLayerName(pcbnew.In2_Cu, "In2.Cu (3V3)")
# outline with 1 mm corner radius
r = 1.0
def seg(x1, y1, x2, y2):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1))
    s.SetStart(pcbnew.VECTOR2I(MM(x1), MM(y1))); s.SetEnd(pcbnew.VECTOR2I(MM(x2), MM(y2))); b.Add(s)
def arc(cx, cy, a0):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_ARC); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(MM(0.1))
    p = lambda a: pcbnew.VECTOR2I(MM(cx + r * math.cos(math.radians(a))), MM(cy + r * math.sin(math.radians(a))))
    s.SetArcGeometry(p(a0), p(a0 + 45), p(a0 + 90)); b.Add(s)
X0, Y0, X1, Y1 = BX, BY, BX + BW, BY + BH
seg(X0 + r, Y0, X1 - r, Y0); seg(X1, Y0 + r, X1, Y1 - r); seg(X1 - r, Y1, X0 + r, Y1); seg(X0, Y1 - r, X0, Y0 + r)
arc(X1 - r, Y0 + r, 270); arc(X1 - r, Y1 - r, 0); arc(X0 + r, Y1 - r, 90); arc(X0 + r, Y0 + r, 180)

def get_net(name):
    if not name:
        return None
    if name.startswith('unconnected-'):
        name = name.replace('/', '{slash}')
    n = b.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(b, name); b.Add(n)
    return n

placed = {}
for ref, c in comps.items():
    lib, name = c["footprint"].split(":", 1)
    f = pcbnew.FootprintLoad(LIBS.get(lib, os.path.join(KIFP, lib + ".pretty")), name)
    if f is None:
        raise RuntimeError("missing footprint " + c["footprint"])
    f.SetFPID(pcbnew.LIB_ID(lib, name)); f.SetReference(ref); f.SetValue(c["value"])
    f.SetPath(pcbnew.KIID_PATH(c["path"]))
    try:
        f.SetSheetname(c["sheetname"]); f.SetSheetfile(c["sheetfile"]); f.SetDNP(c["dnp"])
    except Exception:
        pass
    b.Add(f)
    for p in f.Pads():
        n = get_net(padnet.get((ref, p.GetNumber())))
        if n is not None:
            p.SetNet(n)
    placed[ref] = f

# ---- placement: {ref: [x, y, rot]} (x, y = footprint anchor); written/tuned in placement.json
P = json.load(open(PLACE))
for ref, (x, y, rot) in P.items():
    f = placed[ref]
    f.SetOrientationDegrees(rot)
    f.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
missing = [r for r in placed if r not in P]
if missing:
    print("NOT PLACED:", missing)

ds = b.GetDesignSettings()
ds.m_MinClearance = MM(0.127); ds.m_TrackMinWidth = MM(0.127); ds.m_ViasMinSize = MM(0.45)
ds.m_MinThroughDrill = MM(0.2); ds.m_HoleClearance = MM(0.2); ds.m_CopperEdgeClearance = MM(0.3)
ds.m_ViasMinAnnularWidth = MM(0.1)
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetClearance(MM(0.15)); nc.SetTrackWidth(MM(0.25)); nc.SetViaDiameter(MM(0.45)); nc.SetViaDrill(MM(0.2))
tb = b.GetTitleBlock()
tb.SetTitle("LeoPatch v2 - BM20BC + AD8232 + USB-C, 4-layer"); tb.SetRevision("2.0"); tb.SetDate("2026-11-03")
tb.SetCompany("Rice ELEC 494 - LeoPatch")
b.Save(OUT)

# ---- geometry dump for the router
def shape_name(p):
    return {pcbnew.PAD_SHAPE_CIRCLE: "circle", pcbnew.PAD_SHAPE_RECTANGLE: "rect",
            pcbnew.PAD_SHAPE_OVAL: "oval", pcbnew.PAD_SHAPE_ROUNDRECT: "roundrect"}.get(p.GetShape(pcbnew.F_Cu) if hasattr(p, 'GetShape') else p.GetShape(), "rect")
pads = []
for f in b.GetFootprints():
    for p in f.Pads():
        pos = p.GetPosition()
        try:
            sz = p.GetSize(pcbnew.F_Cu)
        except TypeError:
            sz = p.GetSize()
        ls = p.GetLayerSet()
        layers = [l for l, lid in (("F", pcbnew.F_Cu), ("B", pcbnew.B_Cu)) if ls.Contains(lid)]
        try:
            shp = p.GetShape(pcbnew.F_Cu)
        except TypeError:
            shp = p.GetShape()
        sname = {pcbnew.PAD_SHAPE_CIRCLE: "circle", pcbnew.PAD_SHAPE_RECTANGLE: "rect",
                 pcbnew.PAD_SHAPE_OVAL: "oval", pcbnew.PAD_SHAPE_ROUNDRECT: "roundrect"}.get(shp, "rect")
        try:
            rr = ToMM(p.GetRoundRectCornerRadius(pcbnew.F_Cu))
        except TypeError:
            rr = ToMM(p.GetRoundRectCornerRadius())
        drill = ToMM(p.GetDrillSize().x) if p.GetDrillSize().x > 0 else 0
        pads.append(dict(ref=f.GetReference(), num=p.GetNumber(), net=p.GetNetname(), x=ToMM(pos.x), y=ToMM(pos.y),
                         sx=ToMM(sz.x), sy=ToMM(sz.y), rot=p.GetOrientationDegrees(), shape=sname, rr=rr,
                         layers=layers, drill=drill, npth=p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH))
crt = {}
for f in b.GetFootprints():
    bb = f.GetCourtyard(pcbnew.F_CrtYd).BBox() if f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else f.GetBoundingBox(False)
    crt[f.GetReference()] = [ToMM(bb.GetLeft()), ToMM(bb.GetTop()), ToMM(bb.GetRight()), ToMM(bb.GetBottom())]
json.dump(dict(board=[X0, Y0, X1, Y1], pads=pads, courtyards=crt), open(os.path.join(HERE, "geom.json"), "w"))
print("placed", len(P), "of", len(placed), "pads", len(pads))
