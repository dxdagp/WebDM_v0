"""ASER_ZSA: alta de servicios (fase 4e).

Lo que definió Dave (28-nov-2026):

    Captura:  Partida | Tipo de servicio | Descripción | UMB | Grupo de artículos | Estado
              Sin Centro (los servicios no tienen) y sin imágenes.
              El tipo de servicio (ZRA o ZSA) viene del catálogo de tipos de material, y de él depende la
              UMB que se propone: la predeterminada de ese tipo (ADMIN la define en Tipos de material).

    Reglas, iguales que las del alta de materiales: descripción en MAYÚSCULAS y sin acentos (la Ñ se
    queda), máximo 40; UMB y grupo de artículos contra sus catálogos; duplicados contra el catálogo
    de SERVICIOS (la misma descripción bloquea, una parecida solo avisa).

    DM: escribe el Código SAP en su bandeja (como en las altas de materiales) y puede exportar
    Alta_Ser.txt con Código SAP, Descripción, UMB y Grupo de artículos. Al terminar, el servicio
    entra al catálogo de servicios.
"""

from django import forms
from django.db import transaction
from django.utils import timezone

from catalogo_sap.models import MaterialSAP
from catalogos.models import GrupoArticulos, TipoMaterial, UMB  # noqa: F401

from . import duplicados
from .folios import siguiente_folio
from .forms import LIMITE, CampoTextoSAP, Catalogo
from .models import DetalleServicio, Evento, Flujo, Partida, Solicitud
from .rapido import FormsetCompartido, compartir_catalogos

E = Partida.Estado
TIPO_PROPUESTO = "ZSA"  # el tipo con el que nacen los renglones nuevos; se puede cambiar por ZRA
NOMBRE_TXT = "Alta_Ser.txt"
CAMPOS = ["tipo_material", "descripcion", "umb", "grupo_articulos"]
NOMBRES = {"tipo_material": "Tipo de servicio", "descripcion": "Descripción", "umb": "UMB", "grupo_articulos": "Grupo de artículos"}


def umb_de(tipo):
    """La UMB predeterminada de un tipo de servicio, o None si ADMIN no la definió (o está inactiva)."""
    umb = getattr(tipo, "umb_predeterminada", None)
    return umb if umb is not None and umb.activo else None


def umbs_por_tipo():
    """{id de tipo: id de UMB predeterminada}: lo que usa la pantalla para proponer al cambiar el tipo."""
    return {str(t.pk): str(t.umb_predeterminada_id) for t in TipoMaterial.objects.filter(activo=True, umb_predeterminada__activo=True)}


def tipo_propuesto():
    return TipoMaterial.objects.filter(codigo=TIPO_PROPUESTO, activo=True).select_related("umb_predeterminada").first()


