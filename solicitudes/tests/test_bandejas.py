"""Pruebas de las pantallas de la fase 3: bandeja, corrección, detalle y contador del menú."""

from django.test import TestCase
from django.urls import reverse

from solicitudes.models import Evento, Partida

from .datos import crear_catalogos, crear_enviada, crear_usuario

E = Partida.Estado


class BandejaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])
        cls.val_meix = crear_usuario("valmeix", "VAL_MAT", centros=[cls.c["meix"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])
        cls.admin = crear_usuario("admin", "ADMIN")

    def setUp(self):
        self.solicitud = crear_enviada(self.c, self.sol, n=2)
        self.ids = [str(i) for i in self.solicitud.partidas.values_list("pk", flat=True)]

    def test_validador_ve_solo_sus_centros(self):
        self.client.force_login(self.val)
        r = self.client.get(reverse("solicitudes:pendientes"))
        self.assertContains(r, "FILTRO 0")
        self.client.force_login(self.val_meix)
        r = self.client.get(reverse("solicitudes:pendientes"))
        self.assertNotContains(r, "FILTRO 0")

    def test_contador_en_el_menu(self):
        self.client.force_login(self.val)
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, '<span class="wd-contador">2</span>', html=True)

    def test_admin_no_tiene_bandeja(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("solicitudes:pendientes")).status_code, 403)

    def test_aprobar_desde_la_bandeja(self):
        self.client.force_login(self.val)
        r = self.client.post(reverse("solicitudes:accion"), {"accion": "aprobar", "tab": "val", "partidas": self.ids})
        self.assertRedirects(r, reverse("solicitudes:pendientes") + "?tab=val")
        self.assertEqual(set(Partida.objects.values_list("estado", flat=True)), {E.EN_DM})

    def test_devolver_sin_motivo_muestra_error(self):
        self.client.force_login(self.val)
        r = self.client.post(reverse("solicitudes:accion"), {"accion": "devolver", "tab": "val", "partidas": self.ids},
                             follow=True)
        self.assertContains(r, "motivo")
        self.assertEqual(set(Partida.objects.values_list("estado", flat=True)), {E.EN_VALIDACION})

    def test_dm_termina_con_codigo_y_ve_errores(self):
        Partida.objects.update(estado=E.EN_DM)
        self.client.force_login(self.dm)
        r = self.client.post(reverse("solicitudes:terminar_dm"), {f"codigo-{self.ids[0]}": "12A"})
        self.assertContains(r, "6 dígitos")
        self.assertContains(r, 'value="12A"')
        r = self.client.post(reverse("solicitudes:terminar_dm"), {f"codigo-{self.ids[0]}": "123456"})
        self.assertEqual(Partida.objects.get(pk=self.ids[0]).estado, E.TERMINADA)

    def test_detalle_permisos(self):
        self.client.force_login(self.val_meix)
        self.assertEqual(self.client.get(reverse("solicitudes:detalle", args=[self.solicitud.pk])).status_code, 403)
        self.client.force_login(self.dm)
        self.assertEqual(self.client.get(reverse("solicitudes:detalle", args=[self.solicitud.pk])).status_code, 200)


class CorreccionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])

    def datos(self, partidas, accion, **cambios):
        datos = {"form-TOTAL_FORMS": len(partidas), "form-INITIAL_FORMS": len(partidas), "accion": accion}
        for i, p in enumerate(partidas):
            a = p.alta
            fila = {
                "pid": p.pk, "centro": p.centro_id, "descripcion": a.descripcion, "ubicacion": a.ubicacion_id,
                "no_parte_original": a.no_parte_original, "tipo_unidad": a.tipo_unidad, "marca": a.marca,
                "version": a.version, "anio_modelo": a.anio_modelo, "compatibilidad": a.compatibilidad,
                "umb": a.umb_id, "grupo_articulos": a.grupo_articulos_id,
                "categoria_valoracion": a.categoria_valoracion_id, "grupo_compras": a.grupo_compras_id,
            }
            if i == 0:
                fila.update(cambios)
            datos.update({f"form-{i}-{k}": "" if v is None else v for k, v in fila.items()})
        return datos

    def test_solicitante_corrige_y_reenvia(self):
        solicitud = crear_enviada(self.c, self.sol, n=2, estado=E.DEVUELTA_SOL)
        partidas = list(solicitud.partidas.order_by("numero"))
        self.client.force_login(self.sol)
        url = reverse("solicitudes:corregir", args=[solicitud.pk])
        self.assertContains(self.client.get(url), "Guardar y reenviar")
        r = self.client.post(url, self.datos(partidas, "reenviar", marca="Otra marca", numero=999))
        self.assertRedirects(r, reverse("solicitudes:detalle", args=[solicitud.pk]))
        partidas[0].refresh_from_db()
        self.assertEqual(partidas[0].numero, 10)  # el número no se puede cambiar
        self.assertEqual(partidas[0].alta.marca, "OTRA MARCA")
        self.assertEqual(set(solicitud.partidas.values_list("estado", flat=True)), {E.EN_VALIDACION})
        cambio = Evento.objects.get(tipo=Evento.Tipo.CAMBIO_CAMPO)
        self.assertEqual(cambio.detalle, {"campo": "marca", "antes": "MARCA", "despues": "OTRA MARCA"})

    def test_reenviar_exige_obligatorios(self):
        solicitud = crear_enviada(self.c, self.sol, n=1, estado=E.DEVUELTA_SOL)
        partidas = list(solicitud.partidas.all())
        self.client.force_login(self.sol)
        r = self.client.post(reverse("solicitudes:corregir", args=[solicitud.pk]),
                             self.datos(partidas, "reenviar", marca=""))
        self.assertContains(r, "Obligatorio para enviar")
        self.assertEqual(solicitud.partidas.get().estado, E.DEVUELTA_SOL)

    def test_validador_corrige_en_validacion(self):
        solicitud = crear_enviada(self.c, self.sol, n=1)
        partidas = list(solicitud.partidas.all())
        self.client.force_login(self.val)
        url = reverse("solicitudes:corregir", args=[solicitud.pk])
        r = self.client.get(url)
        self.assertNotContains(r, "Guardar y reenviar")
        self.client.post(url, self.datos(partidas, "guardar", version="V2"))
        self.assertEqual(solicitud.partidas.get().alta.version, "V2")
        self.assertEqual(solicitud.partidas.get().estado, E.EN_VALIDACION)

    def test_no_se_corrige_lo_que_ya_avanzo(self):
        solicitud = crear_enviada(self.c, self.sol, n=1, estado=E.EN_DM)
        self.client.force_login(self.val)
        r = self.client.get(reverse("solicitudes:corregir", args=[solicitud.pk]))
        self.assertRedirects(r, reverse("solicitudes:detalle", args=[solicitud.pk]))


