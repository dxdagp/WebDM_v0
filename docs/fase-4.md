# Fase 4 (parte 1): imágenes y búsqueda de duplicados

Esta parte agrega a AMAT_ZRA dos reglas de la Revisión 3:

| Sección | Regla | Dónde vive |
| --- | --- | --- |
| 7.3 Imágenes | De 1 a 3 por partida. JPG, PNG o WebP de hasta 10 MB. Se guardan como WebP de máximo 1920 px y sin metadatos. | `solicitudes/imagenes.py` |
| 8 Duplicados | Se compara contra el Catálogo SAP solo la Descripción y el No. Parte. Un duplicado exacto bloquea; lo demás avisa. | `solicitudes/duplicados.py` |

Lo que queda de la fase 4 (AMPL_ZRA con TXT, modificaciones, servicios, importación SAP y vencimientos) va en las siguientes partes.

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git pull
pip install -r requirements.txt   # Pillow ya estaba desde la fase 1; esto no cambia nada si ya lo tienes
python manage.py migrate          # esta parte NO trae migraciones nuevas: la tabla de imágenes existe desde la fase 1
python manage.py runserver
```

Las imágenes se guardan en la carpeta de `DJANGO_MEDIA_ROOT` de tu `.env`. Si no la pusiste, van a `media\` dentro del proyecto. Ejemplo para Windows:

```
DJANGO_MEDIA_ROOT=C:\webdm-media
```

Para probar duplicados necesitas algo en el Catálogo SAP. Mientras llega la importación del TXT de SAP, crea uno desde el shell:

```powershell
python manage.py shell -c "from catalogo_sap.models import MaterialSAP; from usuarios.models import Usuario; MaterialSAP.objects.create(codigo='100777', descripcion='FILTRO DE AIRE', no_parte_original='FA-100', umb='PZA', tipo_material='ZRA', origen='IMPORT', creado_por=Usuario.objects.get(username='dm'))"
```

Recorrido sugerido (contraseña `demo-webdm-2026`):

1. `solicitante` abre **Crear materiales** y llena un renglón con descripción `Filtro aire`. Abajo de la tabla aparece al momento la coincidencia POSIBLE con el 100777 (88 %).
2. Pulsa **Enviar** sin imagen: no se envía, pero queda guardada como borrador y la celda **Imágenes** se pone roja.
3. En esa celda elige una o varias fotos (hasta 3) y pulsa **Enviar** otra vez. Se guardan y se envía en un solo paso, con el aviso amarillo de la coincidencia.
4. Abre la partida: en la ficha ves las miniaturas, el visor con lupa y puedes quitar o agregar imágenes mientras tu rol y el estado lo permitan.
6. Repite con descripción `Filtro de aire` y No. Parte `FA-100`: ahora es DUPLICADO y la celda Descripción se pone roja con el código 100777.

## 2. Por qué cambió "Guardar borrador"

Hasta la fase 3, guardar un borrador **borraba todas sus partidas y las volvía a crear** (`DELETE` y luego `INSERT`). Era lo más simple y no importaba, porque la partida no tenía nada colgado.

Las imágenes cuelgan de la partida con `on_delete=CASCADE`. Con el método viejo, cada "Guardar borrador" se habría llevado las fotos. Por eso `servicios._reemplazar_partidas` ahora identifica cada partida por su **número** (10, 20, 30…):

| En la tabla | En la base | SQL |
| --- | --- | --- |
| Número que ya existía | Se actualizan sus datos; conserva sus imágenes | `UPDATE` |
| Número nuevo | Se crea | `INSERT` |
| Número que ya no está | Se borra con sus imágenes | `DELETE` (y el archivo se borra al confirmar) |

Consecuencia práctica: si cambias el número de una partida en el borrador (de 10 a 15), para WebDM es otra partida y pierde sus imágenes. Lo normal es no renumerar.

## 3. Imágenes (`solicitudes/imagenes.py`)

### 3.1 La conversión, paso a paso

```python
img = Image.open(archivo)          # Pillow lee el encabezado del archivo
formato = img.format               # el formato REAL: "JPEG", "PNG", "WEBP"…
img.load()                         # decodifica todo; si está corrupta, falla aquí
img = ImageOps.exif_transpose(img) # endereza la foto del celular
img = img.convert("RGB")           # o "RGBA" si tiene transparencia
img.thumbnail((1920, 1920))        # el lado mayor queda en 1920 px, sin deformar
img.save(salida, format="WEBP", quality=85)   # sin exif=…: los metadatos no se copian
```

Tres detalles que vale la pena entender:

- **Se revisa el contenido, no la extensión.** Un `virus.exe` renombrado a `foto.jpg` no pasa: Pillow no lo reconoce como imagen.
- **`exif_transpose`.** El celular no gira los píxeles: guarda la foto "acostada" y anota en el EXIF "gírame 90°". Si quitáramos el EXIF sin girarla antes, la foto quedaría de lado.
- **Sin metadatos.** El EXIF puede traer modelo del teléfono, fecha y hasta la ubicación GPS. No se guarda.

Una foto de 3000 × 2000 px queda en 1920 × 1280. En la prueba del recorrido, un PNG de ~30 KB quedó en un WebP de 4.4 KB.

### 3.2 Quién puede subir o quitar

| Estado de la partida | Quién |
| --- | --- |
| BORRADOR, DEVUELTA_SOL | Su solicitante (SOL_MAT o VAL_MAT) |
| EN_VALIDACION | VAL_MAT de ese Centro |
| EN_DM, TERMINADA, CANCELADA | Nadie: quedan bloqueadas |

### 3.3 Todo o nada, también con archivos

`agregar` **convierte todas** las imágenes antes de guardar la primera. Si subes dos y la segunda está dañada, no se guarda ninguna.

`quitar` borra el renglón y deja el borrado del archivo para **después del COMMIT**:

```python
imagen.delete()
transaction.on_commit(lambda: archivo.storage.delete(archivo.name))
```

¿Por qué esperar? Si algo fallara después del `DELETE`, PostgreSQL haría `ROLLBACK` y el renglón volvería, pero el archivo ya no existiría si lo hubiéramos borrado antes. PostgreSQL puede deshacer, pero el disco no.

### 3.4 Visor, lupa y flechas (pedido de Dave)

En la ficha de la partida (`static/js/ficha.js`):

- **Clic en la miniatura**: la imagen se ve grande en el centro de la pantalla, ajustada a la ventana (máximo 85 % del ancho y del alto), no en su tamaño real.
- **Cerrar**: con el tache de arriba a la derecha, con un clic fuera de la imagen o con Esc.
- **Lupa**: al pasar el cursor sobre la imagen, un círculo de 220 px muestra esa zona 2.5 veces más grande. Es un `<div>` redondo cuyo fondo es la misma imagen, agrandada y recorrida según la posición del cursor.
- **Clic sobre la imagen ampliada**: se abre completa en otra pestaña.
- **Ícono de descarga** (a la izquierda del tache): guarda la imagen como `FOLIO-partida-10-imagen-1.webp`. Es la misma vista `ver_imagen` con `?descargar=1`, que responde con `Content-Disposition: attachment`.
- **Flechas ← →** junto al título: van a la partida anterior o siguiente **de la misma solicitud**, por número. Si cambiaste datos sin guardar, preguntan antes de salir.

El SQL de "siguiente" es tan simple como suena:

```sql
SELECT * FROM solicitudes_partida
WHERE solicitud_id = 7 AND numero > 20
ORDER BY numero ASC LIMIT 1;
```

### 3.5 Las imágenes no se publican en `/media/`

Lo típico en Django es que Nginx sirva `/media/` directo. Eso significa que **cualquiera con la liga** ve la foto. Aquí cada imagen pasa por la vista `ver_imagen`, que primero revisa `puede_ver` (el mismo permiso de la solicitud). Un usuario de otro Centro recibe 403.

Para producción (fase 5) se puede acelerar con `X-Accel-Redirect` de Nginx manteniendo esta revisión.

### 3.6 Mínimo una imagen

Se exige en tres momentos:

| Momento | Dónde |
| --- | --- |
| Enviar | `servicios.revisar_envio` marca la celda Imágenes en rojo |
| Reenviar y Aprobar | `flujo.faltantes` agrega "al menos 1 imagen" a la lista de faltantes |

## 4. Duplicados (`solicitudes/duplicados.py`)

### 4.1 Los cuatro casos

| Caso | Resultado | ¿Bloquea? |
| --- | --- | --- |
| Descripción **y** No. Parte exactos | DUPLICADO: muestra código, descripción, No. Parte y UMB | Sí |
| Solo No. Parte exacto | ADVERTENCIA | No |
| Solo Descripción exacta | ADVERTENCIA | No |
| Descripción parecida al 80 % o más | POSIBLE | No |

"Exacto" se mide **después de normalizar** con `texto_sap` (mayúsculas, sin acentos, espacios limpios). Así, `Filtró de aire` y `FILTRO DE AIRE` son iguales.

### 4.2 Cómo se mide "parecida": palabra por palabra

La primera versión comparaba **letra por letra** con `difflib.SequenceMatcher` y daba esto:

```python
>>> SequenceMatcher(None, "FILTRO DE AIRE", "FILTRO DE ACEITE").ratio()
0.866   # ¡87 %! Comparten "FILTRO DE A…E": muchas letras, pero es otra pieza
```

Dave lo detectó: aceite y aire son cosas totalmente distintas. Bajar el umbral (por ejemplo a 70 %) habría empeorado el problema, porque **más** cosas saldrían como parecidas. Subirlo a 90 % sí sacaría ese caso, pero también dejaría fuera parecidos reales como "FILTRO AIRE" (88 %). El problema no era el número, era **qué** se comparaba. Por eso ahora se compara por palabras:

1. Se quitan las palabras vacías (`DE`, `PARA`, `CON`, `EL`, `LA`…): "FILTRO DE AIRE" queda en `FILTRO`, `AIRE`.
2. Dos palabras cuentan como la misma si se parecen al 85 % o más letra por letra. Así se perdona un error de dedo (`AIRE`/`AIRRE` = 89 %), pero no una palabra distinta (`AIRE`/`ACEITE` = 60 %).
3. Parecido = 2 × palabras iguales ÷ total de palabras de los dos textos.

| Contra "FILTRO DE AIRE" | Antes (letras) | Ahora (palabras) | ¿Sale? |
| --- | --- | --- | --- |
| FILTRO AIRE | 88 % | 100 % | Sí |
| FILTRO DE AIRRE (error de dedo) | 97 % | 100 % | Sí |
| AIRE FILTRO (otro orden) | 48 % | 100 % | Sí |
| FILTRO DE AIRE MOTOR | 82 % | 80 % | Sí |
| FILTRO DE ACEITE | 87 % | 50 % | **No** |
| FILTRO HIDRAULICO | 65 % | 50 % | No |
| BALATA DELANTERA vs BALATA TRASERA | 73 % | 50 % | No |

El umbral se queda en 80 % (`UMBRAL` en `solicitudes/duplicados.py`), y la tolerancia por palabra en 85 % (`UMBRAL_PALABRA`).

### 4.3 El SQL: primero filtra PostgreSQL, después compara Python

Comparar contra **todo** el catálogo en Python sería lento con miles de materiales. Así que primero PostgreSQL trae solo los candidatos que comparten alguna palabra de 3 letras o más. Para `Filtro de aire` con No. Parte `FA-100`, Django genera (columnas recortadas):

```sql
SELECT "id", "codigo", "descripcion", "umb", "no_parte_original", ...
FROM "catalogo_sap_materialsap"
WHERE (   UPPER("descripcion"::text) LIKE UPPER('%FILTRO%')
       OR UPPER("descripcion"::text) LIKE UPPER('%AIRE%')
       OR UPPER("descripcion"::text) = UPPER('FILTRO DE AIRE')
       OR UPPER("no_parte_original"::text) = UPPER('FA-100'))
  AND NOT "es_servicio"
