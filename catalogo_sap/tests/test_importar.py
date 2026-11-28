"""Fase 4b: importación del catálogo SAP (Revisión 3, sección 12 y 17.1)."""

from io import BytesIO, StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from catalogo_sap.importar import ArchivoInvalido, importar
from catalogo_sap.models import Importacion, MaterialCentro, MaterialSAP
from catalogos.models import UMB, GrupoArticulos, GrupoCompras, TipoMaterial
from solicitudes.tests.datos import crear_catalogos, crear_usuario

# Materiales: los renglones de prueba llevan CODIGO, DESCRIPCION, CENTRO, TIPO, UMB, NO_PARTE, OTRA;
# txt() les agrega al final GRUPO_COMPRAS, GRUPO_ARTICULOS, CATEGORIA_VALORACION y CEBE, válidos en WebDM
# (el CeBe es el del Centro del renglón: CEBE-MTTU, CEBE-MEIX).
ENCABEZADOS = ("CODIGO_SAP\tDESCRIPCION\tCENTRO\tTIPO_MATERIAL\tUMB\tNO_PARTE_ORIGINAL\tOTRA"
               "\tGRUPO_COMPRAS\tGRUPO_ARTICULOS\tCATEGORIA_VALORACION\tCEBE")
# Servicios: CODIGO, DESCRIPCION, TIPO, UMB; txt() agrega el GRUPO_ARTICULOS GA1.
ENCABEZADOS_SERVICIOS = "CODIGO_SAP\tDESCRIPCION\tTIPO_MATERIAL\tUMB\tGRUPO_ARTICULOS"


def con_extra(renglon):
    if renglon.count("\t") >= 10:  # ya trae sus propias columnas extra
        return renglon
    centro = renglon.split("\t")[2] if renglon.count("\t") >= 2 else ""
    return renglon + f"\tG01\tGA1\tCV1\tCEBE-{centro}"


def txt(*renglones, encabezados=ENCABEZADOS, codificacion="utf-8"):
    if encabezados == ENCABEZADOS:
        renglones = [con_extra(r) if r else r for r in renglones]
    elif encabezados == ENCABEZADOS_SERVICIOS:
        renglones = [r if r.count("\t") >= 4 else r + "\tGA1" for r in renglones]
    return BytesIO("\n".join([encabezados, *renglones]).encode(codificacion))


def catalogos_para_importar():
    c = crear_catalogos()  # Centros MTTU y MEIX, ZRA, PZA, GA1, CV1 (de ZRA), G01 en MTTU
    GrupoCompras.objects.create(centro=c["meix"], codigo="G01")
    UMB.objects.create(codigo="SER", descripcion="Servicio")
    TipoMaterial.objects.create(codigo="ZSA", descripcion="Servicios")
    GrupoArticulos.objects.create(codigo="GA2", descripcion="Balatas")
    return c


class ImportarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = catalogos_para_importar()
        cls.dm = crear_usuario("dm", "DM")

    def importa(self, *renglones, catalogo="MATERIALES", **kw):
        return importar(txt(*renglones, **kw), "sap.txt", self.dm, catalogo)

    def importa_servicios(self, *renglones):
        return importar(txt(*renglones, encabezados=ENCABEZADOS_SERVICIOS), "s.txt", self.dm, "SERVICIOS")

    def errores(self, imp):
        return list(imp.detalle_errores.values_list("linea", "mensaje"))

    def test_un_codigo_en_dos_centros(self):
        imp = self.importa("123456\tFiltro de aire\tMTTU\tZRA\tPZA\tFA-1\tx", "123456\tFiltro de aire\tMEIX\tZRA\tPZA\tFA-1\tx")
        self.assertEqual((imp.importados, imp.errores), (2, 0))
        m = MaterialSAP.objects.get()
        self.assertEqual((m.descripcion, m.origen, m.importacion, m.es_servicio), ("FILTRO DE AIRE", "IMPORT", imp, False))
        self.assertEqual(sorted(m.centros.values_list("centro__codigo", flat=True)), ["MEIX", "MTTU"])
        self.assertEqual(m.grupo_articulos, "GA1")
        mc = m.centros.get(centro__codigo="MTTU")
        self.assertEqual((mc.grupo_compras, mc.categoria_valoracion, mc.cebe), ("G01", "CV1", "CEBE-MTTU"))

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

    def test_material_y_centro_que_ya_existen_no_se_cargan(self):
        self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t")
        imp = self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t", "123456\tFILTRO\tMEIX\tZRA\tPZA\t\t")
        # MTTU ya estaba: error. MEIX es nuevo: se agrega al MISMO material.
        self.assertEqual((imp.importados, imp.errores), (1, 1))
        self.assertIn("ya existe en WebDM para el Centro MTTU", self.errores(imp)[0][1])
        m = MaterialSAP.objects.get()
        self.assertEqual(sorted(m.centros.values_list("centro__codigo", flat=True)), ["MEIX", "MTTU"])

    def test_material_existente_en_otro_centro_debe_coincidir(self):
        self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t")
        imp = self.importa("123456\tBALATA\tMEIX\tZRA\tPZA\t\t")
        self.assertIn("En WebDM el código 123456 es FILTRO", self.errores(imp)[0][1])
        imp = self.importa("123456\tFILTRO\tMEIX\tZRA\tPZA\t\t\tG01\tGA2\tCV1\tCEBE-MEIX")
        self.assertIn("grupo de artículos GA1", self.errores(imp)[0][1])
        self.assertEqual(MaterialCentro.objects.count(), 1)

    def test_grupo_de_articulos_distinto_no_sube_ninguno(self):
        imp = self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t", "123456\tFILTRO\tMEIX\tZRA\tPZA\t\t\tG01\tGA2\tCV1\tCEBE-MEIX")
        self.assertEqual((imp.importados, imp.errores), (0, 2))
        self.assertIn("grupos de artículos distintos", self.errores(imp)[0][1])
        imp = self.importa_servicios("555555\tMANO DE OBRA\tZSA\tSER\tGA1", "555555\tMANO DE OBRA\tZSA\tSER\tGA2")
        self.assertEqual((imp.importados, imp.errores), (0, 2))

    def test_valida_contra_los_catalogos_de_webdm(self):
        imp = self.importa(
            "111111\tA\tMTTU\tZRX\tCAJA\t\t\tG01\tGA9\tCV1\tCEBE-MTTU",  # tipo, UMB y grupo art. no existen
            "222222\tB\tMTTU\tZRA\tPZA\t\t\tG99\tGA1\tCV9\tCEBE-MTTU",   # grupo compras y categoría
            "333333\tC\tMTTU\tZRA\tPZA\t\t\tG01\tGA1\tCV1\tCEBE-MEIX",   # CeBe de otro Centro
            "444444\tD\tMTTU\tZRA\tPZA\t\t\tG01\tGA1\tCV1\tCEBE-MTTU",   # bueno
        )
        self.assertEqual((imp.importados, imp.errores), (1, 3))
        m = dict(self.errores(imp))
        self.assertIn("Tipo de material ZRX, UMB CAJA, Grupo de artículos GA9", m[2])
        self.assertIn("Categoría de valoración CV9 para ZRA, Grupo de compras G99 en MTTU", m[3])
        self.assertIn("El CeBe de MTTU es CEBE-MTTU, no CEBE-MEIX", m[4])
        imp = self.importa_servicios("555555\tMANO DE OBRA\tZSA\tHORA\tGA1")
        self.assertIn("UMB HORA", self.errores(imp)[0][1])

    def test_servicios_es_otro_catalogo(self):
        imp = self.importa_servicios("555555\tMANO DE OBRA\tZSA\tSER", "666666\tREVISION\tZRA\tSER",
                                     "666666\tREVISION\tZRA\tSER")  # repetido
        self.assertEqual((imp.importados, imp.errores), (2, 1))
        self.assertEqual(MaterialSAP.objects.filter(es_servicio=True).count(), 2)
        self.assertFalse(MaterialCentro.objects.exists())  # los servicios no dependen de un Centro
        # Un ZSA en el catálogo de materiales es error.
        imp = self.importa("777777\tMANO DE OBRA\tMTTU\tZSA\tSER\t\t")
        self.assertIn("catálogo de servicios", self.errores(imp)[0][1])

    def test_servicios_se_filtran_por_grupo_de_articulos(self):
        self.importa_servicios("555555\tMANO DE OBRA\tZSA\tSER\tGA1", "666666\tREVISION\tZRA\tSER\tGA2")
        u = crear_usuario("sol", "SOL_MAT")
        self.client.force_login(u)
        r = self.client.get(reverse("catalogo_sap:servicios"), {"grupo_articulos": "ga2"})
        self.assertEqual([m.codigo for m in r.context["pagina"]], ["666666"])

    def test_mismo_codigo_en_materiales_y_servicios(self):
        # Dave: son catálogos independientes; para SAP son items diferentes.
        self.importa("500001\tACUMULADOR\tMTTU\tZRA\tPZA\t\t")
        imp = self.importa_servicios("500001\tSERVICIO DE MUELLES\tZRA\tSER")
        self.assertEqual((imp.importados, imp.errores), (1, 0))
        self.assertEqual(MaterialSAP.objects.filter(codigo="500001").count(), 2)
        # Pero dentro del mismo catálogo sigue siendo único.
        imp = self.importa_servicios("500001\tOTRO SERVICIO\tZRA\tSER")
        self.assertEqual(imp.errores, 1)
        self.assertIn("ya existe en el catálogo de servicios", self.errores(imp)[0][1])

    def test_bom_y_columnas_en_otro_orden(self):
        datos = ("\ufeffUMB\tCEBE\tCENTRO\tCODIGO_SAP\tGRUPO_COMPRAS\tTIPO_MATERIAL\tGRUPO_ARTICULOS\tDESCRIPCION"
                 "\tCATEGORIA_VALORACION\nPZA\tCEBE-MTTU\tMTTU\t123456\tG01\tZRA\tGA1\tÑandú\tCV1\n")
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

    def test_materiales_exigen_grupos_categoria_y_cebe(self):
        with self.assertRaisesMessage(ArchivoInvalido, "GRUPO_COMPRAS"):
            self.importa("123456\tFILTRO\tMTTU\tZRA\tPZA", encabezados="CODIGO_SAP\tDESCRIPCION\tCENTRO\tTIPO_MATERIAL\tUMB")


class PantallasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = catalogos_para_importar()
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
        importar(txt("555555\tMANO DE OBRA\tZSA\tSER", encabezados=ENCABEZADOS_SERVICIOS), "s.txt", self.dm, "SERVICIOS")
        self.client.force_login(self.sol)
        r = self.client.get(reverse("catalogo_sap:consulta"))
        self.assertContains(r, "123456")
        self.assertNotContains(r, "555555")
        r = self.client.get(reverse("catalogo_sap:servicios"))
        self.assertContains(r, "555555")
        self.assertNotContains(r, "123456")
        r = self.client.get(reverse("catalogo_sap:consulta"), {"descripcion": "filt", "centro": self.c["meix"].pk})
        self.assertNotContains(r, "123456")  # existe solo en MTTU

    def test_materiales_un_renglon_por_material_y_centro(self):
        importar(txt("123456\tFILTRO\tMTTU\tZRA\tPZA\t\t", "123456\tFILTRO\tMEIX\tZRA\tPZA\t\t"), "m.txt", self.dm)
        self.client.force_login(self.sol)
        r = self.client.get(reverse("catalogo_sap:consulta"))
        self.assertEqual([(mc.material.codigo, mc.centro.codigo) for mc in r.context["pagina"]],
                         [("123456", "MEIX"), ("123456", "MTTU")])
        self.assertContains(r, "CEBE-MEIX")
        r = self.client.get(reverse("catalogo_sap:consulta"), {"centro": self.c["mttu"].pk})
        self.assertEqual(r.context["pagina"].paginator.count, 1)


