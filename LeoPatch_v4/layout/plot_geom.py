"""Plot geom.json (and optionally new routes) to a PNG for checking:  python plot_geom.py geom.json out.png [x0 y0 x1 y1] [routes.json]"""
import json, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
import matplotlib.transforms as mt

g = json.load(open(sys.argv[1]))
win = list(map(float, sys.argv[3:7])) if len(sys.argv) >= 7 else g["board"]
routes = json.load(open(sys.argv[7])) if len(sys.argv) >= 8 else None
fig, ax = plt.subplots(figsize=(16, 16 * (win[3] - win[1]) / (win[2] - win[0])))
COL = {"F": "#c83232", "B": "#3232c8"}
for e in g["edges"]:
    ax.plot([e[0], e[2]], [e[1], e[3]], color="#c8c800", lw=1)
for t in g["tracks"]:
    ax.plot([t["x0"], t["x1"]], [t["y0"], t["y1"]], color=COL[t["layer"]], lw=t["w"] * 72 / 25.4 * 16 / (win[2] - win[0]) * 25.4 / 1.0, alpha=0.6, solid_capstyle="round")
for v in g["vias"]:
    ax.add_patch(Circle((v["x"], v["y"]), 0.225, color="#888888"))
small = (win[2] - win[0]) < 40
for p in g["pads"]:
    if not (win[0] - 3 < p["x"] < win[2] + 3 and win[1] - 3 < p["y"] < win[3] + 3):
        continue
    c = "#aaaaaa" if p["npth"] else ("#d4a017" if "F" in p["layers"] else "#4a90d9")
    r = Rectangle((p["x"] - p["sx"] / 2, p["y"] - p["sy"] / 2), p["sx"], p["sy"], color=c, alpha=0.8,
                  transform=mt.Affine2D().rotate_deg_around(p["x"], p["y"], -p["rot"]) + ax.transData)
    ax.add_patch(r)
    if small:
        lbl = f'{p["ref"]}.{p["num"]}' + ("\n" + p["net"].split("/")[-1][:10] if p["net"] and not p["net"].startswith("unconn") else "")
        ax.text(p["x"], p["y"], lbl, fontsize=5, ha="center", va="center")
if routes:
    for t in routes["tracks"]:
        ax.plot([t[1], t[3]], [t[2], t[4]], color="#00b000" if t[0] == "F" else "#00b0b0", lw=2)
    for v in routes["vias"]:
        ax.add_patch(Circle((v[0], v[1]), 0.225, color="#006000"))
ax.set_xlim(win[0], win[2]); ax.set_ylim(win[3], win[1]); ax.set_aspect("equal")
ax.grid(True, lw=0.3); ax.set_xticks(range(int(win[0]), int(win[2]) + 1, 1 if small else 5))
ax.set_yticks(range(int(win[1]), int(win[3]) + 1, 1 if small else 5)); ax.tick_params(labelsize=6)
fig.savefig(sys.argv[2], dpi=110, bbox_inches="tight")
