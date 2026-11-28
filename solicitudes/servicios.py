"""Lógica de negocio de AMAT_ZRA: guardar borrador y enviar.

Se separa de las vistas a propósito: las vistas solo leen la petición y
deciden qué pantalla mostrar; aquí vive lo que dice la Revisión 3. Así se
puede probar sin navegador y reutilizar desde otras pantallas.
"""

from django.db import transaction
from django.utils import timezone

from catalogos.models import Almacen

from .alcance import de_mis_centros
from . import duplicados
from .folios import siguiente_folio
from .models import DetalleAlta, Evento, Flujo, ImagenPartida, Partida, Solicitud

CAMPOS_DETALLE = [
    "descripcion", "umb", "grupo_compras", "grupo_articulos", "categoria_valoracion", "ubicacion",
    "no_parte_original", "tipo_unidad", "marca", "version", "anio_modelo", "compatibilidad", "almacen",
]


def almacen_predeterminado(centro, memo=None):
    """El almacén que se propone para un Centro: el predeterminado; si no hay, el primero
    activo por código (pedido de Dave: proponer el primer dato que aparezca).

    SQL: ... WHERE centro_id = 3 AND activo ORDER BY predeterminado DESC, codigo LIMIT 1
    (en PostgreSQL TRUE va después de FALSE, por eso DESC pone primero al predeterminado).
    """
    if not centro:
        return None
    if memo is not None and centro.pk in memo:  # en una tabla grande: una consulta por Centro, no por renglón
        return memo[centro.pk]
    almacen = Almacen.objects.filter(centro=centro, activo=True).order_by("-predeterminado", "codigo").first()
    if memo is not None:
        memo[centro.pk] = almacen
    return almacen


def puede_capturar(usuario):
    return usuario.groups.filter(name__in=["SOL_MAT", "VAL_MAT"]).exists()


def _reemplazar_partidas(solicitud, formset):
    """Hace que las partidas del borrador queden igual que la tabla.

    Se identifican por su NÚMERO de partida (10, 20, 30…):
    - número que ya existía: se actualizan sus datos (UPDATE) y conserva sus imágenes;
    - número nuevo: se crea (INSERT);
    - número que ya no está en la tabla: se borra con sus imágenes (DELETE).
    Se vale borrar porque un BORRADOR nunca entró al flujo formal
    (Revisión 3: "lo que nunca entró al flujo puede eliminarse").

    Hasta la fase 3 se borraban todas y se volvían a crear; con imágenes eso ya no
    sirve, porque el CASCADE se llevaría las fotos en cada "Guardar borrador".
    """
    existentes = {p.numero: p for p in solicitud.partidas.select_related("alta")}
    memo = {}
    for form in formset.renglones:
        datos = form.cleaned_data
        partida = existentes.pop(datos["numero"], None)
        if partida is None:
            partida = Partida.objects.create(solicitud=solicitud, numero=datos["numero"], centro=datos["centro"])
            detalle = DetalleAlta(partida=partida)
        else:
            partida.centro = datos["centro"]
            partida.save(update_fields=["centro", "actualizada"])
            detalle = partida.alta
        for c in CAMPOS_DETALLE:
            setattr(detalle, c, datos.get(c))
        # Campos automáticos (no se capturan):
        detalle.tipo_material = detalle.categoria_valoracion.tipo_material if detalle.categoria_valoracion else None
        if detalle.almacen is None:  # vacío = el predeterminado del Centro
            detalle.almacen = almacen_predeterminado(partida.centro, memo)
        detalle.save()
    for sobrante in existentes.values():
        borrar_archivos_al_confirmar(sobrante.imagenes.all())
        sobrante.delete()  # CASCADE borra su DetalleAlta y los renglones de sus imágenes


@transaction.atomic
def eliminar_borrador(solicitud):
    """Borra un BORRADOR completo: cabecera, partidas, detalle, eventos e imágenes.
    Solo BORRADOR: lo que ya entró al flujo nunca se borra (se cancela)."""
    if solicitud.estado != Solicitud.Estado.BORRADOR:
        raise ValueError("Solo se puede eliminar un borrador.")
    borrar_archivos_al_confirmar(ImagenPartida.objects.filter(partida__solicitud=solicitud))
    solicitud.delete()  # CASCADE: partidas, DetalleAlta, ImagenPartida y Evento


