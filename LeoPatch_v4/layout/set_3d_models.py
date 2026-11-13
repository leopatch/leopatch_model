"""Attach project-local 3D models (KiCad python):  $PY layout/set_3d_models.py board.kicad_pcb
Paths are ${KIPRJMOD}-relative, so the models show for anyone who opens the project folder.

J201 / J601 CUI (Same Sky) SJ-3523-SMT-TR: 3d/SJ-3523-SMT-TR.step is the maker's STEP (from the SamacSys library
download, in inches, Y up, jack length along -Z, front face at z = 0, feet at y = -2.6 mm, pegs at z = -3.5 / -10.5).
KiCad's stock footprint has the pegs at y = -2.5 / +4.5, so: rotate X +90 (Y up -> board normal), Z 180, then
offset 6 mm along the jack and 2.6 mm up.
The SamacSys licence allows use inside your own organisation but not redistribution as a library part, so the STEP
is not committed to the public git repo: download it from Same Sky / SamacSys and put it in 3d/ (see README)."""
import sys
import wx; app = wx.App(False); wx.DisableAsserts(); wx.Log.EnableLogging(False)
import pcbnew

MODELS = {"J201": ("${KIPRJMOD}/3d/SJ-3523-SMT-TR.step", (0, 6.0, 2.6), (-90, 0, 180)),
          "J601": ("${KIPRJMOD}/3d/SJ-3523-SMT-TR.step", (0, 6.0, 2.6), (-90, 0, 180))}

b = pcbnew.LoadBoard(sys.argv[1])
for ref, (path, off, rot) in MODELS.items():
    f = b.FindFootprintByReference(ref)
    ms = f.Models()
    ms.clear()
    m = pcbnew.FP_3DMODEL()
    m.m_Filename = path
    m.m_Offset = pcbnew.VECTOR3D(*off)
    m.m_Rotation = pcbnew.VECTOR3D(*rot)
    m.m_Scale = pcbnew.VECTOR3D(1, 1, 1)
    ms.push_back(m)
    print(ref, path)
b.Save(sys.argv[1])
