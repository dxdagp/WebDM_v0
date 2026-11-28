"""MOD_ZRA y MOD_ZSA: modificación de un material o un servicio que ya existe (fase 4d).

Lo que definió Dave (28-nov-2026):

    Captura:  un renglón por Material + Dato:
              Partida | Descripción (auto) | Material | Centro | Dato | Valor actual (auto) | Valor nuevo | Estado
              Si pegan desde Excel un material con varias columnas de datos, se separa en un renglón por dato.

    Datos generales (sin Centro): descripción, grupo de artículos, ubicación, No. Parte Original,
              tipo de unidad, marca, versión, año modelo y compatibilidad.
    Datos por Centro (piden Centro): grupo de compras, almacén y CeBe.
    Servicios (MOD_ZSA): solo descripción y grupo de artículos, sin Centro.

    TXT para SAP: con cabecera y solo los valores nuevos. Un renglón por material (y Centro, si el
              dato es por Centro); las columnas de lo que no cambia van vacías.

Flujo igual que AMAT y AMPL: SOL_MAT → VAL_MAT → DM (o VAL_MAT → DM si la crea un validador).
DM exporta el TXT las veces que quiera, excluye con motivo y, al Finalizar, el valor nuevo
se escribe en el catálogo de WebDM.
"""

from django import forms
from django.db import transaction
from django.utils import timezone

from catalogo_sap.models import MaterialCentro, MaterialSAP
from catalogos.models import Almacen, Centro, GrupoArticulos, GrupoCompras, UbicacionRefaccion

from .folios import siguiente_folio
from .forms import LIMITE
from .models import DetalleModificacion, Evento, Flujo, Partida, Solicitud
from .normalizar import texto_sap

E = Partida.Estado
C = DetalleModificacion.Campo
POR_CENTRO = DetalleModificacion.CAMPOS_POR_CENTRO
FLUJOS = (Flujo.MOD_ZRA, Flujo.MOD_ZSA)

# Dónde vive cada dato en el catálogo de WebDM: en el material (MaterialSAP) o en el material
# por Centro (MaterialCentro). Es lo que se lee como "valor actual" y lo que se escribe al Finalizar.
ATRIBUTO = {
    C.DESCRIPCION: "descripcion", C.GRUPO_ARTICULOS: "grupo_articulos", C.UBICACION: "ubicacion",
    C.NO_PARTE: "no_parte_original", C.TIPO_UNIDAD: "tipo_unidad", C.MARCA: "marca", C.VERSION: "version",
    C.ANIO_MODELO: "anio_modelo", C.COMPATIBILIDAD: "compatibilidad",
    C.GRUPO_COMPRAS: "grupo_compras", C.ALMACEN: "almacen", C.CEBE: "cebe",
}
# Orden de la lista "Dato", del pegado desde Excel y de las columnas del TXT.
ORDEN = [C.DESCRIPCION, C.GRUPO_ARTICULOS, C.UBICACION, C.NO_PARTE, C.TIPO_UNIDAD, C.MARCA, C.VERSION,
         C.ANIO_MODELO, C.COMPATIBILIDAD, C.GRUPO_COMPRAS, C.ALMACEN, C.CEBE]
NOMBRE_TXT = {Flujo.MOD_ZRA: "Mod_Mat.txt", Flujo.MOD_ZSA: "Mod_Ser.txt"}
OBLIGATORIOS_ENVIO = ["codigo_sap", "campo", "valor_nuevo"]
NOMBRES = {"codigo_sap": "Material", "centro": "Centro", "campo": "Dato", "valor_nuevo": "Valor nuevo"}


def campos_de(flujo):
    """Los datos que se pueden modificar en cada flujo, en el orden de la lista."""
    if flujo == Flujo.MOD_ZSA:
        return [c for c in ORDEN if c in DetalleModificacion.CAMPOS_SERVICIO]
    return list(ORDEN)


def es_servicio(flujo):
    return flujo == Flujo.MOD_ZSA


def nombre_catalogo(flujo):
    return "servicios" if es_servicio(flujo) else "materiales"


# --- Lo que se consulta UNA vez por tabla (no una vez por renglón) --------------------------


