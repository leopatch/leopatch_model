"""Route what is still unrouted on a board, around the copper that is already there (venv python with numpy):
    python route_new.py geom.json routes_new.json
geom.json comes from dump_geom.py. Output: new tracks / vias, plus dangling copper to delete; apply_new_routes.py
writes them to the board.

- Per net, pads + tracks + vias are grouped into connected pieces. Pieces with no pad are dangling -> deleted.
- Signal nets: pieces are joined by A* on a 0.1 mm grid, two layers (F.Cu / B.Cu), vias between them.
- GND / +3V3 (inner planes In1 / In2): every piece needs a via or a through-hole pad; if it has none, a short stub
  to a new via (or to plane-connected copper of the same net) is routed.
Rules: clearance 0.15 mm, tracks 0.2 mm (0.15 mm on nets that reach the module, 0.3 mm on +1V8), vias 0.45 / 0.2 mm,
0.3 mm from the board edge, no vias or bottom-layer tracks under the module, no vias in pads except big exposed pads,
2 mm free around mounting holes (screw heads), nothing in the antenna keep-out.
"""
import heapq, json, math, sys
import numpy as np

g = json.load(open(sys.argv[1]))
OUT = sys.argv[2]
ONLY = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None

RES, CL, FUDGE, EDGE_CL, HOLE_CL = 0.1, 0.15, 0.015, 0.3, 0.2
VIA_D, VIA_DRILL = 0.45, 0.3   # JLCPCB standard 4-layer via (0.3 mm hole / 0.45 mm pad)
VIA_COST, TURN_COST, MODULE_COST = 12.0, 0.4, 4.0
SEP, COUPLE_COST = 0.5, 4.0   # analog <-> switching-digital tracks on the same layer: keep >= 0.5 mm edge to edge (soft rule)


def sig_kind(n):
    """analog = sensitive (ECG signals, MAX30003 references, +1V8, battery divider); digital = switching lines."""
    if n == "ECG_OUT" or n.startswith("/ECG AD8232/") or n in ("VBAT_SENSE", "+1V8"):
        return "analog"
    if n.startswith("/ECG front end/"):
        return "digital" if n.endswith("/FCLK") else "analog"
    if n in ("ECG_SCK", "ECG_MOSI", "ECG_MISO", "ECG_CS", "ECG_INT", "USB_DP", "USB_DN") or "FLASH" in n or "SWD" in n:
        return "digital"
    return "quiet"
PLANE = {"GND", "+3V3"}
ANTENNA = (140.05, 99.0, 160.05, 106.6)
BX0, BY0, BX1, BY1 = g["board"]
X0, Y0 = 99.95, 99.95
W = int(round((BX1 - X0) / RES)) + 2
H = int(round((BY1 - Y0) / RES)) + 2
N = W * H
XS = X0 + np.arange(W) * RES
YS = Y0 + np.arange(H) * RES
ci = lambda x: int(round((x - X0) / RES))
cj = lambda y: int(round((y - Y0) / RES))
cx = lambda i: X0 + i * RES
cy = lambda j: Y0 + j * RES

u1 = [p for p in g["pads"] if p["ref"] == "U1"]
MOD = (min(p["x"] for p in u1) - 0.6, 106.6, max(p["x"] for p in u1) + 0.6, max(p["y"] for p in u1) + 0.6)
MOUNT = [p for p in g["pads"] if p["npth"] and p["drill"] > 1.5]

nets = sorted({p["net"] for p in g["pads"]} | {t["net"] for t in g["tracks"]} | {v["net"] for v in g["vias"]})
NID = {n: k + 1 for k, n in enumerate(nets)}
module_nets = {p["net"] for p in u1}


def width(net):
    if net == "+1V8":
        return 0.3
    if net in module_nets and net not in PLANE:
        return 0.15
    return 0.2


WIDTHS = sorted({width(n) for n in nets} | {0.2})


