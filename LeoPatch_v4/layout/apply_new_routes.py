"""Write route_new.py output to the board (KiCad python):  $PY layout/apply_new_routes.py board.kicad_pcb routes.json
Adds the new tracks and vias (0.45 / 0.2 mm), deletes the dangling copper route_new.py found."""
import json, sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
r = json.load(open(sys.argv[2]))
assert not r["fails"], r["fails"]
MM, T = pcbnew.FromMM, pcbnew.ToMM
P = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
LAY = {"F": pcbnew.F_Cu, "B": pcbnew.B_Cu}
near = lambda a, b_: abs(a - b_) < 0.002

index = []                                    # (kind, net, coords, item), read before anything is removed
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA":
        index.append(("via", t.GetNetname(), (T(t.GetPosition().x), T(t.GetPosition().y)), t))
    else:
        index.append(("track", t.GetNetname(), (T(t.GetStart().x), T(t.GetStart().y), T(t.GetEnd().x), T(t.GetEnd().y)), t))
doomed = []
for d in r["delete"]:
    want = (d["x"], d["y"]) if d["kind"] == "via" else (d["x0"], d["y0"], d["x1"], d["y1"])
    for kind, n, c, t in index:
        if kind == d["kind"] and n == d["net"] and all(near(a, w) for a, w in zip(c, want)) and t not in doomed:
            doomed.append(t); break
for t in doomed:
    b.Remove(t)
gone = len(doomed)
for lyr, x0, y0, x1, y1, w, n in r["tracks"]:
    t = pcbnew.PCB_TRACK(b); t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1)); t.SetWidth(MM(w)); t.SetLayer(LAY[lyr])
    t.SetNet(b.FindNet(n)); b.Add(t)
for x, y, n in r["vias"]:
    v = pcbnew.PCB_VIA(b); v.SetPosition(P(x, y)); v.SetWidth(MM(0.45)); v.SetDrill(MM(0.2))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu); v.SetNet(b.FindNet(n)); b.Add(v)
# remove track stubs with a free end (left over where old routing was cut), repeat until none are left;
# KiCad's own connectivity decides what is dangling
stubs = 0
while True:
    b.BuildConnectivity()
    conn = b.GetConnectivity()
    dead = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and conn.TestTrackEndpointDangling(t, False)]
    if not dead:
        break
    for t in dead:
        b.Remove(t)
    stubs += len(dead)
print("removed", stubs, "dangling stub tracks")
b.Save(sys.argv[1])
print("deleted", gone, "of", len(r["delete"]), "; added", len(r["tracks"]), "tracks,", len(r["vias"]), "vias")