def precargar(codigos, flujo):
    """Materiales de todos los códigos de la tabla, sus renglones por Centro y los catálogos.

    Son 6 consultas en total, sin importar si la tabla tiene 5 o 2,000 renglones.
    """
    codigos = {x for x in codigos if x}
    materiales = {m.codigo: m for m in MaterialSAP.objects.filter(codigo__in=codigos, es_servicio=es_servicio(flujo))}
    por_centro = {(mc.material_id, mc.centro_id): mc for mc in MaterialCentro.objects.filter(material__in=materiales.values())}
    por_centro_de = lambda modelo: {(x.centro_id, x.codigo) for x in modelo.objects.filter(activo=True)}  # noqa: E731
    return {
        "materiales": materiales,
        "material_centro": por_centro,
        C.GRUPO_ARTICULOS: {x.codigo for x in GrupoArticulos.objects.filter(activo=True)},
        C.UBICACION: {x.codigo for x in UbicacionRefaccion.objects.filter(activo=True)},
        C.GRUPO_COMPRAS: por_centro_de(GrupoCompras),
        C.ALMACEN: por_centro_de(Almacen),
    }


def material_de(codigo, flujo, c=None):
    if not codigo:
        return None
    if c is not None:
        return c["materiales"].get(codigo)
    return MaterialSAP.objects.filter(codigo=codigo, es_servicio=es_servicio(flujo)).first()


def material_centro(material, centro, c=None):
    if not (material and centro):
        return None
    if c is not None:
        return c["material_centro"].get((material.pk, centro.pk))
    return MaterialCentro.objects.filter(material=material, centro=centro).first()


def valor_actual(material, campo, mc=None):
    """El valor que hoy tiene el catálogo, como texto ("" si está vacío)."""
    if not material or not campo:
        return ""
    origen = mc if campo in POR_CENTRO else material
    if origen is None:
        return ""
    valor = getattr(origen, ATRIBUTO[campo])
    return "" if valor is None else str(valor)


def normalizar(campo, texto, centro, c):
    """Valida y normaliza el valor nuevo según el dato. Devuelve (valor, error)."""
    texto = (texto or "").strip()
    if not texto or not campo:
        return texto, None
    if campo == C.ANIO_MODELO:
        if not (len(texto) == 4 and texto.isdigit() and 1900 <= int(texto) <= 2100):
            return texto, "El año debe tener 4 dígitos (1900 a 2100)."
        return texto, None
    if campo in (C.GRUPO_ARTICULOS, C.UBICACION):
        valor = texto.upper()
        if valor not in c[campo]:
            return valor, f"No existe en el catálogo de {C(campo).label.lower()}."
        return valor, None
    if campo in (C.GRUPO_COMPRAS, C.ALMACEN):
        valor = texto.upper()
        if centro and (centro.pk, valor) not in c[campo]:
            return valor, f"No es un {C(campo).label.lower()} de {centro.codigo}."
        return valor, None
    if campo == C.CEBE:
        valor = texto.upper()
        return valor, ("Máximo 20 caracteres." if len(valor) > 20 else None)
    valor = texto_sap(texto)  # mayúsculas y sin acentos, como en el alta (la Ñ se queda)
    return valor, ("Máximo 40 caracteres." if len(valor) > 40 else None)


# --- Formulario: un renglón de la tabla ----------------------------------------------------