# ---------------------------------------------------------------- geometry
def pad_dist(p, X, Y):
    """distance from points (X, Y arrays) to the pad copper (negative inside)."""
    if p["shape"] == "circle":
        return np.hypot(X - p["x"], Y - p["y"]) - p["sx"] / 2
    a = math.radians(p["rot"])
    dx, dy = X - p["x"], Y - p["y"]
    lx = dx * math.cos(a) - dy * math.sin(a)
    ly = dx * math.sin(a) + dy * math.cos(a)
    rad = p["rr"] if p["shape"] == "roundrect" else (min(p["sx"], p["sy"]) / 2 if p["shape"] == "oval" else 0.0)
    qx = np.abs(lx) - (p["sx"] / 2 - rad)
    qy = np.abs(ly) - (p["sy"] / 2 - rad)
    out = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0))
    inside = np.minimum(np.maximum(qx, qy), 0)
    return out + inside - rad


def seg_dist(x0, y0, x1, y1, X, Y):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return np.hypot(X - x0, Y - y0)
    t = np.clip(((X - x0) * dx + (Y - y0) * dy) / L2, 0, 1)
    return np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))


def window(x0, y0, x1, y1, r):
    i0, i1 = max(ci(x0 - r) - 1, 0), min(ci(x1 + r) + 2, W)
    j0, j1 = max(cj(y0 - r) - 1, 0), min(cj(y1 + r) + 2, H)
    X, Y = np.meshgrid(XS[i0:i1], YS[j0:j1])
    return (slice(j0, j1), slice(i0, i1)), X, Y


def item_extent(it):
    k = it["kind"]
    if k == "pad":
        r = max(it["sx"], it["sy"]) / 2
        return it["x"] - r, it["y"] - r, it["x"] + r, it["y"] + r
    if k == "via":
        return it["x"] - it["d"] / 2, it["y"] - it["d"] / 2, it["x"] + it["d"] / 2, it["y"] + it["d"] / 2
    return min(it["x0"], it["x1"]) - it["w"] / 2, min(it["y0"], it["y1"]) - it["w"] / 2, max(it["x0"], it["x1"]) + it["w"] / 2, max(it["y0"], it["y1"]) + it["w"] / 2


def item_dist(it, X, Y):
    k = it["kind"]
    if k == "pad":
        return pad_dist(it, X, Y)
    if k == "via":
        return np.hypot(X - it["x"], Y - it["y"]) - it["d"] / 2
    return seg_dist(it["x0"], it["y0"], it["x1"], it["y1"], X, Y) - it["w"] / 2


def item_layers(it):
    if it["kind"] == "via":
        return ("F", "B")
    if it["kind"] == "pad":
        return tuple(it["layers"])
    return (it["layer"],)


# ---------------------------------------------------------------- items
items = []
for p in g["pads"]:
    if p["npth"] or not p["layers"]:
        continue
    items.append(dict(p, kind="pad"))
for t in g["tracks"]:
    items.append(dict(t, kind="track"))
for v in g["vias"]:
    items.append(dict(v, kind="via"))


# ---------------------------------------------------------------- connectivity (union-find)
parent = list(range(len(items)))


def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a


def union(a, b):
    a, b = find(a), find(b)
    if a != b:
        parent[a] = b


def touching(a, b):
    if not set(item_layers(a)) & set(item_layers(b)):
        return False
    # sample points of a, test inside b (and vice versa); good enough for pads / tracks / vias
    def pts(it):
        if it["kind"] == "track":
            return [(it["x0"], it["y0"]), (it["x1"], it["y1"])]
        return [(it["x"], it["y"])]
    for (x, y) in pts(a):
        if item_dist(b, np.array([x]), np.array([y]))[0] <= 0.01:
            return True
    for (x, y) in pts(b):
        if item_dist(a, np.array([x]), np.array([y]))[0] <= 0.01:
            return True
    if a["kind"] == "track" and b["kind"] == "track":         # crossing segments
        d = seg_dist(a["x0"], a["y0"], a["x1"], a["y1"], np.array([b["x0"], b["x1"]]), np.array([b["y0"], b["y1"]]))
        return False
    return False


