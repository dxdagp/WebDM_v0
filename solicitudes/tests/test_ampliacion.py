"""Fase 4c: AMPL_ZRA, ampliación de material a Centro (Revisión 3, sección 10, y layout de Dave)."""

from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import Almacen, GrupoCompras, Planificador
from solicitudes import ampliacion, flujo
from solicitudes.models import Evento, Flujo, Partida, Solicitud

from .datos import crear_catalogos, crear_usuario

E = Partida.Estado


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = c = crear_catalogos()  # MTTU (RC01, G01) y MEIX (RC01)
        cls.meix_g = GrupoCompras.objects.create(centro=c["meix"], codigo="G05", predeterminado=True)
        cls.meix_p = Planificador.objects.create(centro=c["meix"], codigo="P09", predeterminado=True)
        cls.meix_alm = Almacen.objects.get(centro=c["meix"], codigo="RC01")
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"], c["meix"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[c["mttu"], c["meix"]])
        cls.dm = crear_usuario("dm", "DM", centros=[c["meix"]])
        cls.material = MaterialSAP.objects.create(codigo="310001", descripcion="BALATA", tipo_material="ZRA",
                                                  origen="IMPORT", creado_por=cls.dm)
        MaterialCentro.objects.create(material=cls.material, centro=c["mttu"], categoria_valoracion="CV1", cebe="CEBE-MTTU")

    def post(self, usuario, accion, *renglones, url=None):
        """Manda la tabla como la manda el navegador: form-0-codigo_sap, form-0-centro…"""
        datos = {"form-TOTAL_FORMS": str(len(renglones)), "form-INITIAL_FORMS": "0", "accion": accion}
        for i, r in enumerate(renglones):
            for k, v in r.items():
                datos[f"form-{i}-{k}"] = v
        self.client.force_login(usuario)
        return self.client.post(url or reverse("solicitudes:nueva_ampl"), datos, follow=True)

    def renglon(self, numero=10, codigo="310001", centro=None, **otros):
        return {"numero": numero, "codigo_sap": codigo, "centro": (centro or self.c["meix"]).pk, **otros}


class CapturaTests(Base):
    def test_propone_modelo_almacenes_planificador_y_grupo(self):
        r = self.post(self.sol, "enviar", self.renglon())
        s = Solicitud.objects.get()
        self.assertEqual((s.flujo, s.folio), ("AMPL_ZRA", "AMPL_ZRA-2026-000001"))
        a = s.partidas.get().ampliacion
        self.assertEqual(a.centro_origen, self.c["mttu"])  # donde ya existe
        self.assertEqual((a.almacen_modelo.centro, a.almacen_destino), (self.c["mttu"], self.meix_alm))
        self.assertEqual((a.planificador, a.grupo_compras, a.material), (self.meix_p, self.meix_g, self.material))
        self.assertEqual(s.partidas.get().estado, E.EN_VALIDACION)
        self.assertContains(r, "Solicitud enviada con folio")

    def test_material_que_no_existe_o_centro_modelo_equivocado(self):
        r = self.post(self.sol, "guardar", self.renglon(codigo="999999"))
        self.assertContains(r, "No existe en el catálogo de materiales")
        r = self.post(self.sol, "guardar", self.renglon(centro_origen=self.c["meix"].pk, centro=self.c["mttu"]))
        self.assertContains(r, "Centro modelo debe ser uno donde ya exista")
        self.assertFalse(Solicitud.objects.exists())

    def test_almacen_de_otro_centro_es_error(self):
        mttu_alm = Almacen.objects.get(centro=self.c["mttu"])
        r = self.post(self.sol, "guardar", self.renglon(almacen_destino=mttu_alm.pk))
        self.assertContains(r, "No pertenece al Centro MEIX")

    def test_ya_ampliado_se_omite_y_si_todos_queda_borrador(self):
        r = self.post(self.sol, "enviar", self.renglon(centro=self.c["mttu"]))
        self.assertContains(r, "ya existe en MTTU; se omitió")
        self.assertContains(r, "No existen partidas válidas")
        s = Solicitud.objects.get()
        self.assertEqual((s.estado, s.folio, s.partidas.count()), ("BORRADOR", None, 0))
        self.assertFalse(Evento.objects.filter(tipo=Evento.Tipo.ENVIO).exists())

    def test_repetido_en_la_misma_solicitud(self):
        r = self.post(self.sol, "guardar", self.renglon(10), self.renglon(20))
        self.assertContains(r, "Material y Centro nuevo repetidos")

    def test_validador_va_directo_a_dm(self):
        self.post(self.val, "enviar", self.renglon())
        self.assertEqual(Partida.objects.get().estado, E.EN_DM)

    def test_json_del_material(self):
        self.client.force_login(self.sol)
        datos = self.client.get(reverse("solicitudes:material_ampl"), {"codigo": "310001"}).json()
        self.assertEqual((datos["descripcion"], datos["centros"][0]["codigo"]), ("BALATA", "MTTU"))


