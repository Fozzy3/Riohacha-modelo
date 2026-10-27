"""Compress the web assets in place: glTF geometry (meshopt) + textures (WebP), lightmaps and impostors to WebP.

Usage: python3 -I tools/optimize_web.py <web_dir> [state ...]
Needs npx (@gltf-transform/cli 4) and ImageMagick. Keeps node names, custom attributes (_EID, COLOR_0, TEXCOORD_1)
and the mesh structure the viewer relies on (no join/flatten/instancing/simplify).
"""
import json
import subprocess
import sys
from pathlib import Path

GLTF = ["npx", "-y", "@gltf-transform/cli@4.5.1"]
KEEP = ["--flatten", "false", "--join", "false", "--instance", "false", "--palette", "false", "--simplify", "false",
        "--prune-attributes", "false", "--compress", "meshopt", "--texture-compress", "webp", "--texture-size", "1024"]


def run(cmd):
    print("$", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True)


def main(web, states):
    web = Path(web)
    for glb in (web / "modelo.glb", web / "vegetacion/plantas.glb"):
        # skip files already optimized (re-encoding WebP textures loses quality each time)
        if glb.exists() and b"EXT_meshopt_compression" not in glb.read_bytes()[:200000]:
            out = glb.with_suffix(".opt.glb")
            run(GLTF + ["optimize", glb, out] + KEEP)
            if glb.name == "modelo.glb":  # 'optimize' leaves the louver light (_luz_*) float: a third of the file
                run(GLTF + ["quantize", out, out, "--pattern", "_luz*", "--quantize-generic", "16"])
                run(GLTF + ["meshopt", out, out, "--level", "medium"])
            out.replace(glb)
    for state in states:
        folder = web / "luz" / state
        manifest = json.loads((folder / "manifest.json").read_text())
        for entry in manifest["mapas"].values():
            png = folder / entry["archivo"]
            if png.suffix == ".png":
                webp = png.with_suffix(".webp")
                run(["magick", png, "-depth", "8", "-quality", "90", webp])
                png.unlink()
                entry["archivo"] = webp.name
        (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    for png in (web / "vegetacion").glob("impostor_*.png"):
        run(["magick", png, "-quality", "90", "-define", "webp:alpha-quality=100", png.with_suffix(".webp")])
        png.unlink()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or ["dia", "atardecer", "noche"])
