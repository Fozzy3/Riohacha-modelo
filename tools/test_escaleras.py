"""Lote 2025: the stairs from the plaza down to the labs walkway reach both levels and no wall blocks them.

Usage: uv run --with ifcopenshell --with shapely --with numpy python -I tools/test_escaleras.py
"""
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import numpy as np
from shapely.geometry import MultiPoint

ROOT = Path(__file__).resolve().parent.parent
f = ifcopenshell.open(ROOT / "bim/cip_lote2025.ifc")
lv = json.load(open(ROOT / "datos/sitio_lote2025.json", encoding="utf-8"))["niveles"]
s = ifcopenshell.geom.settings()
s.set("use-world-coords", True)


def shape(e):
    v = np.array(ifcopenshell.geom.create_shape(s, e).geometry.verts).reshape(-1, 3)
    return MultiPoint(v[:, :2]).convex_hull, v[:, 2].min(), v[:, 2].max()


stairs = [shape(e) for e in f.by_type("IfcStairFlight") if e.Name == "Escalera plaza - laboratorios"]
assert len(stairs) == 3, f"{len(stairs)} escaleras"
slabs = {n: [shape(e)[0] for e in f.by_type("IfcSlab") if e.Name == n] for n in ("Plaza en gramoquín", "Patio de laboratorios")}
walls = [shape(e)[0] for e in f.by_type("IfcWall") if e.Name == "Muro de contención"]
for plan, z0, z1 in stairs:
    rise = (lv["plaza"] - lv["patio_c"]) / 15
    assert abs(z1 - (lv["plaza"] - rise)) < 0.01 and z0 <= lv["patio_c"], (z0, z1)  # last tread one riser below the plaza
    for name, polys in slabs.items():
        assert min(p.distance(plan) for p in polys) < 0.05, f"la escalera no llega a {name}"
    assert not any(w.intersects(plan.buffer(-0.1)) for w in walls), "un muro atraviesa la escalera"
print("ok")
