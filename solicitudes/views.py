"""Pantallas de solicitudes: Mis solicitudes, captura de AMAT_ZRA (fase 2), bandejas y corrección (fase 3)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.forms import Select
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import Almacen, CategoriaValoracion, Centro, GrupoCompras, Planificador

from . import alcance, alta_servicio, ampliacion, bandejas, duplicados, flujo, imagenes, lotes, modificacion, servicios
from .forms import CorreccionFormSet, PartidaCorreccionForm, PartidasFormSet
from .models import DetalleAlta, Flujo, ImagenPartida, Partida, Solicitud


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
    # Almacén propuesto por Centro: el predeterminado o, si no hay, el primero por código.
    almacenes = {}
    for a in Almacen.objects.filter(centro__in=centros, activo=True).order_by("-predeterminado", "codigo"):
        almacenes.setdefault(a.centro_id, a)
    grupos = GrupoCompras.objects.filter(centro__in=centros, predeterminado=True, activo=True)
    return {
        "cebe": {str(c.pk): c.centro_beneficio for c in centros},
        "almacenPredeterminado": {str(c): str(a.pk) for c, a in almacenes.items()},
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
            # attname = "almacen_id" para un catálogo: se lee el id sin consultar el objeto.
            fila[campo] = getattr(p.alta, DetalleAlta._meta.get_field(campo).attname)
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
        hay_archivos = bool(request.FILES)
        if accion == "eliminar" or (formset.is_valid() and not formset.renglones and accion not in ("enviar", "validar")):
            # Un borrador sin partidas no sirve de nada: se elimina en vez de quedar vacío
            # en "Mis solicitudes" (Revisión 3: lo que nunca entró al flujo puede eliminarse).
            if solicitud is not None:
                servicios.eliminar_borrador(solicitud)
                messages.success(request, "Borrador eliminado.")
            else:
                messages.info(request, "No había partidas; no se guardó nada.")
            return redirect("solicitudes:mis_solicitudes")
        if accion == "guardar":
            accion = "validar"  # pedido de Dave: Guardar borrador también valida, igual que Enter
        if accion in ("enviar", "validar") and formset.is_valid() and not formset.renglones:
            messages.error(request, "Agrega al menos una partida antes de enviar.")
        elif not formset.is_valid():
            aviso = " Vuelve a elegir las imágenes: el navegador no las conserva." if hay_archivos else ""
            messages.error(request, "Hay valores inválidos; no se guardó nada. Corrige las celdas marcadas." + aviso)
        else:
            # Pedido de Dave: las imágenes se eligen en la misma tabla, sin guardar antes.
            # Por eso SIEMPRE se guarda primero el borrador con sus imágenes (una sola transacción)
            # y después, si la acción es Enviar, se revisa todo. Si el envío no pasa, nada se pierde:
            # queda como borrador, con las imágenes ya guardadas.
            try:
                with transaction.atomic():
                    guardada = servicios.guardar_borrador(request.user, formset, solicitud)
                    _adjuntar_imagenes(request, formset, guardada)
                solicitud = guardada
            except flujo.AccionNoPermitida as e:
                messages.error(request, f"No se guardó nada: {e} Vuelve a elegir las imágenes.")
            else:
                listo = formset.validar_para_envio()
                if listo:
                    # Fase 4: imágenes (mínimo 1) y duplicados contra el Catálogo SAP.
                    listo, avisos = servicios.revisar_envio(formset, solicitud)
                    for aviso in avisos:
                        messages.warning(request, aviso)
                if accion == "validar":
                    # Pedido de Dave: Enter y Guardar borrador revisan todo como si fuera a enviar,
                    # pero NO envían. Se guarda como borrador para no perder lo capturado ni las imágenes.
                    if listo:
                        messages.success(request, "Borrador guardado. Todo está correcto: ya puedes enviar.")
                        return redirect("solicitudes:editar_amat", pk=solicitud.pk)
                    messages.error(request, "Borrador guardado, pero hay celdas por corregir antes de enviar (marcadas en rojo).")
                elif listo:
                    solicitud = servicios.enviar(request.user, formset, solicitud)
                    messages.success(request, f"Solicitud enviada con folio {solicitud.folio}.")
                    return redirect("solicitudes:detalle", pk=solicitud.pk)
                else:
                    messages.error(request, "No se pudo enviar; quedó guardada como borrador (con sus imágenes). Corrige las celdas marcadas.")
    else:
        iniciales = _filas_iniciales(solicitud) if solicitud else [{"numero": n} for n in range(10, 60, 10)]  # 5 renglones vacíos (10 a 50); los vacíos se ignoran al guardar
        formset = PartidasFormSet(initial=iniciales, centros=centros)

    _marcar_guardadas(formset, solicitud, "numero")
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
        return solicitud.partidas.filter(alcance.de_mis_centros(usuario)).exists()
    return False


@login_required
def detalle(request, pk):
    """Vista de solo lectura de una solicitud, con la historia de cada partida."""
    solicitud = get_object_or_404(
        Solicitud.objects.select_related("solicitante").prefetch_related(
            "partidas__alta", "partidas__centro", "partidas__ampliacion__material", "partidas__ampliacion__centro_origen",
            "partidas__ampliacion__almacen_destino", "partidas__ampliacion__almacen_modelo",
            "partidas__ampliacion__planificador", "partidas__ampliacion__grupo_compras",
            "partidas__modificacion__material", "partidas__servicio__umb", "partidas__servicio__grupo_articulos",
        ), pk=pk
    )
    if not puede_ver(request.user, solicitud):
        raise PermissionDenied("Esta solicitud no es tuya ni de tus Centros.")
    roles = flujo.roles_de(request.user)
    centros = set(request.user.centros.values_list("pk", flat=True))
    return render(request, "solicitudes/detalle.html", {
        "solicitud": solicitud,
        "eventos": solicitud.eventos.select_related("usuario", "partida").order_by("fecha"),
        "puede_corregir": servicios.partidas_editables(request.user, solicitud).exists(),
        # AMPL_ZRA: DM con partidas EN_DM de sus Centros ve el botón para exportar, excluir y finalizar.
        "atiende_dm": solicitud.flujo == Flujo.AMPL_ZRA and "DM" in roles
        and ampliacion.partidas_dm(request.user, solicitud).exists(),
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
        t = filtros["texto"]
        # AMPL no tiene descripción propia: se busca en la del material y en su código.
        partidas = partidas.filter(Q(alta__descripcion__icontains=t) | Q(ampliacion__material__descripcion__icontains=t)
                                   | Q(ampliacion__codigo_sap__startswith=t) | Q(servicio__descripcion__icontains=t)
                                   | Q(modificacion__codigo_sap__startswith=t) | Q(modificacion__material__descripcion__icontains=t))

    # Motivos escritos antes de un error (ver accion_en_bloque): se muestran de nuevo una sola vez.
    capturados = request.session.pop("motivos_bandeja", {})
    if capturados:
        partidas = list(partidas)
        for p in partidas:
            p.motivo_capturado = capturados.get(str(p.pk), "")

    return render(request, "solicitudes/pendientes.html", {
        "pestanas": [(c, t, bandejas.partidas_de(request.user, c).count()) for c, t in pestanas],
        "activa": activa,
        "partidas": partidas,
        "filtros": filtros,
        "hay_lote": activa == "dm" and lotes.pendientes(request.user).exists(),
        "hay_amat": activa == "dm" and bandejas.partidas_de(request.user, "dm").filter(
            solicitud__flujo__in=[Flujo.AMAT_ZRA, Flujo.ASER_ZSA]).exists(),
        "hay_finalizar": activa == "dm" and lotes.pendientes(request.user, lotes.FLUJOS).exists(),
    })


@login_required
@require_POST
def accion_en_bloque(request):
    """Aprobar, devolver o cancelar varias partidas a la vez (todas o ninguna)."""
    accion = request.POST.get("accion", "")
    ids = request.POST.getlist("partidas")
    # Un motivo por partida: cada renglón manda "motivo-<id>".
    motivos = {i: request.POST.get(f"motivo-{i}", "") for i in ids}
    try:
        n = flujo.aplicar(request.user, accion, ids, motivos)
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
        # Para no perder lo escrito: los motivos se guardan en la sesión y la bandeja los vuelve a poner.
        request.session["motivos_bandeja"] = {k: v for k, v in motivos.items() if v.strip()}
    else:
        textos = {
            "aprobar": "aprobada(s) y enviada(s) a Datos Maestros", "devolver": "devuelta(s) al solicitante",
            "cancelar": "cancelada(s)", "reenviar": "reenviada(s)", "cancelar_propia": "cancelada(s)",
            "devolver_a_validacion": "devuelta(s) a validación",
            "excluir": "excluida(s); ya no salen en el TXT",
        }
        messages.success(request, f"{n} partida(s) {textos[accion]}.")
        _avisar_si_nadie_las_ve(request, accion, ids)
    return _volver_a_bandeja(request)


# Rol que debe atender las partidas después de cada acción.
SIGUIENTE_ROL = {"aprobar": "DM", "reenviar": "VAL_MAT", "devolver_a_validacion": "VAL_MAT"}


def _avisar_si_nadie_las_ve(request, accion, ids):
    """Si ningún usuario del siguiente rol tiene el Centro de estas partidas, nadie las verá en su bandeja."""
    rol = SIGUIENTE_ROL.get(accion)
    if accion == "reenviar" and "VAL_MAT" in flujo.roles_de(request.user):
        rol = "DM"  # quien también es VAL_MAT reenvía directo a DM
    huerfanos = bandejas.centros_sin_rol(ids, rol) if rol else []
    if huerfanos:
        messages.warning(
            request,
            f"Ojo: ningún usuario activo con rol {rol} tiene autorizado el Centro {', '.join(huerfanos)}. "
            f"Nadie verá estas partidas hasta que ADMIN le asigne ese Centro a un usuario {rol}.",
        )


def _volver_a_bandeja(request):
    """Regresa a la misma pestaña y con los mismos filtros desde los que se hizo la acción."""
    query = {k: request.POST[k] for k in ("tab", "folio", "centro", "texto") if request.POST.get(k)}
    return redirect(f"{reverse('solicitudes:pendientes')}?{urlencode(query)}")


@login_required
@require_POST
def exportar_dm(request):
    """DM: un solo TXT con TODAS las partidas marcadas en la bandeja (ampliaciones o modificaciones),
    de uno o varios folios. Exportar no cambia estados: se puede repetir las veces que haga falta."""
    try:
        codigos = {k.removeprefix("codigo-"): v for k, v in request.POST.items() if k.startswith("codigo-")}
        nombre, texto = lotes.exportar(request.user, request.POST.getlist("partidas"), codigos)
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
        return _volver_a_bandeja(request)
    respuesta = HttpResponse(texto, content_type="text/plain; charset=utf-8")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@login_required
@require_POST
def finalizar_dm(request):
    """DM: termina lo marcado. Ampliación: el Centro nuevo entra al catálogo. Modificación: el valor nuevo."""
    try:
        n = lotes.finalizar(request.user, request.POST.getlist("partidas"))
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{n} partida(s) terminada(s); el catálogo ya tiene los cambios.")
    return _volver_a_bandeja(request)


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
    solicitud = get_object_or_404(Solicitud, pk=pk, flujo__in=[Flujo.AMAT_ZRA, Flujo.AMPL_ZRA, Flujo.MOD_ZRA, Flujo.MOD_ZSA, Flujo.ASER_ZSA])
    editables = list(servicios.partidas_editables(request.user, solicitud).select_related("alta", "ampliacion", "modificacion", "servicio"))
    if not editables:
        messages.error(request, "No tienes partidas de esta solicitud para corregir.")
        return redirect("solicitudes:detalle", pk=solicitud.pk)
    if solicitud.flujo == Flujo.AMPL_ZRA:
        return _corregir_ampl(request, solicitud, editables)
    if solicitud.flujo in modificacion.FLUJOS:
        return _corregir_mod(request, solicitud, editables)
    if solicitud.flujo == Flujo.ASER_ZSA:
        return _corregir_aser(request, solicitud, editables)

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
                    n = servicios.guardar_correcciones(request.user, formset.renglones, solicitud)
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
    _marcar_guardadas(formset, solicitud, "pid")
    return render(request, "solicitudes/corregir.html", {
        "solicitud": solicitud,
        "formset": formset,
        "datos_automaticos": _datos_automaticos(centros),
        "puede_reenviar": puede_reenviar,
        "es_solicitante": es_solicitante,
    })


def _adjuntar_imagenes(request, formset, solicitud):
    """Las imágenes elegidas en cada renglón (campo "form-N-imagenes") se agregan a su partida.

    Si una falla (no es imagen, pesa más de 10 MB, ya son 3…), se marca ese renglón y se
    relanza el error: la transacción de afuera deshace TODO, borrador incluido.
    """
    for form in formset.renglones:
        archivos = request.FILES.getlist(f"{form.prefix}-imagenes")
        if not archivos:
            continue
        partida = solicitud.partidas.get(numero=form.cleaned_data["numero"])
        try:
            imagenes.agregar(request.user, partida, archivos)
        except flujo.AccionNoPermitida as e:
            form.error_imagen = str(e)
            raise flujo.AccionNoPermitida(f"partida {partida.numero}: {e}")


def _marcar_guardadas(formset, solicitud, llave):
    """Fase 4: a cada renglón le pega su partida ya guardada (con cuántas imágenes tiene),
    para la columna Imágenes. Un renglón nuevo, que aún no se guarda, queda en None.

    `llave` es "numero" en la captura (el borrador se identifica por número de partida)
    o "pid" en la corrección (cada renglón trae el id de su partida).
    """
    guardadas = {}
    if solicitud is not None:
        for p in solicitud.partidas.annotate(n_imagenes=Count("imagenes")):
            guardadas[p.numero if llave == "numero" else p.pk] = p
    for form in formset.forms:
        form.guardada = guardadas.get(_entero(form[llave].value()))


def _entero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


# --- Ficha de una sola partida (pedido de Dave, 27-nov-2026) --------------------------------
# Desde "Pendientes de mi atención" cada partida abre su propia ficha tipo formulario:
# sus datos, su historia y solo las acciones que el usuario puede hacer sobre ella.

ETIQUETAS_ACCION = {
    "aprobar": ("Aprobar", "btn-primary"),
    "reenviar": ("Reenviar", "btn-primary"),
    "devolver": ("Devolver al solicitante", "btn-outline-secondary"),
    "devolver_a_validacion": ("Devolver a VAL_MAT", "btn-outline-secondary"),
    "cancelar": ("Cancelar partida", "btn-outline-danger"),
    "cancelar_propia": ("Cancelar partida", "btn-outline-danger"),
}
PESTANA_DE_ESTADO = {
    Partida.Estado.DEVUELTA_SOL: "sol", Partida.Estado.EN_VALIDACION: "val", Partida.Estado.EN_DM: "dm",
}


def _acciones_posibles(usuario, partida):
    """Acciones de flujo.TRANSICIONES que este usuario puede aplicar a esta partida ahora."""
    roles = flujo.roles_de(usuario)
    en_mis_centros = alcance.en_mi_alcance(usuario, partida)
    acciones = []
    for clave, t in flujo.TRANSICIONES.items():
        if t.desde != partida.estado or t.rol not in roles or clave in flujo.SOLO_AMPLIACION:
            continue  # excluir es solo de AMPL, que se atiende en su propia pantalla de DM
        permitido = partida.solicitud.solicitante_id == usuario.pk if t.solo_propias else en_mis_centros
        if permitido:
            etiqueta, clase = ETIQUETAS_ACCION[clave]
            acciones.append({"clave": clave, "etiqueta": etiqueta, "clase": clase, "pide_motivo": t.pide_motivo})
    return acciones


@login_required
def partida(request, pk):
    p = get_object_or_404(
        Partida.objects.select_related(
            "solicitud__solicitante", "centro", "alta__ubicacion", "alta__umb", "alta__grupo_articulos",
            "alta__categoria_valoracion", "alta__tipo_material", "alta__almacen", "alta__grupo_compras",
        ),
        pk=pk,
    )
    solicitud = p.solicitud
    if not puede_ver(request.user, solicitud):
        raise PermissionDenied("Esta partida no es tuya ni de tus Centros.")
    if solicitud.flujo != Flujo.AMAT_ZRA:
        # AMPL y MOD no tienen ficha por partida: sus datos caben en un renglón del detalle.
        return redirect(f"{reverse('solicitudes:detalle', args=[solicitud.pk])}#partida-{p.numero}")

    editable = servicios.partidas_editables(request.user, solicitud).filter(pk=p.pk).exists()
    centros = request.user.centros.filter(activo=True)
    form = None
    if editable:
        inicial = {"pid": p.pk, "numero": p.numero, "centro": p.centro_id}
        for campo in servicios.CAMPOS_DETALLE:
            valor = getattr(p.alta, campo)
            inicial[campo] = getattr(valor, "pk", valor)
        form = PartidaCorreccionForm(request.POST or None, initial=inicial, centros=centros)
        for campo in form.fields.values():  # estilo de Bootstrap para cada control
            campo.widget.attrs["class"] = "form-select" if isinstance(campo.widget, Select) else "form-control"

    volver = _volver_de_ficha(request.user, p)

    if request.method == "POST":
        accion = request.POST.get("accion", "")
        motivo = request.POST.get("motivo", "")
        try:
            with transaction.atomic():
                # Si la ficha es editable, primero se guardan los cambios (también al aprobar o reenviar).
                if form is not None:
                    if not form.is_valid():
                        raise flujo.AccionNoPermitida("Hay valores inválidos; corrige los campos marcados.")
                    if accion == "reenviar":
                        for campo in form.faltantes():
                            form.add_error(campo, "Obligatorio para enviar.")
                        if form.errors:
                            raise flujo.AccionNoPermitida("Faltan datos obligatorios para reenviar.")
                    n = servicios.guardar_correcciones(request.user, [form], solicitud)
                if accion == "guardar":
                    if form is None:
                        raise flujo.AccionNoPermitida("No puedes modificar esta partida.")
                    messages.success(request, f"Cambios guardados: {n} campo(s).")
                    return redirect("solicitudes:partida", pk=p.pk)
                if accion == "terminar":
                    flujo.terminar_con_codigos(request.user, {p.pk: request.POST.get("codigo", "")})
                    messages.success(request, f"Partida {solicitud.folio}/{p.numero} terminada; ya está en el Catálogo SAP.")
                else:
                    flujo.aplicar(request.user, accion, [p.pk], motivo)
                    messages.success(request, f"Partida {solicitud.folio}/{p.numero}: {ETIQUETAS_ACCION[accion][0].lower()} listo.")
                    _avisar_si_nadie_las_ve(request, accion, [p.pk])
            return redirect(volver)
        except flujo.ErroresCodigo as e:
            messages.error(request, e.errores[p.pk])
        except (flujo.AccionNoPermitida, PermissionError) as e:
            messages.error(request, str(e))

    return render(request, "solicitudes/partida.html", {
        "p": p,
        "solicitud": solicitud,
        "form": form,
        "acciones": _acciones_posibles(request.user, p),
        "puede_terminar": (
            p.estado == Partida.Estado.EN_DM and "DM" in flujo.roles_de(request.user)
            and request.user.centros.filter(pk=p.centro_id).exists()
        ),
        "eventos": p.eventos.select_related("usuario").order_by("fecha"),
        "volver": volver,
        "cebe": p.centro.centro_beneficio if p.centro else "",
        # Fase 4
        "imagenes": p.imagenes.all(),
        "edita_imagenes": imagenes.puede_editar(request.user, p),
        "lugares_libres": imagenes.MAX_IMAGENES - p.imagenes.count(),
        "coincidencias": _coincidencias_de(p),
        **_vecinas(p),
    })


def _vecinas(p):
    """La partida anterior y la siguiente de la MISMA solicitud, por número (pedido de Dave:
    flechas para moverse entre partidas sin regresar a la lista).

    SQL de "siguiente": ... WHERE solicitud_id = 7 AND numero > 20 ORDER BY numero LIMIT 1
    """
    hermanas = Partida.objects.filter(solicitud_id=p.solicitud_id)
    numeros = list(hermanas.order_by("numero").values_list("numero", flat=True))
    return {
        "anterior": hermanas.filter(numero__lt=p.numero).order_by("-numero").first(),
        "siguiente": hermanas.filter(numero__gt=p.numero).order_by("numero").first(),
        "posicion": numeros.index(p.numero) + 1,
        "total_partidas": len(numeros),
    }


def _volver_de_ficha(usuario, p):
    """A dónde regresa el enlace de la ficha: un borrador vuelve a su tabla de captura;
    lo que está en una bandeja, a esa pestaña; lo demás, a la solicitud completa."""
    if p.estado == Partida.Estado.BORRADOR:
        return reverse("solicitudes:editar_amat", args=[p.solicitud_id])
    pestana = PESTANA_DE_ESTADO.get(p.estado)
    if pestana:
        return f"{reverse('solicitudes:pendientes')}?tab={pestana}"
    return reverse("solicitudes:detalle", args=[p.solicitud_id])


def _coincidencias_de(p):
    """Duplicados en el Catálogo SAP. Se omite el propio código si la partida ya terminó
    (si no, toda partida TERMINADA saldría como duplicado de sí misma)."""
    if p.solicitud.flujo != Flujo.AMAT_ZRA:
        return []
    propio = p.alta.codigo_sap
    return [c for c in duplicados.buscar(p.alta.descripcion, p.alta.no_parte_original) if c.codigo != propio]


# --- Fase 4: imágenes y búsqueda de coincidencias --------------------------------------------


@login_required
@require_POST
def subir_imagenes(request, pk):
    p = get_object_or_404(Partida.objects.select_related("solicitud"), pk=pk)
    archivos = request.FILES.getlist("imagenes")
    if not archivos:
        messages.error(request, "Elige al menos una imagen.")
    else:
        try:
            n = imagenes.agregar(request.user, p, archivos)
            messages.success(request, f"{n} imagen(es) agregada(s).")
        except flujo.AccionNoPermitida as e:
            messages.error(request, str(e))
    return redirect("solicitudes:partida", pk=p.pk)


@login_required
@require_POST
def quitar_imagen(request, pk):
    imagen = get_object_or_404(ImagenPartida, pk=pk)
    try:
        imagenes.quitar(request.user, imagen)
        messages.success(request, f"Imagen {imagen.orden} quitada.")
    except flujo.AccionNoPermitida as e:
        messages.error(request, str(e))
    return redirect("solicitudes:partida", pk=imagen.partida_id)


@login_required
def ver_imagen(request, pk):
    """Sirve el archivo SOLO a quien puede ver la solicitud.

    Por eso las imágenes no se publican en /media/ como un archivo estático: cualquiera
    con la liga podría verlas. Aquí cada petición pasa por puede_ver.
    """
    imagen = get_object_or_404(ImagenPartida.objects.select_related("partida__solicitud"), pk=pk)
    # El catálogo es global (Revisión 3): las imágenes de un material YA dado de alta las ve
    # cualquier usuario desde el catálogo. Las de partidas en trámite, solo quien ve la solicitud.
    en_catalogo = MaterialSAP.objects.filter(partida_origen_id=imagen.partida_id).exists()
    if not en_catalogo and not puede_ver(request.user, imagen.partida.solicitud):
        raise PermissionDenied("Esta imagen no es tuya ni de tus Centros.")
    try:
        archivo = imagen.archivo.open("rb")
    except FileNotFoundError:
        raise Http404("El archivo de la imagen no está en el disco.")
    if request.GET.get("descargar"):
        # as_attachment manda "Content-Disposition: attachment": el navegador la guarda en vez de mostrarla.
        nombre = f"{imagen.partida.solicitud.folio or 'borrador'}-partida-{imagen.partida.numero}-imagen-{imagen.orden}.webp"
        return FileResponse(archivo, content_type="image/webp", as_attachment=True, filename=nombre)
    respuesta = FileResponse(archivo, content_type="image/webp")
    respuesta["Cache-Control"] = "private, max-age=3600"
    return respuesta


@login_required
def coincidencias(request):
    """JSON para "Buscar coincidencias" y el aviso mientras se escribe.

    Ejemplo: GET /solicitudes/coincidencias/?descripcion=FILTRO%20AIRE&no_parte=ABC-1
    """
    resultados = duplicados.buscar(request.GET.get("descripcion", ""), request.GET.get("no_parte", ""))
    return JsonResponse({"coincidencias": [c.como_dict() for c in resultados]})


# --- Fase 4c: AMPL_ZRA, ampliación de material a Centro (Revisión 3, sección 10) --------------


def _datos_ampliacion(centros):
    """Lo que el JavaScript necesita para proponer valores: por Centro, su CeBe y sus predeterminados."""
    def primeros(modelo):
        elegidos = {}
        for x in modelo.objects.filter(activo=True).order_by("-predeterminado", "codigo"):
            elegidos.setdefault(str(x.centro_id), str(x.pk))
        return elegidos

    return {
        "cebe": {str(c.pk): c.centro_beneficio for c in Centro.objects.filter(activo=True)},
        "almacen": primeros(Almacen),
        "grupo": primeros(GrupoCompras),
        "planificador": primeros(Planificador),
        "urlMaterial": reverse("solicitudes:material_ampl"),
    }


@login_required
def material_ampl(request):
    """JSON para la captura AMPL: descripción del material y los Centros donde ya existe."""
    material = ampliacion.material_de(request.GET.get("codigo", "").strip())
    if material is None:
        return JsonResponse({"existe": False})
    centros = ampliacion.centros_del_material(material)
    return JsonResponse({
        "existe": True, "descripcion": material.descripcion,
        "centros": [{"id": c.pk, "codigo": c.codigo} for c in centros],
    })


@login_required
def capturar_ampl(request, pk=None):
    """Nueva solicitud AMPL_ZRA o edición de un borrador propio."""
    if not servicios.puede_capturar(request.user):
        raise PermissionDenied("Necesitas el rol SOL_MAT o VAL_MAT.")
    solicitud = None
    if pk:
        solicitud = get_object_or_404(Solicitud, pk=pk, flujo=Flujo.AMPL_ZRA, solicitante=request.user)
        if solicitud.estado != Solicitud.Estado.BORRADOR:
            return redirect("solicitudes:detalle", pk=solicitud.pk)
    centros = request.user.centros.filter(activo=True)

    if request.method == "POST":
        formset = ampliacion.AmpliacionFormSet(request.POST, centros=centros)
        accion = request.POST.get("accion")
        if accion == "eliminar" or (formset.is_valid() and not formset.renglones and accion not in ("enviar", "validar")):
            if solicitud is not None:
                servicios.eliminar_borrador(solicitud)
                messages.success(request, "Borrador eliminado.")
            else:
                messages.info(request, "No había partidas; no se guardó nada.")
            return redirect("solicitudes:mis_solicitudes")
        # Pedido de Dave: Enter, Guardar borrador y Enviar validan todo igual. Primero se guarda el
        # borrador (para no perder nada) y luego se revisa como si fuera a enviar; solo Enviar envía.
        elif not formset.is_valid():
            messages.error(request, "Hay valores inválidos; no se guardó nada. Corrige las celdas marcadas.")
        elif not formset.renglones:
            messages.error(request, "Agrega al menos una partida antes de enviar.")
        else:
            solicitud = ampliacion.guardar_borrador(request.user, formset, solicitud)
            listo = formset.validar_para_envio()
            if listo and accion == "enviar":
                solicitud = ampliacion.enviar(request.user, formset, solicitud)
                messages.success(request, f"Solicitud enviada con folio {solicitud.folio}.")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if listo:
                messages.success(request, "Borrador guardado. Todo está correcto: ya puedes enviar.")
                return redirect("solicitudes:editar_ampl", pk=solicitud.pk)
            no_envio = "; no se envió" if accion == "enviar" else ""
            messages.error(request, f"Borrador guardado{no_envio}. Hay celdas por corregir antes de enviar (marcadas en rojo).")
    else:
        iniciales = ampliacion.filas_iniciales(solicitud) if solicitud else [{"numero": n} for n in range(10, 60, 10)]
        formset = ampliacion.AmpliacionFormSet(initial=iniciales, centros=centros)

    return render(request, "solicitudes/capturar_ampl.html", {
        "solicitud": solicitud, "formset": formset, "datos_automaticos": _datos_ampliacion(centros),
        "sin_centros": not centros.exists(),
    })


# --- Fase 4d: modificaciones MOD_ZRA (materiales) y MOD_ZSA (servicios) -------------------

TIPOS_MOD = {"materiales": Flujo.MOD_ZRA, "servicios": Flujo.MOD_ZSA}
URL_MOD = {v: k for k, v in TIPOS_MOD.items()}


def _flujo_mod(tipo):
    if tipo not in TIPOS_MOD:
        raise Http404("Tipo de modificación desconocido.")
    return TIPOS_MOD[tipo]


def _datos_modificacion(centros, flujo_mod):
    """Lo que usa static/js/modificacion.js: la lista de datos, sus catálogos y la URL del material."""
    from catalogos.models import GrupoArticulos, UbicacionRefaccion

    por_centro = lambda modelo: {  # noqa: E731
        str(c.pk): [x.codigo for x in modelo.objects.filter(centro=c, activo=True).order_by("codigo")] for c in centros
    }
    return {
        "campos": [{"valor": c.value, "texto": c.label, "porCentro": c in modificacion.POR_CENTRO}
                   for c in modificacion.campos_de(flujo_mod)],
        "catalogos": {
            "GRUPO_ARTICULOS": list(GrupoArticulos.objects.filter(activo=True).order_by("codigo").values_list("codigo", flat=True)),
            "UBICACION": list(UbicacionRefaccion.objects.filter(activo=True).order_by("codigo").values_list("codigo", flat=True)),
        },
        "porCentro": {"GRUPO_COMPRAS": por_centro(GrupoCompras), "ALMACEN": por_centro(Almacen)},
        "centros": {c.codigo: str(c.pk) for c in centros},
        "servicio": modificacion.es_servicio(flujo_mod),
        "urlMaterial": reverse("solicitudes:material_mod") + f"?tipo={URL_MOD[flujo_mod]}",
    }


@login_required
def material_mod(request):
    """JSON para la captura MOD: descripción del material y el valor actual de cada dato."""
    flujo_mod = _flujo_mod(request.GET.get("tipo", ""))
    material = modificacion.material_de(request.GET.get("codigo", "").strip(), flujo_mod)
    if material is None:
        return JsonResponse({"existe": False})
    generales = {c.value: modificacion.valor_actual(material, c) for c in modificacion.campos_de(flujo_mod)
                 if c not in modificacion.POR_CENTRO}
    por_centro = {
        str(mc.centro_id): {c.value: modificacion.valor_actual(material, c, mc) for c in modificacion.POR_CENTRO}
        for mc in MaterialCentro.objects.filter(material=material)
    }
    return JsonResponse({"existe": True, "descripcion": material.descripcion, "valores": generales, "porCentro": por_centro})


@login_required
def capturar_mod(request, tipo, pk=None):
    """Nueva solicitud MOD_ZRA / MOD_ZSA o edición de un borrador propio."""
    flujo_mod = _flujo_mod(tipo)
    if not servicios.puede_capturar(request.user):
        raise PermissionDenied("Necesitas el rol SOL_MAT o VAL_MAT.")
    solicitud = None
    if pk:
        solicitud = get_object_or_404(Solicitud, pk=pk, flujo=flujo_mod, solicitante=request.user)
        if solicitud.estado != Solicitud.Estado.BORRADOR:
            return redirect("solicitudes:detalle", pk=solicitud.pk)
    centros = request.user.centros.filter(activo=True)
    editar = lambda s: redirect("solicitudes:editar_mod", tipo=tipo, pk=s.pk)  # noqa: E731

    if request.method == "POST":
        formset = modificacion.ModificacionFormSet(request.POST, centros=centros, flujo=flujo_mod, solicitud=solicitud)
        accion = request.POST.get("accion")
        if accion == "eliminar" or (formset.is_valid() and not formset.renglones and accion not in ("enviar", "validar")):
            if solicitud is not None:
                servicios.eliminar_borrador(solicitud)
                messages.success(request, "Borrador eliminado.")
            else:
                messages.info(request, "No había partidas; no se guardó nada.")
            return redirect("solicitudes:mis_solicitudes")
        # Igual que AMAT y AMPL: Enter, Guardar borrador y Enviar guardan y luego validan; solo Enviar envía.
        elif not formset.is_valid():
            messages.error(request, "Hay valores inválidos; no se guardó nada. Corrige las celdas marcadas.")
        elif not formset.renglones:
            messages.error(request, "Agrega al menos una partida antes de enviar.")
        else:
            solicitud = modificacion.guardar_borrador(request.user, formset, solicitud)
            formset.solicitud = solicitud
            listo = formset.validar_para_envio()
            if listo and accion == "enviar":
                solicitud = modificacion.enviar(request.user, formset, solicitud)
                messages.success(request, f"Solicitud enviada con folio {solicitud.folio}.")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if listo:
                messages.success(request, "Borrador guardado. Todo está correcto: ya puedes enviar.")
                return editar(solicitud)
            no_envio = "; no se envió" if accion == "enviar" else ""
            messages.error(request, f"Borrador guardado{no_envio}. Hay celdas por corregir antes de enviar (marcadas en rojo).")
    else:
        iniciales = modificacion.filas_iniciales(solicitud) if solicitud else [{"numero": n} for n in range(10, 60, 10)]
        formset = modificacion.ModificacionFormSet(initial=iniciales, centros=centros, flujo=flujo_mod, solicitud=solicitud)

    return render(request, "solicitudes/capturar_mod.html", {
        "solicitud": solicitud, "formset": formset, "flujo": flujo_mod, "tipo": tipo,
        "servicio": modificacion.es_servicio(flujo_mod),
        "datos_automaticos": _datos_modificacion(centros, flujo_mod), "sin_centros": not centros.exists(),
    })


def _corregir_mod(request, solicitud, editables):
    """Corregir partidas MOD devueltas o en validación: la misma tabla, con el id de cada partida."""
    centros = request.user.centros.filter(activo=True)
    es_solicitante = solicitud.solicitante_id == request.user.pk
    puede_reenviar = es_solicitante and any(p.estado == Partida.Estado.DEVUELTA_SOL for p in editables)
    iniciales = [
        {"pid": p.pk, "numero": p.numero, "codigo_sap": p.modificacion.codigo_sap, "centro": p.centro_id,
         "campo": p.modificacion.campo, "valor_nuevo": p.modificacion.valor_nuevo}
        for p in editables
    ]
    kwargs = {"centros": centros, "flujo": solicitud.flujo, "solicitud": solicitud}
    if request.method == "POST":
        formset = modificacion.ModificacionCorreccionFormSet(request.POST, initial=iniciales, **kwargs)
        accion = request.POST.get("accion")
        valido = formset.validar_para_envio() if accion == "reenviar" else formset.is_valid()
        if valido:
            devueltas = {p.pk for p in editables if p.estado == Partida.Estado.DEVUELTA_SOL}
            try:
                with transaction.atomic():
                    n = modificacion.guardar_correcciones(request.user, formset.renglones, solicitud)
                    if accion == "reenviar":
                        ids = [f.cleaned_data["pid"] for f in formset.renglones if f.cleaned_data["pid"] in devueltas]
                        flujo.aplicar(request.user, "reenviar", ids)
            except (PermissionError, flujo.AccionNoPermitida) as e:
                messages.error(request, str(e))
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if accion == "reenviar":
                messages.success(request, f"Partidas reenviadas ({n} dato(s) corregido(s)).")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            messages.success(request, f"Correcciones guardadas: {n} dato(s) cambiado(s).")
            return redirect("solicitudes:corregir", pk=solicitud.pk)
        messages.error(request, "No se guardó nada. Corrige las celdas marcadas; tus datos siguen en pantalla.")
    else:
        formset = modificacion.ModificacionCorreccionFormSet(initial=iniciales, **kwargs)
    estados = {p.pk: p.get_estado_display() for p in editables}
    for form in formset:
        form.estado_partida = estados.get(_entero(form["pid"].value()), "")
    return render(request, "solicitudes/capturar_mod.html", {
        "solicitud": solicitud, "formset": formset, "flujo": solicitud.flujo, "tipo": URL_MOD[solicitud.flujo],
        "servicio": modificacion.es_servicio(solicitud.flujo), "correccion": True, "puede_reenviar": puede_reenviar,
        "datos_automaticos": _datos_modificacion(centros, solicitud.flujo),
    })


# --- Fase 4e: alta de servicios ASER_ZSA -------------------------------------------------


@login_required
def capturar_aser(request, pk=None):
    """Nueva solicitud ASER_ZSA o edición de un borrador propio."""
    if not servicios.puede_capturar(request.user):
        raise PermissionDenied("Necesitas el rol SOL_MAT o VAL_MAT.")
    solicitud = None
    if pk:
        solicitud = get_object_or_404(Solicitud, pk=pk, flujo=Flujo.ASER_ZSA, solicitante=request.user)
        if solicitud.estado != Solicitud.Estado.BORRADOR:
            return redirect("solicitudes:detalle", pk=solicitud.pk)

    if request.method == "POST":
        formset = alta_servicio.ServicioFormSet(request.POST)
        accion = request.POST.get("accion")
        if accion == "eliminar" or (formset.is_valid() and not formset.renglones and accion not in ("enviar", "validar")):
            if solicitud is not None:
                servicios.eliminar_borrador(solicitud)
                messages.success(request, "Borrador eliminado.")
            else:
                messages.info(request, "No había partidas; no se guardó nada.")
            return redirect("solicitudes:mis_solicitudes")
        # Igual que las demás capturas: Enter, Guardar y Enviar guardan y luego validan; solo Enviar envía.
        elif not formset.is_valid():
            messages.error(request, "Hay valores inválidos; no se guardó nada. Corrige las celdas marcadas.")
        elif not formset.renglones:
            messages.error(request, "Agrega al menos una partida antes de enviar.")
        else:
            solicitud = alta_servicio.guardar_borrador(request.user, formset, solicitud)
            listo, avisos = formset.validar_para_envio()
            for aviso in avisos:
                messages.warning(request, aviso)
            if listo and accion == "enviar":
                solicitud = alta_servicio.enviar(request.user, formset, solicitud)
                messages.success(request, f"Solicitud enviada con folio {solicitud.folio}.")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if listo:
                messages.success(request, "Borrador guardado. Todo está correcto: ya puedes enviar.")
                return redirect("solicitudes:editar_aser", pk=solicitud.pk)
            no_envio = "; no se envió" if accion == "enviar" else ""
            messages.error(request, f"Borrador guardado{no_envio}. Hay celdas por corregir antes de enviar (marcadas en rojo).")
    else:
        iniciales = alta_servicio.filas_iniciales(solicitud) if solicitud else alta_servicio.filas_nuevas()
        formset = alta_servicio.ServicioFormSet(initial=iniciales)
    return render(request, "solicitudes/capturar_aser.html", _contexto_aser(solicitud, formset))


def _contexto_aser(solicitud, formset, **extra):
    umb = alta_servicio.umb_propuesta()
    return {"solicitud": solicitud, "formset": formset, "datos_automaticos": {"umb": str(umb.pk) if umb else ""},
            "sin_umb": umb is None, **extra}


def _corregir_aser(request, solicitud, editables):
    es_solicitante = solicitud.solicitante_id == request.user.pk
    puede_reenviar = es_solicitante and any(p.estado == Partida.Estado.DEVUELTA_SOL for p in editables)
    iniciales = [{"pid": p.pk, "numero": p.numero, "descripcion": p.servicio.descripcion, "umb": p.servicio.umb_id,
                  "grupo_articulos": p.servicio.grupo_articulos_id} for p in editables]
    if request.method == "POST":
        formset = alta_servicio.ServicioCorreccionFormSet(request.POST, initial=iniciales)
        accion = request.POST.get("accion")
        valido = formset.validar_para_envio()[0] if accion == "reenviar" else formset.is_valid()
        if valido:
            devueltas = {p.pk for p in editables if p.estado == Partida.Estado.DEVUELTA_SOL}
            try:
                with transaction.atomic():
                    n = alta_servicio.guardar_correcciones(request.user, formset.renglones, solicitud)
                    if accion == "reenviar":
                        ids = [f.cleaned_data["pid"] for f in formset.renglones if f.cleaned_data["pid"] in devueltas]
                        flujo.aplicar(request.user, "reenviar", ids)
            except (PermissionError, flujo.AccionNoPermitida) as e:
                messages.error(request, str(e))
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if accion == "reenviar":
                messages.success(request, f"Partidas reenviadas ({n} campo(s) corregido(s)).")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            messages.success(request, f"Correcciones guardadas: {n} campo(s) cambiado(s).")
            return redirect("solicitudes:corregir", pk=solicitud.pk)
        messages.error(request, "No se guardó nada. Corrige las celdas marcadas; tus datos siguen en pantalla.")
    else:
        formset = alta_servicio.ServicioCorreccionFormSet(initial=iniciales)
    estados = {p.pk: p.get_estado_display() for p in editables}
    for form in formset:
        form.estado_partida = estados.get(_entero(form["pid"].value()), "")
    return render(request, "solicitudes/capturar_aser.html",
                  _contexto_aser(solicitud, formset, correccion=True, puede_reenviar=puede_reenviar))


def _corregir_ampl(request, solicitud, editables):
    """Corregir partidas AMPL devueltas o en validación: la misma tabla, con el id de cada partida."""
    centros = request.user.centros.filter(activo=True)
    es_solicitante = solicitud.solicitante_id == request.user.pk
    puede_reenviar = es_solicitante and any(p.estado == Partida.Estado.DEVUELTA_SOL for p in editables)
    iniciales = []
    for p in editables:
        a = p.ampliacion
        iniciales.append({
            "pid": p.pk, "numero": p.numero, "codigo_sap": a.codigo_sap, "centro": p.centro_id,
            "almacen_destino": a.almacen_destino_id, "centro_origen": a.centro_origen_id,
            "almacen_modelo": a.almacen_modelo_id, "planificador": a.planificador_id, "grupo_compras": a.grupo_compras_id,
        })
    if request.method == "POST":
        formset = ampliacion.AmpliacionCorreccionFormSet(request.POST, initial=iniciales, centros=centros)
        accion = request.POST.get("accion")
        valido = formset.validar_para_envio() if accion == "reenviar" else formset.is_valid()
        if valido:
            devueltas = {p.pk for p in editables if p.estado == Partida.Estado.DEVUELTA_SOL}
            try:
                with transaction.atomic():
                    n = ampliacion.guardar_correcciones(request.user, formset.renglones, solicitud)
                    if accion == "reenviar":
                        ids = [f.cleaned_data["pid"] for f in formset.renglones if f.cleaned_data["pid"] in devueltas]
                        flujo.aplicar(request.user, "reenviar", ids)
            except (PermissionError, flujo.AccionNoPermitida) as e:
                messages.error(request, str(e))
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            if accion == "reenviar":
                messages.success(request, f"Partidas reenviadas ({n} campo(s) corregido(s)).")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            messages.success(request, f"Correcciones guardadas: {n} campo(s) cambiado(s).")
            return redirect("solicitudes:corregir", pk=solicitud.pk)
        messages.error(request, "No se guardó nada. Corrige las celdas marcadas; tus datos siguen en pantalla.")
    else:
        formset = ampliacion.AmpliacionCorreccionFormSet(initial=iniciales, centros=centros)
    estados = {p.pk: p.get_estado_display() for p in editables}
    for form in formset:
        form.estado_partida = estados.get(_entero(form["pid"].value()), "")
    return render(request, "solicitudes/capturar_ampl.html", {
        "solicitud": solicitud, "formset": formset, "datos_automaticos": _datos_ampliacion(centros),
        "correccion": True, "puede_reenviar": puede_reenviar, "es_solicitante": es_solicitante,
    })


@login_required
def ampliacion_dm(request, pk):
    """DM atiende una solicitud AMPL_ZRA: exporta Amp_Mat.txt, excluye con motivo y finaliza."""
    solicitud = get_object_or_404(Solicitud, pk=pk, flujo=Flujo.AMPL_ZRA)
    if "DM" not in flujo.roles_de(request.user):
        raise PermissionDenied("Necesitas el rol DM.")
    partidas = ampliacion.partidas_dm(request.user, solicitud)

    if request.GET.get("exportar"):
        # Exportar no es un estado ni bloquea nada (sección 10.4): se puede repetir.
        respuesta = HttpResponse(ampliacion.texto_txt(partidas), content_type="text/plain; charset=utf-8")
        respuesta["Content-Disposition"] = f'attachment; filename="{ampliacion.NOMBRE_TXT}"'
        return respuesta

    if request.method == "POST":
        try:
            if request.POST.get("accion") == "finalizar":
                n = ampliacion.finalizar(request.user, solicitud)
                messages.success(request, f"{n} partida(s) terminada(s); su Centro nuevo ya está en el catálogo de materiales.")
                return redirect("solicitudes:detalle", pk=solicitud.pk)
            ids = request.POST.getlist("partidas")
            n = flujo.aplicar(request.user, "excluir", ids, {i: request.POST.get(f"motivo-{i}", "") for i in ids})
            messages.success(request, f"{n} partida(s) excluida(s). Ya no salen en el TXT.")
        except flujo.AccionNoPermitida as e:
            messages.error(request, str(e))
        return redirect("solicitudes:ampliacion_dm", pk=solicitud.pk)

    return render(request, "solicitudes/ampliacion_dm.html", {
        "solicitud": solicitud, "partidas": partidas,
        "renglones": [(p, ampliacion.renglon_txt(p)) for p in partidas],
        "excluidas": solicitud.partidas.filter(estado=Partida.Estado.EXCLUIDA).select_related("ampliacion", "centro"),
    })
