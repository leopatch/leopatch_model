"""Dump board copper to JSON for route_new.py (KiCad python):  $PY layout/dump_geom.py board.kicad_pcb geom.json
Pads (net, shape, size, rotation, copper layers), tracks, vias, board outline bbox, NPTH holes."""
import json, sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
T = pcbnew.ToMM
out = {"pads": [], "tracks": [], "vias": [], "fps": {}}
bb = b.GetBoardEdgesBoundingBox()
out["board"] = [T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())]
# outline segments (to keep tracks off cut-outs)
out["edges"] = []
for d in b.GetDrawings():
    if d.GetLayer() == pcbnew.Edge_Cuts:
        out["edges"].append([T(d.GetStart().x), T(d.GetStart().y), T(d.GetEnd().x), T(d.GetEnd().y)])
SHAPE = {pcbnew.PAD_SHAPE_CIRCLE: "circle", pcbnew.PAD_SHAPE_RECTANGLE: "rect", pcbnew.PAD_SHAPE_OVAL: "oval",
         pcbnew.PAD_SHAPE_ROUNDRECT: "roundrect", pcbnew.PAD_SHAPE_TRAPEZOID: "rect", pcbnew.PAD_SHAPE_CUSTOM: "rect",
         pcbnew.PAD_SHAPE_CHAMFERED_RECT: "rect"}
for f in b.GetFootprints():
    ref = f.GetReference()
    out["fps"][ref] = [T(f.GetPosition().x), T(f.GetPosition().y), f.GetOrientationDegrees()]
    for p in f.Pads():
        ls = [n for n, l in (("F", pcbnew.F_Cu), ("B", pcbnew.B_Cu)) if p.IsOnLayer(l)]
        npth = p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
        sz = p.GetSize(pcbnew.F_Cu) if hasattr(p, "GetSize") else p.GetSize()
        try:
            sh = p.GetShape(pcbnew.F_Cu)
        except TypeError:
            sh = p.GetShape()
        try:
            rr = p.GetRoundRectCornerRadius(pcbnew.F_Cu)
        except TypeError:
            rr = p.GetRoundRectCornerRadius()
        out["pads"].append({"ref": ref, "num": p.GetNumber(), "net": p.GetNetname(), "x": T(p.GetPosition().x),
                            "y": T(p.GetPosition().y), "sx": T(sz.x), "sy": T(sz.y), "rot": p.GetOrientationDegrees(),
                            "shape": SHAPE.get(sh, "rect"), "rr": T(rr), "layers": ls, "npth": npth,
                            "drill": T(p.GetDrillSize().x), "pth": (not npth) and p.GetDrillSize().x > 0})
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        out["vias"].append({"net": t.GetNetname(), "x": T(t.GetPosition().x), "y": T(t.GetPosition().y), "d": T(t.GetWidth(pcbnew.F_Cu) if hasattr(t, 'GetWidth') else 0.45)})
    elif t.GetClass() == "PCB_TRACK":
        out["tracks"].append({"net": t.GetNetname(), "layer": "F" if t.GetLayer() == pcbnew.F_Cu else "B",
                              "x0": T(t.GetStart().x), "y0": T(t.GetStart().y), "x1": T(t.GetEnd().x), "y1": T(t.GetEnd().y),
                              "w": T(t.GetWidth())})
json.dump(out, open(sys.argv[2], "w"))
print("pads", len(out["pads"]), "tracks", len(out["tracks"]), "vias", len(out["vias"]), "board", out["board"])
