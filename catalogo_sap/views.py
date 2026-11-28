"""Pantallas del Catálogo SAP: consulta (todos) e importación del TXT (ADMIN y DM)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from catalogos.models import Centro

from .importar import COLUMNAS, ArchivoInvalido, importar
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
    if datos_catalogo["servicio"]:
        # Servicios: un renglón por código (no dependen de un Centro).
        renglones = MaterialSAP.objects.filter(es_servicio=True).select_related("creado_por", "importacion")
        prefijo, orden = "", ["codigo"]
    else:
        # Materiales: un renglón por Material + Centro (pedido de Dave). La consulta parte de
        # MaterialCentro y trae su material y su Centro con JOIN (select_related).
        renglones = MaterialCentro.objects.filter(material__es_servicio=False).select_related(
            "centro", "material__creado_por", "material__importacion")
        prefijo, orden = "material__", ["material__codigo", "centro__codigo"]
        if centro:
            renglones = renglones.filter(centro_id=centro)
    if texto:
        # Q(...) | Q(...) = OR en el WHERE.
        renglones = renglones.filter(
            Q(**{f"{prefijo}codigo__startswith": texto}) | Q(**{f"{prefijo}descripcion__icontains": texto})
            | Q(**{f"{prefijo}no_parte_original__icontains": texto})
        )
    pagina = Paginator(renglones.order_by(*orden), 50).get_page(request.GET.get("pagina"))
    return render(request, "catalogo_sap/consulta.html", {
        "pagina": pagina, "q": texto, "centro": centro, "catalogo": catalogo, "titulo": datos_catalogo["titulo"], "es_servicios": datos_catalogo["servicio"],
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
        "columnas": COLUMNAS,
        "elegido": request.POST.get("catalogo") or request.GET.get("catalogo", ""),
    })


@login_required
def importacion(request, pk):
    if not puede_importar(request.user):
        raise PermissionDenied("Solo ADMIN y DM.")
    imp = get_object_or_404(Importacion.objects.select_related("usuario"), pk=pk)
    errores = Paginator(imp.detalle_errores.all(), 100).get_page(request.GET.get("pagina"))
    return render(request, "catalogo_sap/importacion.html", {"imp": imp, "errores": errores})
