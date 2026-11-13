"""LeoPatch v4 schematic batch (system python3, KiCad closed, run from LeoPatch_v4). Then run layout/set_part_fields.py.

MAX30003 sheet, matched to the MAX30003WING2 evaluation kit:
  R201/R202 1k -> 49.9k, C201 10nF -> 1nF, C213/C214 1nF -> 10pF, C202 10uF -> 1uF (0.5 Hz, settles in ~1-2 s),
  new R208 499k from VCM to the RL electrode (eval kit R6)
AD8232 sheet (AD8232 datasheet):
  R603/R604 180k -> 360k (patient current < 10 uA: R >= 3.3 V / 10 uA), output RC to the ADC (Fig. 61):
  U601 OUT is now local net AOUT (TP601 stays on it) -> R623 1k -> ECG_OUT -> C608 10nF to GND -> module pad F7
Status LEDs (active high, GPIO -> R -> LED -> GND):
  D103 PWR (green, R106 1k from +3V3, Power sheet)
  D201 MAX30003 LEADS (green, R206 100R) <- LED_MAX_LEADS, module A7 (P3.03): firmware lights it while DCLOFFINT is clear.
       A7 was ECG_SDN: the AD8232 SDN pin now only has its 10k pull-up R615, so the AD8232 is always on (~170 uA).
       A5 can no longer be routed out of the module.
  D601 AD8232 LEADS (green, R621 100R) <- LED_AD_LEADS, module F8 (P1.17): firmware lights it while LO+ and LO- are low
  (BEAT LEDs were dropped: only three module pins can still be routed out and the board would not route with four LEDs)
"""
import re, sys, uuid
sys.path.insert(0, "layout")
import build_ecg_sheet as B

ROOT = "7a41c3d9-2e65-4f0b-9c88-3d5e1f6a2b90"
SHEETS = {"LeoPatch_ECG.kicad_sch": "f0d23f52-e0d2-5d2d-be47-e1184c1697c7",
          "LeoPatch_ECG_AD8232.kicad_sch": "1d6c4f87-bd9a-573e-bd57-1bf4989b18b5",
          "LeoPatch_Power.kicad_sch": "1bd637cf-7783-5fe2-bdf0-ffd80b334887"}
NS = uuid.UUID("5b0e1c1e-0000-4000-8000-00000000c006")
NEW = ("R208", "D201", "R206", "D601", "R621", "R623", "C608", "D103", "R106")
for r in NEW:
    B.SYM_UUID[r] = str(uuid.uuid5(NS, r))
MCU_PINS = {"F8": "LED_AD_LEADS"}
U = lambda: str(uuid.uuid4())
ui = open("LeoPatch_UI.kicad_sch").read()


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


LED_LIB = block(ui, ui.index('(symbol "Device:LED"'))


def set_value(t, ref, val):
    i = t.index(f'(reference "{ref}")')
    k = t.rindex("(symbol\n\t\t(lib_id", 0, i)
    b = block(t, k)
    nb, c = re.subn(r'(\(property "Value" )"[^"]*"', lambda m: f'{m.group(1)}"{val}"', b, 1)
    assert c == 1, ref
    return t.replace(b, nb, 1)


def led(ref, val, x, y, anode_label):
    s = B.symbol("Device:LED", ref, val, x, y, [("Footprint", "LED_SMD:LED_0603_1608Metric"), ("Datasheet", "~"),
                 ("Description", "Light emitting diode")], ["1", "2"], refxy=(x, y - 3.81), valxy=(x, y + 3.81))
    return s + B.label(anode_label, x + 3.81, y, 0) + B.power("GND", x - 3.81, y)


def led_circuit(ref_r, rval, ref_d, color, x, drive, tag):
    """drive: ('global', NET) or a local label name; R vertical at (x, 76.2), LED horizontal at (x, 92.71)."""
    a = f"LEDA_{tag}"
    return B.passive("R", ref_r, rval, x, 76.2, drive, a) + led(ref_d, color, x, 92.71, a)


def finish(t, body, fname):
    body = body.replace('(project "LeoPatch_v3"', '(project "LeoPatch_v4"')
    if '(symbol "Device:LED"' not in t:
        li = t.index("(lib_symbols") + len("(lib_symbols")
        t = t[:li] + "\n\t\t" + LED_LIB + t[li:]
    k = t.rindex("\t(sheet_instances") if "\t(sheet_instances" in t else t.rindex("\n\t(embedded_fonts") + 1
    t = t[:k] + body + t[k:]
    open(fname, "w").write(t)


# ---------------------------------------------------------------- MAX30003 sheet
f = "LeoPatch_ECG.kicad_sch"
t = open(f).read()
assert '(reference "R208")' not in t, "already applied"
B.PATH = f"/{ROOT}/{SHEETS[f]}"
B.pwr = iter(range(240, 270))
for ref, val in (("R201", "49.9k"), ("R202", "49.9k"), ("C201", "1nF C0G"), ("C213", "10pF C0G"), ("C214", "10pF C0G"), ("C202", "1uF X7R")):
    t = set_value(t, ref, val)
t = t.replace("Input filter (datasheet Figure 11): 1k pulse-proof series resistors, then C201 10 nF across ECGP-ECGN and\\nC213 / C214 1 nF to GND (matched C0G) on the chip side.",
              "Input network as on the MAX30003WING2 evaluation kit: 49.9k pulse-proof series resistors, C201 1 nF across ECGP-ECGN,\\nC213 / C214 10 pF to GND (matched C0G), R208 499k from VCM to the RL electrode. C202 1 uF = 0.5 Hz high-pass.")