class FlujoDMTests(Base):
    def setUp(self):
        self.post(self.sol, "enviar", self.renglon(10), self.renglon(20, codigo="310002"))  # el 310002 no existe…

    def enviada(self):
        return Solicitud.objects.filter(folio__isnull=False).get()

    def test_aprobar_exportar_excluir_y_finalizar(self):
        otro = MaterialSAP.objects.create(codigo="310002", descripcion="FILTRO", tipo_material="ZRA", origen="IMPORT", creado_por=self.dm)
        MaterialCentro.objects.create(material=otro, centro=self.c["mttu"])
        self.post(self.sol, "enviar", self.renglon(10), self.renglon(20, codigo="310002"))
        s = self.enviada()
        ids = list(s.partidas.values_list("pk", flat=True))
        flujo.aplicar(self.val, "aprobar", ids)

        self.client.force_login(self.dm)
        url = reverse("solicitudes:ampliacion_dm", args=[s.pk])
        r = self.client.get(url, {"exportar": 1})
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="Amp_Mat.txt"')
        lineas = r.content.decode().split("\r\n")
        self.assertEqual(lineas[0].split("\t"), ["310001", "310001", "MEIX", "RC01", "MTTU", "RC01", "P09", "G05", "CEBE-MEIX"])
        self.assertEqual(len([l for l in lineas if l]), 2)  # sin encabezados

        p20 = s.partidas.get(numero=20)
        self.client.post(url, {"accion": "excluir", "partidas": [p20.pk], "motivo-%d" % p20.pk: "SAP lo rechazó"})
        p20.refresh_from_db()
        self.assertEqual(p20.estado, E.EXCLUIDA)
        self.assertEqual(len([l for l in self.client.get(url, {"exportar": 1}).content.decode().split("\r\n") if l]), 1)

        self.client.post(url, {"accion": "finalizar"})
        p10 = s.partidas.get(numero=10)
        self.assertEqual(p10.estado, E.TERMINADA)
        mc = MaterialCentro.objects.get(material=self.material, centro=self.c["meix"])
        # Pedido de Dave: la ampliación agrega el Centro al catálogo de materiales.
        self.assertEqual((mc.almacen, mc.grupo_compras, mc.cebe, mc.categoria_valoracion), ("RC01", "G05", "CEBE-MEIX", "CV1"))
        s.refresh_from_db()
        self.assertEqual(s.estado, "TERMINADA")

    def test_excluir_exige_motivo_y_solo_ampl(self):
        self.post(self.val, "enviar", self.renglon())
        p = Partida.objects.get(estado=E.EN_DM)
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "motivo es obligatorio"):
            flujo.aplicar(self.dm, "excluir", [p.pk])

    def test_aprobar_revisa_si_ya_se_amplio_mientras_tanto(self):
        self.post(self.sol, "enviar", self.renglon())
        p = Partida.objects.get(estado=E.EN_VALIDACION)
        MaterialCentro.objects.create(material=self.material, centro=self.c["meix"])  # entró por importación
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "ya está ampliado"):
            flujo.aplicar(self.val, "aprobar", [p.pk])

    def test_bandeja_y_detalle_muestran_la_ampliacion(self):
        self.post(self.val, "enviar", self.renglon())
        s = Solicitud.objects.get(partidas__estado=E.EN_DM)
        self.client.force_login(self.dm)
        r = self.client.get(reverse("solicitudes:pendientes"), {"tab": "dm"})
        self.assertContains(r, "Ampliar 310001 · BALATA")
        self.assertContains(r, reverse("solicitudes:exportar_ampl"))  # un solo botón arriba, no uno por partida
        self.assertNotContains(r, reverse("solicitudes:ampliacion_dm", args=[s.pk]))
        r = self.client.get(reverse("solicitudes:detalle", args=[s.pk]))
        self.assertContains(r, "Datos Maestros: exportar / finalizar")
        r = self.client.get(reverse("solicitudes:partida", args=[s.partidas.get().pk]))
        self.assertRedirects(r, reverse("solicitudes:detalle", args=[s.pk]) + "#partida-10")


