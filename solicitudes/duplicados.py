"""Búsqueda de duplicados de AMAT_ZRA contra el Catálogo SAP interno (Revisión 3, sección 8).

Solo se comparan la Descripción técnica y el No. Parte Original. Sin IA.

| Caso                                     | Resultado              | ¿Bloquea? |
| ---------------------------------------- | ---------------------- | --------- |
| Descripción Y No. Parte exactos          | DUPLICADO              | Sí        |
| No. Parte exacto, descripción distinta   | ADVERTENCIA            | No        |
| Descripción exacta, No. Parte distinto   | ADVERTENCIA            | No        |
| Descripción parecida al 80 % o más       | POSIBLE                | No        |

Cómo se mide "parecida": `difflib.SequenceMatcher` de Python (biblioteca estándar)
compara dos textos y da un número de 0 a 1 según cuántos caracteres comparten en el
mismo orden. "FILTRO DE AIRE" contra "FILTRO AIRE" da 0.88.

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


def parecido(a, b):
    return SequenceMatcher(None, a, b).ratio()


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
