"""Extract every vector path and text from the architectural PDF sheets, grouped by AutoCAD layer.

Usage: uv run --with pymupdf python -I tools/extract_vectors.py <pdf_dir> <out_dir>
Writes <out_dir>/<sheet>.json with:
  pt_to_m   meters per PDF point. The title blocks say 1:100, but every sheet was plotted at 1:125:
            calibrate_scale.py matches 98 of 109 dimension labels in A-111 (and all of them in A-107..A-109).
  layers    {layer: [{"stroke","fill","width","closed","paths":[[x,y,...], ...]}]}
  texts     [{"text","x","y","size","angle","bbox"}]
Curves are flattened to polylines (8 segments per Bezier); coordinates stay in PDF points, y down.
"""
import json
import math
import sys
from pathlib import Path

import pymupdf

PT_TO_M = 25.4 / 72 / 1000 * 125
SHEETS = {
    "A-106": "CORTES.pdf",
    "A-107": "CORTES Y FACHADA SUR ACCESO PRINCIPAL.pdf",
    "A-108": "FACHADA NORTE.pdf",
    "A-109": "FACHADA ESTE Y OESTE.pdf",
    "A-111": "PLANTA OBRAS EXTERIORES Y ORNAMENTACION.pdf",
}


def rgb(c):
    return [round(v, 3) for v in c] if c else None


def bezier(p0, p1, p2, p3, n=8):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0.x + b * p1.x + c * p2.x + d * p3.x, a * p0.y + b * p1.y + c * p2.y + d * p3.y))
    return out


def paths_of(drawing):
    """Split a drawing's items into continuous polylines."""
    paths, cur, last = [], [], None
    for it in drawing["items"]:
        kind = it[0]
        if kind == "re":
            r = it[1]
            paths.append([r.x0, r.y0, r.x1, r.y0, r.x1, r.y1, r.x0, r.y1, r.x0, r.y0])
            last = None
            continue
        if kind == "qu":
            q = it[1]
            paths.append([q.ul.x, q.ul.y, q.ur.x, q.ur.y, q.lr.x, q.lr.y, q.ll.x, q.ll.y, q.ul.x, q.ul.y])
            last = None
            continue
        start = it[1]
        if last is None or math.hypot(start.x - last.x, start.y - last.y) > 1e-3:
            if len(cur) >= 4:
                paths.append(cur)
            cur = [start.x, start.y]
        pts = [(it[2].x, it[2].y)] if kind == "l" else bezier(it[1], it[2], it[3], it[4])
        for x, y in pts:
            cur += [x, y]
        last = it[-1]
    if len(cur) >= 4:
        paths.append(cur)
    return [[round(v, 3) for v in p] for p in paths]


def texts_of(page):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            angle = round(math.degrees(math.atan2(-line["dir"][1], line["dir"][0])), 1)
            for s in line["spans"]:
                t = s["text"].strip()
                if t:
                    out.append({"text": t, "x": round(s["origin"][0], 2), "y": round(s["origin"][1], 2),
                                "size": round(s["size"], 2), "angle": angle,
                                "bbox": [round(v, 2) for v in s["bbox"]]})
    return out


def extract(pdf):
    page = pymupdf.open(pdf)[0]
    layers = {}
    for d in page.get_drawings():
        entry = {"stroke": rgb(d.get("color")), "fill": rgb(d.get("fill")),
                 "width": round(d.get("width") or 0, 3), "closed": bool(d.get("closePath")),
                 "paths": paths_of(d)}
        layers.setdefault(d.get("layer") or "_", []).append(entry)
    return {"pt_to_m": PT_TO_M, "page": [page.rect.width, page.rect.height], "layers": layers, "texts": texts_of(page)}


def main(pdf_dir, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for sheet, name in SHEETS.items():
        data = extract(Path(pdf_dir) / name)
        (out / f"{sheet}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        n = sum(len(v) for v in data["layers"].values())
        print(f"{sheet}: {len(data['layers'])} layers, {n} drawings, {len(data['texts'])} texts")


if __name__ == "__main__":
    main(*sys.argv[1:])
