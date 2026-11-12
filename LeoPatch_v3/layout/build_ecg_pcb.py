"""LeoPatch v3 board: swap the AD8232 front end for the MAX30003.

  PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
  $PY layout/build_ecg_pcb.py LeoPatch_v3.kicad_pcb <netlist.xml>     (netlist: kicad-cli sch export netlist --format kicadxml)
  $PY layout/refill.py LeoPatch_v3.kicad_pcb ; then DRC

Removes the AD8232 and its passives, TP3 and R215, and every track of the old ECG nets; places the MAX30003 (U201,
turned 90 degrees so its SPI pins face the module), its capacitors, the 1.8 V regulator U202, the 32.768 kHz
oscillator X201 and the INT pull-up R205; wires everything. Pad nets come from the netlist. The electrode jack J201
and header J202 stay where they were.

Layout: inputs (ECGP/ECGN) on the chip's south edge, west to the jack; reference caps on the west edge; CHPF, CPLL,
regulator and oscillator on the east; SPI on the north edge. SPI: MISO (A8), MOSI (K8) and CS (D9) on the bottom
layer as three parallel 45-degree lanes; SCK (E9) and INT (C9) on the top layer along y = 122.6 / 121.4.
"""
import os, re, sys, uuid
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_ecg_sheet import SYM_UUID

b = pcbnew.LoadBoard(sys.argv[1])
MM, mm = pcbnew.FromMM, pcbnew.ToMM
P = lambda x, y: pcbnew.VECTOR2I(MM(x), MM(y))
F, B = pcbnew.F_Cu, pcbnew.B_Cu
FPLIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
SHEET = "/f0d23f52-e0d2-5d2d-be47-e1184c1697c7/"
assert b.FindFootprintByReference("U201").GetValue().startswith("AD8232"), "already converted"

# ---------------------------------------------------------------- netlist: (ref, pin) -> net name
xml = open(sys.argv[2]).read()
PIN_NET = {}
for name, body in re.findall(r'<net code="\d+" name="([^"]+)"[^>]*>(.*?)</net>', xml, re.S):
    for ref, pin in re.findall(r'ref="([^"]+)" pin="([^"]+)"', body):
        PIN_NET[(ref, pin)] = name


def net(name):
    n = b.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(b, name); b.Add(n)
    return n


# ---------------------------------------------------------------- 1. clear the old front end
OLD_FP = [f"R2{n:02d}" for n in range(1, 21)] + [f"C2{n:02d}" for n in range(1, 8)] + ["U201", "TP3"]
OLD_NETS = {"ECG_OUT", "ECG_LO+", "ECG_LO-", "ECG_SDN"}
doomed = []
for f in list(b.GetFootprints()):
    if f.GetReference() in OLD_FP:
        doomed.append(f)
for t in list(b.GetTracks()):
    n = t.GetNetname()
    if n.startswith("/ECG front end/") or n in OLD_NETS:
        doomed.append(t)
for d in b.GetDrawings():
    if d.GetClass() == "PCB_TEXT" and d.GetText() == "ECG":
        doomed.append(d)

# ---------------------------------------------------------------- 2. place
def place(lib, name, ref, val, x, y, rot, ref_on_fab=True):
    f = pcbnew.FootprintLoad(FPLIB + lib, name)
    f.SetFPID(pcbnew.LIB_ID(lib.replace(".pretty", ""), name))
    f.SetReference(ref); f.SetValue(val)
    f.SetPath(pcbnew.KIID_PATH(SHEET + SYM_UUID[ref]))
    f.SetSheetname("ECG front end"); f.SetSheetfile("LeoPatch_ECG.kicad_sch")
    b.Add(f)
    f.SetPosition(P(x, y)); f.SetOrientationDegrees(rot)
    for p in f.Pads():
        key = (ref, p.GetNumber())
        if key in PIN_NET:
            p.SetNet(net(PIN_NET[key]))
        elif ref == "U201":           # the four paste sub-pads of the exposed pad share pad 29's net
            p.SetNet(net(PIN_NET[(ref, "29")]))
    r = f.Reference(); r.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8))); r.SetTextThickness(MM(0.12))
    if ref_on_fab:
        r.SetLayer(pcbnew.F_Fab)
    return f


