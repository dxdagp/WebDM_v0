"""python manage.py vencimientos  — el job diario (1:00 AM) que cancela las partidas devueltas hace 30 días.

Opciones:
  --simular        solo muestra cuáles cancelaría, sin cambiar nada.
  --fecha AAAA-MM-DD  corre como si hoy fuera esa fecha (para pruebas).
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from solicitudes import vencimientos


class Command(BaseCommand):
    help = "Cancela las partidas devueltas al solicitante que cumplieron 30 días naturales."

    def add_arguments(self, parser):
        parser.add_argument("--simular", action="store_true", help="No cambia nada; solo lista.")
        parser.add_argument("--fecha", help="Fecha AAAA-MM-DD a usar como 'hoy'.")

    def handle(self, *args, simular=False, fecha=None, **opciones):
        try:
            dia = date.fromisoformat(fecha) if fecha else None
        except ValueError:
            raise CommandError("La fecha debe ser AAAA-MM-DD.")
        if simular:
            partidas = list(vencimientos.por_cancelar(dia).select_related("solicitud"))
        else:
            with transaction.atomic():
                partidas = vencimientos.cancelar_vencidas(dia)
        for p in partidas:
            self.stdout.write(f"  {p.solicitud.folio}/{p.numero} (devuelta el {p.ultima_devolucion:%d/%m/%Y})")
        verbo = "se cancelarían" if simular else "canceladas por vencimiento"
        self.stdout.write(self.style.SUCCESS(f"{len(partidas)} partida(s) {verbo}."))