def borrar_archivos_al_confirmar(imagenes):
    """Los renglones se van con el CASCADE, pero los archivos en disco no: se borran
    cuando la transacción se confirma (si se deshiciera, las fotos seguirían ahí)."""
    for imagen in imagenes:
        archivo = imagen.archivo
        transaction.on_commit(lambda a=archivo: a.storage.delete(a.name))


@transaction.atomic
def guardar_borrador(usuario, formset, solicitud=None):
    """Crea o actualiza un borrador. El formset ya debe ser válido (sin valores inválidos)."""
    if solicitud is None:
        solicitud = Solicitud.objects.create(flujo=Flujo.AMAT_ZRA, solicitante=usuario)
        Evento.objects.create(solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.CREACION)
    _reemplazar_partidas(solicitud, formset)
    return solicitud


def revisar_envio(formset, solicitud):
    """Revisiones de la fase 4 al Enviar, después de las de campos obligatorios.

    - Cada partida necesita al menos 1 imagen. Se cuenta lo que ya está guardado: la vista
      guarda el borrador con las imágenes elegidas ANTES de llamar a esta revisión.
    - Duplicados: un duplicado exacto marca la celda Descripción y bloquea; las
      advertencias y coincidencias posibles se devuelven como avisos, no bloquean.

    Devuelve (ok, avisos).
    """
    con_imagen = set()
    if solicitud is not None:
        con_imagen = set(solicitud.partidas.filter(imagenes__isnull=False).values_list("numero", flat=True))
    ok, avisos = True, []
    for form in formset.renglones:
        datos = form.cleaned_data
        if datos["numero"] not in con_imagen:
            form.error_imagen = "Falta al menos 1 imagen."
            ok = False
        for c in duplicados.buscar(datos.get("descripcion"), datos.get("no_parte_original")):
            if c.bloquea:
                form.add_error("descripcion", f"Duplicado: ya existe el código {c.codigo} ({c.descripcion}, No. Parte {c.no_parte or '—'}, UMB {c.umb or '—'}).")
                ok = False
            else:
                avisos.append(f"Partida {datos['numero']}: {c.motivo} Código {c.codigo} «{c.descripcion}».")
    if not ok and any(hasattr(f, "error_imagen") for f in formset.renglones):
        formset._non_form_errors = formset.error_class(
            ["Cada partida necesita al menos 1 imagen. Elígela en la columna Imágenes del renglón marcado."]
        )
    return ok, avisos


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
            de_mis_centros(usuario), estado=Partida.Estado.EN_VALIDACION
        )
    return editables.order_by("numero")


def _valor_legible(valor):
    return "" if valor is None else str(valor)


@transaction.atomic
def guardar_correcciones(usuario, forms, solicitud):
    """Aplica los cambios de los renglones `forms` (de la tabla o de la ficha de una partida).
    Devuelve cuántos campos cambiaron.

    Cada campo que cambió deja un Evento CAMBIO_CAMPO con su valor anterior y el nuevo.
    Lo que no cambió no se registra (no se guarda cada clic, sección 15).
    """
    # Se vuelven a calcular DENTRO de la transacción y con FOR UPDATE: si mientras el
    # usuario editaba alguien aprobó la partida, ya no es editable y no se toca.
    permitidas = {p.pk: p for p in partidas_editables(usuario, solicitud).select_for_update(of=("self",))}
    cambios = 0
    memo = {}
    for form in forms:
        datos = form.cleaned_data
        partida = permitidas.get(datos["pid"])
        if partida is None:
            raise PermissionError("Una de las partidas ya no está disponible para corregir. Recarga la página.")
        alta = partida.alta
        nuevos = {c: datos.get(c) for c in CAMPOS_DETALLE}
        nuevos["centro"] = datos.get("centro")
        # Almacén vacío = el propuesto del Centro. Se resuelve ANTES de comparar para no
        # registrar un cambio falso ("RC01 → vacío") cuando en realidad sigue igual.
        nuevos["almacen"] = nuevos["almacen"] or almacen_predeterminado(nuevos["centro"], memo)
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
        # Tipo de Material se recalcula siempre en el servidor; el almacén vacío toma el predeterminado.
        alta.tipo_material = alta.categoria_valoracion.tipo_material if alta.categoria_valoracion else None
        if alta.almacen is None:
            alta.almacen = almacen_predeterminado(partida.centro, memo)
        partida.save()
        alta.save()
    return cambios
