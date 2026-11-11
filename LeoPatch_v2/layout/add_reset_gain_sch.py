"""Schematic part of two changes. Run with system python3 from the LeoPatch_v2 folder, with KiCad closed.

1. RESET button SW303 (small Omron B3U) from nRESET to GND, on the MCU sheet.
2. ECG gain 400 -> 200 for chest leads on newborns (signals up to several mV): R208 330k -> 1M, and the
   low-pass capacitors retuned so the corner stays put: C201 680pF -> 1nF, C203 1.8nF -> 1.2nF.
   Gain = 100 x (1 + R209/R208) = 100 x 2. Low-pass: R206 = R207 = 1M,
   fc = 1 / (2 pi 1M sqrt(C201 C203)) = 145 Hz, Q = sqrt(C201 C203) / (2 C203 + C201 (1 - 2)) = 0.78.
   Clips at about +/-7.8 mV at the electrodes. Any further gain is a multiplication in firmware.
"""
import uuid

NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000a004")
SYM_UUID = {"SW303": str(uuid.uuid5(NS, "SW303"))}
ECG_VALUES = {"R208": "1M", "C201": "1nF", "C203": "1.2nF"}
U = lambda: str(uuid.uuid4())
MCU_PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/ab00b617-dce4-5dd5-bd30-81c8a7690bc0"


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


if __name__ == "__main__":
    # --- ECG sheet: values
    t = open("LeoPatch_ECG.kicad_sch").read()
    for old, new in (('"Value" "330k"', '"Value" "1M"'), ('"Value" "680pF"', '"Value" "1nF"'), ('"Value" "1.8nF"', '"Value" "1.2nF"')):
        assert t.count(old) == 1, old
        i = t.index(old)
        # make sure this value belongs to the part we mean: its reference follows within the same symbol
        sym = block(t, t.rindex("\t(symbol\n", 0, i) + 1)
        ref = {"330k": "R208", "680pF": "C201", "1.8nF": "C203"}[old.split('"')[3]]
        assert f'(reference "{ref}")' in sym, (old, ref)
        t = t.replace(old, new)
    a = "low-pass (~146 Hz) filter network, total gain ~400"
    assert t.count(a) == 1
    t = t.replace(a, "low-pass (~145 Hz) filter network, total gain ~200")
    open("LeoPatch_ECG.kicad_sch", "w").write(t)

    # --- MCU sheet: reset button
    t = open("LeoPatch_MCU.kicad_sch").read()
    assert '(reference "SW303")' not in t, "already added"
    ui = open("LeoPatch_UI.kicad_sch").read()
    sym = block(ui, ui.index('(symbol "Switch:SW_Push"'))
    lb = block(t, t.index("(lib_symbols"))
    t = t.replace(lb, lb[:-1] + "\t" + sym + "\n\t)", 1)

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
        s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v2"\n\t\t\t\t(path "{MCU_PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
        return s

    X, Y = 330.2, 160.02       # SW_Push: pin 1 at x - 5.08, pin 2 at x + 5.08
    new = symbol("Switch:SW_Push", "SW303", "RESET", X, Y,
                 [("Footprint", "Button_Switch_SMD:SW_SPST_B3U-1000P"), ("Datasheet", "~"), ("Description", "Push button switch, generic, two pins")],
                 ["1", "2"], refxy=(X, Y - 3.81), valxy=(X, Y + 3.81))
    new += (f'\t(label "nRESET"\n\t\t(at {X - 5.08:g} {Y:g} 180)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify right bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += (f'\t(wire\n\t\t(pts\n\t\t\t(xy {X + 5.08:g} {Y:g}) (xy {X + 10.16:g} {Y:g})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    new += symbol("power:GND", "#PWR520", "GND", X + 10.16, Y,
                  [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"GND\\" , ground')],
                  ["1"], bom=False, refxy=(X + 10.16, Y + 6.35), valxy=(X + 10.16, Y + 3.81), refhide=True)
    new += (f'\t(text "SW303 pulls nRESET low. R1 (10k) and C3 (100nF) are the pull-up and debounce."\n\t\t(exclude_from_sim no)\n\t\t(at 312.42 149.86 0)\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
    open("LeoPatch_MCU.kicad_sch", "w").write(t[:k] + new + t[k:])
    print("ok", SYM_UUID)
