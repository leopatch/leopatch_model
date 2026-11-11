"""Add the GD25WQ64E external flash (U2 + C4) to the MCU sheet on P2.00-P2.05, wired like the nRF54LM20 DK.
Run with system python3 from the LeoPatch_v2 folder, with KiCad closed."""
import re, uuid

SCH = "LeoPatch_MCU.kicad_sch"
LIB = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols/Memory_Flash.kicad_sym"
PATH = "/7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90/ab00b617-dce4-5dd5-bd30-81c8a7690bc0"
U = lambda: str(uuid.uuid4())
t = open(SCH).read()
assert "FLASH_CS" not in t, "flash already added"

def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]

# 1. library symbol (same pinout as GD25WQ64E SOP-8)
lib = open(LIB).read()
sym = block(lib, lib.index('(symbol "W25Q32JVSS"'))
sym = sym.replace('(symbol "W25Q32JVSS"', '(symbol "Memory_Flash:W25Q32JVSS"', 1)
i = t.index("(lib_symbols")
lb = block(t, i)
t = t.replace(lb, lb[:-1] + "\t" + sym + "\n\t)", 1)

# 2. U1 pins: drop the no-connect flags, add labels (pin end x=215.9, pins face right)
u1 = {"FLASH_SCK": 121.92, "FLASH_IO3": 124.46, "FLASH_IO2": 127.0,
      "FLASH_IO1": 129.54, "FLASH_CS": 132.08, "FLASH_IO0": 165.1}
for y in u1.values():
    yy = ("%g" % y)
    m = re.search(r"\t\(no_connect\n\t\t\(at 215\.9 " + re.escape(yy) + r"\)\n\t\t\(uuid \"[^\"]+\"\)\n\t\)\n", t)
    assert m, y
    t = t[:m.start()] + t[m.end():]

def label(name, x, y, ang):
    just = "left bottom" if ang == 0 else "right bottom"
    return f'''\t(label "{name}"
\t\t(at {x:g} {y:g} {ang})
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify {just})
\t\t)
\t\t(uuid "{U()}")
\t)
'''

def prop(k, v, x, y, hide=False, just=None):
    e = "\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n"
    extra = (f"\t\t\t(justify {just})\n" if just else "") + ("\t\t\t(hide yes)\n" if hide else "")
    return f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n{e}{extra}\t\t\t)\n\t\t)\n'

def symbol(lib_id, ref, val, x, y, props, pins, bom=True, refxy=None, valxy=None, refhide=False, just=None):
    s = f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x:g} {y:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
    s += f'\t\t(in_bom {"yes" if bom else "no"})\n\t\t(on_board {"yes" if bom else "no"})\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{U()}")\n'
    s += prop("Reference", ref, *(refxy or (x, y)), hide=refhide, just=just)
    s += prop("Value", val, *(valxy or (x, y)), just=just)
    for k, v in props:
        s += prop(k, v, x, y, hide=True)
    for p in pins:
        s += f'\t\t(pin "{p}"\n\t\t\t(uuid "{U()}")\n\t\t)\n'
    s += f'\t\t(instances\n\t\t\t(project "LeoPatch_v2"\n\t\t\t\t(path "{PATH}"\n\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
    return s

pwr = iter(range(510, 520))
def p3v3(x, y):
    return symbol("power:+3V3", f"#PWR{next(pwr)}", "+3V3", x, y,
                  [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"+3V3\\"')],
                  ["1"], bom=False, refxy=(x, y - 7.62), valxy=(x, y - 3.556), refhide=True)
def gnd(x, y):
    return symbol("power:GND", f"#PWR{next(pwr)}", "GND", x, y,
                  [("Footprint", ""), ("Datasheet", ""), ("Description", 'Power symbol creates a global label with name \\"GND\\" , ground')],
                  ["1"], bom=False, refxy=(x, y + 6.35), valxy=(x, y + 3.81), refhide=True)

new = ""
for name, y in u1.items():
    new += label(name, 215.9, y, 0)

# 3. U2 flash at (279.4, 81.28): signal pins on the left at x=269.24, VCC top, GND bottom
X, Y = 279.4, 81.28
new += symbol("Memory_Flash:W25Q32JVSS", "U2", "GD25WQ64ESIGR", X, Y,
              [("Footprint", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
               ("Datasheet", "~"),
               ("Description", "GigaDevice GD25WQ64E 64 Mbit 1.65-3.6 V SPI/QSPI NOR flash, SOP-8 150 mil")],
              [str(n) for n in range(1, 9)], refxy=(X + 2.54, Y - 12.7), valxy=(X + 2.54, Y + 12.7), just="left")
for name, py in (("FLASH_CS", 7.62), ("FLASH_SCK", 5.08), ("FLASH_IO0", 2.54),
                 ("FLASH_IO1", 0), ("FLASH_IO2", -2.54), ("FLASH_IO3", -5.08)):
    new += label(name, X - 10.16, Y - py, 180)
new += p3v3(X, Y - 12.7) + gnd(X, Y + 12.7)

# 4. C4 100 nF decoupling next to U2 VCC
CX = 299.72
new += symbol("Device:C", "C4", "100nF", CX, Y,
              [("Footprint", "Capacitor_SMD:C_0603_1608Metric"), ("Datasheet", "~"), ("Description", "Unpolarized capacitor")],
              ["1", "2"], refxy=(CX + 2.54, Y - 1.27), valxy=(CX + 2.54, Y + 1.27), just="left")
new += p3v3(CX, Y - 3.81) + gnd(CX, Y + 3.81)

new += f'''\t(text "External flash: GD25WQ64E (8 MB) on P2.00-P2.05, same pins as the nRF54LM20 DK flash.\\nPlace C4 next to U2 pin 8."
\t\t(exclude_from_sim no)
\t\t(at 254 58.42 0)
\t\t(effects
\t\t\t(font
\t\t\t\t(size 1.27 1.27)
\t\t\t)
\t\t\t(justify left bottom)
\t\t)
\t\t(uuid "{U()}")
\t)
'''
k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
t = t[:k] + new + t[k:]
open(SCH, "w").write(t)
print("ok")
