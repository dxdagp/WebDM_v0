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


# Filtros de la consulta de materiales, uno por columna (pedido de Dave: todos menos Almacén y UMB).
# (parámetro GET, búsqueda de Django sobre MaterialCentro, encabezado). El orden es el de la tabla,
# igual que la captura AMAT_ZRA.
COLUMNAS_MATERIALES = [
    ("codigo", "material__codigo__startswith", "Código SAP"),
    ("tipo", "material__tipo_material__icontains", "Tipo de material"),
    ("centro", "centro_id", "Centro"),
    ("descripcion", "material__descripcion__icontains", "Descripción"),
    ("umb", None, "UMB"),
    ("grupo_compras", "grupo_compras__icontains", "Grupo de compras"),
    ("grupo_articulos", "material__grupo_articulos__icontains", "Grupo de artículos"),
    ("categoria", "categoria_valoracion__icontains", "Categoría de valoración"),
    ("ubicacion", "material__ubicacion__icontains", "Ubicación"),
    ("no_parte", "material__no_parte_original__icontains", "No. Parte Original"),
    ("tipo_unidad", "material__tipo_unidad__icontains", "Tipo de unidad"),
    ("marca", "material__marca__icontains", "Marca"),
    ("version", "material__version__icontains", "Versión"),
    ("anio", "material__anio_modelo", "Año modelo"),
    ("compatibilidad", "material__compatibilidad__icontains", "Compatibilidad"),
    ("almacen", None, "Almacén"),
    ("cebe", "cebe__icontains", "CeBe"),
    ("origen", "material__origen", "Origen"),
]


def _sin_pagina(request):
    """Los filtros actuales como texto de URL, para que la paginación no los pierda."""
    filtros = request.GET.copy()
    filtros.pop("pagina", None)
    return filtros.urlencode()


@login_required
def consulta(request, catalogo="materiales"):
    """Catálogo de consulta global (Revisión 3: todos ven todos los Centros).

    Materiales y servicios se consultan por separado (pedido de Dave). Por dentro es la misma
    tabla con la columna es_servicio; el código es único dentro de cada catálogo, no entre los dos.
    """
    datos_catalogo = CATALOGOS[catalogo]
    contexto = {"catalogo": catalogo, "titulo": datos_catalogo["titulo"], "es_servicios": datos_catalogo["servicio"],
                "puede_importar": puede_importar(request.user), "filtros_url": _sin_pagina(request)}
    if datos_catalogo["servicio"]:
        # Servicios: un renglón por código (no dependen de un Centro) y una búsqueda general.
        texto = request.GET.get("q", "").strip()
        renglones = MaterialSAP.objects.filter(es_servicio=True).select_related("creado_por", "importacion")
        if texto:
            # Q(...) | Q(...) = OR en el WHERE.
            renglones = renglones.filter(Q(codigo__startswith=texto) | Q(descripcion__icontains=texto))
        contexto.update(q=texto, pagina=Paginator(renglones.order_by("codigo"), 50).get_page(request.GET.get("pagina")))
        return render(request, "catalogo_sap/consulta.html", contexto)

    # Materiales: un renglón por Material + Centro (pedido de Dave). La consulta parte de
    # MaterialCentro y trae su material y su Centro con JOIN (select_related).
    renglones = MaterialCentro.objects.filter(material__es_servicio=False).select_related(
        "centro", "material__creado_por", "material__importacion")
    columnas, hay_filtros = [], False
    for nombre, busqueda, titulo in COLUMNAS_MATERIALES:
        valor = request.GET.get(nombre, "").strip()
        if busqueda and valor:
            if nombre in ("centro", "anio") and not valor.isdigit():
                valor = ""  # basura en la URL: se ignora en vez de tronar
            else:
                # Cada filtro con valor agrega un AND al WHERE.
                renglones = renglones.filter(**{busqueda: valor})
                hay_filtros = True
        columnas.append({"nombre": nombre, "titulo": titulo, "filtra": bool(busqueda), "valor": valor})
    contexto.update(
        columnas=columnas, hay_filtros=hay_filtros, centros=Centro.objects.order_by("codigo"),
        origenes=MaterialSAP.Origen.choices,
        pagina=Paginator(renglones.order_by("material__codigo", "centro__codigo"), 50).get_page(request.GET.get("pagina")),
    )
    return render(request, "catalogo_sap/consulta.html", contexto)


@login_required
def material(request, pk):
    """Todos los datos de un material: generales, por Centro, y las imágenes de su alta en WebDM."""
    m = get_object_or_404(MaterialSAP.objects.select_related("creado_por", "importacion", "partida_origen__solicitud"), pk=pk)
    imagenes = m.partida_origen.imagenes.order_by("orden") if m.partida_origen else []
    return render(request, "catalogo_sap/material.html", {
        "m": m, "centros": m.centros.select_related("centro").order_by("centro__codigo"), "imagenes": imagenes,
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
