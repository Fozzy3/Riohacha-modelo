"""Quality report of bim/cip.ifc: schema validation, IDS data requirements, model vs budget quantities.

Usage: uv run --with ifcopenshell --with ifctester --with shapely python -I tools/qa.py
Writes bim/cip.ids (data requirements) and QA.md (report).
"""
import json
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.shape as us
import ifcopenshell.validate
from ifctester import ids

sys.path.insert(0, str(Path(__file__).parent))
import plan2d  # noqa: E402
import build_ifc  # noqa: E402

ROOT = Path(__file__).parent.parent


def make_ids():
    spec_ids = ids.Ids(title="CIP Guajira - requisitos de información", author="internetinteligente@udistrital.edu.co",
                       description="Cada elemento debe declarar su fuente; cortasoles, losas y vegetación su ítem de presupuesto; "
                                   "espacios su programa.")

    def spec(name, entity, pset_name, prop):
        s = ids.Specification(name=name, ifcVersion=["IFC4"])
        s.applicability.append(ids.Entity(name=entity))
        s.requirements.append(ids.Property(propertySet=pset_name, baseName=prop, cardinality="required"))
        spec_ids.specifications.append(s)

    for entity in ("IFCWALL", "IFCSLAB", "IFCCOLUMN", "IFCPLATE", "IFCMEMBER", "IFCSHADINGDEVICE", "IFCROOF"):
        spec(f"Fuente de {entity}", entity, "CIP_Fuente", "Lamina")
    spec("Cortasoles con ítem de presupuesto", "IFCSHADINGDEVICE", "CIP_Presupuesto", "ItemPrincipal")
    spec("Columnas con ítem de presupuesto", "IFCCOLUMN", "CIP_Presupuesto", "ItemPrincipal")
    spec("Espacios con programa", "IFCSPACE", "CIP_Espacio", "Programa")
    spec_ids.to_xml(str(ROOT / "bim/cip.ids"))
    return spec_ids


def main():
    f = ifcopenshell.open(ROOT / "bim/cip.ifc")
    rows = []

    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log, express_rules=False)
    rows.append(("Esquema IFC4", "0 errores", f"{len(log.statements)} errores", "✓" if not log.statements else "✗"))

    spec_ids = make_ids()
    spec_ids.validate(f)
    for s in spec_ids.specifications:
        ok = s.status
        failed = sum(len(r.failures) for r in s.requirements)
        rows.append((f"IDS: {s.name}", "cumple", "cumple" if ok else f"{failed} fallas", "✓" if ok else "✗"))

    pres = {i["item"]: i for i in json.load(open(ROOT / "datos/presupuesto.json"))["items"]}

    def compare(name, model, budget_value, source, tol=0.05):
        d = (model - budget_value) / budget_value
        rows.append((name, f"{budget_value:,.2f} ({source})", f"{model:,.2f}", f"{d:+.1%} " + ("✓" if abs(d) <= tol else "⚠")))

    fp = plan2d.FOOTPRINT
    compare("Lote (m²)", build_ifc.LOT.area, pres["1.02"]["cantidad"], "memoria 1.02 limpieza")
    compare("Huella piso 1, 4 bloques (m²)", sum(p.area for p in fp.values()), 2034, "presupuesto, área piso 1", tol=0.06)
    compare("Losa laboratorios 6.80 (m²)", fp["C"].area, pres["4.06"]["cantidad"], "4.06")
    compare("Losa auditorio (m²)", fp["D"].area, pres["4.07"]["cantidad"], "4.07")
    def modeled_slab(name, block):  # the slab as built, not the block outline: they differ over A's void
        s = ifcopenshell.geom.settings()
        return sum(us.get_volume(ifcopenshell.geom.create_shape(s, e).geometry) / build_ifc.SLAB
                   for e in f.by_type("IfcSlab") if e.Name == name and ue.get_pset(e, "CIP_Fuente", "Bloque") == block)

    compare("Losa bloque A nivel 15.40 (m²)", modeled_slab("Entrepiso Nivel 5", "A"), pres["4.08"]["cantidad"], "4.08")
    compare("Losa bloque A nivel 19.20 (m²)", modeled_slab("Cubierta", "A"), pres["4.09"]["cantidad"], "4.09")

    louver = {}
    for e in f.by_type("IfcShadingDevice"):
        blk = ue.get_psets(e)["CIP_Fuente"]["Bloque"]
        louver[blk] = louver.get(blk, 0) + 0.30 * e.Representation.Representations[0].Items[0].Depth
    for blk, item in (("A", "6.02"), ("B", "6.03"), ("D", "6.01")):
        compare(f"Cortasoles bloque {blk} (m², módulo 0.30)", louver.get(blk, 0), pres[item]["cantidad"], item)
    # 6.04 in kg at 4.45 kg/ml (memoria p. 75: 24 x 7.21 m); the elevation A-108 draws 20 tubes (PREGUNTAS H8)
    tubes = [e for e in f.by_type("IfcMember") if e.Name == "Columna metálica inclinada"]
    compare("Columnas inclinadas fachada norte A (kg, 4.45 kg/ml)", len(tubes) * 7.21 * 4.45, pres["6.04"]["cantidad"], "6.04")

    def profile_area(el):
        area = el.Representation.Representations[0].Items[0].SweptArea
        poly = build_ifc.Polygon([p.Coordinates for p in area.OuterCurve.Points])
        for inner in getattr(area, "InnerCurves", None) or []:
            poly = poly.difference(build_ifc.Polygon([p.Coordinates for p in inner.Points]))
        return poly.area

    plaza = sum(profile_area(el) for el in f.by_type("IfcSlab") if el.Name == "Plaza en gramoquín")
    compare("Plaza en gramoquín (m²)", plaza, pres["24.06"]["cantidad"], "24.06")
    veg = {}
    for el in f.by_type("IfcGeographicElement"):
        veg[el.Name] = veg.get(el.Name, 0) + 1
    for name, item in (("Palmera grande", "26.05"), ("Planta mediana", "26.02"), ("Planta ornamental", "26.01")):
        compare(f"{name} (und)", veg.get(name, 0), pres[item]["cantidad"], item)

    lines = ["# Control de calidad del modelo BIM", "",
             "Generado por `tools/qa.py`. Tolerancia de cantidades: ±5 % (⚠ fuera de tolerancia; ver SUPUESTOS.md).", "",
             "| Control | Referencia | Modelo | Resultado |", "|---|---|---|---|"]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in rows]
    (ROOT / "QA.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
