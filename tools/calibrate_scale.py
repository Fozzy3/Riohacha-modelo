"""Calibrate the real drawing scale of each sheet from its own dimension annotations.

Usage: python3 -I tools/calibrate_scale.py fuentes/vectores/A-1xx.json [...]
For every numeric dimension text (e.g. '9.82'), finds the dimension-layer segment whose midpoint
is closest to the text and parallel to it, and computes meters-per-point = value / length.
Prints the dominant ratio per sheet (as an equivalent 1:N scale) and how many dimensions agree.
"""
import json
import math
import re
import sys
from collections import Counter

NUM = re.compile(r"^\d{1,3}[.,]\d{2}$")
DIM_LAYERS = ("A-ANNO-DIMS", "G-ANNO-DIMS")
PT_MM = 25.4 / 72


def segments(data):
    out = []
    for name, entries in data["layers"].items():
        if not name.startswith(DIM_LAYERS):
            continue
        for e in entries:
            for p in e["paths"]:
                for k in range(0, len(p) - 2, 2):
                    out.append((p[k], p[k + 1], p[k + 2], p[k + 3]))
    return out


def calibrate(path):
    data = json.load(open(path))
    segs = segments(data)
    ratios = []
    for t in data["texts"]:
        if not NUM.match(t["text"]):
            continue
        value = float(t["text"].replace(",", "."))
        x0, y0, x1, y1 = t["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        ang = math.radians(t["angle"])
        best = None
        for sx, sy, ex, ey in segs:
            length = math.hypot(ex - sx, ey - sy)
            if length < 5:
                continue
            seg_ang = math.atan2(-(ey - sy), ex - sx)
            if abs(math.sin(seg_ang - ang)) > 0.05:  # must be parallel to the text
                continue
            d = math.hypot((sx + ex) / 2 - cx, (sy + ey) / 2 - cy)
            if d < 25 and (best is None or d < best[0]):
                best = (d, length)
        if best:
            ratios.append(value / best[1])  # meters per PDF point
    scales = Counter(round(r * 1000 / PT_MM) for r in ratios)  # 1:N
    return len(ratios), scales.most_common(6)


if __name__ == "__main__":
    for f in sys.argv[1:]:
        n, top = calibrate(f)
        print(f"{f.split('/')[-1]}: {n} cotas emparejadas; escalas 1:N (N: cuántas) {top}")
