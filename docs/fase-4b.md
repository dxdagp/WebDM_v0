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
python manage.py test
python manage.py runserver
```

1. Entra como `dm` (o un ADMIN). En el menú aparece **Administración → Importar catálogo SAP**.
2. Elige **Materiales** y sube `docs\ejemplos\catalogo-materiales-ejemplo.txt`. Resultado: 3 importados y 2 con error (un código de 5 dígitos y un Centro que no existe). La tabla dice en qué línea está cada error y por qué.
3. Abre **Consulta → Catálogo de materiales**. El 310001 aparece en MEIX y MTTU, con origen IMPORT y tu usuario.
4. Importa `catalogo-servicios-ejemplo.txt` eligiendo **Servicios**: entran 3. Uno de ellos es el 310001 SERVICIO DE MUELLES, el mismo código que la balata en materiales, porque los catálogos son independientes.
5. Vuelve a importar el archivo de materiales: ahora todo es error, porque los códigos ya existen. Para agregar un Centro a un material existente está AMPL_ZRA, que viene después.

### Cabeceras del TXT

**Materiales**, un renglón por material y Centro:

```
CODIGO_SAP	DESCRIPCION	CENTRO	TIPO_MATERIAL	UMB	GRUPO_COMPRAS	GRUPO_ARTICULOS	CATEGORIA_VALORACION	CEBE	NO_PARTE_ORIGINAL
```

Todas son obligatorias menos `NO_PARTE_ORIGINAL`.

**Servicios**, un renglón por servicio y sin Centro:

```
CODIGO_SAP	DESCRIPCION	TIPO_MATERIAL	UMB
```

Las columnas pueden venir en cualquier orden y las desconocidas se ignoran. En Excel se guarda con **Archivo → Guardar como → "Texto Unicode (UTF-8)"** o "Texto (delimitado por tabulaciones)".

### Dónde se guarda cada dato

| Dato | Tabla | Por qué |
| --- | --- | --- |
| Descripción, Tipo, UMB, No. Parte, Grupo de artículos | `catalogo_sap_materialsap` | Son del material, igual en todos los Centros. |
| Grupo de compras, Categoría de valoración, CeBe | `catalogo_sap_materialcentro` | En SAP dependen del Centro. |

Si un material trae grupos de artículos distintos en sus renglones, se queda el del primer renglón. Las descripciones distintas sí bloquean el código completo.

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

**Paso 1, cada renglón solo:** campos vacíos, 6 dígitos, Centro existente, 40 caracteres, ZSA en materiales y código que ya existía.

Para "ya existía" no se hace una consulta por renglón. Al inicio se trae una vez:

```python
existentes = set(MaterialSAP.objects.values_list("codigo", flat=True))
```

```sql
SELECT "codigo" FROM "catalogo_sap_materialsap";
```

Preguntar `codigo in existentes` en un `set` de Python tarda lo mismo con 10 que con 100,000 códigos.

**Paso 2, entre renglones:** se agrupan por código. Si las descripciones difieren, todos los renglones de ese código son error. Si Código + Centro se repite, el segundo es error.

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

Los Centros de cada material salen con `Prefetch`. En lugar de una consulta por material (50 consultas), Django hace **una** para los 50:

```sql
SELECT ... FROM "catalogo_sap_materialcentro"
INNER JOIN "catalogos_centro" ON ...
WHERE "catalogo_sap_materialcentro"."material_id" IN (12, 13, 14, ...)
ORDER BY "catalogos_centro"."codigo";
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
- Código ya existente.
- El mismo código en materiales y en servicios.
- Catálogo de servicios sin Centro, y ZSA en materiales.
- Columnas nuevas de materiales: grupo de compras, grupo de artículos, categoría de valoración y CeBe.
- BOM y columnas en otro orden.
- Archivo que no está en UTF-8.
- Encabezados faltantes.
- Permisos.
- La consulta separa materiales y servicios.

En total pasan 119 pruebas.

## 7. Pendiente para la fase 5

Nginx limita por omisión las subidas a 1 MB. Para "sin límite" hay que poner `client_max_body_size 0;` en su configuración.
