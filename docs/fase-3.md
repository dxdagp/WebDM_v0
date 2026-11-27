# Fase 3: bandejas, Código SAP y sesiones

Al terminar esta fase, una solicitud AMAT_ZRA recorre el flujo completo de la Revisión 3, sección 7:

```
SOL_MAT ──Enviar──▶ EN_VALIDACION ──Aprobar──▶ EN_DM ──Código SAP──▶ TERMINADA
                         │   ▲                    │
                 Devolver│   │Reenviar   Devolver │ (solo a VAL_MAT)
                         ▼   │                    ▼
                     DEVUELTA_SOL            EN_VALIDACION
                         │
                 Cancelar└──▶ CANCELADA  (VAL_MAT también cancela desde EN_VALIDACION)
```

| Rol | Qué hace ahora |
| --- | --- |
| SOL_MAT | Ve sus partidas devueltas, las corrige y reenvía, o las cancela. |
| VAL_MAT | Aprueba, devuelve o cancela **varias partidas a la vez**. Corrige datos en la tabla tipo Excel. |
| DM | Pega una columna de Códigos SAP y termina varias partidas a la vez. Devuelve a VAL_MAT. Corrige un código ya asignado. |
| ADMIN | Restablece contraseñas (el usuario debe cambiarla al entrar) y consulta la bitácora de sesiones. |

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git pull
python manage.py migrate          # agrega 2 columnas a la bitácora de sesiones
python manage.py runserver
```

Recorrido sugerido, con tres navegadores o ventanas privadas (una por usuario, contraseña `demo-webdm-2026`):

1. `solicitante` crea y envía una solicitud con 2 partidas.
2. `validador` abre **Pendientes de mi atención** (el número junto al menú dice cuántas tiene). Marca una partida, escribe un motivo y **Devolver al solicitante**. Marca la otra y **Aprobar**.
3. `solicitante` ve la devuelta en **Por corregir**, abre el folio, **Corregir partidas**, cambia la marca y **Guardar y reenviar**.
4. `validador` la aprueba.
5. `dm` pega dos códigos de 6 dígitos (de Excel, en la primera celda de Código SAP) y **Terminar partidas con código**.
6. Abre el folio: la cabecera dice TERMINADA y abajo está la **Historia** completa.

> `validador` también tiene SOL_MAT. Si él envía o reenvía, sus partidas saltan la validación y van directo a DM (Revisión 3, sección 4).

---

## 2. La máquina de estados en un solo archivo (`solicitudes/flujo.py`)

Toda la fase gira alrededor de esta tabla:

```python
TRANSICIONES = {
    "aprobar":  Transicion("VAL_MAT", E.EN_VALIDACION, E.EN_DM, Evento.Tipo.APROBACION, exige_completa=True),
    "devolver": Transicion("VAL_MAT", E.EN_VALIDACION, E.DEVUELTA_SOL, Evento.Tipo.DEVOLUCION, pide_motivo=True),
    ...
    "devolver_a_validacion": Transicion("DM", E.EN_DM, E.EN_VALIDACION, Evento.Tipo.DEVOLUCION, pide_motivo=True),
}
```

Cada renglón dice: **quién** puede hacerla, **desde** qué estado, **hacia** cuál, qué **evento** se registra y si pide motivo o exige la partida completa. Lo que no está en la tabla, no se puede hacer: por ejemplo, no hay ninguna transición de DM a DEVUELTA_SOL ni a CANCELADA, así que DM no puede devolver al solicitante ni cancelar (Revisión 3, sección 4).

`Transicion` es una **dataclass**: una clase que solo guarda datos. `frozen=True` la hace de solo lectura, así nadie la cambia por accidente.

Ninguna vista escribe `partida.estado = …` por su cuenta: todas llaman a `flujo.aplicar(usuario, accion, ids, motivo)`. Así las reglas están en un solo lugar y se prueban sin navegador (`solicitudes/tests/test_flujo.py`).

---

## 3. Todo o nada: `SELECT … FOR UPDATE`

El riesgo: dos validadores tienen abierta la misma bandeja. Uno aprueba 5 partidas y, en el mismo segundo, el otro devuelve 2 de esas 5. ¿Qué pasa?

`aplicar()` hace esto dentro de una transacción (`@transaction.atomic`):

```python
partidas = list(Partida.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
```

Django lo convierte en:

```sql
SELECT … FROM "solicitudes_partida"
WHERE "solicitudes_partida"."id" IN (1, 2)
ORDER BY "solicitudes_partida"."id" ASC
FOR UPDATE;
```

1. **`FOR UPDATE`** bloquea esas filas hasta el `COMMIT`. Si otro validador ya las tiene bloqueadas, esta consulta **espera** a que él termine.
2. Cuando por fin las lee, ya ve el estado nuevo. Si alguna ya no está en EN_VALIDACION, se lanza `AccionNoPermitida`.
3. Una excepción dentro de `@transaction.atomic` provoca un `ROLLBACK`: PostgreSQL deshace todo. No queda ninguna partida a medias.
4. **`ORDER BY id`** importa: si los dos bloquean en el mismo orden, nunca se quedan esperándose mutuamente (eso se llama *deadlock*).

Prueba: `ValidadoresSimultaneosTests` lanza dos hilos, uno aprueba y otro devuelve las mismas 3 partidas. Siempre gana uno y el otro recibe "otra persona las movió".

> `select_for_update()` fuera de una transacción da error a propósito (`TransactionManagementError`): un bloqueo sin transacción no protegería nada.

**Lo mismo con el Código SAP.** `terminar_con_codigos()` revisa que cada código tenga 6 dígitos, no exista en el catálogo y no se repita en la misma captura. Si dos DM registran el mismo código en el mismo instante, el `UNIQUE` de `catalogo_sap_materialsap.codigo` (fase 1) hace fallar al segundo con `IntegrityError`, que convertimos en un mensaje claro.

### Por qué no hay un `CHECK` de "TERMINADA tiene código"

La propuesta lo mencionaba, pero un `CHECK` de PostgreSQL solo puede mirar **columnas de la misma fila**. El estado vive en `solicitudes_partida` y el código en `solicitudes_detallealta`: son dos tablas. Para eso haría falta un *trigger*. Lo protege `flujo.py`, que es el único lugar que pone TERMINADA, y lo comprueba una prueba.

---

## 4. La bandeja (`solicitudes/bandejas.py`)

Cada pestaña es una función que devuelve un **QuerySet**: una consulta que todavía no se ejecuta.

```python
Partida.objects.filter(estado=E.EN_VALIDACION, centro__in=usuario.centros.values("pk"))
```

```sql
SELECT … FROM "solicitudes_partida"
WHERE "solicitudes_partida"."centro_id" IN (
        SELECT U0."id" FROM "catalogos_centro" U0
        INNER JOIN "usuarios_usuario_centros" U1 ON (U0."id" = U1."centro_id")
        WHERE U1."usuario_id" = 2)
  AND "solicitudes_partida"."estado" = 'EN_VALIDACION';
```

`usuarios_usuario_centros` es la tabla intermedia que Django creó para el `ManyToManyField` de Centros autorizados (fase 1).

La misma función sirve para la tabla (`for p in …`) y para el número del menú (`.count()` → `SELECT COUNT(*)`).

**El último motivo de devolución** se trae con una *subconsulta correlacionada*: un `SELECT` dentro del `SELECT` que se repite por cada partida.

```python
ultimo_motivo = Evento.objects.filter(partida=OuterRef("pk"), tipo="DEVOLUCION").order_by("-fecha").values("motivo")[:1]
queryset.annotate(ultimo_motivo=Subquery(ultimo_motivo))
```

`OuterRef("pk")` significa "el id de la partida de la consulta de afuera".

---

## 5. Corregir partidas (`servicios.guardar_correcciones`)

Se reutiliza la tabla tipo Excel con dos diferencias (`forms.PartidaCorreccionForm`):

- Cada renglón lleva oculto el id de su partida (`pid`).
- El número de partida es un campo **`disabled`**: Django ignora lo que mande el navegador y usa el valor que le da la vista. Nadie puede renumerar una partida enviada editando la página.

Al guardar, se compara cada campo con lo que había. Solo lo que cambió deja un `Evento` CAMBIO_CAMPO:

```json
{"campo": "marca", "antes": "MARCA", "despues": "OTRA MARCA"}
```

Se guarda en la columna `detalle`, de tipo **`jsonb`** en PostgreSQL. Puedes consultarla por dentro (ejercicio 2).

"Guardar y reenviar" corre `guardar_correcciones` y `aplicar("reenviar")` dentro de un mismo `transaction.atomic()`: si el reenvío falla, tampoco se guardan las correcciones.

**La ficha de una partida** (`views.partida`, pedido de Dave). Desde la bandeja, el clic en el folio o la descripción abre `/solicitudes/partida/<id>/`: los datos de **esa sola** partida en formato formulario, su historia y solo los botones que el usuario puede usar en ese momento. Los botones salen de la misma tabla `TRANSICIONES` (función `_acciones_posibles`), así que la ficha y la bandeja nunca se contradicen. Si la partida es editable para ti, los campos aparecen como formulario y Aprobar o Reenviar guardan antes los cambios, en la misma transacción. Hay un espacio reservado para las 3 imágenes, que se llenará en la fase 4.

---

## 6. Sesiones y contraseñas (`usuarios/sesiones.py`)

**Señales.** Django avisa cuando alguien entra o sale. En `usuarios/apps.py` conectamos dos funciones a esos avisos:

```python
user_logged_in.connect(sesiones.al_entrar)
user_logged_out.connect(sesiones.al_salir)
```

`al_entrar` crea un renglón en `usuarios_bitacorasesion` con la IP (`REMOTE_ADDR`), el navegador (User-Agent) y la llave de la sesión. `al_salir` lo cierra como LOGOUT_MANUAL.

**¿Y el TIMEOUT?** Cuando pasan 30 minutos sin actividad, nadie avisa: el navegador simplemente deja de pedir páginas. Por eso, la próxima vez que esa persona entra, `cerrar_vencidas()` busca sus registros abiertos y revisa en `django_session` si su sesión sigue viva:

```sql
SELECT 1 FROM django_session WHERE session_key = '…' AND expire_date > now();
```

Si ya no existe, el registro se cierra como TIMEOUT con la hora de su **última actividad**. Esa hora la guarda un *middleware*.

**Middleware.** Es una función por la que pasa **cada** petición antes de llegar a la vista. `SesionMiddleware` (registrado en `config/settings.py`, justo después de `AuthenticationMiddleware`) hace dos cosas:

1. Actualiza `ultima_actividad`, como máximo una vez por minuto para no escribir en la base en cada clic.
2. Si `debe_cambiar_password` está activo, redirige a **Cambiar contraseña** y no deja abrir nada más (solo salir).

**Restablecer contraseña.** En el panel de administración: Usuarios → el usuario → "Contraseña: … **este formulario**". Al guardar una contraseña temporal para **otro** usuario:

- Se activa `debe_cambiar_password`.
- Sus sesiones abiertas se anotan como SESION_INVALIDADA. Django ya las invalida solo: cada sesión guarda un resumen (*hash*) de la contraseña, y si la contraseña cambia, la sesión deja de servir.

**La contraseña no caduca** (indicación de Dave): no hay vencimiento por tiempo, ni de la contraseña normal ni de la temporal. Solo se pide cambiarla después de un restablecimiento. Cualquier usuario puede cambiarla cuando quiera desde el enlace "Cambiar contraseña" bajo su nombre.

La migración `usuarios/0004` agrega las dos columnas nuevas. Mira el SQL con `python manage.py sqlmigrate usuarios 0004`:

```sql
ALTER TABLE "usuarios_bitacorasesion" ADD COLUMN "session_key" varchar(40) DEFAULT '' NOT NULL;
ALTER TABLE "usuarios_bitacorasesion" ALTER COLUMN "session_key" DROP DEFAULT;
ALTER TABLE "usuarios_bitacorasesion" ADD COLUMN "ultima_actividad" timestamp with time zone NULL;
CREATE INDEX "usuarios_bitacorasesion_session_key_02431dd8" ON "usuarios_bitacorasesion" ("session_key");
```

¿Por qué `DEFAULT ''` y luego `DROP DEFAULT`? La tabla ya tiene renglones y la columna es `NOT NULL`: PostgreSQL necesita un valor para llenar los existentes. Después Django quita el default porque los valores por omisión los maneja en Python.

---

## 6b. El rol ADMIN y los permisos del panel (`usuarios/permisos.py`)

En la ficha de un usuario del panel hay dos mundos:

- **WebDM**: Grupos (los roles), Centros autorizados, Activo y Debe cambiar contraseña. Esto decide qué hace en WebDM.
- **Panel de Django**: "Es staff" (puede entrar al panel), "Es superusuario" (puede todo en el panel) y la lista de "Permisos de usuario" por tabla (agregar, modificar, eliminar, ver).

Decisión de Dave: **el rol ADMIN da acceso automático al panel**. Por eso:

1. Al poner o quitar el rol ADMIN, una señal `m2m_changed` marca o desmarca "Es staff". Ya no se toca a mano.
2. Al terminar cada `migrate`, una señal `post_migrate` le da al grupo ADMIN siempre la misma lista de permisos: agregar, modificar y ver usuarios y catálogos; solo ver solicitudes, catálogo SAP, roles y bitácora. **Nunca eliminar**: usuarios y catálogos se desactivan para no perder la historia.
3. La ficha del usuario ya no muestra "Es staff" ni "Permisos de usuario". "Es superusuario" solo la ve un superusuario, y un ADMIN no ve ni edita superusuarios.

¿Por qué `post_migrate` y no una migración de datos como la de los roles? Django crea los permisos de cada tabla justo **después** de sus migraciones. En una base nueva, dentro de una migración todavía no existirían.

Consulta en `psql` qué permisos tiene el rol:

```sql
SELECT p.codename
FROM auth_group g
JOIN auth_group_permissions gp ON gp.group_id = g.id
JOIN auth_permission p ON p.id = gp.permission_id
WHERE g.name = 'ADMIN'
ORDER BY p.codename;
```

---

## 7. Ejercicios en `psql`

Conéctate con `& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U webdm -d webdm`.

1. **La historia de una partida**, en orden:
   ```sql
   SELECT e.fecha, p.numero, e.tipo, e.estado_anterior, e.estado_nuevo, e.motivo
   FROM solicitudes_evento e
   JOIN solicitudes_partida p ON p.id = e.partida_id
   JOIN solicitudes_solicitud s ON s.id = e.solicitud_id
   WHERE s.folio = 'AMAT_ZRA-2026-000001'
   ORDER BY e.fecha;
   ```
2. **Buscar dentro del JSON**: todos los cambios del campo marca. El operador `->>` saca un valor de un `jsonb` como texto.
   ```sql
   SELECT fecha, detalle->>'antes' AS antes, detalle->>'despues' AS despues
   FROM solicitudes_evento
   WHERE tipo = 'CAMBIO_CAMPO' AND detalle->>'campo' = 'marca';
   ```
3. **Ver el bloqueo con tus propios ojos.** Busca el id de una partida con `SELECT id, estado FROM solicitudes_partida;` (aquí suponemos que es 1) y abre dos `psql`.
   - Terminal 1: `BEGIN;` y luego `SELECT id, estado FROM solicitudes_partida WHERE id = 1 FOR UPDATE;`
   - Terminal 2: `BEGIN;` y luego `UPDATE solicitudes_partida SET estado = estado WHERE id = 1;` → se queda esperando.
   - Terminal 1: `ROLLBACK;` → la terminal 2 termina al instante.
   - Terminal 2: `ROLLBACK;` para no dejar nada cambiado.
4. **Bitácora de sesiones**:
   ```sql
   SELECT u.username, b.inicio, b.ultima_actividad, b.fin, b.tipo_cierre, b.ip
   FROM usuarios_bitacorasesion b JOIN usuarios_usuario u ON u.id = b.usuario_id
   ORDER BY b.inicio DESC LIMIT 10;
   ```
5. **Pregunta**: en `flujo.aplicar`, ¿qué pasaría si quitáramos `select_for_update()` y dos validadores actuaran a la vez? Pista: los dos leerían EN_VALIDACION.

---

## 8. Pruebas

```powershell
python manage.py test
```

Deben salir **67 pruebas OK**. Las nuevas:

| Archivo | Qué comprueba |
| --- | --- |
| `solicitudes/tests/test_flujo.py` | Acciones en bloque, motivo obligatorio, todo o nada, partida completa para aprobar, roles y Centros, Código SAP y su corrección, dos validadores a la vez |
| `solicitudes/tests/test_bandejas.py` | Bandeja por Centro, contador del menú, pantallas de acción, corrección y reenvío, ficha de una partida |
| `usuarios/tests/test_sesiones.py` | Bitácora de entrada, salida y TIMEOUT; restablecer y cambio obligatorio |
| `usuarios/tests/test_permisos.py` | El rol ADMIN da y quita el acceso al panel, sus permisos y que no toque superusuarios |

## Siguiente: fase 4

AMPL_ZRA con exportación TXT, modificaciones de materiales y servicios, alta de servicios, imágenes, importación del catálogo SAP, búsqueda de duplicados y vencimientos de 15/30 días.
