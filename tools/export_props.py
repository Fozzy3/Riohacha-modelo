"""Export the per-element data of bim/cip.ifc for Blender and the web viewer.

Usage: uv run --with ifcopenshell --with shapely python -I tools/export_props.py <out_dir> [<ifc> <sitio.json>]
(default bim/cip.ifc; the 2025 variant passes bim/cip_lote2025.ifc and datos/sitio_lote2025.json)
Writes:
  elementos.json        {GlobalId: {clase, nombre, material, bloque, nivel, items, fuente, espacio...}}
  presupuesto.json      budget items keyed by code (description, unit, quantity, unit/total value)
  especificaciones.json specifications keyed by item code
  huellas.json          ground-floor outline of each block (project m), for the walk-mode collisions
  ../cip.ifc            copy of the model for download from the viewer
  sitio.json            variant only: site rotation, levels, plaza and views for the viewer
"""
import json
import shutil
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue

sys.path.insert(0, str(Path(__file__).parent))
import plan2d  # noqa: E402

ROOT = Path(__file__).parent.parent


def space_geometry(sp):
    """Outline rings (project m, outer first) and floor height of a space extrusion, for the viewer's highlight."""
    import ifcopenshell.util.placement as up

    if not sp.Representation:
        return None  # upper floors: no plan sheets (S4)
    solid = sp.Representation.Representations[0].Items[0]
    area = solid.SweptArea
    curves = [area.OuterCurve] + list(getattr(area, "InnerCurves", None) or [])
    rings = [[[round(c, 3) for c in p.Coordinates[:2]] for p in cv.Points[:-1]] for cv in curves]
    z0 = up.get_local_placement(sp.ObjectPlacement)[2, 3] + solid.Position.Location.Coordinates[2]
    return {"anillos": rings, "z0": round(float(z0), 3), "alto": round(float(solid.Depth), 3)}


def main(out_dir, ifc="bim/cip.ifc", sitio=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    f = ifcopenshell.open(ROOT / ifc)
    data = {}
    for e in f.by_type("IfcProduct"):
        if e.is_a("IfcSpatialStructureElement") and not e.is_a("IfcSpace"):
            continue
        ps = ue.get_psets(e)
        mat = ue.get_material(e)
        container = ue.get_container(e) or ue.get_aggregate(e)
        rec = {
            "clase": e.is_a(), "nombre": e.Name or "", "tipo": ue.get_predefined_type(e) or "",
            "material": mat.Name if mat is not None and mat.is_a("IfcMaterial") else "",
            "bloque": ps.get("CIP_Fuente", {}).get("Bloque") or ps.get("CIP_Espacio", {}).get("Bloque", ""),
            "nivel": container.Name if container is not None else "",
        }
        fuente = ps.get("CIP_Fuente") or {}
        if fuente:
            rec["fuente"] = {k: v for k, v in fuente.items() if k in ("Lamina", "Capa", "EsSupuesto", "Supuesto")}
        if "CIP_Presupuesto" in ps:
            rec["items"] = [c.strip() for c in ps["CIP_Presupuesto"]["Items"].split(",")]
        if "CIP_Especificacion" in ps:
            rec["especificacion"] = ps["CIP_Especificacion"]["Item"]
        for name in ("CIP_Espacio", "CIP_Mobiliario", "CIP_Dotacion"):
            if name in ps:
                rec[name[4:].lower()] = {k: v for k, v in ps[name].items() if k != "id"}
        if e.is_a("IfcSpace"):
            rec["nombre_largo"] = e.LongName or ""
            geo = space_geometry(e)
            if geo:
                rec["geometria"] = geo
        data[e.GlobalId] = rec
    (out / "elementos.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    pres = json.load(open(ROOT / "datos/presupuesto.json"))
    items = {i["item"]: {k: i[k] for k in ("descripcion", "unidad", "cantidad", "vr_unitario", "vr_total", "capitulo")}
             for i in pres["items"]}
    (out / "presupuesto.json").write_text(json.dumps({"capitulos": pres["capitulos"], "items": items},
                                                     ensure_ascii=False, separators=(",", ":")))
    shutil.copy(ROOT / "datos/especificaciones.json", out / "especificaciones.json")
    supuestos = {}
    for line in (ROOT / "SUPUESTOS.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[0].startswith("S") and cells[0][1:].isdigit():
            supuestos[cells[0]] = {"tema": cells[1], "supuesto": cells[2], "criterio": cells[3], "estado": cells[4]}
    (out / "supuestos.json").write_text(json.dumps(supuestos, ensure_ascii=False, indent=1))
    shutil.copy(ROOT / "datos/bloques.json", out / "bloques.json")
    huellas = {k: [[round(x, 2), round(y, 2)] for x, y in fp.exterior.coords[:-1]] for k, fp in plan2d.FOOTPRINT.items()}
    (out / "huellas.json").write_text(json.dumps(huellas))
    shutil.copy(ROOT / ifc, out.parent / "cip.ifc")
    if sitio:
        shutil.copy(ROOT / sitio, out / "sitio.json")
    print(f"{len(data)} elementos -> {out}/elementos.json")


if __name__ == "__main__":
    main(*sys.argv[1:])
