"""Draw selected layers of an extracted sheet to PNG, one color per layer, with a labeled grid.

Usage: python3 -I tools/preview_layers.py <sheet.json> <out.png> <x0,y0,x1,y1|all> <px_per_pt> LAYER [LAYER ...]
Layer names are matched by prefix; 'TEXT' draws the texts.
"""
import json
import sys

from PIL import Image, ImageDraw

COLORS = [(220, 30, 30), (20, 90, 220), (20, 150, 60), (200, 120, 0), (140, 40, 180),
          (0, 160, 170), (120, 120, 120), (230, 0, 140), (90, 60, 20), (0, 0, 0)]


def main(src, out, box, scale, *wanted):
    data = json.load(open(src))
    w, h = data["page"]
    x0, y0, x1, y1 = (0, 0, w, h) if box == "all" else map(float, box.split(","))
    s = float(scale)
    img = Image.new("RGB", (int((x1 - x0) * s), int((y1 - y0) * s)), "white")
    d = ImageDraw.Draw(img)
    step = 50 if (x1 - x0) < 800 else 100
    for gx in range(int(x0 // step * step), int(x1) + 1, step):
        d.line([((gx - x0) * s, 0), ((gx - x0) * s, img.height)], fill=(235, 225, 225))
        d.text(((gx - x0) * s + 2, 2), str(gx), fill=(200, 120, 120))
    for gy in range(int(y0 // step * step), int(y1) + 1, step):
        d.line([(0, (gy - y0) * s), (img.width, (gy - y0) * s)], fill=(235, 225, 225))
        d.text((2, (gy - y0) * s + 2), str(gy), fill=(200, 120, 120))
    legend = []
    for i, prefix in enumerate(wanted):
        color = COLORS[i % len(COLORS)]
        if prefix == "TEXT":
            for t in data["texts"]:
                if x0 <= t["x"] <= x1 and y0 <= t["y"] <= y1:
                    d.text(((t["x"] - x0) * s, (t["y"] - y0) * s - 8), t["text"], fill=color)
            legend.append(("TEXT", color))
            continue
        for name, entries in data["layers"].items():
            if not name.startswith(prefix):
                continue
            legend.append((name, color))
            for e in entries:
                for p in e["paths"]:
                    pts = [((p[k] - x0) * s, (p[k + 1] - y0) * s) for k in range(0, len(p), 2)]
                    d.line(pts, fill=color, width=1)
    for k, (name, color) in enumerate(legend):
        d.text((10, img.height - 14 * (len(legend) - k) - 4), name, fill=color)
    img.save(out)
    print(out, img.size, [n for n, _ in legend])


if __name__ == "__main__":
    main(*sys.argv[1:])
