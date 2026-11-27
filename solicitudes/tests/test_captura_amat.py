"""Pruebas de la pantalla de captura AMAT_ZRA: borrador permisivo, envío estricto y folio."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from catalogos.models import (
    Almacen, CategoriaValoracion, Centro, GrupoArticulos, GrupoCompras, TipoMaterial, UbicacionRefaccion, UMB,
)
from catalogo_sap.models import MaterialSAP
from solicitudes.models import ImagenPartida, Partida, Solicitud
from solicitudes.tests.datos import poner_imagen


class BaseCaptura(TestCase):
    """Datos y ayudantes comunes de las pruebas de captura."""

    @classmethod
    def setUpTestData(cls):
        cls.mttu = Centro.objects.create(codigo="MTTU", nombre="MTTU", centro_beneficio="CEBE-MTTU")
        cls.meix = Centro.objects.create(codigo="MEIX", nombre="MEIX", centro_beneficio="CEBE-MEIX")
        Almacen.objects.create(centro=cls.mttu, codigo="RC01", predeterminado=True)
        cls.grupo_mttu = GrupoCompras.objects.create(centro=cls.mttu, codigo="G01", predeterminado=True)
        cls.grupo_meix = GrupoCompras.objects.create(centro=cls.meix, codigo="G01", predeterminado=True)
        cls.ubicacion = UbicacionRefaccion.objects.create(codigo="MOTOR", descripcion="Motor")
        cls.umb = UMB.objects.create(codigo="PZA", descripcion="Pieza")
        cls.grupo_art = GrupoArticulos.objects.create(codigo="GA1", descripcion="Filtros")
        tipo = TipoMaterial.objects.create(codigo="ZRA", descripcion="Refacciones")
        cls.categoria = CategoriaValoracion.objects.create(codigo="CV1", descripcion="Refacción", tipo_material=tipo)

        cls.sol = get_user_model().objects.create_user("sol", password="clave-segura-123")
        cls.sol.groups.add(Group.objects.get(name="SOL_MAT"))
        cls.sol.centros.add(cls.mttu)

    def setUp(self):
        self.client.force_login(self.sol)

    def fila(self, i=0, **cambios):
        """Un renglón completo y válido; `cambios` permite romperlo a propósito."""
        datos = {
            "numero": 10 * (i + 1), "centro": self.mttu.pk, "descripcion": "Filtro de aire",
            "ubicacion": self.ubicacion.pk, "no_parte_original": "abc-123", "tipo_unidad": "Tractocamión",
            "marca": "Marca", "version": "V1", "anio_modelo": "2024", "compatibilidad": "",
            "umb": self.umb.pk, "grupo_articulos": self.grupo_art.pk, "categoria_valoracion": self.categoria.pk,
            "grupo_compras": self.grupo_mttu.pk,
        }
        datos.update(cambios)
        return {f"form-{i}-{k}": v for k, v in datos.items()}

    def post(self, accion, *filas, solicitud=None):
        datos = {"form-TOTAL_FORMS": len(filas), "form-INITIAL_FORMS": 0, "accion": accion}
        for f in filas:
            datos.update(f)
        url = reverse("solicitudes:editar_amat", args=[solicitud.pk]) if solicitud else reverse("solicitudes:nueva_amat")
        return self.client.post(url, datos)

    def borrador_con_imagenes(self, *filas):
        """Fase 4: para enviar, cada partida necesita 1 imagen; y para subirla, la partida
        tiene que existir. Así que primero se guarda el borrador y luego se pone la imagen."""
        self.post("guardar", *filas)
        solicitud = Solicitud.objects.get()
        for partida in solicitud.partidas.all():
            poner_imagen(partida, self.sol)
        return solicitud


class CapturaAmatTests(BaseCaptura):
    def test_borrador_incompleto_si_se_guarda(self):
        self.post("guardar", self.fila(descripcion="", marca=""))
        partida = Partida.objects.get()
        self.assertEqual(partida.estado, Partida.Estado.BORRADOR)
        self.assertIsNone(partida.solicitud.folio)

    def test_valor_invalido_no_se_guarda_ni_en_borrador(self):
        respuesta = self.post("guardar", self.fila(anio_modelo="20A4"))
        self.assertContains(respuesta, "Debe tener 4 dígitos")
        self.assertFalse(Solicitud.objects.exists())

    def test_enviar_incompleto_marca_errores_y_no_guarda(self):
        respuesta = self.post("enviar", self.fila(marca=""))
        self.assertContains(respuesta, "Obligatorio para enviar")
        self.assertFalse(Solicitud.objects.exists())

    def test_enviar_completo_asigna_folio_y_normaliza(self):
        solicitud = self.borrador_con_imagenes(self.fila(), self.fila(1))
        self.post("enviar", self.fila(), self.fila(1), solicitud=solicitud)
        solicitud.refresh_from_db()
        self.assertRegex(solicitud.folio, r"^AMAT_ZRA-\d{4}-000001$")
        self.assertEqual(set(solicitud.partidas.values_list("estado", flat=True)), {"EN_VALIDACION"})
        alta = solicitud.partidas.first().alta
        self.assertEqual(alta.descripcion, "FILTRO DE AIRE")
        self.assertEqual(alta.tipo_unidad, "TRACTOCAMION")
        self.assertEqual(alta.almacen.codigo, "RC01")  # automático
        self.assertEqual(alta.tipo_material.codigo, "ZRA")  # derivado de la categoría

    def test_validador_que_envia_pasa_directo_a_dm(self):
        self.sol.groups.add(Group.objects.get(name="VAL_MAT"))
        solicitud = self.borrador_con_imagenes(self.fila())
        self.post("enviar", self.fila(), solicitud=solicitud)
        self.assertEqual(Partida.objects.get().estado, Partida.Estado.EN_DM)

    def test_grupo_de_compras_de_otro_centro_no(self):
        respuesta = self.post("guardar", self.fila(grupo_compras=self.grupo_meix.pk))
        self.assertContains(respuesta, "no pertenece al Centro")

    def test_centro_no_autorizado_no(self):
        respuesta = self.post("guardar", self.fila(centro=self.meix.pk))
        self.assertContains(respuesta, "con-error")
        self.assertFalse(Solicitud.objects.exists())

    def test_numero_de_partida_repetido(self):
        respuesta = self.post("guardar", self.fila(0), self.fila(1, numero=10))
        self.assertContains(respuesta, "Número de partida repetido")

    def test_sin_rol_no_puede_capturar(self):
        otro = get_user_model().objects.create_user("sin_rol", password="clave-segura-123")
        self.client.force_login(otro)
        self.assertEqual(self.client.get(reverse("solicitudes:nueva_amat")).status_code, 403)

    def test_pantalla_abre_y_muestra_menu(self):
        respuesta = self.client.get(reverse("solicitudes:nueva_amat"))
        self.assertContains(respuesta, "Crear materiales")
        self.assertContains(respuesta, "Cerrar sesión")
        self.assertNotContains(respuesta, "Importar catálogo SAP")  # solo ADMIN


class EnvioFase4Tests(BaseCaptura):
    """Imágenes y duplicados al Enviar (fase 4). Hereda los datos y ayudantes de arriba."""

    def test_sin_imagen_no_se_envia(self):
        self.post("guardar", self.fila())
        solicitud = Solicitud.objects.get()
        r = self.post("enviar", self.fila(), solicitud=solicitud)
        self.assertContains(r, "Falta al menos 1 imagen")
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.folio)

    def test_guardar_borrador_conserva_las_imagenes(self):
        solicitud = self.borrador_con_imagenes(self.fila(), self.fila(1))
        p10 = solicitud.partidas.get(numero=10)
        # Se cambia la descripción de la 10 y se QUITA la 20 de la tabla.
        self.post("guardar", self.fila(descripcion="Filtro de aceite"), solicitud=solicitud)
        p10_despues = solicitud.partidas.get()
        self.assertEqual(p10_despues.pk, p10.pk)  # misma partida (UPDATE, no DELETE + INSERT)
        self.assertEqual(p10_despues.alta.descripcion, "FILTRO DE ACEITE")
        self.assertEqual(ImagenPartida.objects.count(), 1)  # la de la 20 se fue con ella

    def test_duplicado_exacto_bloquea_el_envio(self):
        MaterialSAP.objects.create(codigo="100200", descripcion="FILTRO DE AIRE", no_parte_original="ABC-123",
                                   umb="PZA", tipo_material="ZRA", origen="IMPORT", creado_por=self.sol)
        solicitud = self.borrador_con_imagenes(self.fila())
        r = self.post("enviar", self.fila(), solicitud=solicitud)
        self.assertContains(r, "ya existe el código 100200")
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.folio)

    def test_advertencia_no_bloquea(self):
        MaterialSAP.objects.create(codigo="100201", descripcion="FILTRO DE AIRE", no_parte_original="OTRO-1",
                                   umb="PZA", tipo_material="ZRA", origen="IMPORT", creado_por=self.sol)
        solicitud = self.borrador_con_imagenes(self.fila())
        r = self.post("enviar", self.fila(), solicitud=solicitud)
        solicitud.refresh_from_db()
        self.assertIsNotNone(solicitud.folio)
        avisos = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any("Misma descripción con otro No. Parte" in a for a in avisos))
