"""LeoPatch v3: write the ECG front-end sheet for the MAX30003 (replaces the AD8232 sheet).
Run with system python3 from the LeoPatch_v3 folder, with KiCad closed. Keeps J201 / J202 (and their UUIDs)
from the old sheet so the board footprints stay linked. Symbol UUIDs for the new parts are fixed (uuid5) so
build_ecg_pcb.py can link footprints to them."""
import re, uuid

SCH = "LeoPatch_ECG.kicad_sch"
KSYM = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/"
PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/f0d23f52-e0d2-5d2d-be47-e1184c1697c7"
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000b001")
NEW_REFS = ("U201", "U202", "X201", "R201", "R202", "R205",
            "C201", "C202", "C203", "C204", "C205", "C206", "C207", "C208", "C209", "C210", "C211", "C212")
SYM_UUID = {r: str(uuid.uuid5(NS, r)) for r in NEW_REFS}
U = lambda: str(uuid.uuid4())


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


def libsym(text, name, newname=None):
    b = block(text, text.index(f'(symbol "{name}"\n'))
    return b.replace(f'(symbol "{name}"', f'(symbol "{newname or name}"', 1)


# ---------------------------------------------------------------- MAX30003 symbol
def max30003_symbol():
    L = [("ECGP", 6, 20.32), ("ECGN", 7, 17.78), ("CAPP", 9, 12.7), ("CAPN", 10, 10.16), ("CPLL", 11, 5.08),
         ("VREF", 23, 0), ("VCM", 25, -2.54), ("VBG", 27, -5.08)]
    R = [("CSB", 15, 20.32), ("SCLK", 16, 17.78), ("SDI", 17, 15.24), ("SDO", 18, 12.7), ("INTB", 21, 7.62),
         ("INT2B", 20, 5.08), ("FCLK", 14, 0)]
    T = [("AVDD", 22, -5.08), ("DVDD", 13, 0), ("OVDD", 19, 5.08)]
    B = [("AGND", 3, -12.7), ("AGND", 8, -10.16), ("AGND", 28, -7.62), ("DGND", 12, -5.08), ("EP", 29, -2.54),
         ("I.C.", 1, 0), ("I.C.", 2, 2.54), ("I.C.", 4, 5.08), ("I.C.", 5, 7.62), ("I.C.", 24, 10.16), ("I.C.", 26, 12.7)]
    kind = {"ECGP": "input", "ECGN": "input", "CSB": "input", "SCLK": "input", "SDI": "input", "SDO": "output",
            "INTB": "output", "INT2B": "output", "FCLK": "input", "AVDD": "power_in", "DVDD": "power_in", "OVDD": "power_in",
            "AGND": "power_in", "DGND": "power_in", "EP": "passive", "I.C.": "passive"}

    def pin(name, num, x, y, ang):
        return (f'\t\t\t\t(pin {kind.get(name, "passive")} line\n\t\t\t\t\t(at {x:g} {y:g} {ang})\n\t\t\t\t\t(length 2.54)\n'
                f'\t\t\t\t\t(name "{name}"\n\t\t\t\t\t\t(effects\n\t\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t\t)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n'
                f'\t\t\t\t\t(number "{num}"\n\t\t\t\t\t\t(effects\n\t\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t\t\t)\n\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n')
    pins = "".join(pin(n, k, -17.78, y, 0) for n, k, y in L) + "".join(pin(n, k, 17.78, y, 180) for n, k, y in R)
    pins += "".join(pin(n, k, x, 27.94, 270) for n, k, x in T) + "".join(pin(n, k, x, -27.94, 90) for n, k, x in B)

    def prop(k, v, x, y, hide=False):
        return (f'\t\t\t(property "{k}" "{v}"\n\t\t\t\t(at {x:g} {y:g} 0)\n\t\t\t\t(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n'
                + ("\t\t\t\t\t(hide yes)\n" if hide else "") + "\t\t\t\t)\n\t\t\t)\n")
    return ('\t\t(symbol "LeoPatch:MAX30003"\n\t\t\t(exclude_from_sim no)\n\t\t\t(in_bom yes)\n\t\t\t(on_board yes)\n'
            + prop("Reference", "U", 0, 29.21) + prop("Value", "MAX30003CTI+", 0, -30.48)
            + prop("Footprint", "Package_DFN_QFN:TQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm", 0, 0, True)
            + prop("Datasheet", "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX30003.pdf", 0, 0, True)
            + prop("Description", "Single-channel ECG analog front end, 18-bit, SPI, 28-TQFN", 0, 0, True)
            + '\t\t\t(symbol "MAX30003_0_1"\n\t\t\t\t(rectangle\n\t\t\t\t\t(start -15.24 25.4)\n\t\t\t\t\t(end 15.24 -25.4)\n'
            + '\t\t\t\t\t(stroke\n\t\t\t\t\t\t(width 0.254)\n\t\t\t\t\t\t(type default)\n\t\t\t\t\t)\n\t\t\t\t\t(fill\n\t\t\t\t\t\t(type background)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)\n'
            + '\t\t\t(symbol "MAX30003_1_1"\n' + pins + '\t\t\t)\n\t\t\t(embedded_fonts no)\n\t\t)')


