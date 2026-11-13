"""LeoPatch v4: X201 Epson SG-3030CM -> Micro Crystal OV-7604-C7-32.768kHz-20PPM-TA-QC (LCSC C5337982, in JLC stock;
SG-3030CM only via Global Sourcing with an 808-piece minimum). Same 3.2 x 1.5 mm SON-4 land pattern (KiCad
Oscillator_SMD_SeikoEpson_SG3030CM pads match the OV-7604 recommended pads), 0.3/0.5 uA, 1.2-5.5 V, +-20 ppm,
but pins 1 and 3 are swapped: OV-7604 pin 1 = CLKOUT, pin 3 = CLKOE (SG-3030CM: pin 1 = VIO, pin 3 = OUT).
The embedded symbol is redefined (same pin positions, so the wiring is unchanged): the pin wired to FCLK becomes
pin 1 CLKOUT, the pin tied to +3V3 becomes pin 3 CLKOE (high = clock on). System python3, KiCad closed."""
import re
F = "LeoPatch_ECG.kicad_sch"
t = open(F).read()
assert "OV-7604-C7" not in t, "already applied"


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


L = t.index('(symbol "Oscillator:SG-3030CM"')
lib = block(t, L)
new = lib.replace('(symbol "Oscillator:SG-3030CM"', '(symbol "LeoPatch:OV-7604-C7"')
new = new.replace('"SG-3030CM_0_1"', '"OV-7604-C7_0_1"').replace('"SG-3030CM_1_1"', '"OV-7604-C7_1_1"')
pins = re.findall(r'\(pin \w+ \w+\s*\(at [-\d.]+ [-\d.]+ \d+\).*?\(number "[^"]*"', new, re.S)
for p in pins:
    if '(name "VIO"' in p:
        q = p.replace("(pin power_in", "(pin input").replace('(name "VIO"', '(name "CLKOE"').replace('(number "1"', '(number "3"')
    elif '(name "OUT"' in p:
        q = p.replace('(name "OUT"', '(name "CLKOUT"').replace('(number "3"', '(number "1"')
    else:
        continue
    new = new.replace(p, q, 1)
assert new.count('(name "CLKOE"') == 1 and new.count('(name "CLKOUT"') == 1, "pin rewrite"
new = re.sub(r'(\(property "Value" )"[^"]*"', r'\1"OV-7604-C7"', new, 1)
new = re.sub(r'(\(property "Description" )"[^"]*"', r'\1"32.768 kHz low-power CMOS clock oscillator, SON-4 3.2x1.5 mm, pin 1 CLKOUT, pin 3 CLKOE"', new, 1)
t = t.replace(lib, new, 1)
# the X201 instance
i = t.index('(reference "X201")'); k = t.rindex("(symbol\n\t\t(lib_id", 0, i); b = block(t, k)
nb = b.replace('(lib_id "Oscillator:SG-3030CM")', '(lib_id "LeoPatch:OV-7604-C7")')
nb = re.sub(r'(\(property "Value" )"[^"]*"', r'\1"OV-7604-C7 32.768kHz"', nb, 1)
nb = re.sub(r'(\(property "Description" )"[^"]*"', r'\1"32.768 kHz low-power CMOS oscillator (0.5 uA), 3.2x1.5 mm, 1.2-5.5 V. Pin 1 CLKOUT, pin 3 CLKOE (tied high)"', nb, 1)
assert nb != b
# pin entries in the instance: swap the uuid-bearing pin numbers 1 <-> 3
nb = nb.replace('(pin "1"\n', '(pin "@@1"\n').replace('(pin "3"\n', '(pin "1"\n').replace('(pin "@@1"\n', '(pin "3"\n')
t = t.replace(b, nb, 1)
t = t.replace('(text "Input filter', '(text "Input filter', 1)
open(F, "w").write(t)
print("X201 -> OV-7604-C7")
