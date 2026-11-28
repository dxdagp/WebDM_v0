"""Fase 4d: MOD_ZRA y MOD_ZSA, modificación de materiales y servicios (decisiones de Dave, 28-nov-2026)."""

from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import GrupoArticulos, GrupoCompras
from solicitudes import bandejas, flujo
from solicitudes.models import Evento, Partida, Solicitud

from .datos import crear_catalogos, crear_usuario

E = Partida.Estado


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = c = crear_catalogos()  # MTTU (RC01, G01), MEIX (RC01); grupo de artículos GA1; ubicación MOTOR
        GrupoArticulos.objects.create(codigo="GA2", descripcion="Frenos")
        GrupoCompras.objects.create(centro=c["mttu"], codigo="G02")
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[c["mttu"]])
        cls.val_meix = crear_usuario("val_meix", "VAL_MAT", centros=[c["meix"]])
        cls.dm = crear_usuario("dm", "DM", centros=[c["mttu"]])
        cls.material = MaterialSAP.objects.create(codigo="310001", descripcion="BALATA", tipo_material="ZRA", marca="FORD",
                                                  grupo_articulos="GA1", origen="IMPORT", creado_por=cls.dm)
        MaterialCentro.objects.create(material=cls.material, centro=c["mttu"], grupo_compras="G01", almacen="RC01", cebe="CEBE-MTTU")
        cls.servicio = MaterialSAP.objects.create(codigo="310001", descripcion="MANO DE OBRA", tipo_material="ZSA",
                                                  grupo_articulos="GA1", es_servicio=True, origen="IMPORT", creado_por=cls.dm)

    def post(self, usuario, accion, *renglones, tipo="materiales", url=None):
        datos = {"form-TOTAL_FORMS": str(len(renglones)), "form-INITIAL_FORMS": "0", "accion": accion}
        for i, r in enumerate(renglones):
            for k, v in r.items():
                datos[f"form-{i}-{k}"] = v
        self.client.force_login(usuario)
        return self.client.post(url or reverse("solicitudes:nueva_mod", args=[tipo]), datos, follow=True)

    def renglon(self, numero=10, campo="MARCA", valor="Nissan", codigo="310001", centro=None):
        r = {"numero": numero, "codigo_sap": codigo, "campo": campo, "valor_nuevo": valor}
        if centro:
            r["centro"] = centro.pk
        return r


