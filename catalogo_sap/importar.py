"""Importación del catálogo SAP desde un TXT (Revisión 3, sección 12 y 17.1).

Formato del archivo:
- Texto separado por tabuladores, en UTF-8 (con o sin BOM), con renglón de encabezados.
- Las columnas pueden venir en cualquier orden; las que no se conocen se ignoran.
- MATERIALES (un renglón por material y Centro):
    CODIGO_SAP, DESCRIPCION, CENTRO, TIPO_MATERIAL, UMB, GRUPO_COMPRAS, GRUPO_ARTICULOS,
    CATEGORIA_VALORACION, CEBE; opcional NO_PARTE_ORIGINAL.
- SERVICIOS (un renglón por servicio; no dependen de un Centro):
    CODIGO_SAP, DESCRIPCION, TIPO_MATERIAL, UMB, GRUPO_ARTICULOS.

Reglas (confirmadas por Dave el 28-nov-2026):
- Cada renglón se valida por separado; los buenos se importan aunque otros fallen.
- Los valores se validan contra los catálogos de WebDM (activos): Tipo de material, UMB,
  Grupo de artículos, Categoría de valoración (del mismo tipo de material), Grupo de compras
  del Centro, y el CeBe debe ser el del Centro.
- Materiales: si la combinación Código + Centro ya existe en WebDM, ese renglón no se carga.
  Si el código ya existe pero en OTRO Centro, se agrega el Centro al material existente
  (su descripción y grupo de artículos deben coincidir con los que ya tiene).
- Servicios: si el código ya existe en el catálogo de servicios, no se carga.
- Un código tiene UNA descripción y UN grupo de artículos: si el archivo trae distintos,
  no se importa NINGUNO de sus renglones.
- Materiales y servicios son catálogos independientes: el mismo código puede estar en los dos.
  Materiales son ZRA; servicios ZRA o ZSA. Un ZSA en el archivo de materiales es error.
- Sin límite de tamaño: el archivo se lee renglón por renglón, no completo en memoria.

Tres pasos:
1. Leer y validar cada renglón por sí solo (formato, catálogos, Centro ya cargado…).
2. Validar entre renglones (repetidos, descripción o grupo de artículos distintos del mismo código).
3. Guardar todo lo válido con bulk_create, en UNA transacción.
"""

import csv
import io
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction

from catalogos.models import UMB, CategoriaValoracion, Centro, GrupoArticulos, GrupoCompras, TipoMaterial
from solicitudes.normalizar import texto_sap

from . import historial
from .models import ErrorImportacion, Importacion, MaterialCentro, MaterialSAP