# ---------------------------------------------------------------- schematic items
def prop(k, v, x, y, hide=False, just=None):
    e = "\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
    extra = (f"\t\t\t(justify {just})\n" if just else "") + ("\t\t\t(hide yes)\n" if hide else "")
    return f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n{e}{extra}\t\t\t)\n\t\t)\n'


def symbol(lib_id, ref, val, x, y, props, pins, bom=True, refxy=None, valxy=None, refhide=False, just=None, dnp=False):
    uid = SYM_UUID.get(ref) or U()
    s = f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
    s += f'\t\t(in_bom {"yes" if bom else "no"})\n\t\t(on_board {"yes" if bom else "no"})\n\t\t(dnp {"yes" if dnp else "no"})\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{uid}")\n'
    s += prop("Reference", ref, *(refxy or (x, y)), hide=refhide, just=just)
    s += prop("Value", val, *(valxy or (x, y)), just=just)
    for k, v in props:
        s += prop(k, v, x, y, hide=True)
    for p in pins:
        s += f'\t\t(pin "{p}"\n\t\t\t(uuid "{U()}")\n\t\t)\n'
    s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v3"\n\t\t\t\t(path "{PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
    return s


pwr = iter(range(201, 260))
PWRDESC = {"+3V3": 'Power symbol creates a global label with name \\"+3V3\\"', "+1V8": 'Power symbol creates a global label with name \\"+1V8\\"',
           "GND": 'Power symbol creates a global label with name \\"GND\\" , ground'}


def power(name, x, y):
    up = name != "GND"
    return symbol(f"power:{name}", f"#PWR{next(pwr)}", name, x, y,
                  [("Footprint", ""), ("Datasheet", ""), ("Description", PWRDESC[name])], ["1"], bom=False,
                  refxy=(x, y - 7.62 if up else y + 6.35), valxy=(x, y - 3.556 if up else y + 3.81), refhide=True)


def label(name, x, y, ang, glob=False):
    just = {0: "left", 90: "left", 180: "right", 270: "right"}[ang]
    if glob:
        return (f'\t(global_label "{name}"\n\t\t(shape bidirectional)\n\t\t(at {x:g} {y:g} {ang})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
                f'\t\t\t(justify {just})\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    return (f'\t(label "{name}"\n\t\t(at {x:g} {y:g} {ang})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {just} bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')


def wire(*pts):
    s = ""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        s += (f'\t(wire\n\t\t(pts\n\t\t\t(xy {x0:g} {y0:g}) (xy {x1:g} {y1:g})\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n'
              f'\t\t\t(type default)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    return s


def junction(x, y):
    return f'\t(junction\n\t\t(at {x:g} {y:g})\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "{U()}")\n\t)\n'


def nc(x, y):
    return f'\t(no_connect\n\t\t(at {x:g} {y:g})\n\t\t(uuid "{U()}")\n\t)\n'


def text(s, x, y, size=1.27):
    return (f'\t(text "{s}"\n\t\t(exclude_from_sim no)\n\t\t(at {x:g} {y:g} 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size:g} {size:g})\n'
            f'\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')


def passive(kind, ref, val, x, y, top, bottom, fp=None, dnp=False):
    """Vertical R or C at (x, y): pin 1 at y-3.81 (top), pin 2 at y+3.81. top/bottom: a net name (label),
    a power name ('+3V3', '+1V8', 'GND'), or ('global', name)."""
    lib, desc = ("Device:R", "Resistor") if kind == "R" else ("Device:C", "Unpolarized capacitor")
    fp = fp or ("Resistor_SMD:R_0603_1608Metric" if kind == "R" else "Capacitor_SMD:C_0603_1608Metric")
    s = symbol(lib, ref, val, x, y, [("Footprint", fp), ("Datasheet", "~"), ("Description", desc)], ["1", "2"],
               refxy=(x + 2.54, y - 1.27), valxy=(x + 2.54, y + 1.27), just="left", dnp=dnp)
    for net, yy, ang in ((top, y - 3.81, 90), (bottom, y + 3.81, 270)):
        if net in PWRDESC:
            s += power(net, x, yy)
        elif isinstance(net, tuple):
            s += label(net[1], x, yy, ang, glob=True)
        else:
            s += label(net, x, yy, ang)
    return s


if __name__ == "__main__":
    old = open(SCH).read()
    assert "MAX30003" not in old, "already converted"
    power_sch = open("LeoPatch_Power.kicad_sch").read()
    osc = open(KSYM + "Oscillator.kicad_sym").read()
    plib = open(KSYM + "power.kicad_sym").read()

    libs = [libsym(old, n) for n in ("Device:C", "Device:R", "power:+3V3", "power:GND", "Connector_Audio:AudioJack3", "Connector_Generic:Conn_01x03")]
    libs.append(libsym(power_sch, "Regulator_Linear:MCP1703Ax-330xxTT"))
    libs.append(libsym(osc, "SG-3030CM", "Oscillator:SG-3030CM"))
    libs.append(libsym(plib, "+1V8", "power:+1V8"))
    libs.append(max30003_symbol())

    # the two electrode connectors, verbatim (UUIDs kept)
    keep = ""
    for ref in ("J201", "J202"):
        i = old.index(f'(reference "{ref}")'); k = old.rindex("\t(symbol\n", 0, i) + 1
        keep += block(old, k).replace('(project "LeoPatch_v2"', '(project "LeoPatch_v3"') + "\n"

    X, Y = 139.7, 88.9                      # MAX30003
    body = symbol("LeoPatch:MAX30003", "U201", "MAX30003CTI+", X, Y,
                  [("Footprint", "Package_DFN_QFN:TQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm"),
                   ("Datasheet", "https://www.analog.com/media/en/technical-documentation/data-sheets/MAX30003.pdf"),
                   ("Description", "Single-channel ECG analog front end, 18-bit, SPI, 28-TQFN")],
                  [str(n) for n in range(1, 30)], refxy=(X + 17.78, Y - 29.21), valxy=(X + 17.78, Y - 26.67), just="left")
    LX, RX = X - 17.78, X + 17.78
    for name, dy in (("ECGP", 20.32), ("ECGN", 17.78), ("CAPP", 12.7), ("CAPN", 10.16), ("CPLL", 5.08), ("VREF", 0), ("VCM", -2.54), ("VBG", -5.08)):
        body += label(name, LX, Y - dy, 180)
    for name, dy in (("ECG_CS", 20.32), ("ECG_SCK", 17.78), ("ECG_MOSI", 15.24), ("ECG_MISO", 12.7), ("ECG_INT", 7.62)):
        body += label(name, RX, Y - dy, 0, glob=True)
    body += nc(RX, Y - 5.08) + label("FCLK", RX, Y, 0)
    body += power("+1V8", X - 5.08, Y - 27.94) + power("+1V8", X, Y - 27.94) + power("+3V3", X + 5.08, Y - 27.94)
    xs = [X + dx for dx in (-12.7, -10.16, -7.62, -5.08, -2.54, 0, 2.54, 5.08, 7.62, 10.16, 12.7)]
    for x in xs:
        body += wire((x, Y + 27.94), (x, Y + 30.48))
    body += wire(*[(x, Y + 30.48) for x in xs]) + "".join(junction(x, Y + 30.48) for x in xs[1:-1])
    body += wire((xs[-1], Y + 30.48), (xs[-1] + 5.08, Y + 30.48)) + power("GND", xs[-1] + 5.08, Y + 30.48)

    # input network (left), filter / reference caps (right of the inputs)
    body += passive("R", "R201", "1k", 109.22, 71.12, "LA", "ECGP")
    body += passive("R", "R202", "1k", 101.6, 71.12, "RA", "ECGN")
    body += passive("C", "C201", "1nF C0G", 93.98, 71.12, "LA", "RA")
    body += passive("C", "C202", "10uF X7R", 109.22, 91.44, "CAPP", "CAPN")
    body += passive("C", "C203", "1nF C0G", 101.6, 91.44, "CPLL", "GND")
    body += passive("C", "C204", "10uF", 93.98, 91.44, "VREF", "GND")
    body += passive("C", "C205", "10uF", 86.36, 91.44, "VCM", "GND")
    body += passive("C", "C206", "1uF", 78.74, 91.44, "VBG", "GND")
    # supplies
    body += passive("C", "C207", "10uF", 165.1, 50.8, "+1V8", "GND")
    body += passive("C", "C208", "100nF", 172.72, 50.8, "+1V8", "GND")
    body += passive("C", "C209", "10uF", 185.42, 50.8, "+3V3", "GND")
    body += passive("C", "C210", "100nF", 193.04, 50.8, "+3V3", "GND")
    # 1.8 V regulator
    UX, UY = 215.9, 88.9
    body += symbol("Regulator_Linear:MCP1703Ax-330xxTT", "U202", "MCP1703A-1802E/TT", UX, UY,
                   [("Footprint", "Package_TO_SOT_SMD:SOT-23"), ("Datasheet", "~"), ("Description", "250mA LDO, 1.8 V, SOT-23")],
                   ["1", "2", "3"], refxy=(UX, UY - 8.89), valxy=(UX, UY - 6.35))
    body += wire((UX - 7.62, UY), (UX - 12.7, UY)) + power("+3V3", UX - 12.7, UY)
    body += wire((UX + 7.62, UY), (UX + 12.7, UY)) + power("+1V8", UX + 12.7, UY)
    body += power("GND", UX, UY + 7.62)
    body += passive("C", "C211", "1uF", UX - 12.7, UY + 6.35, "+3V3", "GND")
    body += passive("C", "C212", "1uF", UX + 12.7, UY + 6.35, "+1V8", "GND")
    # 32.768 kHz oscillator and the INTB pull-up
    OX, OY = 177.8, 101.6
    body += symbol("Oscillator:SG-3030CM", "X201", "SG-3030CM 32.768kHz", OX, OY,
                   [("Footprint", "Oscillator:Oscillator_SMD_SeikoEpson_SG3030CM"), ("Datasheet", "~"),
                    ("Description", "32.768 kHz CMOS oscillator, 3.2x1.5 mm, 1.5-5.5 V")],
                   ["1", "2", "3", "4"], refxy=(OX, OY - 11.43), valxy=(OX, OY + 11.43))
    body += wire((OX - 2.54, OY - 7.62), (OX - 2.54, OY - 10.16), (OX, OY - 10.16), (OX + 2.54, OY - 10.16), (OX + 2.54, OY - 7.62))
    body += junction(OX, OY - 10.16) + power("+3V3", OX, OY - 10.16) + power("GND", OX, OY + 7.62) + label("FCLK", OX + 7.62, OY, 0)
    body += passive("R", "R205", "100k", 165.1, 71.12, "+3V3", ("global", "ECG_INT"))
    # electrode labels (same spots as before: J201 pins at x=43.18, J202 pins at x=109.22)
    for name, y in (("RA", 144.78), ("LA", 147.32), ("RL", 149.86)):
        body += wire((45.72, y), (43.18, y)) + label(name, 43.18, y, 180)
    for name, y in (("RL", 144.78), ("LA", 147.32), ("RA", 149.86)):
        body += wire((106.68, y), (109.22, y)) + label(name, 109.22, y, 0)

    body += text("ECG FRONT END: MAX30003, two-electrode (Figure 11 of the datasheet).\\nECGP = LA, ECGN = RA (lead I). The third electrode (RL) is not used by the chip; its jack and header pins are only tied together.", 25.4, 40.64)
    body += text("C202 sets the analog high-pass: 10 uF = 0.04 Hz (waveform quality), 1 uF = 0.4 Hz (more motion rejection).\\nGain (20/40/80/160), 0.5 Hz digital high-pass and 40/100/150 Hz low-pass are set over SPI.", 25.4, 110.49)
    body += text("AVDD/DVDD 1.8 V from U202; OVDD = 3.3 V so the SPI lines match the module. FCLK must be 32.768 kHz (X201).", 25.4, 118.11)
    body += text("Module pins: SCK P1.16 (E9), MOSI P1.06 (K8), MISO P1.02 (A8), CS P0.05 (D9), INT P3.07 (C9).", 25.4, 125.73)
    body += text("Lead cable: 3.5 mm TRS plug, Tip = RL, Ring = LA, Sleeve = RA. J202 = backup solder pads.", 25.4, 160.02)

    sheet_uuid = re.search(r'\(uuid "([^"]+)"', old).group(1)
    head = (f'(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n\t(uuid "{sheet_uuid}")\n'
            '\t(paper "A3")\n\t(title_block\n\t\t(title "LeoPatch - ECG front end (MAX30003)")\n\t\t(date "2026-11-11")\n\t\t(rev "3.0")\n'
            '\t\t(company "Rice ELEC 494 - LeoPatch")\n\t)\n\t(lib_symbols\n' + "\n".join(libs) + "\n\t)\n")
    open(SCH, "w").write(head + keep + body + "\t(sheet_instances\n\t\t(path \"/\"\n\t\t\t(page \"1\")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n")
    print("ok")
