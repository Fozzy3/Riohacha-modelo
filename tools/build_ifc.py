"""Build bim/cip.ifc (IFC4) from the extracted drawings.

Usage: uv run --with ifcopenshell --with shapely python -I tools/build_ifc.py <out.ifc> [datos/sitio_lote2025.json]
v1 scope: georeferenced project, storeys, exact ground-floor walls/columns/glazing/mullions (extruded from
their cut sections in A-111), block slabs and roofs, columns up to each block's roof. Upper-floor partitions,
façade louvers and canopies come in later passes (SUPUESTOS.md lists every assumption by ID).
"""
import json
import math
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.material
import ifcopenshell.api.style
import ifcopenshell.api.aggregate as aggregate
import ifcopenshell.api.context as context
import ifcopenshell.api.georeference as georeference
import ifcopenshell.api.geometry as geometry
import ifcopenshell.api.project as project
import ifcopenshell.api.pset as pset
import ifcopenshell.api.root as root
import ifcopenshell.api.spatial as spatial
import ifcopenshell.api.unit as unit
from shapely.geometry import LineString, Point, Polygon, box

sys.path.insert(0, str(Path(__file__).parent))
import plan2d  # noqa: E402

ROOT = Path(__file__).parent.parent

# Levels from section A-106 (absolute, m). Ground datum 0.00; plaza 0.20; floor 1 at 0.40.
LEVELS = {"Nivel 1": 0.40, "Nivel 2": 4.00, "Nivel 3": 7.80, "Nivel 4": 11.60, "Nivel 5": 15.40, "Cubierta": 19.20}
SLAB = 0.35  # structural slab thickness used for upper floors (S12)
LABS_GLASS_TOP = 3.50  # labs glazing: 3.10 m above plaza (A-107 sections) + floor at 0.40 (S20)

# Georeferencing (S3): project origin = column A/1, placed from Illustration 7 + satellite image.
ORIGIN_E, ORIGIN_N, ORIGIN_H = 5014132.02, 2830635.37, 3.5


FOOTPRINT = plan2d.FOOTPRINT

# Materials (name: (RGB 0-1, transparency)). Specification wording; colours from renders p.77 (S10).
MATERIALS = {
    # Louvers: WPC Ekowood (Informe de avance DEARCA 2025, p. 25), two tones for contrast (S29)
    "WPC Ekowood H 200-100 Teka (cortasol)": ((0.50, 0.30, 0.18), 0.0),
    "WPC Ekowood 90-90 Arena (cortasol)": ((0.76, 0.66, 0.50), 0.0),
    "Tubería metálica 4\" acabado tipo madera": ((0.50, 0.30, 0.18), 0.0),
    "Panel compuesto de aluminio gris oscuro (marco)": ((0.12, 0.12, 0.13), 0.0),
    "Panel compuesto de aluminio gris claro (franja)": ((0.80, 0.80, 0.78), 0.0),
    "Vidrio templado fachada flotante": ((0.30, 0.42, 0.48), 0.55),
    "Perfilería aluminio negro": ((0.08, 0.08, 0.09), 0.0),
    "Mampostería estucada y pintada (blanco)": ((0.93, 0.92, 0.89), 0.0),
    "Concreto 3000 PSI": ((0.70, 0.70, 0.68), 0.0),
    "Gramoquín (adoquín ecológico)": ((0.52, 0.60, 0.42), 0.0),
    "Concreto andén": ((0.78, 0.77, 0.74), 0.0),
    "Grama": ((0.33, 0.52, 0.25), 0.0),
    "Vegetación": ((0.24, 0.45, 0.20), 0.0),
    "Cubierta liviana marquesina (blanco)": ((0.96, 0.96, 0.95), 0.0),
}


def material_for(cls, name, predefined):
    if cls == "IfcShadingDevice":
        return "WPC Ekowood 90-90 Arena (cortasol)" if "90x90" in name else "WPC Ekowood H 200-100 Teka (cortasol)"
    if cls == "IfcCovering":
        return "Panel compuesto de aluminio gris claro (franja)" if "Franja" in name else "Panel compuesto de aluminio gris oscuro (marco)"
    if name.startswith("Columna metálica inclinada"):
        return "Tubería metálica 4\" acabado tipo madera"
    if cls == "IfcRailing":  # fence of the 2025 variant
        return "Perfilería aluminio negro"
    if name == "Muro de contención":
        return "Concreto 3000 PSI"
    if "patio" in name.lower():
        return "Concreto andén"
    if cls == "IfcPlate":
        return "Vidrio templado fachada flotante"
    if cls == "IfcMember":
        return "Perfilería aluminio negro"
    if cls == "IfcWall":
        return "Mampostería estucada y pintada (blanco)"
    if cls == "IfcRoof":
        return "Cubierta liviana marquesina (blanco)"
    if cls == "IfcGeographicElement":
        return "Grama" if "zona verde" in name.lower() else "Vegetación"
    if "gramoquín" in name.lower():
        return "Gramoquín (adoquín ecológico)"
    if "andén" in name.lower():
        return "Concreto andén"
    if "arbórea" in name.lower():
        return "Perfilería aluminio negro"
    return "Concreto 3000 PSI"
# Upper floors of A stop short of the south void over the lobby (memoria 15.07 floors 2-5; S4).
UPPER_A = Polygon([(-1.12, 1.30), (26.54, 1.30), (26.54, -13.34), (-1.12, -13.34)])
# Height of each block's ground-floor walls and roof level (A-106, A-107).
BLOCK = {
    "A": {"roof": 19.20, "wall_top": LEVELS["Nivel 2"] - SLAB, "floors": ["Nivel 2", "Nivel 3", "Nivel 4", "Nivel 5"]},
    "B": {"roof": 11.60, "wall_top": LEVELS["Nivel 2"] - SLAB, "floors": ["Nivel 2", "Nivel 3"]},
    "C": {"roof": 6.80, "wall_top": 6.80 - SLAB, "floors": []},
    "D": {"roof": 7.80, "wall_top": 7.80 - SLAB, "floors": []},
}