bynet = {}
for k, it in enumerate(items):
    bynet.setdefault(it["net"], []).append(k)
for n, ks in bynet.items():
    if not n or n.startswith("unconnected"):
        continue
    ext = [item_extent(items[k]) for k in ks]
    for a in range(len(ks)):
        for c in range(a + 1, len(ks)):
            ea, ec = ext[a], ext[c]
            if ea[0] > ec[2] + 0.01 or ec[0] > ea[2] + 0.01 or ea[1] > ec[3] + 0.01 or ec[1] > ea[3] + 0.01:
                continue
            if touching(items[ks[a]], items[ks[c]]):
                union(ks[a], ks[c])


def pieces(n):
    comp = {}
    for k in bynet.get(n, []):
        comp.setdefault(find(k), []).append(k)
    return list(comp.values())


# ---------------------------------------------------------------- dangling copper (pieces without a pad)
delete = []
dead = set()
for n in bynet:
    if not n or n.startswith("unconnected"):
        continue
    for pc in pieces(n):
        if not any(items[k]["kind"] == "pad" for k in pc):
            for k in pc:
                it = items[k]; dead.add(k)
                delete.append({"kind": it["kind"], "net": n, **({"x": it["x"], "y": it["y"]} if it["kind"] == "via" else
                               {"x0": it["x0"], "y0": it["y0"], "x1": it["x1"], "y1": it["y1"], "layer": it["layer"]})})
print("dangling items to delete:", len(delete))

# ---------------------------------------------------------------- obstacle maps
# owner[layer][w]: 0 free, -1 blocked, k = only net k nearby
L = {"F": 0, "B": 1}
own = {(l, w): np.zeros((H, W), np.int32) for l in (0, 1) for w in WIDTHS}
vown = np.zeros((H, W), np.int32)            # via centres
near = {"analog": np.zeros((2, H, W), bool), "digital": np.zeros((2, H, W), bool)}   # within SEP of such a track


def paint(arr, sl, mask, nid):
    a = arr[sl]
    if nid <= 0:
        a[mask] = -1
    else:
        cur = a[mask]
        a[mask] = np.where((cur == 0) | (cur == nid), nid, -1)


def add_item(it, nid):
    x0, y0, x1, y1 = item_extent(it)
    rmax = max(WIDTHS) / 2 + CL + FUDGE + VIA_D / 2
    sl, X, Y = window(x0, y0, x1, y1, rmax + 0.2)
    d = item_dist(it, X, Y)
    for l in item_layers(it):
        for w in WIDTHS:
            paint(own[(L[l], w)], sl, d < w / 2 + CL + FUDGE, nid)
    paint(vown, sl, d < VIA_D / 2 + CL + FUDGE, nid)
    k = sig_kind(it["net"])
    if it["kind"] == "track" and k != "quiet":
        near[k][L[it["layer"]]][sl] |= d < SEP + 0.1
    if it["kind"] == "pad" and min(it["sx"], it["sy"]) < 2.0:
        paint(vown, sl, d < VIA_D / 2 + CL, -1)               # no vias in (small) pads, any net
    if it["kind"] == "via" or (it["kind"] == "pad" and it.get("pth")):
        dr = (it.get("drill") or VIA_DRILL) / 2
        sl2, X2, Y2 = window(it["x"], it["y"], it["x"], it["y"], 1.0)
        paint(vown, sl2, np.hypot(X2 - it["x"], Y2 - it["y"]) < dr + VIA_DRILL / 2 + 0.25 + 0.05, -1)


for k, it in enumerate(items):
    if k in dead:
        continue
    nid = NID[it["net"]] if it["net"] and not it["net"].startswith("unconnected") else -1
    add_item(it, nid)

