"""Board rework after the design review. Starts from the board as it was after route_flash.py.
Run once with KiCad closed, after add_pullup_testpoints_sch.py, add_power_headers_sch.py, add_start_button_sch.py and add_reset_gain_sch.py:

  PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
  $PY layout/rework_review.py LeoPatch_v3.kicad_pcb
  $PY layout/move_vias_out_of_pads.py LeoPatch_v3.kicad_pcb
  $PY layout/refill.py LeoPatch_v3.kicad_pcb        (zone fill has to be its own run), then DRC

What it does (rules from the Fanstel BM20C datasheet v1.00: no ground or traces at the antenna, cut the
board away below the antenna if possible, avoid signal lines below the module):

1. Antenna: the board is cut away under the antenna, 5 mm wider than the module on each side.
2. No signal via under the module any more. Every signal leaves the module on the top layer through the
   lanes between pads and changes layer outside the module outline. Only GND / +3V3 vias (straight to the
   planes, between pads) are left under it.
3. USB D+/D-: top layer only, no vias, straight through the protection chip U102 (turned to 0 degrees).
4. Vias that sat inside pads of U1 (K9), U201 (pins 6, 20) and J301 (pins 4, 10) moved next to the pad.
5. C3 (reset capacitor) moved next to the SWD header, R1 and C105 turned around.
6. R2 100k pull-up on FLASH_CS; test points TP1 GND, TP2 +3V3, TP3 ECG_OUT.
7. Single power pins J103 (VIN), J104 (3V3), J105 (GND); four M2 mounting holes H1-H4.
8. START button SW302 on U1.H9 (P1.09); the red LED moves from H9 to U1.K2 (P3.10).
9. RESET button SW303; ECG gain 400 -> 200 (R208, C201, C203 values).
"""
import os, sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_pullup_testpoints_sch import SYM_UUID
from add_power_headers_sch import SYM_UUID as PWR_UUID
from add_start_button_sch import SYM_UUID as BTN_UUID
from add_reset_gain_sch import SYM_UUID as RST_UUID, ECG_VALUES
SYM_UUID = {**SYM_UUID, **PWR_UUID, **BTN_UUID, **RST_UUID}

b = pcbnew.LoadBoard(sys.argv[1])
MM, mm = pcbnew.FromMM, pcbnew.ToMM
P = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
F, B = pcbnew.F_Cu, pcbnew.B_Cu
assert not b.FindFootprintByReference("R2"), "rework already applied"
TRACKS = list(b.GetTracks())
DOOMED = []   # removed in one go just before saving: KiCad 9 python lookups break once something is removed


def net(name):
    n = b.FindNet(name)
    assert n is not None, name
    return n


def near(p, x, y):
    return abs(p.x - MM(x)) < 30000 and abs(p.y - MM(y)) < 30000


def doom(t):
    TRACKS.remove(t); DOOMED.append(t)


def rm_via(x, y):
    for t in TRACKS:
        if t.Type() == pcbnew.PCB_VIA_T and near(t.GetPosition(), x, y):
            return doom(t)
    raise AssertionError(f"no via at {x},{y}")


def rm_track(layer, x0, y0, x1, y1):
    for t in TRACKS:
        if t.Type() == pcbnew.PCB_TRACE_T and t.GetLayer() == layer and (
                (near(t.GetStart(), x0, y0) and near(t.GetEnd(), x1, y1)) or
                (near(t.GetStart(), x1, y1) and near(t.GetEnd(), x0, y0))):
            return doom(t)
    raise AssertionError(f"no track {x0},{y0} - {x1},{y1}")


def rm_path(layer, pts):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        rm_track(layer, x0, y0, x1, y1)


def rm_where(name, keep):
    """Remove every track and via of a net except those for which keep(x0, y0, x1, y1) is true
    (a via is passed as a zero-length track)."""
    n = 0
    for t in [t for t in TRACKS if t.GetNetname() == name]:
        s, e = (t.GetPosition(), t.GetPosition()) if t.Type() == pcbnew.PCB_VIA_T else (t.GetStart(), t.GetEnd())
        if keep(mm(s.x), mm(s.y), mm(e.x), mm(e.y)):
            continue
        doom(t); n += 1
    return n


