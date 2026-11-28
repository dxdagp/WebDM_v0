"""Máquina de estados de las partidas (Revisión 3, secciones 4, 7 y 9).

Todas las vistas que cambian el estado de una partida pasan por aquí. Ninguna
vista escribe `partida.estado = …` por su cuenta. Así las reglas viven en un
solo archivo y se pueden probar sin navegador.

Cada acción en bloque sigue el mismo patrón:

1. Abrir una transacción (`@transaction.atomic`).
2. Bloquear las partidas elegidas con `SELECT … FOR UPDATE`.
3. Verificar que TODAS se pueden mover (rol, Centro, estado actual).
4. Si alguna no, se lanza `AccionNoPermitida` y PostgreSQL deshace todo.
5. Si todas sí, se cambian y se registra un `Evento` por partida.
"""

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from catalogo_sap.models import MaterialCentro, MaterialSAP

from . import duplicados
from .forms import CAMPOS_OBLIGATORIOS_ENVIO
from .models import DetalleAlta, Evento, Partida, Solicitud

E = Partida.Estado
ESTADOS_FINALES = {E.TERMINADA, E.CANCELADA, E.EXCLUIDA}


class AccionNoPermitida(Exception):
    """La acción no se aplicó a ninguna partida. El mensaje se muestra al usuario."""


@dataclass(frozen=True)
class Transicion:
    rol: str  # rol que puede hacerla
    desde: E  # estado en el que deben estar las partidas
    hacia: E  # estado al que pasan
    evento: str  # tipo de Evento que se registra
    pide_motivo: bool = False
    exige_completa: bool = False  # revisa obligatorios antes de mover
    solo_propias: bool = False  # True: solo el solicitante; False: por Centros autorizados


# La tabla completa de lo que se puede hacer. Si no está aquí, no se puede.
TRANSICIONES = {
    "aprobar": Transicion("VAL_MAT", E.EN_VALIDACION, E.EN_DM, Evento.Tipo.APROBACION, exige_completa=True),
    "devolver": Transicion("VAL_MAT", E.EN_VALIDACION, E.DEVUELTA_SOL, Evento.Tipo.DEVOLUCION, pide_motivo=True),
    "cancelar": Transicion("VAL_MAT", E.EN_VALIDACION, E.CANCELADA, Evento.Tipo.CANCELACION, pide_motivo=True),
    "reenviar": Transicion(
        "SOL_MAT", E.DEVUELTA_SOL, E.EN_VALIDACION, Evento.Tipo.ENVIO, exige_completa=True, solo_propias=True
    ),
    "cancelar_propia": Transicion(
        "SOL_MAT", E.DEVUELTA_SOL, E.CANCELADA, Evento.Tipo.CANCELACION, pide_motivo=True, solo_propias=True
    ),
    # DM solo puede devolver a VAL_MAT (Revisión 3, sección 7) y no cancela AMAT.
    "devolver_a_validacion": Transicion("DM", E.EN_DM, E.EN_VALIDACION, Evento.Tipo.DEVOLUCION, pide_motivo=True),
}


def roles_de(usuario):
    roles = set(usuario.groups.values_list("name", flat=True))
    if usuario.is_superuser:
        roles.add("ADMIN")
    return roles


def faltantes(partida):
    """Campos obligatorios vacíos de una partida AMAT ya guardada (mismas reglas que Enviar)."""
    alta = partida.alta
    vacios = []
    for campo in CAMPOS_OBLIGATORIOS_ENVIO:
        if campo == "centro":
            valor, nombre = partida.centro_id, "Centro"
        else:
            # attname es "ubicacion_id" para una llave foránea y "descripcion" para un texto:
            # así se lee el valor sin hacer otra consulta para traer el catálogo.
            field = alta._meta.get_field(campo)
            valor, nombre = getattr(alta, field.attname), field.verbose_name
        if valor in (None, ""):
            vacios.append(nombre)
    # Fase 4: mínimo 1 imagen por partida de alta (Revisión 3, sección 7.3).
    if partida.solicitud.flujo == "AMAT_ZRA" and not partida.imagenes.exists():
        vacios.append("al menos 1 imagen")
    return vacios


