"""Grid A* router for LeoPatch v1 (2 signal layers F/B + GND/3V3 planes on In1/In2).
Input: geom.json from place_v1.py. Output: routes.json (tracks + vias) for apply_routes.py."""
import json, math, heapq, sys, itertools
from array import array

GEOM = sys.argv[1] if len(sys.argv) > 1 else '/home/claude/leopatch/geom.json'
OUT = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/leopatch/routes.json'

RES = 0.1
CL = 0.15            # copper clearance
TW = 0.2            # signal track width
STUB_W = 0.2         # fan-out stub width
VIA_D, VIA_DR = 0.45, 0.2
FUDGE = 0.04
EDGE_CL = 0.3
HOLE_CL = 0.2
PLANE_NETS = {'GND': 'In1', '+3V3': 'In2'}
KEEPOUT = (143.3, 99.0, 156.8, 106.6)   # BM20BC antenna area, all layers (x0,y0,x1,y1)
VIA_COST = 8.0

g = json.load(open(GEOM))
BX0, BY0, BX1, BY1 = g['board']
W = int(round((BX1 - BX0) / RES)) + 1
H = int(round((BY1 - BY0) / RES)) + 1
N = W * H
def cx(i): return BX0 + i * RES
def cy(j): return BY0 + j * RES
def ci(x): return int(round((x - BX0) / RES))
def cj(y): return int(round((y - BY0) / RES))

# ------------------------------------------------------------------ nets
pads = [p for p in g['pads'] if p['layers']]
netnames = sorted({p['net'] for p in pads if p['net'] and not p['net'].startswith('unconnected')})
NID = {n: k + 1 for k, n in enumerate(netnames)}
def pid(p):
    n = p['net']
    if not n or n.startswith('unconnected'):
        return -1
    return NID[n]

# ------------------------------------------------------------------ shapes
def shape_of(p, grow=0.0):
    if p['npth']:
        return ('circle', p['x'], p['y'], p['drill'] / 2)
    if p['shape'] == 'circle':
        return ('circle', p['x'], p['y'], p['sx'] / 2)
    rad = p['rr'] if p['shape'] == 'roundrect' else (min(p['sx'], p['sy']) / 2 if p['shape'] == 'oval' else 0.0)
    return ('rrect', p['x'], p['y'], p['sx'] / 2, p['sy'] / 2, p['rot'], rad)

def dist(shape, x, y):
    k = shape[0]
    if k == 'circle':
        return math.hypot(x - shape[1], y - shape[2]) - shape[3]
    if k == 'rrect':
        _, sx, sy, hx, hy, rot, rad = shape
        a = math.radians(rot)
        dx, dy = x - sx, y - sy
        lx = dx * math.cos(a) - dy * math.sin(a)
        ly = dx * math.sin(a) + dy * math.cos(a)
        qx, qy = abs(lx) - (hx - rad), abs(ly) - (hy - rad)
        return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - rad
    if k == 'seg':
        _, x1, y1, x2, y2, hw = shape
        vx, vy = x2 - x1, y2 - y1
        L2 = vx * vx + vy * vy
        t = 0 if L2 == 0 else max(0, min(1, ((x - x1) * vx + (y - y1) * vy) / L2))
        return math.hypot(x - (x1 + t * vx), y - (y1 + t * vy)) - hw
    raise ValueError(k)

def bbox(shape):
    k = shape[0]
    if k == 'circle':
        return shape[1] - shape[3], shape[2] - shape[3], shape[1] + shape[3], shape[2] + shape[3]
    if k == 'rrect':
        r = math.hypot(shape[3], shape[4])
        return shape[1] - r, shape[2] - r, shape[1] + r, shape[2] + r
    _, x1, y1, x2, y2, hw = shape
    return min(x1, x2) - hw, min(y1, y2) - hw, max(x1, x2) + hw, max(y1, y2) + hw

