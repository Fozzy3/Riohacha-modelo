"""Export light-weight vegetation for the web viewer from the photoreal scene.

Run: blender -b blender/cip.blend -P blender/export_vegetation.py -- <web_dir>
Writes <web_dir>/vegetacion/:
  plantas.glb      palms (full geometry) + one decimated mesh per species for the project plants
  impostor_*.png   front views of context species (transparent background) for crossed billboards
  instancias.json  {species: [[x, y, z, rot_z, scale], ...]} in project coordinates (X east, Y north, Z up)
"""
import json
import math
import sys
from pathlib import Path

import bpy

out = Path(sys.argv[sys.argv.index("--") + 1]) / "vegetacion"
out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
# One collection per plant variant. Leaves are alpha cards: aggressive decimation deletes them, so keep shrubs
# whole (~13k triangles) and only reduce the dense Searsia trees.
TARGET_TRIS = {c.name: (25000 if c.name.startswith("searsia") else 10 ** 9)
               for c in bpy.data.collections["Vegetacion_fuente"].children}

# 1. instance positions (context trees and project plants)
inst = {}
for ob in scene.collection.objects:
    if ob.instance_type == "COLLECTION" and ob.instance_collection:
        name = ob.instance_collection.name
        inst.setdefault(name, []).append([round(ob.location.x, 2), round(ob.location.y, 2), round(ob.location.z, 2),
                                          round(ob.rotation_euler.z, 3), round(ob.scale.x, 4)])
(out / "instancias.json").write_text(json.dumps(inst))
print("INSTANCIAS", {k: len(v) for k, v in inst.items()})

# 2. one decimated, joined mesh per species (kept at its library scale; instances carry the scale)
species = []
for name in TARGET_TRIS:
    col = bpy.data.collections[name]
    parts = [o for o in col.all_objects if o.type == "MESH"]
    bpy.ops.object.select_all(action="DESELECT")
    copies = []
    for o in parts:
        c = o.copy()
        c.data = o.data.copy()
        scene.collection.objects.link(c)
        c.matrix_world = o.matrix_world.copy()
        copies.append(c)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    bpy.ops.object.join()
    merged = bpy.context.view_layer.objects.active
    merged.name = f"especie_{name}"
    tris = sum(len(p.vertices) - 2 for p in merged.data.polygons)
    if tris > TARGET_TRIS[name]:
        mod = merged.modifiers.new("dec", "DECIMATE")
        mod.ratio = TARGET_TRIS[name] / tris
        bpy.ops.object.modifier_apply(modifier="dec")
    species.append(merged)

# 3. palms: convert trunks to mesh
palms = []
for ob in list(scene.collection.objects):
    if ob.name.startswith("Palmera"):
        if ob.type == "CURVE":
            bpy.ops.object.select_all(action="DESELECT")
            ob.select_set(True)
            bpy.context.view_layer.objects.active = ob
            bpy.ops.object.convert(target="MESH")
        palms.append(bpy.context.view_layer.objects.get(ob.name) or ob)

bpy.ops.object.select_all(action="DESELECT")
for o in species + palms:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(out / "plantas.glb"), use_selection=True, export_image_format="AUTO",  # leaves need alpha (JPEG drops it)
                          export_apply=True)

# 4. impostors of the context species: orthographic front view, sky light only, transparent background
for ob in scene.objects:
    ob.hide_render = True
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = 512
# Linear radiance scaled by 1/40 (no tone mapping): the viewer multiplies by 40 and tone-maps like the rest.
scene.view_settings.view_transform = "Standard"
scene.view_settings.look = "None"
scene.view_settings.exposure = -math.log2(40)
scene.cycles.samples = 32
cam = bpy.data.objects.new("cam_impostor", bpy.data.cameras.new("impostor"))
scene.collection.objects.link(cam)
cam.data.type = "ORTHO"
scene.camera = cam
meta = {}
for sp in species:
    sp.hide_render = False
    sp.location = (0, 0, 0)
    bpy.context.view_layer.update()
    xs = [(sp.matrix_world @ v.co) for v in sp.data.vertices]
    h = max(v.z for v in xs) - min(v.z for v in xs)
    w = max(max(abs(v.x) for v in xs), max(abs(v.y) for v in xs)) * 2
    size = max(h, w) * 1.04
    cam.data.ortho_scale = size
    cam.location = (0, -50, min(v.z for v in xs) + size / 2)
    cam.rotation_euler = (math.radians(90), 0, 0)
    scene.render.filepath = str(out / f"impostor_{sp.name[8:]}.png")
    bpy.ops.render.render(write_still=True)
    sp.hide_render = True
    # the square image covers `size` metres, centred horizontally, bottom at the plant base
    meta[sp.name[8:]] = {"lado": round(size, 3), "base": round(min(v.z for v in xs), 3)}
    print("IMPOSTOR", sp.name, round(size, 2), "m")
(out / "impostores.json").write_text(json.dumps(meta))
print("VEGETACION lista")
