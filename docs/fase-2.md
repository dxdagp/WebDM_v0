# Fase 2: captura de AMAT_ZRA tipo Excel y folios

Al terminar esta fase, un usuario con rol SOL_MAT o VAL_MAT puede:

- Abrir **Crear materiales** desde el menú lateral (que ya muestra solo las opciones de sus roles).
- Pegar un bloque desde Excel en la tabla, que crea las partidas que hagan falta.
- **Guardar borrador** con datos incompletos.
- **Enviar**: WebDM valida toda la tabla de una vez, asigna el folio `AMAT_ZRA-2026-000001` y pasa las partidas a EN_VALIDACION (o a EN_DM si quien envía es VAL_MAT).
- Ver sus solicitudes en **Mis solicitudes**.

Todavía **no** están: imágenes y búsqueda de duplicados (fase 4), ni las bandejas de VAL_MAT y DM (fase 3). Por eso, de momento, Enviar no exige imágenes.

## 1. Probarlo en tu máquina

```bash
git pull
source .venv/bin/activate
python manage.py migrate
python manage.py datos_demo     # catálogos y 3 usuarios de prueba
python manage.py runserver
```

Entra con `solicitante` / `demo-webdm-2026`. Copia de Excel varias filas con estas 13 columnas, **en este orden** y sin encabezados:

```
Centro | Descripción | Ubicación | No. Parte | Tipo Unidad | Marca | Versión | Año | Compatibilidad | UMB | Grupo artículos | Categoría | Grupo compras
```

Por ejemplo `MTTU, Filtro de aire, MOTOR, abc-1, Tracto, Marca, V1, 2024, (vacío), PZA, REF01, CV01, G01`. Haz clic en la celda Centro de la partida 10 y pega.

---

## 2. El recorrido de una petición

```
Navegador ──POST /solicitudes/amat/nueva/──▶ config/urls.py ──▶ solicitudes/urls.py
   ──▶ views.capturar_amat ──▶ forms.PartidasFormSet (valida) ──▶ servicios.enviar (guarda)
   ──▶ folios.siguiente_folio (SQL) ──▶ redirect a la solicitud
```

Cada pieza tiene una sola responsabilidad:

| Archivo | Responsabilidad |
| --- | --- |
| `solicitudes/urls.py` | Qué dirección va a qué vista |
| `solicitudes/views.py` | Leer la petición, elegir qué mostrar |
| `solicitudes/forms.py` | Validar cada celda y cada renglón |
| `solicitudes/servicios.py` | Reglas de negocio: guardar, enviar, a qué estado pasa cada partida |
| `solicitudes/folios.py` | Reservar el siguiente folio sin duplicados |
| `solicitudes/normalizar.py` | MAYÚSCULAS y sin acentos |
| `static/js/captura.js` | Comodidad en el navegador: pegado, renglones, columnas automáticas |

---

## 3. El folio, línea por línea (`solicitudes/folios.py`)

El riesgo: dos personas envían en el mismo segundo, las dos leen "último = 41" y las dos toman el 42.

La solución es una sola sentencia SQL:

```sql
INSERT INTO solicitudes_contadorfolio (flujo, anio, ultimo)
VALUES ('AMAT_ZRA', 2026, 1)
ON CONFLICT (flujo, anio)
DO UPDATE SET ultimo = solicitudes_contadorfolio.ultimo + 1
RETURNING ultimo;
```

1. **`INSERT … VALUES (…, 1)`**: si es el primer folio del año, crea la fila con 1.
2. **`ON CONFLICT (flujo, anio)`**: si la fila ya existe, la restricción `UNIQUE (flujo, anio)` de la fase 1 provoca un conflicto…
3. **`DO UPDATE SET ultimo = … + 1`**: …y en lugar de fallar, suma 1. A esto se le llama *upsert* (update + insert).
4. **`RETURNING ultimo`**: devuelve el número resultante sin hacer otra consulta.
5. Mientras una transacción tiene la fila modificada, PostgreSQL la **bloquea**. La segunda persona espera milisegundos y recibe el 43.

