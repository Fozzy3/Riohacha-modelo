"""F0 benchmark: Cycles CPU bake + render times on a test façade.

Run: blender -b --factory-startup -P blender/bench_bake.py -- <out_dir> [samples] [bake_px]
Prints seconds for: lightmap bake (irradiance, direct+indirect) and a 1280x720 still.
"""
import math
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
OUT = argv[0]
SAMPLES = int(argv[1]) if len(argv) > 1 else 128
BAKE_PX = int(argv[2]) if len(argv) > 2 else 2048

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = SAMPLES
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPENIMAGEDENOISE"
scene.render.threads_mode = "AUTO"


def material(name, color, rough, metal=0.0, transmission=0.0):
    m = bpy.data.materials.new(name)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Transmission Weight"].default_value = transmission
    return m


def box(name, size, loc, mat):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(mat)
    return o


stucco = material("stucco", (0.85, 0.83, 0.8), 0.8)
wood = material("wood", (0.55, 0.33, 0.17), 0.5)
glass = material("glass", (0.05, 0.07, 0.08), 0.05, metal=0.9)
ground = material("ground", (0.35, 0.33, 0.28), 0.95)

parts = [
    box("ground", (80, 80, 0.1), (0, 0, -0.05), ground),
    box("wall", (24, 0.3, 21), (0, 0, 10.5), stucco),
    box("glass", (23.4, 0.05, 20), (0, -0.2, 10.4), glass),
]
for i in range(78):  # 0.3 m spacing over ~23.4 m, like the main block louvers
    parts.append(box(f"slat{i}", (0.07, 0.22, 17), (-11.55 + i * 0.3, -0.75, 12.5), wood))

# One mesh for the bake target, like a merged façade in production.
bpy.ops.object.select_all(action="DESELECT")
for o in parts[1:]:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[1]
bpy.ops.object.join()
facade = bpy.context.object
facade.data.uv_layers.new(name="Lightmap")
facade.data.uv_layers.active = facade.data.uv_layers["Lightmap"]
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(island_margin=0.003)
bpy.ops.object.mode_set(mode="OBJECT")

# Physical sky + sun at Riohacha 10:00 (azimuth ~105°, altitude ~55°).
world = bpy.data.worlds.new("sky")
scene.world = world
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
sky.sky_type = "MULTIPLE_SCATTERING" if "MULTIPLE_SCATTERING" in [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items] else "NISHITA"
sky.sun_elevation = math.radians(55)
sky.sun_rotation = math.radians(105)
world.node_tree.links.new(sky.outputs[0], world.node_tree.nodes["Background"].inputs[0])
world.node_tree.nodes["Background"].inputs[1].default_value = 0.3
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(35), 0, math.radians(-105 + 180)))
bpy.context.object.data.energy = 4
bpy.context.object.data.angle = math.radians(0.53)

# Bake target image on every material of the façade.
img = bpy.data.images.new("lightmap", BAKE_PX, BAKE_PX, float_buffer=True)
for m in facade.data.materials:
    n = m.node_tree.nodes.new("ShaderNodeTexImage")
    n.image = img
    m.node_tree.nodes.active = n

bpy.ops.object.select_all(action="DESELECT")
facade.select_set(True)
bpy.context.view_layer.objects.active = facade
scene.cycles.bake_type = "DIFFUSE"
scene.render.bake.use_pass_direct = True
scene.render.bake.use_pass_indirect = True
scene.render.bake.use_pass_color = False
scene.render.bake.margin = 4
t = time.time()
bpy.ops.object.bake(type="DIFFUSE")
bake_s = time.time() - t
img.filepath_raw = f"{OUT}/bench_lightmap.exr"
img.file_format = "OPEN_EXR"
img.save()

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
cam.location = (-18, -38, 6)
cam.rotation_euler = (math.radians(82), 0, math.radians(-28))
scene.camera = cam
scene.render.resolution_x, scene.render.resolution_y = 1280, 720
scene.render.filepath = f"{OUT}/bench_render.png"
t = time.time()
bpy.ops.render.render(write_still=True)
render_s = time.time() - t
print(f"BENCH samples={SAMPLES} bake_px={BAKE_PX} bake_s={bake_s:.1f} render_s={render_s:.1f}")
