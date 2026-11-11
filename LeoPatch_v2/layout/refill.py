"""Refill all copper zones and save. Run with KiCad's python after any script that moves tracks or vias."""
import sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(sys.argv[1])
print("zones refilled")