class EjemplosTests(TestCase):
    """Los archivos de docs/ejemplos dan lo que dice docs/fase-4b.md."""

    def test_archivos_de_ejemplo(self):
        from pathlib import Path

        from django.conf import settings
        from django.core.management import call_command

        call_command("datos_demo", stdout=StringIO())
        dm = crear_usuario("dm2", "DM")
        carpeta = Path(settings.BASE_DIR) / "docs" / "ejemplos"

        def sube(nombre, catalogo):
            with open(carpeta / nombre, "rb") as f:
                imp = importar(f, nombre, dm, catalogo)
            return imp.importados, imp.errores

        self.assertEqual(sube("catalogo-materiales-ejemplo.txt", "MATERIALES"), (2, 3))
        self.assertEqual(sube("catalogo-servicios-ejemplo.txt", "SERVICIOS"), (3, 0))
        self.assertEqual(sube("catalogo-materiales-otro-centro.txt", "MATERIALES"), (1, 2))
        m = MaterialSAP.objects.get(codigo="310001", es_servicio=False)
        self.assertEqual(sorted(m.centros.values_list("centro__codigo", flat=True)), ["MEIX", "MTTU"])


class CatalogoCompletoTests(TestCase):
    """Pedido de Dave: todas las columnas del alta, filtro por columna y ficha del material con imágenes."""

    @classmethod
    def setUpTestData(cls):
        from solicitudes import flujo
        from solicitudes.models import Partida
        from solicitudes.tests.datos import crear_enviada

        cls.c = catalogos_para_importar()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])
        cls.otro = crear_usuario("otro", "SOL_MAT", centros=[cls.c["meix"]])  # no ve la solicitud
        solicitud = crear_enviada(cls.c, cls.sol, n=1, estado=Partida.Estado.EN_DM)
        cls.partida = solicitud.partidas.get()
        flujo.terminar_con_codigos(cls.dm, {cls.partida.pk: "100001"})
        importar(txt("200002\tBALATA\tMEIX\tZRA\tPZA\tBD-7\t"), "m.txt", cls.dm)

    def test_alta_en_webdm_llena_todas_las_columnas(self):
        m = MaterialSAP.objects.get(codigo="100001")
        self.assertEqual((m.ubicacion, m.tipo_unidad, m.marca, m.version, m.anio_modelo, m.partida_origen),
                         ("MOTOR", "TRACTO", "MARCA", "V1", 2024, self.partida))
        self.assertEqual(m.centros.get().almacen, "RC01")

    def test_filtros_por_columna(self):
        self.client.force_login(self.otro)
        url = reverse("catalogo_sap:consulta")
        def codigos(**f):
            return [mc.material.codigo for mc in self.client.get(url, f).context["pagina"]]
        self.assertEqual(codigos(), ["100001", "200002"])
        self.assertEqual(codigos(marca="marc"), ["100001"])
        self.assertEqual(codigos(anio="2024"), ["100001"])
        self.assertEqual(codigos(no_parte="bd"), ["200002"])
        self.assertEqual(codigos(origen="IMPORT", centro=str(self.c["meix"].pk)), ["200002"])
        self.assertEqual(codigos(anio="abc"), ["100001", "200002"])  # basura: se ignora
        r = self.client.get(url)
        self.assertNotContains(r, 'name="almacen"')  # Almacén y UMB no se filtran
        self.assertNotContains(r, 'name="umb"')
        self.assertNotContains(r, 'name="grupo_compras"')  # ni Grupo de compras ni CeBe (Dave)
        self.assertNotContains(r, 'name="cebe"')

    def test_ficha_del_material_con_imagenes_para_cualquier_usuario(self):
        m = MaterialSAP.objects.get(codigo="100001")
        self.client.force_login(self.otro)
        r = self.client.get(reverse("catalogo_sap:consulta"))
        self.assertContains(r, reverse("catalogo_sap:material", args=[m.pk]))
        r = self.client.get(reverse("catalogo_sap:material", args=[m.pk]))
        self.assertContains(r, "TRACTO")
        imagen = r.context["imagenes"][0]
        # El catálogo es global: ya dado de alta, su imagen la ve también quien no ve la solicitud.
        self.assertEqual(self.client.get(reverse("solicitudes:ver_imagen", args=[imagen.pk])).status_code, 200)
        r = self.client.get(reverse("catalogo_sap:material", args=[MaterialSAP.objects.get(codigo="200002").pk]))
        self.assertContains(r, "Sin imágenes")


