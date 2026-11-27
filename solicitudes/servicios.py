"""Lógica de negocio de AMAT_ZRA: guardar borrador y enviar.

Se separa de las vistas a propósito: las vistas solo leen la petición y
deciden qué pantalla mostrar; aquí vive lo que dice la Revisión 3. Así se
puede probar sin navegador y reutilizar desde otras pantallas.
"""

from django.db import transaction
from django.utils import timezone

from catalogos.models import Almacen

from .folios import siguiente_folio
from .models import DetalleAlta, Evento, Flujo, Partida, Solicitud

CAMPOS_DETALLE = [
    "descripcion", "ubicacion", "no_parte_original", "tipo_unidad", "marca", "version", "anio_modelo",
    "compatibilidad", "umb", "grupo_articulos", "categoria_valoracion", "grupo_compras",
]


def puede_capturar(usuario):
    return usuario.groups.filter(name__in=["SOL_MAT", "VAL_MAT"]).exists()


def _reemplazar_partidas(solicitud, formset):
    """Borra las partidas del borrador y las vuelve a crear desde la tabla.

    Se vale borrar porque un BORRADOR nunca entró al flujo formal
    (Revisión 3: "lo que nunca entró al flujo puede eliminarse").
    """
    solicitud.partidas.all().delete()  # CASCADE borra también sus DetalleAlta
    for form in formset.renglones:
        datos = form.cleaned_data
        partida = Partida.objects.create(solicitud=solicitud, numero=datos["numero"], centro=datos["centro"])
        detalle = DetalleAlta(partida=partida, **{c: datos.get(c) for c in CAMPOS_DETALLE})
        # Campos automáticos (no se capturan):
        if detalle.categoria_valoracion:
            detalle.tipo_material = detalle.categoria_valoracion.tipo_material
        if partida.centro:
            detalle.almacen = Almacen.objects.filter(centro=partida.centro, predeterminado=True, activo=True).first()
        detalle.save()


@transaction.atomic
def guardar_borrador(usuario, formset, solicitud=None):
    """Crea o actualiza un borrador. El formset ya debe ser válido (sin valores inválidos)."""
    if solicitud is None:
        solicitud = Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=usuario)
        Evento.objects.create(solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.CREACION)
    _reemplazar_partidas(solicitud, formset)
    return solicitud


@transaction.atomic
def enviar(usuario, formset, solicitud=None):
    """Primer envío: guarda, asigna folio y mete cada partida al flujo.

    @transaction.atomic hace que TODO esto sea una sola transacción: si algo
    falla a la mitad, PostgreSQL deshace todo, incluido el consecutivo del folio.
    """
    solicitud = guardar_borrador(usuario, formset, solicitud)

    # Si quien envía es VAL_MAT, sus partidas pasan directo a DM (Revisión 3, sección 4).
    directo_a_dm = usuario.groups.filter(name="VAL_MAT").exists()
    estado_nuevo = Partida.Estado.EN_DM if directo_a_dm else Partida.Estado.EN_VALIDACION

    solicitud.folio = siguiente_folio(Flujo.AMAT_ZRA)
    solicitud.estado = Solicitud.Estado.EN_PROCESO
    solicitud.enviada = timezone.now()
    solicitud.save()

    for partida in solicitud.partidas.all():
        partida.estado = estado_nuevo
        partida.save(update_fields=["estado", "actualizada"])
        Evento.objects.create(
            solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.ENVIO,
            estado_anterior=Partida.Estado.BORRADOR, estado_nuevo=estado_nuevo,
        )
    return solicitud