# Columnas por catálogo, en el orden recomendado para el archivo.
COLUMNAS = {
    "MATERIALES": {
        "obligatorias": ["CODIGO_SAP", "DESCRIPCION", "CENTRO", "TIPO_MATERIAL", "UMB", "GRUPO_COMPRAS",
                         "GRUPO_ARTICULOS", "CATEGORIA_VALORACION", "CEBE"],
        "opcionales": ["NO_PARTE_ORIGINAL"],
    },
    "SERVICIOS": {
        "obligatorias": ["CODIGO_SAP", "DESCRIPCION", "TIPO_MATERIAL", "UMB", "GRUPO_ARTICULOS"],
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
class Existente:
    """Lo que WebDM ya tiene de un código antes de importar."""
    id: int
    descripcion: str
    grupo_articulos: str
    centros: set = field(default_factory=set)  # ids de Centro (vacío en servicios)


@dataclass
class Referencias:
    """Todo lo que se consulta UNA vez al inicio, para validar cada renglón en memoria."""
    centros: dict  # "MTTU" -> Centro
    existentes: dict  # "123456" -> Existente
    tipos: set
    umbs: set
    grupos_articulos: set
    categorias: set  # (tipo de material, categoría)
    grupos_compras: set  # (id de Centro, grupo de compras)

    @classmethod
    def cargar(cls, servicios):
        existentes = {
            m.codigo: Existente(m.id, m.descripcion, m.grupo_articulos)
            for m in MaterialSAP.objects.filter(es_servicio=servicios).only("codigo", "descripcion", "grupo_articulos")
        }
        if not servicios:
            por_id = {e.id: e for e in existentes.values()}
            for material_id, centro_id in MaterialCentro.objects.values_list("material_id", "centro_id"):
                if material_id in por_id:
                    por_id[material_id].centros.add(centro_id)

        def codigos(modelo):
            return {c.upper() for c in modelo.objects.filter(activo=True).values_list("codigo", flat=True)}

        return cls(
            centros={c.codigo.upper(): c for c in Centro.objects.filter(activo=True)},
            existentes=existentes,
            tipos=codigos(TipoMaterial),
            umbs=codigos(UMB),
            grupos_articulos=codigos(GrupoArticulos),
            categorias={(t.upper(), c.upper()) for t, c in CategoriaValoracion.objects.filter(activo=True)
                        .values_list("tipo_material__codigo", "codigo")},
            grupos_compras={(ce, c.upper()) for ce, c in GrupoCompras.objects.filter(activo=True)
                            .values_list("centro_id", "codigo")},
        )


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


def _contra_catalogos(datos, centro, ref, servicios):
    """Errores de valores que no existen en los catálogos de WebDM (lista vacía si todo bien)."""
    tipo = datos["TIPO_MATERIAL"]
    malos = []
    if tipo not in ref.tipos:
        malos.append(f"Tipo de material {tipo}")
    if datos["UMB"] not in ref.umbs:
        malos.append(f"UMB {datos['UMB']}")
    if datos["GRUPO_ARTICULOS"] not in ref.grupos_articulos:
        malos.append(f"Grupo de artículos {datos['GRUPO_ARTICULOS']}")
    if not servicios:
        if (tipo, datos["CATEGORIA_VALORACION"]) not in ref.categorias:
            malos.append(f"Categoría de valoración {datos['CATEGORIA_VALORACION']} para {tipo}")
        if (centro.pk, datos["GRUPO_COMPRAS"]) not in ref.grupos_compras:
            malos.append(f"Grupo de compras {datos['GRUPO_COMPRAS']} en {centro.codigo}")
    errores = ["No existe en WebDM: " + ", ".join(malos) + "."] if malos else []
    if not servicios and datos["CEBE"] != (centro.centro_beneficio or "").upper():
        errores.append(f"El CeBe de {centro.codigo} es {centro.centro_beneficio or '(vacío)'}, no {datos['CEBE']}.")
    return " ".join(errores)


def _validar_renglones(lector, indice, columnas, ref, servicios):
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
        centro = ref.centros.get(centro_txt)
        descripcion = texto_sap(col("DESCRIPCION"))
        datos = {n: col(n).upper() for n in LARGO_MAXIMO if n in indice}
        datos["NO_PARTE_ORIGINAL"] = texto_sap(col("NO_PARTE_ORIGINAL"))
        valores_obligatorios = {"CODIGO_SAP": codigo, "DESCRIPCION": descripcion, "CENTRO": centro_txt, **datos}
        vacios = [n for n in columnas["obligatorias"] if not valores_obligatorios.get(n)]
        largos = [f"{n} (máx. {m})" for n, m in LARGO_MAXIMO.items() if len(datos.get(n, "")) > m]
        existente = ref.existentes.get(codigo)

        if vacios:
            mensaje = "Faltan datos obligatorios: " + ", ".join(vacios) + "."
        elif not (len(codigo) == 6 and codigo.isdigit()):
            mensaje = "El Código SAP debe tener exactamente 6 dígitos."
        elif not servicios and centro is None:
            mensaje = f"El Centro {centro_txt} no existe en WebDM (o está inactivo)."
        elif len(descripcion) > 40:
            mensaje = f"La descripción tiene {len(descripcion)} caracteres; el máximo es 40."
        elif len(datos["NO_PARTE_ORIGINAL"]) > 40:
            mensaje = "El No. Parte Original tiene más de 40 caracteres."
        elif largos:
            mensaje = "Demasiado largo: " + ", ".join(largos) + "."
        elif not servicios and datos["TIPO_MATERIAL"] in TIPOS_SOLO_SERVICIO:
            mensaje = f"{datos['TIPO_MATERIAL']} es de servicios; impórtalo en el catálogo de servicios."
        elif mensaje := _contra_catalogos(datos, centro, ref, servicios):
            pass
        elif existente and servicios:
            mensaje = "El código ya existe en el catálogo de servicios."
        elif existente and centro.pk in existente.centros:
            mensaje = f"El material ya existe en WebDM para el Centro {centro.codigo}; no se cargó."
        else:
            resultado.buenos.append(Renglon(linea, codigo, descripcion, None if servicios else centro, datos))
            continue
        resultado.error(linea, codigo, "" if servicios else centro_txt, mensaje)
    return resultado


def _validar_entre_renglones(resultado, existentes):
    """Paso 2: reglas que necesitan ver varios renglones (y lo que ya existe del mismo código)."""
    por_codigo = {}
    for r in resultado.buenos:
        por_codigo.setdefault(r.codigo, []).append(r)

    buenos = []
    for codigo, renglones in por_codigo.items():
        # Un código = una descripción y un grupo de artículos (pedido de Dave). Si no, no se sube NINGUNO.
        lineas = ", ".join(str(r.linea) for r in renglones)
        problema = None
        if len({r.descripcion for r in renglones}) > 1:
            problema = f"El código trae descripciones distintas (líneas {lineas}); no se importó ninguna."
        elif len({r.datos["GRUPO_ARTICULOS"] for r in renglones}) > 1:
            problema = f"El código trae grupos de artículos distintos (líneas {lineas}); no se importó ninguna."
        elif existente := existentes.get(codigo):
            # Material que ya existe en otro Centro: debe ser el MISMO material.
            r = renglones[0]
            if r.descripcion != existente.descripcion:
                problema = f"En WebDM el código {codigo} es {existente.descripcion}; el archivo dice {r.descripcion}."
            elif r.datos["GRUPO_ARTICULOS"] != existente.grupo_articulos:
                problema = (f"En WebDM el código {codigo} tiene grupo de artículos {existente.grupo_articulos or '(vacío)'};"
                            f" el archivo dice {r.datos['GRUPO_ARTICULOS']}.")
        if problema:
            for r in renglones:
                resultado.error(r.linea, codigo, r.centro_txt, problema)
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
    servicios = catalogo == Importacion.Catalogo.SERVICIOS
    # Catálogos y lo que YA existía, traídos una sola vez a memoria (sets y dicts): preguntar "¿está?"
    # cuesta lo mismo con 10 o con 100,000 elementos, y nos ahorra varias consultas por renglón.
    ref = Referencias.cargar(servicios)
    columnas = COLUMNAS[catalogo]
    try:
        lector, indice = _leer(archivo, columnas)
        resultado = _validar_renglones(lector, indice, columnas, ref, servicios)
    except UnicodeDecodeError:
        raise ArchivoInvalido("El archivo no está en UTF-8. En Excel: Guardar como → 'Texto Unicode (UTF-8)'.")
    except csv.Error as e:
        raise ArchivoInvalido(f"No se pudo leer el archivo: {e}")
    resultado = _validar_entre_renglones(resultado, ref.existentes)

    importacion = Importacion.objects.create(usuario=usuario, catalogo=catalogo, nombre_archivo=nombre[:255])

    # Paso 3. Un material NUEVO por código (el primer renglón manda) y un MaterialCentro por renglón.
    # Si el código ya existía (otro Centro), el MaterialCentro apunta al material existente, por su id.
    materiales = {}
    for r in resultado.buenos:
        if r.codigo not in materiales and r.codigo not in ref.existentes:
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
        por_centro = [MaterialCentro(material_id=(materiales[r.codigo].pk if r.codigo in materiales
                                                  else ref.existentes[r.codigo].id), centro=r.centro,
                                     grupo_compras=r.datos["GRUPO_COMPRAS"], cebe=r.datos["CEBE"],
                                     categoria_valoracion=r.datos["CATEGORIA_VALORACION"])
                      for r in resultado.buenos if r.centro]
        MaterialCentro.objects.bulk_create(por_centro, batch_size=LOTE)
        # Historial de cada material: alta (primer Centro) y ampliaciones (los demás Centros).
        historial.importados(importacion, materiales.values(), [(mc.material_id, mc.centro.codigo) for mc in por_centro])
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