ORDER BY "codigo" ASC
LIMIT 2000;
```

- `descripcion__icontains="FILTRO"` se traduce a `UPPER(…) LIKE UPPER('%FILTRO%')`.
- La palabra `DE` no entra al filtro: es muy corta y traería medio catálogo.
- Los servicios (`es_servicio`) no cuentan como duplicado de un material.

Ese `LIKE '%…%'` no puede usar un índice normal (B-tree) porque empieza con `%`: PostgreSQL recorre toda la tabla. Con unos miles de materiales tarda milisegundos. Si el catálogo crece mucho, la alternativa es la extensión **`pg_trgm`** de PostgreSQL: parte el texto en trigramas ("FIL", "ILT", "LTR"…), permite un índice GIN para `LIKE '%…%'` y hasta calcula la similitud dentro de PostgreSQL con `similarity(a, b)`. Lo dejamos para cuando haya datos reales que lo justifiquen.

### 4.4 Dónde aparece

| Momento | Qué hace |
| --- | --- |
| Mientras escribes Descripción o No. Parte | 400 ms después de la última tecla pregunta a `/solicitudes/coincidencias/` y muestra el resultado abajo de la tabla. Solo informa. |
| Botón **Buscar coincidencias** | Revisa todos los renglones a la vez. Útil después de pegar desde Excel. |
| **Enviar** | Validación final obligatoria: el DUPLICADO marca la celda y no deja enviar; lo demás sale como aviso amarillo. |
| **Reenviar** y **Aprobar** | `flujo.aplicar` vuelve a revisar: si mientras tanto alguien dio de alta el mismo material, no deja avanzar. |
| Ficha de la partida | Tabla "Coincidencias en el Catálogo SAP". En una partida TERMINADA se omite su propio código. |

Esperar 400 ms después de la última tecla (en inglés, *debounce*) evita mandar una consulta por cada letra.

## 5. Ejercicios en `psql`

```sql
-- 1. ¿Cuántas imágenes tiene cada partida? (LEFT JOIN: también salen las que tienen 0)
SELECT p.id, p.numero, p.estado, COUNT(i.id) AS imagenes
FROM solicitudes_partida p
LEFT JOIN solicitudes_imagenpartida i ON i.partida_id = p.id
GROUP BY p.id ORDER BY p.id;

