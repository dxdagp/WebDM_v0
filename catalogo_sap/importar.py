"""Importación del catálogo SAP desde un TXT (Revisión 3, sección 12 y 17.1).

Formato del archivo:
- Texto separado por tabuladores, en UTF-8 (con o sin BOM), con renglón de encabezados.
- Obligatorias: CODIGO_SAP, DESCRIPCION, CENTRO, TIPO_MATERIAL, UMB.
- Opcional: NO_PARTE_ORIGINAL. Cualquier otra columna se ignora.
- Un renglón por combinación material-Centro.

Reglas (confirmadas por Dave el 28-nov-2026):
- Cada renglón se valida por separado; los buenos se importan aunque otros fallen.
- Código + Centro no se repite dentro del archivo.
- Si el código ya existía en WebDM ANTES de la importación: error (se amplía con AMPL_ZRA).
- Si un código trae descripciones distintas en sus renglones: no se importa NINGUNO de sus renglones.
- Materiales y servicios son catálogos SEPARADOS: quien importa elige a cuál va el archivo.
  Materiales son ZRA; servicios pueden ser ZRA o ZSA. Un ZSA en el archivo de materiales es error.
- Los códigos son únicos entre los dos catálogos (en SAP son el mismo número de material).
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

OBLIGATORIAS = ["CODIGO_SAP", "DESCRIPCION", "CENTRO", "TIPO_MATERIAL", "UMB"]
OPCIONALES = ["NO_PARTE_ORIGINAL"]
TIPOS_SOLO_SERVICIO = {"ZSA"}
LOTE = 1000  # renglones por INSERT en bulk_create


class ArchivoInvalido(Exception):
    """El archivo completo no se puede importar (codificación, encabezados…). No se guarda nada."""


@dataclass
class Renglon:
    linea: int
    codigo: str
    descripcion: str
    centro: Centro
    tipo_material: str
    umb: str
    no_parte: str


@dataclass
class Resultado:
    buenos: list = field(default_factory=list)
    errores: list = field(default_factory=list)  # (linea, codigo, centro, mensaje)

    def error(self, linea, codigo, centro, mensaje):
        self.errores.append((linea, codigo[:20], centro[:10], mensaje[:255]))


def _leer(archivo):
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
    faltan = [c for c in OBLIGATORIAS if c not in encabezados]
    if faltan:
        raise ArchivoInvalido(
            "Faltan columnas obligatorias: " + ", ".join(faltan)
            + ". ¿Está separado por tabuladores y tiene renglón de encabezados?"
        )
    indice = {nombre: encabezados.index(nombre) for nombre in OBLIGATORIAS + OPCIONALES if nombre in encabezados}
    return lector, indice


def _validar_renglones(lector, indice, centros, existentes, servicios):
    """Paso 1: cada renglón por sí solo."""
    resultado = Resultado()
    for linea, valores in enumerate(lector, start=2):  # la línea 1 son los encabezados
        if not any(v.strip() for v in valores):
            continue  # renglón en blanco: se ignora, no es error

        def col(nombre):
            i = indice.get(nombre)
            return valores[i].strip() if i is not None and i < len(valores) else ""

        codigo, centro_txt = col("CODIGO_SAP"), col("CENTRO").upper()
        descripcion = texto_sap(col("DESCRIPCION"))
        tipo, umb = col("TIPO_MATERIAL").upper(), col("UMB").upper()
        no_parte = texto_sap(col("NO_PARTE_ORIGINAL"))
        vacios = [n for n, v in [("CODIGO_SAP", codigo), ("DESCRIPCION", descripcion), ("CENTRO", centro_txt),
                                 ("TIPO_MATERIAL", tipo), ("UMB", umb)] if not v]
        if vacios:
            mensaje = "Faltan datos obligatorios: " + ", ".join(vacios) + "."
        elif not (len(codigo) == 6 and codigo.isdigit()):
            mensaje = "El Código SAP debe tener exactamente 6 dígitos."
        elif centro_txt not in centros:
            mensaje = f"El Centro {centro_txt} no existe en WebDM."
        elif len(descripcion) > 40:
            mensaje = f"La descripción tiene {len(descripcion)} caracteres; el máximo es 40."
        elif len(no_parte) > 40:
            mensaje = "El No. Parte Original tiene más de 40 caracteres."
        elif len(tipo) > 10 or len(umb) > 10:
            mensaje = "TIPO_MATERIAL y UMB tienen máximo 10 caracteres."
        elif not servicios and tipo in TIPOS_SOLO_SERVICIO:
            mensaje = f"{tipo} es de servicios; impórtalo en el catálogo de servicios."
        elif codigo in existentes:
            mensaje = "El código ya existía en WebDM antes de esta importación (en materiales o en servicios). Para otro Centro usa AMPL_ZRA."
        else:
            resultado.buenos.append(Renglon(linea, codigo, descripcion, centros[centro_txt], tipo, umb, no_parte))
            continue
        resultado.error(linea, codigo, centro_txt, mensaje)
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
                resultado.error(r.linea, codigo, r.centro.codigo,
                                f"El código trae descripciones distintas (líneas {lineas}); no se importó ninguna.")
            continue
        vistos = {}
        for r in renglones:
            if r.centro.pk in vistos:
                resultado.error(r.linea, codigo, r.centro.codigo,
                                f"Código y Centro repetidos (ya venían en la línea {vistos[r.centro.pk]}).")
            else:
                vistos[r.centro.pk] = r.linea
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
    existentes = set(MaterialSAP.objects.values_list("codigo", flat=True))
    try:
        lector, indice = _leer(archivo)
        servicios = catalogo == Importacion.Catalogo.SERVICIOS
        resultado = _validar_renglones(lector, indice, centros, existentes, servicios)
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
                codigo=r.codigo, descripcion=r.descripcion, tipo_material=r.tipo_material, umb=r.umb,
                no_parte_original=r.no_parte, es_servicio=servicios, origen=MaterialSAP.Origen.IMPORT,
                importacion=importacion, creado_por=usuario,
            )
    try:
        # bulk_create: un INSERT con muchos VALUES (…), (…) por lote, en vez de uno por material.
        # En PostgreSQL devuelve los id generados (RETURNING id), que usamos abajo.
        MaterialSAP.objects.bulk_create(materiales.values(), batch_size=LOTE)
        MaterialCentro.objects.bulk_create(
            [MaterialCentro(material=materiales[r.codigo], centro=r.centro) for r in resultado.buenos],
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
