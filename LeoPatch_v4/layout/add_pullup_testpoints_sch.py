"""Add the FLASH_CS pull-up (R2, 100k to +3V3) and three test points (TP1 GND, TP2 +3V3, TP3 ECG_OUT)
to the MCU sheet. Run with system python3 from the LeoPatch_v3 folder, with KiCad closed.
The symbol UUIDs are fixed so add_pullup_testpoints_pcb.py can link the footprints to them."""
import uuid

SCH = "LeoPatch_MCU.kicad_sch"
LIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/Connector.kicad_sym"
PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/ab00b617-dce4-5dd5-bd30-81c8a7690bc0"
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000a001")
SYM_UUID = {r: str(uuid.uuid5(NS, r)) for r in ("R2", "TP1", "TP2", "TP3")}
U = lambda: str(uuid.uuid4())

if __name__ == "__main__":
    t = open(SCH).read()
    assert '(reference "R2")' not in t, "already added"

    def block(s, start):
        d = 0
        for j in range(start, len(s)):
            if s[j] == "(": d += 1
            elif s[j] == ")":
                d -= 1
                if d == 0: return s[start:j + 1]

    lib = open(LIB).read()
    sym = block(lib, lib.index('(symbol "TestPoint"\n'))
    sym = sym.replace('(symbol "TestPoint"', '(symbol "Connector:TestPoint"', 1)
    lb = block(t, t.index("(lib_symbols"))
    t = t.replace(lb, lb[:-1] + "\t" + sym + "\n\t)", 1)

    def prop(k, v, x, y, hide=False, just=None):
        e = "\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
        extra = (f"\t\t\t(justify {just})\n" if just else "") + ("\t\t\t(hide yes)\n" if hide else "")
        return f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n{e}{extra}\t\t\t)\n\t\t)\n'

    def symbol(lib_id, ref, val, x, y, props, pins, bom=True, refxy=None, valxy=None, refhide=False, just=None):
        uid = SYM_UUID.get(ref) or U()
        s = f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
        s += f'\t\t(in_bom {"yes" if bom and not ref.startswith("TP") else "no"})\n\t\t(on_board {"yes" if bom else "no"})\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{uid}")\n'
        s += prop("Reference", ref, *(refxy or (x, y)), hide=refhide, just=just)
        s += prop("Value", val, *(valxy or (x, y)), just=just)
        for k, v in props:
            s += prop(k, v, x, y, hide=True)
        for p in pins:
            s += f'\t\t(pin "{p}"\n\t\t\t(uuid "{U()}")\n\t\t)\n'
        s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v3"\n\t\t\t\t(path "{PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
        return s

    pwr = iter(range(514, 530))
    def p3v3(x, y):
        return symbol("power:+3V3", f"#PWR{next(pwr)}", "+3V3", x, y,
                      [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"+3V3\\"')],
                      ["1"], bom=False, refxy=(x, y - 7.62), valxy=(x, y - 3.556), refhide=True)
    def gnd(x, y):
        return symbol("power:GND", f"#PWR{next(pwr)}", "GND", x, y,
                      [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"GND\\" , ground')],
                      ["1"], bom=False, refxy=(x, y + 6.35), valxy=(x, y + 3.81), refhide=True)
    def wire(x0, y0, x1, y1):
        return (f'\t(wire\n\t\t(pts\n\t\t\t(xy {x0:g} {y0:g}) (xy {x1:g} {y1:g})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n'
                f'\t\t\t(type default)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    def text(s, x, y):
        return (f'\t(text "{s}"\n\t\t(exclude_from_sim no)\n\t\t(at {x:g} {y:g} 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
                f'\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')

    new = ""
    # R2: FLASH_CS pull-up. Pin 1 (top) to +3V3, pin 2 (bottom) to FLASH_CS.
    X, Y = 320.04, 81.28
    new += symbol("Device:R", "R2", "100k", X, Y,
                  [("Footprint", "Resistor_SMD:R_0603_1608Metric"), ("Datasheet", "~"), ("Description", "Resistor")],
                  ["1", "2"], refxy=(X + 2.54, Y - 1.27), valxy=(X + 2.54, Y + 1.27), just="left")
    new += p3v3(X, Y - 3.81)
    new += (f'\t(label "FLASH_CS"\n\t\t(at {X:g} {Y + 3.81:g} 270)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify right bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += text("R2 keeps the flash deselected while the MCU pins float (reset, programming).", 312.42, 68.58)

    # Test points: pin at the symbol origin, pointing up.
    TY = 121.92
    def tp(ref, val, x):
        return symbol("Connector:TestPoint", ref, val, x, TY,
                      [("Footprint", "TestPoint:TestPoint_Pad_D1.0mm"), ("Datasheet", "~"), ("Description", "test point")],
                      ["1"], refxy=(x, TY - 6.858), valxy=(x, TY - 5.08))
    new += tp("TP1", "GND", 320.04) + wire(320.04, TY, 320.04, TY + 2.54) + gnd(320.04, TY + 2.54)
    # +3V3 symbol points up, so bring it in from the side
    new += tp("TP2", "3V3", 335.28) + wire(335.28, TY, 342.9, TY) + p3v3(342.9, TY)
    new += tp("TP3", "ECG_OUT", 355.6)
    new += (f'\t(global_label "ECG_OUT"\n\t\t(shape bidirectional)\n\t\t(at 355.6 {TY:g} 270)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify right)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += text("Test points (1 mm pads on the top side)", 312.42, 109.22)

    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
    t = t[:k] + new + t[k:]
    open(SCH, "w").write(t)
    print("ok", SYM_UUID)