class BandejaDMTests(Base):
    """Pedido de Dave: Exportar no es por partida ni por folio, sino de todo lo seleccionado."""

    def setUp(self):
        otro = MaterialSAP.objects.create(codigo="310002", descripcion="FILTRO", tipo_material="ZRA", origen="IMPORT", creado_por=self.dm)
        MaterialCentro.objects.create(material=otro, centro=self.c["mttu"])
        self.post(self.val, "enviar", self.renglon(10))                      # folio 1, directo a DM
        self.post(self.val, "enviar", self.renglon(10, codigo="310002"))     # folio 2, directo a DM
        self.ids = list(Partida.objects.filter(estado=E.EN_DM).order_by("pk").values_list("pk", flat=True))
        self.client.force_login(self.dm)

    def test_exporta_un_solo_txt_de_varios_folios(self):
        r = self.client.post(reverse("solicitudes:exportar_ampl"), {"partidas": self.ids})
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="Amp_Mat.txt"')
        lineas = [l.split("\t")[0] for l in r.content.decode().split("\r\n") if l]
        self.assertEqual(lineas, ["310001", "310002"])
        # Solo lo marcado:
        r = self.client.post(reverse("solicitudes:exportar_ampl"), {"partidas": self.ids[1:]})
        self.assertEqual(r.content.decode().count("\r\n"), 1)
        self.assertFalse(Partida.objects.exclude(estado=E.EN_DM).filter(pk__in=self.ids).exists())  # exportar no cambia nada

    def test_seleccion_con_algo_que_no_es_ampliacion_en_dm(self):
        self.post(self.sol, "enviar", self.renglon(10))
        en_validacion = Partida.objects.get(estado=E.EN_VALIDACION).pk
        self.client.force_login(self.dm)
        r = self.client.post(reverse("solicitudes:exportar_ampl"), {"partidas": self.ids + [en_validacion], "tab": "dm"}, follow=True)
        self.assertContains(r, "Quita de la selección")
        r = self.client.post(reverse("solicitudes:exportar_ampl"), {"tab": "dm"}, follow=True)
        self.assertContains(r, "Selecciona al menos una ampliación")

    def test_excluir_y_finalizar_lo_seleccionado(self):
        excluida, terminada = self.ids
        r = self.client.post(reverse("solicitudes:accion"), {"accion": "excluir", "partidas": [excluida],
                                                             f"motivo-{excluida}": "SAP lo rechazó", "tab": "dm"}, follow=True)
        self.assertContains(r, "excluida(s)")
        r = self.client.post(reverse("solicitudes:finalizar_ampl"), {"partidas": [terminada], "tab": "dm"}, follow=True)
        self.assertContains(r, "1 ampliación(es) terminada(s)")
        self.assertEqual(Partida.objects.get(pk=excluida).estado, E.EXCLUIDA)
        self.assertEqual(Partida.objects.get(pk=terminada).estado, E.TERMINADA)
        self.assertTrue(MaterialCentro.objects.filter(material__codigo="310002", centro=self.c["meix"]).exists())
        self.assertEqual(Partida.objects.get(pk=terminada).solicitud.estado, "TERMINADA")


class CorreccionTests(Base):
    def test_devuelta_se_corrige_y_reenvia(self):
        self.post(self.sol, "enviar", self.renglon())
        s = Solicitud.objects.get()
        p = s.partidas.get()
        flujo.aplicar(self.val, "devolver", [p.pk], "otro almacén")
        nuevo = Almacen.objects.create(centro=self.c["meix"], codigo="RC02")
        a = p.ampliacion
        datos = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1", "accion": "reenviar",
                 "form-0-pid": p.pk, "form-0-numero": 10, "form-0-codigo_sap": "310001", "form-0-centro": self.c["meix"].pk,
                 "form-0-almacen_destino": nuevo.pk, "form-0-centro_origen": a.centro_origen_id,
                 "form-0-almacen_modelo": a.almacen_modelo_id, "form-0-planificador": a.planificador_id,
                 "form-0-grupo_compras": a.grupo_compras_id}
        self.client.force_login(self.sol)
        self.client.post(reverse("solicitudes:corregir", args=[s.pk]), datos)
        p.refresh_from_db()
        self.assertEqual((p.estado, p.ampliacion.almacen_destino), (E.EN_VALIDACION, nuevo))
        self.assertTrue(p.eventos.filter(tipo=Evento.Tipo.CAMBIO_CAMPO, detalle__campo="Almacén nuevo").exists())


class MenuTests(Base):
    def test_menu_ampliar_activo(self):
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:mis_solicitudes"))
        self.assertContains(r, reverse("solicitudes:nueva_ampl"))
        self.assertEqual(Flujo.AMPL_ZRA, "AMPL_ZRA")


class EnterValidaTests(Base):
    """Pedido de Dave: Enter no envía; valida lo capturado (y lo guarda como borrador)."""

    def test_validar_no_envia(self):
        r = self.post(self.sol, "validar", self.renglon())
        self.assertContains(r, "Validación correcta")
        s = Solicitud.objects.get()
        self.assertEqual((s.estado, s.folio), ("BORRADOR", None))

    def test_validar_marca_errores(self):
        r = self.post(self.sol, "validar", self.renglon(codigo="999999"))
        self.assertContains(r, "La validación encontró errores")
        self.assertContains(r, "No existe en el catálogo de materiales")
        self.assertFalse(Solicitud.objects.exists())

    def test_enter_dispara_validar(self):
        # El primer botón de envío del formulario es el que usa Enter: debe ser "validar".
        self.client.force_login(self.sol)
        for url in (reverse("solicitudes:nueva_ampl"), reverse("solicitudes:nueva_amat")):
            html = self.client.get(url).content.decode()
            form = html[html.index('id="form-captura"'):]
            self.assertIn('value="validar"', form[:form.index('type="submit"') + 80])