class FichaPartidaTests(TestCase):
    """La ficha tipo formulario de UNA partida, que se abre desde Pendientes de mi atención."""

    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])
        cls.val_meix = crear_usuario("valmeix", "VAL_MAT", centros=[cls.c["meix"]])

    def setUp(self):
        self.solicitud = crear_enviada(self.c, self.sol, n=2)
        self.p1, self.p2 = self.solicitud.partidas.order_by("numero")
        self.url = reverse("solicitudes:partida", args=[self.p1.pk])

    def datos(self, accion, **cambios):
        a = self.p1.alta
        datos = {
            "accion": accion, "pid": self.p1.pk, "centro": self.p1.centro_id, "descripcion": a.descripcion,
            "ubicacion": a.ubicacion_id, "no_parte_original": a.no_parte_original, "tipo_unidad": a.tipo_unidad,
            "marca": a.marca, "version": a.version, "anio_modelo": a.anio_modelo, "compatibilidad": "",
            "umb": a.umb_id, "grupo_articulos": a.grupo_articulos_id,
            "categoria_valoracion": a.categoria_valoracion_id, "grupo_compras": a.grupo_compras_id,
        }
        datos.update(cambios)
        return datos

    def test_la_bandeja_enlaza_a_la_ficha(self):
        self.client.force_login(self.val)
        r = self.client.get(reverse("solicitudes:pendientes"))
        self.assertContains(r, self.url)

    def test_muestra_solo_esa_partida_y_sus_acciones(self):
        self.client.force_login(self.val)
        r = self.client.get(self.url)
        self.assertContains(r, "FILTRO 0")
        self.assertNotContains(r, "FILTRO 1")
        self.assertContains(r, 'value="aprobar"')
        self.assertContains(r, 'value="devolver"')
        self.assertContains(r, "Imagen 1")

    def test_validador_corrige_y_aprueba_desde_la_ficha(self):
        self.client.force_login(self.val)
        r = self.client.post(self.url, self.datos("aprobar", marca="Marca nueva"))
        self.assertRedirects(r, reverse("solicitudes:pendientes") + "?tab=val", fetch_redirect_response=False)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.estado, E.EN_DM)
        self.assertEqual(self.p1.alta.marca, "MARCA NUEVA")
        self.assertEqual(self.p2.estado, E.EN_VALIDACION)  # la otra partida no se toca

    def test_dm_termina_desde_la_ficha(self):
        Partida.objects.filter(pk=self.p1.pk).update(estado=E.EN_DM)
        self.client.force_login(self.dm)
        r = self.client.get(self.url)
        self.assertContains(r, 'value="terminar"')
        self.assertNotContains(r, 'name="descripcion"')  # DM ve los datos, no los edita
        self.client.post(self.url, {"accion": "terminar", "codigo": "654321"})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.estado, E.TERMINADA)

    def test_otro_centro_no_la_ve(self):
        self.client.force_login(self.val_meix)
        self.assertEqual(self.client.get(self.url).status_code, 403)


class AvisoSinDmTests(TestCase):
    """Si nadie de DM tiene el Centro, al aprobar se avisa: si no, las partidas 'desaparecen'."""

    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])

    def aprobar(self):
        solicitud = crear_enviada(self.c, self.sol, n=1)
        ids = [str(i) for i in solicitud.partidas.values_list("pk", flat=True)]
        self.client.force_login(self.val)
        return self.client.post(reverse("solicitudes:accion"), {"accion": "aprobar", "tab": "val", "partidas": ids},
                                follow=True)

    def test_avisa_si_ningun_dm_tiene_el_centro(self):
        crear_usuario("dm", "DM", centros=[self.c["meix"]])  # DM existe, pero de otro Centro
        crear_usuario("dm2", "DM")  # y otro DM sin ningún Centro
        self.assertContains(self.aprobar(), "ningún usuario activo con rol DM tiene autorizado el Centro MTTU")

    def test_no_avisa_si_hay_dm(self):
        crear_usuario("dm", "DM", centros=[self.c["mttu"]])
        self.assertNotContains(self.aprobar(), "ningún usuario activo")
