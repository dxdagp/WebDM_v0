# Fase 4d: MOD_ZRA y MOD_ZSA, modificación de materiales y servicios

Lo que definió Dave el 28-nov-2026:

| Decisión | Cómo quedó |
| --- | --- |
| Captura | Un renglón por **Material + Dato**: Partida, Descripción (automática), Material, Centro, Dato, Valor actual (automático), Valor nuevo y Estado. |
| Datos generales (sin Centro) | Descripción, grupo de artículos, ubicación, No. Parte Original, tipo de unidad, marca, versión, año modelo y compatibilidad. |
| Datos por Centro | **Grupo de compras, Almacén y CeBe.** Piden Centro, y el material debe existir en ese Centro. |
| Servicios (MOD_ZSA) | La misma pantalla, con el catálogo de servicios, sin Centro, y solo descripción y grupo de artículos. |
| Pegado desde Excel | Como la tabla (Material, Centro, Dato, Valor nuevo), o **un renglón por material con encabezados**, que se separa solo en un renglón por dato. |
| TXT para SAP | `Mod_Mat.txt` o `Mod_Ser.txt`, **con cabecera** y **solo los valores nuevos** (ver la sección 5). |
| Flujo | Igual que AMAT y AMPL: VAL_MAT aprueba, devuelve o cancela; si la crea un validador, va directo a DM. DM exporta, excluye con motivo y finaliza desde su bandeja. |
| Finalizar | Escribe el valor nuevo en el catálogo de WebDM. |

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git fetch origin
git checkout fase-4d
git pull
python manage.py migrate      # agrega codigo_sap y valor_actual a la modificación
python manage.py test
python manage.py runserver
```

1. Entra como `validador`. En el menú, **Materiales → Modificar materiales** y **Servicios → Modificar servicios** ya están activos.
2. En Excel escribe esto y cópialo (con los encabezados):

   ```
   Material   Centro   Marca    Año modelo   Grupo de compras
   310001     MTTU     Nissan   2024         G01
   ```

3. Pégalo en la primera celda de Material. Salen **3 renglones**, uno por dato. Cada uno muestra la descripción y el valor actual. Marca y Año modelo quedan sin Centro, porque son datos generales.
4. Presiona **Enter**: valida y guarda el borrador. Prueba un año `20A4` o una marca igual a la actual para ver los errores en rojo.
5. **Enviar.** Como eres validador, va directo a Datos Maestros.
6. Entra como `dm`. En **Pendientes → Datos Maestros** marca las partidas y usa **Exportar TXT**. Ábrelo con el Bloc de notas.
7. **Finalizar seleccionadas.** Abre el material en **Consulta → Catálogo de materiales**: ya tiene la marca nueva.

## 2. Dónde se guarda

`DetalleModificacion` existía desde la fase 1. Se agregaron dos columnas y tres datos posibles:

```sql
ALTER TABLE "solicitudes_detallemodificacion" ADD COLUMN "codigo_sap" varchar(6) DEFAULT '' NOT NULL;
ALTER TABLE "solicitudes_detallemodificacion" ALTER COLUMN "codigo_sap" DROP DEFAULT;
ALTER TABLE "solicitudes_detallemodificacion" ADD COLUMN "valor_actual" varchar(40) DEFAULT '' NOT NULL;
ALTER TABLE "solicitudes_detallemodificacion" ALTER COLUMN "valor_actual" DROP DEFAULT;
```

Los tres datos nuevos (`GRUPO_COMPRAS`, `ALMACEN` y `CEBE`) son opciones de un `choices`, así que no cambian la tabla, solo la validación de Django.

| Columna | Para qué |
| --- | --- |
| `codigo_sap` | Lo que escribió el usuario. `material_id` es el material del catálogo que le corresponde. |
| `campo` | El dato: `MARCA`, `ALMACEN`, etc. |
| `valor_actual` | Una **foto** del catálogo al capturar. Así VAL_MAT ve «FORD» → «NISSAN» aunque luego cambie el catálogo. |
| `valor_nuevo` | Ya normalizado: mayúsculas y sin acentos (la Ñ se queda), igual que en el alta. |
| `solicitudes_partida.centro_id` | Solo para los datos por Centro. En los generales queda **NULL**. |

## 3. ¿Quién ve una modificación sin Centro?

Hasta ahora toda partida tenía Centro y la regla era "la ven los VAL_MAT y DM de ese Centro". Una marca o una descripción no son de ningún Centro. La regla nueva vive en `solicitudes/alcance.py`, y la usan todas las bandejas y revisiones:

- Con Centro: igual que siempre.
- MOD_ZRA sin Centro: la ven quienes tengan alguno de los Centros donde existe el material.
- MOD_ZSA: los servicios no tienen Centro, así que la ve cualquier VAL_MAT o DM.

```sql
WHERE p.centro_id IN (mis centros)
   OR (p.centro_id IS NULL AND (m.es_servicio
       OR EXISTS (SELECT 1 FROM catalogo_sap_materialcentro mc
                  WHERE mc.material_id = d.material_id AND mc.centro_id IN (mis centros))))
