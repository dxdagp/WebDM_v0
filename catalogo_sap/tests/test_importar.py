"""Fase 4b: importación del catálogo SAP (Revisión 3, sección 12 y 17.1)."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalogo_sap.importar import ArchivoInvalido, importar
from catalogo_sap.models import Importacion, MaterialCentro, MaterialSAP
from solicitudes.tests.datos import crear_catalogos, crear_usuario

ENCABEZADOS = "CODIGO_SAP\tDESCRIPCION\tCENTRO\tTIPO_MATERIAL\tUMB\tNO_PARTE_ORIGINAL\tOTRA"


def txt(*renglones, encabezados=ENCABEZADOS, codificacion="utf-8"):
    return BytesIO("\n".join([encabezados, *renglones]).encode(codificacion))


class ImportarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()  # Centros MTTU y MEIX
        cls.dm = crear_usuario("dm", "DM")

    def importa(self, *renglones, catalogo="MATERIALES", **kw):
        return importar(txt(*renglones, **kw), "sap.txt", self.dm, catalogo)

    def errores(self, imp):
        return list(imp.detalle_errores.values_list("linea", "mensaje"))

    def test_un_codigo_en_dos_centros(self):
        imp = self.importa("123456\tFiltro de aire\tMTTU\tZRA\tPZA\tFA-1\tx", "123456\tFiltro de aire\tMEIX\tZRA\tPZA\tFA-1\tx")
        self.assertEqual((imp.importados, imp.errores), (2, 0))
        m = MaterialSAP.objects.get()
        self.assertEqual((m.descripcion, m.origen, m.importacion, m.es_servicio), ("FILTRO DE AIRE", "IMPORT", imp, False))
        self.assertEqual(sorted(m.centros.values_list("centro__codigo", flat=True)), ["MEIX", "MTTU"])

    def test_buenos_entran_aunque_otros_fallen(self):
        imp = self.importa(
            "123456\tFILTRO\tMTTU\tZRA\tPZA\t\t",
            "12345\tCORTO\tMTTU\tZRA\tPZA\t\t",          # 5 dígitos
            "222222\tBALATA\tXXXX\tZRA\tPZA\t\t",         # Centro inexistente
            "333333\t\tMTTU\tZRA\tPZA\t\t",               # sin descripción
            "123456\tFILTRO\tMTTU\tZRA\tPZA\t\t",         # Código + Centro repetido
            "444444\t" + "X" * 41 + "\tMTTU\tZRA\tPZA\t\t",  # 41 caracteres
            "",                                            # renglón en blanco: se ignora
        )
        self.assertEqual((imp.importados, imp.errores), (1, 5))
        mensajes = dict(self.errores(imp))
        self.assertIn("6 dígitos", mensajes[3])
        self.assertIn("no existe", mensajes[4])
        self.assertIn("DESCRIPCION", mensajes[5])
        self.assertIn("línea 2", mensajes[6])
        self.assertIn("41 caracteres", mensajes[7])

    def test_descripcion_distinta_no_sube_ninguno(self):
        imp = self.importa("123456\tFILTRO AIRE\tMTTU\tZRA\tPZA\t\t", "123456\tFILTRO ACEITE\tMEIX\tZRA\tPZA\t\t")
        self.assertEqual((imp.importados, imp.errores), (0, 2))
        self.assertFalse(MaterialSAP.objects.exists())

    def test_codigo_que_ya_existia_es_error(self):
        self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t")
        imp = self.importa("123456\tFILTRO\tMEIX\tZRA\tPZA\t\t")  # otro Centro: eso es AMPL_ZRA
        self.assertEqual((imp.importados, imp.errores), (0, 1))
        self.assertEqual(MaterialCentro.objects.count(), 1)

    def test_servicios_es_otro_catalogo(self):
        imp = self.importa("555555\tMANO DE OBRA\tMTTU\tZSA\tSER\t\t", "666666\tREVISION\tMTTU\tZRA\tSER\t\t",
                           catalogo="SERVICIOS")
        self.assertEqual(imp.importados, 2)
        self.assertEqual(MaterialSAP.objects.filter(es_servicio=True).count(), 2)
        # Un ZSA en el catálogo de materiales es error.
        imp = self.importa("777777\tMANO DE OBRA\tMTTU\tZSA\tSER\t\t")
        self.assertIn("catálogo de servicios", self.errores(imp)[0][1])

    def test_mismo_codigo_en_materiales_y_servicios(self):
        # Dave: son catálogos independientes; para SAP son items diferentes.
        self.importa("500001\tACUMULADOR\tMTTU\tZRA\tPZA\t\t")
        imp = self.importa("500001\tSERVICIO DE MUELLES\tMTTU\tZRA\tSER\t\t", catalogo="SERVICIOS")
        self.assertEqual((imp.importados, imp.errores), (1, 0))
        self.assertEqual(MaterialSAP.objects.filter(codigo="500001").count(), 2)
        # Pero dentro del mismo catálogo sigue siendo único.
        imp = self.importa("500001\tOTRO SERVICIO\tMEIX\tZRA\tSER\t\t", catalogo="SERVICIOS")
        self.assertEqual(imp.errores, 1)

    def test_bom_y_columnas_en_otro_orden(self):
        datos = "﻿UMB\tCENTRO\tCODIGO_SAP\tTIPO_MATERIAL\tDESCRIPCION\nPZA\tMTTU\t123456\tZRA\tÑandú\n"
        imp = importar(BytesIO(datos.encode("utf-8")), "a.txt", self.dm)
        self.assertEqual(imp.importados, 1)
        self.assertEqual(MaterialSAP.objects.get().descripcion, "ÑANDU")

    def test_archivo_que_no_es_utf8_no_importa_nada(self):
        with self.assertRaisesMessage(ArchivoInvalido, "UTF-8"):
            self.importa("123456\tCAÑO\tMTTU\tZRA\tPZA\t\t", codificacion="latin-1")
        self.assertFalse(Importacion.objects.exists())

    def test_faltan_encabezados(self):
        with self.assertRaisesMessage(ArchivoInvalido, "UMB"):
            self.importa("123456\tFILTRO\tMTTU\tZRA", encabezados="CODIGO_SAP\tDESCRIPCION\tCENTRO\tTIPO_MATERIAL")


class PantallasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.dm = crear_usuario("dm", "DM")
        cls.sol = crear_usuario("sol", "SOL_MAT")

    def test_solo_admin_y_dm_importan(self):
        self.client.force_login(self.sol)
        self.assertEqual(self.client.get(reverse("catalogo_sap:importar")).status_code, 403)
        self.client.force_login(self.dm)
        archivo = SimpleUploadedFile("sap.txt", txt("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t").getvalue())
        r = self.client.post(reverse("catalogo_sap:importar"), {"catalogo": "MATERIALES", "archivo": archivo}, follow=True)
        self.assertContains(r, "1 renglón(es) importado(s), 0 con error")

    def test_consulta_separa_materiales_y_servicios(self):
        importar(txt("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t"), "m.txt", self.dm, "MATERIALES")
        importar(txt("555555\tMANO DE OBRA\tMTTU\tZSA\tSER\t\t"), "s.txt", self.dm, "SERVICIOS")
        self.client.force_login(self.sol)
        r = self.client.get(reverse("catalogo_sap:consulta"), {"q": ""})
        self.assertContains(r, "123456")
        self.assertNotContains(r, "555555")
        r = self.client.get(reverse("catalogo_sap:servicios"))
        self.assertContains(r, "555555")
        self.assertNotContains(r, "123456")
        r = self.client.get(reverse("catalogo_sap:consulta"), {"q": "filt", "centro": self.c["meix"].pk})
        self.assertNotContains(r, "123456")  # existe solo en MTTU
