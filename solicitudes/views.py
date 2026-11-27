"""Pantallas de solicitudes: Mis solicitudes, captura de AMAT_ZRA (fase 2), bandejas y corrección (fase 3)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from catalogos.models import Almacen, CategoriaValoracion, GrupoCompras

from . import bandejas, flujo, servicios
from .forms import CorreccionFormSet, PartidasFormSet
from .models import Flujo, Partida, Solicitud


@login_required
def mis_solicitudes(request):
    solicitudes = (
        Solicitud.objects.filter(solicitante=request.user).prefetch_related("partidas").order_by("-creada")
    )
    return render(request, "solicitudes/mis_solicitudes.html", {"solicitudes": solicitudes})


def _datos_automaticos(centros):
    """Datos para que la pantalla llene sola CeBe, Tipo de Material, Almacén y Grupo de compras.

    La plantilla los mete a la página como JSON (filtro json_script, que además
    los escapa para que no se puedan inyectar etiquetas). El JavaScript los usa al cambiar
    de Centro o de Categoría. El servidor vuelve a calcularlos al guardar: lo
    que muestra el navegador es solo una ayuda visual.
    """
    almacenes = Almacen.objects.filter(centro__in=centros, predeterminado=True, activo=True)
    grupos = GrupoCompras.objects.filter(centro__in=centros, predeterminado=True, activo=True)
    return {
        "cebe": {str(c.pk): c.centro_beneficio for c in centros},
        "almacen": {str(a.centro_id): a.codigo for a in almacenes},
        "grupoPredeterminado": {str(g.centro_id): str(g.pk) for g in grupos},
        "tipoMaterial": {
            str(c.pk): c.tipo_material.codigo for c in CategoriaValoracion.objects.select_related("tipo_material")
        },
    }


def _filas_iniciales(solicitud):
    """Convierte las partidas guardadas en los valores iniciales del formset."""
    filas = []
    for p in solicitud.partidas.select_related("alta").order_by("numero"):
        fila = {"numero": p.numero, "centro": p.centro_id}
        for campo in servicios.CAMPOS_DETALLE:
            valor = getattr(p.alta, campo)
            fila[campo] = getattr(valor, "pk", valor)  # para catálogos se usa su id
        filas.append(fila)
    return filas


@login_required
def capturar_amat(request, pk=None):
    """Nueva solicitud AMAT_ZRA (sin pk) o edición de un borrador propio (con pk)."""
    if not servicios.puede_capturar(request.user):
        raise PermissionDenied("Necesitas el rol SOL_MAT o VAL_MAT.")

    solicitud = None
    if pk:
        solicitud = get_object_or_404(Solicitud, pk=pk, flujo=Flujo.AMAT_ZRA, solicitante=request.user)
        if solicitud.estado != Solicitud.Estado.BORRADOR:
            return redirect("solicitudes:detalle", pk=solicitud.pk)

    centros = request.user.centros.filter(activo=True)

    if request.method == "POST":
        formset = PartidasFormSet(request.POST, centros=centros)
        accion = request.POST.get("accion")
        if accion == "enviar":
            if formset.validar_para_envio():
                solicitud = servicios.enviar(request.user, formset, solicitud)
                messages.success(request, f"Solicitud enviada con folio {solicitud.folio}.")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            messages.error(request, "No se pudo enviar. Corrige las celdas marcadas; tus datos siguen en pantalla.")
        elif formset.is_valid():
            solicitud = servicios.guardar_borrador(request.user, formset, solicitud)
            messages.success(request, "Borrador guardado.")
            return redirect("solicitudes:editar_amat", pk=solicitud.pk)
        else:
            messages.error(request, "Hay valores inválidos; no se guardó nada. Corrige las celdas marcadas.")
    else:
        iniciales = _filas_iniciales(solicitud) if solicitud else [{"numero": n} for n in (10, 20, 30)]
        formset = PartidasFormSet(initial=iniciales, centros=centros)

    return render(request, "solicitudes/capturar_amat.html", {
        "solicitud": solicitud,
        "formset": formset,
        "datos_automaticos": _datos_automaticos(centros),
        "sin_centros": not centros.exists(),
    })


def puede_ver(usuario, solicitud):
    """Quién puede abrir una solicitud: su solicitante, ADMIN, o VAL_MAT/DM si tiene
    alguna partida en sus Centros autorizados."""
    if solicitud.solicitante_id == usuario.pk:
        return True
    roles = flujo.roles_de(usuario)
    if "ADMIN" in roles:
        return True
    if roles & {"VAL_MAT", "DM"}:
        return solicitud.partidas.filter(centro__in=usuario.centros.values("pk")).exists()
    return False


@login_required
def detalle(request, pk):
    """Vista de solo lectura de una solicitud, con la historia de cada partida."""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related("solicitante").prefetch_related("partidas__alta", "partidas__centro"), pk=pk
    )
    if not puede_ver(request.user, solicitud):
        raise PermissionDenied("Esta solicitud no es tuya ni de tus Centros.")
    roles = flujo.roles_de(request.user)
    centros = set(request.user.centros.values_list("pk", flat=True))
    return render(request, "solicitudes/detalle.html", {
        "solicitud": solicitud,
        "eventos": solicitud.eventos.select_related("usuario", "partida").order_by("fecha"),
        "puede_corregir": servicios.partidas_editables(request.user, solicitud).exists(),
        # DM puede corregir el código de las TERMINADA de sus Centros (sección 9).
        "corregibles_codigo": [
            p for p in solicitud.partidas.all()
            if "DM" in roles and p.estado == Partida.Estado.TERMINADA and p.centro_id in centros
        ],
    })


# --- Fase 3: bandeja "Pendientes de mi atención" ------------------------------------------


@login_required
def pendientes(request):
    pestanas = bandejas.pestanas_de(request.user)
    if not pestanas:
        raise PermissionDenied("Tu rol no tiene bandeja de pendientes.")
    claves = [c for c, _ in pestanas]
    activa = request.GET.get("tab") if request.GET.get("tab") in claves else claves[0]

    partidas = bandejas.con_datos_de_tabla(bandejas.partidas_de(request.user, activa))
    # Filtros simples. icontains = ILIKE '%texto%' en PostgreSQL (sin importar mayúsculas).
    filtros = {k: request.GET.get(k, "").strip() for k in ("folio", "centro", "texto")}
    if filtros["folio"]:
        partidas = partidas.filter(solicitud__folio__icontains=filtros["folio"])
    if filtros["centro"]:
        partidas = partidas.filter(centro__codigo__iexact=filtros["centro"])
    if filtros["texto"]:
        partidas = partidas.filter(alta__descripcion__icontains=filtros["texto"])

    return render(request, "solicitudes/pendientes.html", {
        "pestanas": [(c, t, bandejas.partidas_de(request.user, c).count()) for c, t in pestanas],
        "activa": activa,
        "partidas": partidas,
        "filtros": filtros,
    })


@login_required
@require_POST
def accion_en_bloque(request):
    """Aprobar, devolver o cancelar varias partidas a la vez (todas o ninguna)."""
    accion = request.POST.get("accion", "")
    ids = request.POST.getlist("partidas")
    try:
        n = flujo.aplicar(request.user, accion, ids, request.POST.get("motivo", ""))
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
    else:
        textos = {
            "aprobar": "aprobada(s) y enviada(s) a Datos Maestros", "devolver": "devuelta(s) al solicitante",
            "cancelar": "cancelada(s)", "reenviar": "reenviada(s)", "cancelar_propia": "cancelada(s)",
            "devolver_a_validacion": "devuelta(s) a validación",
        }
        messages.success(request, f"{n} partida(s) {textos[accion]}.")
    return _volver_a_bandeja(request)


def _volver_a_bandeja(request):
    """Regresa a la misma pestaña y con los mismos filtros desde los que se hizo la acción."""
    query = {k: request.POST[k] for k in ("tab", "folio", "centro", "texto") if request.POST.get(k)}
    return redirect(f"{reverse('solicitudes:pendientes')}?{urlencode(query)}")


@login_required
@require_POST
def terminar_dm(request):
    """DM: guarda los Códigos SAP capturados en la bandeja y termina esas partidas."""
    codigos = {k.removeprefix("codigo-"): v for k, v in request.POST.items() if k.startswith("codigo-")}
    try:
        n = flujo.terminar_con_codigos(request.user, codigos)
    except flujo.ErroresCodigo as e:
        messages.error(request, "No se terminó ninguna partida. Corrige los códigos marcados.")
        # Se vuelve a mostrar la bandeja con lo que DM escribió y el error junto a cada código.
        partidas = list(bandejas.con_datos_de_tabla(bandejas.partidas_de(request.user, "dm")))
        for p in partidas:
            p.codigo_capturado = codigos.get(str(p.pk), "")
            p.error_codigo = e.errores.get(p.pk, "")
        return render(request, "solicitudes/pendientes.html", {
            "pestanas": [(c, t, bandejas.partidas_de(request.user, c).count()) for c, t in bandejas.pestanas_de(request.user)],
            "activa": "dm", "partidas": partidas,
            "filtros": {k: request.POST.get(k, "") for k in ("folio", "centro", "texto")},
        })
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{n} partida(s) terminada(s); sus materiales ya están en el Catálogo SAP.")
    return _volver_a_bandeja(request)


@login_required
@require_POST
def corregir_codigo(request, pk):
    """DM corrige el Código SAP de una partida TERMINADA."""
    partida = get_object_or_404(Partida, pk=pk)
    try:
        flujo.corregir_codigo(request.user, partida.pk, request.POST.get("codigo"), request.POST.get("motivo"))
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Código SAP corregido.")
    return redirect("solicitudes:detalle", pk=partida.solicitud_id)


# --- Fase 3: corregir partidas devueltas o en validación ----------------------------------


@login_required
def corregir(request, pk):
    """Tabla tipo Excel con solo las partidas que el usuario puede corregir ahora."""
    solicitud = get_object_or_404(Solicitud, pk=pk, flujo=Flujo.AMAT_ZRA)
    editables = list(servicios.partidas_editables(request.user, solicitud).select_related("alta"))
    if not editables:
        messages.error(request, "No tienes partidas de esta solicitud para corregir.")
        return redirect("solicitudes:detalle", pk=solicitud.pk)

    # El Centro se puede cambiar solo por uno de los Centros autorizados del usuario.
    centros = request.user.centros.filter(activo=True)
    es_solicitante = solicitud.solicitante_id == request.user.pk
    puede_reenviar = es_solicitante and any(p.estado == Partida.Estado.DEVUELTA_SOL for p in editables)

    # Valores actuales de cada partida. En POST también se pasan: el número de partida es un
    # campo `disabled` y Django toma su valor de aquí, nunca de lo que mande el navegador.
    iniciales = []
    for p in editables:
        fila = {"pid": p.pk, "numero": p.numero, "centro": p.centro_id}
        for campo in servicios.CAMPOS_DETALLE:
            valor = getattr(p.alta, campo)
            fila[campo] = getattr(valor, "pk", valor)
        iniciales.append(fila)

    if request.method == "POST":
        formset = CorreccionFormSet(request.POST, initial=iniciales, centros=centros)
        accion = request.POST.get("accion")
        valido = formset.validar_para_envio() if accion == "reenviar" else formset.is_valid()
        if valido:
            devueltas = {p.pk for p in editables if p.estado == Partida.Estado.DEVUELTA_SOL}
            try:
                # Una sola transacción: si el reenvío falla, tampoco se guardan las correcciones.
                with transaction.atomic():
                    n = servicios.guardar_correcciones(request.user, formset, solicitud)
                    if accion == "reenviar":
                        ids = [f.cleaned_data["pid"] for f in formset.renglones if f.cleaned_data["pid"] in devueltas]
                        flujo.aplicar(request.user, "reenviar", ids)
                if accion == "reenviar":
                    messages.success(request, f"Partidas reenviadas ({n} campo(s) corregido(s)).")
                    return redirect("solicitudes:detalle", pk=solicitud.pk)
            except (PermissionError, flujo.AccionNoPermitida) as e:
                messages.error(request, str(e))
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            messages.success(request, f"Correcciones guardadas: {n} campo(s) cambiado(s).")
            return redirect("solicitudes:corregir", pk=solicitud.pk)
        messages.error(request, "No se guardó nada. Corrige las celdas marcadas; tus datos siguen en pantalla.")
    else:
        formset = CorreccionFormSet(initial=iniciales, centros=centros)

    estados = {p.pk: p.get_estado_display() for p in editables}
    for form in formset:
        form.estado_partida = estados.get(_entero(form["pid"].value()), "")
    return render(request, "solicitudes/corregir.html", {
        "solicitud": solicitud,
        "formset": formset,
        "datos_automaticos": _datos_automaticos(centros),
        "puede_reenviar": puede_reenviar,
        "es_solicitante": es_solicitante,
    })


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None
