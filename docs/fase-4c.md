# Fase 4c: AMPL_ZRA, ampliación de material a Centro

Revisión 3, sección 10, con el layout que definió Dave el 28-nov-2026:

| Decisión | Cómo quedó |
| --- | --- |
| Captura | Material, Centro nuevo, Almacén nuevo, Centro modelo, Almacén modelo. WebDM propone el Centro y el Almacén modelo; también el Planificador y el Grupo de compras del Centro nuevo. El CeBe es automático. |
| TXT para SAP | Siempre se llama **`Amp_Mat.txt`**, sin encabezados, separado por tabuladores, con 9 columnas (ver la sección 4). |
| Renglón ya ampliado | Si el material ya existe en el Centro nuevo, la celda **Centro nuevo** sale en rojo: "El material ya existe en MTTU." No se puede enviar hasta corregirla o quitar el renglón. |
| Validación | Igual que AMAT: VAL_MAT aprueba, devuelve o cancela varias a la vez; si la crea un validador, pasa directo a DM. |
| DM | Exporta las veces que quiera, excluye con motivo, y al **Finalizar** las partidas pasan a TERMINADA y su Centro nuevo se agrega al **catálogo de materiales** (es una nueva ubicación del mismo material). |

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git fetch origin
git checkout fase-4c
git pull
python manage.py migrate      # agrega codigo_sap a la ampliación
python manage.py test
python manage.py runserver
```

1. Entra como `validador`. En el menú, **Materiales → Ampliar a Centro** ya está activo.
2. Escribe un Código SAP que exista en el catálogo de materiales (por ejemplo uno importado en MTTU) y elige **MEIX** como Centro nuevo. Al salir de la celda aparecen la descripción y las propuestas: Centro modelo MTTU, sus almacenes, el planificador, el grupo de compras y el CeBe de MEIX.
3. **Enviar.** Como eres validador, la partida va directo a Datos Maestros.
4. Entra como `dm`. En **Pendientes → Datos Maestros** la partida dice "Ampliar 310001 · …" y tiene el botón **Exportar / finalizar**.
5. **Exportar Amp_Mat.txt**, ábrelo con el Bloc de notas: un renglón, 9 columnas.
6. **Finalizar.** Abre **Consulta → Catálogo de materiales**: el material ya sale en MTTU y en MEIX.
7. Prueba también enviar el mismo material a MTTU: la celda Centro nuevo sale en rojo con "El material ya existe en MTTU." y no se envía.

## 2. Dónde se guarda

No hubo tabla nueva. `DetalleAmpliacion` ya existía desde la fase 1. Solo se agregó el código que escribe el usuario:

```sql
ALTER TABLE "solicitudes_detalleampliacion" ADD COLUMN "codigo_sap" varchar(6) DEFAULT '' NOT NULL;
ALTER TABLE "solicitudes_detalleampliacion" ALTER COLUMN "codigo_sap" DROP DEFAULT;
```

¿Por qué guardar el texto si ya hay una llave `material`? Porque `codigo_sap` es lo que el usuario capturó, y `material` es el material del catálogo que le corresponde. Si mañana DM corrige el catálogo, la partida conserva lo que se pidió.

| Dato de la tabla | Dónde vive |
| --- | --- |
| Centro nuevo | `solicitudes_partida.centro_id`, igual que en AMAT. Así las bandejas y la visibilidad por Centro funcionan sin cambios. |
| Material, Centro modelo, almacenes, planificador, grupo de compras | `solicitudes_detalleampliacion` |
| CeBe | No se guarda: es siempre el del Centro nuevo (`catalogos_centro.centro_beneficio`). |

## 3. El código, archivo por archivo

`solicitudes/ampliacion.py` concentra las reglas, igual que `servicios.py` en AMAT:

- **`AmpliacionForm`**: un renglón. `clean()` revisa que:
  - el código exista en el catálogo de **materiales** (no en servicios);
  - el Centro modelo sea uno donde el material ya existe;
  - cada almacén, planificador y grupo de compras sea de **su** Centro (el almacén modelo, del Centro modelo; los demás, del Centro nuevo);
  - el Centro nuevo y el modelo no sean el mismo.
- **`completar()`**: llena con la propuesta lo que quedó vacío. Se usa al guardar **y** antes de exigir obligatorios: lo que WebDM propone no se le exige al usuario.
- **`validar_para_envio()`**: marca en Centro nuevo los renglones ya ampliados (`ya_ampliado()`).
- **`enviar()`**: guarda, asigna folio `AMPL_ZRA-2026-…` y los mete al flujo.
- **`faltantes()`**: lo que usa `flujo.aplicar` al **Aprobar** y **Reenviar**. Además de los obligatorios, vuelve a revisar si el material ya se amplió mientras la partida esperaba (por ejemplo, porque alguien importó el TXT de SAP).
- **`texto_txt()`** y **`finalizar()`**: lo de Datos Maestros.

`flujo.py` ganó una transición:

```python
"excluir": Transicion("DM", E.EN_DM, E.EXCLUIDA, Evento.Tipo.EXCLUSION, pide_motivo=True),
```

Con eso, excluir hereda todo lo de las demás acciones en bloque: `SELECT … FOR UPDATE`, motivo obligatorio, todas o ninguna, y un `Evento` por partida. Un candado extra impide excluir partidas de AMAT.

`static/js/ampliacion.js` es la versión AMPL de `captura.js`. Al salir de la celda Material llama a `/solicitudes/ampl/material/?codigo=…`, que responde en JSON la descripción y los Centros donde ya existe.

## 4. El TXT

```
Columna 1  Material
Columna 2  Material (el mismo)
Columna 3  Centro nuevo
Columna 4  Almacén nuevo
Columna 5  Centro modelo
Columna 6  Almacén modelo
Columna 7  Planificador (puede ir vacío si el Centro no tiene)
Columna 8  Grupo de compras
Columna 9  CeBe
```

Ejemplo de un renglón (los `→` son tabuladores):

```
693380→693380→MEIX→RC01→MTTU→RC01→P01→G01→CEBE-MEIX
```

Exportar **no cambia ningún estado**: es un `GET` que solo lee. Por eso DM lo puede repetir. Las partidas EXCLUIDAS ya no salen.

## 5. Finalizar

```python
MaterialCentro.objects.get_or_create(material=material, centro=p.centro, defaults={...})
```

`get_or_create` hace primero un `SELECT` y, solo si no encuentra el renglón, un `INSERT`:

```sql
SELECT ... FROM "catalogo_sap_materialcentro" WHERE material_id = 7 AND centro_id = 2 LIMIT 21;
INSERT INTO "catalogo_sap_materialcentro" (material_id, centro_id, grupo_compras, categoria_valoracion, almacen, cebe, agregado)
VALUES (7, 2, 'G01', 'CV01', 'RC01', 'CEBE-MEIX', now());
```

Si alguien importó ese Material + Centro desde SAP mientras tanto, no se duplica: la partida se termina igual. La **categoría de valoración** no se captura en AMPL; se copia del Centro modelo.

## 6. Ejercicios en `psql`

```sql
-- Las ampliaciones con su Centro nuevo y su Centro modelo
SELECT s.folio, p.numero, p.estado, a.codigo_sap, cn.codigo AS centro_nuevo, cm.codigo AS centro_modelo
FROM solicitudes_detalleampliacion a
JOIN solicitudes_partida p ON p.id = a.partida_id
JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
JOIN catalogos_centro cn ON cn.id = p.centro_id
LEFT JOIN catalogos_centro cm ON cm.id = a.centro_origen_id
ORDER BY s.folio, p.numero;

