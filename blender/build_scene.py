"""Build the photoreal Blender scene of the CIP from the IFC export.

Run: blender -b --factory-startup -P blender/build_scene.py -- <cip.glb> <out.blend> <sun_az_deg> <sun_alt_deg>
                                                                  [<web_dir> <sitio.json>]
The 2025 variant passes web/lote2025 and datos/sitio_lote2025.json (another origin, a rotated project north,
natural ground 4 m below the Troncal; SUPUESTOS S31). sun_az_deg is always the true azimuth.
Inputs (relative to modelo-3d/): <web_dir>/data/elementos.json, data/tex, data/vegetacion, data/terrain.json, data/osm.json,
data/ground.jpg. Project frame: X east, Y north, Z up, origin = column A/1 (same as the IFC).
"""
import json
import math
import random
import sys
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

ROOT = Path(__file__).resolve().parent.parent
argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUT = argv[0], argv[1]
SUN_AZ, SUN_ALT = float(argv[2]), float(argv[3])
WEB = ROOT / (argv[4] if len(argv) > 4 else "web")
SITIO = json.load(open(ROOT / argv[5], encoding="utf-8")) if len(argv) > 5 else None
ORIGIN_ENU = (-100.35, 90.85)  # project origin in local ENU metres from the OSM node (build_ifc.py)
NORTE = 0.0  # bearing of the project north, degrees clockwise from true north
if SITIO:  # same ENU frame: move the origin by the EPSG:9377 difference and turn the project axes
    ORIGIN_ENU = (ORIGIN_ENU[0] + SITIO["origen_EN"][0] - 5014132.02, ORIGIN_ENU[1] + SITIO["origen_EN"][1] - 2830635.37)
    NORTE = SITIO["norte"]
_COS, _SIN = math.cos(math.radians(-NORTE)), math.sin(math.radians(-NORTE))


def project_to_enu(x, y):
    return ORIGIN_ENU[0] + _COS * x - _SIN * y, ORIGIN_ENU[1] + _SIN * x + _COS * y


def enu_to_project(e, n):
    e, n = e - ORIGIN_ENU[0], n - ORIGIN_ENU[1]
    return _COS * e + _SIN * n, -_SIN * e + _COS * n


def inside(poly, x, y):
    hit = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            hit = not hit
    return hit


def segment_distance(x, y, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)
rng = random.Random(7)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# ---------------------------------------------------------------- materials
def image(name, srgb):
    path = ROOT / "data/tex" / name
    img = bpy.data.images.load(str(path), check_existing=True)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    return img