class ModificacionForm(forms.Form):
    numero = forms.IntegerField(min_value=1, required=False, label="Partida")
    codigo_sap = forms.CharField(max_length=6, required=False, label="Material")
    centro = forms.ModelChoiceField(queryset=Centro.objects.none(), required=False, empty_label="", label="Centro")
    campo = forms.ChoiceField(required=False, label="Dato")
    valor_nuevo = forms.CharField(max_length=60, required=False, label="Valor nuevo")

    def __init__(self, *args, centros=None, compartido=None, flujo=Flujo.MOD_ZRA, **kwargs):
        super().__init__(*args, **kwargs)
        self.flujo = flujo
        self.fields["centro"].queryset = centros if centros is not None else Centro.objects.none()
        self.fields["campo"].choices = [("", "")] + [(x.value, x.label) for x in campos_de(flujo)]
        self.fields["codigo_sap"].label = "Servicio" if es_servicio(flujo) else "Material"
        if es_servicio(flujo):
            del self.fields["centro"]  # los servicios no tienen Centro
        self.compartido = compartido
        self.material = None
        self.mc = None
        self.valor_actual = ""

    @property
    def vacio(self):
        datos = getattr(self, "cleaned_data", {})
        return all(datos.get(c) in (None, "") for c in ("codigo_sap", "centro", "campo", "valor_nuevo"))

    def clean_codigo_sap(self):
        codigo = self.cleaned_data["codigo_sap"].strip()
        if codigo and not (len(codigo) == 6 and codigo.isdigit()):
            raise forms.ValidationError("Debe tener 6 dígitos.")
        return codigo

    def clean(self):
        datos = super().clean()
        c = self.compartido if self.compartido is not None else precargar([datos.get("codigo_sap")], self.flujo)
        if not self.vacio and not datos.get("numero"):
            self.add_error("numero", "Falta el número de partida.")
        codigo, campo, centro = datos.get("codigo_sap"), datos.get("campo"), datos.get("centro")
        if codigo:
            self.material = material_de(codigo, self.flujo, c)
            if self.material is None:
                self.add_error("codigo_sap", f"No existe en el catálogo de {nombre_catalogo(self.flujo)}.")
        if campo and campo not in POR_CENTRO:
            datos["centro"] = centro = None  # dato general: el Centro no aplica
        if campo in POR_CENTRO and centro and self.material:
            self.mc = material_centro(self.material, centro, c)
            if self.mc is None:
                self.add_error("centro", f"El material no existe en {centro.codigo}.")
        valor, error = normalizar(campo, datos.get("valor_nuevo"), centro, c)
        datos["valor_nuevo"] = valor
        if error:
            self.add_error("valor_nuevo", error)
        self.valor_actual = valor_actual(self.material, campo, self.mc)
        if valor and not error and self.material and valor == self.valor_actual:
            self.add_error("valor_nuevo", "Es igual al valor actual.")
        return datos

    def faltantes(self):
        datos = self.cleaned_data
        vacios = [c for c in OBLIGATORIOS_ENVIO if datos.get(c) in (None, "")]
        if datos.get("campo") in POR_CENTRO and not datos.get("centro"):
            vacios.append("centro")
        return vacios


class BaseModificacionFormSet(forms.BaseFormSet):
    default_error_messages = {
        **forms.BaseFormSet.default_error_messages,
        "too_many_forms": "Máximo %(num)d partidas por solicitud. Divide la captura en varias solicitudes.",
    }

    def __init__(self, *args, centros=None, flujo=Flujo.MOD_ZRA, solicitud=None, **kwargs):
        self.centros, self.flujo, self.solicitud = centros, flujo, solicitud
        super().__init__(*args, **kwargs)

    @property
    def compartido(self):
        if not hasattr(self, "_compartido"):
            if self.is_bound:
                codigos = [v.strip() for k, v in self.data.items() if k.endswith("-codigo_sap")]
            else:
                codigos = [f.get("codigo_sap") for f in (self.initial or [])]
            self._compartido = precargar(codigos, self.flujo)
        return self._compartido

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "centros": self.centros, "flujo": self.flujo, "compartido": self.compartido}

    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid() and not f.vacio]

    def clean(self):
        """Entre renglones: no se repite el número de partida ni Material + Centro + Dato."""
        if any(self.errors):
            return
        numeros, vistos = set(), {}
        for form in self.renglones:
            d = form.cleaned_data
            if d.get("numero") in numeros:
                form.add_error("numero", "Número de partida repetido.")
            numeros.add(d.get("numero"))
            llave = (d.get("codigo_sap"), d.get("centro"), d.get("campo"))
            if llave[0] and llave[2]:
                if llave in vistos:
                    form.add_error("campo", f"Este dato ya está en la partida {vistos[llave]}.")
                vistos.setdefault(llave, d.get("numero"))

    def validar_para_envio(self):
        if not self.is_valid():
            return False
        if not self.renglones:
            self._non_form_errors = self.error_class(["Agrega al menos una partida antes de enviar."])
            return False
        ok = True
        for form in self.renglones:
            for campo in form.faltantes():
                form.add_error(campo, "Obligatorio para enviar.")
                ok = False
        if ok:
            # El mismo dato del mismo material no puede estar en dos solicitudes abiertas a la vez.
            abiertas = en_otras_solicitudes([f.cleaned_data for f in self.renglones], self.flujo, self.solicitud)
            for form in self.renglones:
                d = form.cleaned_data
                folio = abiertas.get((d["codigo_sap"], getattr(d.get("centro"), "pk", None), d["campo"]))
                if folio:
                    form.add_error("campo", f"Este dato ya se está modificando en {folio}.")
                    ok = False
        return ok


ModificacionFormSet = forms.formset_factory(ModificacionForm, formset=BaseModificacionFormSet, extra=0, can_delete=False, **LIMITE)


