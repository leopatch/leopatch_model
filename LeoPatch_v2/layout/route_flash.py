"""Route the GD25WQ64E (U2) flash nets to the BM20BC module (U1).

Run with KiCad's bundled python:
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
      layout/route_flash.py LeoPatch_v2.kicad_pcb

Escape plan (U1 left columns A/B, 0.9 mm LGA pitch, 0.15 mm traces):
  F.Cu lanes between pad rows:  109.35 SCK | 110.25 IO0 | 111.15 IO3 | 112.05 IO2 | 112.95 CS
  IO1 drops through a via between B5/B6/C5/C6 and runs on B.Cu.
  IO2 hops to B.Cu to get past the C1/C2 decoupling caps.
  SCK + IO0 go over the top of C2/U2, IO3 passes between U2 pins 3/4 under the body.
To free lane 109.35 the A1/B1 GND via is removed (A1-B1 tied, B1 -> existing C1 via),
and the C2 GND via is moved next to U2 pin 4 (shared with it).
"""
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew, sys

b = pcbnew.LoadBoard(sys.argv[1])
MM = pcbnew.FromMM
P = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
N = lambda n: b.FindNet(n)
F, B = pcbnew.F_Cu, pcbnew.B_Cu
SIG_W = 0.15


def find_via(x, y):
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_VIA_T and t.GetPosition() == P(x, y):
            return t


def find_track(x0, y0, x1, y1):
    for t in b.GetTracks():
        if t.Type() == pcbnew.PCB_TRACE_T and {(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)} == {
                (MM(x0), MM(y0)), (MM(x1), MM(y1))}:
            return t


def path(net, layer, pts, w=SIG_W):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1))
        t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNet(N(net))
        b.Add(t)


def via(net, x, y):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(P(x, y)); v.SetWidth(MM(0.45)); v.SetDrill(MM(0.2))
    v.SetLayerPair(F, B); v.SetNet(N(net))
    b.Add(v)


# --- clear lane 109.35 and the space above C2 -------------------------------
for obj in [find_via(146.45, 109.35), find_track(146.0, 108.9, 146.45, 109.35),
            find_track(146.9, 108.9, 146.45, 109.35),
            find_via(143.0, 109.2), find_track(143.0, 110.125, 143.0, 109.2)]:
    assert obj is not None, "expected object not found (board already routed?)"
    b.Remove(obj)
path("GND", F, [(146.0, 108.9), (146.9, 108.9), (147.35, 109.35)], 0.2)   # A1-B1 -> C1's via
via("GND", 142.0, 110.09)                                                # C2 + U2.4 GND via
path("GND", F, [(143.0, 110.125), (142.0, 110.09)], 0.2)
path("GND", F, [(140.47, 110.09), (142.0, 110.09)], 0.3)

FL = "/BM20BC module/FLASH_"

# SCK: U1.B2 -> lane 109.35 -> over the top at 108.95 -> down the outside -> U2.6
path(FL + "SCK", F, [(146.9, 109.8), (146.45, 109.35), (145.6, 109.35), (145.2, 108.95),
                     (134.3, 108.95), (134.0, 109.25), (134.0, 111.06), (134.3, 111.36), (135.53, 111.36)])
# IO0: U1.E2 -> lane 110.25 -> up to 109.35 -> over C2/U2 -> drop into U2.5
path(FL + "IO0", F, [(149.6, 109.8), (149.15, 110.25), (145.6, 110.25), (144.7, 109.35),
                     (135.83, 109.35), (135.53, 109.65), (135.53, 110.09)])
# IO3: U1.B3 -> lane 111.15 -> C2 pad gap -> between U2.4/U2.3 -> under body -> U2.7
path(FL + "IO3", F, [(146.9, 110.7), (146.45, 111.15), (144.6, 111.15), (144.35, 110.895),
                     (142.05, 110.895), (141.88, 110.725), (137.9, 110.725), (137.6, 111.025),
                     (137.6, 112.34), (137.3, 112.64), (135.53, 112.64)])
# IO2: U1.B4 -> lane 112.05 -> via -> B.Cu under C2 -> via -> U2.3
path(FL + "IO2", F, [(146.9, 111.6), (146.45, 112.05), (144.6, 112.05)])
via(FL + "IO2", 144.6, 112.05)
path(FL + "IO2", B, [(144.6, 112.05), (144.45, 111.9), (142.45, 111.9), (142.0, 111.45), (142.0, 111.36)])
via(FL + "IO2", 142.0, 111.36)
path(FL + "IO2", F, [(142.0, 111.36), (140.47, 111.36)])
# CS: U1.B6 -> lane 112.95 -> C1 pad gap -> U2.1
path(FL + "CS", F, [(146.9, 113.4), (146.45, 112.95), (145.0, 112.95), (144.0, 113.95),
                    (143.755, 114.195), (142.25, 114.195), (141.965, 113.91), (140.47, 113.91)])
# IO1: U1.B5 -> via between B5/B6/C5/C6 -> B.Cu -> via -> U2.2
path(FL + "IO1", F, [(146.9, 112.5), (147.35, 112.95)])
via(FL + "IO1", 147.35, 112.95)
path(FL + "IO1", B, [(147.35, 112.95), (145.5, 112.95), (145.0, 113.45), (142.5, 113.45), (142.0, 112.95)])
via(FL + "IO1", 142.0, 112.95)
path(FL + "IO1", F, [(142.0, 112.95), (141.69, 112.64), (140.47, 112.64)])

# VCC: U2.8 -> C4.1 -> +3V3 plane via; C4.2 -> GND via
path("+3V3", F, [(135.53, 113.91), (132.9, 113.91)], 0.3)
path("+3V3", F, [(132.9, 114.08), (131.8, 114.08)], 0.3)
via("+3V3", 131.8, 114.08)
path("GND", F, [(132.9, 112.53), (131.8, 112.53)], 0.3)
via("GND", 131.8, 112.53)

# Refill zones in a separate run afterwards (filling here segfaults in KiCad 9 python):
#   load board, pcbnew.ZONE_FILLER(b).Fill(b.Zones()), b.Save(...)
b.Save(sys.argv[1])
print("routed")
