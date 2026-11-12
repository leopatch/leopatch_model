"""LeoPatch v4, schematic: add the AD8232 front end back as its own sheet, next to the MAX30003.
Run with system python3 from the LeoPatch_v4 folder, with KiCad closed.

- LeoPatch_ECG_AD8232.kicad_sch = the v2 AD8232 sheet (SparkFun circuit, gain 200), parts renumbered 2xx -> 6xx
  (U601, J601 jack, J602 header, R601-R620, C601-C607), plus test point TP601 on ECG_OUT.
- Root sheet: new sheet block "ECG AD8232" (page 7).
- MCU sheet: module pads for the AD8232 signals (they were the MAX30003's in v3, so new pads):
    F7  P1.29 / AIN3  ECG_OUT   (analog input; nRF54LM20 AIN0-7 = P1.00, P1.31, P1.30, P1.29, P1.06, P1.05, P1.04, P1.03)
    D8  P3.06         ECG_LO+
    E8  P1.25         ECG_LO-
    A7  P3.03         ECG_SDN   (left edge; G8 is boxed in by the LED and button tracks)
Symbol UUIDs are fixed (uuid5) so build_v4_pcb.py can link the footprints."""
import re, uuid

V2 = "../LeoPatch_v2/LeoPatch_ECG.kicad_sch"
NEW = "LeoPatch_ECG_AD8232.kicad_sch"
ROOT_UUID = "7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90"
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c004")
SHEET_UUID = str(uuid.uuid5(NS, "sheet"))
PATH = f"/{ROOT_UUID}/{SHEET_UUID}"
U = lambda: str(uuid.uuid4())
MCU_PINS = {"F7": "ECG_OUT", "D8": "ECG_LO+", "E8": "ECG_LO-", "A7": "ECG_SDN"}


def newref(r):
    m = re.fullmatch(r"(#PWR|[A-Z]+)2(\d\d)", r)
    return f"{m.group(1)}6{m.group(2)}" if m else r


def sym_uuid(ref):
    return str(uuid.uuid5(NS, ref))


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


# ---------------------------------------------------------------- 1. the AD8232 sheet
t = open(V2).read()
assert "AD8232" in t
t = re.sub(r'\(reference "([^"]+)"\)', lambda m: f'(reference "{newref(m.group(1))}")', t)
t = re.sub(r'\(property "Reference" "([^"]+)"', lambda m: f'(property "Reference" "{newref(m.group(1))}"', t)
t = t.replace('(project "LeoPatch_v2"', '(project "LeoPatch_v4"')
t = t.replace(f'(path "/{ROOT_UUID}/f0d23f52-e0d2-5d2d-be47-e1184c1697c7"', f'(path "{PATH}"')
assert "f0d23f52" not in t
t = re.sub(r'\(uuid "[0-9a-f-]+"\)', lambda m: f'(uuid "{U()}")', t)
# placed symbols get fixed UUIDs
out, pos = [], 0
for m in re.finditer(r'\n\t\(symbol\n', t):
    k = m.start() + 1
    blk = block(t, k)
    ref = re.search(r'\(reference "([^"]+)"\)', blk).group(1)
    i = blk.index("(uuid ")                    # first uuid in a placed symbol is its own
    blk2 = blk[:i] + f'(uuid "{sym_uuid(ref)}")' + blk[blk.index(")", i) + 1:]
    out.append(t[pos:k] + blk2); pos = k + len(blk)
t = "".join(out) + t[pos:]
t = re.sub(r'\(title "[^"]*"\)', '(title "LeoPatch v4 - ECG front end B (AD8232)")', t, 1)
t = re.sub(r'\(rev "[^"]*"\)', '(rev "4.0")', t, 1)
t = re.sub(r'\(date "[^"]*"\)', '(date "2026-11-12")', t, 1)
t = t.replace("J202 = backup solder pads", "J602 = backup solder pads")

# test point on ECG_OUT (symbol copied from the MCU sheet)
mcu = open("LeoPatch_MCU.kicad_sch").read()
tp_lib = block(mcu, mcu.index('(symbol "Connector:TestPoint"'))
li = t.index("(lib_symbols") + len("(lib_symbols")
t = t[:li] + "\n\t\t" + tp_lib + t[li:]
TX, TY = 254.0, 132.08
tp = (f'\t(symbol\n\t\t(lib_id "Connector:TestPoint")\n\t\t(at {TX:g} {TY:g} 0)\n\t\t(unit 1)\n\t\t(exclude_from_sim no)\n'
      f'\t\t(in_bom no)\n\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n\t\t(uuid "{sym_uuid("TP601")}")\n')