class ModificacionCorreccionForm(ModificacionForm):
    """Corrección de partidas devueltas o en validación: lleva el id de su partida y no se renumera."""

    pid = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero"].disabled = True


class BaseModificacionCorreccionFormSet(BaseModificacionFormSet):
    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid()]


ModificacionCorreccionFormSet = forms.formset_factory(
    ModificacionCorreccionForm, formset=BaseModificacionCorreccionFormSet, extra=0, can_delete=False, **LIMITE
)


def en_otras_solicitudes(renglones, flujo, solicitud=None):
    """{(código, centro_id, dato): folio} de lo que ya se está modificando en otra solicitud enviada y abierta."""
    codigos = {d["codigo_sap"] for d in renglones}
    qs = (DetalleModificacion.objects.filter(partida__solicitud__flujo=flujo, codigo_sap__in=codigos,
                                             partida__estado__in=[E.EN_VALIDACION, E.DEVUELTA_SOL, E.EN_DM])
          .select_related("partida__solicitud"))
    if solicitud is not None:
        qs = qs.exclude(partida__solicitud=solicitud)
    return {(d.codigo_sap, d.partida.centro_id, d.campo): d.partida.solicitud.folio for d in qs}


# --- Guardar y enviar ------------------------------------------------------------------------


def filas_iniciales(solicitud):
    return [
        {"numero": p.numero, "codigo_sap": p.modificacion.codigo_sap, "centro": p.centro_id,
         "campo": p.modificacion.campo, "valor_nuevo": p.modificacion.valor_nuevo}
        for p in solicitud.partidas.select_related("modificacion").order_by("numero")
    ]


def _guardar_detalle(partida, form):
    d = form.cleaned_data
    detalle = getattr(partida, "modificacion", None) or DetalleModificacion(partida=partida)
    detalle.codigo_sap = d["codigo_sap"]
    detalle.material = form.material
    detalle.campo = d.get("campo") or ""
    detalle.valor_actual = form.valor_actual
    detalle.valor_nuevo = d.get("valor_nuevo") or ""
    detalle.save()


@transaction.atomic
def guardar_borrador(usuario, formset, solicitud=None):
    """Crea o actualiza el borrador: las partidas quedan igual que la tabla (por número de partida)."""
    if solicitud is None:
        solicitud = Solicitud.objects.create(flujo=formset.flujo, solicitante=usuario)
        Evento.objects.create(solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.CREACION)
    existentes = {p.numero: p for p in solicitud.partidas.select_related("modificacion")}
    for form in formset.renglones:
        numero, centro = form.cleaned_data["numero"], form.cleaned_data.get("centro")
        partida = existentes.pop(numero, None)
        if partida is None:
            partida = Partida.objects.create(solicitud=solicitud, numero=numero, centro=centro)
        elif partida.centro_id != getattr(centro, "pk", None):
            partida.centro = centro
            partida.save(update_fields=["centro", "actualizada"])
        _guardar_detalle(partida, form)
    for sobrante in existentes.values():
        sobrante.delete()  # un borrador nunca entró al flujo: se vale borrar
    return solicitud


@transaction.atomic
def enviar(usuario, formset, solicitud):
    """Primer envío. Se llama solo si validar_para_envio() pasó."""
    solicitud = guardar_borrador(usuario, formset, solicitud)
    directo_a_dm = usuario.groups.filter(name="VAL_MAT").exists()
    estado_nuevo = E.EN_DM if directo_a_dm else E.EN_VALIDACION
    solicitud.folio = siguiente_folio(solicitud.flujo)
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
    return solicitud


def faltantes(partida):
    """Lo que le falta a una partida MOD ya guardada para aprobarse o reenviarse (lo usa flujo.aplicar)."""
    d = partida.modificacion
    vacios = [NOMBRES[c] for c, v in [("codigo_sap", d.codigo_sap), ("campo", d.campo), ("valor_nuevo", d.valor_nuevo)] if not v]
    if d.campo in POR_CENTRO and not partida.centro_id:
        vacios.append("Centro")
    if d.material_id is None and d.codigo_sap:
        vacios.append(f"un código que exista en el catálogo de {nombre_catalogo(partida.solicitud.flujo)}")
    elif d.material_id and d.campo and d.valor_nuevo:
        mc = material_centro(d.material, partida.centro) if d.campo in POR_CENTRO else None
        if d.valor_nuevo == valor_actual(d.material, d.campo, mc):
            vacios.append("un valor nuevo distinto al que ya tiene el catálogo")
    return vacios


