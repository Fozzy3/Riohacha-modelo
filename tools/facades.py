"""Extract façade louvers (cortasoles) from the elevations and place them in plan.

Usage: python3 -I tools/facades.py <out.json>
Each elevation is registered to the plan with its structural axes (S-GRID lines), verified against several
columns of A-111. Heights use the main block top (21.20 m) as reference. Louver section 0.10 x 0.30 m
(A-111 cut). Output: list of {"bloque","cara","x","y","z0","z1","rot"} in project meters, rot = louver
yaw in degrees (its 0.30 m depth is perpendicular to the façade).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
K = 0.0440972  # m per PDF point at 1:125

# sheet, y-window of the elevation, along-façade mapping, y of the main block top (Z = 21.20)
ELEVATIONS = {
    "sur": ("A-107", (850, 1460), lambda x: (x - 1114.8) * K, 968.4),
    "norte": ("A-108", (430, 1090), lambda x: (1641.24 - x) * K, 602.3),
    "este": ("A-109", (130, 690), lambda x: -(1928.4 - x) * K, 197.8),
    "oeste": ("A-109", (960, 1540), lambda x: -(x - 893.52) * K, 1054.6),
}
# Louver screens of axis-aligned blocks: elevation, along-range (m), z-range (m), plane (fixed coordinate of
# the louver centreline, from the outer face of the A-111 louver sections minus half depth), yaw.
SCREENS = [
    {"bloque": "A", "cara": "sur", "rango": (-1.3, 26.9), "z": (3.0, 21.3), "plano": ("y", -20.03 + 0.15), "rot": 0},
    {"bloque": "A", "cara": "norte", "rango": (-1.3, 26.9), "z": (11.0, 21.3), "plano": ("y", 1.44 - 0.15), "rot": 0},
    {"bloque": "A", "cara": "este", "rango": (-20.1, 1.5), "z": (11.0, 21.3), "plano": ("x", 26.84 - 0.15), "rot": 90},
    {"bloque": "A", "cara": "oeste", "rango": (-20.1, 1.5), "z": (3.0, 21.3), "plano": ("x", -1.29 + 0.15), "rot": 90},
]


import math

# Louver screens on rotated faces of block B (columns of the wing from A-111: NW (36.514, 5.218),
# N (47.258, 10.096), E (56.073, -9.356), SW corner (36.054, -18.405)). A louver of 0.10 x 0.30 m on a face
# rotated a from the view axis projects 0.10 cos a + 0.30 sin a wide (0.215 m at 24.4°).
# Each entry: elevation, a point of the face line, face direction (deg), along-coordinate range, outward
# normal (deg). The louver centreline sits 0.50 m outside the face line (S18).
OBLIQUE = [
    {"bloque": "B", "cara": "norte", "p0": (36.514, 5.218), "dir": 24.42, "rango": (27.0, 47.4), "normal": 114.42},
    {"bloque": "B", "cara": "sur", "p0": (56.073, -9.356), "dir": 24.32, "rango": (40.2, 56.6), "normal": -65.68},
    {"bloque": "B", "cara": "este", "p0": (47.258, 10.096), "dir": -65.62, "rango": (-10.0, 10.9), "normal": 24.38},
]
LOUVER_OFFSET = 0.50


def thin_verticals(sheet, ywin, along, ytop, width=(0.06, 0.14)):
    """Thin tall rectangles in the louver layer: (h, z0, z1) in meters, deduplicated."""
    data = json.load(open(ROOT / f"fuentes/vectores/{sheet}.json"))
    seen = set()
    for e in data["layers"].get("A-GLAZ-CWMG", []):
        for p in e["paths"]:
            xs, ys = p[0::2], p[1::2]
            if not (ywin[0] < min(ys) and max(ys) < ywin[1]):
                continue
            h0, h1 = sorted((along(min(xs)), along(max(xs))))
            z0, z1 = 21.20 - (max(ys) - ytop) * K, 21.20 - (min(ys) - ytop) * K
            if width[0] < h1 - h0 < width[1] and z1 - z0 > 0.8:
                key = (round((h0 + h1) / 2, 2), round(z0, 1), round(z1, 1))
                if key not in seen:
                    seen.add(key)
                    yield (h0 + h1) / 2, z0, z1


def auditorium_ring():
    """Auditorium louvers: exact plan positions (A-111 cut sections), top 7.42 m, bottom from the elevation
    that sees each face (the arch over the south entrance starts higher; item 6.01 'tipo arcos')."""
    sys.path.insert(0, str(Path(__file__).parent))
    import plan2d
    from shapely.geometry import Point

    sheet = plan2d.Sheet(ROOT / "fuentes/vectores/A-111.json")
    fp = plan2d.FOOTPRINT["D"]
    ring = [g for g in sheet.fills("A-GLAZ-CWMG")
            if fp.buffer(1.0).contains(g.centroid) and not fp.buffer(-0.5).contains(g.centroid)]
    bottoms = {}
    for face in ("sur", "este"):
        sheet_id, ywin, along, ytop = ELEVATIONS[face]
        bottoms[face] = [(h, z0) for h, z0, z1 in thin_verticals(sheet_id, ywin, along, ytop) if z1 < 9]
    minx, miny, maxx, maxy = fp.bounds
    out = []
    for g in ring:
        c = g.centroid
        r = g.minimum_rotated_rectangle.exterior.coords
        long_dx, long_dy = max(((r[1][0] - r[0][0], r[1][1] - r[0][1]), (r[2][0] - r[1][0], r[2][1] - r[1][1])),
                               key=lambda v: v[0] ** 2 + v[1] ** 2)
        face, h = ("sur", c.x) if c.y < miny + 0.3 else ("este", c.y) if c.x > maxx - 0.3 else (None, None)
        near = [z0 for hh, z0 in bottoms.get(face, []) if abs(hh - h) < 0.08] if face else []
        z0 = min(near) if near else 0.24
        rot = 90 if abs(long_dx) > abs(long_dy) else 0  # depth (long side) perpendicular to the façade
        out.append({"bloque": "D", "cara": face or "oculta", "x": round(c.x, 3), "y": round(c.y, 3),
                    "z0": round(z0, 3), "z1": 7.42, "rot": rot})
    return out


def oblique_screens():
    out = []
    for s in OBLIQUE:
        sheet, ywin, along, ytop = ELEVATIONS[s["cara"]]
        d = math.radians(s["dir"])
        dx, dy = math.cos(d), math.sin(d)
        nx, ny = math.cos(math.radians(s["normal"])), math.sin(math.radians(s["normal"]))
        view_x = s["cara"] in ("norte", "sur")  # along-coordinate is X in N/S views, Y in E/W views
        a = math.radians(s["dir"]) if view_x else math.radians(s["dir"] - 90)
        w = 0.10 * abs(math.cos(a)) + 0.30 * abs(math.sin(a))
        for h, z0, z1 in thin_verticals(sheet, ywin, along, ytop, (w - 0.03, w + 0.03)):
            if not (s["rango"][0] <= h <= s["rango"][1]):
                continue
            t = (h - s["p0"][0]) / dx if view_x else (h - s["p0"][1]) / dy
            x, y = s["p0"][0] + t * dx + nx * LOUVER_OFFSET, s["p0"][1] + t * dy + ny * LOUVER_OFFSET
            out.append({"bloque": s["bloque"], "cara": s["cara"], "x": round(x, 3), "y": round(y, 3),
                        "z0": round(z0, 3), "z1": round(z1, 3), "rot": s["dir"]})
    return out


def hidden_east_screen():
    """East face of the main block above block B (z 11.9-21.2, y -11.23..1.30) is hidden in A-109.
    Budget item 6.02 (1,146 m²) only adds up with louvers there too, at the same 0.30 m module (S19)."""
    out, y = [], -11.23 + 0.30
    while y < 1.30:
        out.append({"bloque": "A", "cara": "este-supuesto", "x": 26.84 - 0.15, "y": round(y, 3),
                    "z0": 11.9, "z1": 21.2, "rot": 90})
        y += 0.30
    return out


CANOPY_X = [(-13.87, 2.65), (8.45, 25.05)]  # entrance canopies in front of the south façade (A-107)
SOUTH_BAND_BOTTOM = 3.83  # lowest louver band of the main block south face (A-107)


def merge_occluded(louvers, max_gap=3.0):
    """Elevations only draw visible lines: canopies and Y-column arms in front cut the louvers into pieces.
    Join pieces of the same louver separated by less than max_gap, and on the south face extend louvers that
    start inside the canopy zone down to the band bottom (S25)."""
    by_pos = {}
    for l in louvers:
        by_pos.setdefault((l["bloque"], l["cara"], round(l["x"], 2), round(l["y"], 2)), []).append(l)
    out = []
    for (blk, face, x, y), pieces in by_pos.items():
        pieces.sort(key=lambda p: p["z0"])
        merged = [dict(pieces[0])]
        for p in pieces[1:]:
            if p["z0"] - merged[-1]["z1"] < max_gap:
                merged[-1]["z1"] = max(merged[-1]["z1"], p["z1"])
            else:
                merged.append(dict(p))
        first = merged[0]
        if (blk == "A" and face == "sur" and SOUTH_BAND_BOTTOM < first["z0"] < 7.6
                and any(a <= first["x"] <= b for a, b in CANOPY_X)):
            first["z0"] = SOUTH_BAND_BOTTOM
            first["cara"] = "sur-ocluido"
        out += merged
    return out


def extract():
    out = auditorium_ring() + oblique_screens() + hidden_east_screen()
    for s in SCREENS:
        sheet, ywin, along, ytop = ELEVATIONS[s["cara"]]
        axis, value = s["plano"]
        for h, z0, z1 in thin_verticals(sheet, ywin, along, ytop):
            if not (s["rango"][0] <= h <= s["rango"][1] and s["z"][0] <= z0 and z1 <= s["z"][1]):
                continue
            x, y = (h, value) if axis == "y" else (value, h)
            out.append({"bloque": s["bloque"], "cara": s["cara"], "x": round(x, 3), "y": round(y, 3),
                        "z0": round(z0, 3), "z1": round(z1, 3), "rot": s["rot"]})
    return merge_occluded(out)


if __name__ == "__main__":
    louvers = extract()
    Path(sys.argv[1]).write_text(json.dumps(louvers, indent=0))
    from collections import Counter
    print(len(louvers), "cortasoles", Counter((l["bloque"], l["cara"]) for l in louvers))
