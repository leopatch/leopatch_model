import json, sys, math
from PIL import Image, ImageDraw, ImageFont
g = json.load(open(sys.argv[1])); r = json.load(open(sys.argv[2])); out = sys.argv[3]
crop = [float(v) for v in sys.argv[4].split(',')] if len(sys.argv) > 4 else None
X0, Y0, X1, Y1 = crop or g['board']
S = float(sys.argv[5]) if len(sys.argv) > 5 else 25
im = Image.new('RGB', (int((X1 - X0) * S), int((Y1 - Y0) * S)), (20, 40, 25))
d = ImageDraw.Draw(im, 'RGBA')
P = lambda x, y: ((x - X0) * S, (y - Y0) * S)
for p in g['pads']:
    if not p['layers']: continue
    col = (200, 200, 200, 255) if p['npth'] else ((230, 180, 60, 255) if 'F' in p['layers'] else (60, 120, 230, 255))
    if p['shape'] == 'circle' or p['npth']:
        rr = (p['drill'] if p['npth'] else p['sx']) / 2
        x, y = P(p['x'], p['y']); d.ellipse([x - rr * S, y - rr * S, x + rr * S, y + rr * S], fill=col)
    else:
        a = math.radians(p['rot']); hx, hy = p['sx'] / 2, p['sy'] / 2
        pts = [(sx * hx, sy * hy) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        d.polygon([P(p['x'] + u * math.cos(a) + v * math.sin(a), p['y'] - u * math.sin(a) + v * math.cos(a)) for u, v in pts], fill=col)
for t in r['tracks']:
    col = (220, 50, 50, 200) if t['layer'] == 'F' else (60, 160, 255, 170)
    d.line([P(t['x1'], t['y1']), P(t['x2'], t['y2'])], fill=col, width=max(1, int(t['w'] * S)))
for v in r['vias']:
    x, y = P(v['x'], v['y']); rr = 0.225 * S
    col = (120, 255, 120, 255) if v['net'] == 'GND' else ((255, 120, 255, 255) if v['net'] == '+3V3' else (255, 255, 255, 255))
    d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=col)
f = ImageFont.load_default()
for p in g['pads']:
    if p['num'] in ('1',) and p['layers']:
        d.text(P(p['x'] + 0.3, p['y'] - 0.9), p['ref'], fill=(255, 255, 255, 255), font=f)
im.save(out)
