"""Extract wall lines from the A-111 site plan into plan-space meters.

Usage: uv run --with pymupdf python -I tools/extract_plans.py <A-111.pdf> <out.json> [preview.png]
The plan is 1:100 on a 1000 mm wide sheet: 1 pt = 25.4/72 mm paper = 0.035278 m real.
"""
import json
import sys

import pymupdf

PT_TO_M = 25.4 / 72 / 1000 * 100
WALL = (0.39, 0.39, 0.4)  # dark gray, 0.96 pt: building walls and outlines


def wall_segments(page):
    segs = []
    for d in page.get_drawings():
        color = tuple(round(c, 2) for c in (d.get("color") or ()))
        if color != WALL or round(d.get("width") or 0, 2) < 0.9:
            continue
        for item in d["items"]:
            if item[0] == "l":
                segs.append((item[1].x, item[1].y, item[2].x, item[2].y))
            elif item[0] == "re":
                r = item[1]
                segs += [(r.x0, r.y0, r.x1, r.y0), (r.x1, r.y0, r.x1, r.y1),
                         (r.x1, r.y1, r.x0, r.y1), (r.x0, r.y1, r.x0, r.y0)]
    return segs


def labels(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if t:
                    out.append({"text": t, "x": s["origin"][0], "y": s["origin"][1], "size": s["size"]})
    return out


def main(pdf, out, preview=None):
    page = pymupdf.open(pdf)[0]
    segs = wall_segments(page)
    json.dump({"pt_to_m": PT_TO_M, "segments_pt": segs, "labels": labels(page)}, open(out, "w"))
    print(f"{len(segs)} wall segments -> {out}")
    if preview:
        doc = pymupdf.open()
        p = doc.new_page(width=page.rect.width, height=page.rect.height)
        for x0, y0, x1, y1 in segs:
            p.draw_line((x0, y0), (x1, y1), color=(0, 0, 0), width=1.5)
        p.get_pixmap(dpi=36).save(preview)


if __name__ == "__main__":
    main(*sys.argv[1:])