# board edge, cut-out, antenna, holes, module
XX, YY = np.meshgrid(XS, YS)
inside = (XX > 100.0) & (XX < 170.0) & (YY > 100.0) & (YY < BY1 - 0.05)
inside &= ~((XX > ANTENNA[0]) & (XX < ANTENNA[2]) & (YY < ANTENNA[3]))
edged = np.full((H, W), np.inf)
for e in g["edges"]:
    edged = np.minimum(edged, seg_dist(e[0], e[1], e[2], e[3], XX, YY))
for (l, w), a in own.items():
    a[~inside | (edged < w / 2 + EDGE_CL + FUDGE)] = -1
vown[~inside | (edged < VIA_D / 2 + EDGE_CL + FUDGE)] = -1
for p in g["pads"]:
    if p["npth"]:
        rr = p["drill"] / 2
        d = np.hypot(XX - p["x"], YY - p["y"])
        head = 2.0 if p["drill"] > 1.5 else 0.0
        for (l, w), a in own.items():
            a[d < max(rr + HOLE_CL, head) + w / 2 + FUDGE] = -1
        vown[d < max(rr + HOLE_CL + VIA_DRILL / 2 + 0.05, head + VIA_D / 2)] = -1
ant = (XX > ANTENNA[0] - 0.3) & (XX < ANTENNA[2] + 0.3) & (YY < ANTENNA[3] + 0.3)
for a in own.values():
    a[ant] = -1
vown[ant] = -1
under_mod = (XX > MOD[0]) & (XX < MOD[2]) & (YY > MOD[1]) & (YY < MOD[3])
for w in WIDTHS:
    own[(1, w)][under_mod] = -1
vown[under_mod] = -1
cost_mod = under_mod.ravel()
# second pass: tracks of a previous run mark where switching / analog lines will go, so the early nets keep away
if len(sys.argv) > 5:
    for lyr, x0, y0, x1, y1, w_, n_ in json.load(open(sys.argv[5]))["tracks"]:
        k_ = sig_kind(n_)
        if k_ != "quiet":
            t_ = {"kind": "track", "layer": lyr, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "w": w_}
            sl_, X_, Y_ = window(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), SEP + 0.5)
            near[k_][L[lyr]][sl_] |= item_dist(t_, X_, Y_) < SEP + 0.1
escape = ((XX > MOD[0] - 0.5) & (XX < MOD[2] + 0.5) & (YY > MOD[1]) & (YY < MOD[3] + 1.0))   # forced module escape lanes
for a in list(own.values()) + [vown]:
    a[0, :] = a[-1, :] = a[:, 0] = a[:, -1] = -1

# ---------------------------------------------------------------- A*
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
DOFF = [dx + dy * W for dx, dy, _ in DIRS]


def cells_of(piece, lyr):
    """grid cells (flat) inside the copper of a piece, on layer lyr, passable for the net."""
    out = set()
    for k in piece:
        it = items[k]
        if lyr not in item_layers(it):
            continue
        x0, y0, x1, y1 = item_extent(it)
        sl, X, Y = window(x0, y0, x1, y1, 0.0)
        d = item_dist(it, X, Y)
        js, is_ = np.nonzero(d <= -0.0)
        for jj, ii in zip(js + sl[0].start, is_ + sl[1].start):
            out.add(int(jj) * W + int(ii))
        if it["kind"] in ("pad", "via") and not len(js):
            out.add(cj(it["y"]) * W + ci(it["x"]))
    return out


