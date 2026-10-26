"""Light states of the photoreal scene, applied in memory before baking or rendering.

Used by bake.py, render_sky.py and render_stills.py: `estado.aplicar("noche")`; `aplicar("dia")` restores the
scene as saved. Sun from web/geo.js for 2026-12-15 at 15:00 (dia), 17:00 (atardecer) and 19:00 (noche).
Night: blue-hour sky and the interior lighting only. The luminaires in the budget are interior 4000 K fittings
(LENS linear and BALA downlights); no exterior lighting is drawn or budgeted, so none is modelled (SUPUESTOS S27).
"""
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

SOL = {"dia": (233.4, 31.3), "atardecer": (244.7, 5.9), "noche": (247.6, -20.0)}  # azimuth, altitude (deg)
CIELO_NOCHE = (0.0016, 0.0024, 0.0045)  # linear radiance of the blue-hour sky
LUZ_4000K = (1.0, 0.80, 0.62)
# Camera exposure (stops) per state, like an auto-exposing camera; bake.py stores it in the manifest for the viewer.
EXPOSICION = {"dia": -3.2, "atardecer": -2.4, "noche": 3.5}
TECHO = 0.35  # ceiling emission (W/m²): ~500 lx on the floors below, in the units of the day sky


def aplicar(state):
    world = bpy.context.scene.world.node_tree
    sky = next(n for n in world.nodes if n.type == "TEX_SKY")
    background = world.nodes["Background"].inputs["Color"]
    az, alt = SOL[state]
    norte = bpy.context.scene.get("norte", 0.0)  # 2025 variant: project north turned from true north
    sky.sun_rotation, sky.sun_elevation = math.radians(az - norte), math.radians(alt)
    bpy.context.scene.view_settings.exposure = EXPOSICION[state]
    glass_lets_shadow_rays_through()
    old = bpy.data.objects.get("Techos iluminados")
    if old:
        me = old.data
        bpy.data.objects.remove(old)
        bpy.data.meshes.remove(me)
    if state == "noche":
        for link in list(background.links):
            world.links.remove(link)
        background.default_value = (*CIELO_NOCHE, 1)
        ceilings()
    else:
        world.links.new(sky.outputs[0], background)


def glass_lets_shadow_rays_through():
    """Light from the sun or the interior reaches the other side of the glazing by direct sampling instead of
    refractive caustics (noisy in a bake). Idempotent."""
    nt = bpy.data.materials["Vidrio"].node_tree
    if "SOMBRA" in nt.nodes:
        return
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    glass = out.inputs["Surface"].links[0].from_node
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.name = "SOMBRA"
    nt.links.new(nt.nodes.new("ShaderNodeLightPath").outputs["Is Shadow Ray"], mix.inputs[0])
    nt.links.new(glass.outputs[0], mix.inputs[1])
    nt.links.new(nt.nodes.new("ShaderNodeBsdfTransparent").outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def ceilings():
    """Emissive copy of the underside of every upper slab and roof slab (IfcSlab in the IFC), 2 cm below it."""
    data = Path(bpy.context.scene.get("web", Path(__file__).resolve().parent.parent / "web")) / "data"
    guids = json.loads((data / "eid.json").read_text())
    elems = json.loads((data / "elementos.json").read_text())
    slabs = {i for i, g in enumerate(guids)  # building slabs only (the plaza and walkways are IfcSlab too)
             if elems.get(g, {}).get("clase") == "IfcSlab" and elems[g].get("bloque")
             and not elems[g]["nombre"].startswith("Placa de piso")}
    bm = bmesh.new()
    for ob in bpy.context.scene.collection.objects:
        if ob.type != "MESH" or "_eid" not in ob.data.attributes:
            continue
        eid = [0.0] * len(ob.data.vertices)
        ob.data.attributes["_eid"].data.foreach_get("value", eid)
        rot = ob.matrix_world.to_3x3()  # meshes keep the glTF Y-up axes; the object carries the rotation
        for f in ob.data.polygons:
            if (rot @ f.normal).normalized().z < -0.99 and all(round(eid[v]) in slabs for v in f.vertices):
                bm.faces.new([bm.verts.new(ob.matrix_world @ ob.data.vertices[v].co - Vector((0, 0, 0.02)))
                              for v in f.vertices])
    me = bpy.data.meshes.new("Techos iluminados")
    bm.to_mesh(me)
    bm.free()
    mat = bpy.data.materials.get("Luz interior") or bpy.data.materials.new("Luz interior")
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Emission Color"].default_value = (*LUZ_4000K, 1)
    bsdf.inputs["Emission Strength"].default_value = TECHO
    me.materials.append(mat)
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("Techos iluminados", me))
    print("TECHOS", len(me.polygons), "caras", round(sum(p.area for p in me.polygons)), "m²")
