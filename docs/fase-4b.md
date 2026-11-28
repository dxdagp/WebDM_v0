# Fase 4b: Catálogo SAP e importación del TXT

Revisión 3, secciones 12 y 17.1, con las decisiones de Dave del 28-nov-2026:

| Decisión | Cómo quedó |
| --- | --- |
| Quién importa | ADMIN y DM |
| Materiales y servicios | **Catálogos separados e independientes**: se importan, consultan y (después) reportan por separado. Materiales son ZRA; servicios pueden ser ZRA o ZSA. El mismo código puede existir en los dos (material 500001 ACUMULADOR y servicio 500001 SERVICIO DE MUELLES). |
| Mismo código con descripciones distintas | No se importa **ninguno** de sus renglones |
| Columnas | Materiales llevan además grupo de compras, grupo de artículos, categoría de valoración y CeBe. Servicios **no llevan Centro**: no dependen de uno. |
| Normalización | Igual que la captura: mayúsculas, sin acentos, conserva la Ñ |
| Tamaño del archivo | Sin límite: se lee renglón por renglón |

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git fetch origin
git checkout fase-4b
git pull
python manage.py migrate      # catálogo en importaciones, código único por catálogo, datos por Centro
python manage.py datos_demo   # agrega ZSA, UMB SER y H, y el grupo de artículos SER01
python manage.py test
python manage.py runserver
```

1. Entra como `dm` (o un ADMIN). En el menú aparece **Administración → Importar catálogo SAP**.
2. Elige **Materiales** y sube `docs\ejemplos\catalogo-materiales-ejemplo.txt`. Resultado: 2 importados y 3 con error (un CeBe que no es el de MTTU, un código de 5 dígitos y un Centro que no existe). La tabla dice en qué línea está cada error y por qué.
3. Abre **Consulta → Catálogo de materiales**. El 310001 aparece en MTTU, con origen IMPORT y tu usuario.
4. Importa `catalogo-servicios-ejemplo.txt` eligiendo **Servicios**: entran 3. Uno de ellos es el 310001 SERVICIO DE MUELLES, el mismo código que la balata en materiales, porque los catálogos son independientes.
5. Importa `catalogo-materiales-otro-centro.txt` (Materiales). Resultado: 1 importado y 2 con error.
   - 310001 en MTTU ya existe en WebDM: no se carga.
   - 310001 en MEIX es nuevo: se agrega MEIX al **mismo** material (no se crea otro).
   - 310002 en MEIX trae grupo de artículos REF02, pero en WebDM es REF01: un código tiene un solo grupo de artículos.

### Cabeceras del TXT

**Materiales**, un renglón por material y Centro:

```
CODIGO_SAP	DESCRIPCION	CENTRO	TIPO_MATERIAL	UMB	GRUPO_COMPRAS	GRUPO_ARTICULOS	CATEGORIA_VALORACION	CEBE	NO_PARTE_ORIGINAL
```

Todas son obligatorias menos `NO_PARTE_ORIGINAL`.

**Servicios**, un renglón por servicio y sin Centro:

```
CODIGO_SAP	DESCRIPCION	TIPO_MATERIAL	UMB	GRUPO_ARTICULOS
```

Las columnas pueden venir en cualquier orden y las desconocidas se ignoran. En Excel se guarda con **Archivo → Guardar como → "Texto Unicode (UTF-8)"** o "Texto (delimitado por tabulaciones)".

### Dónde se guarda cada dato

| Dato | Tabla | Por qué |
| --- | --- | --- |
| Descripción, Tipo, UMB, No. Parte, Grupo de artículos | `catalogo_sap_materialsap` | Son del material, igual en todos los Centros. |
| Grupo de compras, Categoría de valoración, CeBe | `catalogo_sap_materialcentro` | En SAP dependen del Centro. |

Un código tiene **una** descripción y **un** grupo de artículos, en materiales y en servicios. Si el archivo trae distintos para el mismo código, no se carga ninguno de sus renglones. Si el código ya existe en WebDM (otro Centro), deben coincidir con los que ya tiene.

### Validación contra los catálogos de WebDM

Cada valor debe existir (y estar activo) en WebDM:

| Columna | Se busca en |
| --- | --- |
| CENTRO | Centros |
| TIPO_MATERIAL | Tipos de material |
| UMB | Unidades de medida |
| GRUPO_ARTICULOS | Grupos de artículos |
| CATEGORIA_VALORACION | Categorías de valoración, **del mismo tipo de material** |
| GRUPO_COMPRAS | Grupos de compras **de ese Centro** |
| CEBE | Debe ser igual al CeBe del Centro |

Si algo no existe, el mensaje dice todo lo que falta de una vez, por ejemplo `No existe en WebDM: UMB CAJA, Grupo de artículos GA9.`

## 2. Un catálogo por dentro, dos por fuera

Para Dave son dos catálogos distintos e independientes. En la base es **una sola tabla** (`catalogo_sap_materialsap`) con la columna `es_servicio`:

- Las pantallas filtran con `WHERE es_servicio = false` para materiales y `= true` para servicios.
- El código es único **dentro de cada catálogo**, no entre los dos. Por eso la restricción es sobre el par de columnas:

```sql
ALTER TABLE "catalogo_sap_materialsap" DROP CONSTRAINT "catalogo_sap_materialsap_codigo_key";
ALTER TABLE "catalogo_sap_materialsap"
  ADD CONSTRAINT "materialsap_codigo_unico_por_catalogo" UNIQUE ("codigo", "es_servicio");