for k, v, dx, dy, hide in (("Reference", "TP601", 2.54, -2.54, False), ("Value", "ECG_OUT", 2.54, 0, False),
                           ("Footprint", "TestPoint:TestPoint_Pad_D1.0mm", 0, 0, True), ("Datasheet", "~", 0, 0, True),
                           ("Description", "test point", 0, 0, True)):
    tp += (f'\t\t(property "{k}" "{v}"\n\t\t\t(at {TX + dx:g} {TY + dy:g} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n'
           + ("\t\t\t\t(justify left)\n" if not hide else "\t\t\t\t(hide yes)\n") + "\t\t\t)\n\t\t)\n")
tp += (f'\t\t(pin "1"\n\t\t\t(uuid "{U()}")\n\t\t)\n\t\t(instances\n\t\t\t(project "LeoPatch_v4"\n\t\t\t\t(path "{PATH}"\n'
       f'\t\t\t\t\t(reference "TP601")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')
tp += (f'\t(global_label "ECG_OUT"\n\t\t(shape bidirectional)\n\t\t(at {TX:g} {TY:g} 270)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
       f'\t\t\t)\n\t\t\t(justify right)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
tp += (f'\t(text "Module pads: ECG_OUT -> F7 (P1.29 / AIN3), LO+ -> D8 (P3.06), LO- -> E8 (P1.25), SDN -> A7 (P3.03). TP601 = ECG_OUT test pad."\n'
       f'\t\t(exclude_from_sim no)\n\t\t(at 20 36 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\n\t(embedded_fonts") + 1
t = t[:k] + tp + t[k:]
open(NEW, "w").write(t)

# ---------------------------------------------------------------- 2. root sheet
r = open("LeoPatch_v4.kicad_sch").read()
assert SHEET_UUID not in r, "already added"
i = r.index('(property "Sheetname" "ECG front end"')
k = r.rindex("\t(sheet\n", 0, i) + 1
sb = block(r, k)
nb = re.sub(r'\(uuid "[0-9a-f-]+"\)', f'(uuid "{SHEET_UUID}")', sb, 1)
nb = nb.replace('"ECG front end"', '"ECG AD8232"').replace('"LeoPatch_ECG.kicad_sch"', f'"{NEW}"')
nb = nb.replace("(at 30.48 101.6)", "(at 172.72 101.6)").replace("(at 30.48 100.8884 0)", "(at 172.72 100.8884 0)")
nb = nb.replace("(at 30.48 127.6 0)", "(at 172.72 127.6 0)").replace('(page "4")', '(page "7")')
nb = re.sub(r"\(at 30\.48 ", "(at 172.72 ", nb)
r = r[:k + len(sb)] + "\n" + nb + r[k + len(sb):]
r = re.sub(r'\(title "[^"]*"\)', '(title "LeoPatch v4 - newborn CCHD ECG screening (BM20BC, MAX30003 + AD8232)")', r, 1)
r = re.sub(r'\(rev "[^"]*"\)', '(rev "4.0")', r, 1)
r = re.sub(r'\(date "[^"]*"\)', '(date "2026-11-12")', r, 1)
open("LeoPatch_v4.kicad_sch", "w").write(r)

# ---------------------------------------------------------------- 3. MCU sheet: labels on the four module pads
i = mcu.index('(symbol "LeoPatch:BM20BC"')
sym = block(mcu, i)
pins = {num: (float(x), float(y), int(a)) for x, y, a, num in
        re.findall(r'\(pin \w+ \w+\s*\(at ([\d.\-]+) ([\d.\-]+) (\d+)\).*?\(number "([^"]*)"', sym, re.S)}
m = re.search(r'\(symbol\s*\(lib_id "LeoPatch:BM20BC"\)\s*\(at ([\d.]+) ([\d.]+) (\d+)\)', mcu)
sx, sy = float(m.group(1)), float(m.group(2))
for pad, netname in MCU_PINS.items():
    x, y, a = pins[pad]
    px, py = round(sx + x, 2), round(sy - y, 2)
    nc = re.search(r'\t\(no_connect\n\t\t\(at %s %s\)\n\t\t\(uuid "[^"]+"\)\n\t\)\n' % (re.escape(f"{px:g}"), re.escape(f"{py:g}")), mcu)
    assert nc, (pad, px, py)
    mcu = mcu[:nc.start()] + mcu[nc.end():]
    ang, just = {0: (180, "right"), 180: (0, "left"), 90: (270, "right"), 270: (90, "left")}[a]
    lbl = (f'\t(global_label "{netname}"\n\t\t(shape bidirectional)\n\t\t(at {px:g} {py:g} {ang})\n\t\t(effects\n\t\t\t(font\n'
           f'\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n\t\t\t(justify {just})\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
    k = mcu.rindex("\t(sheet_instances") if "\t(sheet_instances" in mcu else mcu.rindex("\t(embedded_fonts")
    mcu = mcu[:k] + lbl + mcu[k:]
    print(pad, netname, "at", px, py, "pin angle", a)
open("LeoPatch_MCU.kicad_sch", "w").write(mcu)
print("ok, sheet uuid", SHEET_UUID)