@transaction.atomic
def guardar_correcciones(usuario, forms_, solicitud):
    """Como en AMAT: un Evento CAMBIO_CAMPO por cada dato que cambió."""
    from .servicios import partidas_editables

    permitidas = {p.pk: p for p in partidas_editables(usuario, solicitud).select_related("modificacion").select_for_update(of=("self",))}
    cambios = 0
    for form in forms_:
        partida = permitidas.get(form.cleaned_data["pid"])
        if partida is None:
            raise PermissionError("Una de las partidas ya no está disponible para corregir. Recarga la página.")
        d, nuevos = partida.modificacion, form.cleaned_data
        for campo, actual, nuevo in [
            ("codigo_sap", d.codigo_sap, nuevos["codigo_sap"]),
            ("centro", partida.centro, nuevos.get("centro")),
            ("campo", d.campo, nuevos.get("campo") or ""),
            ("valor_nuevo", d.valor_nuevo, nuevos.get("valor_nuevo") or ""),
        ]:
            if actual == nuevo or (actual in (None, "") and nuevo in (None, "")):
                continue
            Evento.objects.create(
                solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.CAMBIO_CAMPO,
                estado_anterior=partida.estado, estado_nuevo=partida.estado,
                detalle={"campo": NOMBRES[campo], "antes": "" if actual is None else str(actual),
                         "despues": "" if nuevo is None else str(nuevo)},
            )
            cambios += 1
        partida.centro = nuevos.get("centro")
        partida.save()
        _guardar_detalle(partida, form)
    return cambios


# --- Datos Maestros: exportar y finalizar -----------------------------------------------------


def columnas_txt(flujo):
    """Cabecera del TXT: Material (y Centro en materiales) y una columna por dato."""
    if es_servicio(flujo):
        return ["Servicio"] + [x.label for x in campos_de(flujo)]
    return ["Material", "Centro"] + [x.label for x in campos_de(flujo)]


def texto_txt(partidas, flujo):
    """Con cabecera, separado por tabuladores. Un renglón por material (y Centro, en los datos por
    Centro) y solo los valores nuevos: lo que no cambia va vacío. Exportar NO cambia estados."""
    datos = campos_de(flujo)
    renglones = {}  # (código, centro) -> {dato: valor nuevo}; dict conserva el orden de llegada
    for p in partidas:
        d = p.modificacion
        llave = (d.codigo_sap, p.centro.codigo if p.centro else "")
        renglones.setdefault(llave, {})[d.campo] = d.valor_nuevo
    lineas = [columnas_txt(flujo)]
    for (codigo, centro), valores in renglones.items():
        inicio = [codigo] if es_servicio(flujo) else [codigo, centro]
        lineas.append(inicio + [valores.get(x, "") for x in datos])
    return "".join("\t".join(linea) + "\r\n" for linea in lineas)


def finalizar_partidas(usuario, partidas):
    """Escribe el valor nuevo en el catálogo de WebDM y pasa cada partida a TERMINADA.

    Las partidas ya vienen bloqueadas (SELECT … FOR UPDATE) por quien llama.
    """
    from .flujo import AccionNoPermitida, _registrar

    for p in partidas:
        d = p.modificacion
        if d.material is None:
            raise AccionNoPermitida(f"{p.solicitud.folio}/{p.numero}: el código {d.codigo_sap} ya no está en el catálogo. Exclúyela.")
        if d.campo in POR_CENTRO:
            destino = MaterialCentro.objects.filter(material=d.material, centro=p.centro).first()
            if destino is None:
                raise AccionNoPermitida(f"{p.solicitud.folio}/{p.numero}: el material ya no existe en {p.centro.codigo}. Exclúyela.")
        else:
            destino = d.material
        atributo = ATRIBUTO[d.campo]
        antes = getattr(destino, atributo)
        setattr(destino, atributo, int(d.valor_nuevo) if d.campo == C.ANIO_MODELO else d.valor_nuevo)
        destino.save(update_fields=[atributo])
        anterior = p.estado
        p.estado = E.TERMINADA
        p.save(update_fields=["estado", "actualizada"])
        _registrar(p, usuario, Evento.Tipo.TERMINACION, anterior, detalle={
            "campo": C(d.campo).label, "antes": "" if antes is None else str(antes), "despues": d.valor_nuevo,
        })