def pbr(name, tex=None, scale=1.0, tint=(1, 1, 1), rough=None, metal=0.0, uv="UVMap"):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    if tex:
        coord = nt.nodes.new("ShaderNodeUVMap")
        coord.uv_map = uv
        mapping = nt.nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = (scale, scale, scale)
        nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
        diff = nt.nodes.new("ShaderNodeTexImage")
        diff.image = image(f"{tex}_diff.jpg", True)
        arm = nt.nodes.new("ShaderNodeTexImage")
        arm.image = image(f"{tex}_arm.jpg", False)
        nor = nt.nodes.new("ShaderNodeTexImage")
        nor.image = image(f"{tex}_nor.jpg", False)
        for n in (diff, arm, nor):
            nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        mix.inputs["B"].default_value = (*tint, 1)
        nt.links.new(diff.outputs["Color"], mix.inputs["A"])
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(arm.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.uv_map = uv
        nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    else:
        bsdf.inputs["Base Color"].default_value = (*tint, 1)
    if rough is not None and not tex:
        bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    return m


def glass():
    m = bpy.data.materials.new("Vidrio")
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.80, 0.88, 0.90, 1)
    b.inputs["Transmission Weight"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.02
    b.inputs["IOR"].default_value = 1.52
    return m


MAT = {
    # WPC Ekowood (Informe de avance 2025, p. 25): flat albedos, the glTF exporter drops texture tints
    "WPC Ekowood H 200-100 Teka (cortasol)": pbr("Cortasol teka", None, tint=(0.07, 0.033, 0.016), rough=0.55),
    "WPC Ekowood 90-90 Arena (cortasol)": pbr("Cortasol arena", None, tint=(0.24, 0.17, 0.10), rough=0.55),
    "Panel compuesto de aluminio gris oscuro (marco)": pbr("Marco aluminio compuesto", None, tint=(0.035, 0.035, 0.04), rough=0.35),
    "Panel compuesto de aluminio gris claro (franja)": pbr("Franja aluminio compuesto", None, tint=(0.55, 0.55, 0.53), rough=0.35),
    "Vidrio templado fachada flotante": glass(),
    "Perfilería aluminio negro": pbr("Aluminio negro", None, tint=(0.025, 0.025, 0.028), rough=0.35, metal=1.0),
    "Mampostería estucada y pintada (blanco)": pbr("Estuco blanco", "plastered_wall", 0.4, (1.0, 0.99, 0.96)),
    "Concreto 3000 PSI": pbr("Concreto", "plastered_wall", 0.4, (0.72, 0.71, 0.69)),
    "Gramoquín (adoquín ecológico)": pbr("Gramoquín", "grass_concrete_pavement", 0.5),
    "Concreto andén": pbr("Andén", "concrete_pavement", 0.4),
    "Grama": pbr("Grama", "leafy_grass", 0.35, (0.85, 0.95, 0.75)),
    "Cubierta liviana marquesina (blanco)": pbr("Marquesina", "plastered_wall", 0.5, (1.0, 1.0, 0.98)),
}

MAT["Tubería metálica 4\" acabado tipo madera"] = MAT["WPC Ekowood H 200-100 Teka (cortasol)"]  # same wood-look tone

# ---------------------------------------------------------------- building
bpy.ops.import_scene.gltf(filepath=GLB)
elements = json.load(open(WEB / "data/elementos.json"))
guids = []
groups = {}
veg_points = []
for ob in list(bpy.data.objects):
    if ob.type != "MESH":
        continue
    info = elements.get(ob.name)
    if info is None:
        bpy.data.objects.remove(ob)
        continue
    if info["clase"] == "IfcGeographicElement" and not info["nombre"].startswith("Zona verde"):
        c = sum((ob.matrix_world @ v.co for v in ob.data.vertices), Vector()) / len(ob.data.vertices)
        size = max(ob.dimensions.x, ob.dimensions.y)
        veg_points.append((info["nombre"], c.x, c.y, size, c.z - 0.025))
        bpy.data.objects.remove(ob)
        continue
    mat = MAT.get(info["material"], MAT["Concreto 3000 PSI"])
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    # element id per vertex so merged meshes can still be picked in the web viewer
    eid = len(guids)
    guids.append(ob.name)
    attr = ob.data.attributes.new("_eid", "FLOAT", "POINT")
    attr.data.foreach_set("value", [float(eid)] * len(ob.data.vertices))
    key = (mat.name, info["bloque"] or "sitio", info["clase"] == "IfcShadingDevice")
    groups.setdefault(key, []).append(ob)

(WEB / "data/eid.json").write_text(json.dumps(guids))

merged = []
for (mname, block, louver), objs in groups.items():
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = f"{mname}|{block}" + ("|cortasoles" if louver else "")
    merged.append(ob)

# Tiling texture coordinates in metres (UV0): cube projection in world units.
bpy.ops.object.select_all(action="DESELECT")
for ob in merged:
    ob.select_set(True)
bpy.context.view_layer.objects.active = merged[0]
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.cube_project(cube_size=1.0, scale_to_bounds=False)
bpy.ops.object.mode_set(mode="OBJECT")
for ob in merged:
    if ob.data.uv_layers:
        ob.data.uv_layers[0].name = "UVMap"

# ---------------------------------------------------------------- site context
terrain = json.load(open(ROOT / "data/terrain.json"))
# SRTM is a surface model: canopies show up as mounds. Box-blur it (3 passes of radius 2 ≈ 50 m) to keep only
# the landform.
_size = terrain["size"]
_h = terrain["h"]
for _ in range(3):
    blurred = []
    for r in range(_size):
        for c in range(_size):
            acc = n = 0
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < _size and 0 <= cc < _size:
                        acc += _h[rr * _size + cc]
                        n += 1
            blurred.append(acc / n)
    _h = blurred
terrain["h"] = _h

img = bpy.data.images.load(str(ROOT / "data/ground.jpg"))
W, H = img.size
px = img.pixels[:]
half = terrain["half"]


def green(x, y):
    """Vegetation index 0-1 from the Sentinel-2 mosaic at project coordinates."""
    e, n = project_to_enu(x, y)
    i = int((e + half) / (2 * half) * (W - 1))
    j = int((n + half) / (2 * half) * (H - 1))  # pixels start at the bottom row (south)
    if not (0 <= i < W and 0 <= j < H):
        return 0.4
    k = 4 * (j * W + i)
    r, g, b = px[k], px[k + 1], px[k + 2]
    v = max(0.0, min(1.0, ((g - r) / (g + r + 1e-3) + (g - b) * 0.5 + 0.02) / 0.14))
    # The SENA campus around the CIP is lawn with trees (S26); the 10 m satellite pixels read it as bare.
    if math.hypot(x - 12, y + 20) < 130:
        v = max(v, 0.75)
    return v


def in_lot(x, y):
    if SITIO:
        x0, y0, x1, y1 = SITIO["via_acceso"]
        return inside(SITIO["cerca"], x, y) or (x0 - 3 < x < x1 + 3 and y0 - 6 < y < y1)
    return -48 < x < 61 and -62 < y < 17 and not (x < -10 and y > -2) and not (x > 45 and y < -18)


lat0, lon0 = 11.5156959, -72.869435


def to_project(lat, lon):
    e = (lon - lon0) * 111195 * math.cos(math.radians(lat0))
    n = (lat - lat0) * 111195
    return enu_to_project(e, n)


osm = json.load(open(ROOT / "data/osm.json"))
TRONCAL = [[to_project(lat, lon) for lat, lon in f["pts"]] for f in osm if f.get("tag") == "trunk"]


def embankment(x, y):
    """2025 variant: the Troncal and the access drive stand at road level on 1:1.5 embankments near the site."""
    x0, y0, x1, y1 = SITIO["via_acceso"]
    d = math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1))
    if math.hypot(x - 12, y + 20) < 300:
        d = min([d] + [segment_distance(x, y, a, b) - 6.0 for line in TRONCAL for a, b in zip(line, line[1:])])
    return SITIO["niveles"]["via"] - max(0.0, d) / 1.5