En Python:

```python
with connection.cursor() as cursor:
    cursor.execute(SQL_SIGUIENTE, [flujo, anio])
    (numero,) = cursor.fetchone()
return formatear_folio(flujo, anio, numero)   # f"{flujo}-{anio}-{numero:06d}"
```

- Los valores van en una lista aparte (`[flujo, anio]`) y en el SQL aparecen como `%s`. **Nunca** los pegues dentro del texto con un f-string: psycopg los escapa por ti y así se evita la *inyección de SQL*.
- `{numero:06d}` rellena con ceros hasta 6 dígitos: 7 → `000007`.

**Sin huecos en la numeración:** `servicios.enviar` tiene el decorador `@transaction.atomic`. Si algo falla después de pedir el folio, PostgreSQL deshace toda la transacción, también el `+1` del contador.

**La prueba de fuego** está en `solicitudes/tests/test_folios.py`: `test_veinte_envios_simultaneos_no_repiten_folio` lanza 20 hilos que piden folio exactamente al mismo tiempo y comprueba que salen 20 folios distintos, del 1 al 20.

### Practica en `psql`

```sql
SELECT * FROM solicitudes_contadorfolio;

-- Simula un envío a mano (y revisa cómo sube el contador):
INSERT INTO solicitudes_contadorfolio (flujo, anio, ultimo) VALUES ('AMAT_ZRA', 2026, 1)
ON CONFLICT (flujo, anio) DO UPDATE SET ultimo = solicitudes_contadorfolio.ultimo + 1
RETURNING ultimo;
```

Experimento de bloqueo: abre **dos** terminales con `psql`. En la primera escribe `BEGIN;` y luego el `INSERT … ON CONFLICT`. En la segunda ejecuta el mismo `INSERT`: se queda esperando. Regresa a la primera y escribe `COMMIT;`. La segunda termina al instante con el número siguiente. Eso es exactamente lo que protege a los folios.

---

## 4. Borrador permisivo, Enviar estricto (`solicitudes/forms.py`)

Cada renglón de la tabla es un `PartidaAltaForm`. Todos juntos forman un **formset**: un conjunto de formularios iguales que Django numera `form-0-…`, `form-1-…`, etc. Por eso cada celda se llama, por ejemplo, `form-2-descripcion`.

**Primer nivel: lo inválido nunca se guarda.** Lo revisa cada campo:

- `CampoTextoSAP`: máximo 40 caracteres, y su método `to_python` normaliza antes de medir. "Óptimo" se convierte en "OPTIMO" y luego se cuenta.
- `anio_modelo`: entero entre 1900 y 2100. "20A4" da el error "Debe tener 4 dígitos".
- `centro`: solo los Centros autorizados del usuario (`queryset` que manda la vista).
- `clean()` del renglón: el grupo de compras debe pertenecer al Centro, y el Centro debe tener almacén predeterminado.
- `clean()` del formset: el número de partida no se repite.

Si algo de esto falla, **no se guarda nada**, ni siquiera como borrador.

**Segundo nivel: Enviar exige lo obligatorio.** `validar_para_envio()` recorre todos los renglones y marca **todos** los faltantes de una vez con "Obligatorio para enviar", como pide la Revisión 3. Los datos siguen en pantalla para corregirlos.

**Renglones vacíos:** un renglón donde solo está el número de partida se ignora (propiedad `vacio`), igual que en Excel una fila en blanco no cuenta.

---

## 5. Guardar y enviar (`solicitudes/servicios.py`)