class ExportarTests(TestCase):
    """Pedido de Dave: exportar lo filtrado al portapapeles, TXT, CSV y Excel."""

    @classmethod
    def setUpTestData(cls):
        cls.c = catalogos_para_importar()
        cls.dm = crear_usuario("dm", "DM")
        importar(txt("123456\tFiltro, de aire\tMTTU\tZRA\tPZA\tFA-1\t", "222222\tBALATA\tMTTU\tZRA\tPZA\t\t"), "m.txt", cls.dm)
        importar(txt("555555\tMANO DE OBRA\tZSA\tSER", encabezados=ENCABEZADOS_SERVICIOS), "s.txt", cls.dm, "SERVICIOS")

    def setUp(self):
        self.client.force_login(self.dm)

    def baja(self, url, **params):
        r = self.client.get(url, params)
        return r, b"".join(r.streaming_content).decode("utf-8") if r.streaming else r.content

    def test_txt_con_tabuladores_respeta_filtros(self):
        r, texto = self.baja(reverse("catalogo_sap:consulta"), exportar="txt", descripcion="filtro")
        self.assertIn('attachment; filename="catalogo-materiales-', r["Content-Disposition"])
        lineas = texto.lstrip("﻿").split("\r\n")
        self.assertTrue(lineas[0].startswith("Código SAP\tTipo de material\tCentro\tDescripción"))
        self.assertEqual(lineas[1].split("\t")[:4], ["123456", "ZRA", "MTTU", "FILTRO, DE AIRE"])
        self.assertEqual(len([l for l in lineas if l]), 2)  # encabezado + 1: el filtro aplica

    def test_portapapeles_sin_bom_y_csv_con_comillas(self):
        _, texto = self.baja(reverse("catalogo_sap:consulta"), exportar="portapapeles")
        self.assertTrue(texto.startswith("Código SAP\t"))
        _, texto = self.baja(reverse("catalogo_sap:consulta"), exportar="csv")
        self.assertIn('123456,ZRA,MTTU,"FILTRO, DE AIRE"', texto)

    def test_excel(self):
        from openpyxl import load_workbook

        r, contenido = self.baja(reverse("catalogo_sap:servicios"), exportar="xlsx")
        hoja = load_workbook(BytesIO(contenido)).active
        self.assertEqual([c.value for c in hoja[1]], ["Código SAP", "Descripción", "Tipo de material", "UMB",
                                                    "Grupo de artículos", "Origen"])
        self.assertEqual([c.value for c in hoja[2]][:5], ["555555", "MANO DE OBRA", "ZSA", "SER", "GA1"])
        self.assertEqual(hoja.max_row, 2)

    def test_menu_exportar_conserva_filtros(self):
        r = self.client.get(reverse("catalogo_sap:consulta"), {"marca": "x", "pagina": "1"})
        self.assertContains(r, "marca=x&amp;exportar=xlsx")