def path(netname, layer, pts, w=0.2):
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b)
        t.SetStart(P(x0, y0)); t.SetEnd(P(x1, y1))
        t.SetWidth(MM(w)); t.SetLayer(layer); t.SetNet(net(netname))
        b.Add(t)


def via(netname, x, y):
    v = pcbnew.PCB_VIA(b)
    v.SetPosition(P(x, y)); v.SetWidth(MM(0.45)); v.SetDrill(MM(0.2))
    v.SetLayerPair(F, B); v.SetNet(net(netname))
    b.Add(v)


def fp(ref):
    f = b.FindFootprintByReference(ref)
    assert f is not None, ref
    return f


U1, U102, R1, C3, C105 = fp("U1"), fp("U102"), fp("R1"), fp("C3"), fp("C105")
KEEPOUT = [z for z in b.Zones() if z.GetZoneName() == "ANTENNA_KEEPOUT"][0]
TOP_EDGE = [d for d in b.GetDrawings() if d.GetClass() == "PCB_SHAPE" and d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT
            and near(d.GetStart(), 101.0, 100.0) and near(d.GetEnd(), 169.0, 100.0)][0]

# ---------------------------------------------------------------- 1. antenna cut-out
# Module outline is x 145.05 .. 155.05; the shield (main body) starts about 6.5 mm below the module's top edge.
AX0, AX1, AY = 140.05, 160.05, 106.6
TOP_EDGE.SetEnd(P(AX0, 100.0))
for (x0, y0), (x1, y1) in (((AX0, 100.0), (AX0, AY)), ((AX0, AY), (AX1, AY)), ((AX1, AY), (AX1, 100.0)), ((AX1, 100.0), (169.0, 100.0))):
    s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT); s.SetLayer(pcbnew.Edge_Cuts)
    s.SetStart(P(x0, y0)); s.SetEnd(P(x1, y1)); s.SetWidth(TOP_EDGE.GetWidth()); b.Add(s)
o = KEEPOUT.Outline(); o.RemoveAllContours(); o.NewOutline()
for x, y in ((AX0, 99.0), (AX1, 99.0), (AX1, AY), (AX0, AY)):
    o.Append(MM(x), MM(y))

# ---------------------------------------------------------------- 2. USB data lines, top layer only
DP, DN, VBUS = "USB_DP", "USB_DN", "VBUS"
RST, SWDIO, SWDCLK = "/BM20BC module/nRESET", "/BM20BC module/SWDIO", "/BM20BC module/SWDCLK"
rm_where(DP, lambda *a: False); rm_where(DN, lambda *a: False)
# pins 1/6 (D+) top row, 3/4 (D-) bottom row; 0.12 mm left so its courtyard clears the connector
U102.SetOrientationDegrees(0); U102.SetPosition(P(159.48, 112.0))

# Outside the module lanes the two lines are 0.27 mm wide; side by side with a 0.2 mm gap that is about 90 ohm
# differential on the JLC04161H-7628 stackup. Inside the lanes only 0.15 mm fits between the pads.
# Path lengths module pad -> connector pad: D+ 14.44 mm, D- 14.42 mm (D- gets a bend below the pair to make up
# for D+'s shorter way round).
UW = 0.27
# D+ : U1.G7 -> up the F/G column lane -> lane 112.95 -> dips under the SWD vias -> U102.1 -> U102.6 -> J102.B6
path(DP, F, [(151.4, 114.3), (150.95, 113.85), (150.95, 112.95), (154.7, 112.95)], 0.15)
path(DP, F, [(154.7, 112.95), (155.1, 113.35), (155.9, 113.35), (157.2, 112.05), (157.2, 111.45),
             (157.6, 111.05), (158.34, 111.05), (160.4, 111.05), (160.6, 111.25), (162.3, 111.25)], UW)
path(DP, F, [(163.2, 111.3), (163.5, 111.3), (163.6, 111.4), (163.6, 112.1), (163.5, 112.2), (163.2, 112.2)])  # B6-A6 behind the pads
# D- : U1.G6 -> lane 113.85 -> U102.3 -> U102.4 -> J102.B7, A7 joined in front of the pads
path(DN, F, [(151.4, 113.4), (151.85, 113.85), (154.7, 113.85)], 0.15)
path(DN, F, [(154.7, 113.85), (156.75, 113.85), (156.75, 115.2), (157.75, 115.2), (157.75, 113.6), (158.34, 113.01),
             (158.34, 112.95), (160.4, 112.95), (160.6, 112.75), (162.3, 112.75)], UW)
