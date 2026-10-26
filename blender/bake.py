"""Bake one light state of the photoreal scene for the web viewer.

Run: blender -b blender/cip.blend -P blender/bake.py -- <state> <out_dir> [samples]
  state     light state of estado.py (dia, atardecer, noche)
  out_dir   web/ folder: writes luz/<state>/*.png lightmaps, luz/<state>/manifest.json and modelo.glb with UV0
            (tiling, metres), UV1 'Lightmap', per-vertex light '_luz_<state>' of every baked state (louvers) and _eid.
Large surfaces get irradiance lightmaps (direct + indirect, no albedo, so the web multiplies them with the tiling
textures); thin repeated elements (louvers) get per-vertex irradiance. Glass and aluminium are not baked.
"""
import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estado  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
STATE, OUT = argv[0], Path(argv[1])
SAMPLES = int(argv[2]) if len(argv) > 2 else 128
ONLY = argv[3] if len(argv) > 3 else None  # pilot: bake only objects whose name contains this; no save/export
(OUT / "luz" / STATE).mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
estado.aplicar(STATE)
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.render.bake.use_pass_direct = True
scene.render.bake.use_pass_indirect = True
scene.render.bake.use_pass_color = False
scene.render.bake.margin = 6

NO_BAKE = ("Vidrio", "Aluminio negro", "Luz interior")
DENSITY = {"Terreno": 2.0, "Horizonte": 0.0, "Vías": 4.0, "Edificios vecinos": 4.0}  # px per metre; building: 20
# Context meshes: their Blender materials (satellite-driven earth/grass mix, no texture UVs) do not survive glTF,
# so they are baked with albedo included and shown as-is in the viewer.
WITH_COLOR = ("Terreno", "Vías", "Edificios vecinos")


def surface_area(ob):
    return sum(p.area for p in ob.data.polygons)


def web_meshes():
    """Meshes that go to the web model: building groups and site context. Vegetation (library collections,
    instances, palms) is handled separately in the viewer."""
    return [ob for ob in scene.collection.objects
            if ob.type == "MESH" and ob.name not in ("Horizonte", "Techos iluminados") and not ob.name.startswith("Palmera")]


def bake_targets():
    wanted = ONLY.split(",") if ONLY else None
    return [ob for ob in web_meshes() if not (ob.data.materials and ob.data.materials[0].name in NO_BAKE)
            and (wanted is None or any(w in ob.name for w in wanted))]


