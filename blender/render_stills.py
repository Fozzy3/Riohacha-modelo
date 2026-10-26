"""Render the approval stills of the photoreal scene with Cycles (CPU).

Run: blender -b blender/cip.blend -P blender/render_stills.py -- <state> <out_dir> <width> <samples> [view ...]
"""
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estado  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
state, out_dir, width, samples = argv[0], argv[1], int(argv[2]), int(argv[3])
estado.aplicar(state)
views = argv[4:] or [o.name[4:] for o in bpy.data.objects if o.name.startswith("cam_")]

scene = bpy.context.scene
scene.render.resolution_x = width
scene.render.resolution_y = width * 9 // 16
scene.cycles.samples = samples
scene.cycles.use_adaptive_sampling = True
scene.cycles.adaptive_threshold = 0.02
scene.cycles.max_bounces = 6
scene.cycles.transparent_max_bounces = 16
scene.render.image_settings.file_format = "PNG"
for view in views:
    scene.camera = bpy.data.objects[f"cam_{view}"]
    scene.render.filepath = f"{out_dir}/F3_{view}_{state}.png"
    t = time.time()
    bpy.ops.render.render(write_still=True)
    print(f"STILL {view} {time.time() - t:.0f}s")