path(DN, F, [(162.3, 111.75), (161.8, 111.75), (161.8, 112.75)])

# U102 GND (pin 2) and VBUS (pin 5) sit between the two data lines: one via each under its body
rm_via(159.6, 114.2); rm_track(F, 159.6, 113.14, 159.6, 114.2)
via("GND", 159.48, 112.4); path("GND", F, [(158.34, 112.0), (159.08, 112.0), (159.48, 112.4)])
rm_path(F, [(159.9, 110.1), (159.9, 110.2), (159.8, 110.3)])
rm_path(F, [(159.7, 111.4), (160.2, 111.9), (160.3, 111.9), (160.4, 112.0), (160.8, 112.0), (161.2, 112.4),
            (161.2, 112.5), (161.3, 112.6), (161.3, 114.6)])
via(VBUS, 159.48, 110.2); path(VBUS, F, [(159.9, 110.1), (159.48, 110.2)])
via(VBUS, 159.48, 111.6); path(VBUS, F, [(160.62, 112.0), (159.88, 112.0), (159.48, 111.6)])
via(VBUS, 160.3, 114.2); path(VBUS, F, [(160.3, 114.2), (160.3, 114.7)])
path(VBUS, B, [(159.48, 110.2), (159.48, 111.6), (160.3, 112.42), (160.3, 114.2)])

# ---------------------------------------------------------------- 3. module, right side
# Layer changes sit in one column at x = 155.5, just outside the module outline (edge at 155.05):
#   111.3 SWDCLK | 112.0 nRESET | 112.8 SWDIO | (USB pair passes) | 114.85 VBUS | 115.6 ECG_OUT | 116.35 VBAT_SENSE
VX = 155.5

# nRESET: U1.G2 -> lane 110.25 -> R1 (turned so its nRESET pad faces the lane) -> via -> bottom layer to J301
rm_where(RST, lambda x0, y0, x1, y1: min(x0, x1) > 158.25 and (x0, y0) != (x1, y1) and not (near(P(x1, y1), 167.2, 130.2) or near(P(x0, y0), 167.2, 130.2)))
R1.SetOrientationDegrees(270)                       # pad 1 (+3V3) up, pad 2 (nRESET) down
rm_via(156.1, 110.8); rm_track(F, 156.6, 110.025, 156.1, 110.8)
via("+3V3", 155.55, 108.375); path("+3V3", F, [(156.6, 108.375), (155.55, 108.375)], 0.25)
path(RST, F, [(151.4, 109.8), (151.85, 110.25), (154.6, 110.25)], 0.15)
path(RST, F, [(154.6, 110.25), (155.6, 110.25), (156.3, 110.05)])
path(RST, F, [(156.6, 110.3), (156.6, 111.55), (156.15, 112.0), (VX, 112.0)])
via(RST, VX, 112.0); path(RST, B, [(VX, 112.0), (158.3, 114.8)])
# C3 (reset capacitor) goes next to the SWD header, where nRESET arrives
rm_via(157.1, 110.8); rm_track(F, 156.6, 111.625, 157.1, 110.8)
C3.SetPosition(P(165.5, 132.95)); C3.SetOrientationDegrees(180)   # pad 1 (nRESET) east, pad 2 (GND) west
path(RST, F, [(166.5, 130.54), (166.5, 132.95)])
via("GND", 163.6, 132.95); path("GND", F, [(164.725, 132.95), (163.6, 132.95)])
# J301 pin 10: via beside the pad instead of inside it
path(RST, B, [(166.7, 129.7), (167.54, 130.54), (169.1, 130.54)])
via(RST, 169.1, 130.54); path(RST, F, [(169.1, 130.54), (168.3, 130.54)])

