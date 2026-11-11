"""Place the GD25WQ64E flash (U2) and its 100 nF cap (C4) left of the BM20BC and give U1/U2/C4 the FLASH_* nets.
Run with KiCad's python from the LeoPatch_v2 folder, after add_flash_sch.py, with KiCad closed. Routing is left to the PCB editor."""
import wx
app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew
from pcbnew import FromMM as MM

PCB = "LeoPatch_v2.kicad_pcb"
FP = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/"
SHEET = "/ab00b617-dce4-5dd5-bd30-81c8a7690bc0/"
b = pcbnew.LoadBoard(PCB)
assert not b.FindFootprintByReference("U2"), "flash already placed"

def net(name):
    n = b.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(b, name); b.Add(n)
    return n

F = "/BM20BC module/FLASH_"
u1_pads = {"B2": "SCK", "B3": "IO3", "B4": "IO2", "B5": "IO1", "B6": "CS", "E2": "IO0"}
u1 = b.FindFootprintByReference("U1")
for p in u1.Pads():
    if p.GetNumber() in u1_pads:
        old = p.GetNet()
        p.SetNet(net(F + u1_pads[p.GetNumber()]))
        if old.GetNetCode() > 0:
            b.Remove(old)

def place(lib, name, ref, val, uid, x, y, rot, nets):
    f = pcbnew.FootprintLoad(FP + lib, name)
    f.SetFPID(pcbnew.LIB_ID(lib.replace(".pretty", ""), name))
    f.SetReference(ref); f.SetValue(val)
    f.SetPath(pcbnew.KIID_PATH(SHEET + uid))
    f.SetSheetname("BM20BC module"); f.SetSheetfile("LeoPatch_MCU.kicad_sch")
    b.Add(f)
    f.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y))); f.SetOrientationDegrees(rot)
    for p in f.Pads():
        p.SetNet(net(nets[p.GetNumber()]))
    return f

# rot 180: pins 4..1 (GND, IO2, IO1, CS) face the module top to bottom, matching the B4/B5/B6 escape order
place("Package_SO.pretty", "SOIC-8_3.9x4.9mm_P1.27mm", "U2", "GD25WQ64ESIGR",
      "39a78684-c295-4783-8fe1-bf39eed0eff4", 138.0, 112.0, 180,
      {"1": F + "CS", "2": F + "IO1", "3": F + "IO2", "4": "GND",
       "5": F + "IO0", "6": F + "SCK", "7": F + "IO3", "8": "+3V3"})
# C4 just left of U2 pin 8 (VCC, bottom-left at rot 180), +3V3 pad toward the pin
place("Capacitor_SMD.pretty", "C_0603_1608Metric", "C4", "100nF",
      "105f54b2-d368-4b41-a0d9-e3422d5a0905", 132.9, 113.3, 90,
      {"1": "+3V3", "2": "GND"})

filler = pcbnew.ZONE_FILLER(b); filler.Fill(b.Zones())
b.Save(PCB)
print("ok")
