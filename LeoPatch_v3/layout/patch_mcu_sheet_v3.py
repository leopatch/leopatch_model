"""LeoPatch v3: module pins for the MAX30003 SPI on the MCU sheet, and TP3 (ECG_OUT) removed.
Run with system python3 from the LeoPatch_v3 folder, with KiCad closed."""
import re, uuid
U = lambda: str(uuid.uuid4())
t = open("LeoPatch_MCU.kicad_sch").read()
assert "ECG_SCK" not in t, "already patched"


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


# left-side module pins: K8 -> ECG_MOSI, C9 -> ECG_INT, D9 -> ECG_CS, E9 -> ECG_SCK (global labels at x = 162.56)
for old, new, y in (("ECG_OUT", "ECG_MOSI", 116.84), ("ECG_LO+", "ECG_INT", 111.76), ("ECG_LO-", "ECG_CS", 114.3), ("ECG_SDN", "ECG_SCK", 119.38)):
    a = f'(global_label "{old}"\n\t\t(shape bidirectional)\n\t\t(at 162.56 {y:g} 180)'
    assert t.count(a) == 1, old
    t = t.replace(a, a.replace(old, new))
# A8 (P1.02) -> ECG_MISO: replace its no-connect flag with a global label
m = re.search(r'\t\(no_connect\n\t\t\(at 215\.9 119\.38\)\n\t\t\(uuid "[^"]+"\)\n\t\)\n', t)
assert m, "A8 no-connect not found"
t = t[:m.start()] + t[m.end():]
lbl = ('\t(global_label "ECG_MISO"\n\t\t(shape bidirectional)\n\t\t(at 215.9 119.38 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
       f'\t\t\t(justify left)\n\t\t)\n\t\t(uuid "{U()}")\n\t)\n')
# TP3 and its ECG_OUT label go
i = t.index('(reference "TP3")'); k = t.rindex("\t(symbol\n", 0, i) + 1
t = t.replace(block(t, k) + "\n", "", 1)
a = t.index('(global_label "ECG_OUT"\n\t\t(shape bidirectional)\n\t\t(at 355.6 121.92 270)')
t = t.replace(block(t, a) + "\n", "", 1)
t = t.replace("Test points (1 mm pads on the top side)", "Test points (1 mm pads on the top side): GND and 3V3")
k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\t(embedded_fonts")
t = t[:k] + lbl + t[k:]
open("LeoPatch_MCU.kicad_sch", "w").write(t)
print("ok")