```

  Así puede existir `('500001', false)`, el material ACUMULADOR, y `('500001', true)`, el servicio SERVICIO DE MUELLES, pero no dos materiales 500001.
- La búsqueda de duplicados de AMAT_ZRA, el Código SAP que captura DM y su corrección solo miran el catálogo de **materiales**.

Cada importación guarda a qué catálogo fue (`Importacion.catalogo`). La migración:

```sql
ALTER TABLE "catalogo_sap_importacion" ADD COLUMN "catalogo" varchar(10) DEFAULT 'MATERIALES' NOT NULL;
ALTER TABLE "catalogo_sap_importacion" ALTER COLUMN "catalogo" DROP DEFAULT;
```

¿Por qué el `DEFAULT` y luego el `DROP DEFAULT`? Las importaciones que ya existían necesitan un valor para cumplir `NOT NULL`. Django lo pone solo mientras agrega la columna y luego lo quita: el valor por omisión vive en Python, no en PostgreSQL.

## 3. La importación paso a paso (`catalogo_sap/importar.py`)

### 3.1 Leer sin cargar todo a memoria

```python
texto = io.TextIOWrapper(archivo, encoding="utf-8-sig", newline="")
lector = csv.reader(texto, delimiter="\t", quoting=csv.QUOTE_NONE)
```

- `TextIOWrapper` convierte bytes en texto **mientras se lee**. Un archivo de 500 MB nunca está completo en memoria.
- `utf-8-sig` acepta el BOM, tres bytes invisibles que el Bloc de notas pone al inicio de algunos archivos UTF-8.
- `QUOTE_NONE`: una comilla en la descripción (`TORNILLO 1/2"`) es texto, no un delimitador.
- Si un byte no es UTF-8 válido, Python lanza `UnicodeDecodeError` y **no se importa nada**.

### 3.2 Validar en dos pasos

**Paso 1, cada renglón solo:** campos vacíos, 6 dígitos, Centro existente, 40 caracteres, ZSA en materiales, valores contra los catálogos, y Material + Centro que ya existía (en servicios, el código).

No se hace ninguna consulta por renglón. La clase `Referencias` trae todo una vez al inicio:

```python
ref = Referencias.cargar(servicios)
# ref.existentes = {"310001": Existente(id=7, descripcion=..., grupo_articulos=..., centros={1, 2})}
# ref.umbs = {"PZA", "JGO", ...}; ref.grupos_compras = {(1, "G01"), (2, "G01"), ...}
```

```sql
SELECT "id", "codigo", "descripcion", "grupo_articulos" FROM "catalogo_sap_materialsap" WHERE NOT "es_servicio";
SELECT "material_id", "centro_id" FROM "catalogo_sap_materialcentro";
SELECT "codigo" FROM "catalogos_umb" WHERE "activo";
-- …y así cada catálogo
```

