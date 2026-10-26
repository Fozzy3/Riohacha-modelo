"""Checks for the published web assets: run with  python3 -I tools/test_web_assets.py"""
import json
import struct
from pathlib import Path

WEB = Path(__file__).parent.parent / "web"

for web in (WEB, WEB / "lote2025"):
    glb = (web / "modelo.glb").read_bytes()
    gltf = json.loads(glb[20:20 + struct.unpack("<I", glb[12:16])[0]])
    # initial load budget of the plan (<= 25 MB): the model is most of it
    assert len(glb) <= 25 * 2**20, (web, len(glb) / 2**20)
    # louver light per state (_luz_*): 16-bit normalized, not float (float is a third of the file)
    luz = [gltf["accessors"][a] for m in gltf["meshes"] for p in m["primitives"]
           for k, a in p["attributes"].items() if k.startswith("_LUZ_")]
    assert luz and all(a["componentType"] == 5123 and a.get("normalized") for a in luz), (web, luz[0])
    # every light state is compressed and complete
    for state in ("dia", "atardecer", "noche"):
        manifest = json.loads((web / "luz" / state / "manifest.json").read_text())
        files = [e["archivo"] for e in manifest["mapas"].values()]
        assert files and all(f.endswith(".webp") and (web / "luz" / state / f).exists() for f in files), (web, state)
        assert (web / "luz" / state / "cielo.hdr").exists(), (web, state)
print("ok")