# SWDCLK: U1.K3 -> via -> straight diagonal on the bottom layer to its old run near J301 (no more loop under the USB connector)
rm_where(SWDCLK, lambda x0, y0, x1, y1: max(y0, y1) > 120.55 and not (near(P(x1, y1), 167.3, 126.4) or near(P(x0, y0), 167.3, 126.4)))
path(SWDCLK, F, [(154.1, 110.7), (154.9, 110.7), (VX, 111.3)])
via(SWDCLK, VX, 111.3); path(SWDCLK, B, [(VX, 111.3), (164.7, 120.5)])
path(SWDCLK, B, [(167.1, 126.2), (167.63, 126.73), (169.1, 126.73)])
via(SWDCLK, 169.1, 126.73); path(SWDCLK, F, [(169.1, 126.73), (168.3, 126.73)])

# SWDIO: U1.J3 -> lane 111.15 -> via -> bottom layer
rm_where(SWDIO, lambda x0, y0, x1, y1: max(x0, x1) > 156.15)
path(SWDIO, F, [(153.2, 110.7), (153.65, 111.15), (154.7, 111.15), (154.9, 111.35), (154.9, 112.2), (VX, 112.8)], 0.15)
via(SWDIO, VX, 112.8); path(SWDIO, B, [(VX, 112.8), (VX, 113.9), (156.1, 114.5)])

# VBUS: U1.H7 -> lane 114.75 -> via (feeds the bottom-layer run to D102) -> C105 -> USB connector
rm_via(151.85, 114.75); rm_via(156.2, 116.5)
rm_track(F, 152.3, 114.3, 151.85, 114.75); rm_path(F, [(151.9, 114.8), (151.9, 114.7), (152.2, 114.4)])
rm_path(B, [(150.6, 115.3), (151.3, 115.3), (151.8, 114.8), (151.9, 114.8), (152.4, 115.3), (154.8, 115.3), (156.0, 116.5), (156.2, 116.5)])
rm_track(B, 150.6, 115.3, 144.1, 108.8)
rm_path(F, [(157.0, 116.3), (157.3, 116.3), (157.6, 116.0), (157.9, 116.0), (158.7, 115.2)])
rm_via(152.75, 114.75); rm_track(F, 152.3, 115.2, 152.75, 114.75)          # H8 ground via was in the lane
via("GND", 152.75, 115.65); path("GND", F, [(152.3, 115.2), (152.75, 115.65)])
C105.SetOrientationDegrees(270); C105.SetPosition(P(156.6, 116.8))   # pad 1 (VBUS) up, pad 2 (GND) down; 1 mm lower for the D- bend
rm_via(156.6, 114.1); rm_track(F, 156.6, 115.025, 156.6, 114.1)
path(VBUS, F, [(152.3, 114.3), (152.75, 114.75), (154.6, 114.75)], 0.15)
path(VBUS, F, [(154.6, 114.75), (VX, 114.85), (155.95, 114.85), (156.25, 115.15), (156.25, 115.7)])
via(VBUS, VX, 114.85); path(VBUS, B, [(VX, 114.85), (150.15, 114.85), (144.1, 108.8)])
path(VBUS, F, [(156.9, 115.75), (158.15, 115.75), (158.7, 115.2)])
via("GND", 157.6, 117.8); path("GND", F, [(156.6, 117.475), (157.6, 117.8)])

# ECG_OUT (K8) and VBAT_SENSE (K9): vias out of the pad / out from under the module
rm_via(154.4, 116.9); rm_path(F, [(154.2, 115.3), (154.6, 115.7), (154.6, 116.7), (154.4, 116.9)])
path("ECG_OUT", F, [(154.1, 115.2), (155.15, 115.2), (VX, 115.6)])
via("ECG_OUT", VX, 115.6); path("ECG_OUT", B, [(VX, 115.6), (156.25, 115.6), (156.25, 116.55), (155.9, 116.9), (154.4, 116.9)])
rm_via(154.0, 116.2)
via("VBAT_SENSE", VX, 116.35)
path("VBAT_SENSE", F, [(154.1, 116.23), (VX, 116.35)]); path("VBAT_SENSE", B, [(154.0, 116.2), (VX, 116.35)])

