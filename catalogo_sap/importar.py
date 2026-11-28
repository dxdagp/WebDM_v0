"""Importación del catálogo SAP desde un TXT (Revisión 3, sección 12 y 17.1).

Formato del archivo:
- Texto separado por tabuladores, en UTF-8 (con o sin BOM), con renglón de encabezados.
- Las columnas pueden venir en cualquier orden; las que no se conocen se ignoran.
- MATERIALES (un renglón por material y Centro):
    CODIGO_SAP, DESCRIPCION, CENTRO, TIPO_MATERIAL, UMB, GRUPO_COMPRAS, GRUPO_ARTICULOS,
    CATEGORIA_VALORACION, CEBE; opcional NO_PARTE_ORIGINAL.
- SERVICIOS (un renglón por servicio; no dependen de un Centro):
    CODIGO_SAP, DESCRIPCION, TIPO_MATERIAL, UMB.

Reglas (confirmadas por Dave el 28-nov-2026):
- Cada renglón se valida por separado; los buenos se importan aunque otros fallen.
- Materiales: Código + Centro no se repite. Servicios: el código no se repite.
- Si el código ya existía en ESE catálogo antes de la importación: error.
- Si un código de materiales trae descripciones distintas: no se importa NINGUNO de sus renglones.
- Materiales y servicios son catálogos independientes: el mismo código puede estar en los dos.
  Materiales son ZRA; servicios ZRA o ZSA. Un ZSA en el archivo de materiales es error.
- Sin límite de tamaño: el archivo se lee renglón por renglón, no completo en memoria.

Tres pasos:
1. Leer y validar cada renglón por sí solo (formato, Centro existente…).
2. Validar entre renglones (repetidos, descripciones distintas del mismo código).
3. Guardar todo lo válido con bulk_create, en UNA transacción.
"""

import csv
import io
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from catalogos.models import Centro
from solicitudes.normalizar import texto_sap

from .models import ErrorImportacion, Importacion, MaterialCentro, MaterialSAP

# Columnas por catálogo, en el orden recomendado para el archivo.
COLUMNAS = {
    "MATERIALES": {
        "obligatorias": ["CODIGO_SAP", "DESCRIPCION", "CENTRO", "TIPO_MATERIAL", "UMB", "GRUPO_COMPRAS",
                         "GRUPO_ARTICULOS", "CATEGORIA_VALORACION", "CEBE"],
        "opcionales": ["NO_PARTE_ORIGINAL"],
    },
    "SERVICIOS": {
        "obligatorias": ["CODIGO_SAP", "DESCRIPCION", "TIPO_MATERIAL", "UMB"],
        "opcionales": [],
    },
}
LARGO_MAXIMO = {"TIPO_MATERIAL": 10, "UMB": 10, "GRUPO_COMPRAS": 20, "GRUPO_ARTICULOS": 20,
                "CATEGORIA_VALORACION": 20, "CEBE": 20}
TIPOS_SOLO_SERVICIO = {"ZSA"}
LOTE = 1000  # renglones por INSERT en bulk_create


class ArchivoInvalido(Exception):
    """El archivo completo no se puede importar (codificación, encabezados…). No se guarda nada."""


@dataclass
class Renglon:
    linea: int
    codigo: str
    descripcion: str
    centro: Centro | None  # None en servicios
    datos: dict  # TIPO_MATERIAL, UMB, NO_PARTE_ORIGINAL, GRUPO_COMPRAS…

    @property
    def centro_txt(self):
        return self.centro.codigo if self.centro else ""


@dataclass
class Resultado:
    buenos: list = field(default_factory=list)
    errores: list = field(default_factory=list)  # (linea, codigo, centro, mensaje)

    def error(self, linea, codigo, centro, mensaje):
        self.errores.append((linea, codigo[:20], centro[:10], mensaje[:255]))