def dem(x, y):
    """Blurred DEM height (m) at project coordinates."""
    size, half, h = terrain["size"], terrain["half"], terrain["h"]
    e, n = project_to_enu(x, y)
    step = 2 * half / (size - 1)
    fc = min(size - 1.001, max(0.0, (e + half) / step))
    fr = min(size - 1.001, max(0.0, (half - n) / step))
    c, r = int(fc), int(fr)
    tx, ty = fc - c, fr - r
    at = lambda rr, cc: h[rr * size + cc]
    return (at(r, c) * (1 - tx) + at(r, c + 1) * tx) * (1 - ty) + (at(r + 1, c) * (1 - tx) + at(r + 1, c + 1) * tx) * ty


def terrain_height(x, y):
    """Real DEM around the site, flattened to 0 on the CIP platform (within 70 m), blended out to 140 m."""
    raw, site = dem(x, y), TERRAIN_SITE
    if SITIO:  # natural ground 3.90 m below the Troncal around the lot (no platform: the IFC carries the fills)
        return max(SITIO["niveles"]["natural"] + 0.4 * (raw - DEM_SITE), embankment(x, y))
    d = math.hypot(x - 12, y + 20)
    w = min(1.0, max(0.0, (d - 70) / 70))
    # SRTM noise on this coastal plain is of the order of the relief itself: keep 40 % (SUPUESTOS S24).
    return 0.4 * (raw - site) * w * w * (3 - 2 * w) - 0.02


