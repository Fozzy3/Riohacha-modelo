"""Index 'Memoria cantidades de obra.pdf': one entry per budget item with its quantity, calculation lines and plan screenshots.

Usage: uv run --with pymupdf python -I tools/index_memoria.py <memoria.pdf> <out_dir>
Writes <out_dir>/indice.json and <out_dir>/img/<item>_<n>.jpg.
An item starts at a span like "5,04"; the next line holds description, unit and quantity.
Images below a header (or on following pages before the next header) belong to that item.
"""
import json
import re
import sys
from pathlib import Path

import pymupdf

ITEM = re.compile(r"^\d{1,2}[,.]\d{2}$")


def code(s):
    a, b = re.split(r"[,.]", s)
    return int(a), int(b)


def is_next_item(text, bold, last):
    """Item codes only grow. Bold headers may skip numbers; regular-weight ones must be the exact
    next code, so calculation values like '4,43' in the same column are not taken as headers."""
    if not ITEM.match(text):
        return False
    c = code(text)
    if last is None:
        return True
    exact_next = c == (last[0], last[1] + 1) or (c[1] == 1 and 0 < c[0] - last[0] <= 3)
    return exact_next or (bold and c > last and c[0] - last[0] <= 3)
UNITS = {"ml", "m2", "m²", "m3", "m³", "und", "un", "kg", "gl", "glb", "d", "m", "lt", "mes", "hr", "jgo", "sum"}


def num(s):
    s = s.strip().replace(".", "").replace(",", ".") if s.count(",") == 1 else s.strip()
    try:
        return float(s)
    except ValueError:
        return None


def lines_of(page):
    """Text lines as (y, [texts sorted by x], first_span_is_bold)."""
    rows = {}
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if t:
                    rows.setdefault(round(s["origin"][1]), []).append((s["origin"][0], t, "Bold" in s["font"]))
    merged = []
    for y in sorted(rows):
        if merged and y - merged[-1][0] <= 2:  # same visual line
            merged[-1][1].extend(rows[y])
        else:
            merged.append((y, list(rows[y])))
    out = []
    for y, spans in merged:
        spans.sort()
        out.append((y, [t for _, t, _ in spans], spans[0][2]))
    return out


def main(pdf, out_dir):
    out = Path(out_dir)
    (out / "img").mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf)
    items, cur, last = [], None, None
    for pno, page in enumerate(doc, start=1):
        events = [(y, "text", (spans, bold)) for y, spans, bold in lines_of(page)]
        for info in page.get_image_info(xrefs=True):
            events.append((info["bbox"][1], "img", info))
        events.sort(key=lambda e: e[0])
        for y, kind, payload in events:
            if kind == "text":
                payload, bold = payload
                if is_next_item(payload[0], bold, last):
                    last = code(payload[0])
                    cur = {"item": "%d.%02d" % last, "descripcion": "", "unidad": None, "cantidad": None,
                           "pagina": pno, "detalle": [], "imagenes": []}
                    items.append(cur)
                    payload = payload[1:]  # inline format: "26.01  Plantas ornamentales  Und  30"
                    if not payload:
                        continue
                if cur and cur["unidad"] is None and len(cur["detalle"]) == 0:
                    # Description lines until one ends with "<unit> <quantity>".
                    unit_idx = next((i for i, t in enumerate(payload) if t.lower() in UNITS), None)
                    if unit_idx is not None and unit_idx == len(payload) - 2 and num(payload[-1]) is not None:
                        cur["descripcion"] = " ".join([cur["descripcion"]] + payload[:unit_idx]).strip()
                        cur["unidad"], cur["cantidad"] = payload[unit_idx].lower(), num(payload[-1])
                    elif len(cur["descripcion"]) < 200:
                        cur["descripcion"] = " ".join([cur["descripcion"]] + payload).strip()
                    continue
                if cur:
                    cur["detalle"].append(" | ".join(payload))
            elif cur and payload["xref"]:
                pix = pymupdf.Pixmap(doc, payload["xref"])
                if pix.n - pix.alpha >= 4:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                name = f"{cur['item']}_{len(cur['imagenes']) + 1}.jpg"
                pix.save(out / "img" / name, jpg_quality=85) if hasattr(pix, "save") else None
                cur["imagenes"].append({"archivo": name, "pagina": pno, "px": [pix.width, pix.height]})
    (out / "indice.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    n_img = sum(len(i["imagenes"]) for i in items)
    print(f"{len(items)} items, {n_img} images, {sum(1 for i in items if i['cantidad'] is None)} without quantity")


if __name__ == "__main__":
    main(*sys.argv[1:])
