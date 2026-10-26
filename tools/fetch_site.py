"""Download site context into data/: terrain heights, OSM features, ground imagery.

Usage: python3 -I tools/fetch_site.py <out_dir> [--esri-preview preview.jpg]
Sources (credited in the viewer):
  - Terrain: AWS Terrain Tiles (terrarium), derived from SRTM and other open DEMs.
  - Map features: OpenStreetMap contributors via Overpass API (ODbL).
  - Imagery: Sentinel-2 cloudless 2016 by EOX (CC BY 4.0).
The Esri preview is only for checking building placement by eye; it is not shipped.
"""
import io
import json
import math
import sys
import urllib.parse
import urllib.request

from PIL import Image

LAT, LON = 11.5156959, -72.869435  # must match ORIGIN in geo.js
HALF = 600  # meters around the origin
UA = {"User-Agent": "cip-guajira-3d/1.0 (academic project)"}


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def bbox():
    dlat = HALF / 111195
    dlon = HALF / (111195 * math.cos(math.radians(LAT)))
    return LAT - dlat, LON - dlon, LAT + dlat, LON + dlon


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def mosaic(url_fmt, z, size, mode="RGB"):
    """Stitch tiles covering bbox() and resample to size x size (north up)."""
    s, w, n, e = bbox()
    x0, y0 = tile_xy(n, w, z)
    x1, y1 = tile_xy(s, e, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    canvas = Image.new(mode, ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            img = Image.open(io.BytesIO(get(url_fmt.format(z=z, x=tx, y=ty)))).convert(mode)
            canvas.paste(img.resize((256, 256)), ((tx - tx0) * 256, (ty - ty0) * 256))
    crop = ((x0 - tx0) * 256, (y0 - ty0) * 256, (x1 - tx0) * 256, (y1 - ty0) * 256)
    return canvas.crop(tuple(round(c) for c in crop)).resize((size, size), Image.BICUBIC)


def terrain(out):
    img = mosaic("https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", 15, 129)
    px = img.tobytes()
    heights = [px[i] * 256 + px[i + 1] + px[i + 2] / 256 - 32768 for i in range(0, len(px), 3)]
    base = min(heights)
    # ponytail: 129x129 grid at ~9 m spacing; the site is coastal plain, finer DEMs add nothing.
    json.dump({"size": 129, "half": HALF, "base": round(base, 2),
               "h": [round(h - base, 2) for h in heights]}, open(f"{out}/terrain.json", "w"))
    print(f"terrain: {min(heights):.1f}..{max(heights):.1f} m")


def osm(out):
    s, w, n, e = bbox()
    q = f"""[out:json][timeout:60];
(way["building"]({s},{w},{n},{e}); way["highway"]({s},{w},{n},{e});
 way["waterway"]({s},{w},{n},{e}); way["natural"="water"]({s},{w},{n},{e});
 node["natural"="tree"]({s},{w},{n},{e}););
out geom;"""
    body = urllib.parse.urlencode({"data": q}).encode()
    for mirror in ("https://overpass-api.de/api/interpreter",
                   "https://overpass.kumi.systems/api/interpreter",
                   "https://overpass.private.coffee/api/interpreter"):
        try:
            data = json.loads(get(mirror, body))
            break
        except OSError as err:  # public mirrors are often overloaded
            print("overpass mirror failed:", mirror, err)
    else:
        raise SystemExit("all Overpass mirrors failed")
    feats = []
    for el in data["elements"]:
        t = el.get("tags", {})
        if el["type"] == "node":
            feats.append({"kind": "tree", "pts": [[el["lat"], el["lon"]]]})
            continue
        kind = ("building" if "building" in t else "road" if "highway" in t
                else "water")
        feats.append({"kind": kind, "tag": t.get("highway") or t.get("building") or "",
                      "levels": t.get("building:levels"),
                      "pts": [[p["lat"], p["lon"]] for p in el["geometry"]]})
    json.dump(feats, open(f"{out}/osm.json", "w"))
    print("osm:", {k: sum(f["kind"] == k for f in feats) for k in ("building", "road", "water", "tree")})


def imagery(out):
    img = mosaic("https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg", 16, 2048)
    img.save(f"{out}/ground.jpg", quality=85)
    print("imagery: ground.jpg 2048x2048")


TEXTURES = ["grass_concrete_pavement", "concrete_pavement", "leafy_grass", "dry_ground_01",
            "fine_grained_wood", "plastered_wall", "palm_tree_bark", "asphalt_02"]


def textures(out):
    """CC0 PBR textures from Poly Haven: diffuse, OpenGL normal, AO/rough/metal (1k jpg)."""
    import os
    os.makedirs(f"{out}/tex", exist_ok=True)
    for name in TEXTURES:
        files = json.loads(get(f"https://api.polyhaven.com/files/{name}"))
        for key, suffix in (("Diffuse", "diff"), ("nor_gl", "nor"), ("arm", "arm")):
            url = files[key]["1k"]["jpg"]["url"]
            open(f"{out}/tex/{name}_{suffix}.jpg", "wb").write(get(url))
    print("textures:", len(TEXTURES))


VEGETATION = ["searsia_lucida", "searsia_burchellii", "shrub_02", "shrub_04"]  # CC0 dry-forest trees and shrubs


def vegetation(out):
    """Poly Haven CC0 glTF models (1k textures) for Blender renders and bakes; not shipped to the web."""
    import os
    for name in VEGETATION:
        files = json.loads(get(f"https://api.polyhaven.com/files/{name}"))
        entry = files["gltf"]["1k"]["gltf"]
        base = f"{out}/vegetacion/{name}"
        os.makedirs(base, exist_ok=True)
        gltf = json.loads(get(entry["url"]))
        for rel, inc in entry.get("include", {}).items():
            os.makedirs(os.path.dirname(f"{base}/{rel}"), exist_ok=True)
            open(f"{base}/{rel}", "wb").write(get(inc["url"]))
        # The glTF ships a JPEG diffuse (no alpha): merge the separate Alpha map into an RGBA PNG for the leaf cards.
        diff = f"textures/{name}_diff_1k"
        alpha = Image.open(io.BytesIO(get(files["Alpha"]["1k"]["png"]["url"]))).convert("L")
        rgba = Image.open(f"{base}/{diff}.jpg").convert("RGB")
        rgba.putalpha(alpha.resize(rgba.size))
        rgba.save(f"{base}/{diff}.png")
        for img in gltf["images"]:
            if img["uri"] == f"{diff}.jpg":
                img["uri"] = f"{diff}.png"
                img["mimeType"] = "image/png"
        open(f"{base}/{name}.gltf", "w").write(json.dumps(gltf))
        print("vegetacion:", name)


def esri_preview(path):
    url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
    mosaic(url, 18, 2048).save(path, quality=85)
    print("esri preview:", path)


if __name__ == "__main__":
    out = sys.argv[1]
    if "--esri-preview" in sys.argv:
        esri_preview(sys.argv[sys.argv.index("--esri-preview") + 1])
    elif "--textures" in sys.argv:
        textures(out)
    elif "--vegetacion" in sys.argv:
        vegetation(out)
    else:
        terrain(out)
        osm(out)
        imagery(out)
