"""LeoPatch v4: MAX30003 input filter as in datasheet Figure 11 (system python3, KiCad closed, run from LeoPatch_v4).
- C201 (differential cap) moves from LA-RA (electrode side) to ECGP-ECGN (chip side of the 1k resistors), 1nF -> 10nF C0G
- new C213 ECGP-GND and C214 ECGN-GND, 1nF C0G (common-mode EMI filter; matched C0G keeps CMRR)
- R201 / R202 (1k series) -> 1206 footprint, pulse-proof part ("energy rated", datasheet Note 11 / ESD section)
Then run layout/set_part_fields.py for the MPN / LCSC fields."""
import re, sys, uuid
sys.path.insert(0, "layout")
import build_ecg_sheet as B

SCH = "LeoPatch_ECG.kicad_sch"
t = open(SCH).read()
assert '(reference "C213")' not in t, "already applied"


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


def sym_block(ref):
    i = t.index(f'(reference "{ref}")')
    k = t.rindex("(symbol\n\t\t(lib_id", 0, i)
    return k, block(t, k)


# C201: value and its two net labels (it sits at x = 93.98, labels at y = 71.12 -/+ 3.81)
k, b = sym_block("C201")
t = t.replace(b, b.replace('(property "Value" "1nF C0G"', '(property "Value" "10nF C0G"'), 1)
for old, new, y in (("LA", "ECGP", 67.31), ("RA", "ECGN", 74.93)):
    pat = re.compile(r'\(label "%s"\n\t\t\(at 93\.98 %s (\d+)\)' % (old, re.escape(f"{y:g}")))
    assert len(pat.findall(t)) == 1, (old, y)
    t = pat.sub(lambda m: f'(label "{new}"\n\t\t(at 93.98 {y:g} {m.group(1)})', t)
# R201 / R202 footprint -> 1206
for ref in ("R201", "R202"):
    k, b = sym_block(ref)
    nb = b.replace('"Resistor_SMD:R_0603_1608Metric"', '"Resistor_SMD:R_1206_3216Metric"')
    assert nb != b, ref
    t = t.replace(b, nb, 1)

# new C213 / C214, fixed UUIDs (build_v4_pcb.py links the footprints with the same uuid5)
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c005")
for r in ("C213", "C214"):
    B.SYM_UUID[r] = str(uuid.uuid5(NS, r))
B.pwr = iter(range(230, 260))
body = B.passive("C", "C213", "1nF C0G", 78.74, 71.12, "ECGP", "GND")
body += B.passive("C", "C214", "1nF C0G", 71.12, 71.12, "ECGN", "GND")
body += B.text("Input filter (datasheet Figure 11): 1k pulse-proof series resistors, then C201 10 nF across ECGP-ECGN and\\nC213 / C214 1 nF to GND (matched C0G) on the chip side.", 25.4, 60.96)
body = body.replace('(project "LeoPatch_v3"', '(project "LeoPatch_v4"')
k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\n\t(embedded_fonts") + 1
t = t[:k] + body + t[k:]
open(SCH, "w").write(t)
print("ok:", {r: B.SYM_UUID[r] for r in ("C213", "C214")})
