"""Pruebas de las reglas de base de datos en catálogo SAP y solicitudes."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import Centro
from solicitudes.models import Flujo, ImagenPartida, Partida, Solicitud


class ReglasTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="ana", password="clave-segura-123")
        self.mttu = Centro.objects.create(codigo="MTTU", nombre="Centro MTTU", centro_beneficio="CEBE1")

    def nuevo_material(self, codigo):
        return MaterialSAP.objects.create(
            codigo=codigo, descripcion="FILTRO DE AIRE", tipo_material="ZRA",
            origen=MaterialSAP.Origen.IMPORT, creado_por=self.usuario,
        )

    def test_codigo_sap_debe_tener_6_digitos(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.nuevo_material("12345A")

    def test_codigo_sap_mas_centro_no_se_repite(self):
        material = self.nuevo_material("123456")
        MaterialCentro.objects.create(material=material, centro=self.mttu)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaterialCentro.objects.create(material=material, centro=self.mttu)

    def test_varios_borradores_sin_folio_conviven(self):
        Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario)
        Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario)
        self.assertEqual(Solicitud.objects.filter(folio__isnull=True).count(), 2)

    def test_folio_repetido_no(self):
        Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario, folio="AMAT_ZRA-2026-000001")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario, folio="AMAT_ZRA-2026-000001")

    def test_numero_de_partida_unico_en_la_solicitud(self):
        solicitud = Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario)
        Partida.objects.create(solicitud=solicitud, numero=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Partida.objects.create(solicitud=solicitud, numero=10)

    def test_no_hay_cuarta_imagen(self):
        solicitud = Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=self.usuario)
        partida = Partida.objects.create(solicitud=solicitud, numero=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImagenPartida.objects.create(partida=partida, orden=4, archivo="x.webp", subida_por=self.usuario)


class AdminTests(TestCase):
    """Prueba de humo: cada lista del panel abre sin error para un superusuario."""

    def test_paginas_del_admin(self):
        admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "clave-segura-123")
        self.client.force_login(admin)
        for url in [
            "admin:usuarios_usuario_changelist", "admin:usuarios_bitacorasesion_changelist",
            "admin:catalogos_centro_changelist", "admin:catalogos_almacen_changelist",
            "admin:catalogos_categoriavaloracion_changelist", "admin:catalogo_sap_materialsap_changelist",
            "admin:catalogo_sap_importacion_changelist", "admin:solicitudes_solicitud_changelist",
            "admin:solicitudes_partida_changelist", "admin:catalogos_centro_add",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(url)).status_code, 200)
