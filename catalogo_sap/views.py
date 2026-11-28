"""Pantallas del Catálogo SAP: consulta (todos) e importación del TXT (ADMIN y DM)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render

from catalogos.models import Centro

from .importar import ArchivoInvalido, importar
from .models import Importacion, MaterialCentro, MaterialSAP

ROLES_IMPORTAR = {"ADMIN", "DM"}


def puede_importar(usuario):
    return usuario.is_superuser or usuario.groups.filter(name__in=ROLES_IMPORTAR).exists()


CATALOGOS = {
    "materiales": {"titulo": "Catálogo de materiales", "servicio": False},
    "servicios": {"titulo": "Catálogo de servicios", "servicio": True},
}


@login_required
def consulta(request, catalogo="materiales"):
    """Catálogo de consulta global (Revisión 3: todos ven todos los Centros).

    Materiales y servicios se consultan por separado (pedido de Dave). Por dentro es la misma
    tabla con la columna es_servicio; el código es único dentro de cada catálogo, no entre los dos.
    """
    datos_catalogo = CATALOGOS[catalogo]
    texto = request.GET.get("q", "").strip()
    centro = request.GET.get("centro", "")
    materiales = MaterialSAP.objects.filter(es_servicio=datos_catalogo["servicio"]).select_related("creado_por", "importacion").prefetch_related(
        # Prefetch trae los Centros de los 50 materiales de la página en UNA consulta extra (no 50).
        Prefetch("centros", queryset=MaterialCentro.objects.select_related("centro").order_by("centro__codigo"))
    )
    if texto:
        # Q(...) | Q(...) = OR en el WHERE.
        materiales = materiales.filter(
            Q(codigo__startswith=texto) | Q(descripcion__icontains=texto) | Q(no_parte_original__icontains=texto)
        )
    if centro:
        materiales = materiales.filter(centros__centro_id=centro)
    pagina = Paginator(materiales.order_by("codigo"), 50).get_page(request.GET.get("pagina"))
    return render(request, "catalogo_sap/consulta.html", {
        "pagina": pagina, "q": texto, "centro": centro, "catalogo": catalogo, "titulo": datos_catalogo["titulo"],
        "centros": Centro.objects.order_by("codigo"),
        "puede_importar": puede_importar(request.user),
    })


@login_required
def importar_txt(request):
    if not puede_importar(request.user):
        raise PermissionDenied("Importar el catálogo SAP es solo para ADMIN y DM.")
    if request.method == "POST":
        archivo = request.FILES.get("archivo")
        catalogo = request.POST.get("catalogo")
        if catalogo not in Importacion.Catalogo.values:
            messages.error(request, "Elige a qué catálogo va el archivo: materiales o servicios.")
        elif not archivo:
            messages.error(request, "Elige el archivo .txt.")
        else:
            try:
                imp = importar(archivo.file, archivo.name, request.user, catalogo)
            except ArchivoInvalido as e:
                messages.error(request, f"No se importó nada: {e}")
            else:
                messages.success(request, f"Importación terminada: {imp.importados} renglón(es) importado(s), {imp.errores} con error.")
                return redirect("catalogo_sap:importacion", pk=imp.pk)
    return render(request, "catalogo_sap/importar.html", {
        "historial": Importacion.objects.select_related("usuario")[:20],
        "catalogos": Importacion.Catalogo.choices,
        "elegido": request.POST.get("catalogo") or request.GET.get("catalogo", ""),
    })


@login_required
def importacion(request, pk):
    if not puede_importar(request.user):
        raise PermissionDenied("Solo ADMIN y DM.")
    imp = get_object_or_404(Importacion.objects.select_related("usuario"), pk=pk)
    errores = Paginator(imp.detalle_errores.all(), 100).get_page(request.GET.get("pagina"))
    return render(request, "catalogo_sap/importacion.html", {"imp": imp, "errores": errores})