- **`guardar_borrador`**: crea la solicitud si es nueva y **reemplaza** sus partidas por lo que hay en la tabla. Borrar está permitido porque un borrador nunca entró al flujo ("lo que nunca entró al flujo puede eliminarse").
- Las columnas automáticas se calculan **en el servidor**: Tipo de Material sale de la Categoría de valoración, y el Almacén es el predeterminado del Centro. El navegador también las muestra, pero solo como ayuda visual; nadie puede mandar un almacén distinto modificando la página.
- **`enviar`**: guarda, pide el folio, cambia la cabecera a EN_PROCESO y cada partida a EN_VALIDACION. Si quien envía tiene VAL_MAT, las partidas van directo a EN_DM. Además registra un `Evento` de ENVIO por partida (la bitácora de la Revisión 3, sección 15).

---

## 6. La tabla tipo Excel (`static/js/captura.js`)

1. **Pegado**: escucha el evento `paste`. Excel copia las celdas como texto: columnas separadas por tabulador (`\t`) y renglones por salto de línea (`\n`). El código parte el texto y llena desde la celda donde pegaste, hacia la derecha y hacia abajo. Si faltan renglones, los crea.
2. **Listas desplegables**: al pegar "MOTOR" en Ubicación busca la opción cuyo código o descripción coincide. Si no encuentra ninguna, pinta la celda en rojo.
3. **Agregar renglón**: copia la plantilla `<template id="fila-vacia">`, cambia `__prefix__` por el número de renglón y suma 1 a `form-TOTAL_FORMS`. Ese contador le dice a Django cuántos renglones leer; si no se actualizara, el servidor ignoraría los renglones nuevos.
4. **Columnas automáticas**: al cambiar el Centro muestra el CeBe y el Almacén, y propone el Grupo de compras predeterminado. Los datos vienen en `<script id="datos-automaticos">`, generado con el filtro `json_script`, que además los escapa por seguridad.
5. **Aviso al salir**: si cambiaste algo y no guardaste, el navegador pide confirmación (`beforeunload`).

Se usa **delegación de eventos**: se escucha en la tabla completa (`cuerpo.addEventListener`) en vez de en cada celda, así los renglones agregados después también funcionan.

---

## 7. El menú lateral (`core/menu.py`)

Es un *context processor*: Django lo ejecuta en cada página y su resultado llega a todas las plantillas. La lista `OPCIONES` dice qué roles ven cada opción. Las que aún no existen se ven como "próximamente". La intersección de conjuntos `roles & visibles_para` responde "¿el usuario tiene alguno de estos roles?".

---

## 8. Ejercicios

1. Envía una solicitud con 3 partidas y luego, en `psql`:
   ```sql
   SELECT s.folio, p.numero, p.estado, a.descripcion, a.almacen_id
   FROM solicitudes_solicitud s
   JOIN solicitudes_partida p ON p.solicitud_id = s.id
   JOIN solicitudes_detallealta a ON a.partida_id = p.id
   ORDER BY s.folio, p.numero;
   ```
   ¿Por qué `JOIN solicitudes_detallealta a ON a.partida_id = p.id` funciona aunque `DetalleAlta` no tenga columna `id`?
2. Consulta la bitácora: `SELECT tipo, estado_anterior, estado_nuevo, fecha FROM solicitudes_evento ORDER BY fecha;`
3. Entra con `validador` / `demo-webdm-2026`, envía una solicitud y revisa en qué estado quedan sus partidas. ¿Qué regla de la Revisión 3 lo explica?
4. Pega una descripción con acento y Ñ, por ejemplo "Piñón óptimo". ¿Cómo queda guardada? Revisa `solicitudes/normalizar.py`.

Respuesta de la 1: en `DetalleAlta`, la llave primaria **es** `partida_id` (`OneToOneField(…, primary_key=True)`).

---

## Siguiente: fase 3

Bandejas "Pendientes de mi atención" de VAL_MAT y DM con acciones en bloque (aprobar, devolver, cancelar con motivo), asignación de Código SAP, bitácora de sesiones y cambio obligatorio de contraseña.