class ServicioForm(forms.Form):
    numero = forms.IntegerField(min_value=1, required=False, label="Partida")
    tipo_material = Catalogo(TipoMaterial.objects.select_related("umb_predeterminada"), label="Tipo de servicio")
    descripcion = CampoTextoSAP(label="Descripción")
    umb = Catalogo(UMB.objects.all(), label="UMB")
    grupo_articulos = Catalogo(GrupoArticulos.objects.all(), label="Grupo de artículos")

    def __init__(self, *args, compartido=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.compartido = compartido
        if compartido is not None:
            compartir_catalogos(self, compartido)

    @property
    def vacio(self):
        datos = getattr(self, "cleaned_data", {})
        # Tipo y UMB solos no cuentan: los renglones nuevos ya los traen propuestos.
        return all(datos.get(c) in (None, "") for c in ("descripcion", "grupo_articulos"))

    def clean(self):
        datos = super().clean()
        if not self.vacio and not datos.get("numero"):
            self.add_error("numero", "Falta el número de partida.")
        return datos

    def faltantes(self):
        """Obligatorios vacíos. La UMB vacía no falta si su tipo tiene predeterminada: se guarda esa."""
        vacios = [c for c in CAMPOS if self.cleaned_data.get(c) in (None, "")]
        if "umb" in vacios and umb_de(self.cleaned_data.get("tipo_material")) is not None:
            vacios.remove("umb")
        return vacios


class BaseServicioFormSet(FormsetCompartido, forms.BaseFormSet):
    default_error_messages = {
        **forms.BaseFormSet.default_error_messages,
        "too_many_forms": "Máximo %(num)d partidas por solicitud. Divide la captura en varias solicitudes.",
    }

    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid() and not f.vacio]

    def clean(self):
        """Entre renglones: no se repite el número de partida ni la descripción."""
        if any(self.errors):
            return
        numeros, descripciones = set(), {}
        for form in self.renglones:
            d = form.cleaned_data
            if d.get("numero") in numeros:
                form.add_error("numero", "Número de partida repetido.")
            numeros.add(d.get("numero"))
            descripcion = d.get("descripcion")
            if descripcion:
                if descripcion in descripciones:
                    # add_error quita el campo de cleaned_data: por eso se guardó antes en `descripcion`.
                    form.add_error("descripcion", f"Descripción repetida (partida {descripciones[descripcion]}).")
                descripciones.setdefault(descripcion, d.get("numero"))

    def validar_para_envio(self):
        """Obligatorios y duplicados contra el catálogo de servicios. Devuelve (listo, avisos)."""
        if not self.is_valid():
            return False, []
        if not self.renglones:
            self._non_form_errors = self.error_class(["Agrega al menos una partida antes de enviar."])
            return False, []
        listo, avisos = True, []
        for form in self.renglones:
            for campo in form.faltantes():
                form.add_error(campo, "Obligatorio para enviar.")
                listo = False
            descripcion = form.cleaned_data.get("descripcion")
            for c in duplicados.buscar(descripcion, servicio=True) if descripcion else []:
                if c.bloquea:
                    form.add_error("descripcion", f"Ya existe el servicio {c.codigo} con esta descripción.")
                    listo = False
                    break
                avisos.append(f"Partida {form.cleaned_data['numero']}: se parece al servicio {c.codigo} · {c.descripcion} ({c.parecido} %).")
                break  # un aviso por partida basta
        return listo, avisos


ServicioFormSet = forms.formset_factory(ServicioForm, formset=BaseServicioFormSet, extra=0, can_delete=False, **LIMITE)


class ServicioCorreccionForm(ServicioForm):
    pid = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["numero"].disabled = True


class BaseServicioCorreccionFormSet(BaseServicioFormSet):
    @property
    def renglones(self):
        return [f for f in self.forms if f.is_valid()]


ServicioCorreccionFormSet = forms.formset_factory(
    ServicioCorreccionForm, formset=BaseServicioCorreccionFormSet, extra=0, can_delete=False, **LIMITE
)


# --- Guardar y enviar ------------------------------------------------------------------------


def filas_iniciales(solicitud):
    return [
        {"numero": p.numero, "tipo_material": p.servicio.tipo_material_id, "descripcion": p.servicio.descripcion,
         "umb": p.servicio.umb_id, "grupo_articulos": p.servicio.grupo_articulos_id}
        for p in solicitud.partidas.select_related("servicio").order_by("numero")
    ]


def filas_nuevas(cuantas=5):
    """Renglones vacíos (10 a 50) con el tipo ZSA y su UMB ya propuestos."""
    tipo = tipo_propuesto()
    umb = umb_de(tipo)
    return [{"numero": n, "tipo_material": tipo.pk if tipo else None, "umb": umb.pk if umb else None}
            for n in range(10, 10 * cuantas + 10, 10)]


def _guardar_detalle(partida, datos):
    detalle = getattr(partida, "servicio", None) or DetalleServicio(partida=partida)
    detalle.tipo_material = datos.get("tipo_material")
    detalle.descripcion = datos.get("descripcion") or ""
    detalle.umb = datos.get("umb") or umb_de(detalle.tipo_material)  # vacía = la predeterminada de su tipo
    detalle.grupo_articulos = datos.get("grupo_articulos")
    detalle.save()


@transaction.atomic
def guardar_borrador(usuario, formset, solicitud=None):
    if solicitud is None:
        solicitud = Solicitud.objects.create(flujo=Flujo.ASER_ZSA, solicitante=usuario)
        Evento.objects.create(solicitud=solicitud, usuario=usuario, tipo=Evento.Tipo.CREACION)
    existentes = {p.numero: p for p in solicitud.partidas.select_related("servicio")}
    for form in formset.renglones:
        numero = form.cleaned_data["numero"]
        partida = existentes.pop(numero, None) or Partida.objects.create(solicitud=solicitud, numero=numero)
        _guardar_detalle(partida, form.cleaned_data)
    for sobrante in existentes.values():
        sobrante.delete()
    return solicitud


