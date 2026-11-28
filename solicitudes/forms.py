"""Formularios de captura de AMAT_ZRA.

Cada renglón de la tabla tipo Excel es un `PartidaAltaForm`. Todos los
renglones juntos forman un *formset* (un conjunto de formularios iguales).

Dos niveles de validación (Revisión 3, sección 6):
- Guardar borrador: PERMISIVO con lo que falta, pero nunca guarda valores
  inválidos (un año "20A4", un texto de 41 caracteres, un grupo de compras
  de otro Centro). Eso lo hacen los campos y `clean()` de cada formulario.
- Enviar: ESTRICTO. Además exige todos los campos obligatorios. Eso lo hace
  `validar_para_envio()` en el formset.
"""

from django import forms
from django.conf import settings

from catalogos.models import Almacen, CategoriaValoracion, Centro, GrupoArticulos, GrupoCompras, UbicacionRefaccion, UMB

from .normalizar import texto_sap
from .rapido import FormsetCompartido, compartir_catalogos


class CampoTextoSAP(forms.CharField):
    """Texto de hasta 40 caracteres que se guarda en MAYÚSCULAS y sin acentos."""

    def __init__(self, **kwargs):
        super().__init__(max_length=40, required=False, **kwargs)

    def to_python(self, value):
        # to_python corre ANTES de validar la longitud: así "Óptimo" cuenta ya normalizado.
        return texto_sap(super().to_python(value))


class Catalogo(forms.ModelChoiceField):
    """Lista desplegable de un catálogo, solo con valores activos, opcional en borrador."""

    def __init__(self, queryset, **kwargs):
        # empty_label="": la opción vacía se ve como celda en blanco (como Excel), no "---------".
        super().__init__(queryset=queryset.filter(activo=True), required=False, empty_label="", **kwargs)


# Orden de columnas definido por Dave (28-nov-2026), que reemplaza al de la Revisión 3 (7.2).
# Es también el orden del pegado desde Excel (static/js/captura.js, COLUMNAS).
# Tipo de Material y CeBe son automáticos: no se capturan ni se pegan.
CAMPOS_OBLIGATORIOS_ENVIO = [
    "centro", "descripcion", "umb", "grupo_compras", "grupo_articulos", "categoria_valoracion",
    "ubicacion", "no_parte_original", "tipo_unidad", "marca", "version", "anio_modelo",
]