def duplicado_de(partida):
    """El material del Catálogo SAP que duplica EXACTO a esta partida (sección 8), o None."""
    alta = partida.alta
    return duplicados.bloqueante(alta.descripcion, alta.no_parte_original)


def _bloquear(ids):
    """SELECT … FOR UPDATE: nadie más puede cambiar estas filas hasta que termine la transacción.

    Si otro validador tiene alguna bloqueada, esta consulta ESPERA a que él termine;
    después lee el estado ya actualizado.
    """
    return list(Partida.objects.select_for_update().filter(pk__in=ids).order_by("pk"))


def _verificar_alcance(usuario, partidas, t):
    if t.solo_propias:
        ajenas = [p for p in partidas if p.solicitud.solicitante_id != usuario.pk]
        if ajenas:
            raise AccionNoPermitida("Solo puedes mover partidas de tus propias solicitudes.")
    else:
        centros = set(usuario.centros.values_list("pk", flat=True))
        fuera = [p for p in partidas if p.centro_id not in centros]
        if fuera:
            raise AccionNoPermitida("Alguna partida es de un Centro que no tienes autorizado.")


def actualizar_cabecera(solicitud, usuario):
    """La cabecera termina cuando todas sus partidas están en un estado final (sección 11)."""
    estados = set(solicitud.partidas.values_list("estado", flat=True))
    nuevo = Solicitud.Estado.TERMINADA if estados and estados <= ESTADOS_FINALES else Solicitud.Estado.EN_PROCESO
    if solicitud.estado != nuevo:
        anterior = solicitud.estado
        solicitud.estado = nuevo
        solicitud.save(update_fields=["estado", "actualizada"])
        if nuevo == Solicitud.Estado.TERMINADA:
            Evento.objects.create(
                solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.TERMINACION,
                estado_anterior=anterior, estado_nuevo=nuevo,
            )


def _registrar(partida, usuario, tipo, anterior, motivo="", detalle=None):
    Evento.objects.create(
        solicitud=partida.solicitud, partida=partida, usuario=usuario, tipo=tipo,
        estado_anterior=anterior, estado_nuevo=partida.estado, motivo=motivo, detalle=detalle or {},
    )