Preguntar `centro.pk in existente.centros` o `"PZA" in ref.umbs` en un `set` de Python tarda lo mismo con 10 que con 100,000 elementos.

**Paso 2, entre renglones:** se agrupan por código. Si las descripciones o los grupos de artículos difieren, todos los renglones de ese código son error. Si el código ya existía en otro Centro, la descripción y el grupo de artículos deben ser los mismos que tiene en WebDM. Si Código + Centro se repite en el archivo, el segundo es error.

**Al guardar**, un código que ya existía no crea otro `MaterialSAP`: su `MaterialCentro` nuevo apunta al material existente con `material_id=ref.existentes[codigo].id`.

### 3.3 Guardar en lotes

```python
MaterialSAP.objects.bulk_create(materiales.values(), batch_size=1000)
```

En vez de 50,000 `INSERT`, Django manda 50 de este estilo:

```sql
INSERT INTO "catalogo_sap_materialsap" ("codigo", "descripcion", ...)
VALUES ('310001', 'BALATA DELANTERA', ...), ('310002', 'FILTRO DE COMBUSTIBLE', ...), ...
RETURNING "id";
```

`RETURNING "id"` hace que PostgreSQL regrese los id nuevos. Con eso se crean los `MaterialCentro` en otro `bulk_create`. Medido aquí: **50,000 renglones en 2.7 segundos**.

Todo va en una transacción (`@transaction.atomic`). Si alguien da de alta el mismo código mientras se importa, el `UNIQUE` de PostgreSQL lanza `IntegrityError`, se deshace todo y se pide volver a intentar.

## 4. Consulta

| Ruta | Pantalla |
| --- | --- |
| `/catalogo-sap/` | Catálogo de materiales |
| `/catalogo-sap/servicios/` | Catálogo de servicios |
| `/catalogo-sap/importar/` | Importar (ADMIN y DM) e historial |
| `/catalogo-sap/importar/<id>/` | Resultado de una importación, con sus errores |

La búsqueda acepta código (empieza con), descripción o No. Parte (contiene), más un filtro por Centro. Son 50 por página.

**Materiales: un renglón por Material + Centro, con todas las columnas del alta AMAT_ZRA** (pedido de Dave), en el mismo orden que la captura: Código SAP, Tipo de material, Centro, Descripción, UMB, Grupo de compras, Grupo de artículos, Categoría de valoración, Ubicación, No. Parte Original, Tipo de unidad, Marca, Versión, Año modelo, Compatibilidad, Almacén, CeBe y Origen.

- Lo **importado** solo trae lo que tiene el layout del TXT; las demás columnas salen con "—".
- Lo **dado de alta en WebDM** las llena todas: al terminar con código, DM copia los datos de la partida al catálogo (`flujo.terminar_con_codigos`) y guarda `partida_origen`, de donde salen las imágenes.
- La migración `0006_llenar_materiales_webdm` llena estas columnas en los materiales que ya se habían dado de alta antes del cambio.

**Filtros:** bajo cada encabezado hay un cuadro de filtro (todos menos Almacén y UMB). Escribes y presionas Enter. La lista `COLUMNAS_MATERIALES` de `views.py` dice qué búsqueda usa cada columna:

| Columna | Búsqueda | SQL |
| --- | --- | --- |
| Código SAP | `material__codigo__startswith` | `codigo LIKE '3100%'` |
| Centro, Origen | igual (lista) | `centro_id = 1` |
| Año modelo | igual | `anio_modelo = 2024` |
| Las demás | `__icontains` | `UPPER(marca) LIKE UPPER('%marc%')` |

Cada filtro con valor agrega un `AND` al `WHERE`. La paginación conserva los filtros (`filtros_url`).

**Ficha del material:** clic en el código abre `/catalogo-sap/material/<id>/` con todos sus datos, una tabla por Centro (grupo de compras, categoría, almacén, CeBe) y sus imágenes, con el mismo visor de la ficha de partida (lupa, descarga, abrir en otra pestaña). El catálogo es global, así que las imágenes de un material **ya dado de alta** las ve cualquier usuario; las de partidas en trámite siguen siendo solo para quien ve la solicitud.

