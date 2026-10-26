"""Find Blender's sky sun_rotation convention: shadow of a pole lit only by the Nishita sky sun disc.

Run: blender -b --factory-startup -P blender/test_sky_axis.py -- <out.png>
Prints the shadow tip direction; the sun is opposite to it.
"""
import math
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.samples = 16
sc.render.resolution_x = sc.render.resolution_y = 256
bpy.ops.mesh.primitive_plane_add(size=20)
bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=4, location=(0, 0, 2))
w = bpy.data.worlds.new("w")
sc.world = w
sky = w.node_tree.nodes.new("ShaderNodeTexSky")
types = [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items]
sky.sky_type = "MULTIPLE_SCATTERING" if "MULTIPLE_SCATTERING" in types else "NISHITA"
sky.sun_elevation = math.radians(30)
sky.sun_rotation = 0.0
w.node_tree.links.new(sky.outputs[0], w.node_tree.nodes["Background"].inputs[0])
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
sc.collection.objects.link(cam)
cam.data.type = "ORTHO"
cam.data.ortho_scale = 20
cam.location = (0, 0, 30)
sc.camera = cam
sc.view_settings.view_transform = "Standard"
sc.view_settings.exposure = -5
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(out)
px = list(img.pixels)
n = img.size[0]
lum = sorted(px[0::4])
median = lum[len(lum) // 2]
dark = [(i % n, i // n) for i in range(n * n) if px[4 * i] < 0.6 * median]  # pixel rows start at the bottom (south)
# shadow pixels away from the pole centre
far = [(x - n / 2, y - n / 2) for x, y in dark if (x - n / 2) ** 2 + (y - n / 2) ** 2 > 100]
mx = sum(p[0] for p in far) / max(1, len(far))
my = sum(p[1] for p in far) / max(1, len(far))
print("SKY", sky.sky_type, "shadow direction (x east, y north):", round(mx, 1), round(my, 1),
      "=> sun azimuth (deg from north, clockwise):", round(math.degrees(math.atan2(-mx, -my)) % 360, 1))