@transaction.atomic
def aplicar(usuario, accion, ids, motivo=""):
    """Aplica `accion` a TODAS las partidas `ids`, o a ninguna. Devuelve cuántas movió.

    `motivo` es un texto, o un diccionario {id de partida: texto} cuando cada partida
    lleva su propio motivo (así lo pide Dave en la bandeja, 27-nov-2026).
    """
    t = TRANSICIONES.get(accion)
    if t is None:
        raise AccionNoPermitida("Acción desconocida.")
    if t.rol not in roles_de(usuario):
        raise AccionNoPermitida(f"Necesitas el rol {t.rol}.")
    ids = {int(i) for i in ids}
    if not ids:
        raise AccionNoPermitida("Selecciona al menos una partida.")
    if isinstance(motivo, dict):
        motivos = {int(k): (v or "").strip() for k, v in motivo.items()}
    else:
        motivos = {i: (motivo or "").strip() for i in ids}

    partidas = _bloquear(ids)
    if len(partidas) != len(ids):
        raise AccionNoPermitida("Alguna partida ya no existe. Recarga la página.")
    _verificar_alcance(usuario, partidas, t)

    movidas = [p for p in partidas if p.estado != t.desde]
    if movidas:
        raise AccionNoPermitida(
            f"{len(movidas)} de las partidas seleccionadas ya no están en {t.desde.label}; "
            "otra persona las movió. No se cambió ninguna. Recarga la página."
        )

    if t.pide_motivo:
        sin_motivo = [f"{p.solicitud.folio}/{p.numero}" for p in partidas if not motivos.get(p.pk)]
        if sin_motivo:
            raise AccionNoPermitida(
                "El motivo es obligatorio para devolver o cancelar. No se movió ninguna. Falta en: " + ", ".join(sin_motivo)
            )

    if t.exige_completa:
        incompletas = []
        for p in partidas:
            vacios = faltantes(p)
            if vacios:
                incompletas.append(f"{p.solicitud.folio}/{p.numero} (falta: {', '.join(vacios)})")
        if incompletas:
            raise AccionNoPermitida("No se movió ninguna. Partidas incompletas: " + "; ".join(incompletas))
        # Fase 4: validación final de duplicados. Un duplicado exacto bloquea (sección 8).
        repetidas = []
        for p in partidas:
            d = duplicado_de(p)
            if d:
                repetidas.append(f"{p.solicitud.folio}/{p.numero} (ya existe el código {d.codigo})")
        if repetidas:
            raise AccionNoPermitida("No se movió ninguna. Duplicados en el Catálogo SAP: " + "; ".join(repetidas))

    hacia = t.hacia
    # Igual que en el primer envío: si quien reenvía también es VAL_MAT, va directo a DM.
    if accion == "reenviar" and "VAL_MAT" in roles_de(usuario):
        hacia = E.EN_DM

    ahora = timezone.now()
    for p in partidas:
        anterior = p.estado
        p.estado = hacia
        campos = ["estado", "actualizada"]
        if hacia == E.DEVUELTA_SOL:
            p.ultima_devolucion = ahora  # desde aquí se cuentan los 15/30 días (fase 4)
            campos.append("ultima_devolucion")
        p.save(update_fields=campos)
        _registrar(p, usuario, t.evento, anterior, motivos.get(p.pk, ""))

    for solicitud in {p.solicitud for p in partidas}:
        actualizar_cabecera(solicitud, usuario)
    return len(partidas)


class ErroresCodigo(Exception):
    """Algún Código SAP no es válido. `errores` = {id de partida: mensaje}."""

    def __init__(self, errores):
        super().__init__("Hay Códigos SAP con error.")
        self.errores = errores


def _error_codigo(codigo):
    if not (len(codigo) == 6 and codigo.isdigit()):
        return "Debe tener exactamente 6 dígitos."
    # Solo contra el catálogo de MATERIALES: un servicio con el mismo código es otro item.
    if MaterialSAP.objects.filter(codigo=codigo, es_servicio=False).exists() or DetalleAlta.objects.filter(codigo_sap=codigo).exists():
        return "Este Código SAP ya existe."
    return None


