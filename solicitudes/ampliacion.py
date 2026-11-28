"""AMPL_ZRA: ampliación de un material que ya existe a un Centro nuevo (Revisión 3, sección 10).

Layout definido por Dave (28-nov-2026):

    Captura:  Material | Centro nuevo | Almacén nuevo | Centro modelo | Almacén modelo
              (+ Planificador y Grupo de compras, que se proponen; el CeBe es automático)

    TXT para SAP (siempre se llama Amp_Mat.txt, sin encabezados, separado por tabuladores):
        1 Material  2 Material (el mismo)  3 Centro nuevo  4 Almacén nuevo  5 Centro modelo
        6 Almacén modelo  7 Planificador  8 Grupo de compras  9 CeBe

Flujo: SOL_MAT → VAL_MAT → DM (o VAL_MAT → DM si la crea un validador). DM exporta el TXT
las veces que quiera, excluye con motivo lo que SAP rechace y al Finalizar las partidas no
excluidas pasan a TERMINADA y su Centro nuevo se agrega al catálogo de materiales.

Igual que en AMAT, este archivo concentra las reglas; las vistas solo leen la petición.
"""

from django import forms
from django.db import transaction
from django.utils import timezone

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import Almacen, Centro, GrupoCompras, Planificador

from .folios import siguiente_folio
from .models import DetalleAmpliacion, Evento, Flujo, Partida, Solicitud

E = Partida.Estado
NOMBRE_TXT = "Amp_Mat.txt"

# Campos del detalle, en el orden de la tabla (también el orden del pegado desde Excel).
CAMPOS = ["codigo_sap", "centro", "almacen_destino", "centro_origen", "almacen_modelo", "planificador", "grupo_compras"]
OBLIGATORIOS_ENVIO = ["codigo_sap", "centro", "almacen_destino", "centro_origen", "almacen_modelo", "grupo_compras"]
NOMBRES = {
    "codigo_sap": "Material", "centro": "Centro nuevo", "almacen_destino": "Almacén nuevo",
    "centro_origen": "Centro modelo", "almacen_modelo": "Almacén modelo", "planificador": "Planificador",
    "grupo_compras": "Grupo de compras",
}


# --- Propuestas (valores predeterminados) ---------------------------------------------------


def _primero(modelo, centro):
    """El predeterminado del Centro o, si no hay, el primero activo por código (como en AMAT)."""
    if not centro:
        return None
    return modelo.objects.filter(centro=centro, activo=True).order_by("-predeterminado", "codigo").first()


def material_de(codigo):
    """El material (catálogo de MATERIALES, no servicios) con ese código, o None."""
    if not codigo:
        return None
    return MaterialSAP.objects.filter(codigo=codigo, es_servicio=False).first()


def centros_del_material(material):
    """Centros donde ya existe el material, por código de Centro. El primero es el que se propone como modelo."""
    if material is None:
        return Centro.objects.none()
    return Centro.objects.filter(materialcentro__material=material).order_by("codigo")


# --- Formulario: un renglón de la tabla ----------------------------------------------------


def _catalogo(queryset, etiqueta):
    return forms.ModelChoiceField(queryset=queryset.filter(activo=True), required=False, empty_label="", label=etiqueta)


class AmpliacionForm(forms.Form):
    numero = forms.IntegerField(min_value=1, required=False, label="Partida")
    codigo_sap = forms.CharField(max_length=6, required=False, label="Material")
    centro = forms.ModelChoiceField(queryset=Centro.objects.none(), required=False, empty_label="", label="Centro nuevo")
    almacen_destino = _catalogo(Almacen.objects.select_related("centro"), "Almacén nuevo")
    centro_origen = _catalogo(Centro.objects.all(), "Centro modelo")
    almacen_modelo = _catalogo(Almacen.objects.select_related("centro"), "Almacén modelo")
    planificador = _catalogo(Planificador.objects.select_related("centro"), "Planificador")
    grupo_compras = _catalogo(GrupoCompras.objects.select_related("centro"), "Grupo de compras")

    def __init__(self, *args, centros=None, **kwargs):
        super().__init__(*args, **kwargs)
        # El Centro nuevo solo puede ser uno de los Centros autorizados del usuario (sección 10.2).
        self.fields["centro"].queryset = centros if centros is not None else Centro.objects.none()
        self.material = None

    @property
    def vacio(self):
        datos = getattr(self, "cleaned_data", {})
        return all(datos.get(c) in (None, "") for c in CAMPOS)

    def clean_codigo_sap(self):
        codigo = self.cleaned_data["codigo_sap"].strip()
        if codigo and not (len(codigo) == 6 and codigo.isdigit()):
            raise forms.ValidationError("Debe tener 6 dígitos.")
        return codigo

    def clean(self):
        datos = super().clean()
        if not self.vacio and not datos.get("numero"):
            self.add_error("numero", "Falta el número de partida.")
        codigo = datos.get("codigo_sap")
        if codigo:
            self.material = material_de(codigo)
            if self.material is None:
                self.add_error("codigo_sap", "No existe en el catálogo de materiales.")
        destino, origen = datos.get("centro"), datos.get("centro_origen")
        # Cada catálogo por Centro tiene que ser de SU Centro.
        for campo, centro in [("almacen_destino", destino), ("planificador", destino), ("grupo_compras", destino),
                              ("almacen_modelo", origen)]:
            valor = datos.get(campo)
            if valor and centro and valor.centro_id != centro.id:
                self.add_error(campo, f"No pertenece al Centro {centro.codigo}.")
        if self.material and origen and not MaterialCentro.objects.filter(material=self.material, centro=origen).exists():
            self.add_error("centro_origen", f"El material no existe en {origen.codigo}; el Centro modelo debe ser uno donde ya exista.")
        if destino and origen and destino == origen:
            self.add_error("centro", "El Centro nuevo no puede ser el mismo que el Centro modelo.")
        return datos

    def faltantes(self):
        """Obligatorios vacíos DESPUÉS de aplicar las propuestas: lo que WebDM propone no se exige capturarlo."""
        datos = completar(self.cleaned_data, self.material)
        return [c for c in OBLIGATORIOS_ENVIO if datos.get(c) in (None, "")]


