# Fuentes extraídas (generadas, no editar a mano)

Regenerar desde `modelo-3d/`:
```
uv run --with pymupdf python -I tools/extract_vectors.py "../4. PRESUPUESTO" fuentes/vectores
uv run --with pymupdf python -I tools/index_memoria.py "../4. PRESUPUESTO/Memoria cantidades de obra.pdf" fuentes/memoria
uv run --with openpyxl python -I tools/parse_presupuesto.py "../4. PRESUPUESTO/Pto CIP Guajira 5.xlsx" fuentes/memoria/indice.json datos
python3 -I tools/parse_documentos.py "../6. OBSERVACIONES PREOCAD/SUBSANACIONES 21-OCT-2022/APUs CIP Guajira.pdf" "../4. PRESUPUESTO/Especificaciones tecnicas.pdf" datos
python3 -I tools/calibrate_scale.py fuentes/vectores/A-1*.json
```

## `vectores/A-1xx.json`
Todos los trazos y textos de cada lámina, agrupados por **capa de AutoCAD** y en puntos del PDF (y crece hacia abajo).
- Escala real: **1:125** → `pt_to_m = 0.0440972`. El rótulo dice 1:100; ver `SUPUESTOS.md` S1.
- Las capas siguen el estándar de Revit/AIA. Las útiles para el modelo:

| Capa | Contenido |
|---|---|
| `A-WALL` | Muros |
| `A-GLAZ-CURT` | Paños de vidrio de los muros cortina |
| `A-GLAZ-CWMG` | Montantes del muro cortina; en fachadas incluye los **cortasoles** |
| `A-DOOR`, `A-DOOR-FRAM`, `A-DOOR-GLAZ` | Puertas |
| `S-COLS`, `S-GRID`, `S-GRID-IDEN` | Columnas, ejes y burbujas de ejes |
| `S-STRS*` | Escaleras |
| `A-FLOR*` | Pisos, niveles y barandas |
| `A-GENM` | Modelos genéricos: marquesinas sobre columnas en Y |
| `I-FURN` | Mobiliario |
| `A-ANNO-DIMS`, `G-ANNO-DIMS` | Cotas (sirven para calibrar) |
| `PAISAVEGSIMBOLOGIA`, `ARBOLES` | Vegetación |
| `C-TOPO` | Terreno en cortes y fachadas |
| `SENA *`, `LOTE_*` | Edificaciones existentes del SENA y lote |

## `memoria/indice.json` + `memoria/img/`
305 ítems de la memoria de cantidades, cada uno con descripción, unidad, cantidad, página, líneas de cálculo y capturas de plano.
Plantas por piso de los bloques A y B (fuente de las plantas altas):
- **15.07**: cielo raso, imágenes 1 a 5 = pisos 1 a 5.
- **8.13**: estuco interior, imágenes 1 a 5 = pisos 1 a 5.
- **15.08** y **8.16**: variantes.
- **4.15**: acero de refuerzo, 29 imágenes de estructura.
