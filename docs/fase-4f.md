# Fase 4f: vencimientos de 15/30 días

Esto sale de la Revisión 3 (sección 11) y de las respuestas de Dave del 28-nov-2026.

| Decisión | Cómo quedó |
| --- | --- |
| A qué aplica | A las partidas **devueltas al solicitante** (DEVUELTA_SOL) de los **4 flujos**: AMAT, AMPL, MOD y ASER. |
| Desde cuándo | Desde la **devolución más reciente** (`Partida.ultima_devolucion`). Cada devolución nueva reinicia la cuenta en cero. |
| Cómo se cuenta | **Días naturales**, por fecha y en la hora de México (`TIME_ZONE`). Una devolución del lunes a las 23:59 ya cuenta 1 día el martes. |
| Día 15 | Aparece el indicador rojo **VENCIDA · se cancela en N día(s)**. No es un estado nuevo: la partida sigue DEVUELTA_SOL. Antes del día 15 se ve "Vence en N día(s)". |
| Día 30 | El job la pasa a **CANCELADA** con el motivo "CANCELADA POR VENCIMIENTO". En la bitácora el usuario aparece como "Sistema". Si todas las partidas de la solicitud quedan en un estado final, la cabecera pasa a TERMINADA. |
| Job | `python manage.py vencimientos`, todos los días a la **1:00 AM**. Si un día no corre, al día siguiente cancela todo lo atrasado. |

El indicador aparece en cuatro lugares:

- **Mis solicitudes:** "N vencida(s)" junto al estado de la solicitud.
- **Detalle:** junto al estado de cada partida.
- **Ficha de la partida:** junto al estado, en el título.
- **Pendientes → Por corregir:** en la columna "En espera desde".

## 1. Probarlo en tu máquina (Windows)

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git fetch origin
git checkout fase-4f
git pull
python manage.py test                      # no hay migraciones en esta fase
python manage.py vencimientos --simular    # lista lo que cancelaría hoy, sin cambiar nada
```

Para ver el indicador sin esperar 15 días:

1. Como `validador`, devuelve una partida al solicitante.
2. Cambia la fecha de la devolución en `psql` (Administración es de solo lectura para partidas):

   ```sql
   UPDATE solicitudes_partida SET ultima_devolucion = now() - interval '20 days' WHERE id = <id>;
   ```

3. Entra como `solicitante`. En Mis solicitudes, en el detalle y en la ficha de la partida aparece **VENCIDA · se cancela en 10 día(s)**.
4. Corre el job como si hoy fuera dentro de 10 días. Usa una fecha 10 días después de hoy:

   ```powershell
   python manage.py vencimientos --simular --fecha 2026-12-08
   python manage.py vencimientos --fecha 2026-12-08
   ```

   La partida queda CANCELADA, y en su bitácora aparece "Cancelada por vencimiento", con Sistema como usuario.

## 2. Programar el job

### Windows: Programador de tareas

`scripts\vencimientos.bat` se ubica en la carpeta del proyecto, corre el comando y guarda el resultado en `logs\vencimientos.log`. Para programarlo, ejecuta esto en PowerShell **como administrador**:

```powershell
schtasks /Create /TN "WebDM vencimientos" /SC DAILY /ST 01:00 /TR "C:\proyectos\WebDM_v0\scripts\vencimientos.bat" /RU SYSTEM
schtasks /Run /TN "WebDM vencimientos"     # probarlo ahora
Get-Content C:\proyectos\WebDM_v0\logs\vencimientos.log -Tail 5
```

- `/RU SYSTEM` hace que la tarea corra aunque no haya una sesión abierta. La computadora sí tiene que estar encendida a la 1:00 AM. Si está apagada, el job cancela lo atrasado la siguiente vez que corra.
- Para borrar la tarea: `schtasks /Delete /TN "WebDM vencimientos" /F`.

### Ubuntu: cron (cuando migres)

```bash
chmod +x /srv/webdm/scripts/vencimientos.sh
crontab -e
# agrega esta línea (minuto hora día mes día-semana):
0 1 * * * /srv/webdm/scripts/vencimientos.sh
```

cron usa la hora del servidor. Revísala con `timedatectl`, y si hace falta cámbiala con `sudo timedatectl set-timezone America/Mexico_City`.

## 3. El código

- `solicitudes/vencimientos.py` concentra todas las reglas:
  - `dias_desde_devolucion(partida)`: los días naturales desde la última devolución. Da `None` si la partida no está devuelta.
  - `estado_vencimiento(partida)`: lo que muestran las pantallas, `{"dias", "vencida", "faltan"}`.
  - `por_cancelar(fecha)`: el queryset de las partidas que ya cumplieron 30 días.
  - `cancelar_vencidas(fecha)`: las cancela en una sola transacción, con `select_for_update`. Así, si el solicitante reenvía justo en ese momento, el job espera; cuando la partida ya no está DEVUELTA_SOL, no la toca.
- `solicitudes/management/commands/vencimientos.py` es el comando, con las opciones `--simular` y `--fecha`.
- `solicitudes/templatetags/vencimientos.py` tiene `{% aviso_vencimiento p %}` y `{% vencidas_de solicitud %}`, que se usan en las plantillas con `{% load vencimientos %}`.
- Los 15 y 30 días se pueden cambiar en `config/settings.py` con `VENCIMIENTO_DIAS_AVISO` y `VENCIMIENTO_DIAS_CANCELA`. Si no los defines, valen 15 y 30.

### El cálculo de "día 30" en SQL

"Cumplió 30 días" quiere decir que la fecha de la devolución es igual o anterior a hoy − 30. Para que PostgreSQL pueda usar un índice, la condición se escribe como "antes del inicio del día (hoy − 29)":

```sql
SELECT id FROM solicitudes_partida
WHERE estado = 'DEVUELTA_SOL'
  AND ultima_devolucion < '2026-11-30 00:00:00-06:00'   -- hoy = 2026-12-29
