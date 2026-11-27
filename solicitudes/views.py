"""Pantallas de solicitudes (fase 2: Mis solicitudes y captura de AMAT_ZRA)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from catalogos.models import Almacen, CategoriaValoracion, GrupoCompras

from . import servicios
from .forms import PartidasFormSet
from .models import Flujo, Solicitud


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


@login_required
def detalle(request, pk):
    """Vista de solo lectura de una solicitud del usuario."""
    solicitud = get_object_or_404(
        Solicitud.objects.prefetch_related("partidas__alta"), pk=pk, solicitante=request.user
    )
    return render(request, "solicitudes/detalle.html", {"solicitud": solicitud})