class BaseAmpliacionFormSet(forms.BaseFormSet):
    def __init__(self, *args, centros=None, **kwargs):
        self.centros = centros
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "centros": self.centros}

    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid() and not f.vacio]

    def clean(self):
        """Entre renglones: no se repite el número de partida ni la combinación Material + Centro nuevo."""
        if any(self.errors):
            return
        numeros, combinaciones = set(), {}
        for form in self.renglones:
            d = form.cleaned_data
            if d.get("numero") in numeros:
                form.add_error("numero", "Número de partida repetido.")
            numeros.add(d.get("numero"))
            llave = (d.get("codigo_sap"), d.get("centro"))
            if all(llave):
                if llave in combinaciones:
                    form.add_error("codigo_sap", f"Material y Centro nuevo repetidos (partida {combinaciones[llave]}).")
                combinaciones.setdefault(llave, d.get("numero"))

    def validar_para_envio(self):
        if not self.is_valid():
            return False
        if not self.renglones:
            self._non_form_errors = self.error_class(["Agrega al menos una partida antes de enviar."])
            return False
        ok = True
        for form in self.renglones:
            if ya_ampliado(form.material, form.cleaned_data.get("centro")):
                continue  # se omitirá al enviar (sección 10.3); no tiene caso exigirle datos
            for campo in form.faltantes():
                form.add_error(campo, "Obligatorio para enviar.")
                ok = False
            centro = form.cleaned_data.get("centro")
            if centro and not centro.centro_beneficio:
                form.add_error("centro", f"{centro.codigo} no tiene CeBe; avisa a ADMIN.")
                ok = False
        return ok


AmpliacionFormSet = forms.formset_factory(AmpliacionForm, formset=BaseAmpliacionFormSet, extra=0, can_delete=False)


class AmpliacionCorreccionForm(AmpliacionForm):
    """Corrección de partidas devueltas o en validación: lleva el id de su partida y no se renumera."""

    pid = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero"].disabled = True


class BaseAmpliacionCorreccionFormSet(BaseAmpliacionFormSet):
    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid()]


AmpliacionCorreccionFormSet = forms.formset_factory(
    AmpliacionCorreccionForm, formset=BaseAmpliacionCorreccionFormSet, extra=0, can_delete=False
)


# --- Guardar y enviar ------------------------------------------------------------------------


def completar(datos, material):
    """Llena con la propuesta lo que el usuario dejó vacío. Devuelve un dict nuevo.

    - Centro modelo: el primer Centro (por código) donde ya existe el material.
    - Almacén modelo: el predeterminado del Centro modelo.
    - Almacén nuevo, Planificador y Grupo de compras: los predeterminados del Centro nuevo.
      El Planificador puede quedar vacío si el Centro no tiene (sección 10.2).
    """
    d = dict(datos)
    if not d.get("centro_origen") and material:
        d["centro_origen"] = centros_del_material(material).exclude(pk=getattr(d.get("centro"), "pk", None)).first()
    if not d.get("almacen_modelo"):
        d["almacen_modelo"] = _primero(Almacen, d.get("centro_origen"))
    for campo, modelo in [("almacen_destino", Almacen), ("planificador", Planificador), ("grupo_compras", GrupoCompras)]:
        if not d.get(campo):
            d[campo] = _primero(modelo, d.get("centro"))
    return d


