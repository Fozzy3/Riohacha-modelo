"""Checks for plan2d: run with  uv run --with shapely python -I tools/test_plan2d.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan2d  # noqa: E402

sheet = plan2d.Sheet(Path(__file__).parent.parent / "fuentes/vectores/A-111.json")

# 1:125 scale and project origin at the main block axis A/1 column centre.
assert abs(sheet.k - 0.0440972) < 1e-6
ox, oy = sheet.to_m(*plan2d.ORIGIN_PT)
assert abs(ox) < 1e-9 and abs(oy) < 1e-9
# North is +Y: higher on the page (smaller y) means larger Y.
assert sheet.to_m(plan2d.ORIGIN_PT[0], plan2d.ORIGIN_PT[1] - 100)[1] > 0

# Round columns on axis 3 of the main block are 12.76 m apart (dimension on the memoria floor plans).
axis3 = sorted(x for x, y in sheet.column_centres() if abs(y + 17.15) < 0.6 and -1 < x < 30)
assert len(axis3) == 3, axis3
assert abs(axis3[1] - axis3[0] - 12.76) < 0.05 and abs(axis3[2] - axis3[1] - 12.76) < 0.05, axis3

# Footprints match the drawing dimensions: main block 27.66 x 20.52 m, auditorium 15.75 x 20.92 m.
fp = plan2d.FOOTPRINT
assert abs(fp["A"].area - 27.66 * 20.52) < 1 and abs(fp["D"].area - 15.75 * 20.92) < 1
# Floor-1 total is within 10 % of the budget's 2,034 m² (budget counts covered connections too).
total = sum(p.area for p in fp.values())
assert abs(total - 2034) / 2034 < 0.10, total

# Every exact wall section on floor 1 falls in a block (no orphan geometry).
orphans = [w.centroid.coords[0] for w in sheet.fills("A-WALL") if sheet.block_of(w) is None]
assert len(orphans) <= 3, orphans
print("ok", {k: round(v.area, 1) for k, v in fp.items()}, "total", round(total, 1), "orphan walls", orphans)

# Ground-floor rooms: the labelled ones exist, and rooms never exceed their block.
rooms = sheet.rooms_ground()
names = [r["nombre"] for r in rooms]
for expected in ("AUDITORIO", "Taller", "SALA 2", "COWORKING", "Oficina de Laboratoristas"):
    assert any(expected in n for n in names), (expected, names)
for r in rooms:
    assert r["poligono"].area <= plan2d.FOOTPRINT[r["bloque"]].area
labelled = sum(r["poligono"].area for r in rooms if r["nombre"] != "Circulación")
print("rooms ok", len(rooms), "labelled area", round(labelled, 1))