class CapturaTests(Base):
    def test_dato_general_se_normaliza_y_guarda_valor_actual(self):
        r = self.post(self.sol, "guardar", self.renglon(valor="  nissán  "))
        self.assertContains(r, "Todo está correcto")
        d = Partida.objects.get().modificacion
        self.assertEqual((d.valor_actual, d.valor_nuevo, d.partida.centro), ("FORD", "NISSAN", None))

    def test_dato_general_ignora_el_centro(self):
        self.post(self.sol, "guardar", self.renglon(centro=self.c["mttu"]))
        self.assertIsNone(Partida.objects.get().centro)

    def test_dato_por_centro_pide_centro_y_valida_su_catalogo(self):
        r = self.post(self.sol, "enviar", self.renglon(campo="GRUPO_COMPRAS", valor="G02"))
        self.assertContains(r, "Obligatorio para enviar")
        r = self.post(self.sol, "guardar", self.renglon(campo="GRUPO_COMPRAS", valor="G99", centro=self.c["mttu"]))
        self.assertContains(r, "No es un grupo de compras de MTTU")
        r = self.post(self.sol, "guardar", self.renglon(campo="GRUPO_COMPRAS", valor="g02", centro=self.c["mttu"]))
        self.assertContains(r, "Todo está correcto")
        p = Partida.objects.filter(modificacion__valor_nuevo="G02", centro__isnull=False).last()
        self.assertEqual((p.centro, p.modificacion.valor_actual), (self.c["mttu"], "G01"))

    def test_material_que_no_esta_en_ese_centro(self):
        crear_usuario("sol2", "SOL_MAT", centros=[self.c["mttu"], self.c["meix"]])
        from django.contrib.auth import get_user_model

        r = self.post(get_user_model().objects.get(username="sol2"), "guardar",
                      self.renglon(campo="ALMACEN", valor="RC01", centro=self.c["meix"]))
        self.assertContains(r, "El material no existe en MEIX")

    def test_errores_de_valor(self):
        r = self.post(self.sol, "guardar", self.renglon(campo="MARCA", valor="ford"))
        self.assertContains(r, "Es igual al valor actual")
        r = self.post(self.sol, "guardar", self.renglon(campo="ANIO_MODELO", valor="20A4"))
        self.assertContains(r, "4 dígitos")
        r = self.post(self.sol, "guardar", self.renglon(campo="GRUPO_ARTICULOS", valor="XX"))
        self.assertContains(r, "No existe en el catálogo de grupo de artículos")
        r = self.post(self.sol, "guardar", self.renglon(codigo="999999"))
        self.assertContains(r, "No existe en el catálogo de materiales")

    def test_repetido_en_la_misma_solicitud_y_en_otra_abierta(self):
        r = self.post(self.sol, "guardar", self.renglon(10), self.renglon(20, valor="Chevrolet"))
        self.assertContains(r, "Este dato ya está en la partida 10")
        self.post(self.sol, "enviar", self.renglon())
        r = self.post(self.sol, "enviar", self.renglon(valor="Chevrolet"))
        self.assertContains(r, "Este dato ya se está modificando en MOD_ZRA-")

    def test_servicio_solo_descripcion_y_grupo(self):
        r = self.post(self.sol, "guardar", self.renglon(campo="MARCA"), tipo="servicios")
        self.assertContains(r, "Seleccione una opción válida")
        r = self.post(self.sol, "enviar", self.renglon(campo="GRUPO_ARTICULOS", valor="GA2"), tipo="servicios")
        self.assertContains(r, "MOD_ZSA-")
        d = Partida.objects.get().modificacion
        self.assertEqual((d.material, d.valor_actual), (self.servicio, "GA1"))  # el servicio, no el material del mismo código

    def test_json_del_material(self):
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:material_mod"), {"codigo": "310001", "tipo": "materiales"}).json()
        self.assertEqual((r["descripcion"], r["valores"]["MARCA"]), ("BALATA", "FORD"))
        self.assertEqual(r["porCentro"][str(self.c["mttu"].pk)]["GRUPO_COMPRAS"], "G01")

    def test_menu_y_pantalla(self):
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:nueva_mod", args=["materiales"]))
        self.assertContains(r, reverse("solicitudes:nueva_mod", args=["servicios"]))  # menú activo
        self.assertEqual(r.content.decode().count('value="validar"'), 1)  # solo el oculto que usa Enter


