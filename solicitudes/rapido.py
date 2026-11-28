"""Capturas grandes sin esperar (pedido de Dave: 1,194 partidas en una solicitud).

Con cientos de renglones, dos cosas hacían lenta la tabla:

1. **Consultas repetidas.** Cada renglón es un formulario, y cada lista desplegable
   (UMB, Almacén, Grupo de compras…) consultaba su catálogo por su cuenta: para mostrarse y
   otra vez para validar. 1,200 renglones × 7 listas = más de 8,000 consultas iguales.
   Aquí cada catálogo se consulta UNA vez por formset y todos los renglones comparten la lista.

2. **Dibujar las listas.** Django dibuja cada <option> con una plantilla. 1,200 × 7 listas ×
   sus opciones son decenas de miles de plantillas. `SelectRapido` arma el HTML directo en Python.
"""

from django import forms
from django.forms.utils import flatatt
from django.utils.html import escape, format_html


class SelectRapido(forms.Select):
    """Igual que forms.Select, pero arma el HTML en Python (mucho más rápido con miles de listas)."""

    def render(self, name, value, attrs=None, renderer=None):
        seleccionado = "" if value is None else str(value)
        opciones = "".join(
            f'<option value="{escape(v)}"{" selected" if str(v) == seleccionado else ""}>{escape(t)}</option>'
            for v, t in self.choices
        )
        final = self.build_attrs(self.attrs, {**(attrs or {}), "name": name})
        return format_html("<select{}>{}</select>", flatatt(final), _seguro(opciones))


def _seguro(html):
    from django.utils.safestring import mark_safe

    return mark_safe(html)  # ya se escapó cada valor y texto arriba


def compartir_catalogos(form, compartido):
    """Hace que las listas de `form` usen los catálogos guardados en `compartido` (un dict del formset).

    El primer renglón consulta cada catálogo y lo guarda; los demás lo reutilizan.
    Validar un valor ya no consulta la base: se busca en un diccionario {id: objeto}.
    """
    for nombre, campo in form.fields.items():
        if not isinstance(campo, forms.ModelChoiceField) or campo.disabled:
            continue
        if nombre not in compartido:
            objetos = list(campo.queryset)
            compartido[nombre] = (
                {str(o.pk): o for o in objetos},
                [("", campo.empty_label or "")] + [(o.pk, campo.label_from_instance(o)) for o in objetos],
            )
        por_id, opciones = compartido[nombre]
        campo.widget = SelectRapido(attrs=campo.widget.attrs)
        campo.widget.choices = opciones

        def to_python(valor, campo=campo, por_id=por_id):
            if valor in campo.empty_values:
                return None
            objeto = por_id.get(str(getattr(valor, "pk", valor)))
            if objeto is None:
                raise forms.ValidationError(campo.error_messages["invalid_choice"], code="invalid_choice")
            return objeto

        campo.to_python = to_python
        campo.validate = lambda valor, campo=campo: forms.Field.validate(campo, valor)


class FormsetCompartido:
    """Mezcla para un formset: cada renglón recibe el mismo dict `compartido`."""

    @property
    def compartido(self):
        if not hasattr(self, "_compartido"):
            self._compartido = {}
        return self._compartido

    def get_form_kwargs(self, index):
        return {**super().get_form_kwargs(index), "compartido": self.compartido}
