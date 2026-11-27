"""Pruebas del generador de folios, incluida la de dos envíos simultáneos."""

import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase

from solicitudes.folios import formatear_folio, siguiente_folio
from solicitudes.normalizar import texto_sap


class FolioTests(TestCase):
    def test_formato(self):
        self.assertEqual(formatear_folio("AMAT_ZRA", 2026, 7), "AMAT_ZRA-2026-000007")

    def test_consecutivo_por_flujo_y_anio(self):
        self.assertEqual(siguiente_folio("AMAT_ZRA", 2026), "AMAT_ZRA-2026-000001")
        self.assertEqual(siguiente_folio("AMAT_ZRA", 2026), "AMAT_ZRA-2026-000002")
        # Otro flujo lleva su propio consecutivo…
        self.assertEqual(siguiente_folio("AMPL_ZRA", 2026), "AMPL_ZRA-2026-000001")
        # …y el año nuevo reinicia en 1.
        self.assertEqual(siguiente_folio("AMAT_ZRA", 2027), "AMAT_ZRA-2027-000001")


class FolioConcurrenteTests(TransactionTestCase):
    """TransactionTestCase usa transacciones reales, necesarias para probar bloqueos entre hilos."""

    def test_veinte_envios_simultaneos_no_repiten_folio(self):
        folios, barrera = [], threading.Barrier(20)

        def enviar():
            barrera.wait()  # los 20 hilos arrancan al mismo tiempo
            try:
                folios.append(siguiente_folio("AMAT_ZRA", 2026))
            finally:
                connection.close()  # cada hilo abre su propia conexión a PostgreSQL

        hilos = [threading.Thread(target=enviar) for _ in range(20)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(len(set(folios)), 20)
        self.assertEqual(max(folios), "AMAT_ZRA-2026-000020")


class NormalizarTests(TestCase):
    def test_mayusculas_sin_acentos_y_espacios(self):
        self.assertEqual(texto_sap("  Filtro de  aire óptimo "), "FILTRO DE AIRE OPTIMO")

    def test_conserva_la_enie(self):
        self.assertEqual(texto_sap("Piñón"), "PIÑON")
