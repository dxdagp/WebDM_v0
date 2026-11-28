"""Datos Maestros atiende desde su bandeja las partidas que van a SAP por TXT (pedido de Dave).

Son las ampliaciones (AMPL_ZRA) y las modificaciones (MOD_ZRA y MOD_ZSA). Las tres se atienden
igual: DM marca partidas de uno o varios folios y

- Exporta un solo TXT con todo lo marcado (no cambia nada; se puede repetir),
- Excluye con motivo (flujo.aplicar "excluir"), o
- Finaliza: cada flujo escribe en el catálogo lo suyo y las partidas pasan a TERMINADA.

Un TXT es de un solo tipo: Amp_Mat.txt, Mod_Mat.txt y Mod_Ser.txt tienen columnas distintas.
"""

from django.db import transaction

from . import alcance, ampliacion, modificacion
from .models import Flujo, Partida

E = Partida.Estado
FLUJOS = (Flujo.AMPL_ZRA, Flujo.MOD_ZRA, Flujo.MOD_ZSA)


def pendientes(usuario):
    """Las partidas de estos flujos que esperan a este DM."""
    return Partida.objects.filter(alcance.de_mis_centros(usuario), solicitud__flujo__in=FLUJOS, estado=E.EN_DM)


def seleccion(usuario, ids):
    """Lo que DM marcó. Todas o ninguna: si algo no es de estos flujos o no le toca, no se hace nada."""
    from .flujo import AccionNoPermitida

    ids = {int(i) for i in ids if str(i).isdigit()}
    if not ids:
        raise AccionNoPermitida("Selecciona al menos una partida.")
    partidas = list(
        pendientes(usuario).filter(pk__in=ids).select_related(
            "solicitud", "centro", "ampliacion__material", "ampliacion__centro_origen", "ampliacion__almacen_destino",
            "ampliacion__almacen_modelo", "ampliacion__planificador", "ampliacion__grupo_compras", "modificacion__material",
        ).order_by("solicitud__folio", "numero")
    )
    if len(partidas) != len(ids):
        sobran = Partida.objects.filter(pk__in=ids - {p.pk for p in partidas}).select_related("solicitud")
        nombres = ", ".join(f"{x.solicitud.folio or 'borrador'}/{x.numero}" for x in sobran[:5])
        raise AccionNoPermitida(
            f"Solo se exportan o finalizan ampliaciones y modificaciones en Datos Maestros. Quita de la selección: {nombres}."
        )
    return partidas


def exportar(usuario, ids):
    """(nombre del archivo, texto) del TXT de lo marcado."""
    from .flujo import AccionNoPermitida

    partidas = seleccion(usuario, ids)
    flujos = {p.solicitud.flujo for p in partidas}
    if len(flujos) > 1:
        raise AccionNoPermitida(
            "Exporta un tipo a la vez (" + ", ".join(sorted(flujos)) + "): cada uno lleva su propio TXT. Filtra por folio, por ejemplo MOD_ZRA."
        )
    tipo = flujos.pop()
    if tipo == Flujo.AMPL_ZRA:
        return ampliacion.NOMBRE_TXT, ampliacion.texto_txt(partidas)
    return modificacion.NOMBRE_TXT[tipo], modificacion.texto_txt(partidas, tipo)


@transaction.atomic
def finalizar(usuario, ids):
    """Termina lo marcado, de uno o varios flujos. Devuelve cuántas partidas terminó."""
    from .flujo import AccionNoPermitida, actualizar_cabecera, roles_de

    if "DM" not in roles_de(usuario):
        raise AccionNoPermitida("Necesitas el rol DM.")
    seleccion(usuario, ids)  # revisa todo lo marcado antes de bloquear
    # SELECT … FOR UPDATE de las partidas (solo de su tabla: of=("self",)), y se vuelven a leer ya bloqueadas.
    bloqueadas = [p.pk for p in Partida.objects.select_for_update(of=("self",)).filter(pk__in=ids).order_by("pk")]
    partidas = seleccion(usuario, bloqueadas)
    ampl = [p for p in partidas if p.solicitud.flujo == Flujo.AMPL_ZRA]
    mod = [p for p in partidas if p.solicitud.flujo != Flujo.AMPL_ZRA]
    ampliacion.finalizar_partidas(usuario, ampl)
    modificacion.finalizar_partidas(usuario, mod)
    for cabecera in {p.solicitud_id: p.solicitud for p in partidas}.values():
        actualizar_cabecera(cabecera, usuario)  # cada folio pasa a TERMINADA si ya no le queda nada
    return len(partidas)
