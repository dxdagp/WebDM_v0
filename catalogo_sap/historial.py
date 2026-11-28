"""Escribe el historial de un material del catálogo (HistorialMaterial).

Una función por momento en que el catálogo cambia. Cada una hace un INSERT en
catalogo_sap_historialmaterial; importar usa bulk_create (un INSERT con muchos VALUES).
"""

from .models import HistorialMaterial, MaterialSAP

H = HistorialMaterial.Tipo
WEBDM, IMPORT = MaterialSAP.Origen.WEBDM, MaterialSAP.Origen.IMPORT


def _de_partida(partida):
    """Folio, partida y solicitante de un movimiento que viene de una solicitud de WebDM."""
    return {"origen": WEBDM, "partida": partida, "folio": partida.solicitud.folio or "",
            "solicitante_id": partida.solicitud.solicitante_id}


def alta_webdm(material, usuario, partida):
    """DM terminó un alta (AMAT_ZRA o ASER_ZSA) con su Código SAP."""
    return HistorialMaterial.objects.create(
        material=material, tipo=H.ALTA, usuario=usuario, centro=partida.centro.codigo if partida.centro else "",
        **_de_partida(partida))


def ampliacion_webdm(material, usuario, partida):
    """DM finalizó una AMPL_ZRA: el material ya existe en el Centro nuevo."""
    return HistorialMaterial.objects.create(
        material=material, tipo=H.AMPLIACION, usuario=usuario, centro=partida.centro.codigo, **_de_partida(partida))


def modificacion_webdm(material, usuario, partida, campo, antes, despues):
    """DM finalizó una MOD_ZRA / MOD_ZSA: el dato cambió en el catálogo."""
    return HistorialMaterial.objects.create(
        material=material, tipo=H.MODIFICACION, usuario=usuario, centro=partida.centro.codigo if partida.centro else "",
        campo=campo, antes=antes[:100], despues=despues[:100], **_de_partida(partida))


def correccion_codigo(material, usuario, partida, antes, despues):
    """DM corrigió el Código SAP de un alta ya terminada."""
    return HistorialMaterial.objects.create(
        material=material, tipo=H.CORRECCION_CODIGO, usuario=usuario, campo="Código SAP", antes=antes, despues=despues,
        **_de_partida(partida))


def importados(importacion, nuevos, centros):
    """Importación del TXT de SAP.

    nuevos  = materiales creados por esta importación (ya con id).
    centros = [(material_id, código de Centro)] de cada renglón importado, en el orden del archivo.
    El primer Centro de un material nuevo es su alta; los siguientes, y los de materiales que ya
    existían, son ampliaciones.
    """
    base = {"origen": IMPORT, "importacion": importacion, "folio": importacion.nombre_archivo[:30],
            "usuario_id": importacion.usuario_id, "fecha": importacion.fecha}
    sin_alta = {m.pk for m in nuevos}
    movimientos = []
    for material_id, centro in centros:
        tipo = H.ALTA if material_id in sin_alta else H.AMPLIACION
        sin_alta.discard(material_id)
        movimientos.append(HistorialMaterial(material_id=material_id, tipo=tipo, centro=centro, **base))
    # Servicios (sin Centro): solo su alta.
    movimientos += [HistorialMaterial(material_id=pk, tipo=H.ALTA, **base) for pk in sin_alta]
    HistorialMaterial.objects.bulk_create(movimientos, batch_size=1000)
