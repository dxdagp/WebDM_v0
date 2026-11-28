"""Qué partidas esperan a cada rol ("Pendientes de mi atención", Revisión 3, sección 15).

Una pestaña por rol. Cada función devuelve un QuerySet: una consulta que
todavía no se ejecuta. Así la misma función sirve para listar las partidas
(la tabla de la bandeja) y para contarlas (el número del menú lateral, con COUNT).
"""

from django.db.models import OuterRef, Subquery

from . import alcance
from .flujo import roles_de
from .models import Evento, Partida

E = Partida.Estado

# (clave en la URL, rol, título de la pestaña)
PESTANAS = [
    ("sol", "SOL_MAT", "Por corregir"),
    ("val", "VAL_MAT", "Por validar"),
    ("dm", "DM", "Datos Maestros"),
]


def partidas_de(usuario, clave):
    """Partidas de la pestaña `clave` para `usuario`, sin ejecutar la consulta."""
    if clave == "sol":
        # Lo que me devolvieron a mí, sin importar el Centro.
        return Partida.objects.filter(solicitud__solicitante=usuario, estado=E.DEVUELTA_SOL)
    estado = {"val": E.EN_VALIDACION, "dm": E.EN_DM}[clave]
    # Solo mis Centros autorizados (ver alcance.py: las modificaciones generales no tienen Centro).
    return Partida.objects.filter(alcance.de_mis_centros(usuario), estado=estado)


def pestanas_de(usuario):
    """Pestañas visibles para el usuario según sus roles."""
    roles = roles_de(usuario)
    return [(clave, titulo) for clave, rol, titulo in PESTANAS if rol in roles]


def contar(usuario):
    """Total de pendientes del usuario para el contador del menú."""
    return sum(partidas_de(usuario, clave).count() for clave, _ in pestanas_de(usuario))


def con_datos_de_tabla(queryset):
    """Agrega lo que muestra la tabla: datos del folio, del detalle y el último motivo."""
    ultimo_motivo = (
        Evento.objects.filter(partida=OuterRef("pk"), tipo=Evento.Tipo.DEVOLUCION).order_by("-fecha").values("motivo")[:1]
    )
    return (
        queryset.select_related("solicitud__solicitante", "centro", "alta__grupo_articulos", "alta__umb",
                                 "ampliacion__material", "ampliacion__centro_origen",
                                 "modificacion__material", "servicio__umb", "servicio__tipo_material", "servicio__grupo_articulos")
        # Subquery = un SELECT dentro del SELECT: para cada partida trae el motivo de su devolución más reciente.
        .annotate(ultimo_motivo=Subquery(ultimo_motivo))
        .order_by("actualizada")
    )


def centros_sin_rol(ids, rol):
    """Centros de las partidas `ids` que no tienen ningún usuario activo con `rol`.

    Sirve para avisar, por ejemplo al aprobar, que nadie de DM verá esas partidas
    porque ningún usuario DM tiene ese Centro autorizado.
    """
    from catalogos.models import Centro
    from usuarios.models import Usuario

    # Centros que SÍ tienen a alguien: los de usuarios activos con ese rol.
    # centros__isnull=False importa: un NULL dentro de "NOT IN (…)" hace que SQL no devuelva NADA.
    atendidos = Usuario.objects.filter(groups__name=rol, is_active=True, centros__isnull=False).values("centros")
    return list(
        Centro.objects.filter(partida__pk__in=ids).exclude(pk__in=atendidos).distinct().values_list("codigo", flat=True)
    )