def filas_iniciales(solicitud):
    filas = []
    for p in solicitud.partidas.select_related("ampliacion").order_by("numero"):
        a = p.ampliacion
        filas.append({
            "numero": p.numero, "codigo_sap": a.codigo_sap, "centro": p.centro_id,
            "almacen_destino": a.almacen_destino_id, "centro_origen": a.centro_origen_id,
            "almacen_modelo": a.almacen_modelo_id, "planificador": a.planificador_id, "grupo_compras": a.grupo_compras_id,
        })
    return filas


def _guardar_detalle(partida, form):
    d = completar(form.cleaned_data, form.material)
    detalle = getattr(partida, "ampliacion", None) or DetalleAmpliacion(partida=partida)
    detalle.codigo_sap = d["codigo_sap"]
    detalle.material = form.material
    for campo in ["almacen_destino", "centro_origen", "almacen_modelo", "planificador", "grupo_compras"]:
        setattr(detalle, campo, d.get(campo))
    detalle.save()


@transaction.atomic
def guardar_borrador(usuario, formset, solicitud=None):
    """Crea o actualiza el borrador: las partidas quedan igual que la tabla (por número de partida)."""
    if solicitud is None:
        solicitud = Solicitud.objects.create(flujo=Flujo.AMPL_ZRA, solicitante=usuario)
        Evento.objects.create(solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.CREACION)
    existentes = {p.numero: p for p in solicitud.partidas.select_related("ampliacion")}
    for form in formset.renglones:
        numero = form.cleaned_data["numero"]
        partida = existentes.pop(numero, None)
        if partida is None:
            partida = Partida.objects.create(solicitud=solicitud, numero=numero, centro=form.cleaned_data["centro"])
        else:
            partida.centro = form.cleaned_data["centro"]
            partida.save(update_fields=["centro", "actualizada"])
        _guardar_detalle(partida, form)
    for sobrante in existentes.values():
        sobrante.delete()  # un borrador nunca entró al flujo: se vale borrar
    return solicitud


def ya_ampliado(material, centro):
    """True si el material ya existe en ese Centro (en el catálogo de materiales)."""
    return bool(material and centro) and MaterialCentro.objects.filter(material=material, centro=centro).exists()


@transaction.atomic
def enviar(usuario, formset, solicitud=None):
    """Primer envío (sección 10.3).

    Un renglón cuyo material YA existe en el Centro nuevo es innecesario: se quita con un aviso
    y no entra al flujo (no crea partida ni historia). Si no queda ninguno, la solicitud sigue
    en BORRADOR. Devuelve (solicitud, omitidas); solicitud.folio es None si no se envió.
    """
    omitidas = [f.cleaned_data for f in formset.renglones if ya_ampliado(f.material, f.cleaned_data["centro"])]
    numeros_omitidos = {d["numero"] for d in omitidas}
    formset_valido = [f for f in formset.renglones if f.cleaned_data["numero"] not in numeros_omitidos]

    class _Solo:  # el mismo formset, pero solo con los renglones que sí entran
        renglones = formset_valido

    solicitud = guardar_borrador(usuario, _Solo, solicitud)
    if not formset_valido:
        return solicitud, omitidas

    directo_a_dm = usuario.groups.filter(name="VAL_MAT").exists()
    estado_nuevo = E.EN_DM if directo_a_dm else E.EN_VALIDACION
    solicitud.folio = siguiente_folio(Flujo.AMPL_ZRA)
    solicitud.estado = Solicitud.Estado.EN_PROCESO
    solicitud.enviada = timezone.now()
    solicitud.save()
    for partida in solicitud.partidas.all():
        partida.estado = estado_nuevo
        partida.save(update_fields=["estado", "actualizada"])
        Evento.objects.create(
            solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.ENVIO,
            estado_anterior=E.BORRADOR, estado_nuevo=estado_nuevo,
        )
    return solicitud, omitidas


def faltantes(partida):
    """Lo que le falta a una partida AMPL ya guardada para aprobarse o reenviarse (lo usa flujo.aplicar)."""
    a = partida.ampliacion
    vacios = []
    valores = {"codigo_sap": a.codigo_sap, "centro": partida.centro_id, "almacen_destino": a.almacen_destino_id,
               "centro_origen": a.centro_origen_id, "almacen_modelo": a.almacen_modelo_id, "grupo_compras": a.grupo_compras_id}
    for campo in OBLIGATORIOS_ENVIO:
        if valores[campo] in (None, ""):
            vacios.append(NOMBRES[campo])
    if a.material_id is None and a.codigo_sap:
        vacios.append("un material que exista en el catálogo")
    if ya_ampliado(a.material, partida.centro):
        vacios.append(f"que el material no exista ya en {partida.centro.codigo} (ya está ampliado)")
    return vacios


CAMPOS_CORRECCION = ["codigo_sap", "almacen_destino", "centro_origen", "almacen_modelo", "planificador", "grupo_compras"]


