# Preguntas para el diseñador (Gedco, Arq. Alvin Prieto) y hallazgos del presupuesto

## Preguntas al diseñador

1. **Planos faltantes.** ¿Pueden compartir las láminas A-101 a A-105 y A-110? Por la numeración serían las plantas por piso y la cubierta. Las capas de los PDF (`A-WALL`, `A-GLAZ-CURT`, `S-COLS`…) indican que existe un **modelo Revit**: ¿se puede compartir en RVT o IFC?
2. **Escala.** Todas las láminas dicen "ESC 1/100", pero se imprimieron a 1:125 (verificado con las cotas). ¿Es intencional?
3. **Levantamiento topográfico.** ¿Existen coordenadas del lote o de los ejes (MAGNA-SIRGAS / Origen Nacional)? La capa `COORDENADAS` no trae valores.
4. **Cortasoles.** ¿Material y acabado exactos ("pérgola metálica tipo madera"): perfil, sección, color o referencia comercial?
5. **Vidrio y perfilería.** ¿Tono y reflectividad del vidrio, y color de la perfilería (en los renders se ve negra)?
6. **Vegetación.** ¿Qué especies son las palmeras grandes, las plantas medianas y las ornamentales?
7. **Vacío sur del Bloque Principal.** El corte 2-2 (A-106) dibuja un vacío de altura completa entre el eje 3 y la escalera, cubierto por la losa de cubierta, con barandas de vidrio en el borde de los entrepisos. ¿El vidrio de fachada va en la línea sur del bloque (vacío interior) o en el borde de las losas (vacío abierto tras los cortasoles)? El modelo usa el borde de las losas (`SUPUESTOS.md` S33).
8. **Laboratorios.** ¿En qué recinto queda cada laboratorio? En A-111 solo dicen "Laboratorio" o "SALA n". La asignación provisional está en `SUPUESTOS.md` S22.
9. **Marquesinas del acceso sur.** Están a 35–40 m al sur del Bloque Principal, fuera del lote. ¿Las columnas en Y tienen dos o cuatro brazos? ¿Corresponden al ítem 6.04 ("columnas metálicas inclinadas, tubería 4", bloque A fachada")?
10. **Iluminación exterior.** Los planos y el presupuesto solo traen luminarias interiores (LENS y BALA de 4000 K). ¿Hay alumbrado de plaza, andenes o fachadas (postes, bolardos, reflectores)? Por ahora la vista nocturna solo muestra la luz interior (`SUPUESTOS.md` S27).

## Hallazgos en el presupuesto (para el equipo formulador)

| ID | Hallazgo | Evidencia |
|---|---|---|
| H1 | El total del capítulo 27 (filtro francés) no incluye el ítem 27.05. Total en la hoja: $2.927.651; suma de sus ítems: $3.871.294 (diferencia $943.643). | `Pto CIP Guajira 5.xlsx`, hoja 08, filas 618–623 |
| H2 | El precio unitario del presupuesto es el del APU multiplicado por un factor fijo según el capítulo: **×1,25** en los capítulos 6, 7, 8, 10 y 14 (69 ítems) y **×1,111** en los capítulos 4, 17 y 22 (38 ítems). Ningún documento explica el factor. | `datos/presupuesto.json` contra `datos/apu.json` |
| H3 | En los capítulos 5, 25 y 27 la numeración del APU no coincide con la del presupuesto (razones de precio entre ×0,002 y ×3,5, propias de ítems distintos con el mismo código). | Ítems 5.17–5.31, 25.01–25.03, 27.01–27.04 |
| H4 | El ítem 29.10 ("Rubro de seguridad cursos exámenes") está numerado como capítulo 29, pero pertenece al capítulo 28 (Seguridad). | Hoja 08 |
| H5 | Positivo: las cantidades de los 305 ítems de la memoria de cantidades coinciden exactamente con el presupuesto. | `tools/parse_presupuesto.py` |
| H6 | El capítulo 16 (cubiertas) invierte las letras de los bloques: llama "bloque D" a los laboratorios y "bloque C" al auditorio, al revés que el resto del presupuesto y la memoria. | Ítems 16.08–16.13 |
| H7 | Las 4 marquesinas del acceso sur (cubierta y columnas en Y, capa A-GENM) no tienen un ítem de presupuesto identificable. | A-107, A-109 y presupuesto |
| H8 | Ítem 6.04 (columnas metálicas inclinadas, fachada norte del bloque A): la memoria cuenta 24 tubos de 7,21 m (770 kg), pero el alzado A-108 dibuja 20 (unos 642 kg). La diferencia es de 4 tubos, unos 128 kg y $2,8 millones. | Memoria p. 75 frente a A-108 (capa A-GENM). |
| H9 | El ítem 4.08 (losa del bloque A a nivel 15,40) mide 567,68 m², el contorno completo del bloque, pero el corte 2-2 dibuja en ese nivel el vacío sur (unos 163 m² sin losa). | A-106 corte 2-2 frente a la memoria, ítem 4.08 (`QA.md`) |