DBG = []
def run(order):
    global own_t, own_v, tracks, vias, fan_points, gap_net
    # ------------------------------------------------------------------ occupancy
    INF_T = CL + TW / 2 + FUDGE
    INF_V = CL + VIA_D / 2 + FUDGE
    own_t = [array('i', [0]) * N for _ in range(2)]
    own_v = [array('i', [0]) * N for _ in range(2)]
    LAYER = {'F': 0, 'B': 1}

    def mark(shape, layer, net, inf_t=INF_T, inf_v=INF_V):
        x0, y0, x1, y1 = bbox(shape)
        m = max(inf_t, inf_v)
        i0, i1 = max(0, ci(x0 - m) - 1), min(W - 1, ci(x1 + m) + 1)
        j0, j1 = max(0, cj(y0 - m) - 1), min(H - 1, cj(y1 + m) + 1)
        ot, ov = own_t[layer], own_v[layer]
        for j in range(j0, j1 + 1):
            y = cy(j); base = j * W
            for i in range(i0, i1 + 1):
                d = dist(shape, cx(i), y)
                if d < inf_t:
                    k = base + i; o = ot[k]
                    if o == 0: ot[k] = net
                    elif o != net: ot[k] = -1
                if d < inf_v:
                    k = base + i; o = ov[k]
                    if o == 0: ov[k] = net
                    elif o != net: ov[k] = -1

    def block_rect(x0, y0, x1, y1, layers=(0, 1)):
        for l in layers:
            for j in range(max(0, cj(y0)), min(H, cj(y1) + 1)):
                for i in range(max(0, ci(x0)), min(W, ci(x1) + 1)):
                    own_t[l][j * W + i] = -1; own_v[l][j * W + i] = -1

    # board edge
    et, ev = EDGE_CL + TW / 2 + FUDGE, EDGE_CL + VIA_D / 2 + FUDGE
    for l in (0, 1):
        for j in range(H):
            for i in range(W):
                x, y = cx(i), cy(j)
                dd = min(x - BX0, BX1 - x, y - BY0, BY1 - y)
                # rounded corners (r = 1 mm)
                for (ccx, ccy) in ((BX0 + 1, BY0 + 1), (BX1 - 1, BY0 + 1), (BX0 + 1, BY1 - 1), (BX1 - 1, BY1 - 1)):
                    if abs(x - ccx) <= 1 and abs(y - ccy) <= 1 and ((x - ccx) * (ccx - (BX0 + BX1) / 2) > 0) and ((y - ccy) * (ccy - (BY0 + BY1) / 2) > 0):
                        dd = min(dd, 1 - math.hypot(x - ccx, y - ccy))
                k = j * W + i
                if dd < et: own_t[l][k] = -1
                if dd < ev: own_v[l][k] = -1
    block_rect(*KEEPOUT)

    # pads
    for p in pads:
        sh = shape_of(p)
        n = pid(p)
        for L in p['layers']:
            if p['npth']:
                mark(sh, LAYER[L], -1, HOLE_CL + TW / 2 + FUDGE, HOLE_CL + VIA_D / 2 + FUDGE)
            else:
                mark(sh, LAYER[L], n)
        if p['drill'] and not p['npth']:
            pass

    tracks, vias = [], []
    def add_track(x1, y1, x2, y2, layer, net, w=TW):
        tracks.append(dict(x1=round(x1, 4), y1=round(y1, 4), x2=round(x2, 4), y2=round(y2, 4), layer='FB'[layer], net=net, w=w))
        mark(('seg', x1, y1, x2, y2, w / 2), layer, NID[net] if net in NID else -1)
    def add_via(x, y, net):
        vias.append(dict(x=round(x, 4), y=round(y, 4), net=net))
        for l in (0, 1):
            mark(('circle', x, y, VIA_D / 2), l, NID[net])

    def free_t(layer, x, y, net):
        i, j = ci(x), cj(y)
        if not (0 <= i < W and 0 <= j < H): return False
        o = own_t[layer][j * W + i]
        return o == 0 or o == net
    def free_v(x, y, net):
        i, j = ci(x), cj(y)
        if not (0 <= i < W and 0 <= j < H): return False
        k = j * W + i
        return all(own_v[l][k] in (0, net) for l in (0, 1))
    def seg_free(layer, x1, y1, x2, y2, net):
        n = max(2, int(math.hypot(x2 - x1, y2 - y1) / 0.05))
        return all(free_t(layer, x1 + (x2 - x1) * t / n, y1 + (y2 - y1) * t / n, net) for t in range(n + 1))

    # ------------------------------------------------------------------ fan-out
    mod = {p['num']: p for p in pads if p['ref'] == 'U1'}
    LET = 'ABCDEFGHJK'
    colx = {l: mod[f'{l}1']['x'] for l in LET}
    rowy = {n: mod[f'A{n}']['y'] for n in range(1, 9)}
    rowy[9] = rowy[8] + (rowy[8] - rowy[7])
    def gap_ok(gx, gy):
        return colx['A'] < gx < colx['K'] and rowy[1] < gy < rowy[9] and not (KEEPOUT[0] <= gx <= KEEPOUT[2] and KEEPOUT[1] <= gy <= KEEPOUT[3])
    gap_net = {}
    fan_points = {}     # net -> list of (x, y) via points that start routes
    def _inner(num):
        return num[0] not in 'AK' and num[1:] not in ('1', '9')
    mod_fan = [(num, p) for num, p in mod.items() if p['net'] in PLANE_NETS or
               (_inner(num) and p['net'] and not p['net'].startswith('unconnected'))]
    # pads needing a via first: signals, then VDD, then GND
    mod_fan.sort(key=lambda t: (0 if t[1]['net'] not in PLANE_NETS else (1 if t[1]['net'] == '+3V3' else 2)))
    fail_fan = []
    for num, p in mod_fan:
        net = p['net']; n = NID[net]
        l, r = num[0], int(num[1:])
        py = rowy[r]
        cands = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                gx, gy = p['x'] + sx * 0.45, py + sy * 0.45
                if not gap_ok(gx, gy):
                    continue
                key = (round(gx, 2), round(gy, 2))
                if key in gap_net and gap_net[key] != net:
                    continue
                # prefer gaps already holding a via of the same net, then gaps among GND/NC neighbours
                share = 0 if gap_net.get(key) == net else 1
                cands.append((share, abs(gy - rowy[5]) if net in PLANE_NETS else -abs(gy - rowy[5]), gx, gy, key))
        cands.sort()
        done = False
        for share, _, gx, gy, key in cands:
            if key not in gap_net:
                # exact check against neighbouring module pads (gap centres are off the 0.1 mm grid)
                bad = False
                for q in mod.values():
                    if abs(q['x'] - gx) < 1.5 and abs(q['y'] - gy) < 1.5 and q['net'] != net:
                        if dist(shape_of(q), gx, gy) < CL + VIA_D / 2 + 0.005:
                            bad = True; break
                if bad:
                    continue
                gap_net[key] = net
                add_via(gx, gy, net)
                if net not in PLANE_NETS:
                    fan_points.setdefault(net, []).append((gx, gy))
            add_track(p['x'], py, gx, gy, 0, net, STUB_W)
            done = True
            break
        if not done:
            fail_fan.append(('U1', num, net))

    # other SMD plane pads
    def fp_center(ref):
        ps = [q for q in pads if q['ref'] == ref]
        return sum(q['x'] for q in ps) / len(ps), sum(q['y'] for q in ps) / len(ps)
    for p in pads:
        if p['ref'] == 'U1' or p['net'] not in PLANE_NETS or p['layers'] != ['F']:
            continue
        net = p['net']; n = NID[net]
        if p['ref'] == 'U201' and p['num'] in ('15', '17') and round(p['rot']) == 90:   # hand fan-out, keeps escapes of 14 / 18 clear
            x, y = p['x'], p['y']
            pts = [(x, y), (x, y - 0.55), (x - 0.6, y - 1.15)] if p['num'] == '15' else [(x, y), (x - 0.75, y), (x - 1.25, y - 0.5)]
            for (a, b2), (c, d2) in zip(pts, pts[1:]):
                add_track(a, b2, c, d2, 0, net, 0.2)
            add_via(pts[-1][0], pts[-1][1], net)
            continue
        if False:      # +VS: hop around the corner to FR (pin 15, also +3V3)
            p15 = [q for q in pads if q['ref'] == 'U201' and q['num'] == '15'][0]
            x, y = p['x'], p['y']
            pts = [(x, y), (x, y - 0.81), (x + 0.8, y - 0.81), (x + 2.2, y + 0.59), (x + 2.2, p15['y']), (p15['x'] + 0.25, p15['y'])]
            for (a, b2), (c, d2) in zip(pts, pts[1:]):
                add_track(a, b2, c, d2, 0, net, 0.2)
            continue
        if p['ref'] == 'U201' and p['num'] == '16':      # GND pin next to the exposed pad: tie it straight in
            ep = [q for q in pads if q['ref'] == 'U201' and q['num'] == '21'][0]
            ux, uy = ep['x'] - p['x'], ep['y'] - p['y']
            if abs(ux) > abs(uy): add_track(p['x'], p['y'], p['x'] + math.copysign(0.9, ux), p['y'], 0, net, 0.2)
            else: add_track(p['x'], p['y'], p['x'], p['y'] + math.copysign(0.9, uy), 0, net, 0.2)
            continue
        if p['ref'] == 'U201' and p['num'] == '21':      # exposed pad: two vias in the pad
            for dx in (-0.6, 0.6):
                add_via(p['x'] + dx, p['y'] + 0.6, net)
            continue
        fx, fy = fp_center(p['ref'])
        ux, uy = p['x'] - fx, p['y'] - fy
        L = math.hypot(ux, uy) or 1.0
        ux, uy = ux / L, uy / L
        half = max(p['sx'], p['sy']) / 2
        cands = []
        # first: straight out along the pad's long axis (clean escape between fine-pitch neighbours)
        esx, esy = (p['sy'], p['sx']) if round(p['rot']) % 180 == 90 else (p['sx'], p['sy'])
        if esy > esx * 1.5: ax, ay = 0.0, math.copysign(1, uy)
        elif esx > esy * 1.5: ax, ay = math.copysign(1, ux), 0.0
        else: ax, ay = ux, uy
        for r in (half + 0.45, half + 0.6, half + 0.8, half + 1.0):
            cands.append((round((p['x'] + ax * r) / RES) * RES, round((p['y'] + ay * r) / RES) * RES))
        for r in (half + 0.45, half + 0.65, half + 0.9, half + 1.2, half + 1.6, half + 2.0, half + 2.5, half + 3.0):
            for a in (0, 30, -30, 60, -60, 90, -90, 120, -120, 150, -150, 180):
                ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
                vx, vy = ux * ca - uy * sa, ux * sa + uy * ca
                cands.append((round((p['x'] + vx * r) / RES) * RES, round((p['y'] + vy * r) / RES) * RES))
        ok = False
        for vx, vy in cands:
            if free_v(vx, vy, n) and seg_free(0, p['x'], p['y'], vx, vy, n):
                add_via(vx, vy, net)
                add_track(p['x'], p['y'], vx, vy, 0, net, TW)
                ok = True
                break
        if not ok:
            fail_fan.append((p['ref'], p['num'], net))

    # ------------------------------------------------------------------ signal routing
    def pad_cells(p):
        sh = shape_of(p)
        x0, y0, x1, y1 = bbox(sh)
        cells = []
        for L in p['layers']:
            l = LAYER[L]
            for j in range(max(0, cj(y0)), min(H, cj(y1) + 1)):
                for i in range(max(0, ci(x0)), min(W, ci(x1) + 1)):
                    if dist(sh, cx(i), cy(j)) <= -0.02:
                        cells.append(l * N + j * W + i)
            if not cells or all(c // N != l for c in cells):
                cells.append(l * N + cj(p['y']) * W + ci(p['x']))
        return cells

    SQ2 = math.sqrt(2)
    DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]

    def astar(net, sources, targets_by_pad):
        n = NID[net]
        tset = {}
        tcent = []
        for k, cells in targets_by_pad.items():
            for c in cells: tset[c] = k
            xs = [(c % N) % W for c in cells]; ys = [(c % N) // W for c in cells]
            tcent.append((sum(xs) / len(xs), sum(ys) / len(ys)))
        def h(idx):
            i, j = idx % W, idx // W
            best = 1e9
            for (ti, tj) in tcent:
                dx, dy = abs(i - ti), abs(j - tj)
                best = min(best, max(dx, dy) + (SQ2 - 1) * min(dx, dy))
            return best
        gsc = {}
        prev = {}
        heap = []
        for s in sources:
            gsc[s] = 0.0
            heapq.heappush(heap, (h(s % N), 0.0, s))
        closed = set()
        while heap:
            f, gs, s = heapq.heappop(heap)
            if s in closed: continue
            closed.add(s)
            if s in tset:
                path = [s]
                while path[-1] in prev: path.append(prev[path[-1]])
                return path[::-1], tset[s]
            l, idx = divmod(s, N)
            i, j = idx % W, idx // W
            ot = own_t[l]
            for di, dj, c in DIRS:
                ni, nj = i + di, j + dj
                if not (0 <= ni < W and 0 <= nj < H): continue
                nidx = nj * W + ni
                o = ot[nidx]
                if o != 0 and o != n: continue
                if di and dj:   # no corner cutting
                    o1, o2 = ot[j * W + ni], ot[nj * W + i]
                    if (o1 != 0 and o1 != n) or (o2 != 0 and o2 != n): continue
                ns = l * N + nidx
                ng = gs + c
                if ng < gsc.get(ns, 1e18):
                    gsc[ns] = ng; prev[ns] = s
                    heapq.heappush(heap, (ng + h(nidx), ng, ns))
            # via
            if own_v[0][idx] in (0, n) and own_v[1][idx] in (0, n):
                ns = (1 - l) * N + idx
                ng = gs + VIA_COST
                if ng < gsc.get(ns, 1e18):
                    gsc[ns] = ng; prev[ns] = s
                    heapq.heappush(heap, (ng + h(idx), ng, ns))
        return None, None

    def emit(net, path):
        """Convert a cell path to tracks + vias (merging collinear steps)."""
        pts = [(c // N, (c % N) % W, (c % N) // W) for c in path]
        segs = []
        k = 0
        while k < len(pts) - 1:
            l, i, j = pts[k]
            nl, ni, nj = pts[k + 1]
            if nl != l:
                add_via(cx(i), cy(j), net); k += 1; continue
            d = (ni - i, nj - j)
            m = k + 1
            while m + 1 < len(pts) and pts[m + 1][0] == l and (pts[m + 1][1] - pts[m][1], pts[m + 1][2] - pts[m][2]) == d:
                m += 1
            segs.append((l, i, j, pts[m][1], pts[m][2]))
            k = m
        for l, i, j, i2, j2 in segs:
            add_track(cx(i), cy(j), cx(i2), cy(j2), l, net)

    def route_all(order):
        failed = []
        for net in order:
            n = NID[net]
            ps = [p for p in pads if p['net'] == net]
            groups = {}
            for p in ps:
                groups.setdefault((p['ref'], p['num']), []).append(p)
            # pads of the same ref+number (e.g. button has 2 pads per pin) count as one terminal
            terms = list(groups.values())
            tree = set()
            start_terms = []
            if net in fan_points:          # start from the module fan-out via
                for (x, y) in fan_points[net]:
                    for l in (0, 1): tree.add(l * N + cj(y) * W + ci(x))
            else:
                first = terms.pop(0)
                for p in first: tree.update(pad_cells(p))
            remaining = {k: sum((pad_cells(p) for p in t), []) for k, t in enumerate(terms)}
            while remaining:
                path, hit = astar(net, list(tree), remaining)
                if path is None:
                    failed.append(net); DBG.append((net, [(t[0]["ref"],t[0]["num"]) for t in terms], list(remaining.keys()))); break
                emit(net, path)
                tree.update(path)
                tree.update(remaining.pop(hit))
        return failed


    failed = route_all(order)
    # plane pins that could not get a via: route them to the nearest via of their plane
    still = []
    for ref, num, net in fail_fan:
        ps = [p for p in pads if p['ref'] == ref and p['num'] == num]
        tgt = {}
        k = 0
        for v in vias:
            if v['net'] == net:
                tgt[k] = [l * N + cj(v['y']) * W + ci(v['x']) for l in (0, 1)]; k += 1
        src = sum((pad_cells(p) for p in ps), [])
        path, hit = astar(net, src, tgt)
        if path is None:
            still.append((ref, num, net))
        else:
            emit(net, path)
    return dict(tracks=tracks, vias=vias, failed=failed, fail_fan=still)

def hpwl(net):
    ps = [p for p in pads if p['net'] == net]
    xs = [p['x'] for p in ps]; ys = [p['y'] for p in ps]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))
sig = [n for n in netnames if n not in PLANE_NETS]
PRIORITY = ['/ECG front end/ACDC', 'ECG_SDN', 'ECG_LO-', 'ECG_LO+', 'ECG_OUT']
order = [n for n in PRIORITY if n in sig] + sorted([n for n in sig if n not in PRIORITY], key=hpwl)
best = None
import random
random.seed(7)
for attempt in range(int(__import__('os').environ.get('ATT','30'))):
    res = run(order)
    print('attempt', attempt, 'failed', res['failed'], 'fanout', res['fail_fan'], DBG[-3:]); DBG.clear()
    if best is None or len(res['failed']) + len(res['fail_fan']) < len(best['failed']) + len(best['fail_fan']):
        best = res
    if not res['failed'] and not res['fail_fan']:
        break
    rest = [n for n in order if n not in res['failed']]
    if attempt % 2: random.shuffle(rest)
    order = res['failed'] + rest
json.dump(best, open(OUT, 'w'), indent=0)
print('tracks', len(best['tracks']), 'vias', len(best['vias']), 'failed', best['failed'], best['fail_fan'])
