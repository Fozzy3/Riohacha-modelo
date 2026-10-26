"""2D geometry from the extracted PDF sheets, in project meters.

Project frame: origin at the centre of the main block column on axes A/1, X east, Y north
(north of the drawing = true north, SUPUESTOS.md S3). Scale 1:125 (S1).
"""
import json
import math

from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import unary_union, voronoi_diagram

ORIGIN_PT = (1265.22, 409.2)  # A-111, column A/1 of the main block


def rot(u, v, deg):
    a = math.radians(deg)
    return (u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a))


# Ground-floor envelope of each block (project m), measured from the extents of the A-111 cut sections
# (SUPUESTOS.md S13). C is measured in its own frame rotated 45°.
FOOTPRINT = {
    "A": Polygon([(-1.12, 1.30), (26.54, 1.30), (26.54, -19.22), (-1.12, -19.22)]),
    "B": Polygon([(26.54, 1.30), (36.43, 5.27), (47.23, 10.10), (56.00, -9.33), (36.00, -18.40),
                  (31.00, -7.33), (29.90, -6.67), (26.54, -6.67)]),
    "C": Polygon([rot(u, v, 45) for u, v in ((-56.59, -16.54), (-16.10, -16.54), (-16.10, -2.64), (-56.59, -2.64))]),
    "D": Polygon([(23.91, -19.01), (39.66, -19.01), (39.66, -39.93), (23.91, -39.93)]),
}
# Elements a little outside a footprint (louvers, outer mullions) still belong to it.
BLOCK_ZONES = {k: v.buffer(1.5, join_style=2) for k, v in FOOTPRINT.items()}


class Sheet:
    def __init__(self, path, origin_pt=ORIGIN_PT):
        self.data = json.load(open(path))
        self.k = self.data["pt_to_m"]
        self.origin = origin_pt

    def to_m(self, x, y):
        return (x - self.origin[0]) * self.k, -(y - self.origin[1]) * self.k

    def _pts(self, path):
        return [self.to_m(path[i], path[i + 1]) for i in range(0, len(path) - 1, 2)]

    def fills(self, layer):
        """Filled polygons of a layer (cut poché: exact wall/column/mullion sections), unioned."""
        polys = []
        for e in self.data["layers"].get(layer, []):
            if e["fill"] is None:
                continue
            for p in e["paths"]:
                if len(p) >= 6:
                    g = Polygon(self._pts(p)).buffer(0)
                    if g.area > 1e-6:
                        polys.append(g)
        u = unary_union(polys)
        return [g for g in getattr(u, "geoms", [u]) if not g.is_empty]

    def lines(self, layer, min_width=0.0):
        out = []
        for e in self.data["layers"].get(layer, []):
            if e["fill"] is None and e["width"] >= min_width:
                out += [LineString(self._pts(p)) for p in e["paths"] if len(p) >= 4]
        return out

    def column_centres(self):
        return [(g.centroid.x, g.centroid.y) for g in self.fills("S-COLS")]

    def labels(self, size=9.5):
        """Room labels (font 9.5 on A-111); words on consecutive lines are joined ('Oficina de' + 'Laboratoristas')."""
        words = sorted(((self.to_m(t["x"], t["y"]), t["text"]) for t in self.data["texts"]
                        if abs(t["size"] - size) < 0.2 and t["text"] not in ("ARRIBA", "REF.")),
                       key=lambda w: -w[0][1])
        out = []
        for (x, y), text in words:
            prev = next((o for o in out if abs(o[0][0] - x) < 1.2 and 0 < o[0][1] - y < 0.8), None)
            if prev:
                prev[1] += " " + text
                prev[0] = (prev[0][0], y)
            else:
                out.append([(x, y), text])
        return [(Point(p), t) for p, t in out]

    def rooms_ground(self, door=0.6):
        """Rooms of floor 1: block footprint minus walls/glazing/columns, with door gaps (< 2 x door)
        closed so each room is its own region; named by the labels that fall inside."""
        # Partitions: walls, glazing, columns, plus movable/glass partitions drawn as thick A-GENM lines.
        walls = unary_union(self.fills("A-WALL") + self.fills("A-GLAZ-CURT") + self.fills("A-GLAZ-CWMG")
                            + self.fills("S-COLS") + self.lines("A-GLAZ-CURT") + self.lines("A-GENM", 0.9))
        labels = self.labels()
        rooms = []
        for blk, fp in FOOTPRINT.items():
            free = fp.difference(walls.buffer(door))
            for part in getattr(free, "geoms", [free]):
                room = part.buffer(door).intersection(fp).difference(walls)
                room = max(getattr(room, "geoms", [room]), key=lambda g: g.area)
                if room.area < 2.0:
                    continue
                inside = [(p, t) for p, t in labels if room.contains(p)]
                if blk == "B" and len(inside) > 1:
                    # Movable panels between B's rooms leave gaps: share the region among its labels (S23).
                    cells = voronoi_diagram(MultiPoint([p for p, _ in inside]), envelope=room.envelope.buffer(5))
                    for cell in cells.geoms:
                        part_room = cell.intersection(room)
                        name = next(t for p, t in inside if cell.contains(p))
                        rooms.append({"bloque": blk, "nombre": name, "poligono": part_room, "supuesto": "S23"})
                    continue
                rooms.append({"bloque": blk, "nombre": " / ".join(t for _, t in inside) or "Circulación", "poligono": room})
        return rooms

    def block_of(self, geom):
        """Block whose footprint contains the element; nearest footprint when zones overlap or miss."""
        p = geom.representative_point() if hasattr(geom, "representative_point") else Point(geom)
        inside = [n for n, fp in FOOTPRINT.items() if fp.contains(p)]
        if inside:
            return inside[0]
        near = min(FOOTPRINT, key=lambda n: FOOTPRINT[n].distance(p))
        return near if FOOTPRINT[near].distance(p) <= 1.5 else None
