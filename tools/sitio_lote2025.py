"""Site of the 2025 variant (approximate): the CIP on the 5,600 m² lot of the Informe de avance V.01 (DEARCA, 2025).

Usage: python3 -I tools/sitio_lote2025.py  -> datos/sitio_lote2025.json (project metres, X east / Y north of the
project, origin column A/1, like the IFC; SUPUESTOS S30-S31).

Georeference, fitted from the report images:
- p. 8 implantation plan: Origen Nacional grid every 76 m (159.5 px, 0.4765 m/px, north up); the Troncal del Caribe
  drawn on it runs at 129.4°, the same bearing as in OpenStreetMap, which fixes the east offset.
- p. 21 site plan (project north up, block A square): its fence matches the yellow 5,990 m² polygon of p. 8 with a
  40.1° clockwise rotation (residuals 2-4 m at true scale).
Levels (p. 13, 33): Troncal = reference; natural ground -3.90 m; plaza fill +0.40 m; block C platform -2.00 m.
Model level 0.00 = Troncal - 0.20 (plaza 0.20 = Troncal + 0.40).
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
S21, A_PX = 0.153, (507.5, 168)  # p. 21: metres per pixel (block A, 27.66 x 20.52 m) and A's NW corner in pixels


def project(x, y):
    """p. 21 pixel -> project metres (A's NW corner is (-1.12, 1.30))."""
    return round(-1.12 + (x - A_PX[0]) * S21, 2), round(1.30 - (y - A_PX[1]) * S21, 2)


sitio = {
    "nombre": "Lote 2025 (aproximado, informe de avance DEARCA)",
    "origen_EN": [5014079.01, 2830659.93],  # column A/1 in EPSG:9377
    "norte": 40.1,  # bearing of the project north, clockwise from true north (degrees)
    "niveles": {"via": -0.20, "natural": -4.10, "plaza": 0.20, "patio_c": -2.20},
    "desplazamiento": {"C": -2.40},  # block C floor at Troncal -2.00
    "semisotano": {"bloques": ["A", "B", "D"], "piso": -4.10},
    "cerca": [project(*p) for p in ((425, 90), (901.5, 90), (901.5, 512), (232, 512), (232, 490), (425, 260))],
    # plaza between C's stairs, A's south façade, D's west and south sides and the south fence
    "plaza": [(-26.7, -50.7), (-1.0, -22.4), (-1.12, -19.22), (23.91, -19.22), (23.91, -39.93), (33.1, -39.93), (33.1, -50.7)],
    "acceso": [project(*p) for p in ((693, 508), (735, 508))],  # gate on the south fence; the drive runs to the Troncal
    "garita": [27.5, -50.4, 30.5, -46.4],
    # drive from the gate to the edge of the Troncal (its axis runs at Y = -88 in this frame, OpenStreetMap)
    "via_acceso": [27.26, -82.5, 33.69, -50.72],
    "arboles": [project(*p) for p in (
        (320, 58), (392, 57), (315, 128), (388, 120), (262, 205), (241, 253), (220, 323), (192, 410),
        (468, 125), (548, 132), (835, 10), (835, 67), (895, 67), (889, 130), (878, 198),
        (866, 320), (1057, 330), (805, 390), (860, 385), (918, 450), (857, 440), (797, 450), (487, 400))],
    "vistas": {  # project coordinates: [camera, target, lens]
        "aerea_suroeste": [[-62, -98, 46], [12, -14, 6], 30],
        "plaza_andén": [[9.5, -47, 1.85], [11, -12, 9], 24],
        "acceso_sur": [[30.5, -64, 1.65], [16, -20, 6], 22],
        "laboratorios": [[-50, -6, 9.0], [-21, -33, -1.5], 26],  # from the north-west: the labs sit 2.40 m below the plaza
        "semisotano": [[22, 11, -2.3], [12, 0, -2.6], 22],
        "noreste": [[82, 38, 22], [32, -6, 4], 30],
    },
}
(ROOT / "datos/sitio_lote2025.json").write_text(json.dumps(sitio, ensure_ascii=False, indent=1))
print("datos/sitio_lote2025.json:", len(sitio["arboles"]), "árboles, cerca", sitio["cerca"])
