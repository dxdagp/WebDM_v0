"""Normalización de texto para SAP: MAYÚSCULAS y sin acentos (Revisión 3, sección 7.2).

Ejemplo: "  Filtro de  aire óptimo " -> "FILTRO DE AIRE OPTIMO"
"""

import unicodedata


def texto_sap(valor):
    """Convierte a mayúsculas, quita acentos y deja un solo espacio entre palabras.

    Cómo se quitan los acentos: la forma NFD de Unicode separa cada letra de
    su acento ("Ó" se vuelve "O" + "◌́"). Luego descartamos los caracteres de
    categoría "Mn" (marcas que se combinan con la letra anterior).

    Suposición: la Ñ se conserva, porque no es una letra acentuada sino una
    letra propia del español. Si SAP la rechaza, basta con quitar el bloque
    que la protege.
    """
    if valor is None:
        return ""
    texto = " ".join(str(valor).split()).upper()  # split() sin argumentos también quita tabuladores y saltos
    texto = texto.replace("Ñ", "\0")  # protege la Ñ con un carácter temporal
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return sin_acentos.replace("\0", "Ñ")