# ---------------------------------------------------------------- 4. module, left side
FL = "/BM20BC module/FLASH_"
# FLASH_IO1 takes lane 112.95 and changes layer left of the module; FLASH_CS moves to lane 113.85.
rm_track(F, 146.9, 112.5, 147.35, 112.95); rm_via(147.35, 112.95)
rm_path(B, [(147.35, 112.95), (145.5, 112.95), (145.0, 113.45), (142.5, 113.45)])
rm_path(F, [(146.9, 113.4), (146.45, 112.95), (145.0, 112.95), (144.0, 113.95), (143.755, 114.195)])
# lane 113.85 was blocked by B7's ground via: B7 takes the spot of B8's +3V3 via, B8 shares C8's via
rm_via(146.45, 113.85); rm_track(F, 146.9, 114.3, 146.45, 113.85)
rm_via(146.45, 114.75); rm_track(F, 146.9, 115.2, 146.45, 114.75)
via("GND", 146.45, 114.75); path("GND", F, [(146.9, 114.3), (146.45, 114.75)])
path("+3V3", F, [(146.9, 115.2), (147.35, 114.75)])
path(FL + "IO1", F, [(146.9, 112.5), (146.45, 112.95), (144.3, 112.95)], 0.15)
via(FL + "IO1", 144.3, 112.95); path(FL + "IO1", B, [(144.3, 112.95), (143.8, 113.45), (142.5, 113.45)], 0.15)
path(FL + "CS", F, [(146.9, 113.4), (146.45, 113.85), (144.1, 113.85), (143.755, 114.195)], 0.15)

# ---------------------------------------------------------------- 5. AD8232: vias out of pins 20 and 6
HPS, SW = "/ECG front end/HPSENSE", "/ECG front end/SW"
rm_via(124.8, 129.1); via(HPS, 124.8, 130.45)          # just past the package corner
path(HPS, F, [(124.8, 129.0), (124.8, 130.45)]); path(HPS, B, [(124.8, 129.1), (124.8, 130.45)])
rm_via(129.3, 129.1); via(SW, 129.75, 129.5)
path(SW, F, [(129.2, 129.0), (129.75, 129.5)]); path(SW, B, [(129.3, 129.1), (129.75, 129.5)])

# C204 pin 2 (HPSENSE) and R206 pin 1 (FILT): done by hand, move_vias_out_of_pads.py finds no free spot for the second
rm_via(118.4, 132.3); rm_path(B, [(118.4, 132.3), (119.3, 132.3), (120.1, 131.5)])
via(HPS, 118.25, 131.3); path(HPS, F, [(118.2, 132.0), (118.25, 131.3)]); path(HPS, B, [(118.25, 131.3), (119.9, 131.3), (120.1, 131.5)])
FILT = "/ECG front end/FILT"
rm_via(120.5, 132.3); via(FILT, 119.3, 132.5)
path(FILT, F, [(120.0, 132.5), (119.3, 132.5)]); path(FILT, B, [(120.5, 132.3), (119.3, 132.5)])

# Battery input: its via sat under the on/off switch. It now runs on the bottom layer around the switch.
BAT = "/Power/BAT_RAW"
rm_via(102.8, 111.6); rm_path(B, [(102.8, 111.6), (102.8, 109.9), (102.7, 109.8), (102.7, 104.3)])
rm_path(F, [(102.9, 113.5), (102.8, 113.4), (102.8, 111.6)])
path(BAT, B, [(102.6, 103.5), (102.6, 104.9), (105.3, 107.6), (105.3, 113.75)], 0.3)
via(BAT, 105.3, 113.75); path(BAT, F, [(103.63, 113.75), (105.3, 113.75)], 0.3)

# ---------------------------------------------------------------- 6. R2 and test points
FPLIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
SHEET = "/ab00b617-dce4-5dd5-bd30-81c8a7690bc0/"


def place(lib, name, ref, val, x, y, rot, nets, sheet=(SHEET, "BM20BC module", "LeoPatch_MCU.kicad_sch")):
    f = pcbnew.FootprintLoad(FPLIB + lib, name)
    f.SetFPID(pcbnew.LIB_ID(lib.replace(".pretty", ""), name))
    f.SetReference(ref); f.SetValue(val)
    if sheet:
        f.SetPath(pcbnew.KIID_PATH(sheet[0] + SYM_UUID[ref]))
        f.SetSheetname(sheet[1]); f.SetSheetfile(sheet[2])
    b.Add(f)
    f.SetPosition(P(x, y)); f.SetOrientationDegrees(rot)
    for p in f.Pads():
        if p.GetNumber() in nets:
            p.SetNet(net(nets[p.GetNumber()]))
    r = f.Reference(); r.SetLayer(pcbnew.F_Fab)
    r.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8))); r.SetTextThickness(MM(0.12))
    return f


