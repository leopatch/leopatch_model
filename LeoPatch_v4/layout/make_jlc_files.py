"""Make the JLCPCB assembly files for LeoPatch v4 (system python3, run from LeoPatch_v4):
    python3 layout/make_jlc_files.py
Inputs: LeoPatch_v4.kicad_pcb (positions via kicad-cli), layout/parts.csv (manufacturer / MPN / LCSC per reference),
layout/jlc_rotations.csv (JLC rotation corrections). Outputs in fab/:
  LeoPatch_v4_JLC_BOM.csv       Comment, Designator, Footprint, LCSC Part #  (+ Manufacturer, MPN for parts JLC must source)
  LeoPatch_v4_JLC_CPL.csv       Designator, Mid X, Mid Y, Layer, Rotation
  LeoPatch_v4_BOM_detailed.csv  everything, for people: quantity, manufacturer, MPN, LCSC, description, sourcing note
Test pads (TP*), mounting holes (H*) and DNP parts are left out."""
import csv, io, re, subprocess, tempfile

CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
with tempfile.TemporaryDirectory() as td:
    subprocess.run([CLI, "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp",
                    "-o", f"{td}/pos.csv", "LeoPatch_v4.kicad_pcb"], capture_output=True, check=True)
    pos_csv = open(f"{td}/pos.csv").read()
POS = {r["Ref"]: r for r in csv.DictReader(io.StringIO(pos_csv))}

PART = {}
ROWS = list(csv.DictReader(open("layout/parts.csv")))
for row in ROWS:
    for ref in row["Refs"].split(","):
        PART[ref.strip()] = row

ROT = []
for line in open("layout/jlc_rotations.csv"):
    if line.startswith("#") or line.startswith('"Footprint pattern"'):
        continue
    f = next(csv.reader([line]))
    if f:
        ROT.append((re.compile(f[0]), float(f[1]), float(f[2]) if len(f) > 2 and f[2].strip() else 0.0))


def natural(ref):
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else (ref, 0)


placed = sorted((r for r in POS if not re.match(r"^(TP|H)\d", r)), key=natural)
missing = [r for r in placed if r not in PART]
assert not missing, f"no parts.csv row for {missing}"
unplaced = sorted({r for r in PART if PART[r]["MPN"] and r not in POS}, key=natural)
assert not unplaced, f"parts.csv refs not on the board: {unplaced}"

# ---------------------------------------------------------------- BOM (one line per parts.csv row)
groups = []
for row in ROWS:
    refs = sorted((r.strip() for r in row["Refs"].split(",") if r.strip() in POS), key=natural)
    if not refs or not row["MPN"]:
        continue                                            # DNP
    pkg = POS[refs[0]]["Package"]
    groups.append((refs, row, pkg))
with open("fab/LeoPatch_v4_JLC_BOM.csv", "w", newline="") as fh:
    w = csv.writer(fh, quoting=csv.QUOTE_ALL)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Manufacturer", "Manufacturer Part Number", "Quantity"])
    for refs, row, pkg in groups:
        w.writerow([f'{row["Description"]} ({row["MPN"]})', ",".join(refs), pkg, row["LCSC"], row["Manufacturer"], row["MPN"], len(refs)])
with open("fab/LeoPatch_v4_BOM_detailed.csv", "w", newline="") as fh:
    w = csv.writer(fh, quoting=csv.QUOTE_ALL)
    w.writerow(["Designator", "Qty", "Manufacturer", "MPN", "LCSC", "Description", "Footprint", "Mount", "Note"])
    for refs, row, pkg in groups:
        mount = "through-hole" if "through-hole" in row["Description"] else "SMD"
        w.writerow([",".join(refs), len(refs), row["Manufacturer"], row["MPN"], row["LCSC"] or "-", row["Description"], pkg, mount, row["Note"]])
    w.writerow(["(loose)", 1, "", "2.54 mm jumper cap", "", "Jumper shunt for JP101 (current-measure jumper)", "", "loose", "not assembled - fit by hand"])

# ---------------------------------------------------------------- CPL
notes = []
with open("fab/LeoPatch_v4_JLC_CPL.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for ref in placed:
        p = POS[ref]
        rot = float(p["Rot"])
        for rx, corr, offx in ROT:
            if rx.search(p["Package"]):
                rot += corr
                if offx:
                    notes.append(f"{ref}: table offset for {rx.pattern} not applied (this footprint's origin is its centre)")
                break
        rot = rot % 360
        w.writerow([ref, f'{float(p["PosX"]):.4f}mm', f'{float(p["PosY"]):.4f}mm', "Top" if p["Side"] == "top" else "Bottom", f"{rot:g}"])
print(f"BOM: {len(groups)} lines, {sum(len(g[0]) for g in groups)} parts; CPL: {len(placed)} placements")
no_lcsc = [(",".join(g[0]), g[1]["MPN"]) for g in groups if not g[1]["LCSC"]]
print("no LCSC number (JLC Global Sourcing or consign):", no_lcsc)
for n in notes:
    print("note:", n)