FOR UPDATE OF solicitudes_partida;

UPDATE solicitudes_partida SET estado = 'CANCELADA', actualizada = now() WHERE id = <id>;
INSERT INTO solicitudes_evento (solicitud_id, partida_id, usuario_id, tipo, estado_anterior, estado_nuevo, motivo, detalle, fecha)
VALUES (<sol>, <id>, NULL, 'VENCIMIENTO', 'DEVUELTA_SOL', 'CANCELADA', 'CANCELADA POR VENCIMIENTO', '{"dias": 30}', now());
```

`usuario_id NULL` quiere decir que lo hizo el sistema, y la bitácora lo muestra como "Sistema".

## 4. Ejercicios en `psql`

```sql
-- Partidas devueltas y sus días (naturales, hora de México)
SELECT s.folio, p.numero, (current_date - (p.ultima_devolucion AT TIME ZONE 'America/Mexico_City')::date) AS dias
FROM solicitudes_partida p JOIN solicitudes_solicitud s ON s.id = p.solicitud_id
WHERE p.estado = 'DEVUELTA_SOL' ORDER BY dias DESC;

-- Canceladas por vencimiento
SELECT s.folio, p.numero, e.fecha FROM solicitudes_evento e
JOIN solicitudes_partida p ON p.id = e.partida_id JOIN solicitudes_solicitud s ON s.id = e.solicitud_id
WHERE e.tipo = 'VENCIMIENTO' ORDER BY e.fecha DESC;
```

## 5. Pruebas

`solicitudes/tests/test_vencimientos.py` tiene 7 pruebas:

- Días naturales por fecha local.
- Aviso y VENCIDA: días 14, 15 y 29.
- Cancelación al día 30 en los 4 flujos, con su evento y la cabecera; la de 29 días no se toca.
- Atrasados, y que no repite.
- Una devolución nueva reinicia la cuenta.
- El comando con `--simular` y `--fecha`.
- Los indicadores en las 4 pantallas.

En total pasan 191 pruebas.

## 6. Lo que sigue

Con esto queda completa la fase 4. Lo que sigue es la fase 5, el despliegue en Ubuntu: nginx con `client_max_body_size 0` y el cron de este job.