TERRAIN_SITE = 0.0
DEM_SITE = dem(12, -20)
TERRAIN_SITE = terrain_height(12, -20) + 0.02 if not SITIO else 0.0  # blurred DEM height at the CIP becomes level 0

bpy.ops.mesh.primitive_grid_add(x_subdivisions=240, y_subdivisions=240, size=1100, location=(12, -20, 0))
ground = bpy.context.object
ground.name = "Terreno"
mask = ground.data.color_attributes.new("verde", "FLOAT_COLOR", "POINT")
for v in ground.data.vertices:
    x, y = ground.location.x + v.co.x, ground.location.y + v.co.y
    v.co.z = terrain_height(x, y)
    g = green(x, y)
    mask.data[v.index].color = (g, g, g, 1)


def tex_set(nt, tex, scale, tint):
    """Colour, roughness and normal-map colour outputs of a Poly Haven texture set (UV in metres)."""
    coord = nt.nodes.new("ShaderNodeUVMap")
    coord.uv_map = "UVMap"
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["UV"], mapping.inputs["Vector"])
    out = {}
    for suffix, srgb in (("diff", True), ("arm", False), ("nor", False)):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = image(f"{tex}_{suffix}.jpg", srgb)
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        out[suffix] = n
    tinted = nt.nodes.new("ShaderNodeMix")
    tinted.data_type = "RGBA"
    tinted.blend_type = "MULTIPLY"
    tinted.inputs["Factor"].default_value = 1.0
    tinted.inputs["B"].default_value = (*tint, 1)
    nt.links.new(out["diff"].outputs["Color"], tinted.inputs["A"])
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(out["arm"].outputs["Color"], sep.inputs["Color"])
    return tinted.outputs["Result"], sep.outputs["Green"], out["nor"].outputs["Color"]


def ground_material():
    """Dry earth where the satellite sees bare ground, grass where it sees vegetation."""
    m = bpy.data.materials.new("Suelo natural")
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    dry = tex_set(nt, "dry_ground_01", 0.12, (0.70, 0.58, 0.45))  # ochre earth of La Guajira
    grass = tex_set(nt, "leafy_grass", 0.25, (0.80, 0.82, 0.50))  # dry-season grass
    attr = nt.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "verde"
    noise = nt.nodes.new("ShaderNodeTexNoise")  # break the 4 m mask grid into natural patches
    noise.inputs["Scale"].default_value = 0.08
    mixf = nt.nodes.new("ShaderNodeMath")
    mixf.operation = "MULTIPLY_ADD"
    nt.links.new(noise.outputs["Fac"], mixf.inputs[0])
    mixf.inputs[1].default_value = 0.3
    nt.links.new(attr.outputs["Fac"], mixf.inputs[2])
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.30
    ramp.inputs["From Max"].default_value = 0.70
    nt.links.new(mixf.outputs["Value"], ramp.inputs["Value"])
    for i, (kind, target) in enumerate((("RGBA", "Base Color"), ("FLOAT", "Roughness"), ("RGBA", None))):
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = kind
        nt.links.new(ramp.outputs["Result"], mix.inputs["Factor"])
        a, b = (("A", "B") if kind == "RGBA" else ("A", "B"))
        nt.links.new(dry[i], mix.inputs[6 if kind == "RGBA" else 2])
        nt.links.new(grass[i], mix.inputs[7 if kind == "RGBA" else 3])
        result = mix.outputs[2 if kind == "RGBA" else 0]
        if target:
            nt.links.new(result, bsdf.inputs[target])
        else:
            nmap = nt.nodes.new("ShaderNodeNormalMap")
            nmap.uv_map = "UVMap"
            nt.links.new(result, nmap.inputs["Color"])
            nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return m