def slug(name):
    import re
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def ensure_lightmap_uv(ob):
    if "Lightmap" in ob.data.uv_layers:
        return
    uv = ob.data.uv_layers.new(name="Lightmap")
    ob.data.uv_layers.active = uv
    for layer in ob.data.uv_layers:
        layer.active_render = layer.name == "UVMap"
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004, area_weight=1.0, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def subdivide_long_edges(ob, step=0.5):
    """Louvers are 10 m tall boxes: add vertices every 0.5 m so per-vertex light can show shadows."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    long_edges = [e for e in bm.edges if e.calc_length() > step * 1.5]
    for e in long_edges:
        cuts = int(e.calc_length() / step)
        bmesh.ops.subdivide_edges(bm, edges=[e], cuts=cuts)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(ob.data)
    bm.free()


def set_bake_image(ob, img):
    for mat in ob.data.materials:
        nt = mat.node_tree
        node = nt.nodes.get("BAKE_TARGET") or nt.nodes.new("ShaderNodeTexImage")
        node.name = "BAKE_TARGET"
        node.image = img
        nt.nodes.active = node


def normalise(values, channels=4):
    """Scale irradiance into 0-1 (8/16-bit storage) by its 99.5th percentile; returns the factor for the viewer."""
    import numpy as np

    a = np.asarray(values, dtype=np.float32).reshape(-1, channels)
    lum = a[:, :3].max(axis=1)
    k = float(np.percentile(lum[lum > 0], 99.5)) if (lum > 0).any() else 1.0
    a[:, :3] = np.clip(a[:, :3] / k, 0, 1)
    return a.ravel(), k


def denoise(img_path):
    """OIDN denoise of a baked lightmap through the compositor of a scratch scene."""
    src = bpy.data.images.load(str(img_path))
    sc = bpy.data.scenes.new("denoise")
    sc.render.resolution_x, sc.render.resolution_y = src.size
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "16"
    sc.view_settings.view_transform = "Standard"
    tree = bpy.data.node_groups.new("dn", "CompositorNodeTree")
    sc.compositing_node_group = tree
    node_in = tree.nodes.new("CompositorNodeImage")
    node_in.image = src
    dn = tree.nodes.new("CompositorNodeDenoise")
    out = tree.nodes.new("NodeGroupOutput")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    tree.links.new(node_in.outputs[0], dn.inputs["Image"])
    tree.links.new(dn.outputs[0], out.inputs[0])
    sc.render.filepath = str(img_path)
    bpy.ops.render.render(write_still=True, scene=sc.name)
    bpy.data.scenes.remove(sc)


manifest_path = OUT / "luz" / STATE / "manifest.json"
manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"estado": STATE, "mapas": {}, "vertices": []}
t0 = time.time()
for ob in bake_targets():
    is_louver = ob.name.endswith("|cortasoles")
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    if is_louver:
        subdivide_long_edges(ob)  # no-op once done
        name = f"_luz_{STATE}"  # '_' prefix: exported as a custom glTF attribute, one per state
        attr = ob.data.color_attributes.get(name) or ob.data.color_attributes.new(name, "FLOAT_COLOR", "CORNER")
        ob.data.color_attributes.active_color = attr
        scene.render.bake.target = "VERTEX_COLORS"
        bpy.ops.object.bake(type="DIFFUSE")
        raw = [0.0] * (len(attr.data) * 4)
        attr.data.foreach_get("color", raw)
        scaled, k = normalise(raw)
        attr.data.foreach_set("color", scaled)
        manifest["vertices"] = [v for v in manifest["vertices"] if v["objeto"] != ob.name] + [{"objeto": ob.name, "escala": k}]
        print(f"BAKE vertices {ob.name} {time.time() - t0:.0f}s", flush=True)
        continue
    ensure_lightmap_uv(ob)
    density = DENSITY.get(ob.name, 20.0)
    side = 2 ** max(7, min(12, round(math.log2(math.sqrt(surface_area(ob)) * density))))
    img = bpy.data.images.new(f"lm_{STATE}_{len(manifest['mapas'])}", side, side, float_buffer=True)
    set_bake_image(ob, img)
    scene.render.bake.target = "IMAGE_TEXTURES"
    with_color = ob.name in WITH_COLOR
    scene.render.bake.use_pass_color = with_color
    bpy.ops.object.bake(type="DIFFUSE")
    scene.render.bake.use_pass_color = False
    scaled, k = normalise(img.pixels[:])
    img.pixels.foreach_set(scaled)
    fname = f"{slug(ob.name)}.png"
    path = OUT / "luz" / STATE / fname
    img.filepath_raw = str(path)
    img.file_format = "PNG"
    img.save()
    denoise(path)
    manifest["mapas"][ob.name] = {"archivo": fname, "escala": k, "lado": side, "con_color": with_color}
    print(f"BAKE {side}px {ob.name} {time.time() - t0:.0f}s", flush=True)

manifest["exposicion"] = estado.EXPOSICION[STATE]
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
if ONLY:
    print("PILOTO listo", f"{time.time() - t0:.0f}s")
    sys.exit(0)
estado.aplicar("dia")  # the saved scene stays in its day state
bpy.ops.object.select_all(action="DESELECT")
for ob in web_meshes():
    ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(OUT / "modelo.glb"), use_selection=True, export_attributes=True,
                          export_vertex_color="NONE", export_apply=True, export_image_format="JPEG")
bpy.ops.wm.save_mainfile()
print("BAKE listo", STATE, f"{time.time() - t0:.0f}s")
