"""Abre en Administración la lista, "agregar" y la ficha de CADA modelo registrado.

Nació de un error real (28-nov-2026): la ficha de una partida con imágenes tronaba con
"'subida' cannot be specified for ImagenPartida model form as it is a non-editable field".
Si mañana alguien registra un modelo nuevo o cambia un admin, esta prueba lo abre solo.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import ErrorImportacion, Importacion, MaterialCentro, MaterialSAP
from catalogos.models import Planificador, TipoServicio
from solicitudes.models import (ContadorFolio, DetalleAmpliacion, DetalleModificacion, DetalleServicio, Evento, Flujo, Partida,
                                Solicitud)
from solicitudes.tests.datos import crear_catalogos, crear_enviada, crear_usuario


class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        c = crear_catalogos()
        sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        crear_enviada(c, sol)  # AMAT con imagen y eventos
        material = MaterialSAP.objects.create(codigo="100001", descripcion="FILTRO", tipo_material="ZRA",
                                              origen="IMPORT", creado_por=sol)
        MaterialCentro.objects.create(material=material, centro=c["mttu"])
        imp = Importacion.objects.create(usuario=sol, nombre_archivo="sap.txt")
        ErrorImportacion.objects.create(importacion=imp, linea=2, mensaje="Centro inválido")
        TipoServicio.objects.create(codigo="MO", descripcion="Mano de obra", umb_predeterminada=c["umb"])
        Planificador.objects.create(centro=c["mttu"], codigo="P01", descripcion="Planificador 1")
        ContadorFolio.objects.create(flujo=Flujo.AMAT_ZRA, anio=2026, ultimo=1)
        # Una partida de cada uno de los otros flujos, con su detalle (cada flujo tiene su propio inline).
        for i, (flujo, crear) in enumerate([
            (Flujo.AMPL_ZRA, lambda p: DetalleAmpliacion.objects.create(partida=p, codigo_sap="100001", material=material)),
            (Flujo.MOD_ZRA, lambda p: DetalleModificacion.objects.create(partida=p, material=material, campo="MARCA", valor_nuevo="X")),
            (Flujo.MOD_ZSA, lambda p: DetalleModificacion.objects.create(partida=p, material=material, campo="DESCRIPCION", valor_nuevo="X")),
            (Flujo.ASER_ZSA, lambda p: DetalleServicio.objects.create(partida=p, descripcion="LAVADO")),
        ], start=2):
            s = Solicitud.objects.create(flujo=flujo, solicitante=sol, folio=f"{flujo}-2026-00000{i}", estado="EN_PROCESO")
            p = Partida.objects.create(solicitud=s, numero=10, estado="EN_VALIDACION")
            crear(p)
            Evento.objects.create(solicitud=s, partida=p, usuario=sol, tipo=Evento.Tipo.ENVIO)
        cls.admin = get_user_model().objects.create_superuser("admin", "", "clave-de-prueba-123")

    def test_cada_modelo_abre(self):
        self.client.force_login(self.admin)  # también deja un registro en la bitácora de sesiones
        sin_datos = []
        for modelo, modelo_admin in admin.site._registry.items():
            info = (modelo._meta.app_label, modelo._meta.model_name)
            with self.subTest(modelo=modelo.__name__):
                self.assertEqual(self.client.get(reverse("admin:%s_%s_changelist" % info)).status_code, 200)
                if modelo_admin.has_add_permission(self.client.request().wsgi_request):
                    self.assertEqual(self.client.get(reverse("admin:%s_%s_add" % info)).status_code, 200)
                objetos = modelo._default_manager.all()
                if modelo is Partida:
                    objetos = objetos.order_by("solicitud__flujo")  # todas: cada flujo tiene inlines distintos
                else:
                    objetos = objetos[:1]
                if not objetos:
                    sin_datos.append(modelo.__name__)
                for obj in objetos:
                    r = self.client.get(reverse("admin:%s_%s_change" % info, args=[obj.pk]))
                    self.assertEqual(r.status_code, 200, f"{modelo.__name__} {obj.pk}")
        # Group puede no tener datos; todo lo demás sí, para que la prueba de verdad abra su ficha.
        self.assertLessEqual(set(sin_datos), {"Group"}, sin_datos)

    def test_ficha_de_partida_con_bitacora_y_sin_id(self):
        self.client.force_login(self.admin)
        p = Partida.objects.get(solicitud__folio="AMAT_ZRA-2026-000001", numero=10)
        Evento.objects.create(solicitud=p.solicitud, partida=p, usuario=None, tipo=Evento.Tipo.VENCIMIENTO,
                              estado_anterior="DEVUELTA_SOL", estado_nuevo="CANCELADA", motivo="CANCELADA POR VENCIMIENTO")
        r = self.client.get(reverse("admin:solicitudes_partida_change", args=[p.pk]))
        self.assertContains(r, "Bitácora de la partida")
        self.assertContains(r, "Envío")
        self.assertContains(r, "CANCELADA POR VENCIMIENTO")
        self.assertContains(r, "Sistema")
        self.assertNotContains(r, "<label>ID:</label>", html=False)

    def test_importacion_de_solo_lectura(self):
        """Pedido de Dave: en una importación no se edita nada (ni el catálogo) ni se agregan errores."""
        self.client.force_login(self.admin)
        imp = Importacion.objects.get()
        r = self.client.get(reverse("admin:catalogo_sap_importacion_change", args=[imp.pk]))
        self.assertNotContains(r, 'name="catalogo"')
        self.assertNotContains(r, 'id="detalle_errores-empty"')  # la fila en blanco para agregar errores
        self.assertNotContains(r, 'name="_save"')
        self.assertEqual(self.client.post(reverse("admin:catalogo_sap_importacion_delete", args=[imp.pk])).status_code, 403)