-- 2. Partidas en validación SIN imagen (no deberían existir después de esta fase)
SELECT p.id, s.folio, p.numero
FROM solicitudes_partida p JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
WHERE p.estado = 'EN_VALIDACION'
  AND NOT EXISTS (SELECT 1 FROM solicitudes_imagenpartida i WHERE i.partida_id = p.id);

-- 3. Intenta meter una cuarta imagen a mano: la CHECK constraint de la fase 1 lo impide
INSERT INTO solicitudes_imagenpartida (partida_id, orden, archivo, subida, subida_por_id)
VALUES (1, 4, 'x.webp', now(), 1);
-- ERROR: new row ... violates check constraint "imagen_orden_1_a_3"

-- 4. La misma búsqueda de duplicados, a mano
SELECT codigo, descripcion, no_parte_original
FROM catalogo_sap_materialsap
WHERE descripcion ILIKE '%FILTRO%' OR no_parte_original = 'FA-100';
```

## 6. Pruebas

```powershell
python manage.py test
```

92 pruebas. Las nuevas:

| Archivo | Qué prueba |
| --- | --- |
| `test_imagenes.py` | Conversión a WebP de 1920 px sin EXIF, orientación del celular, rechazo de no-imágenes, GIF y más de 10 MB. Quién puede subir según el estado. Máximo 3. Todo o nada. Quitar borra el archivo. Solo quien ve la solicitud ve la imagen. Sin imagen no se aprueba. |
| `test_duplicados.py` | Los cuatro casos, la normalización, que los servicios no cuentan, el JSON y que VAL_MAT no puede aprobar un duplicado. |
| `test_captura_amat.py` (`EnvioFase4Tests`) | Sin imagen no se envía; guardar el borrador conserva las imágenes; el duplicado bloquea y la advertencia no. |

Las pruebas guardan sus imágenes en una carpeta temporal que se borra al terminar (`config/test_runner.py`), así nunca ensucian tu `DJANGO_MEDIA_ROOT`.

## 7. Supuestos de esta parte

1. En la captura, las imágenes se eligen en la columna **Imágenes** del renglón y se guardan al pulsar Guardar o Enviar. Como el navegador no puede conservar archivos elegidos si la página regresa con error, **Enviar siempre guarda primero el borrador** con sus imágenes; si el envío no pasa, queda como borrador y no se pierde nada. Solo si hay valores inválidos (por ejemplo, un año con letras) no se guarda nada y hay que volver a elegirlas. En la corrección (DEVUELTA_SOL, EN_VALIDACION) se cambian desde la ficha.
2. Al renumerar una partida de un borrador, sus imágenes se pierden (para WebDM es otra partida).
3. El duplicado exacto también bloquea **Reenviar** y **Aprobar**, no solo el primer Enviar.
4. Subir o quitar imágenes en BORRADOR no deja historia. Desde EN_VALIDACION sí, como cambio del campo "imagenes".
5. No se comparan las partidas de una misma solicitud entre sí, solo contra el Catálogo SAP.
