"""Generación de folios: AMAT_ZRA-2026-000001 (Revisión 3, sección 16).

El problema: si dos personas envían al mismo tiempo, ambas podrían leer
"último = 41" y las dos tomar el 42. Folio duplicado.

La solución usa UNA sola sentencia SQL que PostgreSQL ejecuta de forma
atómica (de un jalón, sin que nadie se meta a la mitad):

    INSERT INTO solicitudes_contadorfolio (flujo, anio, ultimo)
    VALUES ('AMAT_ZRA', 2026, 1)
    ON CONFLICT (flujo, anio)
    DO UPDATE SET ultimo = solicitudes_contadorfolio.ultimo + 1
    RETURNING ultimo;

- Si es el primer folio del año, no existe la fila: la INSERTA con 1.
- Si ya existe, choca con la restricción UNIQUE (flujo, anio) y en lugar de
  fallar hace el UPDATE: suma 1.
- RETURNING devuelve el número resultante.
- Mientras una transacción tiene esa fila modificada, PostgreSQL BLOQUEA la
  fila: la segunda persona espera unos milisegundos y recibe el siguiente.

Importante: esta función debe llamarse DENTRO de la misma transacción que
guarda la solicitud. Si el envío falla y se revierte, el contador también se
revierte, así que no quedan huecos en la numeración.
"""

from django.db import connection
from django.utils import timezone

from .models import ContadorFolio

SQL_SIGUIENTE = f"""
    INSERT INTO {ContadorFolio._meta.db_table} (flujo, anio, ultimo)
    VALUES (%s, %s, 1)
    ON CONFLICT (flujo, anio)
    DO UPDATE SET ultimo = {ContadorFolio._meta.db_table}.ultimo + 1
    RETURNING ultimo
"""


def formatear_folio(flujo, anio, numero):
    """('AMAT_ZRA', 2026, 7) -> 'AMAT_ZRA-2026-000007'. `:06d` rellena con ceros a 6 dígitos."""
    return f"{flujo}-{anio}-{numero:06d}"


def siguiente_folio(flujo, anio=None):
    """Reserva y devuelve el siguiente folio del flujo para el año dado (por defecto, el actual)."""
    anio = anio or timezone.localdate().year
    # Los %s NO se sustituyen con f-strings: se pasan aparte para que el
    # conector (psycopg) los escape. Así se evita la inyección de SQL.
    with connection.cursor() as cursor:
        cursor.execute(SQL_SIGUIENTE, [flujo, anio])
        (numero,) = cursor.fetchone()
    return formatear_folio(flujo, anio, numero)
