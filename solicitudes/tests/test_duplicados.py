"""Fase 4: búsqueda de duplicados contra el Catálogo SAP (Revisión 3, sección 8)."""

from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialSAP
from solicitudes import duplicados, flujo

from .datos import crear_catalogos, crear_enviada, crear_usuario


class BuscarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u = crear_usuario("u", "SOL_MAT")
        alta = dict(tipo_material="ZRA", umb="PZA", origen="IMPORT", creado_por=cls.u)
        MaterialSAP.objects.create(codigo="100001", descripcion="FILTRO DE AIRE", no_parte_original="ABC-1", **alta)
        MaterialSAP.objects.create(codigo="100002", descripcion="BALATA DELANTERA", no_parte_original="XYZ-9", **alta)
        MaterialSAP.objects.create(codigo="900001", descripcion="FILTRO DE AIRE", no_parte_original="ABC-1",
                                   es_servicio=True, **alta)  # los servicios no cuentan

    def tipos(self, descripcion, no_parte=""):
        return [(c.tipo, c.codigo) for c in duplicados.buscar(descripcion, no_parte)]

    def test_exacto_bloquea_aunque_cambien_mayusculas_y_acentos(self):
        # texto_sap normaliza: "Filtró de aire" → "FILTRO DE AIRE".
        self.assertEqual(self.tipos("Filtró de aire", "abc-1"), [("DUPLICADO", "100001")])
        self.assertEqual(duplicados.bloqueante("filtro de aire", "abc-1").codigo, "100001")

    def test_mismo_no_parte_es_advertencia(self):
        self.assertEqual(self.tipos("BALATA TRASERA", "ABC-1")[0], ("ADVERTENCIA", "100001"))

    def test_misma_descripcion_es_advertencia(self):
        self.assertEqual(self.tipos("FILTRO DE AIRE", "OTRO"), [("ADVERTENCIA", "100001")])

    def test_parecida_es_posible(self):
        self.assertEqual(self.tipos("FILTRO AIRE"), [("POSIBLE", "100001")])  # sin "DE": 100 %
        self.assertEqual(self.tipos("FILTRO DE AIRRE"), [("POSIBLE", "100001")])  # error de dedo
        self.assertEqual(self.tipos("FILTRO DE AIRE MOTOR"), [("POSIBLE", "100001")])  # 80 %

    def test_otra_palabra_no_es_parecida(self):
        # Pedido de Dave: ACEITE y AIRE son cosas distintas (50 %, debajo del 80 %).
        self.assertEqual(self.tipos("FILTRO DE ACEITE"), [])
        self.assertEqual(self.tipos("FILTRO HIDRAULICO"), [])
        self.assertEqual(duplicados.parecido("BALATA DELANTERA", "BALATA TRASERA"), 0.5)

    def test_endpoint_json(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("solicitudes:coincidencias"), {"descripcion": "filtro de aire", "no_parte": "ABC-1"})
        datos = r.json()["coincidencias"]
        self.assertEqual(datos[0]["codigo"], "100001")
        self.assertTrue(datos[0]["bloquea"])


class AprobarDuplicadoTests(TestCase):
    def test_validador_no_puede_aprobar_un_duplicado(self):
        c = crear_catalogos()
        sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        val = crear_usuario("val", "VAL_MAT", centros=[c["mttu"]])
        solicitud = crear_enviada(c, sol, n=1)  # descripción "FILTRO 0", No. Parte "ABC-0"
        MaterialSAP.objects.create(codigo="123456", descripcion="FILTRO 0", no_parte_original="ABC-0",
                                   tipo_material="ZRA", origen="IMPORT", creado_por=sol)
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "ya existe el código 123456"):
            flujo.aplicar(val, "aprobar", list(solicitud.partidas.values_list("pk", flat=True)))
