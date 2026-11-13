"""LeoPatch v4 test points (system python3, KiCad closed, run from LeoPatch_v4). Bare 1.5 mm top-side copper pads,
not in the BOM. build_v4_pcb.py places the footprints with the same uuid5 paths.

MAX30003 sheet: TP201 FCLK, TP202-TP206 ECG_CS / SCK / MOSI / MISO / INT (logic analyzer on the SPI bus), TP207 +1V8
AD8232 sheet:   TP602 ECG_OUT after the R623/C608 filter (what the ADC sees), TP603 REFOUT (~1.65 V), TP604 GND
Power sheet:    TP101 VBAT_SENSE (battery divider, compare with what the firmware reports)
No test points on ECGP/ECGN, INP/INN or the chip-side LA/RA: high impedance, a pad adds leakage and pickup.
"""
import re, sys, uuid
sys.path.insert(0, "layout")
import build_ecg_sheet as B

ROOT = "7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90"
SHEETS = {"LeoPatch_ECG.kicad_sch": "f0d23f52-e0d2-5d2d-be47-e1184c1697c7",
          "LeoPatch_ECG_AD8232.kicad_sch": "1d6c4f87-bd9a-573e-bd57-1bf4989b18b5",
          "LeoPatch_Power.kicad_sch": "1bd637cf-7783-5fe2-bdf0-ffd80b334887"}
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c007")
FP = "TestPoint:TestPoint_Pad_D1.5mm"
# ref, net, kind ('global' | 'local' | 'power'), sheet x, y
TPS = {
    "LeoPatch_ECG.kicad_sch": [("TP201", "FCLK", "local"), ("TP202", "ECG_CS", "global"), ("TP203", "ECG_SCK", "global"),
                               ("TP204", "ECG_MOSI", "global"), ("TP205", "ECG_MISO", "global"),
                               ("TP206", "ECG_INT", "global"), ("TP207", "+1V8", "power")],
    "LeoPatch_ECG_AD8232.kicad_sch": [("TP602", "ECG_OUT", "global"), ("TP603", "REFOUT", "local"), ("TP604", "GND", "power")],
    "LeoPatch_Power.kicad_sch": [("TP101", "VBAT_SENSE", "global")],
}
ORIGIN = {"LeoPatch_ECG.kicad_sch": (50.8, 190.5, 25.4), "LeoPatch_ECG_AD8232.kicad_sch": (292.1, 203.2, 25.4),
          "LeoPatch_Power.kicad_sch": (269.24, 68.58, 25.4)}
for refs in TPS.values():
    for r, *_ in refs:
        B.SYM_UUID[r] = str(uuid.uuid5(NS, r))


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


ad = open("LeoPatch_ECG_AD8232.kicad_sch").read()
TP_LIB = block(ad, ad.index('(symbol "Connector:TestPoint"'))


def tp(ref, net, kind, x, y):
    s = B.symbol("Connector:TestPoint", ref, net.lstrip("+"), x, y,
                 [("Footprint", FP), ("Datasheet", "~"), ("Description", "test point")], ["1"], bom=False,
                 refxy=(x + 2.54, y - 5.08), valxy=(x + 2.54, y - 2.54), just="left")
    s = s.replace("(on_board no)", "(on_board yes)", 1)             # bare pad: on the board, not in the BOM
    if kind == "power":
        return s + B.wire((x, y), (x, y + 2.54)) + B.power(net, x, y + 2.54)
    return s + B.label(net, x, y, 180, glob=(kind == "global"))


for f, refs in TPS.items():
    t = open(f).read()
    assert f'(reference "{refs[0][0]}")' not in t, "already applied"
    B.PATH = f"/{ROOT}/{SHEETS[f]}"
    B.pwr = iter({"LeoPatch_ECG.kicad_sch": range(270, 290), "LeoPatch_ECG_AD8232.kicad_sch": range(670, 690),
                  "LeoPatch_Power.kicad_sch": range(150, 170)}[f])
    x0, y0, dx = ORIGIN[f]
    body = B.text("Test points (bare 1.5 mm pads, top side, not in the BOM)", x0 - 12.7, y0 - 12.7)
    for i, (r, net, kind) in enumerate(refs):
        body += tp(r, net, kind, x0 + i * dx, y0)
    body = body.replace('(project "LeoPatch_v3"', '(project "LeoPatch_v4"')
    if '(symbol "Connector:TestPoint"' not in t:
        li = t.index("(lib_symbols") + len("(lib_symbols")
        t = t[:li] + "\n\t\t" + TP_LIB + t[li:]
    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\n\t(embedded_fonts") + 1
    t = t[:k] + body + t[k:]
    open(f, "w").write(t)
    print(f, [r for r, *_ in refs])
