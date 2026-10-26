"""Quick look at a GLB: neutral materials, sun, aerial camera, Eevee render.

Run: blender -b --factory-startup -P blender/preview_glb.py -- <in.glb> <out.png> [az_deg] [el_deg] [dist]
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
az = math.radians(float(argv[2]) if len(argv) > 2 else 215)
el = math.radians(float(argv[3]) if len(argv) > 3 else 35)
dist = float(argv[4]) if len(argv) > 4 else 120

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
lo = Vector((min(v[i] for o in objs for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
hi = Vector((max(v[i] for o in objs for v in (o.matrix_world @ Vector(c) for c in o.bound_box)) for i in range(3)))
centre = (lo + hi) / 2

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x, scene.render.resolution_y = 1600, 900
scene.view_settings.view_transform = "AgX"
world = bpy.data.worlds.new("w")
scene.world = world
world.color = (0.75, 0.82, 0.9)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
cam.location = centre + Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el))) * dist
cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.lens = 35
scene.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(40), 0, math.radians(30))
sun.data.energy = 4
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("PREVIEW", out, "bbox", tuple(round(v, 1) for v in lo), tuple(round(v, 1) for v in hi))