class Builder:
    def __init__(self, sitio=None):
        f = self.f = project.create_file(version="IFC4")
        self.project = root.create_entity(f, ifc_class="IfcProject", name="CIP Guajira")
        meters = unit.add_si_unit(f, unit_type="LENGTHUNIT")  # default would be millimetres
        unit.assign_unit(f, units=[meters, unit.add_si_unit(f, unit_type="AREAUNIT"),
                                   unit.add_si_unit(f, unit_type="VOLUMEUNIT"),
                                   unit.add_si_unit(f, unit_type="PLANEANGLEUNIT")])
        model = context.add_context(f, context_type="Model")
        self.body = context.add_context(f, context_type="Model", context_identifier="Body",
                                        target_view="MODEL_VIEW", parent=model)
        # 2025 variant (S31): another origin and a project north rotated clockwise by sitio["norte"] degrees
        east, north = sitio["origen_EN"] if sitio else (ORIGIN_E, ORIGIN_N)
        turn = math.radians(-sitio["norte"]) if sitio else 0.0
        georeference.add_georeferencing(f)
        georeference.edit_georeferencing(
            f, projected_crs={"Name": "EPSG:9377", "Description": "MAGNA-SIRGAS 2018 / Origen-Nacional"},
            coordinate_operation={"Eastings": east, "Northings": north, "OrthogonalHeight": ORIGIN_H,
                                  "XAxisAbscissa": math.cos(turn), "XAxisOrdinate": math.sin(turn), "Scale": 1.0})
        self.site = self._spatial("IfcSite", "Lote CIP - SENA Centro Industrial y de Energías Alternativas", self.project)
        self.building = self._spatial("IfcBuilding", "Centro de Innovación y Productividad", self.site)
        self.storeys = {}
        self.zoff = sitio["desplazamiento"] if sitio else {}  # block -> vertical shift (m)
        levels = {"Semisótano": sitio["semisotano"]["piso"], **LEVELS} if sitio else LEVELS
        for name, z in levels.items():
            s = self._spatial("IfcBuildingStorey", name, self.building)
            s.Elevation = z
            self.storeys[name] = s
        self.count = {}
        self.meta = []  # (element, class, name, block, storey) for the data-linking pass
        self.materials = {}

    def _spatial(self, cls, name, parent):
        e = root.create_entity(self.f, ifc_class=cls, name=name)
        geometry.edit_object_placement(self.f, product=e)
        aggregate.assign_object(self.f, products=[e], relating_object=parent)
        return e

    def _curve(self, coords):
        pts = [self.f.createIfcCartesianPoint((float(x), float(y))) for x, y in coords[:-1]]
        return self.f.createIfcPolyline(pts + [pts[0]])

    def extrusion(self, poly, z0, height):
        poly = poly.buffer(0)
        if poly.geom_type != "Polygon" or poly.area < 1e-5 or height <= 0:
            return None
        outer = self._curve(list(poly.exterior.coords))
        if poly.interiors:
            prof = self.f.createIfcArbitraryProfileDefWithVoids("AREA", None, outer,
                                                                 [self._curve(list(r.coords)) for r in poly.interiors])
        else:
            prof = self.f.createIfcArbitraryClosedProfileDef("AREA", None, outer)
        pos = self.f.createIfcAxis2Placement3D(self.f.createIfcCartesianPoint((0.0, 0.0, float(z0))))
        solid = self.f.createIfcExtrudedAreaSolid(prof, pos, self.f.createIfcDirection((0.0, 0.0, 1.0)), float(height))
        return self.f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", [solid])

    def extrusion_xz(self, profile_xz, y0, depth):
        """Profile drawn in the vertical X-Z plane, extruded southwards (-Y) from y0 by depth."""
        prof = self.f.createIfcArbitraryClosedProfileDef("AREA", None, self._curve(list(profile_xz) + [profile_xz[0]]))
        pos = self.f.createIfcAxis2Placement3D(self.f.createIfcCartesianPoint((0.0, float(y0), 0.0)),
                                               self.f.createIfcDirection((0.0, -1.0, 0.0)),
                                               self.f.createIfcDirection((1.0, 0.0, 0.0)))
        solid = self.f.createIfcExtrudedAreaSolid(prof, pos, self.f.createIfcDirection((0.0, 0.0, 1.0)), float(depth))
        return self.f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", [solid])

    def bar(self, p0, p1, size, round_=False):
        """Square (or round) bar between two 3D points (Y-column arms, inclined tubes)."""
        import numpy as np
        a, b = np.array(p0, float), np.array(p1, float)
        axis = (b - a) / np.linalg.norm(b - a)
        ref = np.array([0.0, 0.0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        xdir = np.cross(ref, axis)
        xdir /= np.linalg.norm(xdir)
        prof = (self.f.createIfcCircleProfileDef("AREA", None, None, size / 2) if round_
                else self.f.createIfcRectangleProfileDef("AREA", None, None, size, size))
        pos = self.f.createIfcAxis2Placement3D(self.f.createIfcCartesianPoint(tuple(map(float, a))),
                                               self.f.createIfcDirection(tuple(map(float, axis))),
                                               self.f.createIfcDirection(tuple(map(float, xdir))))
        solid = self.f.createIfcExtrudedAreaSolid(prof, pos, self.f.createIfcDirection((0.0, 0.0, 1.0)),
                                                  float(np.linalg.norm(b - a)))
        return solid

    def material(self, name):
        """IfcMaterial with a surface style (colours from Table 29 / specifications / renders p.77; S10)."""
        if name not in self.materials:
            rgb, transparency = MATERIALS[name]
            m = ifcopenshell.api.material.add_material(self.f, name=name)
            st = ifcopenshell.api.style.add_style(self.f, name=name)
            ifcopenshell.api.style.add_surface_style(self.f, style=st, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]},
                "Transparency": transparency})
            ifcopenshell.api.style.assign_material_style(self.f, material=m, style=st, context=self.body)
            self.materials[name] = m
        return self.materials[name]

    def placement(self, block):
        import numpy as np
        m = np.eye(4)
        m[2, 3] = self.zoff.get(block or "", 0.0)
        return m

    def element(self, cls, name, storey, rep, block, fuente, predefined=None):
        if rep is None:
            return None
        e = root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=predefined)
        geometry.edit_object_placement(self.f, product=e, matrix=self.placement(block))
        geometry.assign_representation(self.f, product=e, representation=rep)
        ifcopenshell.api.material.assign_material(self.f, products=[e], material=self.material(material_for(cls, name, predefined)))
        spatial.assign_container(self.f, products=[e], relating_structure=self.storeys[storey])
        p = pset.add_pset(self.f, product=e, name="CIP_Fuente")
        pset.edit_pset(self.f, pset=p, properties={"Bloque": block or "", **fuente})
        self.count[cls] = self.count.get(cls, 0) + 1
        self.meta.append((e, cls, name, block or "", storey))
        return e