C = ("Capacitor_SMD.pretty", "C_0603_1608Metric")
R = ("Resistor_SMD.pretty", "R_0603_1608Metric")
place("Package_DFN_QFN.pretty", "TQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm", "U201", "MAX30003CTI+", 128.0, 130.0, 90, ref_on_fab=False)
place(*R, "R201", "1k", 126.8, 134.2, 0)              # ECGP series
place(*R, "R202", "1k", 126.8, 135.8, 0)              # ECGN series
place(*C, "C201", "1nF C0G", 124.4, 135.0, 90)         # differential input cap
place(*C, "C202", "10uF X7R", 133.0, 130.75, 90)       # CHPF
place(*C, "C203", "1nF C0G", 132.6, 127.0, 0)          # CPLL
place(*C, "C204", "10uF", 123.0, 129.0, 0)             # VREF
place(*C, "C205", "10uF", 123.0, 130.6, 0)             # VCM
place(*C, "C206", "1uF", 123.0, 132.2, 0)              # VBG
place(*C, "C207", "10uF", 123.0, 125.6, 0)             # AVDD
place(*C, "C208", "100nF", 123.0, 124.0, 0)            # AVDD
place(*C, "C209", "10uF", 130.0, 124.8, 90)            # +3V3 near the chip
place(*C, "C210", "100nF", 127.0, 124.8, 90)           # OVDD
place("Package_TO_SOT_SMD.pretty", "SOT-23", "U202", "MCP1703A-1802E/TT", 137.0, 129.4, 0)
place(*C, "C211", "1uF", 139.2, 130.2, 90)             # regulator in
place(*C, "C212", "1uF", 135.2, 131.6, 90)             # regulator out
place("Oscillator.pretty", "Oscillator_SMD_SeikoEpson_SG3030CM", "X201", "SG-3030CM", 133.4, 124.9, 0)
place(*R, "R205", "100k", 124.6, 120.2, 90)            # INT pull-up

# ---------------------------------------------------------------- 3. route
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


E = "/ECG front end/"
# -- grounds: every GND pin of U201 links to the exposed pad (0.2 mm bridges under the chip), two vias in the pad
for x in (126.5, 127.0, 127.5, 128.0, 128.5):            # pins 1-5 (south edge)
    path("GND", F, [(x, 131.9), (x, 131.6)])
for y in (129.5, 130.5, 131.5):                          # pins 24, 26, 28 (west edge)
    path("GND", F, [(126.1, y), (126.4, y)])
for y in (129.5, 131.5):                                 # pins 12 (DGND), 8 (east edge)
    path("GND", F, [(129.9, y), (129.6, y)])
via("GND", 127.4, 129.4); via("GND", 128.6, 130.6)

# -- west edge: AVDD (22), VREF (23), VCM (25), VBG (27)
path(E + "VREF", F, [(125.64, 129.0), (123.775, 129.0)])
path(E + "VCM", F, [(125.64, 130.0), (124.9, 130.0), (124.3, 130.6), (123.775, 130.6)])
path(E + "VBG", F, [(125.64, 131.0), (124.9, 131.0), (124.0, 131.9), (123.775, 132.2)])
for y in (129.0, 130.6, 132.2, 125.6, 124.0):            # cap GND ends
    path("GND", F, [(122.225, y), (121.3, y)]); via("GND", 121.3, y)