place("Resistor_SMD.pretty", "R_0603_1608Metric", "R2", "100k", 140.9, 116.2, 90, {"1": "+3V3", "2": FL + "CS"})
# VBAT_SENSE used to run straight through here: it now passes between R2's pads
rm_track(F, 121.1, 115.2, 142.1, 115.2)
path("VBAT_SENSE", F, [(121.1, 115.2), (139.2, 115.2), (140.2, 116.2), (141.6, 116.2), (142.1, 115.7), (142.1, 115.2)])
path(FL + "CS", F, [(140.47, 113.91), (140.9, 114.34), (140.9, 115.375)], 0.15)
via("+3V3", 139.9, 117.025); path("+3V3", F, [(140.9, 117.025), (139.9, 117.025)], 0.3)


def silk(txt, x, y, size=0.8):
    t = pcbnew.PCB_TEXT(b); t.SetText(txt); t.SetLayer(pcbnew.F_SilkS)
    t.SetPosition(P(x, y)); t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size))); t.SetTextThickness(MM(0.12))
    b.Add(t)


TPY = 126.5
for ref, val, netname, x, label in (("TP3", "ECG_OUT", "ECG_OUT", 141.0, "ECG"), ("TP1", "GND", "GND", 144.0, "GND"),
                                    ("TP2", "3V3", "+3V3", 147.0, "3V3")):
    place("TestPoint.pretty", "TestPoint_Pad_D1.0mm", ref, val, x, TPY, 0, {"1": netname})
    silk(label, x, TPY + 1.5)
via("ECG_OUT", 139.6, 124.5); path("ECG_OUT", F, [(139.6, 124.5), (141.0, 125.9), (141.0, TPY)])   # taps the bottom-layer run
via("GND", 144.0, 125.2); path("GND", F, [(144.0, 125.2), (144.0, TPY)], 0.3)
via("+3V3", 147.0, 125.2); path("+3V3", F, [(147.0, 125.2), (147.0, TPY)], 0.3)

# the EXPORT label moves left to make room for C3
for d in b.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetText() == "EXPORT":
        d.SetPosition(P(160.6, 132.9))

# ---------------------------------------------------------------- 7. power pins and mounting holes
# Three single pins, about 7 mm apart so alligator clips fit side by side: J103 VIN (regulator input, after the
# battery / USB diodes), J104 3V3, J105 GND. GND and +3V3 connect straight to the inner planes; only VIN needs a track.
PWR = ("/1bd637cf-7783-5fe2-bdf0-ffd80b334887/", "Power", "LeoPatch_Power.kicad_sch")
HDR = ("Connector_PinHeader_2.54mm.pretty", "PinHeader_1x01_P2.54mm_Vertical")
for ref, val, x, y, n1, ly in (("J103", "VIN", 108.0, 116.0, "/Power/VBAT", 113.7), ("J104", "3V3", 117.0, 116.0, "+3V3", 113.7),
                               ("J105", "GND", 112.5, 121.5, "GND", 123.8)):
    place(*HDR, ref, val, x, y, 0, {"1": n1}, sheet=PWR)
    silk(val, x, ly)
path("/Power/VBAT", F, [(110.0, 109.3), (110.0, 114.0), (108.0, 116.0)], 0.3)

# M2 mounting holes (2.2 mm, not plated). Board-only parts: not in the schematic, BOM or placement file.
for i, (x, y) in enumerate(((104.0, 124.5), (125.5, 112.0), (167.5, 120.0), (154.5, 142.0)), 1):
    f = place("MountingHole.pretty", "MountingHole_2.2mm_M2", f"H{i}", "M2", x, y, 0, {}, sheet=None)
    f.SetAttributes(pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_POS_FILES | pcbnew.FP_EXCLUDE_FROM_BOM)

