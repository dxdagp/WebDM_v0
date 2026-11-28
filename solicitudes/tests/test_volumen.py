"""Pedido de Dave: capturas grandes (él intentó 1,194 partidas). Tope: settings.MAX_PARTIDAS."""

import time

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialCentro, MaterialSAP
from solicitudes.models import Partida, Solicitud

from .datos import crear_catalogos, crear_usuario

N = 1200


class VolumenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"], cls.c["meix"]])
        materiales = MaterialSAP.objects.bulk_create(
            [MaterialSAP(codigo=f"{400000 + i}", descripcion=f"PIEZA {i}", tipo_material="ZRA", origen="IMPORT",
                         creado_por=cls.sol) for i in range(N)])
        MaterialCentro.objects.bulk_create([MaterialCentro(material=m, centro=cls.c["mttu"]) for m in materiales])

    def post(self, url, accion, filas):
        datos = {"form-TOTAL_FORMS": str(len(filas)), "form-INITIAL_FORMS": "0", "accion": accion}
        for i, fila in enumerate(filas):
            datos.update({f"form-{i}-{k}": v for k, v in fila.items()})
        self.client.force_login(self.sol)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        inicio = time.perf_counter()
        with CaptureQueriesContext(connection) as q:
            r = self.client.post(url, datos)
        medio = time.perf_counter()
        # Guardar inserta cada partida y su detalle; lo que no debe crecer por renglón son los catálogos.
        self.assertLess(len(q), 5 * len(filas) + 100)
        if r.status_code == 302:
            with CaptureQueriesContext(connection) as q:
                r = self.client.get(r.url)
            self.assertLess(len(q), 100)  # dibujar la tabla: consultas fijas, no una por renglón
        return r, time.perf_counter() - inicio

    def test_ampliacion_de_1200_partidas(self):
        filas = [{"numero": 10 * (i + 1), "codigo_sap": f"{400000 + i}", "centro": self.c["meix"].pk} for i in range(N)]
        r, segundos = self.post(reverse("solicitudes:nueva_ampl"), "guardar", filas)
        self.assertContains(r, "Borrador guardado")
        self.assertEqual(Partida.objects.count(), N)

    def test_alta_de_1200_partidas(self):
        filas = [{"numero": 10 * (i + 1), "centro": self.c["mttu"].pk, "descripcion": f"FILTRO {i}"} for i in range(N)]
        r, segundos = self.post(reverse("solicitudes:nueva_amat"), "guardar", filas)
        self.assertContains(r, "Borrador guardado")
        self.assertEqual(Solicitud.objects.get().partidas.count(), N)

    def test_mas_del_maximo_marca_error(self):
        filas = [{"numero": 10 * (i + 1), "centro": self.c["mttu"].pk, "descripcion": "X"} for i in range(settings.MAX_PARTIDAS + 1)]
        r, _ = self.post(reverse("solicitudes:nueva_amat"), "guardar", filas)
        self.assertContains(r, f"Máximo {settings.MAX_PARTIDAS} partidas por solicitud")
        self.assertFalse(Solicitud.objects.exists())
