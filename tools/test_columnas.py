"""Columns end under the roof slab, not flush with its top (coplanar faces flicker and bake dark), and the part of a
facade column that sticks out past the roof edge still reaches the roof level (no notch).

Usage: uv run --with ifcopenshell --with shapely --with numpy python -I tools/test_columnas.py
"""
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
s = ifcopenshell.geom.settings()
s.set("use-world-coords", True)


def tops(e):
    """Upward-facing triangles of an element as (z, plan polygon)."""
    g = ifcopenshell.geom.create_shape(s, e).geometry
    v = np.array(g.verts).reshape(-1, 3)
    for a, b, c in v[np.array(g.faces).reshape(-1, 3)]:
        n = np.cross(b - a, c - a)
        if n[2] > 0.99 * np.linalg.norm(n) > 0:
            yield a[2], Polygon([a[:2], b[:2], c[:2]])


def block(e):
    return ue.get_pset(e, "CIP_Fuente", "Bloque")


for ifc in ("bim/cip.ifc", "bim/cip_lote2025.ifc"):
    f = ifcopenshell.open(ROOT / ifc)
    roofs = {}
    for e in f.by_type("IfcSlab"):
        if e.Name == "Cubierta":
            t = list(tops(e))
            z = max(z for z, _ in t)
            roofs[block(e)] = z, unary_union([p for zz, p in t if abs(zz - z) < 1e-3])
    for c in f.by_type("IfcColumn"):
        if c.Name != "Columna":
            continue
        z, roof = roofs[block(c)]
        t = list(tops(c))
        flush = unary_union([p for zz, p in t if abs(zz - z) < 1e-3])
        assert flush.intersection(roof).area < 1e-4, (ifc, c.GlobalId, "columna al ras de la cubierta")
        outside = unary_union([p for _, p in t]).difference(roof).area
        assert abs(flush.area - outside) < 1e-3, (ifc, c.GlobalId, "muesca bajo el borde de la cubierta")
print("ok")