natural = ground_material()
ground.data.materials.append(natural)
bpy.ops.object.shade_smooth()
# Flat apron to the horizon so the sky never shows below the terrain edge. Below the lowest terrain point: above
# any of it, it shades the terrain black in the bake (2025 lot: hollows under natural - 0.6).
bpy.ops.mesh.primitive_circle_add(vertices=64, radius=6000, fill_type="NGON",
                                location=(12, -20, min(v.co.z for v in ground.data.vertices) - 0.5))
apron = bpy.context.object
apron.name = "Horizonte"
apron.data.materials.append(natural)

asphalt = pbr("Asfalto", "asphalt_02", 0.2, (0.8, 0.8, 0.8))
neighbour = pbr("Vecinos", "plastered_wall", 0.4, (0.92, 0.9, 0.86))


lot_box = (-50, -65, 62, 20) if not SITIO else (-48, -90, 64, 18)
bm = bmesh.new()
roads = bmesh.new()
for feat in osm:
    pts = [to_project(lat, lon) for lat, lon in feat["pts"]]
    if feat["kind"] == "building" and len(pts) > 3:
        cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        if lot_box[0] < cx < lot_box[2] and lot_box[1] < cy < lot_box[3]:
            continue
        levels = int(feat.get("levels") or (1 if rng.random() < 0.75 else 2))
        base = min(terrain_height(x, y) for x, y in pts)
        verts = [bm.verts.new((x, y, base)) for x, y in pts[:-1]]
        if len(verts) < 3:
            continue
        try:
            face = bm.faces.new(verts)
        except ValueError:
            continue
        ext = bmesh.ops.extrude_face_region(bm, geom=[face])
        top = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=top, vec=(0, 0, levels * 3.3))
    elif feat["kind"] == "road" and len(pts) > 1:
        width = {"primary": 9, "trunk": 9, "secondary": 8, "tertiary": 7}.get(feat.get("tag"), 4.5)
        prev = None
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            dx, dy = x1 - x0, y1 - y0
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln * width / 2, dx / ln * width / 2
            quad = [roads.verts.new((x0 + nx, y0 + ny, terrain_height(x0, y0) + 0.06)),
                    roads.verts.new((x0 - nx, y0 - ny, terrain_height(x0, y0) + 0.06)),
                    roads.verts.new((x1 - nx, y1 - ny, terrain_height(x1, y1) + 0.06)),
                    roads.verts.new((x1 + nx, y1 + ny, terrain_height(x1, y1) + 0.06))]
            roads.faces.new(quad)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])  # clockwise OSM outlines extrude inside-out (black in the bake)
for name, b, mat in (("Edificios vecinos", bm, neighbour), ("Vías", roads, asphalt)):
    me = bpy.data.meshes.new(name)
    b.to_mesh(me)
    b.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    me.materials.append(mat)

# ---------------------------------------------------------------- vegetation
veg_col = bpy.data.collections.new("Vegetacion_fuente")
scene.collection.children.link(veg_col)
veg_col.hide_render = True
library = {}
# Each Poly Haven file holds several variants side by side: one collection per variant, centred at the origin.
for name in ("searsia_lucida", "searsia_burchellii", "shrub_02"):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(ROOT / f"data/vegetacion/{name}/{name}.gltf"))
    for o in [o for o in bpy.data.objects if o not in before and o.type == "MESH"]:
        variant = o.name.replace("_LOD0", "")
        col = bpy.data.collections.new(variant)
        veg_col.children.link(col)
        for c in o.users_collection:
            c.objects.unlink(o)
        col.objects.link(o)
        o.location = (0, 0, o.location.z)
        library[variant] = (col, o.dimensions.z)
