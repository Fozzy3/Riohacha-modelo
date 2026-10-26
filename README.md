# Riohacha-modelo

Modelo 3D fotorrealista del Centro de Innovación y Productividad (CIP) Guajira, Riohacha (BPIN 2022000100057).
Flujo: planos PDF → IFC4 → luz horneada en Blender Cycles → visor web three.js (WebGPU, con WebGL2 de respaldo).

| Carpeta | Contenido |
|---|---|
| `web/` | Visor listo para publicar: sitio estático, sin build. Versión aprobada 2021 en `/`, variante Lote 2025 en `/?version=lote2025` |
| `bim/` | Modelos IFC4 georreferenciados (EPSG:9377) |
| `tools/`, `blender/` | Scripts del flujo: extracción de planos, IFC, escena, horneado, optimización web |
| `datos/`, `fuentes/` | Presupuesto, APU, especificaciones y vectores extraídos de los PDF del proyecto (`fuentes/README.md`) |
| `data/` | Entorno: terreno, OSM, texturas y vegetación (`tools/fetch_site.py`) |

Supuestos en `SUPUESTOS.md`, preguntas abiertas en `PREGUNTAS_DISENADOR.md`, control de calidad del modelo en `QA.md`.

## Ver en local

```
python3 -m http.server 8766 --directory web
```

Abrir http://127.0.0.1:8766.

## Publicar

- **GitHub Pages:** Settings → Pages → *Deploy from a branch*, rama `main`, carpeta `/`. Cada push a `main` se publica en
  https://fozzy3.github.io/Riohacha-modelo/; el `index.html` de la raíz abre el visor de `web/`.
- **Otro servidor:** servir `web/` como archivos estáticos. WebGPU exige HTTPS; sin HTTPS el visor usa WebGL2.

## Regenerar

Las escenas `.blend` no están en el repositorio. Se reconstruyen desde el IFC:

```
uv run --with ifcopenshell python -I tools/ifc2glb.py bim/cip.ifc blender/cip.glb
blender -b --factory-startup -P blender/build_scene.py -- blender/cip.glb blender/cip.blend <azimut_sol> <altura_sol>
blender -b blender/cip.blend -P blender/bake.py -- <estado> <carpeta_salida> [muestras]
python3 -I tools/optimize_web.py web
```

La variante 2025 usa `bim/cip_lote2025.ifc` y pasa `web/lote2025 datos/sitio_lote2025.json` a `build_scene.py`.
