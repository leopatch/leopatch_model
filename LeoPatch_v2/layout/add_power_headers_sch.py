"""Add three single power pins to the Power sheet (single pins, spaced apart, so alligator clips fit):
  J103 "VIN": VBAT (the regulator input, after the battery and USB diodes)
  J104 "3V3": +3V3
  J105 "GND"
Run with system python3 from the LeoPatch_v2 folder, with KiCad closed.
The symbol UUIDs are fixed so rework_review.py can link the footprints to them."""
import uuid

SCH = "LeoPatch_Power.kicad_sch"
PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/1bd637cf-7783-5fe2-bdf0-ffd80b334887"
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000a002")
SYM_UUID = {r: str(uuid.uuid5(NS, r)) for r in ("J103", "J104", "J105")}
U = lambda: str(uuid.uuid4())

if __name__ == "__main__":
    t = open(SCH).read()
    assert '(reference "J103")' not in t, "already added"

    def block(s, start):
        d = 0
        for j in range(start, len(s)):
            if s[j] == "(": d += 1
            elif s[j] == ")":
                d -= 1
                if d == 0: return s[start:j + 1]

    lib = open("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/Connector_Generic.kicad_sym").read()
    sym = block(lib, lib.index('(symbol "Conn_01x01"\n'))
    sym = sym.replace('(symbol "Conn_01x01"', '(symbol "Connector_Generic:Conn_01x01"', 1)
    lb = block(t, t.index("(lib_symbols"))
    t = t.replace(lb, lb[:-1] + "\t" + sym + "\n\t)", 1)

    def prop(k, v, x, y, hide=False, just=None):
        e = "\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
        extra = (f"\t\t\t(justify {just})\n" if just else "") + ("\t\t\t(hide yes)\n" if hide else "")
        return f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n{e}{extra}\t\t\t)\n\t\t)\n'

    def symbol(lib_id, ref, val, x, y, props, pins, bom=True, refxy=None, valxy=None, refhide=False, just=None):
        uid = SYM_UUID.get(ref) or U()
        s = f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
        s += f'\t\t(in_bom {"yes" if bom else "no"})\n\t\t(on_board {"yes" if bom else "no"})\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{uid}")\n'
        s += prop("Reference", ref, *(refxy or (x, y)), hide=refhide, just=just)
        s += prop("Value", val, *(valxy or (x, y)), just=just)
        for k, v in props:
            s += prop(k, v, x, y, hide=True)
        for p in pins:
            s += f'\t\t(pin "{p}"\n\t\t\t(uuid "{U()}")\n\t\t)\n'
        s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v2"\n\t\t\t\t(path "{PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
        return s

    pwr = iter(range(120, 130))
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

    def pin(ref, val, x, y):         # Conn_01x01: its pin is at (x - 5.08, y)
        return symbol("Connector_Generic:Conn_01x01", ref, val, x, y,
                      [("Footprint", "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"), ("Datasheet", "~"),
                       ("Description", "Generic connector, single row, 01x01")],
                      ["1"], refxy=(x + 2.54, y - 1.27), valxy=(x + 2.54, y + 1.27), just="left")

    new = ""
    X = 259.08
    Y = 121.92
    new += pin("J103", "VIN", X, Y) + wire(X - 5.08, Y, X - 12.7, Y)
    new += (f'\t(label "VBAT"\n\t\t(at {X - 12.7:g} {Y:g} 180)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify right bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += text("J103 VIN: external supply in, in parallel with the batteries and USB (joins after their diodes,\\nso it cannot back-feed either). 3.6 - 6 V. Clip the supply's minus to J105.", 228.6, 114.3)
    Y = 137.16
    new += pin("J104", "3V3", X, Y) + wire(X - 5.08, Y, X - 12.7, Y) + p3v3(X - 12.7, Y)
    new += text("J104 3V3: 3.3 V rail out (or in from a bench supply: pull the JP101 jumper first).", 228.6, 129.54)
    Y = 152.4
    new += pin("J105", "GND", X, Y) + wire(X - 5.08, Y, X - 12.7, Y) + gnd(X - 12.7, Y)

    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
    t = t[:k] + new + t[k:]
    open(SCH, "w").write(t)
    print("ok", SYM_UUID)
