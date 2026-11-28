"""Fase 4e: ASER_ZSA, alta de servicios (decisiones de Dave, 28-nov-2026)."""

from django.test import TestCase
from django.urls import reverse

from catalogo_sap.models import MaterialSAP
from catalogos.models import TipoMaterial, UMB
from solicitudes import bandejas, flujo
from solicitudes.models import Evento, Partida, Solicitud

from .datos import crear_catalogos, crear_usuario

E = Partida.Estado


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = c = crear_catalogos()  # UMB PZA, grupo de artículos GA1
        cls.ser = UMB.objects.create(codigo="SER", descripcion="Servicio")
        TipoMaterial.objects.create(codigo="ZSA", descripcion="Servicios", umb_predeterminada=cls.ser)
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[c["meix"]])  # sin el Centro del solicitante: igual lo ve
        cls.dm = crear_usuario("dm", "DM", centros=[c["meix"]])
        MaterialSAP.objects.create(codigo="900001", descripcion="MANO DE OBRA FRENOS", tipo_material="ZSA",
                                   es_servicio=True, origen="IMPORT", creado_por=cls.dm)
        # Un MATERIAL con el código que usará el servicio: no choca, son catálogos distintos.
        MaterialSAP.objects.create(codigo="900002", descripcion="BALATA", tipo_material="ZRA", origen="IMPORT", creado_por=cls.dm)

    def post(self, usuario, accion, *renglones, url=None):
        datos = {"form-TOTAL_FORMS": str(len(renglones)), "form-INITIAL_FORMS": "0", "accion": accion}
        for i, r in enumerate(renglones):
            for k, v in r.items():
                datos[f"form-{i}-{k}"] = v
        self.client.force_login(usuario)
        return self.client.post(url or reverse("solicitudes:nueva_aser"), datos, follow=True)

    def renglon(self, numero=10, descripcion="Alineación y balanceo", umb="", grupo=None):
        return {"numero": numero, "descripcion": descripcion, "umb": umb,
                "grupo_articulos": (grupo or self.c["grupo_art"]).pk}


class CapturaTests(Base):
    def test_pantalla_propone_umb_y_menu(self):
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:nueva_aser"))
        self.assertContains(r, f'<option value="{self.ser.pk}" selected>')
        self.assertContains(r, 'href="/solicitudes/aser/nueva/" class="activa"')
        self.assertEqual(r.content.decode().count('value="validar"'), 1)

    def test_guarda_normalizado_con_umb_propuesta(self):
        r = self.post(self.sol, "guardar", self.renglon())
        self.assertContains(r, "Todo está correcto")
        d = Partida.objects.get().servicio
        self.assertEqual((d.descripcion, d.umb, d.partida.centro), ("ALINEACION Y BALANCEO", self.ser, None))

    def test_obligatorios_y_repetidos(self):
        r = self.post(self.sol, "enviar", {"numero": 10, "descripcion": "Lavado"})
        self.assertContains(r, "Obligatorio para enviar")
        r = self.post(self.sol, "guardar", self.renglon(10), self.renglon(20))
        self.assertContains(r, "Descripción repetida (partida 10)")

    def test_duplicado_en_catalogo_de_servicios(self):
        r = self.post(self.sol, "enviar", self.renglon(descripcion="mano de obra frenos"))
        self.assertContains(r, "Ya existe el servicio 900001 con esta descripción")
        self.assertFalse(Solicitud.objects.filter(folio__isnull=False).exists())
        r = self.post(self.sol, "enviar", self.renglon(descripcion="Mano de obra de frenos traseros"))
        self.assertContains(r, "se parece al servicio 900001")
        self.assertContains(r, "ASER_ZSA-")  # un parecido solo avisa

    def test_sin_umb_predeterminada_avisa(self):
        TipoMaterial.objects.filter(codigo="ZSA").update(umb_predeterminada=None)
        self.client.force_login(self.sol)
        self.assertContains(self.client.get(reverse("solicitudes:nueva_aser")), "no tiene UMB predeterminada")
        r = self.post(self.sol, "enviar", self.renglon())
        self.assertContains(r, "Obligatorio para enviar")