@transaction.atomic
def terminar_con_codigos(usuario, codigos):
    """DM asigna Código SAP a varias partidas EN_DM y las termina (sección 9).

    `codigos` = {id de partida: "123456"}. Las que llegan vacías se ignoran
    (se quedan en EN_DM). Si algún código falla, no se termina ninguna.
    """
    if "DM" not in roles_de(usuario):
        raise AccionNoPermitida("Necesitas el rol DM.")
    codigos = {int(pid): (c or "").strip() for pid, c in codigos.items() if (c or "").strip()}
    if not codigos:
        raise AccionNoPermitida("Escribe al menos un Código SAP.")

    partidas = _bloquear(codigos)
    if len(partidas) != len(codigos):
        raise AccionNoPermitida("Alguna partida ya no existe. Recarga la página.")
    _verificar_alcance(usuario, partidas, TRANSICIONES["devolver_a_validacion"])
    movidas = [p for p in partidas if p.estado != E.EN_DM]
    if movidas:
        raise AccionNoPermitida("Alguna partida ya no está en Datos Maestros. No se terminó ninguna. Recarga la página.")

    errores, vistos = {}, {}
    for p in partidas:
        codigo = codigos[p.pk]
        error = _error_codigo(codigo)
        if not error and codigo in vistos:
            error = "Código repetido en esta captura."
        # Fase 4: tampoco se termina una partida sin imágenes (p. ej. una que llegó a DM antes
        # de esta fase). DM la devuelve a VAL_MAT para que le suban al menos una.
        if not error and p.solicitud.flujo == "AMAT_ZRA" and not p.imagenes.exists():
            error = "La partida no tiene imágenes. Devuélvela a VAL_MAT."
        vistos.setdefault(codigo, p.pk)
        if error:
            errores[p.pk] = error
    if errores:
        raise ErroresCodigo(errores)

    try:
        for p in partidas:
            alta = p.alta
            alta.codigo_sap = codigos[p.pk]
            alta.save(update_fields=["codigo_sap"])
            # El material entra al catálogo interno, en el Centro de la partida.
            material = MaterialSAP.objects.create(
                codigo=alta.codigo_sap, descripcion=alta.descripcion,
                tipo_material=alta.tipo_material.codigo if alta.tipo_material else "",
                umb=alta.umb.codigo if alta.umb else "", no_parte_original=alta.no_parte_original,
                grupo_articulos=alta.grupo_articulos.codigo if alta.grupo_articulos else "",
                ubicacion=alta.ubicacion.codigo if alta.ubicacion else "", tipo_unidad=alta.tipo_unidad,
                marca=alta.marca, version=alta.version, anio_modelo=alta.anio_modelo,
                compatibilidad=alta.compatibilidad,
                origen=MaterialSAP.Origen.WEBDM, folio_origen=p.solicitud.folio or "", partida_origen=p,
                creado_por=usuario,
            )
            MaterialCentro.objects.create(
                material=material, centro=p.centro, cebe=p.centro.centro_beneficio if p.centro else "",
                grupo_compras=alta.grupo_compras.codigo if alta.grupo_compras else "",
                categoria_valoracion=alta.categoria_valoracion.codigo if alta.categoria_valoracion else "",
                almacen=alta.almacen.codigo if alta.almacen else "",
            )
            anterior = p.estado
            p.estado = E.TERMINADA
            p.save(update_fields=["estado", "actualizada"])
            _registrar(p, usuario, Evento.Tipo.CODIGO_SAP, anterior, detalle={"codigo": alta.codigo_sap})
    except IntegrityError:
        # Otra persona registró el mismo código en este instante: el UNIQUE de PostgreSQL lo detuvo.
        raise AccionNoPermitida("Otro usuario acaba de registrar alguno de estos códigos. No se terminó ninguna.")

    for solicitud in {p.solicitud for p in partidas}:
        actualizar_cabecera(solicitud, usuario)
    return len(partidas)


@transaction.atomic
def corregir_codigo(usuario, partida_id, nuevo, motivo):
    """Corrige el Código SAP de una partida TERMINADA sin reabrirla (sección 9)."""
    if "DM" not in roles_de(usuario):
        raise AccionNoPermitida("Necesitas el rol DM.")
    motivo, nuevo = (motivo or "").strip(), (nuevo or "").strip()
    if not motivo:
        raise AccionNoPermitida("Escribe el motivo de la corrección.")
    partidas = _bloquear([partida_id])
    if not partidas:
        raise AccionNoPermitida("La partida no existe.")
    p = partidas[0]
    _verificar_alcance(usuario, partidas, TRANSICIONES["devolver_a_validacion"])
    if p.estado != E.TERMINADA:
        raise AccionNoPermitida("Solo se corrige el código de una partida TERMINADA.")
    error = _error_codigo(nuevo)
    if error:
        raise AccionNoPermitida(error)

    alta = p.alta
    anterior = alta.codigo_sap
    try:
        # Se cambia el código del MISMO material: su id no cambia, así que sus Centros se conservan.
        MaterialSAP.objects.filter(codigo=anterior, es_servicio=False).update(codigo=nuevo)
        alta.codigo_sap = nuevo
        alta.save(update_fields=["codigo_sap"])
    except IntegrityError:
        raise AccionNoPermitida("Otro usuario acaba de registrar ese código.")
    _registrar(p, usuario, Evento.Tipo.CORRECCION_CODIGO_SAP, p.estado, motivo, {"antes": anterior, "despues": nuevo})
    return p
