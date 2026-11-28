"""{% load vencimientos %} … {% aviso_vencimiento partida %}: el indicador de 15/30 días."""

from django import template
from django.utils.html import format_html

from solicitudes.vencimientos import DIAS_CANCELA, estado_vencimiento

register = template.Library()


@register.simple_tag
def aviso_vencimiento(partida):
    v = estado_vencimiento(partida)
    if v is None:
        return ""
    if v["vencida"]:
        return format_html('<span class="wd-vencida" title="Devuelta hace {} días; a los {} se cancela sola.">'
                           'VENCIDA · se cancela en {} día(s)</span>', v["dias"], DIAS_CANCELA, v["faltan"])
    return format_html('<span class="wd-por-vencer" title="Devuelta hace {} días.">Vence en {} día(s)</span>',
                       v["dias"], v["faltan"])


@register.simple_tag
def vencidas_de(solicitud):
    """Cuántas partidas de la solicitud están VENCIDAS (usa las partidas ya precargadas)."""
    n = sum(1 for p in solicitud.partidas.all() if (estado_vencimiento(p) or {}).get("vencida"))
    return format_html('<span class="wd-vencida">{} vencida(s)</span>', n) if n else ""
