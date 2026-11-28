"""Fase 4f: vencimientos de 15/30 días naturales desde la última devolución (Dave, 28-nov-2026)."""

from datetime import date, datetime, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from solicitudes import vencimientos
from solicitudes.models import DetalleAlta, Evento, Partida, Solicitud

from .datos import crear_catalogos, crear_usuario

E = Partida.Estado
HOY = date(2026, 12, 31)


def local(d, h=12, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)))


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])

    def solicitud(self, flujo="AMAT_ZRA", *partidas):
        """partidas = [(estado, días desde la devolución o None)]."""
        s = Solicitud.objects.create(flujo=flujo, folio=f"{flujo}-2026-{Solicitud.objects.count() + 1:06d}",
                                     solicitante=self.sol, estado=Solicitud.Estado.EN_PROCESO)
        for i, (estado, dias) in enumerate(partidas, start=1):
            Partida.objects.create(solicitud=s, numero=10 * i, estado=estado, centro=self.c["mttu"],
                                   ultima_devolucion=local(HOY - timedelta(days=dias)) if dias is not None else None)
        return s


class ReglasTests(Base):
    def test_dias_naturales_por_fecha_local(self):
        p = Partida(estado=E.DEVUELTA_SOL, ultima_devolucion=local(HOY - timedelta(days=1), 23, 59))
        self.assertEqual(vencimientos.dias_desde_devolucion(p, HOY), 1)  # un minuto antes de medianoche ya cuenta 1 día
        self.assertIsNone(vencimientos.dias_desde_devolucion(Partida(estado=E.EN_DM, ultima_devolucion=p.ultima_devolucion), HOY))

    def test_aviso_y_vencida(self):
        def v(dias):
            return vencimientos.estado_vencimiento(Partida(estado=E.DEVUELTA_SOL, ultima_devolucion=local(HOY - timedelta(days=dias))), HOY)
        self.assertEqual(v(14), {"dias": 14, "vencida": False, "faltan": 1})
        self.assertEqual(v(15), {"dias": 15, "vencida": True, "faltan": 15})
        self.assertEqual(v(29), {"dias": 29, "vencida": True, "faltan": 1})


class JobTests(Base):
    def test_cancela_al_dia_30_en_los_4_flujos(self):
        cancelan = [self.solicitud(f, (E.DEVUELTA_SOL, 30)) for f in ("AMAT_ZRA", "AMPL_ZRA", "MOD_ZRA", "ASER_ZSA")]
        queda = self.solicitud("AMAT_ZRA", (E.DEVUELTA_SOL, 29), (E.EN_DM, 90))
        canceladas = vencimientos.cancelar_vencidas(HOY)
        self.assertEqual(len(canceladas), 4)
        for s in cancelan:
            p = s.partidas.get()
            self.assertEqual(p.estado, E.CANCELADA)
            e = Evento.objects.get(partida=p, tipo=Evento.Tipo.VENCIMIENTO)
            self.assertEqual((e.usuario, e.motivo, e.estado_anterior, e.detalle), (None, "CANCELADA POR VENCIMIENTO", E.DEVUELTA_SOL, {"dias": 30}))
            s.refresh_from_db()
            self.assertEqual(s.estado, Solicitud.Estado.TERMINADA)  # todas sus partidas en estado final
        self.assertEqual(sorted(queda.partidas.values_list("estado", flat=True)), [E.DEVUELTA_SOL, E.EN_DM])
        queda.refresh_from_db()
        self.assertEqual(queda.estado, Solicitud.Estado.EN_PROCESO)

    def test_atrasados_y_no_repite(self):
        self.solicitud("AMAT_ZRA", (E.DEVUELTA_SOL, 45))  # el job no corrió unos días
        self.assertEqual(len(vencimientos.cancelar_vencidas(HOY)), 1)
        self.assertEqual(len(vencimientos.cancelar_vencidas(HOY)), 0)

    def test_nueva_devolucion_reinicia(self):
        s = self.solicitud("AMAT_ZRA", (E.DEVUELTA_SOL, 40))
        s.partidas.update(ultima_devolucion=local(HOY - timedelta(days=3)))  # la devolvieron otra vez
        self.assertEqual(len(vencimientos.cancelar_vencidas(HOY)), 0)

    def test_comando_simular_y_fecha(self):
        s = self.solicitud("AMAT_ZRA", (E.DEVUELTA_SOL, 30))
        out = StringIO()
        call_command("vencimientos", "--simular", "--fecha", HOY.isoformat(), stdout=out)
        self.assertIn("1 partida(s) se cancelarían", out.getvalue())
        self.assertEqual(s.partidas.get().estado, E.DEVUELTA_SOL)
        call_command("vencimientos", "--fecha", HOY.isoformat(), stdout=out)
        self.assertIn("1 partida(s) canceladas por vencimiento", out.getvalue())
        self.assertEqual(s.partidas.get().estado, E.CANCELADA)


class PantallasTests(Base):
    def test_indicadores(self):
        hoy = timezone.localdate()
        s = Solicitud.objects.create(flujo="AMAT_ZRA", folio="AMAT_ZRA-2026-000099", solicitante=self.sol, estado=Solicitud.Estado.EN_PROCESO)
        vencida = Partida.objects.create(solicitud=s, numero=10, estado=E.DEVUELTA_SOL, centro=self.c["mttu"], ultima_devolucion=local(hoy - timedelta(days=20)))
        Partida.objects.create(solicitud=s, numero=20, estado=E.DEVUELTA_SOL, centro=self.c["mttu"], ultima_devolucion=local(hoy - timedelta(days=5)))
        DetalleAlta.objects.create(partida=vencida, descripcion="FILTRO")
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:mis_solicitudes"))
        self.assertContains(r, "1 vencida(s)")
        r = self.client.get(reverse("solicitudes:detalle", args=[s.pk]))
        self.assertContains(r, "VENCIDA · se cancela en 10 día(s)")
        self.assertContains(r, "Vence en 10 día(s)")
        r = self.client.get(reverse("solicitudes:pendientes"), {"tab": "sol"})
        self.assertContains(r, "VENCIDA · se cancela en 10 día(s)")
        r = self.client.get(reverse("solicitudes:partida", args=[vencida.pk]))
        self.assertContains(r, "VENCIDA")
