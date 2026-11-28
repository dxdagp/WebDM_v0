"""Pruebas de la máquina de estados (fase 3): acciones en bloque, todo o nada, Código SAP."""

import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase

from catalogo_sap.models import MaterialCentro, MaterialSAP
from solicitudes import flujo
from solicitudes.models import DetalleAlta, Evento, Partida, Solicitud

from .datos import crear_catalogos, crear_enviada, crear_usuario

E = Partida.Estado


class AccionesValidadorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])

    def setUp(self):
        self.solicitud = crear_enviada(self.c, self.sol, n=3)
        self.ids = list(self.solicitud.partidas.values_list("pk", flat=True))

    def estados(self):
        return list(self.solicitud.partidas.order_by("numero").values_list("estado", flat=True))

    def test_aprobar_varias_a_la_vez(self):
        self.assertEqual(flujo.aplicar(self.val, "aprobar", self.ids), 3)
        self.assertEqual(self.estados(), [E.EN_DM] * 3)
        self.assertEqual(Evento.objects.filter(tipo=Evento.Tipo.APROBACION).count(), 3)

    def test_devolver_exige_motivo_y_lo_guarda(self):
        with self.assertRaises(flujo.AccionNoPermitida):
            flujo.aplicar(self.val, "devolver", self.ids, motivo="   ")
        flujo.aplicar(self.val, "devolver", self.ids[:2], motivo="Falta foto")
        self.assertEqual(self.estados(), [E.DEVUELTA_SOL, E.DEVUELTA_SOL, E.EN_VALIDACION])
        p = Partida.objects.get(pk=self.ids[0])
        self.assertIsNotNone(p.ultima_devolucion)
        self.assertEqual(p.eventos.get(tipo=Evento.Tipo.DEVOLUCION).motivo, "Falta foto")

    def test_todo_o_nada_si_una_ya_se_movio(self):
        Partida.objects.filter(pk=self.ids[0]).update(estado=E.CANCELADA)
        with self.assertRaises(flujo.AccionNoPermitida):
            flujo.aplicar(self.val, "aprobar", self.ids)
        self.assertEqual(self.estados(), [E.CANCELADA, E.EN_VALIDACION, E.EN_VALIDACION])

    def test_aprobar_exige_partida_completa(self):
        DetalleAlta.objects.filter(partida_id=self.ids[1]).update(marca="")
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "marca"):
            flujo.aplicar(self.val, "aprobar", self.ids)
        self.assertEqual(self.estados(), [E.EN_VALIDACION] * 3)

    def test_rol_y_centro(self):
        with self.assertRaises(flujo.AccionNoPermitida):
            flujo.aplicar(self.sol, "aprobar", self.ids)  # no es VAL_MAT
        otro = crear_usuario("val2", "VAL_MAT", centros=[self.c["meix"]])
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "Centro"):
            flujo.aplicar(otro, "aprobar", self.ids)

    def test_dm_no_puede_cancelar_ni_devolver_al_solicitante(self):
        flujo.aplicar(self.val, "aprobar", self.ids)
        for accion in ("cancelar", "devolver"):
            with self.assertRaises(flujo.AccionNoPermitida):
                flujo.aplicar(self.dm, accion, self.ids, motivo="x")
        flujo.aplicar(self.dm, "devolver_a_validacion", self.ids, motivo="Revisar UMB")
        self.assertEqual(self.estados(), [E.EN_VALIDACION] * 3)

    def test_cancelar_todas_termina_la_cabecera(self):
        flujo.aplicar(self.val, "cancelar", self.ids, motivo="Duplicadas")
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.TERMINADA)

    def test_reenviar_y_cancelar_propias(self):
        flujo.aplicar(self.val, "devolver", self.ids, motivo="Corrige")
        with self.assertRaises(flujo.AccionNoPermitida):
            flujo.aplicar(self.val, "reenviar", self.ids)  # no es el solicitante… ni SOL_MAT
        flujo.aplicar(self.sol, "reenviar", self.ids[:2])
        flujo.aplicar(self.sol, "cancelar_propia", self.ids[2:], motivo="Ya no se necesita")
        self.assertEqual(self.estados(), [E.EN_VALIDACION, E.EN_VALIDACION, E.CANCELADA])


class CodigoSapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])

    def setUp(self):
        self.solicitud = crear_enviada(self.c, self.sol, n=2, estado=E.EN_DM)
        self.p1, self.p2 = self.solicitud.partidas.order_by("numero")

    def test_terminar_crea_material_en_catalogo(self):
        flujo.terminar_con_codigos(self.dm, {self.p1.pk: "100001", self.p2.pk: ""})
        self.p1.refresh_from_db()
        self.p2.refresh_from_db()
        self.assertEqual(self.p1.estado, E.TERMINADA)
        self.assertEqual(self.p2.estado, E.EN_DM)  # sin código: se queda
        material = MaterialSAP.objects.get(codigo="100001")
        self.assertEqual(material.origen, MaterialSAP.Origen.WEBDM)
        self.assertEqual(material.folio_origen, self.solicitud.folio)
        self.assertTrue(MaterialCentro.objects.filter(material=material, centro=self.c["mttu"]).exists())
        # La cabecera sigue en proceso: una partida aún está en DM.
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.EN_PROCESO)

    def test_codigos_con_error_no_terminan_ninguna(self):
        MaterialSAP.objects.create(codigo="200000", descripcion="X", tipo_material="ZRA", origen="IMPORT",
                                   creado_por=self.dm)
        casos = [
            ({self.p1.pk: "12345", self.p2.pk: "100002"}, self.p1.pk),  # 5 dígitos
            ({self.p1.pk: "200000", self.p2.pk: "100002"}, self.p1.pk),  # ya existe en el catálogo
            ({self.p1.pk: "100003", self.p2.pk: "100003"}, self.p2.pk),  # repetido en la misma captura
        ]
        for codigos, con_error in casos:
            with self.assertRaises(flujo.ErroresCodigo) as ctx:
                flujo.terminar_con_codigos(self.dm, codigos)
            self.assertEqual(list(ctx.exception.errores), [con_error])
        self.assertEqual(Partida.objects.filter(estado=E.TERMINADA).count(), 0)

    def test_terminar_todas_termina_cabecera(self):
        flujo.terminar_con_codigos(self.dm, {self.p1.pk: "100001", self.p2.pk: "100002"})
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado, Solicitud.Estado.TERMINADA)

    def test_corregir_codigo_conserva_centros(self):
        flujo.terminar_con_codigos(self.dm, {self.p1.pk: "100001"})
        material_id = MaterialSAP.objects.get(codigo="100001").pk
        with self.assertRaises(flujo.AccionNoPermitida):
            flujo.corregir_codigo(self.dm, self.p1.pk, "100009", motivo="")
        flujo.corregir_codigo(self.dm, self.p1.pk, "100009", motivo="Se capturó mal")
        material = MaterialSAP.objects.get(pk=material_id)
        self.assertEqual(material.codigo, "100009")
        self.assertEqual(material.centros.count(), 1)
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.alta.codigo_sap, "100009")
        evento = self.p1.eventos.get(tipo=Evento.Tipo.CORRECCION_CODIGO_SAP)
        self.assertEqual(evento.detalle, {"antes": "100001", "despues": "100009"})
        self.assertEqual(list(material.historial.order_by("fecha", "id").values_list("tipo", "folio", "centro", "campo", "antes", "despues")), [
            ("ALTA", self.solicitud.folio, self.p1.centro.codigo, "", "", ""),
            ("CORRECCION_CODIGO", self.solicitud.folio, "", "Código SAP", "100001", "100009"),
        ])


class ValidadoresSimultaneosTests(TransactionTestCase):
    """Dos validadores actúan sobre las mismas partidas al mismo tiempo: solo uno gana."""

    def test_aprobar_y_devolver_a_la_vez(self):
        c = crear_catalogos()
        sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        v1 = crear_usuario("v1", "VAL_MAT", centros=[c["mttu"]])
        v2 = crear_usuario("v2", "VAL_MAT", centros=[c["mttu"]])
        ids = list(crear_enviada(c, sol, n=3).partidas.values_list("pk", flat=True))
        resultados, barrera = [], threading.Barrier(2)

        def actuar(usuario, accion):
            barrera.wait()
            try:
                flujo.aplicar(usuario, accion, ids, motivo="x")
                resultados.append(accion)
            except flujo.AccionNoPermitida:
                resultados.append("rechazada")
            finally:
                connection.close()

        hilos = [threading.Thread(target=actuar, args=(v1, "aprobar")),
                 threading.Thread(target=actuar, args=(v2, "devolver"))]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        self.assertEqual(sorted(resultados).count("rechazada"), 1)
        ganadora = next(r for r in resultados if r != "rechazada")
        esperado = E.EN_DM if ganadora == "aprobar" else E.DEVUELTA_SOL
        self.assertEqual(set(Partida.objects.values_list("estado", flat=True)), {esperado})
        # Una sola acción quedó registrada por partida.
        self.assertEqual(Evento.objects.exclude(tipo=Evento.Tipo.ENVIO).count(), 3)
