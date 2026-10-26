"""Render the sky of the current light state as an equirectangular HDR for the web viewer (background and
reflections), with the same units as the baked lightmaps.

Run: blender -b blender/cip.blend -P blender/render_sky.py -- <state> <out.hdr>
"""
import math
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estado  # noqa: E402

state, out = sys.argv[sys.argv.index("--") + 1:][:2]
estado.aplicar(state)
scene = bpy.context.scene
for ob in scene.objects:  # world only: the viewer draws the real geometry
    ob.hide_render = True
cam = bpy.data.objects.new("cam_cielo", bpy.data.cameras.new("cielo"))
scene.collection.objects.link(cam)
cam.data.type = "PANO"
cam.data.panorama_type = "EQUIRECTANGULAR"
cam.location = (12, -20, 2)
cam.rotation_euler = (math.radians(90), 0, math.radians(-90))  # looks north (+Y): matches three.js equirect mapping
scene.camera = cam
scene.render.resolution_x, scene.render.resolution_y = 2048, 1024
scene.cycles.samples = 16
scene.cycles.use_denoising = False
scene.render.image_settings.file_format = "HDR"
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0
scene.render.filepath = out
bpy.ops.render.render(write_still=True)
print("CIELO", out)