-- Después de Finalizar: en qué Centros está el material
SELECT m.codigo, c.codigo, mc.almacen, mc.grupo_compras, mc.cebe, mc.agregado
FROM catalogo_sap_materialcentro mc
JOIN catalogo_sap_materialsap m ON m.id = mc.material_id
JOIN catalogos_centro c ON c.id = mc.centro_id
WHERE m.codigo = '693380';

-- La historia de las exclusiones
SELECT fecha, tipo, motivo FROM solicitudes_evento WHERE tipo = 'EXCLUSION' ORDER BY fecha;
```

## 7. Pruebas

`solicitudes/tests/test_ampliacion.py` prueba lo siguiente:

- Las propuestas: Centro modelo, almacenes, planificador y grupo de compras.
- Un material que no existe, y un Centro modelo donde el material no está.
- Un almacén de otro Centro.
- Un renglón ya ampliado marca error en Centro nuevo al guardar, con Enter y al enviar; no se envía.
- Material y Centro nuevo repetidos en la misma solicitud.
- El validador manda directo a DM.
- El JSON del material.
- El flujo completo: aprobar, exportar `Amp_Mat.txt`, excluir con motivo, exportar otra vez sin la excluida, y finalizar (que agrega el Centro al catálogo).
- Excluir sin motivo.
- Aprobar revisa si ya se amplió mientras tanto.
- La bandeja y el detalle muestran la ampliación.
- Corregir y reenviar una partida devuelta, con su evento de cambio.

- Enter (Validar) revisa sin enviar, en AMAT y en AMPL.

En total pasan 156 pruebas (incluye `test_volumen.py`: 1,200 partidas en AMAT y en AMPL, y 2,001 que deben marcar error).

## 8. Enter y Guardar borrador validan; nadie envía sin querer (AMAT y AMPL)

Segundo pedido de Dave: **ya no hay botón Validar**. Se valida solo con **Enter**, al **Guardar borrador** y al **Enviar**. Los tres guardan primero el borrador y luego revisan todo como si fueran a enviar. Solo Enviar asigna folio. En el código, `accion == "guardar"` se trata igual que `"validar"`.

Mensajes:

- Todo bien: "Borrador guardado. Todo está correcto: ya puedes enviar."
- Con errores: "Borrador guardado, pero hay celdas por corregir antes de enviar (marcadas en rojo)."
- Un valor que no existe en los catálogos (por ejemplo, un material que no está): "Hay valores inválidos; no se guardó nada." Ese no se puede guardar, porque la base no acepta una llave a un catálogo que no existe.

Lo que sigue es cómo quedó la primera versión de este pedido. El botón visible ya se quitó; el oculto sigue.

Pedido de Dave: en una tabla de captura, **Enter** ya no envía la solicitud. Ahora valida.

¿Por qué Enter enviaba? En HTML, Enter dentro de un `<input>` "presiona" el **primer botón de envío** del formulario. En AMAT ese era "Eliminar borrador" o "Guardar borrador", y en AMPL "Guardar". La solución fue poner como primer botón uno invisible, `value="validar"` (clase `.wd-enter`). También hay un botón **Validar** visible.

Validar hace lo siguiente:

- Revisa todo como al enviar: obligatorios, valores contra catálogos y, en AMAT, imágenes y duplicados.
- Marca los errores en rojo.
- Guarda como **borrador**, para no perder lo capturado ni las imágenes elegidas.
- **No** asigna folio ni envía.

En AMPL, además, avisa qué renglones se omitirán por estar ya ampliados.

## 9. Capturas grandes: hasta 2,000 partidas

Dave intentó subir 1,194 partidas y Django respondió *"The number of GET/POST parameters exceeded settings.DATA_UPLOAD_MAX_NUMBER_FIELDS"*.

**¿Por qué?** Django, por seguridad, acepta como máximo **1,000 campos** por envío. Cada renglón manda un campo por columna (unos 16 en AMAT, 8 en AMPL), así que el tope real era de unas **60 partidas en AMAT y 120 en AMPL**.

**Lo que cambió** en `config/settings.py`:

```python
MAX_PARTIDAS = 2000                                  # tope por solicitud
DATA_UPLOAD_MAX_NUMBER_FIELDS = MAX_PARTIDAS * 25    # campos suficientes para 2,000 renglones
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024       # 20 MB de texto por envío
```

Y los formsets usan `max_num=absolute_max=MAX_PARTIDAS` con `validate_max=True`. Con más de 2,000 sale el mensaje *"Máximo 2000 partidas por solicitud. Divide la captura en varias solicitudes."* y no se guarda nada.

**Que no tarde.** Con 1,200 renglones la pantalla tardaba unos 30 segundos. Ahora tarda unos 7. Hubo dos causas, y su arreglo está en `solicitudes/rapido.py`:

1. Cada renglón consultaba sus catálogos (UMB, Almacén, Grupo de compras…) por su cuenta: más de 9,000 consultas iguales. Ahora cada catálogo se consulta **una vez** por tabla y todos los renglones comparten la lista (`compartir_catalogos`, `FormsetCompartido`). Igual con el almacén predeterminado: una consulta por Centro, no por renglón.
2. Django dibuja cada `<option>` con una plantilla. `SelectRapido` arma el `<select>` directo en Python.

Al abrir un borrador grande, la tabla se dibuja con unas 25 consultas, sin importar cuántas partidas tenga. Lo que sí crece por renglón son los `INSERT`: cada partida y su detalle se guardan.

## 10. DM atiende las ampliaciones desde su bandeja

Pedido de Dave: exportar no es por partida ni por folio, sino **todo lo seleccionado**. Las ampliaciones ya traen su código, así que no se captura nada: solo se marcan.

En **Pendientes → Datos Maestros**, cuando hay ampliaciones, aparecen tres botones que usan las casillas:

| Botón | Qué hace |
| --- | --- |
| **Exportar Amp_Mat.txt** | Un solo archivo con todas las partidas marcadas, aunque sean de varios folios. No cambia nada y se puede repetir. |
| **Excluir** | Pide el motivo de cada partida marcada (igual que Devolver). Ya no salen en el TXT. |
| **Finalizar ampliaciones seleccionadas** | Las pasa a TERMINADA y agrega su Centro nuevo al catálogo de materiales. Cada folio queda TERMINADA cuando ya no le queda nada pendiente. |

El botón de las altas AMAT cambió de nombre a **Terminar altas con el código capturado**, y solo sale si hay altas en la bandeja.

Si entre lo marcado hay algo que no es una ampliación en Datos Maestros (por ejemplo, un alta AMAT), no se hace nada y el mensaje dice qué quitar: todas o ninguna.

El código está en `ampliacion.seleccion_dm()` y en las vistas `exportar_ampl` y `finalizar_ampl`. La consulta que arma el TXT es una sola, para todos los folios:

```sql
SELECT ... FROM solicitudes_partida p
JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
JOIN solicitudes_detalleampliacion a ON a.partida_id = p.id
...
WHERE s.flujo = 'AMPL_ZRA' AND p.estado = 'EN_DM'
  AND p.centro_id IN (SELECT centro_id FROM ... centros del usuario)
  AND p.id IN (41, 42, 57)
ORDER BY s.folio, p.numero;
```

## 11. Lo que sigue

Modificaciones (MOD_ZRA y MOD_ZSA), alta de servicios (ASER_ZSA) y vencimientos de 15/30 días.
