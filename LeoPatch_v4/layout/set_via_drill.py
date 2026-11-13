"""Set every via to a 0.3 mm drill, keeping the 0.45 mm pad (KiCad python):  $PY layout/set_via_drill.py board.kicad_pcb
JLCPCB's standard 4-layer via is 0.3 mm hole / 0.45 mm pad; 0.2 mm holes are a paid option. The pad size is
unchanged, so track clearances are unchanged; the design check verifies hole-to-copper (0.2 mm) and
hole-to-hole (0.25 mm). Run before refill.py so the plane clearances follow the bigger holes."""
import sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

DRILL = pcbnew.FromMM(0.3)
b = pcbnew.LoadBoard(sys.argv[1])
n = 0
for t in b.GetTracks():
    if t.GetClass() == "PCB_VIA" and t.GetDrill() != DRILL:
        t.SetDrill(DRILL); n += 1
# same-net vias whose holes would be < 0.25 mm apart (e.g. one via per QFN ground pin at 0.5 mm pitch):
# join the dropped via's track ends to the kept via with a short track and remove the dropped via
GAP = pcbnew.FromMM(0.25)
vias = sorted((t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"), key=lambda v: (v.GetPosition().x, v.GetPosition().y))
kept, merged = [], 0
for v in vias:
    p = v.GetPosition()
    u = next((k for k in kept if k.GetNetCode() == v.GetNetCode() and (k.GetPosition() - p).EuclideanNorm() < DRILL + GAP), None)
    if u is None:
        kept.append(v); continue
    layers = {t.GetLayer() for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and p in (t.GetStart(), t.GetEnd())} or {pcbnew.F_Cu}
    for lyr in layers:
        s = pcbnew.PCB_TRACK(b); s.SetStart(u.GetPosition()); s.SetEnd(p); s.SetWidth(pcbnew.FromMM(0.2))
        s.SetLayer(lyr); s.SetNet(v.GetNet()); b.Add(s)
    b.Remove(v); merged += 1
print("merged", merged, "too-close same-net vias")
nc = b.GetDesignSettings().m_NetSettings.GetDefaultNetclass()
nc.SetViaDrill(DRILL)
b.Save(sys.argv[1])
print("via drill -> 0.3 mm on", n, "vias")
