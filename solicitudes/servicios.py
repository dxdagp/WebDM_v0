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


# --- Fase 3: corrección de partidas ya enviadas -----------------------------------------


def partidas_editables(usuario, solicitud):
    """Partidas de `solicitud` que `usuario` puede corregir ahora (Revisión 3, sección 4).

    - Su solicitante, las DEVUELTA_SOL.
    - VAL_MAT, las EN_VALIDACION de sus Centros autorizados.
    """
    roles = set(usuario.groups.values_list("name", flat=True))
    editables = Partida.objects.none()
    if solicitud.solicitante_id == usuario.pk and roles & {"SOL_MAT", "VAL_MAT"}:
        editables = editables | solicitud.partidas.filter(estado=Partida.Estado.DEVUELTA_SOL)
    if "VAL_MAT" in roles:
        editables = editables | solicitud.partidas.filter(
            estado=Partida.Estado.EN_VALIDACION, centro__in=usuario.centros.values("pk")
        )
    return editables.order_by("numero")


def _valor_legible(valor):
    return "" if valor is None else str(valor)


@transaction.atomic
def guardar_correcciones(usuario, formset, solicitud):
    """Aplica los cambios de la tabla de corrección. Devuelve cuántos campos cambiaron.

    Cada campo que cambió deja un Evento CAMBIO_CAMPO con su valor anterior y el nuevo.
    Lo que no cambió no se registra (no se guarda cada clic, sección 15).
    """
    # Se vuelven a calcular DENTRO de la transacción y con FOR UPDATE: si mientras el
    # usuario editaba alguien aprobó la partida, ya no es editable y no se toca.
    permitidas = {p.pk: p for p in partidas_editables(usuario, solicitud).select_for_update()}
    cambios = 0
    for form in formset.renglones:
        datos = form.cleaned_data
        partida = permitidas.get(datos["pid"])
        if partida is None:
            raise PermissionError("Una de las partidas ya no está disponible para corregir. Recarga la página.")
        alta = partida.alta
        nuevos = {c: datos.get(c) for c in CAMPOS_DETALLE}
        nuevos["centro"] = datos.get("centro")
        for campo, nuevo in nuevos.items():
            destino = partida if campo == "centro" else alta
            actual = getattr(destino, campo)
            if actual == nuevo:
                continue
            Evento.objects.create(
                solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.CAMBIO_CAMPO,
                estado_anterior=partida.estado, estado_nuevo=partida.estado,
                detalle={"campo": campo, "antes": _valor_legible(actual), "despues": _valor_legible(nuevo)},
            )
            setattr(destino, campo, nuevo)
            cambios += 1
        # Los automáticos se recalculan siempre en el servidor.
        alta.tipo_material = alta.categoria_valoracion.tipo_material if alta.categoria_valoracion else None
        alta.almacen = (
            Almacen.objects.filter(centro=partida.centro, predeterminado=True, activo=True).first()
            if partida.centro else None
        )
        partida.save()
        alta.save()
    return cambios