class PartidaAltaForm(forms.Form):
    # El orden de declaración es el orden en que se dibujan los campos en la ficha.
    numero = forms.IntegerField(min_value=1, required=False, label="Partida")
    centro = forms.ModelChoiceField(queryset=Centro.objects.none(), required=False, label="Centro", empty_label="")
    descripcion = CampoTextoSAP(label="Descripción técnica del material")
    umb = Catalogo(UMB.objects.all(), label="Unidad de medida base")
    grupo_compras = Catalogo(GrupoCompras.objects.select_related("centro"), label="Grupo de compras")
    grupo_articulos = Catalogo(GrupoArticulos.objects.all(), label="Grupo de artículos")
    categoria_valoracion = Catalogo(CategoriaValoracion.objects.all(), label="Categoría de valoración")
    ubicacion = Catalogo(UbicacionRefaccion.objects.all(), label="Ubicación de la refacción")
    no_parte_original = CampoTextoSAP(label="No. Parte Original")
    tipo_unidad = CampoTextoSAP(label="Tipo de Unidad")
    marca = CampoTextoSAP(label="Marca de la unidad")
    version = CampoTextoSAP(label="Versión de la Unidad")
    anio_modelo = forms.IntegerField(
        required=False, min_value=1900, max_value=2100, label="Año modelo",
        error_messages={"invalid": "Debe tener 4 dígitos.", "min_value": "Año no válido.", "max_value": "Año no válido."},
    )
    compatibilidad = CampoTextoSAP(label="Compatibilidad entre unidades")
    # Editable desde el 28-nov-2026 (pedido de Dave). Si se deja vacío, el servidor pone
    # el almacén predeterminado del Centro.
    almacen = Catalogo(Almacen.objects.select_related("centro"), label="Almacén")

    def __init__(self, *args, centros=None, compartido=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Un usuario solo puede capturar en sus Centros autorizados (Revisión 3, sección 5).
        self.fields["centro"].queryset = centros if centros is not None else Centro.objects.none()
        self.compartido = compartido
        if compartido is not None:  # en una tabla: los catálogos se consultan una vez para todos los renglones
            compartir_catalogos(self, compartido)

    @property
    def vacio(self):
        """True si el renglón no tiene nada capturado (aparte del número de partida)."""
        datos = getattr(self, "cleaned_data", {})
        return all(datos.get(c) in (None, "") for c in self.fields if c != "numero")

    def clean(self):
        datos = super().clean()
        if not self.vacio and not datos.get("numero"):
            self.add_error("numero", "Falta el número de partida.")
        centro, grupo = datos.get("centro"), datos.get("grupo_compras")
        if centro and grupo and grupo.centro_id != centro.id:
            self.add_error("grupo_compras", "Este grupo de compras no pertenece al Centro de la partida.")
        almacen = datos.get("almacen")
        if centro and almacen and almacen.centro_id != centro.id:
            # La relación Centro–Almacén: el almacén tiene que ser de ESE Centro.
            self.add_error("almacen", "Este almacén no pertenece al Centro de la partida.")
        if centro and not almacen and not self._centro_tiene_almacen(centro):
            self.add_error("almacen", "Este Centro no tiene almacenes activos; avisa a ADMIN.")
        return datos

    def _centro_tiene_almacen(self, centro):
        if self.compartido is not None and "almacen" in self.compartido:
            return any(a.centro_id == centro.id for a in self.compartido["almacen"][0].values())
        return Almacen.objects.filter(centro=centro, activo=True).exists()

    def faltantes(self):
        """Campos obligatorios vacíos. Solo se usa al Enviar."""
        return [c for c in CAMPOS_OBLIGATORIOS_ENVIO if self.cleaned_data.get(c) in (None, "")]


# Máximo de partidas por solicitud (config/settings.py). validate_max: si llegan más, el formset
# marca un error en vez de cortar los renglones sobrantes en silencio.
LIMITE = {"max_num": settings.MAX_PARTIDAS, "absolute_max": settings.MAX_PARTIDAS, "validate_max": True}


class BasePartidasFormSet(FormsetCompartido, forms.BaseFormSet):
    default_error_messages = {
        **forms.BaseFormSet.default_error_messages,
        "too_many_forms": "Máximo %(num)d partidas por solicitud. Divide la captura en varias solicitudes.",
    }

    def __init__(self, *args, centros=None, **kwargs):
        self.centros = centros
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        # Así cada renglón recibe los Centros del usuario.
        return {**super().get_form_kwargs(index), "centros": self.centros}

    @property
    def renglones(self):
        """Renglones con algo capturado. Los vacíos se ignoran, como en Excel."""
        return [f for f in self.forms if f.is_valid() and not f.vacio]

    def clean(self):
        """Reglas entre renglones: el número de partida no se repite."""
        if any(self.errors):
            return
        vistos = set()
        for form in self.renglones:
            numero = form.cleaned_data.get("numero")
            if numero in vistos:
                form.add_error("numero", "Número de partida repetido.")
            vistos.add(numero)

    def validar_para_envio(self):
        """Validación estricta: True si se puede enviar; si no, marca TODOS los errores a la vez."""
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
        return ok


PartidasFormSet = forms.formset_factory(PartidaAltaForm, formset=BasePartidasFormSet, extra=0, can_delete=False, **LIMITE)


# --- Corrección de partidas ya enviadas (fase 3) ------------------------------------------
# SOL_MAT corrige sus partidas DEVUELTA_SOL y VAL_MAT las EN_VALIDACION de sus Centros.
# Es la misma tabla, con dos diferencias: cada renglón lleva el id de su partida
# (oculto) y el número de partida ya no se puede cambiar ni se agregan renglones.


class PartidaCorreccionForm(PartidaAltaForm):
    pid = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # disabled: el navegador no lo deja editar y Django IGNORA lo que llegue en la petición
        # para este campo; usa siempre el valor inicial. Nadie puede renumerar una partida enviada.
        self.fields["numero"].disabled = True


class BaseCorreccionFormSet(BasePartidasFormSet):
    @property
    def renglones(self):
        # Aquí todos los renglones cuentan, aunque se hayan vaciado: son partidas que ya existen.
        return [f for f in self.forms if f.is_valid()]


CorreccionFormSet = forms.formset_factory(
    PartidaCorreccionForm, formset=BaseCorreccionFormSet, extra=0, can_delete=False, **LIMITE
)
