# Fase 4e: ASER_ZSA, alta de servicios

Lo que definió Dave el 28-nov-2026:

| Decisión | Cómo quedó |
| --- | --- |
| Captura | Partida, **Tipo de servicio**, Descripción, UMB, Grupo de artículos y Estado. Sin Centro y **sin imágenes**. |
| Tipo de servicio | Sale del catálogo de **Tipos de material** (ZRA, ZSA…). Los renglones nuevos traen ZSA y se puede cambiar. Es obligatorio para enviar. |
| UMB | **Depende del tipo**: se propone la UMB predeterminada del tipo elegido. ADMIN la define en **Administración → Tipos de material**. Al cambiar el tipo, la UMB cambia a la del tipo nuevo, salvo que el usuario ya haya elegido otra a mano. Si la UMB se deja vacía, se guarda la del tipo. |
| Reglas | Las mismas del alta de materiales: descripción en mayúsculas y sin acentos (la Ñ se queda), máximo 40, y catálogos activos. |
| Duplicados | Contra el **catálogo de servicios**. La misma descripción **bloquea**; una parecida solo **avisa**. |
| Quién la atiende | Cualquier VAL_MAT o DM, porque los servicios no tienen Centro. |
| DM | Escribe el **Código SAP** en su bandeja, como en las altas de materiales, y puede **exportar `Alta_Ser.txt`** con Código SAP, Descripción, UMB y Grupo de artículos. |
| Al terminar | El servicio entra al **catálogo de servicios**, con origen WEBDM y el folio. |

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git fetch origin
git checkout fase-4e
git pull
python manage.py migrate      # UMB predeterminada en Tipos de material y UMB en el servicio
python manage.py test
python manage.py runserver
```

1. Como **admin**, abre **Administración → Tipos de material** y elige la **UMB predeterminada** de cada tipo (por ejemplo ZSA → SER y ZRA → PZA). Si el tipo ZSA no existe, créalo.
2. Entra como `validador`. En el menú, **Servicios → Crear servicios** ya está activo. Cada renglón trae el tipo ZSA y su UMB.
3. Cambia el tipo de un renglón a ZRA: la UMB cambia a PZA. Elige a mano otra UMB y vuelve a cambiar el tipo: tu UMB se respeta.
4. Pega desde Excel `Tipo ⇥ Descripción ⇥ UMB ⇥ Grupo de artículos`. Si dejas la UMB vacía, se queda la del tipo.
5. Presiona **Enter**: valida y guarda el borrador. Prueba la descripción de un servicio que ya existe: sale en rojo "Ya existe el servicio … con esta descripción".
6. **Enviar.** Como eres validador, va directo a DM.
7. Entra como `dm`. En **Pendientes → Datos Maestros**, escribe el Código SAP en el renglón, márcalo y usa **Exportar TXT**: sale `Alta_Ser.txt` con ese código.
8. **Terminar altas con el código capturado.** El servicio aparece en **Consulta → Catálogo de servicios**.

## 2. Dónde se guarda

```sql
ALTER TABLE "catalogos_tipomaterial" ADD COLUMN "umb_predeterminada_id" bigint NULL
    REFERENCES "catalogos_umb" ("id") DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE "solicitudes_detalleservicio" ADD COLUMN "umb_id" bigint NULL
    REFERENCES "catalogos_umb" ("id") DEFERRABLE INITIALLY DEFERRED;
-- Migración 0005: el tipo de servicio de cada renglón
ALTER TABLE "solicitudes_detalleservicio" ADD COLUMN "tipo_material_id" bigint NULL
    REFERENCES "catalogos_tipomaterial" ("id") DEFERRABLE INITIALLY DEFERRED;
CREATE INDEX "solicitudes_detalleservicio_tipo_material_id_b91fbe6f"
    ON "solicitudes_detalleservicio" ("tipo_material_id");
```

`DetalleServicio` ya existía desde la fase 1, con descripción, grupo de artículos y código SAP. Ahora también tiene UMB y tipo de servicio. Al terminar, el código del tipo (ZSA o ZRA) se copia al servicio del catálogo. La partida queda con `centro_id` en **NULL**.

## 3. El código

- `solicitudes/alta_servicio.py` reúne las reglas:
  - `umb_de(tipo)` (la UMB predeterminada de un tipo), `umbs_por_tipo()` (la tabla que usa la pantalla) y `tipo_propuesto()` (ZSA);
  - el formulario y el formset, con `validar_para_envio()`, que revisa obligatorios y duplicados;
  - `guardar_borrador()`, `enviar()` y `faltantes()`;
  - `texto_txt()`, `error_codigo()` y `terminar()`.
- `duplicados.buscar(..., servicio=True)` busca en el catálogo de servicios. Ahí la misma descripción ya es un duplicado, porque los servicios no tienen No. Parte.
- `flujo.terminar_con_codigos()` ahora termina altas de materiales **y** de servicios. El código de un servicio se valida contra el catálogo de servicios: el mismo código puede existir como material.
- `lotes.exportar()` arma `Alta_Ser.txt` con el código que DM escribió en el renglón, aunque todavía no lo haya guardado.
- `alcance.py`: un alta de servicio la ve cualquier VAL_MAT o DM.
- `static/js/alta_servicio.js` maneja agregar renglones con el tipo y su UMB, el pegado desde Excel y `proponerUmb()`: al cambiar el tipo, cambia la UMB solo si estaba vacía o era la del tipo anterior. La vista le pasa `umbPorTipo`, por ejemplo `{"2": "4", "1": "1"}` (id de tipo → id de UMB).

## 4. El TXT

Lleva cabecera y está separado por tabuladores (los `→` son tabuladores):

```
Código SAP→Descripción→UMB→Grupo de artículos
900002→ALINEACION Y BALANCEO→SER→GA1
→LAVADO DE MOTOR→SER→GA1
```

Si una partida todavía no tiene código, la columna va vacía. Exportar **no cambia nada**.

## 5. Ejercicios en `psql`

```sql
-- Servicios dados de alta desde WebDM
SELECT codigo, descripcion, umb, grupo_articulos, folio_origen FROM catalogo_sap_materialsap
WHERE es_servicio AND origen = 'WEBDM' ORDER BY codigo;

-- La UMB que se propone para cada tipo
SELECT t.codigo, u.codigo AS umb FROM catalogos_tipomaterial t LEFT JOIN catalogos_umb u ON u.id = t.umb_predeterminada_id;

-- Servicios capturados por tipo
SELECT t.codigo AS tipo, count(*) FROM solicitudes_detalleservicio d
LEFT JOIN catalogos_tipomaterial t ON t.id = d.tipo_material_id GROUP BY t.codigo;
```

## 6. Pruebas

`solicitudes/tests/test_alta_servicio.py` tiene 11 pruebas:

- El tipo y la UMB propuestos y el menú.
- La UMB depende del tipo, y la que eligió el usuario no se cambia.
- La normalización.
- Obligatorios y repetidos.
- Duplicado exacto y parecido.
- Sin UMB predeterminada.
- Quién la ve.
- Exportar con el código del renglón y terminar: un código que ya existe en servicios se rechaza, y uno de material se acepta.
- Aprobar revisa duplicados.
- Corregir y reenviar.
- El detalle.

En total pasan 183 pruebas.

## 7. Lo que sigue

Vencimientos de 15/30 días.
