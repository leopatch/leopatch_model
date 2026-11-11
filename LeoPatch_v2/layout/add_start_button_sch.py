"""Add the START button (SW302) and free a wake-capable pin for it.
  U1.H9 (P1.09) was LED_RED -> now BTN_START (port 1, same port as the EXPORT button)
  U1.K2 (P3.10) was unused  -> now LED_RED (an LED works on any pin)
Run with system python3 from the LeoPatch_v2 folder, with KiCad closed."""
import re, uuid

NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000a003")
SYM_UUID = {"SW302": str(uuid.uuid5(NS, "SW302"))}
U = lambda: str(uuid.uuid4())
UI_PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/707f3a77-758b-5a35-aad2-4bc90a18387e"


def glabel(name, x, y, ang):
    return (f'\t(global_label "{name}"\n\t\t(shape bidirectional)\n\t\t(at {x:g} {y:g} {ang})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {"right" if ang == 180 else "left"})\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')


def insert(t, new):
    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
    return t[:k] + new + t[k:]


if __name__ == "__main__":
    # --- MCU sheet: swap the two pins
    t = open("LeoPatch_MCU.kicad_sch").read()
    assert "BTN_START" not in t, "already added"
    a = '(global_label "LED_RED"\n\t\t(shape bidirectional)\n\t\t(at 162.56 124.46 180)'
    assert t.count(a) == 1
    t = t.replace(a, a.replace("LED_RED", "BTN_START"))
    m = re.search(r'\t\(no_connect\n\t\t\(at 215\.9 238\.76\)\n\t\t\(uuid "[^"]+"\)\n\t\)\n', t)
    assert m, "K2 no-connect flag not found"
    t = t[:m.start()] + t[m.end():]
    t = insert(t, glabel("LED_RED", 215.9, 238.76, 0))
    open("LeoPatch_MCU.kicad_sch", "w").write(t)

    # --- UI sheet: SW302 below SW301, wired the same way (pin 1 to the MCU, pin 2 to GND, internal pull-up)
    t = open("LeoPatch_UI.kicad_sch").read()

    def prop(k, v, x, y, hide=False):
        return (f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
                + ("\t\t\t\t(hide yes)\n" if hide else "") + "\t\t\t)\n\t\t)\n")

    def symbol(lib_id, ref, val, x, y, props, pins, bom=True, refxy=None, valxy=None, refhide=False):
        s = f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
        s += f'\t\t(in_bom {"yes" if bom else "no"})\n\t\t(on_board {"yes" if bom else "no"})\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{SYM_UUID.get(ref) or U()}")\n'
        s += prop("Reference", ref, *(refxy or (x, y)), hide=refhide) + prop("Value", val, *(valxy or (x, y)))
        for k, v in props:
            s += prop(k, v, x, y, hide=True)
        for p in pins:
            s += f'\t\t(pin "{p}"\n\t\t\t(uuid "{U()}")\n\t\t)\n'
        s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v2"\n\t\t\t\t(path "{UI_PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
        return s

    X, Y = 205.74, 76.2
    new = symbol("Switch:SW_Push", "SW302", "START", X, Y,
                 [("Footprint", "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92"), ("Datasheet", "~"), ("Description", "Push button switch, generic, two pins")],
                 ["1", "2"], refxy=(X, Y - 3.81), valxy=(X, Y + 3.81))
    new += glabel("BTN_START", X - 5.08, Y, 180)
    new += (f'\t(wire\n\t\t(pts\n\t\t\t(xy {X + 5.08:g} {Y:g}) (xy 214.63 {Y:g})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += symbol("power:GND", "#PWR305", "GND", 214.63, Y,
                  [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"GND\\" , ground')],
                  ["1"], bom=False, refxy=(214.63, Y + 6.35), valxy=(214.63, Y + 3.81), refhide=True)
    open("LeoPatch_UI.kicad_sch", "w").write(insert(t, new))
    print("ok", SYM_UUID)