class FlujoTests(Base):
    def enviada(self):
        self.post(self.sol, "enviar", self.renglon(10), self.renglon(20, descripcion="Lavado de motor"))
        return Solicitud.objects.get(folio__isnull=False)

    def test_cualquier_validador_la_ve(self):
        s = self.enviada()
        self.assertEqual(bandejas.partidas_de(self.val, "val").filter(solicitud=s).count(), 2)
        self.client.force_login(self.val)
        r = self.client.get(reverse("solicitudes:pendientes"), {"tab": "val"})
        self.assertContains(r, "Servicio · ALINEACION Y BALANCEO")

    def test_dm_exporta_y_termina_con_codigo(self):
        s = self.enviada()
        p10, p20 = s.partidas.order_by("numero")
        flujo.aplicar(self.val, "aprobar", [p10.pk, p20.pk])
        self.client.force_login(self.dm)
        r = self.client.get(reverse("solicitudes:pendientes"), {"tab": "dm"})
        self.assertContains(r, f'name="codigo-{p10.pk}"')
        self.assertContains(r, "Exportar TXT")
        # TXT con el código que DM escribió en el renglón (aún sin terminar).
        r = self.client.post(reverse("solicitudes:exportar_dm"), {"partidas": [p10.pk, p20.pk], f"codigo-{p10.pk}": "900002"})
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="Alta_Ser.txt"')
        self.assertEqual(r.content.decode().split("\r\n")[:3], [
            "Código SAP\tDescripción\tUMB\tGrupo de artículos",
            "900002\tALINEACION Y BALANCEO\tSER\tGA1",
            "\tLAVADO DE MOTOR\tSER\tGA1",
        ])
        p10.refresh_from_db()
        self.assertEqual(p10.estado, E.EN_DM)  # exportar no cambia nada

        r = self.client.post(reverse("solicitudes:terminar_dm"), {f"codigo-{p10.pk}": "900001", "tab": "dm"}, follow=True)
        self.assertContains(r, "Este Código SAP ya existe en servicios")
        # 900002 es un MATERIAL, no un servicio: sí se puede.
        r = self.client.post(reverse("solicitudes:terminar_dm"), {f"codigo-{p10.pk}": "900002", "tab": "dm"}, follow=True)
        self.assertContains(r, "1 partida(s) terminada(s)")
        servicio = MaterialSAP.objects.get(codigo="900002", es_servicio=True)
        self.assertEqual((servicio.descripcion, servicio.tipo_material, servicio.umb, servicio.grupo_articulos, servicio.origen),
                         ("ALINEACION Y BALANCEO", "ZSA", "SER", "GA1", "WEBDM"))
        self.assertFalse(servicio.centros.exists())
        self.assertTrue(Evento.objects.filter(partida=p10, tipo=Evento.Tipo.CODIGO_SAP).exists())

    def test_aprobar_revisa_duplicados(self):
        s = self.enviada()
        MaterialSAP.objects.create(codigo="900003", descripcion="LAVADO DE MOTOR", tipo_material="ZSA",
                                   es_servicio=True, origen="IMPORT", creado_por=self.dm)
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "900003"):
            flujo.aplicar(self.val, "aprobar", list(s.partidas.values_list("pk", flat=True)))

    def test_devuelta_se_corrige_y_reenvia(self):
        s = self.enviada()
        p = s.partidas.get(numero=10)
        flujo.aplicar(self.val, "devolver", [p.pk], {str(p.pk): "Falta detalle"})
        self.client.force_login(self.sol)
        datos = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1", "accion": "reenviar", "form-0-pid": p.pk,
                 "form-0-numero": "10", "form-0-descripcion": "Alineación 3D", "form-0-umb": self.ser.pk,
                 "form-0-grupo_articulos": self.c["grupo_art"].pk}
        r = self.client.post(reverse("solicitudes:corregir", args=[s.pk]), datos, follow=True)
        self.assertContains(r, "Partidas reenviadas (1 campo(s) corregido(s))")
        p.refresh_from_db()
        self.assertEqual((p.estado, p.servicio.descripcion), (E.EN_VALIDACION, "ALINEACION 3D"))

    def test_detalle(self):
        s = self.enviada()
        self.client.force_login(self.sol)
        r = self.client.get(reverse("solicitudes:detalle", args=[s.pk]))
        self.assertContains(r, "LAVADO DE MOTOR")
        self.assertContains(r, "<td>SER</td>", html=False)