@transaction.atomic
def enviar(usuario, formset, solicitud):
    solicitud = guardar_borrador(usuario, formset, solicitud)
    directo_a_dm = usuario.groups.filter(name="VAL_MAT").exists()
    estado_nuevo = E.EN_DM if directo_a_dm else E.EN_VALIDACION
    solicitud.folio = siguiente_folio(Flujo.ASER_ZSA)
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
    """Para Aprobar y Reenviar (flujo.aplicar). Los duplicados los revisa flujo.duplicado_de()."""
    d = partida.servicio
    valores = {"tipo_material": d.tipo_material_id, "descripcion": d.descripcion, "umb": d.umb_id, "grupo_articulos": d.grupo_articulos_id}
    return [NOMBRES[c] for c in CAMPOS if valores[c] in (None, "")]


@transaction.atomic
def guardar_correcciones(usuario, forms_, solicitud):
    from .servicios import partidas_editables

    permitidas = {p.pk: p for p in partidas_editables(usuario, solicitud).select_related("servicio").select_for_update(of=("self",))}
    cambios = 0
    for form in forms_:
        partida = permitidas.get(form.cleaned_data["pid"])
        if partida is None:
            raise PermissionError("Una de las partidas ya no está disponible para corregir. Recarga la página.")
        d = partida.servicio
        for campo in CAMPOS:
            actual = getattr(d, campo)
            nuevo = form.cleaned_data.get(campo) or (umb_de(form.cleaned_data.get("tipo_material")) if campo == "umb" else None)
            if actual == nuevo or (actual in (None, "") and nuevo in (None, "")):
                continue
            Evento.objects.create(
                solicitud=solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.CAMBIO_CAMPO,
                estado_anterior=partida.estado, estado_nuevo=partida.estado,
                detalle={"campo": NOMBRES[campo], "antes": "" if actual is None else str(actual),
                         "despues": "" if nuevo is None else str(nuevo)},
            )
            cambios += 1
        _guardar_detalle(partida, form.cleaned_data)
    return cambios


# --- Datos Maestros ---------------------------------------------------------------------------


def texto_txt(partidas, codigos):
    """Alta_Ser.txt: con cabecera, separado por tabuladores. `codigos` = lo que DM escribió en su
    bandeja ({id de partida: código}); puede ir vacío si aún no lo tiene. Exportar no cambia nada."""
    lineas = [["Código SAP", "Descripción", "UMB", "Grupo de artículos"]]
    for p in partidas:
        d = p.servicio
        lineas.append([
            (codigos.get(str(p.pk)) or d.codigo_sap or "").strip(), d.descripcion,
            d.umb.codigo if d.umb else "", d.grupo_articulos.codigo if d.grupo_articulos else "",
        ])
    return "".join("\t".join(linea) + "\r\n" for linea in lineas)


def error_codigo(codigo):
    """Código SAP para un servicio nuevo: 6 dígitos y que no exista en el catálogo de SERVICIOS."""
    if not (len(codigo) == 6 and codigo.isdigit()):
        return "Debe tener exactamente 6 dígitos."
    if MaterialSAP.objects.filter(codigo=codigo, es_servicio=True).exists() or DetalleServicio.objects.filter(codigo_sap=codigo).exists():
        return "Este Código SAP ya existe en servicios."
    return None


def terminar(usuario, partida, codigo):
    """Guarda el código y da de alta el servicio en el catálogo. La partida ya viene bloqueada."""
    d = partida.servicio
    d.codigo_sap = codigo
    d.save(update_fields=["codigo_sap"])
    MaterialSAP.objects.create(
        codigo=codigo, descripcion=d.descripcion, tipo_material=d.tipo_material.codigo if d.tipo_material else "", umb=d.umb.codigo if d.umb else "",
        grupo_articulos=d.grupo_articulos.codigo if d.grupo_articulos else "", es_servicio=True,
        origen=MaterialSAP.Origen.WEBDM, folio_origen=partida.solicitud.folio or "", partida_origen=partida,
        creado_por=usuario,
    )