path("+1V8", F, [(125.64, 128.5), (125.1, 127.96), (125.1, 126.1), (124.6, 125.6), (123.775, 125.6)])
path("+1V8", F, [(124.6, 125.6), (124.6, 124.0), (123.775, 124.0)])
path("+1V8", F, [(124.6, 124.0), (124.6, 123.2)]); via("+1V8", 124.6, 123.2)
# +1V8 from the regulator, bottom layer round the south of the chip
path("+1V8", B, [(124.6, 123.2), (124.6, 133.8), (136.0, 133.8), (136.6, 133.2), (136.6, 132.4)])
via("+1V8", 136.6, 132.4)
path("+1V8", F, [(136.6, 132.4), (136.6, 130.9), (136.06, 130.35)])

# -- south edge: ECGP (6, x=129.0), ECGN (7, x=129.5) -> 1k resistors -> electrodes
path(E + "ECGP", F, [(129.0, 132.36), (129.0, 133.4), (128.2, 134.2), (127.575, 134.2)])
path(E + "ECGN", F, [(129.5, 132.36), (129.5, 135.3), (129.0, 135.8), (127.575, 135.8)])
path(E + "LA", F, [(126.025, 134.2), (124.4, 134.2), (113.0, 134.2), (112.0, 135.2)])          # -> jack ring
path(E + "LA", F, [(125.2, 134.2), (125.2, 138.5), (126.54, 139.84), (126.54, 142.5)])          # -> J202.2
path(E + "RA", F, [(126.025, 135.8), (124.4, 135.8), (114.0, 135.8), (113.0, 136.8), (113.0, 137.8), (105.4, 137.8),
                   (104.2, 136.6), (104.2, 134.6)])                                              # -> jack sleeve
path(E + "RA", F, [(126.025, 136.1), (126.025, 136.7), (129.08, 139.75), (129.08, 142.5)])      # -> J202.3
path(E + "RL", F, [(124.0, 143.0), (124.0, 144.3), (105.0, 144.3), (104.4, 144.3)])             # J202.1 <-> jack tip

# -- east edge: CAPP (9, y=131.0), CAPN (10, 130.5), CPLL (11, 130.0), DVDD (13, 129.0), FCLK (14, 128.5)
path(E + "CAPP", F, [(130.36, 131.0), (131.9, 131.0), (132.5, 131.525), (133.0, 131.525)])
path(E + "CAPN", F, [(130.36, 130.5), (131.9, 130.5), (132.5, 129.975), (133.0, 129.975)])
path(E + "CPLL", F, [(130.36, 130.0), (131.1, 130.0), (131.5, 129.6), (131.5, 127.4), (131.825, 127.0)])
path("GND", F, [(133.375, 127.0), (134.3, 127.8)]); via("GND", 134.3, 127.8)
path("+1V8", F, [(130.36, 129.0), (130.9, 129.0)]); via("+1V8", 130.9, 129.0)
path("+1V8", B, [(130.9, 129.0), (135.6, 129.0)]); via("+1V8", 135.6, 129.0)
path("+1V8", F, [(135.6, 129.0), (135.6, 129.75), (136.06, 129.75), (136.06, 130.35)])
path(E + "FCLK", F, [(130.36, 128.5), (130.6, 128.3), (130.6, 127.9), (131.0, 127.5), (131.0, 123.9), (131.5, 123.4),
                     (134.3, 123.4), (134.725, 123.85), (134.725, 124.3)])