# ---------------------------------------------------------------- 8. START button
# START needs a pin that can wake the chip, so it takes U1.H9 (P1.09, same port as EXPORT) from the red LED,
# and the red LED moves to U1.K2 (P3.10), which was unused.
UI = ("/707f3a77-758b-5a35-aad2-4bc90a18387e/", "LEDs + button", "LeoPatch_UI.kicad_sch")
START = pcbnew.NETINFO_ITEM(b, "BTN_START"); b.Add(START)
rm_where("LED_RED", lambda *a: False)
for p_ in U1.Pads():
    if p_.GetNumber() == "H9":
        p_.SetNet(START)
    elif p_.GetNumber() == "K2":
        old_net = p_.GetNet(); p_.SetNet(net("LED_RED"))
        if old_net.GetNetCode() > 0:
            DOOMED.append(old_net)
# red LED: U1.K2 -> via just outside the module -> bottom layer round the top of the USB connector -> R303
path("LED_RED", F, [(154.1, 109.8), (155.0, 109.8), (VX, 109.3)])
via("LED_RED", VX, 109.3)
path("LED_RED", B, [(VX, 109.3), (159.2, 109.3), (159.8, 108.7), (160.7, 108.7), (160.8, 108.8), (164.0, 112.0), (164.0, 114.0),
                    (164.5, 114.5), (164.5, 115.6), (164.7, 115.8), (164.7, 118.4)])     # jog clears the connector's shell pin
via("LED_RED", 164.7, 118.4)
path("LED_RED", F, [(164.7, 118.4), (164.2, 118.9), (159.775, 118.9), (159.775, 120.0)])
# START: U1.H9 keeps the red LED's old escape, then runs down the bottom layer to the new button left of EXPORT
SX, SY = 146.0, 138.0
place("Button_Switch_SMD.pretty", "SW_SPST_PTS645Sx43SMTR92", "SW302", "START", SX, SY, 0, {"1": "BTN_START", "2": "GND"}, sheet=UI)
path("BTN_START", F, [(152.4, 116.5), (153.4, 117.5)])
via("BTN_START", 153.4, 117.5)
path("BTN_START", B, [(153.4, 117.5), (154.1, 118.2), (154.2, 118.2), (154.7, 118.7), (154.8, 118.7), (154.9, 118.8), (156.2, 118.8),
                      (157.1, 119.7), (157.1, 131.2), (153.6, 134.7), (151.9, 134.7)])
via("BTN_START", 151.9, 134.7)
path("BTN_START", F, [(151.9, 134.7), (150.85, 135.75), (SX + 3.98, SY - 2.25)])
path("BTN_START", F, [(SX - 3.98, SY - 2.25), (SX + 3.98, SY - 2.25)], 0.3)      # the two pin-1 pads are not tied inside the part
for dx in (-3.98, 3.98):
    vx = SX + dx + (1.0 if dx > 0 else -1.0)
    via("GND", vx, SY + 3.0); path("GND", F, [(SX + dx, SY + 2.25), (vx, SY + 3.0)], 0.3)
silk("START", SX, 133.0, 1.0)

# ---------------------------------------------------------------- 9. RESET button and ECG gain 200
# Small B3U button below EXPORT. nRESET reaches it on the bottom layer down the right edge from J301 pin 10.
place("Button_Switch_SMD.pretty", "SW_SPST_B3U-1000P", "SW303", "RESET", 163.0, 143.2, 180, {"1": RST, "2": "GND"})
path(RST, B, [(169.1, 130.54), (169.1, 142.0), (167.9, 143.2), (166.0, 143.2)])
via(RST, 166.0, 143.2); path(RST, F, [(166.0, 143.2), (164.7, 143.2)])
via("GND", 160.2, 143.2); path("GND", F, [(161.3, 143.2), (160.2, 143.2)], 0.3)
silk("RESET", 158.2, 143.3)
for ref, val in ECG_VALUES.items():      # gain 400 -> 200, low-pass retuned (see add_reset_gain_sch.py)
    fp(ref).SetValue(val)

for t in DOOMED:
    b.Remove(t)
b.Save(sys.argv[1])
print("rework applied,", len(DOOMED), "tracks/vias removed")