print("variantes", {k: round(v[1], 2) for k, v in library.items()})
TREES = ["searsia_burchellii_large", "searsia_burchellii_medium", "searsia_lucida_a", "searsia_lucida_b"]
SHRUBS = ["searsia_lucida_d", "searsia_lucida_e", "searsia_lucida_f", "shrub_02_a", "shrub_02_b", "shrub_02_c", "shrub_02_d"]
MEDIUM = ["searsia_lucida_a", "searsia_lucida_b", "searsia_lucida_c"]
ORNAMENTAL = ["shrub_02_a", "shrub_02_b", "shrub_02_c", "shrub_02_d"]


def place(name, x, y, height, rot=None, z=None):
    col, h0 = library[name]
    inst = bpy.data.objects.new(f"{name}_inst", None)
    inst.instance_type = "COLLECTION"
    inst.instance_collection = col
    s = height / h0
    inst.scale = (s, s, s)
    if z is None:
        z = terrain_height(x, y) if not (-50 < x < 62 and -62 < y < 18) or SITIO else 0.2
    inst.location = (x, y, z)
    inst.rotation_euler.z = rot if rot is not None else rng.random() * math.tau
    scene.collection.objects.link(inst)


bark = pbr("Corteza palma", "palm_tree_bark", 1.5, (0.62, 0.55, 0.47))
frond_mat = bpy.data.materials.new("Hoja palma")
bsdf = frond_mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.11, 0.22, 0.05, 1)
bsdf.inputs["Roughness"].default_value = 0.5
bsdf.inputs["Subsurface Weight"].default_value = 0.15  # leaves let some light through


def palm(x, y, height, z=0.2):
    """Coconut-type palm: curved trunk and 18 fronds, each a drooping rachis with ~70 leaflets (geometry, no alpha)."""
    curve = bpy.data.curves.new("tronco", "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.2
    curve.bevel_resolution = 4
    sp = curve.splines.new("BEZIER")
    sp.bezier_points.add(1)
    lean = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)).normalized() * height * 0.08
    for i, p in enumerate(sp.bezier_points):
        p.co = Vector((0, 0, 0)) if i == 0 else lean + Vector((0, 0, height))
        p.handle_left_type = p.handle_right_type = "AUTO"
    trunk = bpy.data.objects.new("Palmera tronco", curve)
    curve.materials.append(bark)
    trunk.location = (x, y, z)
    scene.collection.objects.link(trunk)
    me = bpy.data.meshes.new("frondas")
    b = bmesh.new()
    for k in range(18):
        ang = k / 18 * math.tau + rng.uniform(-0.12, 0.12)
        rise = 0.9 if k % 3 == 0 else 0.5 if k % 3 == 1 else 0.2  # young fronds up, old ones hanging
        length = rng.uniform(3.6, 4.4)
        d = Vector((math.cos(ang), math.sin(ang), 0))
        side = Vector((-math.sin(ang), math.cos(ang), 0))

        def rachis(t):
            return d * (t * length) + Vector((0, 0, rise * math.sin(t * math.pi * 0.6) * 1.6 - (t ** 2.2) * length * 0.55))

        for i in range(36):
            t = 0.08 + 0.92 * i / 35
            base = rachis(t)
            tangent = (rachis(min(1, t + 0.02)) - rachis(max(0, t - 0.02))).normalized()
            ll = (0.95 * math.sin(math.pi * min(1.0, t * 1.08)) ** 0.6 + 0.12) * rng.uniform(0.9, 1.1)
            for s in (-1, 1):
                # leaflet points forward and droops; a thin strip of two quads
                dirv = (tangent * 0.55 + side * s * 0.8 + Vector((0, 0, -0.35))).normalized()
                width = 0.045
                w = tangent.cross(dirv).normalized() * width
                tip = base + dirv * ll + Vector((0, 0, -0.12 * ll))
                mid = base + dirv * ll * 0.5
                v = [b.verts.new(p) for p in (base - w * 0.5, base + w * 0.5, mid + w, mid - w, tip)]
                b.faces.new((v[0], v[1], v[2], v[3]))
                b.faces.new((v[3], v[2], v[4]))
        # rachis itself
        prev = None
        for i in range(11):
            p = rachis(i / 10)
            ring = [b.verts.new(p + side * 0.025 * s) for s in (-1, 1)]
            if prev:
                b.faces.new((prev[0], prev[1], ring[1], ring[0]))
            prev = ring
    b.to_mesh(me)
    b.free()
    me.materials.append(frond_mat)
    crown = bpy.data.objects.new("Palmera frondas", me)
    crown.location = Vector((x, y, z)) + lean + Vector((0, 0, height))
    scene.collection.objects.link(crown)