body = B.passive("R", "R208", "499k", 266.7, 127.0, "VCM", "RL")
body += led_circuit("R206", "100", "D201", "GREEN", 266.7, ("global", "LED_MAX_LEADS"), "MAXLEADS")
body += B.text("Status LED D201 LEADS: firmware lights it while both electrodes are on (DCLOFFINT clear).", 254.0, 60.96)
finish(t, body, f)

# ---------------------------------------------------------------- AD8232 sheet
f = "LeoPatch_ECG_AD8232.kicad_sch"
t = open(f).read()
B.PATH = f"/{ROOT}/{SHEETS[f]}"
B.pwr = iter(range(640, 670))
for ref in ("R603", "R604"):
    t = set_value(t, ref, "360k")
# SDN is no longer driven by the module: global ECG_SDN -> local SDN (R615 pull-up keeps the AD8232 on)
for m in list(re.finditer(r'\t\(global_label "ECG_SDN"\n', t))[::-1]:          # at U601 SDN and at R615
    b = block(t, m.start() + 1)
    at = re.search(r'\(at ([\d.]+) ([\d.]+) (\d+)\)', b)
    t = t[:m.start() + 1] + B.label("SDN", float(at.group(1)), float(at.group(2)), int(at.group(3))).lstrip("\t").rstrip("\n") + t[m.start() + 1 + len(b):]
assert "ECG_SDN" not in t
n = 0
for m in list(re.finditer(r'\t\(global_label "ECG_OUT"\n', t))[::-1]:
    b = block(t, m.start() + 1)
    at = re.search(r'\(at ([\d.]+) ([\d.]+) (\d+)\)', b)
    t = t[:m.start() + 1] + B.label("AOUT", float(at.group(1)), float(at.group(2)), int(at.group(3))).lstrip("\t").rstrip("\n") + t[m.start() + 1 + len(b):]
    n += 1
assert n == 4, n
body = B.passive("R", "R623", "1k", 304.8, 127.0, "AOUT", ("global", "ECG_OUT"))
body += B.passive("C", "C608", "10nF C0G", 330.2, 127.0, ("global", "ECG_OUT"), "GND")
body += B.text("Output RC to the nRF54 ADC (AD8232 datasheet Fig. 61): the AD8232 op amp is slow (100 kHz GBP), C608 supplies the ADC\\nsampling charge. R603/R604 360k: patient current < 10 uA even in a fault (datasheet: R >= supply / 10 uA).", 294.64, 111.76)
body += led_circuit("R621", "100", "D601", "GREEN", 304.8, ("global", "LED_AD_LEADS"), "ADLEADS")
body += B.text("Status LED D601 LEADS: firmware lights it while LO+ and LO- are both low (both electrodes on).", 294.64, 60.96)
finish(t, body, f)

# ---------------------------------------------------------------- Power sheet
f = "LeoPatch_Power.kicad_sch"
t = open(f).read()
B.PATH = f"/{ROOT}/{SHEETS[f]}"
B.pwr = iter(range(130, 150))
body = B.passive("R", "R106", "1k", 88.9, 185.42, "+3V3", "PWR_A") + led("D103", "GREEN", 101.6, 191.77, "PWR_A")
body += B.text("D103: power LED (on whenever the 3.3 V rail is up, ~0.5 mA)", 76.2, 177.8)
finish(t, body, f)

# ---------------------------------------------------------------- MCU sheet: module pads for the three LED GPIOs
mcu = open("LeoPatch_MCU.kicad_sch").read()
sym = block(mcu, mcu.index('(symbol "LeoPatch:BM20BC"'))
pins = {num: (float(x), float(y), int(a)) for x, y, a, num in
        re.findall(r'\(pin \w+ \w+\s*\(at ([\d.\-]+) ([\d.\-]+) (\d+)\).*?\(number "([^"]*)"', sym, re.S)}
m = re.search(r'\(symbol\s*\(lib_id "LeoPatch:BM20BC"\)\s*\(at ([\d.]+) ([\d.]+) (\d+)\)', mcu)
sx, sy = float(m.group(1)), float(m.group(2))
for pad, netname in MCU_PINS.items():
    x, y, a = pins[pad]
    px, py = round(sx + x, 2), round(sy - y, 2)
    nc = re.search(r'\t\(no_connect\n\t\t\(at %s %s\)\n\t\t\(uuid "[^"]+"\)\n\t\)\n' % (re.escape(f"{px:g}"), re.escape(f"{py:g}")), mcu)
    assert nc, (pad, px, py)
    ang = {0: 180, 180: 0, 90: 270, 270: 90}[a]
    mcu = mcu[:nc.start()] + B.label(netname, px, py, ang, glob=True) + mcu[nc.end():]
    print(pad, netname, px, py)
# A7 (P3.03) was ECG_SDN -> now drives the MAX30003 LEADS LED
assert mcu.count('(global_label "ECG_SDN"') == 1
mcu = mcu.replace('(global_label "ECG_SDN"', '(global_label "LED_MAX_LEADS"')
open("LeoPatch_MCU.kicad_sch", "w").write(mcu)
print("ok")