def build(out, sitio=None):
    b = Builder(sitio)
    sheet = plan2d.Sheet(ROOT / "fuentes/vectores/A-111.json")
    src = lambda capa, sup="": {"Lamina": "A-111", "Capa": capa, "EsSupuesto": bool(sup), "Supuesto": sup}

    # Ground floor: exact cut sections extruded to each block's wall top.
    auditorium_inner = FOOTPRINT["D"].buffer(-0.5)
    for layer, cls, label, pre in (("A-WALL", "IfcWall", "Muro", "STANDARD"), ("A-GLAZ-CURT", "IfcPlate", "Vidrio", "CURTAIN_PANEL"),
                                   ("A-GLAZ-CWMG", "IfcMember", "Montante", "MULLION")):
        for g in sheet.fills(layer):
            blk = sheet.block_of(g)
            if layer == "A-GLAZ-CWMG" and blk == "D" and not auditorium_inner.contains(g.centroid):
                continue  # auditorium ring: these are louvers, added below from fachadas.json
            top = BLOCK[blk]["wall_top"] if blk else LEVELS["Nivel 2"] - SLAB
            if blk == "C" and layer != "A-WALL":
                top = LABS_GLASS_TOP  # labs: glazing only up to 3.50 m, solid band above (S20)
            b.element(cls, f"{label} N1", "Nivel 1", b.extrusion(g, LEVELS["Nivel 1"], top - LEVELS["Nivel 1"]),
                      blk, src(layer, "" if blk else "S13"), pre)
    # Columns run from floor 1 to the roof of their block.
    for g in sheet.fills("S-COLS"):
        blk = sheet.block_of(g) or "A"
        z0 = sitio["semisotano"]["piso"] if sitio and blk in sitio["semisotano"]["bloques"] else LEVELS["Nivel 1"]
        b.element("IfcColumn", "Columna", "Nivel 1", b.extrusion(g, z0, BLOCK[blk]["roof"] - z0), blk, src("S-COLS"), "COLUMN")

    # Slabs: ground slab per block, upper floors, roofs.
    for blk, fp in FOOTPRINT.items():
        b.element("IfcSlab", "Placa de piso N1", "Nivel 1", b.extrusion(fp, 0.20, LEVELS["Nivel 1"] - 0.20), blk,
                  src("envolvente", "S13"), "FLOOR")
        upper = UPPER_A if blk == "A" else fp
        for lvl in BLOCK[blk]["floors"]:
            b.element("IfcSlab", f"Entrepiso {lvl}", lvl, b.extrusion(upper, LEVELS[lvl] - SLAB, SLAB), blk,
                      src("envolvente", "S4"), "FLOOR")
        roof_storey = "Cubierta" if blk == "A" else ("Nivel 4" if blk == "B" else "Nivel 1")
        b.element("IfcSlab", "Cubierta", roof_storey, b.extrusion(upper, BLOCK[blk]["roof"] - SLAB, SLAB), blk,
                  src("envolvente", "S13"), "ROOF")

    # Louvers (cortasoles): WPC 100x200 mm (Teka) alternating with 90x90 mm (Arena) along each façade line (S29);
    # positions from elevations (A) and plan (D), tools/facades.py.
    louvers = json.load(open(ROOT / "datos/fachadas.json"))
    lines = {}  # (block, face) -> sorted positions along the façade; pieces of one louver share a position
    for l in louvers:
        a = math.radians(l["rot"])
        lines.setdefault((l["bloque"], l["cara"]), set()).add(round(l["x"] * math.cos(a) + l["y"] * math.sin(a), 2))
    lines = {k: sorted(v) for k, v in lines.items()}
    for l in louvers:
        a = math.radians(l["rot"])
        along = round(l["x"] * math.cos(a) + l["y"] * math.sin(a), 2)
        thin = lines[(l["bloque"], l["cara"])].index(along) % 2 == 1
        w, d = (0.09, 0.09) if thin else (0.10, 0.20)  # side along the façade, depth across it
        ux, uy, nx, ny = math.cos(a) * w / 2, math.sin(a) * w / 2, -math.sin(a) * d / 2, math.cos(a) * d / 2
        sec = Polygon([(l["x"] + sx * ux + sn * nx, l["y"] + sx * uy + sn * ny) for sx, sn in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        # 2025 variant (DEARCA elevations, p. 22-24): the screens are cut into one band per floor at each slab
        spans = [(l["z0"], l["z1"])]
        if sitio and l["bloque"] in ("A", "B"):
            for zs in BAND_SLABS:
                spans = [(z0, z1) for a0, a1 in spans for z0, z1 in ((a0, min(a1, zs - BAND[0])), (max(a0, zs + BAND[1]), a1))
                         if z1 - z0 > 0.3]
        lamina = "A-111 + alzados" if l["bloque"] == "D" else {"sur": "A-107", "norte": "A-108"}.get(l["cara"], "A-109")
        supuesto = {"oculta": "S6", "este-supuesto": "S19", "sur-ocluido": "S25"}.get(l["cara"], "S18" if l["bloque"] == "B" else "")
        for z0, z1 in spans:
            b.element("IfcShadingDevice", f"Cortasol WPC {'90x90' if thin else '100x200'} {l['cara']}", "Nivel 1",
                      b.extrusion(sec, z0, z1 - z0), l["bloque"],
                      {"Lamina": lamina, "Capa": "A-GLAZ-CWMG", "EsSupuesto": bool(supuesto), "Supuesto": supuesto}, "LOUVER")
    if sitio:
        fascias(b, louvers)
    north_frame(b, tubes=not sitio)

    # Upper-floor envelope behind the louvers: glazing between slabs on every edge of the floor plate (S14).
    for blk in ("A", "B"):
        plate = UPPER_A if blk == "A" else FOOTPRINT[blk]
        levels = BLOCK[blk]["floors"]
        tops = levels[1:] + ["roof"]
        for lvl, nxt in zip(levels, tops):
            z0 = LEVELS[lvl]
            z1 = (BLOCK[blk]["roof"] if nxt == "roof" else LEVELS[nxt]) - SLAB
            ring = list(plate.exterior.coords)
            for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
                edge = LineString([(x0, y0), (x1, y1)])
                glass = edge.buffer(0.02, cap_style=2).intersection(plate.buffer(0.03))
                b.element("IfcPlate", f"Vidrio {lvl}", lvl, b.extrusion(glass, z0, z1 - z0), blk,
                          {"Lamina": "memoria 15.07", "Capa": "", "EsSupuesto": True, "Supuesto": "S14"}, "CURTAIN_PANEL")
                n = max(1, round(edge.length / 1.5))
                for i in range(n + 1):
                    p = edge.interpolate(i / n, normalized=True)
                    b.element("IfcMember", f"Montante {lvl}", lvl, b.extrusion(Point(p).buffer(0.05, cap_style=3), z0, z1 - z0),
                              blk, {"Lamina": "memoria 15.07", "Capa": "", "EsSupuesto": True, "Supuesto": "S14"}, "MULLION")

    # Labs solid band above the glazing, and roof parapets of B and D (A-106/A-107 heights; S20, S21).
    for blk, z0, z1, name, sup in (("C", LABS_GLASS_TOP, 7.60, "Franja maciza fachada laboratorios", "S20"),
                                   ("B", BLOCK["B"]["roof"], 12.10, "Antepecho cubierta", "S21"),
                                   ("D", BLOCK["D"]["roof"], 8.30, "Antepecho cubierta", "S21")):
        fp = FOOTPRINT[blk]
        band = fp.difference(fp.buffer(-0.20, join_style=2))
        storey = {"C": "Nivel 1", "B": "Nivel 4", "D": "Nivel 1"}[blk]
        b.element("IfcWall", name, storey, b.extrusion(band, z0, z1 - z0), blk,
                  {"Lamina": "A-106/A-107", "Capa": "", "EsSupuesto": True, "Supuesto": sup}, "PARAPET")

    if sitio:
        lote2025(b, sheet, sitio)
    else:
        site_works(b, sheet)
    spaces(b, sheet)
    link_budget(b)
    b.f.write(str(out))
    print("escrito", out, b.count)


# Program of each floor-1 room labelled only "Laboratorio"/"SALA n" on A-111 (S22, to confirm with the designer):
# C labs from the end near the main block to the far end; B rooms by number.
LAB_PROGRAM = {
    ("C", 0): "Laboratorio de ensayo de caracterización energética de sistemas fotovoltaicos",
    ("C", 1): "Laboratorio de prácticas de sistemas fotovoltaicos",
    ("C", 2): "Laboratorio de prácticas de sistemas de energía eólica",
    ("C", 3): "Laboratorio de Geodata",
    ("B", "SALA1"): "Laboratorio de negocios digitales",
    ("B", "SALA 2"): "Laboratorio de creatividad e innovación",
    ("B", "SALA 3"): "Laboratorio prototipado digital 3d",
}
PROGRAM_BY_LABEL = {"Bodega / Taller": "Taller de estructura de sistemas fotovoltaicos y eólicos",
                    "AUDITORIO / ESCENARIO": "Auditorio", "ADMIN. / ESTAR / COWORKING / RECEPCION": "Área de Coworking",
                    "Oficina de Laboratoristas": "Oficina de laboratoristas", "Local Comercial": "Locales comerciales",
                    "DEP.": "Depósitos laboratorios", "RECEPCION": "Recepción", "ASEO": "Cuarto de aseo"}


def spaces(b, sheet):
    """IfcSpace per room: floor 1 with exact geometry from A-111; floors 2-5 from the furniture sheet without
    geometry (A-101..A-105 missing). Furniture (03.1) and equipment (06) attached as psets."""
    mob = json.load(open(ROOT / "datos/mobiliario.json"))
    dot = {g["espacio"].lower(): g for g in json.load(open(ROOT / "datos/dotacion.json"))}
    f = b.f

    def furniture_for(program, floor):
        m = next((s for s in mob if s["piso"] == floor and s["espacio"].lower().startswith(program.lower()[:24])), None)
        return m

    generic = {"laboratorio", "de", "del", "y", "la", "las", "los", "sistemas", "para", "e", "taller"}

    def words(text):
        return {w.strip("().,") for w in text.lower().split()} - generic

    def equipment_for(program):
        """Equipment group sharing the most distinctive words with the program ('eólica', 'geodata', ...)."""
        best, group = 0, None
        for name, g in dot.items():
            if name.startswith(("equipos y software", "equipos ofim", "sistema de vig")):
                continue
            shared = len(words(program) & words(name))
            if shared > best:
                best, group = shared, g
        return group

    def add_space(name, program, storey, rep, block, fuente, area=None, furniture=None):
        sp = root.create_entity(f, ifc_class="IfcSpace", name=name, predefined_type="INTERNAL")
        sp.LongName = program
        geometry.edit_object_placement(f, product=sp, matrix=b.placement(block))
        if rep is not None:
            geometry.assign_representation(f, product=sp, representation=rep)
        aggregate.assign_object(f, products=[sp], relating_object=b.storeys[storey])
        props = {"Programa": program, "Bloque": block, "Piso": storey, **fuente}
        if area is not None:
            props["AreaNetaM2"] = round(area, 2)
        p = pset.add_pset(f, product=sp, name="CIP_Espacio")
        pset.edit_pset(f, pset=p, properties=props)
        if furniture and furniture["mobiliario"]:
            items = [f"{int(n)} x {k[:70]}" for k, n in furniture["mobiliario"].items()]
            p = pset.add_pset(f, product=sp, name="CIP_Mobiliario")
            pset.edit_pset(f, pset=p, properties={"CantidadEspacios": float(furniture["cantidad_espacios"] or 1),
                                                  "TotalMuebles": float(sum(furniture["mobiliario"].values())),
                                                  "Detalle": "; ".join(items)[:4000]})
        eq = equipment_for(program)
        if eq:
            p = pset.add_pset(f, product=sp, name="CIP_Dotacion")
            pset.edit_pset(f, pset=p, properties={
                "Grupo": eq["espacio"], "NumeroEquipos": float(len(eq["equipos"])),
                "ValorTotalCOP": float(sum(e["vr_total"] for e in eq["equipos"])),
                "Equipos": "; ".join(f"{int(e['cantidad'])} x {e['equipo'][:60]}" for e in eq["equipos"])[:4000]})
        b.count["IfcSpace"] = b.count.get("IfcSpace", 0) + 1
        return sp

    # Floor 1: exact rooms.
    rooms = sheet.rooms_ground()
    labs_c = sorted([r for r in rooms if r["bloque"] == "C" and r["nombre"] == "Laboratorio"],
                    key=lambda r: -(r["poligono"].centroid.x + r["poligono"].centroid.y))  # nearest to block A first
    for r in rooms:
        label = r["nombre"]
        if r["bloque"] == "C" and label == "Laboratorio":
            program, sup = LAB_PROGRAM[("C", labs_c.index(r))], "S22"
        elif (r["bloque"], label) in LAB_PROGRAM:
            program, sup = LAB_PROGRAM[(r["bloque"], label)], "S22"
        elif label == "DEP." and r["bloque"] != "C":
            program, sup = "Depósito", ""
        else:
            program, sup = PROGRAM_BY_LABEL.get(label, label.title()), r.get("supuesto", "")
        top = BLOCK[r["bloque"]]["wall_top"]
        add_space(label.title(), program, "Nivel 1", b.extrusion(r["poligono"], LEVELS["Nivel 1"], top - LEVELS["Nivel 1"]),
                  r["bloque"], {"Lamina": "A-111", "EsSupuesto": bool(sup), "Supuesto": sup},
                  area=r["poligono"].area, furniture=furniture_for(program, "Piso 1"))

    # Equipment groups without an identifiable room hang from the building so no value is lost.
    used = {g["espacio"] for g in (equipment_for(r) for r in list(LAB_PROGRAM.values()) + list(PROGRAM_BY_LABEL.values())) if g}
    rest = [g for g in dot.values() if g["espacio"] not in used and not g["espacio"].lower().startswith("equipos y software")]
    p = pset.add_pset(f, product=b.building, name="CIP_DotacionSinEspacio")
    pset.edit_pset(f, pset=p, properties={
        "Grupos": "; ".join(f"{g['espacio']} ({len(g['equipos'])} equipos)" for g in rest),
        "ValorTotalCOP": float(sum(e["vr_total"] for g in rest for e in g["equipos"]))})

    # Floors 2-5: program only.
    for s in mob:
        floor = int(s["piso"].split()[-1])
        if floor == 1 or s["espacio"].lower().startswith("ventanas"):
            continue
        add_space(s["espacio"][:60], s["espacio"], f"Nivel {floor}", None, "A/B",
                  {"Lamina": "03.1 Mobiliario", "EsSupuesto": True, "Supuesto": "S4"}, furniture=s)


QUANTITY = {"m²": ("IfcQuantityArea", "AreaValue"), "m2": ("IfcQuantityArea", "AreaValue"),
            "m³": ("IfcQuantityVolume", "VolumeValue"), "m3": ("IfcQuantityVolume", "VolumeValue"),
            "ml": ("IfcQuantityLength", "LengthValue"), "m": ("IfcQuantityLength", "LengthValue"),
            "kg": ("IfcQuantityWeight", "WeightValue")}


def link_budget(b):
    """5D: the whole budget as an IfcCostSchedule (chapters > items, unit price in COP, budget quantity),
    items assigned to elements by datos/mapeo_items.csv, plus readable psets on each element."""
    import csv

    import ifcopenshell.api.control as control
    import ifcopenshell.api.cost as cost

    f = b.f
    pres = json.load(open(ROOT / "datos/presupuesto.json"))
    specs = json.load(open(ROOT / "datos/especificaciones.json"))
    cop = unit.add_monetary_unit(f, currency="COP")
    unit.assign_unit(f, units=[cop])
    schedule = cost.add_cost_schedule(f, name="Presupuesto CIP Guajira 5 (subsanación 21-oct-2022)", predefined_type="BUDGET")
    chapters, items = {}, {}
    for n, name in sorted(pres["capitulos"].items(), key=lambda kv: int(kv[0])):
        ci = cost.add_cost_item(f, cost_schedule=schedule)
        cost.edit_cost_item(f, cost_item=ci, attributes={"Identification": str(n), "Name": name})
        chapters[int(n)] = ci
    for it in pres["items"]:
        ci = cost.add_cost_item(f, cost_item=chapters[it["capitulo"]])
        cost.edit_cost_item(f, cost_item=ci, attributes={"Identification": it["item"], "Name": it["descripcion"][:255],
                                                          "Description": it["descripcion"]})
        value = cost.add_cost_value(f, parent=ci)
        cost.edit_cost_value(f, cost_value=value, attributes={"AppliedValue": float(it["vr_unitario"] or 0)})
        qcls, qattr = QUANTITY.get(it["unidad"].lower(), ("IfcQuantityCount", "CountValue"))
        q = cost.add_cost_item_quantity(f, cost_item=ci, ifc_class=qcls)
        setattr(q, qattr, float(it["cantidad"] or 0))
        items[it["item"]] = (ci, it)

    rules = list(csv.DictReader(open(ROOT / "datos/mapeo_items.csv", encoding="utf-8")))
    assigned = {}
    for e, cls, name, block, storey in b.meta:
        codes = []
        for r in rules:
            if r["clase"] == cls and r["nombre"] in name and r["bloque"] in ("", block) and r["nivel"] in ("", storey):
                codes += [c for c in r["items"].split("|") if c not in codes]
        if not codes:
            continue
        for c in codes:
            assigned.setdefault(c, []).append(e)
        main = items[codes[0]][1]
        p = pset.add_pset(f, product=e, name="CIP_Presupuesto")
        pset.edit_pset(f, pset=p, properties={
            "Items": ", ".join(codes), "ItemPrincipal": main["item"], "Descripcion": main["descripcion"],
            "Unidad": main["unidad"], "CantidadPresupuestada": float(main["cantidad"]),
            "ValorUnitarioCOP": float(main["vr_unitario"] or 0), "ValorTotalItemCOP": float(main["vr_total"] or 0)})
        spec = next((specs[c] for c in codes if c in specs), None)
        if spec:
            p = pset.add_pset(f, product=e, name="CIP_Especificacion")
            pset.edit_pset(f, pset=p, properties={"Item": spec["item"], "Titulo": spec["titulo"],
                                                  "Unidad": spec["unidad"], "Descripcion": spec["descripcion"][:4000]})
    for code, elements in assigned.items():
        control.assign_control(f, relating_control=items[code][0], related_objects=elements)
    print(f"presupuesto: {len(items)} items en IfcCostSchedule; {len(assigned)} items enlazados a "
          f"{sum(1 for m in b.meta if any(m[0] in v for v in assigned.values()))} elementos")


# Site outline: A-FLOR polygon of A-111 without the walkway notch (area ~4,540 m²; memoria 1.02 cleans 4,664 m²).
LOT = Polygon([(-7.723, 9.647), (32.959, 9.647), (48.03, 16.489), (60.174, -10.261), (44.294, -17.468),
               (44.294, -50.572), (-17.238, -50.572), (-28.08, -61.415), (-46.966, -42.524), (-7.723, -3.286)])
WALK = box(6.914, -50.572, 9.97, -19.6)  # central walkway with ramps (A-111, layer 0)
GREEN_BAND = 2.5  # lawn strip along the lot edge; 2.5 m makes the plaza 1,866 m² = budget item 24.06 (S16)
# Entrance canopies (A-107 south + A-109 east/west, layer A-GENM): gable 8.25 m wide, eave 5.18, ridge 7.95.
CANOPIES_X = [(-13.87, -5.59), (-5.59, 2.65), (8.45, 16.73), (16.73, 25.05)]
CANOPY_Y = (-55.07, -60.28)


# North face of block A, floors 2-3 (A-108): a frame round the glazing and inclined 4" tubes finished like wood
# ("pérgola metálica tipo madera"; item 6.04 "columnas metálicas inclinadas ... tubería 4\" 7.2 mts").
# Tube axes (X at z 3.83 and at z 10.92) from the two drawn edges of each tube on layer A-GENM. The memoria counts
# 24 tubes of 7.21 m; the elevation draws 20 (PREGUNTAS H8). Frame: 0.40 m bands (A-108), 0.60 m projection (S32).
TUBES_A_NORTE = [(-0.10, 1.15), (1.56, 0.31), (2.20, 3.45), (4.29, 5.55), (5.38, 4.13), (6.49, 7.74), (7.81, 6.56),
                 (8.89, 10.14), (9.10, 7.85), (10.49, 11.73), (10.86, 9.61), (12.58, 13.83), (13.54, 12.29),
                 (14.78, 16.03), (15.55, 14.30), (16.58, 17.83), (17.40, 16.15), (17.87, 19.12), (19.12, 20.37),
                 (19.89, 18.64)]
FRAME_A_NORTE = {"x": (-1.31, 26.70), "z": (3.44, 11.47), "y": (1.30, 1.90), "banda": 0.40, "medio": 7.80}
BAND_SLABS = (4.00, 7.80, 11.60, 15.40, 19.20)  # 2025 variant: louver bands stop at each slab...
BAND = (0.35, 0.25)  # ...this far below / above it, where a light aluminium-composite fascia runs (S31)


def north_frame(b, tubes):
    f = FRAME_A_NORTE
    (x0, x1), (z0, z1), (y0, y1), t = f["x"], f["z"], f["y"], f["banda"]
    fuente = {"Lamina": "A-108", "Capa": "A-GLAZ-CWMG", "EsSupuesto": True, "Supuesto": "S32"}
    for name, (bx0, bx1, bz0, bz1) in (("Marco fachada norte", (x0, x1, z1 - t, z1)), ("Marco fachada norte", (x0, x1, z0, z0 + t)),
                                       ("Marco fachada norte", (x0, x1, f["medio"] - t / 2, f["medio"] + t / 2)),
                                       ("Marco fachada norte", (x0, x0 + t, z0, z1)), ("Marco fachada norte", (x1 - t, x1, z0, z1))):
        b.element("IfcCovering", name, "Nivel 2", b.extrusion(box(bx0, y0, bx1, y1), bz0, bz1 - bz0), "A", fuente, "CLADDING")
    if not tubes:
        return
    y = (y0 + y1) / 2
    for xb, xt in TUBES_A_NORTE:
        rep = b.f.createIfcShapeRepresentation(b.body, "Body", "SweptSolid", [b.bar((xb, y, 3.83), (xt, y, 10.92), 0.114, True)])
        b.element("IfcMember", "Columna metálica inclinada", "Nivel 2", rep, "A",
                  {"Lamina": "A-108", "Capa": "A-GENM", "EsSupuesto": False, "Supuesto": ""}, "STRUT")


def fascias(b, louvers):
    """2025 variant: a light fascia (0.60 x 0.25 m) along every louvered face of A and B at each slab level."""
    from collections import defaultdict
    faces = defaultdict(list)
    for l in louvers:
        if l["bloque"] in ("A", "B"):
            a = math.radians(l["rot"])
            off = round(-l["x"] * math.sin(a) + l["y"] * math.cos(a), 0)  # distance of the screen plane: merges pieces
            faces[(l["bloque"], round(l["rot"]), off)].append(l)
    fuente = {"Lamina": "Informe de avance V.01 (DEARCA 2025)", "Capa": "", "EsSupuesto": True, "Supuesto": "S31"}
    for (blk, rot, _), ls in faces.items():
        a = math.radians(rot)
        c, s_ = math.cos(a), math.sin(a)
        along = [l["x"] * c + l["y"] * s_ for l in ls]
        t = sum(-l["x"] * s_ + l["y"] * c for l in ls) / len(ls)
        s0, s1 = min(along) - 0.1, max(along) + 0.1
        ring = [(u * c - v * s_, u * s_ + v * c) for u, v in ((s0, t - 0.125), (s1, t - 0.125), (s1, t + 0.125), (s0, t + 0.125))]
        zmin, zmax = min(l["z0"] for l in ls), max(l["z1"] for l in ls)
        for zs in BAND_SLABS:
            if zmin < zs < zmax:
                b.element("IfcCovering", "Franja de losa", "Nivel 1", b.extrusion(Polygon(ring), zs - BAND[0], sum(BAND)), blk,
                          fuente, "CLADDING")


def site_works(b, sheet):
    from shapely.ops import unary_union

    fuente = lambda capa, sup="": {"Lamina": "A-111", "Capa": capa, "EsSupuesto": bool(sup), "Supuesto": sup}
    buildings = unary_union(list(FOOTPRINT.values()))
    inner = LOT.buffer(-GREEN_BAND, join_style=2)
    lawn = LOT.difference(inner).difference(buildings)
    plaza = inner.difference(buildings).difference(WALK)
    # South access outside the lot: lawn strips (A-FLOR fills) on both sides of the walkway, which continues
    # to the canopies and the road.
    south = box(-25, -63, 60, -50.7)
    access_lawn = unary_union([g for g in sheet.fills("A-FLOR") if south.contains(g.centroid)]).buffer(0.05).buffer(-0.05)
    access_walk = box(5.913, -61.4, 10.03, -50.572)
    for geom, name, cls, pre, capa, sup in ((lawn, "Zona verde perimetral", "IfcGeographicElement", "TERRAIN", "A-FLOR", "S16"),
                                            (access_lawn, "Zona verde acceso sur", "IfcGeographicElement", "TERRAIN", "A-FLOR", ""),
                                            (plaza, "Plaza en gramoquín", "IfcSlab", "USERDEFINED", "A-FLOR-PATT", ""),
                                            (WALK, "Andén central", "IfcSlab", "USERDEFINED", "0", ""),
                                            (access_walk, "Andén central acceso sur", "IfcSlab", "USERDEFINED", "0", "")):
        for poly in getattr(geom, "geoms", [geom]):
            e = b.element(cls, name, "Nivel 1", b.extrusion(poly, 0.0, 0.20), None, fuente(capa, sup), pre)
            if e is not None and pre == "USERDEFINED":
                e.ObjectType = name

    # Canopies: gable roof slab 0.25 m thick + "tree" column with four inclined arms (S17).
    y0, y1 = CANOPY_Y
    yc = (y0 + y1) / 2
    for xa, xb in CANOPIES_X:
        xc = (xa + xb) / 2
        roof = [(xa, 4.93), (xc, 7.70), (xb, 4.93), (xb, 5.18), (xc, 7.95), (xa, 5.18)]
        b.element("IfcRoof", "Marquesina acceso sur", "Nivel 1", b.extrusion_xz(roof, y0, y0 - y1), None,
                  {"Lamina": "A-107/A-109", "Capa": "A-GENM", "EsSupuesto": False, "Supuesto": ""}, "GABLE_ROOF")
        items = [b.bar((xc, yc, 0.20), (xc, yc, 4.17), 0.40)]
        items += [b.bar((xc, yc, 4.0), (xc + sx * 1.85, yc + sy * 1.05, 6.2), 0.22) for sx in (-1, 1) for sy in (-1, 1)]
        rep = b.f.createIfcShapeRepresentation(b.body, "Body", "SweptSolid", items)
        b.element("IfcColumn", "Columna arbórea marquesina", "Nivel 1", rep, None,
                  {"Lamina": "A-107/A-109", "Capa": "A-GENM", "EsSupuesto": True, "Supuesto": "S17"}, "COLUMN")

    # Vegetation from plan symbols: palms (Ø≈5 m), medium plants (ARBOLES), ornamental (PAISAVEGSIMBOLOGIA orange).
    for kind, cx, cy, diam in vegetation(sheet):
        e = b.element("IfcGeographicElement", kind, "Nivel 1",
                      b.extrusion(Point(cx, cy).buffer(diam / 2, 12), 0.20, 0.05), None, fuente("ARBOLES/PAISAVEGSIMBOLOGIA"),
                      "USERDEFINED")
        if e is not None:
            e.ObjectType = "VEGETACION"


def vegetation(sheet):
    from shapely.ops import unary_union

    groups = {("ARBOLES", (0.0, 0.38, 0.094)): None, ("PAISAVEGSIMBOLOGIA", (0.867, 0.647, 0.0)): "Planta ornamental"}
    legend = box(47, -62, 70, -36)  # ORNAMENTACIÓN legend box on A-111
    out = []
    for (layer, color), fixed in groups.items():
        lines = [LineString(sheet._pts(p)) for e in sheet.data["layers"][layer] if tuple(e["stroke"] or []) == color
                 for p in e["paths"] if len(p) >= 4]
        u = unary_union([l.buffer(0.15) for l in lines])
        for g in getattr(u, "geoms", [u]):
            if g.area < 0.3 or legend.contains(g.centroid):
                continue
            diam = max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1])
            # Symbol size gives the species: Ø5.3 palms (3, item 26.05), Ø4.0 medium plants (10, item 26.02);
            # smaller circles are parts of those same symbols.
            kind = fixed or ("Palmera grande" if diam >= 5 else "Planta mediana" if diam >= 3.5 else None)
            if kind:
                out.append((kind, g.centroid.x, g.centroid.y, diam))
    return out