def astar(nid, w, sources, targets, plane_goal=False, limit=4_000_000, kind="quiet"):
    """sources/targets: sets of state ids (layer * N + cell). Returns list of states or None."""
    other = {"analog": "digital", "digital": "analog"}.get(kind)
    pen = tuple(((near[other][l] & ~escape).ravel().tobytes() if other else bytes(N)) for l in (0, 1))
    okF = ((own[(0, w)] == 0) | (own[(0, w)] == nid)).ravel().tobytes()
    okB = ((own[(1, w)] == 0) | (own[(1, w)] == nid)).ravel().tobytes()
    ok = (okF, okB)
    vok = ((vown == 0) | (vown == nid)).ravel().tobytes()
    costly = cost_mod
    if targets:
        tj = [(s % N) // W for s in targets]; ti = [(s % N) % W for s in targets]
        tx0, tx1, ty0, ty1 = min(ti), max(ti), min(tj), max(tj)
    def h(c):
        if plane_goal or not targets:
            return 0.0
        i, j = c % W, c // W
        dx = max(tx0 - i, 0, i - tx1); dy = max(ty0 - j, 0, j - ty1)
        return max(dx, dy) + 0.4142 * min(dx, dy)
    gbest = {}
    came = {}
    heap = []
    for s in sources:
        lyr, c = divmod(s, N)
        if ok[lyr][c]:
            gbest[s] = 0.0; came[s] = (None, -1)
            heapq.heappush(heap, (h(c), 0.0, s, -1))
    n_exp = 0
    goal_from = {}

    def rebuild(s):
        path = [s]
        while came[path[-1]][0] is not None:
            path.append(came[path[-1]][0])
        return path[::-1]
    while heap:
        f, gc, s, dprev = heapq.heappop(heap)
        if s <= -1000:                                         # plane goal: a via at this cell
            c = -1000 - s
            return rebuild(goal_from[c]), c
        if gc > gbest.get(s, 1e18) + 1e-9:
            continue
        if s in targets:
            return rebuild(s), None
        n_exp += 1
        if n_exp > limit:
            return None, None
        lyr, c = divmod(s, N)
        base = lyr * N
        okl = ok[lyr]
        for k, (dx, dy, st) in enumerate(DIRS):
            c2 = c + DOFF[k]
            if not okl[c2]:
                continue
            if dx and dy and not (okl[c + dx] or okl[c + dy * W]):
                continue                                       # no squeezing diagonally between two blocked cells
            step = st * (MODULE_COST if (lyr == 0 and costly[c2]) else 1.0)
            if dprev >= 0 and dprev != k:
                step += TURN_COST
            if pen[lyr][c2]:
                step += COUPLE_COST
            ng = gc + step
            s2 = base + c2
            if ng < gbest.get(s2, 1e18) - 1e-9:
                gbest[s2] = ng; came[s2] = (s, k)
                heapq.heappush(heap, (ng + h(c2), ng, s2, k))
        if vok[c]:
            if plane_goal:
                ng = gc + VIA_COST
                if ng < gbest.get(("via", c), 1e18):
                    gbest[("via", c)] = ng; goal_from[c] = s
                    heapq.heappush(heap, (ng, ng, -1000 - c, -2))
            s2 = (1 - lyr) * N + c
            if ok[1 - lyr][c]:
                ng = gc + VIA_COST
                if ng < gbest.get(s2, 1e18) - 1e-9:
                    gbest[s2] = ng; came[s2] = (s, -1)
                    heapq.heappush(heap, (ng + h(c), ng, s2, -1))
    return None, None


new_tracks, new_vias = [], []


def commit(path, net, w, via_at=None):
    nid = NID[net]
    segs, vias = [], []
    for a, bb in zip(path, path[1:]):
        la, ca = divmod(a, N); lb, cb = divmod(bb, N)
        if la != lb:
            vias.append([cx(ca % W), cy(ca // W), net])
        else:
            segs.append(("FB"[la], ca, cb))
    if via_at is not None:
        vias.append([cx(via_at % W), cy(via_at // W), net])
    new_vias.extend(vias)
    added = []
    # merge collinear runs
    merged = []
    for lyr, ca, cb in segs:
        if merged and merged[-1][0] == lyr and merged[-1][2] == ca:
            l0, c0, c1 = merged[-1]
            d1 = (c1 % W - c0 % W, c1 // W - c0 // W); d2 = (cb % W - ca % W, cb // W - ca // W)
            if d1[0] * d2[1] - d1[1] * d2[0] == 0 and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                merged[-1] = (l0, c0, cb); continue
        merged.append((lyr, ca, cb))
    for lyr, ca, cb in merged:
        t = {"kind": "track", "layer": lyr, "net": net, "w": w, "x0": cx(ca % W), "y0": cy(ca // W), "x1": cx(cb % W), "y1": cy(cb // W)}
        new_tracks.append([lyr, t["x0"], t["y0"], t["x1"], t["y1"], w, net])
        add_item(t, nid); added.append(t)
    for v in vias:
        t = {"kind": "via", "x": v[0], "y": v[1], "d": VIA_D, "net": net, "drill": VIA_DRILL}
        add_item(t, nid); added.append(t)
    return added


# ---------------------------------------------------------------- what to route
jobs = []
for n in nets:
    if not n or n.startswith("unconnected") or (ONLY and n not in ONLY):
        continue
    pcs = [pc for pc in pieces(n) if not (set(pc) & dead)]
    if n in PLANE:
        for pc in pcs:
            if not any(items[k]["kind"] == "via" or (items[k]["kind"] == "pad" and items[k].get("pth")) for k in pc):
                jobs.append(("plane", n, pc))
    elif len(pcs) > 1:
        jobs.append(("signal", n, pcs))


def span(job):
    if job[0] == "plane":
        return 1e6
    xs = [items[k]["x"] if "x" in items[k] else items[k]["x0"] for pc in job[2] for k in pc]
    ys = [items[k]["y"] if "y" in items[k] else items[k]["y0"] for pc in job[2] for k in pc]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


ORDER = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else []
jobs.sort(key=lambda j: (ORDER.index(j[1]) if j[1] in ORDER else len(ORDER), span(j)))
print("jobs:", len(jobs), "signal nets:", [j[1] for j in jobs if j[0] == "signal"])
fails = []
for kind, n, pcs in jobs:
    nid, w = NID[n], width(n)
    if kind == "plane":
        src = set()
        for lyr in "FB":
            src |= {L[lyr] * N + c for c in cells_of(pcs, lyr)}
        # targets: copper of the same net that already reaches the plane
        tgt = set()
        path, via_c = astar(nid, w, src, tgt, plane_goal=True, limit=200_000)
        if path is None:
            fails.append((n, [items[k].get("ref", "") + "." + items[k].get("num", "") for k in pcs if items[k]["kind"] == "pad"])); continue
        commit(path, n, w, via_at=via_c)
        continue
    pcs = sorted(pcs, key=len, reverse=True)
    tree = list(pcs[0])
    rest = pcs[1:]
    while rest:
        # nearest piece to the tree first
        def dist2(pc):
            a = [(items[k].get("x", items[k].get("x0")), items[k].get("y", items[k].get("y0"))) for k in pc]
            bpts = [(items[k].get("x", items[k].get("x0")), items[k].get("y", items[k].get("y0"))) for k in tree]
            return min((ax - bx) ** 2 + (ay - by) ** 2 for ax, ay in a for bx, by in bpts)
        rest.sort(key=dist2)
        pc = rest.pop(0)
        src = set(); tgt = set()
        for lyr in "FB":
            src |= {L[lyr] * N + c for c in cells_of(pc, lyr)}
            tgt |= {L[lyr] * N + c for c in cells_of(tree, lyr)}
        path, _ = astar(nid, w, src, tgt, kind=sig_kind(n))
        if path is None:
            fails.append((n, [items[k].get("ref", "") + "." + items[k].get("num", "") for k in pc if items[k]["kind"] == "pad"]))
            continue
        added = commit(path, n, w)
        tree += pc
        for it in added:                                       # the new copper joins the tree
            items.append(it); parent.append(len(parent)); tree.append(len(items) - 1)
    print("routed", n, "pieces", len(pcs))
json.dump({"tracks": new_tracks, "vias": new_vias, "delete": delete, "fails": fails}, open(OUT, "w"))
print("tracks", len(new_tracks), "vias", len(new_vias), "FAILED:", fails)