# oscillator: pad 4 Vcc and pad 1 VIO to +3V3, pad 2 GND
path("+3V3", F, [(132.075, 124.3), (131.75, 124.9)]); path("+3V3", F, [(132.075, 125.5), (131.75, 124.9)]); via("+3V3", 131.75, 124.9)
path("GND", F, [(134.725, 125.5), (135.6, 125.5)]); via("GND", 135.6, 125.5)
# regulator: VOUT -> C212, VIN <- C211 <- +3V3, GND
path("+1V8", F, [(136.06, 130.35), (135.6, 130.8), (135.2, 130.825)])
path("GND", F, [(135.2, 131.975), (135.2, 133.2)]); via("GND", 135.2, 133.2)
path("+3V3", F, [(137.94, 129.4), (139.2, 129.425), (140.0, 129.4)]); via("+3V3", 140.0, 129.4)
path("GND", F, [(139.2, 130.975), (139.2, 131.9)]); via("GND", 139.2, 131.9)
path("GND", F, [(136.06, 128.45), (136.5, 127.9)]); via("GND", 136.5, 127.9)
# -- north edge: INTB (21, x=126.5), OVDD (19, 127.5), SDO (18, 128.0), SDI (17, 128.5), SCLK (16, 129.0), CSB (15, 129.5)
path("+3V3", F, [(127.5, 127.64), (127.5, 127.3), (127.0, 126.8), (127.0, 125.575)])              # OVDD -> C210
path("+3V3", F, [(127.0, 124.025), (127.0, 123.2)]); via("+3V3", 127.0, 123.2)
path("+3V3", F, [(130.0, 124.025), (130.0, 123.2)]); via("+3V3", 130.0, 123.2)                     # C209
path("GND", F, [(130.0, 125.575), (130.0, 126.4)]); via("GND", 130.0, 126.4)
path("ECG_MISO", F, [(128.0, 127.64), (128.0, 127.3), (127.9, 127.2), (127.9, 126.2)]); via("ECG_MISO", 127.9, 126.2)
path("ECG_MOSI", F, [(128.5, 127.64), (128.5, 126.7)]); via("ECG_MOSI", 128.5, 126.7)
path("ECG_CS", F, [(129.5, 127.64), (129.5, 127.3), (130.1, 127.3), (130.4, 127.0)]); via("ECG_CS", 130.4, 127.0)
# bottom-layer lanes to the module (x + y = const, 45 degrees)
path("ECG_MISO", B, [(127.9, 126.2), (135.6, 126.2), (144.2, 117.6)]); via("ECG_MISO", 144.2, 117.6)
path("ECG_MISO", F, [(144.2, 117.6), (144.2, 115.7), (144.8, 115.1), (146.0, 115.1)])              # -> A8
path("ECG_MOSI", B, [(128.5, 126.7), (138.5, 126.7), (146.3, 118.9), (147.5, 117.7), (151.6, 117.7), (152.4, 116.9),
                     (154.4, 116.9), (155.9, 116.9), (156.25, 116.55), (156.25, 115.6), (155.5, 115.6)])
via("ECG_MOSI", 155.5, 115.6)
path("ECG_MOSI", F, [(155.5, 115.6), (155.15, 115.2), (154.1, 115.2)])                              # -> K8
path("ECG_CS", B, [(130.4, 127.0), (140.6, 127.0), (148.7, 118.9)]); via("ECG_CS", 148.7, 118.9)
path("ECG_CS", F, [(148.7, 118.9), (148.7, 116.56)])                                               # -> D9
# top-layer: SCK along y = 122.6 to E9, INT along y = 121.4 to C9
path("ECG_SCK", F, [(129.0, 127.64), (129.0, 123.4), (129.8, 122.6), (146.2, 122.6), (149.6, 119.2), (149.6, 116.56)])
path("ECG_INT", F, [(126.5, 127.64), (126.5, 127.2), (125.9, 126.6), (125.9, 121.4), (146.2, 121.4), (147.8, 119.8), (147.8, 116.56)])
path("ECG_INT", F, [(125.9, 121.4), (125.0, 121.4), (124.6, 120.975)])                             # R205 pull-up
path("+3V3", F, [(124.6, 119.425), (124.6, 118.6)]); via("+3V3", 124.6, 118.6)

# silkscreen for the electrode polarity
t = pcbnew.PCB_TEXT(b); t.SetText("MAX30003"); t.SetLayer(pcbnew.F_SilkS); t.SetPosition(P(128.0, 137.9))
t.SetTextSize(pcbnew.VECTOR2I(MM(0.8), MM(0.8))); t.SetTextThickness(MM(0.12)); b.Add(t)

for d in doomed:
    b.Remove(d)
b.Save(sys.argv[1])
print("converted; removed", len(doomed), "items")