def _leer(archivo, columnas):
    """Devuelve un lector de renglones (diccionarios) y la lista de encabezados.

    TextIOWrapper decodifica los bytes a texto MIENTRAS se lee, en pedazos: así un archivo
    de 500 MB no se carga entero a memoria. "utf-8-sig" acepta el BOM que agrega el Bloc de notas.
    """
    texto = io.TextIOWrapper(archivo, encoding="utf-8-sig", newline="")
    # QUOTE_NONE: las comillas son texto normal (SAP no las usa como delimitador).
    lector = csv.reader(texto, delimiter="\t", quoting=csv.QUOTE_NONE)
    try:
        encabezados = [h.strip().upper() for h in next(lector)]
    except StopIteration:
        raise ArchivoInvalido("El archivo está vacío.")
    faltan = [c for c in columnas["obligatorias"] if c not in encabezados]
    if faltan:
        raise ArchivoInvalido(
            "Faltan columnas obligatorias: " + ", ".join(faltan)
            + ". ¿Está separado por tabuladores y tiene renglón de encabezados?"
        )
    conocidas = columnas["obligatorias"] + columnas["opcionales"]
    indice = {nombre: encabezados.index(nombre) for nombre in conocidas if nombre in encabezados}
    return lector, indice


def _validar_renglones(lector, indice, columnas, centros, existentes, servicios):
    """Paso 1: cada renglón por sí solo."""
    resultado = Resultado()
    for linea, valores in enumerate(lector, start=2):  # la línea 1 son los encabezados
        if not any(v.strip() for v in valores):
            continue  # renglón en blanco: se ignora, no es error

        def col(nombre):
            i = indice.get(nombre)
            return valores[i].strip() if i is not None and i < len(valores) else ""

        codigo = col("CODIGO_SAP")
        centro_txt = col("CENTRO").upper()
        descripcion = texto_sap(col("DESCRIPCION"))
        datos = {n: col(n).upper() for n in LARGO_MAXIMO if n in indice}
        datos["NO_PARTE_ORIGINAL"] = texto_sap(col("NO_PARTE_ORIGINAL"))
        valores_obligatorios = {"CODIGO_SAP": codigo, "DESCRIPCION": descripcion, "CENTRO": centro_txt, **datos}
        vacios = [n for n in columnas["obligatorias"] if not valores_obligatorios.get(n)]
        largos = [f"{n} (máx. {m})" for n, m in LARGO_MAXIMO.items() if len(datos.get(n, "")) > m]

        if vacios:
            mensaje = "Faltan datos obligatorios: " + ", ".join(vacios) + "."
        elif not (len(codigo) == 6 and codigo.isdigit()):
            mensaje = "El Código SAP debe tener exactamente 6 dígitos."
        elif not servicios and centro_txt not in centros:
            mensaje = f"El Centro {centro_txt} no existe en WebDM."
        elif len(descripcion) > 40:
            mensaje = f"La descripción tiene {len(descripcion)} caracteres; el máximo es 40."
        elif len(datos["NO_PARTE_ORIGINAL"]) > 40:
            mensaje = "El No. Parte Original tiene más de 40 caracteres."
        elif largos:
            mensaje = "Demasiado largo: " + ", ".join(largos) + "."
        elif not servicios and datos["TIPO_MATERIAL"] in TIPOS_SOLO_SERVICIO:
            mensaje = f"{datos['TIPO_MATERIAL']} es de servicios; impórtalo en el catálogo de servicios."
        elif codigo in existentes:
            mensaje = "El código ya existía en este catálogo antes de esta importación."
            if not servicios:
                mensaje += " Para otro Centro usa AMPL_ZRA."
        else:
            centro = None if servicios else centros[centro_txt]
            resultado.buenos.append(Renglon(linea, codigo, descripcion, centro, datos))
            continue
        resultado.error(linea, codigo, "" if servicios else centro_txt, mensaje)
    return resultado


