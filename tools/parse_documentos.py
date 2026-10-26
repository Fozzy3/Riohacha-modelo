"""Parse the unit-price analyses (APU) and the technical specifications into JSON keyed by budget item.

Usage: python3 -I tools/parse_documentos.py <APUs CIP Guajira.pdf> <Especificaciones tecnicas.pdf> <datos_dir>
Needs pdftotext (poppler). Writes <datos_dir>/apu.json and <datos_dir>/especificaciones.json and
reports coverage against <datos_dir>/presupuesto.json.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

CODE = r"\d{1,2}\.\d{2,3}(?:\.\d{2})?"
APU_ITEM = re.compile(rf"^\s*({CODE})\s+(.+?)\s{{2,}}(\S+)\s+\$\s*([\d.,]+)\s*$")
APU_PART = re.compile(r"^\s+(.+?)\s{2,}(\S+)\s+(\S+)\s+([\d.,]+)\s+\$\s*([\d.,]+)\s+\$\s*([\d.,]+)\s*$")
SPEC_HEAD = re.compile(rf"^({CODE})\.?\s*(\S.+)$")


def text(pdf):
    return subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout


def cop(s):
    """Colombian number: '1.794' -> 1794, '0,0022' -> 0.0022."""
    return float(s.replace(".", "").replace(",", "."))


def apus(pdf):
    out, cur = {}, None
    for line in text(pdf).splitlines():
        m = APU_ITEM.match(line)
        if m:
            cur = {"item": m.group(1), "descripcion": m.group(2).strip(), "unidad": m.group(3),
                   "valor_unitario": cop(m.group(4)), "insumos": []}
            out[cur["item"]] = cur
            continue
        p = APU_PART.match(line)
        if cur and p:
            cur["insumos"].append({"nombre": p.group(1).strip(), "tipo": p.group(2), "unidad": p.group(3),
                                   "cantidad": cop(p.group(4)), "valor_unitario": cop(p.group(5)),
                                   "valor_parcial": cop(p.group(6))})
    return out


def especificaciones(pdf):
    lines = [l.strip() for l in text(pdf).splitlines()]
    out, cur, field = {}, None, "descripcion"
    for i, line in enumerate(lines):
        m = SPEC_HEAD.match(line)
        nxt = " ".join(lines[i + 1:i + 3]).lower()
        if m and "unidad de medida" in nxt:
            cur = {"item": m.group(1), "titulo": m.group(2).strip(), "unidad": "", "descripcion": "", "pago": ""}
            out[cur["item"]] = cur
            field = "descripcion"
            continue
        if not cur or not line:
            continue
        low = line.lower()
        if low.startswith("unidad de medida"):
            cur["unidad"] = line.split(":", 1)[-1].strip()
        elif low.startswith("descripción") or low.startswith("descripcion"):
            field = "descripcion"
            cur[field] += line.split(":", 1)[-1].strip() + " "
        elif low.startswith("pago"):
            field = "pago"
            cur[field] += line.split(":", 1)[-1].strip() + " "
        else:
            cur[field] += line + " "
    for v in out.values():
        v["descripcion"], v["pago"] = v["descripcion"].strip(), v["pago"].strip()
    return out


def main(apu_pdf, spec_pdf, datos):
    d = Path(datos)
    a, e = apus(apu_pdf), especificaciones(spec_pdf)
    (d / "apu.json").write_text(json.dumps(a, ensure_ascii=False, indent=1))
    (d / "especificaciones.json").write_text(json.dumps(e, ensure_ascii=False, indent=1))
    items = json.load(open(d / "presupuesto.json"))["items"]
    codes = [i["item"] for i in items]
    price_diff = [(i["item"], i["vr_unitario"], a[i["item"]]["valor_unitario"]) for i in items
                  if i["item"] in a and abs((i["vr_unitario"] or 0) - a[i["item"]]["valor_unitario"]) > 1]
    print(f"apu: {len(a)} items, {sum(len(v['insumos']) for v in a.values())} insumos; "
          f"cubre {sum(c in a for c in codes)}/{len(codes)} items del presupuesto; {len(price_diff)} con precio distinto")
    print("  precio distinto (item, presupuesto, apu):", price_diff[:12])
    print(f"especificaciones: {len(e)} items; cubre {sum(c in e for c in codes)}/{len(codes)}")
    sin = sorted({c.split('.')[0] for c in codes if c not in e and c not in a}, key=int)
    print("  capitulos con items sin apu ni especificacion:", sin)


if __name__ == "__main__":
    main(*sys.argv[1:])