@transaction.atomic
def guardar_correcciones(usuario, forms_, solicitud):
    """Como servicios.guardar_correcciones (AMAT): un Evento CAMBIO_CAMPO por cada campo que cambió."""
    from .servicios import partidas_editables

    permitidas = {p.pk: p for p in partidas_editables(usuario, solicitud).select_related("ampliacion").select_for_update(of=("self",))}
    cambios = 0
    for form in forms_:
        partida = permitidas.get(form.cleaned_data["pid"])
        if partida is None:
            raise PermissionError("Una de las partidas ya no está disponible para corregir. Recarga la página.")
        a = partida.ampliacion
        nuevos = completar(form.cleaned_data, form.material)
        for campo in ["centro", *CAMPOS_CORRECCION]:
            destino = partida if campo == "centro" else a
            actual, nuevo = getattr(destino, campo), nuevos.get(campo)
            if actual == nuevo or (actual in (None, "") and nuevo in (None, "")):
                continue
            Evento.objects.create(
                solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.CAMBIO_CAMPO,
                estado_anterior=partida.estado, estado_nuevo=partida.estado,
                detalle={"campo": NOMBRES.get(campo, campo), "antes": "" if actual is None else str(actual),
                         "despues": "" if nuevo is None else str(nuevo)},
            )
            setattr(destino, campo, nuevo)
            cambios += 1
        a.material = form.material
        partida.save()
        a.save()
    return cambios


# --- Datos Maestros: exportar, excluir y finalizar (sección 10.4) ----------------------------


def partidas_dm(usuario, solicitud):
    """Partidas AMPL de la solicitud que esperan a este DM (EN_DM y de sus Centros)."""
    return (
        solicitud.partidas.filter(estado=E.EN_DM, centro__in=usuario.centros.values("pk"))
        .select_related("centro", "ampliacion__material", "ampliacion__centro_origen", "ampliacion__almacen_destino",
                        "ampliacion__almacen_modelo", "ampliacion__planificador", "ampliacion__grupo_compras")
        .order_by("numero")
    )


def renglon_txt(partida):
    """Las 9 columnas del TXT, en el orden que pidió Dave."""
    a = partida.ampliacion
    codigo = lambda x: x.codigo if x else ""  # noqa: E731
    return [
        a.codigo_sap, a.codigo_sap, partida.centro.codigo, codigo(a.almacen_destino), codigo(a.centro_origen),
        codigo(a.almacen_modelo), codigo(a.planificador), codigo(a.grupo_compras), partida.centro.centro_beneficio,
    ]


def texto_txt(partidas):
    """Sin encabezados, separado por tabuladores, un renglón por partida. Exportar NO cambia estados:
    DM puede volver a exportar cuantas veces quiera antes de Finalizar."""
    return "".join("\t".join(renglon_txt(p)) + "\r\n" for p in partidas)


@transaction.atomic
def finalizar(usuario, solicitud):
    """Las partidas EN_DM (no excluidas) de los Centros de este DM pasan a TERMINADA y su Centro
    nuevo se agrega al material en el catálogo (pedido de Dave: es una nueva ubicación).

    Si mientras tanto alguien importó ese Material + Centro desde SAP, no se duplica: se termina igual.
    Devuelve cuántas partidas terminó.
    """
    from .flujo import AccionNoPermitida, _registrar, actualizar_cabecera, roles_de

    if "DM" not in roles_de(usuario):
        raise AccionNoPermitida("Necesitas el rol DM.")
    partidas = list(partidas_dm(usuario, solicitud).select_for_update(of=("self",)))
    if not partidas:
        raise AccionNoPermitida("No hay partidas en Datos Maestros para finalizar.")
    for p in partidas:
        a = p.ampliacion
        material = a.material or material_de(a.codigo_sap)
        if material is None:
            raise AccionNoPermitida(f"Partida {p.numero}: el material {a.codigo_sap} ya no está en el catálogo. Exclúyela.")
        modelo = MaterialCentro.objects.filter(material=material, centro=a.centro_origen).first()
        MaterialCentro.objects.get_or_create(material=material, centro=p.centro, defaults={
            "grupo_compras": a.grupo_compras.codigo if a.grupo_compras else "",
            # La categoría de valoración no se captura en AMPL: se copia del Centro modelo.
            "categoria_valoracion": modelo.categoria_valoracion if modelo else "",
            "almacen": a.almacen_destino.codigo if a.almacen_destino else "",
            "cebe": p.centro.centro_beneficio,
        })
        anterior = p.estado
        p.estado = E.TERMINADA
        p.save(update_fields=["estado", "actualizada"])
        _registrar(p, usuario, Evento.Tipo.TERMINACION, anterior)
    actualizar_cabecera(solicitud, usuario)
    return len(partidas)
