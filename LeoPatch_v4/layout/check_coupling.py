"""Signal-integrity check (venv python):  python check_coupling.py geom.json [gap_mm]
Lists every place where a sensitive analog net runs next to a switching net on the same copper layer, edge-to-edge
gap below `gap_mm` (default 0.5 mm), with the parallel length. F.Cu and B.Cu are shielded from each other by the two
inner planes, so only same-layer neighbours count. Also prints the USB pair geometry."""
import json, math, sys
from collections import defaultdict

g = json.load(open(sys.argv[1]))
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5


def kind(n):
    if n == "ECG_OUT" or n.startswith("/ECG AD8232/") or n == "VBAT_SENSE" or n == "+1V8":
        return "analog"
    if n.startswith("/ECG front end/"):
        return "digital" if n.endswith("/FCLK") else "analog"
    if n in ("ECG_SCK", "ECG_MOSI", "ECG_MISO", "ECG_CS", "ECG_INT") or n.startswith("FLASH_") or "FLASH" in n:
        return "digital"
    if n in ("USB_DP", "USB_DN") or "SWD" in n or n.endswith("nRESET"):
        return "digital"
    return "quiet"                                   # GND, +3V3, LEDs, buttons, LO+/LO-/SDN (static), VBUS ...


def seg_pt(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def close_len(s, t, gap):
    """length of segment s that lies within (gap + half widths) of segment t (sampled every 0.05 mm)."""
    L = math.hypot(s["x1"] - s["x0"], s["y1"] - s["y0"])
    n = max(int(L / 0.05), 1)
    lim = gap + s["w"] / 2 + t["w"] / 2
    c = 0
    for k in range(n + 1):
        f = k / n
        px, py = s["x0"] + f * (s["x1"] - s["x0"]), s["y0"] + f * (s["y1"] - s["y0"])
        if seg_pt(t["x0"], t["y0"], t["x1"], t["y1"], px, py) < lim:
            c += 1
    return L * c / (n + 1)


tr = [t for t in g["tracks"] if t["net"]]
pairs = defaultdict(lambda: [0.0, 1e9, None])
for i, a in enumerate(tr):
    ka = kind(a["net"])
    if ka == "quiet":
        continue
    for b in tr[i + 1:]:
        if b["layer"] != a["layer"] or b["net"] == a["net"]:
            continue
        kb = kind(b["net"])
        if kb == "quiet" or (ka == kb == "digital"):
            continue
        # quick reject
        if min(a["x0"], a["x1"]) - 2 > max(b["x0"], b["x1"]) or min(b["x0"], b["x1"]) - 2 > max(a["x0"], a["x1"]):
            continue
        if min(a["y0"], a["y1"]) - 2 > max(b["y0"], b["y1"]) or min(b["y0"], b["y1"]) - 2 > max(a["y0"], a["y1"]):
            continue
        L = close_len(a, b, GAP)
        if L > 0:
            # edge gap at the closest point
            d = min(seg_pt(b["x0"], b["y0"], b["x1"], b["y1"], a["x0"] + f * (a["x1"] - a["x0"]), a["y0"] + f * (a["y1"] - a["y0"]))
                    for f in [k / 20 for k in range(21)]) - a["w"] / 2 - b["w"] / 2
            key = tuple(sorted((a["net"], b["net"]))) + (a["layer"],)
            p = pairs[key]
            p[0] += L; p[1] = min(p[1], d)
            p[2] = p[2] or (round((a["x0"] + a["x1"]) / 2, 1), round((a["y0"] + a["y1"]) / 2, 1))
print(f"same-layer analog/digital and analog/analog neighbours closer than {GAP} mm edge-to-edge:")
print(f"{'net A':28s} {'net B':28s} lyr  parallel_mm  min_gap_mm  near (x, y)")
for (a, b, l), (L, d, xy) in sorted(pairs.items(), key=lambda kv: -kv[1][0]):
    tag = "A-D" if "digital" in (kind(a), kind(b)) else "A-A"
    print(f"{a[-28:]:28s} {b[-28:]:28s} {l:3s} {L:9.2f} {d:11.2f}   {xy}  {tag}")

# USB pair
dp = [t for t in g["tracks"] if t["net"] == "USB_DP"]; dn = [t for t in g["tracks"] if t["net"] == "USB_DN"]
ln = lambda ts: sum(math.hypot(t["x1"] - t["x0"], t["y1"] - t["y0"]) for t in ts)
print(f"\nUSB D+ {ln(dp):.2f} mm, D- {ln(dn):.2f} mm (track lengths), widths {sorted({t['w'] for t in dp + dn})}, layers {sorted({t['layer'] for t in dp + dn})}")
gaps = []
for a in dp:
    if a["w"] < 0.25:
        continue
    for b in dn:
        if b["w"] < 0.25 or a["layer"] != b["layer"]:
            continue
        for f in [k / 10 for k in range(11)]:
            px, py = a["x0"] + f * (a["x1"] - a["x0"]), a["y0"] + f * (a["y1"] - a["y0"])
            d = seg_pt(b["x0"], b["y0"], b["x1"], b["y1"], px, py) - a["w"] / 2 - b["w"] / 2
            if d < 1.0:
                gaps.append(d)
if gaps:
    print(f"USB pair edge gap where they run together: min {min(gaps):.3f} mm, max {max(gaps):.3f} mm")
print("USB vias:", sum(1 for v in g["vias"] if v["net"] in ("USB_DP", "USB_DN")))
