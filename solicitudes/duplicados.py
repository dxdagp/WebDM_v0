"""Búsqueda de duplicados de AMAT_ZRA contra el Catálogo SAP interno (Revisión 3, sección 8).

Solo se comparan la Descripción técnica y el No. Parte Original. Sin IA.

| Caso                                     | Resultado              | ¿Bloquea? |
| ---------------------------------------- | ---------------------- | --------- |
| Descripción Y No. Parte exactos          | DUPLICADO              | Sí        |
| No. Parte exacto, descripción distinta   | ADVERTENCIA            | No        |
| Descripción exacta, No. Parte distinto   | ADVERTENCIA            | No        |
| Descripción parecida al 80 % o más       | POSIBLE                | No        |

Cómo se mide "parecida" (ajuste pedido por Dave: ACEITE y AIRE son cosas distintas):
se compara PALABRA por PALABRA, no letra por letra.
1. Se quitan las palabras vacías (DE, PARA, CON…): "FILTRO DE AIRE" → FILTRO, AIRE.
2. Dos palabras "coinciden" si se parecen al 85 % o más letra por letra
   (`difflib.SequenceMatcher`). Así se perdona un error de dedo (AIRE/AIRRE = 89 %)
   pero no otra palabra (AIRE/ACEITE = 60 %).
3. Parecido = 2 × palabras que coinciden ÷ total de palabras de los dos textos.
   "FILTRO AIRE" vs "FILTRO DE AIRE" = 100 %; vs "FILTRO DE ACEITE" = 50 %.

Para no comparar contra TODO el catálogo, primero PostgreSQL filtra candidatos que
compartan alguna palabra de 3 letras o más (ILIKE), y solo a esos se les calcula el
parecido en Python.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

from django.db.models import Q

from catalogo_sap.models import MaterialSAP

from .normalizar import texto_sap

UMBRAL = 0.80  # umbral inicial; se ajustará con datos reales (Rev. 3)
MAX_RESULTADOS = 10

DUPLICADO, ADVERTENCIA, POSIBLE = "DUPLICADO", "ADVERTENCIA", "POSIBLE"


@dataclass
class Coincidencia:
    tipo: str  # DUPLICADO, ADVERTENCIA o POSIBLE
    motivo: str
    codigo: str
    descripcion: str
    no_parte: str
    umb: str
    parecido: int  # porcentaje

    @property
    def bloquea(self):
        return self.tipo == DUPLICADO

    def como_dict(self):
        return {**self.__dict__, "bloquea": self.bloquea}


PALABRAS_VACIAS = {"DE", "DEL", "LA", "EL", "LOS", "LAS", "PARA", "CON", "Y", "A", "EN", "P/"}
UMBRAL_PALABRA = 0.85  # cuánto deben parecerse dos palabras para contar como la misma


def palabras(texto):
    return [p for p in texto.split() if p not in PALABRAS_VACIAS]


def parecido(a, b):
    """De 0 a 1: qué tanto comparten dos descripciones, palabra por palabra."""
    pa, pb = palabras(a), palabras(b)
    if not pa or not pb:
        return 0.0
    libres = list(pb)
    iguales = 0
    for palabra in pa:
        # La palabra de `b` que más se le parece y aún no se usó.
        mejor = max(libres, key=lambda otra: SequenceMatcher(None, palabra, otra).ratio(), default=None)
        if mejor is not None and SequenceMatcher(None, palabra, mejor).ratio() >= UMBRAL_PALABRA:
            iguales += 1
            libres.remove(mejor)
    return 2 * iguales / (len(pa) + len(pb))


def buscar(descripcion, no_parte=""):
    """Coincidencias de un material contra el catálogo, de la más grave a la más leve."""
    descripcion, no_parte = texto_sap(descripcion), texto_sap(no_parte)
    if not descripcion and not no_parte:
        return []

    palabras = [p for p in descripcion.split() if len(p) >= 3]
    filtro = Q()
    for palabra in palabras:
        filtro |= Q(descripcion__icontains=palabra)
    if descripcion:
        filtro |= Q(descripcion__iexact=descripcion)
    if no_parte:
        filtro |= Q(no_parte_original__iexact=no_parte)
    if not filtro:
        return []

    resultados = []
    for m in MaterialSAP.objects.filter(filtro, es_servicio=False)[:2000]:
        m_desc, m_parte = texto_sap(m.descripcion), texto_sap(m.no_parte_original)
        misma_desc = bool(descripcion) and m_desc == descripcion
        misma_parte = bool(no_parte) and m_parte == no_parte
        p = parecido(descripcion, m_desc) if descripcion else 0
        if misma_desc and misma_parte:
            tipo, motivo = DUPLICADO, "Ya existe con la misma descripción y el mismo No. Parte."
        elif misma_parte:
            tipo, motivo = ADVERTENCIA, "Mismo No. Parte con otra descripción."
        elif misma_desc:
            tipo, motivo = ADVERTENCIA, "Misma descripción con otro No. Parte."
        elif p >= UMBRAL:
            tipo, motivo = POSIBLE, f"Descripción parecida al {round(p * 100)} %."
        else:
            continue
        resultados.append(Coincidencia(tipo, motivo, m.codigo, m.descripcion, m.no_parte_original, m.umb, round(p * 100)))

    gravedad = {DUPLICADO: 0, ADVERTENCIA: 1, POSIBLE: 2}
    resultados.sort(key=lambda c: (gravedad[c.tipo], -c.parecido))
    return resultados[:MAX_RESULTADOS]


def bloqueante(descripcion, no_parte):
    """El primer duplicado exacto, o None. Es lo que impide Enviar."""
    return next((c for c in buscar(descripcion, no_parte) if c.bloquea), None)