class FlujoTests(Base):
    def enviar_general_y_por_centro(self):
        self.post(self.sol, "enviar", self.renglon(10), self.renglon(20, campo="GRUPO_COMPRAS", valor="G02", centro=self.c["mttu"]),
                  self.renglon(30, campo="ANIO_MODELO", valor="2024"))
        return Solicitud.objects.get(folio__isnull=False)

    def test_visible_por_centros_donde_existe_el_material(self):
        s = self.enviar_general_y_por_centro()
        self.assertEqual(bandejas.partidas_de(self.val, "val").filter(solicitud=s).count(), 3)
        self.assertEqual(bandejas.partidas_de(self.val_meix, "val").filter(solicitud=s).count(), 0)  # el material no está en MEIX

    def test_aprobar_exportar_excluir_y_finalizar(self):
        s = self.enviar_general_y_por_centro()
        ids = list(s.partidas.order_by("numero").values_list("pk", flat=True))
        flujo.aplicar(self.val, "aprobar", ids)
        self.client.force_login(self.dm)
        r = self.client.post(reverse("solicitudes:exportar_dm"), {"partidas": ids})
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="Mod_Mat.txt"')
        lineas = [l.split("\t") for l in r.content.decode().split("\r\n") if l]
        self.assertEqual(lineas[0][:4], ["Material", "Centro", "Descripción técnica", "Grupo de artículos"])
        general = lineas[1]
        self.assertEqual((general[0], general[1], general[lineas[0].index("Marca")], general[lineas[0].index("Año Modelo")]),
                         ("310001", "", "NISSAN", "2024"))
        por_centro = lineas[2]
        self.assertEqual((por_centro[1], por_centro[lineas[0].index("Grupo de compras")], por_centro[lineas[0].index("Marca")]),
                         ("MTTU", "G02", ""))  # solo el valor nuevo; lo que no cambia va vacío

        excluida = ids[2]
        self.client.post(reverse("solicitudes:accion"), {"accion": "excluir", "partidas": [excluida],
                                                         f"motivo-{excluida}": "SAP lo rechazó", "tab": "dm"})
        r = self.client.post(reverse("solicitudes:finalizar_dm"), {"partidas": ids[:2], "tab": "dm"}, follow=True)
        self.assertContains(r, "2 partida(s) terminada(s)")
        self.material.refresh_from_db()
        self.assertEqual((self.material.marca, self.material.anio_modelo), ("NISSAN", None))
        self.assertEqual(MaterialCentro.objects.get(material=self.material, centro=self.c["mttu"]).grupo_compras, "G02")
        s.refresh_from_db()
        self.assertEqual(s.estado, "TERMINADA")
        fin = Evento.objects.get(partida_id=ids[0], tipo=Evento.Tipo.TERMINACION)
        self.assertEqual(fin.detalle, {"campo": "Marca", "antes": "FORD", "despues": "NISSAN"})
        # Historial del material (pedido de Dave): cada dato modificado, con su folio y quién lo atendió.
        h = self.material.historial.get(campo="Marca")
        self.assertEqual((h.tipo, h.folio, h.antes, h.despues, h.solicitante, h.usuario),
                         ("MODIFICACION", s.folio, "FORD", "NISSAN", s.solicitante, self.dm))
        self.assertEqual(self.material.historial.get(campo="Grupo de compras").centro, "MTTU")

    def test_exportar_un_tipo_a_la_vez(self):
        self.post(self.val, "enviar", self.renglon())
        self.post(self.val, "enviar", self.renglon(campo="DESCRIPCION", valor="Mano de obra fina"), tipo="servicios")
        ids = list(Partida.objects.filter(estado=E.EN_DM).values_list("pk", flat=True))
        self.client.force_login(self.dm)
        r = self.client.post(reverse("solicitudes:exportar_dm"), {"partidas": ids, "tab": "dm"}, follow=True)
        self.assertContains(r, "Exporta un tipo a la vez")
        servicio = Partida.objects.get(solicitud__flujo="MOD_ZSA").pk
        r = self.client.post(reverse("solicitudes:exportar_dm"), {"partidas": [servicio]})
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="Mod_Ser.txt"')
        self.assertEqual(r.content.decode().split("\r\n")[:2],
                         ["Servicio\tDescripción técnica\tGrupo de artículos", "310001\tMANO DE OBRA FINA\t"])

    def test_aprobar_revisa_que_siga_siendo_distinto(self):
        self.post(self.sol, "enviar", self.renglon())
        MaterialSAP.objects.filter(pk=self.material.pk).update(marca="NISSAN")  # alguien ya lo cambió
        p = Partida.objects.get()
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "distinto"):
            flujo.aplicar(self.val, "aprobar", [p.pk])

    def test_devuelta_se_corrige_y_reenvia(self):
        self.post(self.sol, "enviar", self.renglon())
        p = Partida.objects.get()
        flujo.aplicar(self.val, "devolver", [p.pk], {str(p.pk): "Es Nissan Mexicana"})
        url = reverse("solicitudes:corregir", args=[p.solicitud_id])
        self.client.force_login(self.sol)
        datos = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1", "accion": "reenviar", "form-0-pid": p.pk,
                 "form-0-numero": "10", "form-0-codigo_sap": "310001", "form-0-campo": "MARCA", "form-0-valor_nuevo": "Nissan Mexicana"}
        r = self.client.post(url, datos, follow=True)
        self.assertContains(r, "Partidas reenviadas (1 dato(s) corregido(s))")
        p.refresh_from_db()
        self.assertEqual((p.estado, p.modificacion.valor_nuevo), (E.EN_VALIDACION, "NISSAN MEXICANA"))

    def test_detalle_y_bandeja(self):
        s = self.enviar_general_y_por_centro()
        self.client.force_login(self.val)
        r = self.client.get(reverse("solicitudes:detalle", args=[s.pk]))
        self.assertContains(r, "General")
        self.assertContains(r, "NISSAN")
        r = self.client.get(reverse("solicitudes:pendientes"), {"tab": "val"})
        self.assertContains(r, "Modificar 310001 · Marca: «FORD» → «NISSAN»")
