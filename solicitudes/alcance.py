"""Qué partidas le tocan a un VAL_MAT o a un DM según sus Centros autorizados.

Hasta la fase 4c toda partida tenía Centro y la regla era simple: "la partida es de uno de mis
Centros". Las modificaciones (MOD_ZRA y MOD_ZSA) traen datos GENERALES del material, que no
son de ningún Centro (descripción, marca, año…). Para esas partidas, sin Centro, la regla es:

- MOD_ZRA: le tocan a quien tenga autorizado alguno de los Centros donde existe el material.
- MOD_ZSA: los servicios no tienen Centro, así que le tocan a cualquier VAL_MAT o DM.

Todas las bandejas y revisiones de alcance usan estas dos funciones, así la regla vive en un solo lugar.
"""

from django.db.models import Exists, OuterRef, Q

from catalogo_sap.models import MaterialCentro


def de_mis_centros(usuario):
    """Filtro (Q) para Partida.objects.filter(...): las partidas al alcance de `usuario`.

    SQL que genera, más o menos:
        WHERE centro_id IN (mis centros)
           OR (centro_id IS NULL AND (material.es_servicio
               OR EXISTS (SELECT 1 FROM catalogo_sap_materialcentro mc
                          WHERE mc.material_id = modificacion.material_id AND mc.centro_id IN (mis centros))))
    EXISTS no repite renglones aunque el material esté en varios de mis Centros.
    """
    mis = usuario.centros.values("pk")
    en_mis_centros = Exists(MaterialCentro.objects.filter(material=OuterRef("modificacion__material"), centro__in=mis))
    return Q(centro__in=mis) | (Q(centro__isnull=True) & (Q(modificacion__material__es_servicio=True) | en_mis_centros))


def en_mi_alcance(usuario, partida):
    """Lo mismo que de_mis_centros(), para una sola partida ya cargada."""
    mis = set(usuario.centros.values_list("pk", flat=True))
    if partida.centro_id is not None:
        return partida.centro_id in mis
    detalle = getattr(partida, "modificacion", None)
    if detalle is None or detalle.material_id is None:
        return False
    if detalle.material.es_servicio:
        return True
    return MaterialCentro.objects.filter(material_id=detalle.material_id, centro__in=mis).exists()
