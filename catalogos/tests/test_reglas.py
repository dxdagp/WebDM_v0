"""Pruebas de las reglas que protege PostgreSQL en los catálogos.

Cada prueba intenta guardar algo prohibido y espera IntegrityError: el error
que lanza la BASE DE DATOS cuando una restricción se viola. Usamos
transaction.atomic() porque, después de un error, PostgreSQL invalida la
transacción en curso; el bloque atómico la aísla para que la prueba continúe.
"""

from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase

from catalogos.models import Almacen, Centro


class AlmacenTests(TestCase):
    def setUp(self):
        self.mttu = Centro.objects.create(codigo="MTTU", nombre="Centro MTTU", centro_beneficio="CEBE1")
        self.meix = Centro.objects.create(codigo="MEIX", nombre="Centro MEIX", centro_beneficio="CEBE2")

    def test_un_solo_predeterminado_por_centro(self):
        Almacen.objects.create(centro=self.mttu, codigo="RC01", predeterminado=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Almacen.objects.create(centro=self.mttu, codigo="RC02", predeterminado=True)

    def test_varios_no_predeterminados_si_se_permiten(self):
        Almacen.objects.create(centro=self.mttu, codigo="RC01", predeterminado=True)
        Almacen.objects.create(centro=self.mttu, codigo="RC02")
        Almacen.objects.create(centro=self.mttu, codigo="RC03")
        self.assertEqual(Almacen.objects.filter(centro=self.mttu).count(), 3)

    def test_mismo_codigo_en_otro_centro_si_se_permite(self):
        Almacen.objects.create(centro=self.mttu, codigo="RC01", predeterminado=True)
        Almacen.objects.create(centro=self.meix, codigo="RC01", predeterminado=True)

    def test_codigo_repetido_en_el_mismo_centro_no(self):
        Almacen.objects.create(centro=self.mttu, codigo="RC01")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Almacen.objects.create(centro=self.mttu, codigo="RC01")


class RolesTests(TestCase):
    def test_la_migracion_crea_los_cuatro_roles(self):
        nombres = set(Group.objects.values_list("name", flat=True))
        self.assertTrue({"SOL_MAT", "VAL_MAT", "DM", "ADMIN"} <= nombres)