for name, x, y, size, z in veg_points:
    if name == "Palmera grande":
        palm(x, y, rng.uniform(8.5, 10.5), z)
    elif name == "Planta mediana":
        place(rng.choice(MEDIUM), x, y, rng.uniform(2.8, 3.6), z=z)
    elif name.startswith("Árbol existente"):  # 2025 variant: trees kept on the new lot
        place(rng.choice(TREES[:2]), x, y, rng.uniform(5.5, 8.0), z=z)
    else:  # ornamental
        place(rng.choice(ORNAMENTAL), x, y, rng.uniform(1.0, 1.5), z=z)

# Dry forest around the site where the Sentinel-2 image is green, away from the lot, roads and buildings.
placed = shrubs = 0
for _ in range(400000):
    if placed >= 5000 and shrubs >= 9000:
        break
    x, y = rng.uniform(-430, 450), rng.uniform(-470, 430)
    if in_lot(x, y) or (not SITIO and -25 < x < 45 and -95 < y < -50):  # keep the lot and the south access clear
        continue
    g = green(x, y)
    if placed < 5000 and rng.random() < g ** 1.3:
        place(rng.choice(TREES), x, y, rng.uniform(4, 8))
        placed += 1
    elif shrubs < 9000 and rng.random() < 0.45 + 0.4 * g:
        place(rng.choice(SHRUBS), x, y, rng.uniform(0.6, 1.8))
        shrubs += 1
print("arboles de contexto", placed, "arbustos", shrubs)

# ---------------------------------------------------------------- sky and sun
world = bpy.data.worlds.new("Cielo")
scene.world = world
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
types = [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items]
sky.sky_type = "MULTIPLE_SCATTERING" if "MULTIPLE_SCATTERING" in types else "NISHITA"
sky.sun_elevation = math.radians(SUN_ALT)
sky.sun_rotation = math.radians(SUN_AZ - NORTE)  # azimuth clockwise from project north (test_sky_axis.py)
scene["norte"] = NORTE  # estado.py turns the sun of every light state the same way
scene["web"] = str(WEB)
sky.altitude = 10
sky.air_density = 1.2
sky.aerosol_density = 1.6  # coastal haze (Blender 5.x name for dust density)
world.node_tree.links.new(sky.outputs[0], world.node_tree.nodes["Background"].inputs[0])

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPENIMAGEDENOISE"
scene.view_settings.view_transform = "AgX"
scene.view_settings.look = "AgX - Base Contrast"
scene.view_settings.exposure = -3.2

# ---------------------------------------------------------------- cameras
VIEWS = SITIO["vistas"] if SITIO else {
    "aerea_suroeste": ((-62, -98, 46), (12, -14, 6), 30),
    "plaza_andén": ((9.5, -47, 1.65), (11, -12, 9), 24),
    "acceso_sur": ((11.5, -68, 1.65), (12, -24, 7), 22),
    "laboratorios": ((8, -36, 1.65), (-20, -30, 3.5), 24),
    "noreste": ((82, 38, 22), (32, -6, 6), 30),
}
for name, (loc, target, lens) in VIEWS.items():
    cam = bpy.data.objects.new(f"cam_{name}", bpy.data.cameras.new(name))
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_end = 3000
    cam.location = loc
    cam.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
scene.camera = bpy.data.objects["cam_aerea_suroeste"]

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("ESCENA", OUT, "objetos", len(bpy.data.objects), "grupos", len(merged))