def lote2025(b, sheet, sitio):
    """2025 variant (approximate, SUPUESTOS S30-S31): semi-basement parking under A, B and D at natural ground level,
    plaza fill with retaining walls, block C platform 2.40 m lower, fence, guard house and the existing trees."""
    from shapely.ops import unary_union

    lv = sitio["niveles"]
    fuente = {"Lamina": "Informe de avance V.01 (DEARCA 2025)", "Capa": "", "EsSupuesto": True, "Supuesto": "S31"}
    basement = sitio["semisotano"]["bloques"]
    plaza = Polygon(sitio["plaza"]).difference(unary_union([FOOTPRINT[k] for k in basement]))
    patio_c = FOOTPRINT["C"].buffer(3.0, join_style=2).difference(Polygon(sitio["plaza"])).difference(FOOTPRINT["C"])
    for k in basement:
        b.element("IfcSlab", "Placa semisótano parqueadero", "Semisótano", b.extrusion(FOOTPRINT[k], lv["natural"] - 0.20, 0.20),
                  k, fuente, "FLOOR")
    for poly, name, z in ((plaza, "Plaza en gramoquín", lv["plaza"]), (patio_c, "Patio de laboratorios", lv["patio_c"])):
        for g in getattr(poly, "geoms", [poly]):
            e = b.element("IfcSlab", name, "Nivel 1", b.extrusion(g, z - 0.20, 0.20), None, fuente, "USERDEFINED")
            if e is not None:
                e.ObjectType = name
    # Retaining walls on every edge of the plaza and of the C platform: down to the natural ground, or to the C
    # platform; a 1.0 m parapet where the edge is open (not against a building).
    blocks = unary_union(list(FOOTPRINT.values()))
    for poly, top in ((Polygon(sitio["plaza"]), lv["plaza"]), (patio_c, lv["patio_c"])):
        for g in getattr(poly, "geoms", [poly]):
            ring = list(g.exterior.coords)
            for p0, p1 in zip(ring, ring[1:]):
                edge = LineString([p0, p1])
                if edge.length < 0.3:
                    continue
                mid = edge.interpolate(0.5, normalized=True)
                out = Point(mid.x + (p1[1] - p0[1]) / edge.length * 1.5, mid.y - (p1[0] - p0[0]) / edge.length * 1.5)
                if not g.exterior.is_ccw:
                    out = Point(2 * mid.x - out.x, 2 * mid.y - out.y)
                if patio_c.contains(out) and top == lv["plaza"]:
                    bottom = lv["patio_c"]
                elif Polygon(sitio["plaza"]).contains(out):
                    continue  # inner edge of the C platform, already walled from the plaza side
                else:
                    bottom = lv["natural"] - 0.20
                against = blocks.buffer(0.5).contains(edge)
                b.element("IfcWall", "Muro de contención", "Nivel 1",
                          b.extrusion(edge.buffer(0.15, cap_style=2), bottom, top - bottom + (0 if against else 1.0)),
                          None, fuente, "RETAININGWALL")
    # Fence (vertical bars 2.2 m, posts every 2.5 m) on the lot boundary, open at the gate.
    gate = LineString(sitio["acceso"]).buffer(1.5, cap_style=2)  # the gate is drawn on the plaza edge, 0.6 m inside
    fence = LineString(sitio["cerca"] + [sitio["cerca"][0]]).difference(gate)
    for seg in getattr(fence, "geoms", [fence]):
        z = lv["plaza"] if Polygon(sitio["plaza"]).buffer(2.0).contains(seg.centroid) else lv["natural"]
        n = int(seg.length / 0.15)
        items = [b.f.createIfcExtrudedAreaSolid(
            b.f.createIfcRectangleProfileDef("AREA", None, b.f.createIfcAxis2Placement2D(
                b.f.createIfcCartesianPoint((float(q.x), float(q.y)))), 0.04 if i % 17 else 0.08, 0.04 if i % 17 else 0.08),
            b.f.createIfcAxis2Placement3D(b.f.createIfcCartesianPoint((0.0, 0.0, float(z)))),
            b.f.createIfcDirection((0.0, 0.0, 1.0)), 2.2)
            for i, q in enumerate(seg.interpolate(k / max(n, 1), normalized=True) for k in range(n + 1))]
        b.element("IfcRailing", "Cerramiento", "Nivel 1", b.f.createIfcShapeRepresentation(b.body, "Body", "SweptSolid", items),
                  None, fuente, "USERDEFINED")
    e = b.element("IfcSlab", "Vía de acceso", "Nivel 1", b.extrusion(box(*sitio["via_acceso"]), lv["via"], 0.20), None,
                  fuente, "USERDEFINED")
    e.ObjectType = "Vía de acceso"
    x0, y0, x1, y1 = sitio["garita"]
    b.element("IfcWall", "Garita", "Nivel 1", b.extrusion(box(x0, y0, x1, y1), lv["plaza"], 2.8), None, fuente, "SOLIDWALL")
    # Existing trees to keep (p. 16-18, 21) and the 2021 project plants that fall on the new plaza.
    for x, y in sitio["arboles"]:
        z = lv["plaza"] if plaza.contains(Point(x, y)) else lv["natural"]
        e = b.element("IfcGeographicElement", "Árbol existente (conservado)", "Nivel 1",
                      b.extrusion(Point(x, y).buffer(3.0, 12), z, 0.05), None, fuente, "USERDEFINED")
        e.ObjectType = "VEGETACION"
    for kind, cx, cy, diam in vegetation(sheet):
        if plaza.contains(Point(cx, cy)):
            e = b.element("IfcGeographicElement", kind, "Nivel 1", b.extrusion(Point(cx, cy).buffer(diam / 2, 12), lv["plaza"], 0.05),
                          None, {"Lamina": "A-111", "Capa": "ARBOLES/PAISAVEGSIMBOLOGIA", "EsSupuesto": False, "Supuesto": ""},
                          "USERDEFINED")
            e.ObjectType = "VEGETACION"


if __name__ == "__main__":
    build(Path(sys.argv[1]), json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else None)