La consulta parte de `MaterialCentro` y trae su material y su Centro con `JOIN` (`select_related`), así que la página es **una** consulta (más el `COUNT` del paginador):

```sql
SELECT "catalogo_sap_materialcentro".*, "catalogo_sap_materialsap".*, "catalogos_centro".*, ...
FROM "catalogo_sap_materialcentro"
INNER JOIN "catalogos_centro" ON ("catalogo_sap_materialcentro"."centro_id" = "catalogos_centro"."id")
INNER JOIN "catalogo_sap_materialsap" ON ("catalogo_sap_materialcentro"."material_id" = "catalogo_sap_materialsap"."id")
LEFT OUTER JOIN "catalogo_sap_importacion" ON (...)
INNER JOIN "usuarios_usuario" ON (...)
WHERE NOT "catalogo_sap_materialsap"."es_servicio"
  AND UPPER("catalogo_sap_materialsap"."marca"::text) LIKE UPPER('%marc%')
ORDER BY "catalogo_sap_materialsap"."codigo" ASC, "catalogos_centro"."codigo" ASC
LIMIT 50;
```

Los **servicios** siguen con un renglón por código y una búsqueda general, porque no tienen Centro.

**Columnas nuevas (migración 0005):**

```sql
ALTER TABLE "catalogo_sap_materialsap" ADD COLUMN "ubicacion" varchar(20) DEFAULT '' NOT NULL;
ALTER TABLE "catalogo_sap_materialsap" ADD COLUMN "anio_modelo" smallint NULL CHECK ("anio_modelo" >= 0);
-- …tipo_unidad, marca, version, compatibilidad igual que ubicacion
ALTER TABLE "catalogo_sap_materialsap" ADD COLUMN "partida_origen_id" bigint NULL UNIQUE
    REFERENCES "solicitudes_partida"("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "catalogo_sap_materialcentro" ADD COLUMN "almacen" varchar(20) DEFAULT '' NOT NULL;
```

## 5. Ejercicios en `psql`

```sql
-- 1. ¿Cuántos códigos hay en cada catálogo?
SELECT es_servicio, COUNT(*) FROM catalogo_sap_materialsap GROUP BY es_servicio;

-- 2. Materiales que existen en más de un Centro
SELECT m.codigo, m.descripcion, COUNT(*) AS centros
FROM catalogo_sap_materialsap m JOIN catalogo_sap_materialcentro mc ON mc.material_id = m.id
GROUP BY m.id HAVING COUNT(*) > 1;

-- 3. Los errores más comunes de la última importación
SELECT mensaje, COUNT(*) FROM catalogo_sap_errorimportacion
WHERE importacion_id = (SELECT MAX(id) FROM catalogo_sap_importacion)
GROUP BY mensaje ORDER BY 2 DESC;
```

## 6. Pruebas

`catalogo_sap/tests/test_importar.py` prueba lo siguiente:

- Un código en dos Centros.
- Los renglones buenos entran aunque otros fallen.
- Cada tipo de error, con su línea.
- Descripción distinta: no se sube ninguno.
- Material + Centro ya existente: no se carga; el mismo código en otro Centro sí, sobre el mismo material.
- Material existente con otra descripción o grupo de artículos.
- Grupo de artículos distinto en el mismo código (materiales y servicios).
- Valores que no existen en los catálogos de WebDM, y CeBe de otro Centro.
- Los archivos de ejemplo dan los resultados que dice esta guía.
- El mismo código en materiales y en servicios.
- Catálogo de servicios sin Centro, y ZSA en materiales.
- Columnas nuevas de materiales: grupo de compras, grupo de artículos, categoría de valoración y CeBe.
- BOM y columnas en otro orden.
- Archivo que no está en UTF-8.
- Encabezados faltantes.
- Permisos.
- La consulta separa materiales y servicios.
- Materiales: un renglón por Material + Centro.
- El alta en WebDM llena todas las columnas; filtros por columna (sin Almacén ni UMB); ficha del material con imágenes visible para cualquier usuario.

En total pasan 127 pruebas.

## 7. Pendiente para la fase 5

Nginx limita por omisión las subidas a 1 MB. Para "sin límite" hay que poner `client_max_body_size 0;` en su configuración.