def _validar_entre_renglones(resultado):
    """Paso 2: reglas que necesitan ver varios renglones."""
    por_codigo = {}
    for r in resultado.buenos:
        por_codigo.setdefault(r.codigo, []).append(r)

    buenos = []
    for codigo, renglones in por_codigo.items():
        # Descripciones distintas para el mismo código: no se sube NINGUNO (pedido de Dave).
        if len({r.descripcion for r in renglones}) > 1:
            lineas = ", ".join(str(r.linea) for r in renglones)
            for r in renglones:
                resultado.error(r.linea, codigo, r.centro_txt,
                                f"El código trae descripciones distintas (líneas {lineas}); no se importó ninguna.")
            continue
        vistos = {}
        for r in renglones:
            llave = r.centro.pk if r.centro else None  # servicios: el código solo, sin Centro
            if llave in vistos:
                que = "Código y Centro repetidos" if r.centro else "Código repetido"
                resultado.error(r.linea, codigo, r.centro_txt, f"{que} (ya venía en la línea {vistos[llave]}).")
            else:
                vistos[llave] = r.linea
                buenos.append(r)
    resultado.buenos = buenos
    resultado.errores.sort()
    return resultado


@transaction.atomic
def importar(archivo, nombre, usuario, catalogo=Importacion.Catalogo.MATERIALES):
    """Importa el TXT al catálogo indicado (materiales o servicios) y devuelve la Importacion con su resumen. Lanza ArchivoInvalido si no se puede leer."""
    centros = {c.codigo.upper(): c for c in Centro.objects.all()}
    # Los códigos que YA existían antes de empezar. Un set en memoria: preguntar "¿está?" cuesta lo mismo
    # con 10 o con 100,000 elementos, y nos ahorra una consulta por renglón.
    servicios = catalogo == Importacion.Catalogo.SERVICIOS
    existentes = set(MaterialSAP.objects.filter(es_servicio=servicios).values_list("codigo", flat=True))
    columnas = COLUMNAS[catalogo]
    try:
        lector, indice = _leer(archivo, columnas)
        resultado = _validar_renglones(lector, indice, columnas, centros, existentes, servicios)
    except UnicodeDecodeError:
        raise ArchivoInvalido("El archivo no está en UTF-8. En Excel: Guardar como → 'Texto Unicode (UTF-8)'.")
    except csv.Error as e:
        raise ArchivoInvalido(f"No se pudo leer el archivo: {e}")
    resultado = _validar_entre_renglones(resultado)

    importacion = Importacion.objects.create(usuario=usuario, catalogo=catalogo, nombre_archivo=nombre[:255])

    # Paso 3. Un material por código (el primer renglón manda) y un MaterialCentro por renglón.
    materiales = {}
    for r in resultado.buenos:
        if r.codigo not in materiales:
            materiales[r.codigo] = MaterialSAP(
                codigo=r.codigo, descripcion=r.descripcion, tipo_material=r.datos["TIPO_MATERIAL"],
                umb=r.datos["UMB"], no_parte_original=r.datos["NO_PARTE_ORIGINAL"],
                grupo_articulos=r.datos.get("GRUPO_ARTICULOS", ""), es_servicio=servicios, origen=MaterialSAP.Origen.IMPORT,
                importacion=importacion, creado_por=usuario,
            )
    try:
        # bulk_create: un INSERT con muchos VALUES (…), (…) por lote, en vez de uno por material.
        # En PostgreSQL devuelve los id generados (RETURNING id), que usamos abajo.
        MaterialSAP.objects.bulk_create(materiales.values(), batch_size=LOTE)
        # Solo los materiales tienen Centro (con su grupo de compras, categoría y CeBe).
        MaterialCentro.objects.bulk_create(
            [MaterialCentro(material=materiales[r.codigo], centro=r.centro,
                            grupo_compras=r.datos["GRUPO_COMPRAS"], cebe=r.datos["CEBE"],
                            categoria_valoracion=r.datos["CATEGORIA_VALORACION"])
             for r in resultado.buenos if r.centro],
            batch_size=LOTE,
        )
    except IntegrityError:
        # Alguien dio de alta uno de estos códigos mientras leíamos el archivo.
        raise ArchivoInvalido("Otro usuario agregó materiales mientras se importaba. Vuelve a intentarlo.")

    ErrorImportacion.objects.bulk_create(
        [ErrorImportacion(importacion=importacion, linea=l, codigo_sap=c, centro=ce, mensaje=m)
         for l, c, ce, m in resultado.errores],
        batch_size=LOTE,
    )
    importacion.importados = len(resultado.buenos)
    importacion.errores = len(resultado.errores)
    importacion.save(update_fields=["importados", "errores"])
    return importacion
