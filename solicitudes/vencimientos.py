"""Vencimientos de partidas devueltas al solicitante (Revisión 3, sección 11; fase 4f).

Reglas (Dave, 28-nov-2026):
- Aplican a las partidas DEVUELTA_SOL de los 4 flujos (AMAT, AMPL, MOD y ASER).
- Se cuentan DÍAS NATURALES (de calendario) desde la devolución más reciente
  (Partida.ultima_devolucion). Cada devolución nueva reinicia la cuenta.
- Desde el día 15: indicador VENCIDA. No es un estado: la partida sigue DEVUELTA_SOL.
- Día 30: el job diario (python manage.py vencimientos, a la 1:00 AM) la cancela con el motivo
  del sistema "CANCELADA POR VENCIMIENTO".

"Día N" se cuenta por fecha, en la zona horaria de WebDM (TIME_ZONE), no por horas:
una devolución del lunes a las 23:59 cumple 1 día el martes a las 00:00.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Evento, Partida

E = Partida.Estado
DIAS_AVISO = getattr(settings, "VENCIMIENTO_DIAS_AVISO", 15)
DIAS_CANCELA = getattr(settings, "VENCIMIENTO_DIAS_CANCELA", 30)
MOTIVO = "CANCELADA POR VENCIMIENTO"


def hoy():
    return timezone.localdate()


def dias_desde_devolucion(partida, fecha=None):
    """Días naturales desde la última devolución, o None si no aplica (no está devuelta)."""
    if partida.estado != E.DEVUELTA_SOL or partida.ultima_devolucion is None:
        return None
    return ((fecha or hoy()) - timezone.localdate(partida.ultima_devolucion)).days


def estado_vencimiento(partida, fecha=None):
    """Lo que muestran las pantallas: None, o {"dias", "vencida", "faltan"}.

    faltan = días para el aviso (antes del 15) o para la cancelación (desde el 15).
    """
    dias = dias_desde_devolucion(partida, fecha)
    if dias is None:
        return None
    vencida = dias >= DIAS_AVISO
    return {"dias": dias, "vencida": vencida,
            "faltan": max((DIAS_CANCELA if vencida else DIAS_AVISO) - dias, 0)}


def _inicio_del_dia(fecha):
    return timezone.make_aware(datetime.combine(fecha, time.min))


def por_cancelar(fecha=None):
    """Partidas devueltas que ya cumplieron DIAS_CANCELA días.

    dias >= 30  ⇔  fecha de devolución <= hoy - 30  ⇔  ultima_devolucion < inicio del día (hoy - 29).
    SQL:  SELECT ... FROM solicitudes_partida
          WHERE estado = 'DEVUELTA_SOL' AND ultima_devolucion < '<hoy-29> 00:00 (hora local)'
    """
    limite = _inicio_del_dia((fecha or hoy()) - timedelta(days=DIAS_CANCELA - 1))
    return Partida.objects.filter(estado=E.DEVUELTA_SOL, ultima_devolucion__lt=limite)


@transaction.atomic
def cancelar_vencidas(fecha=None):
    """Cancela las partidas que cumplieron 30 días. Devuelve la lista de partidas canceladas.

    Si el job no corrió algún día, al siguiente cancela todo lo atrasado (usa <, no =).
    Si un solicitante reenvía al mismo tiempo, select_for_update espera a que termine;
    luego la partida ya no está DEVUELTA_SOL y no se toca (por eso se vuelve a filtrar el estado).
    """
    from .flujo import actualizar_cabecera  # flujo importa modelos; evitar import circular

    partidas = list(por_cancelar(fecha).select_for_update(of=("self",)).select_related("solicitud").order_by("pk"))
    for p in partidas:
        dias = dias_desde_devolucion(p, fecha)  # antes de cambiar el estado
        p.estado = E.CANCELADA
        p.save(update_fields=["estado", "actualizada"])
        Evento.objects.create(
            solicitud=p.solicitud, partida=p, usuario=None, tipo=Evento.Tipo.VENCIMIENTO,
            estado_anterior=E.DEVUELTA_SOL, estado_nuevo=E.CANCELADA, motivo=MOTIVO,
            detalle={"dias": dias},
        )
    for solicitud in {p.solicitud for p in partidas}:
        actualizar_cabecera(solicitud, None)  # usuario None = el sistema
    return partidas
