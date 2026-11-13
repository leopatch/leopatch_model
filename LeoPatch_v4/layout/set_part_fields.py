"""LeoPatch v4: write the part choices of layout/parts.csv into the schematic (system python3, KiCad closed, run from LeoPatch_v4).
Every placed symbol gets hidden Manufacturer / MPN / LCSC fields (old MPN fields are replaced) and its Datasheet
field set to the datasheet link in parts.csv. Also:
  U2   footprint -> SOIC-8 5.3x5.3 mm (GD25WQ64ESIGR is the 208-mil SOP-8; v2/v3 had the 150-mil footprint)
  U202 value     -> MCP1700T-1802E/TT (MCP1703AT-1802E/CB: 3 pcs at LCSC; same SOT-23 pinout GND / VOUT / VIN)
  R301 value     -> 100 (green InGaN LED needs ~3 V; 1k from a 3.3 V pin gave ~0.2 mA)
Safe to run again."""
import csv, glob, re

PARTS = {}
for row in csv.DictReader(open("layout/parts.csv")):
    for r in row["Refs"].split(","):
        PARTS[r.strip()] = row
CHANGE = {"U2": {"Footprint": "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
                 "Description": "GigaDevice GD25WQ64E 64 Mbit 1.65-3.6 V SPI/QSPI NOR flash, SOP-8 208 mil"},
          "U202": {"Value": "MCP1700T-1802E/TT", "Description": "LDO 1.8 V 250 mA, 6 V max in, 1.6 uA Iq, SOT-23 (GND, VOUT, VIN)"},
          "R301": {"Value": "100"},
          "U101": {"Value": "MCP1703AT-3302E/CB"}}


def block(s, start):
    d = 0
    for j in range(start, len(s)):
        if s[j] == "(": d += 1
        elif s[j] == ")":
            d -= 1
            if d == 0: return s[start:j + 1]


def prop(k, v, x, y):
    v = v.replace('"', '\\"')
    return (f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x} {y} 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            f'\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n')


seen = set()
for fn in sorted(glob.glob("*.kicad_sch")):
    t = open(fn).read()
    out, pos, n = [], 0, 0
    for m in re.finditer(r"\n\t?\(symbol\n\t\t\(lib_id ", t):
        k = m.start() + 1
        blk = block(t, k)
        rm = re.search(r'\(reference "([^"]+)"\)', blk)
        ref = rm.group(1) if rm else None
        new = blk
        if ref in PARTS or ref in CHANGE:
            for key, val in CHANGE.get(ref, {}).items():
                new, c = re.subn(r'(\(property "%s" )"[^"]*"' % key, lambda mm: f'{mm.group(1)}"{val}"', new, 1)
                assert c == 1, (ref, key)
            if ref in PARTS:
                p = PARTS[ref]
                if p.get("Datasheet"):                                # datasheet link from parts.csv
                    ds = p["Datasheet"].replace('"', '%22')
                    new, c = re.subn(r'(\(property "Datasheet" )"[^"]*"', lambda mm: f'{mm.group(1)}"{ds}"', new, 1)
                    assert c == 1, (ref, "Datasheet")
                for key in ("Manufacturer", "MPN", "LCSC"):             # drop old copies
                    i = new.find(f'\t\t(property "{key}" ')
                    if i >= 0:
                        b = block(new, i + 2)
                        new = new[:i] + new[i + 2 + len(b) + 1:]
                at = re.search(r"\(at ([\d.\-]+) ([\d.\-]+)", new)
                x, y = at.group(1), at.group(2)
                i = new.index("\t\t(pin ") if "\t\t(pin " in new else new.index("\t\t(instances")
                new = new[:i] + prop("Manufacturer", p["Manufacturer"], x, y) + prop("MPN", p["MPN"], x, y) + prop("LCSC", p["LCSC"], x, y) + new[i:]
                seen.add(ref); n += 1
        out.append(t[pos:k] + new); pos = k + len(blk)
    t = "".join(out) + t[pos:]
    open(fn, "w").write(t)
    print(fn, n, "symbols")
missing = sorted(set(PARTS) - seen)
print("parts.csv refs not found in the schematic:", missing)