```

`EXISTS` responde sí o no y no repite renglones aunque el material esté en varios de tus Centros. Con un `JOIN` normal, la misma partida saldría una vez por Centro.

## 4. Validaciones

Se revisan con Enter, al Guardar borrador y al Enviar (igual que AMAT y AMPL):

| Regla | Mensaje |
| --- | --- |
| El código existe en SU catálogo (materiales o servicios: el mismo código puede estar en los dos) | "No existe en el catálogo de materiales." |
| Grupo de artículos y ubicación existen en sus catálogos | "No existe en el catálogo de grupo de artículos." |
| Almacén y grupo de compras son del Centro | "No es un almacén de MTTU." |
| El material existe en el Centro (datos por Centro) | "El material no existe en MEIX." |
| Año de 4 dígitos, textos de máximo 40, CeBe de máximo 20 | "El año debe tener 4 dígitos (1900 a 2100)." |
| El valor nuevo es distinto al actual | "Es igual al valor actual." |
| Material + Centro + Dato no se repite en la solicitud | "Este dato ya está en la partida 10." |
| …ni en otra solicitud enviada y abierta (solo al enviar) | "Este dato ya se está modificando en MOD_ZRA-2026-000004." |

Al **Aprobar** y al **Reenviar**, `modificacion.faltantes()` revisa otra vez que el valor nuevo siga siendo distinto. Si alguien ya cambió el catálogo mientras tanto, no deja aprobar.

## 5. El TXT

Un renglón por material (y por Centro, si hay datos por Centro), con cabecera. Solo van los **valores nuevos**; lo que no cambia va vacío. Ejemplo de `Mod_Mat.txt` (los `→` son tabuladores):

```
Material→Centro→Descripción técnica→Grupo de artículos→Ubicación de refacción→No. Parte Original→Tipo de Unidad→Marca→Versión→Año Modelo→Compatibilidad→Grupo de compras→Almacén→CeBe
310001→→→→→→→NISSAN→→2024→→→→
310001→MTTU→→→→→→→→→→G01→→
```

`Mod_Ser.txt` lleva `Servicio`, `Descripción técnica` y `Grupo de artículos`.

Un TXT es de un solo tipo. Si marcas ampliaciones y modificaciones juntas, sale "Exporta un tipo a la vez". Para separarlas, filtra la bandeja por folio, por ejemplo `MOD_ZRA`.

## 6. La bandeja de DM ahora atiende ampliaciones y modificaciones

`solicitudes/lotes.py` reúne lo de AMPL (fase 4c) y lo de MOD:

| Botón | Qué hace |
| --- | --- |
| **Exportar TXT** | `Amp_Mat.txt`, `Mod_Mat.txt` o `Mod_Ser.txt` con todo lo marcado, de uno o varios folios. No cambia nada. |
| **Excluir** | Con motivo por partida. Ya no salen en el TXT. |
| **Finalizar seleccionadas** | Cada flujo hace lo suyo: AMPL agrega el Centro al catálogo y MOD escribe el valor nuevo. Las partidas pasan a TERMINADA. |

Finalizar una modificación general hace un `UPDATE` al material. Una por Centro lo hace al renglón material + Centro:

```sql
UPDATE "catalogo_sap_materialsap" SET "marca" = 'NISSAN' WHERE id = 7;
UPDATE "catalogo_sap_materialcentro" SET "grupo_compras" = 'G01' WHERE id = 12;
```

`update_fields=[atributo]` hace que el `UPDATE` toque **solo** esa columna. Si otra persona cambió otro dato del mismo material al mismo tiempo, no se pisa. La historia de la partida guarda el antes y el después.

## 7. El código, archivo por archivo

- `solicitudes/modificacion.py`: las reglas: la tabla `ATRIBUTO` (dónde vive cada dato), `normalizar()` (valida el valor nuevo según el dato), los formularios, `guardar_borrador()`, `enviar()`, `faltantes()`, `texto_txt()` y `finalizar_partidas()`.
- `solicitudes/alcance.py`: quién ve qué (sección 3).
- `solicitudes/lotes.py`: Exportar y Finalizar de DM para AMPL y MOD.
- `static/js/modificacion.js`: valor actual, sugerencias de catálogo (`<datalist>`) y el pegado que separa por dato.
- `solicitudes/templates/solicitudes/capturar_mod.html` y `_fila_mod.html`: la tabla.

Una tabla grande no repite consultas: `precargar()` trae de una vez los materiales, sus Centros y los catálogos (6 consultas en total, sean 5 o 2,000 renglones).

## 8. Ejercicios en `psql`

```sql
-- Las modificaciones con su valor actual y el nuevo
SELECT s.folio, p.numero, p.estado, d.codigo_sap, c.codigo AS centro, d.campo, d.valor_actual, d.valor_nuevo
FROM solicitudes_detallemodificacion d
JOIN solicitudes_partida p ON p.id = d.partida_id
JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
LEFT JOIN catalogos_centro c ON c.id = p.centro_id     -- LEFT: los datos generales no tienen Centro
ORDER BY s.folio, p.numero;

-- Lo que se está modificando ahora (enviado y sin terminar)
SELECT d.codigo_sap, d.campo, s.folio FROM solicitudes_detallemodificacion d
JOIN solicitudes_partida p ON p.id = d.partida_id JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
WHERE p.estado IN ('EN_VALIDACION', 'DEVUELTA_SOL', 'EN_DM');
```

## 9. Pruebas

`solicitudes/tests/test_modificacion.py` tiene 15 pruebas:

- Normalización y valor actual.
- Un dato general ignora el Centro; un dato por Centro lo exige y valida su catálogo.
- Material que no está en el Centro; año, catálogos y valor igual al actual.
- Repetido en la solicitud y en otra abierta.
- Servicios: solo sus dos datos, y el servicio y no el material del mismo código.
- JSON del valor actual; menú.
- Quién lo ve según los Centros del material.
- Flujo completo: aprobar, exportar con cabecera, excluir, finalizar y la historia.
- Un tipo a la vez en el TXT; `Mod_Ser.txt`.
- Aprobar revisa que el valor siga siendo distinto.
- Corregir y reenviar.
- Detalle y bandeja.

En total pasan 171 pruebas.

## 10. Lo que sigue

Alta de servicios (ASER_ZSA) y vencimientos de 15/30 días.
