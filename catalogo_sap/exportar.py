"""Exportar el catálogo (pedido de Dave): portapapeles, TXT con tabuladores, CSV y Excel.

Se exporta TODO lo que dejan los filtros (no solo la página de 50), con las mismas columnas y
en el mismo orden que la pantalla.

- TXT, CSV y portapapeles se mandan con StreamingHttpResponse: Django manda el archivo en pedazos
  mientras lo va generando, y .iterator() lee de PostgreSQL de 2,000 en 2,000. Así 100,000
  renglones no se cargan enteros a memoria.
- Excel usa openpyxl en modo write_only, que también escribe renglón por renglón.
"""

import csv
import io

from django.http import HttpResponse, StreamingHttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

FORMATOS = {"portapapeles", "txt", "csv", "xlsx"}


def _origen(m):
    if m.origen == "IMPORT":
        fecha = f" {m.importacion.fecha:%d/%m/%Y}" if m.importacion else ""
        return f"IMPORT {m.creado_por}{fecha}"
    return f"WEBDM {m.folio_origen}"


def _valor(nombre, r, servicio):
    """El dato de una columna para un renglón: r es MaterialSAP (servicios) o MaterialCentro (materiales)."""
    m = r if servicio else r.material
    por_centro = {"centro": lambda: r.centro.codigo, "grupo_compras": lambda: r.grupo_compras,
                  "categoria": lambda: r.categoria_valoracion, "almacen": lambda: r.almacen, "cebe": lambda: r.cebe}
    if nombre in por_centro:
        return por_centro[nombre]()
    del_material = {"codigo": m.codigo, "tipo": m.tipo_material, "descripcion": m.descripcion, "umb": m.umb,
                    "grupo_articulos": m.grupo_articulos, "ubicacion": m.ubicacion, "no_parte": m.no_parte_original,
                    "tipo_unidad": m.tipo_unidad, "marca": m.marca, "version": m.version,
                    "anio": m.anio_modelo if m.anio_modelo is not None else "", "compatibilidad": m.compatibilidad,
                    "origen": _origen(m)}
    return del_material[nombre]


def _renglones(queryset, columnas, servicio):
    yield [c["titulo"] for c in columnas]
    for r in queryset.iterator(chunk_size=2000):
        yield [_valor(c["nombre"], r, servicio) for c in columnas]


class _Eco:
    """Un "archivo" que devuelve lo que se le escribe: así csv.writer genera texto renglón por renglón."""

    def write(self, texto):
        return texto


def _texto(queryset, columnas, servicio, delimitador):
    escritor = csv.writer(_Eco(), delimiter=delimitador, lineterminator="\r\n",
                          quoting=csv.QUOTE_MINIMAL if delimitador == "," else csv.QUOTE_NONE, escapechar="\\")
    yield "\ufeff"  # BOM: así Excel y el Bloc de notas reconocen UTF-8 (acentos y Ñ)
    for fila in _renglones(queryset, columnas, servicio):
        if delimitador == "\t":  # un tabulador o salto dentro de un dato rompería las columnas
            fila = [str(v).replace("\t", " ").replace("\r", " ").replace("\n", " ") for v in fila]
        yield escritor.writerow(fila)


def respuesta(formato, queryset, columnas, servicio, catalogo):
    nombre = f"catalogo-{catalogo}-{timezone.localtime():%Y%m%d-%H%M}"
    if formato == "portapapeles":
        # Texto con tabuladores, sin BOM ni descarga: el JavaScript lo copia al portapapeles.
        texto = _texto(queryset, columnas, servicio, "\t")
        next(texto)
        return StreamingHttpResponse(texto, content_type="text/plain; charset=utf-8")
    if formato in ("txt", "csv"):
        delimitador, tipo = ("\t", "text/plain") if formato == "txt" else (",", "text/csv")
        r = StreamingHttpResponse(_texto(queryset, columnas, servicio, delimitador), content_type=f"{tipo}; charset=utf-8")
        r["Content-Disposition"] = f'attachment; filename="{nombre}.{formato}"'
        return r

    libro = Workbook(write_only=True)
    hoja = libro.create_sheet(catalogo.title())
    hoja.freeze_panes = "A2"  # encabezados fijos (en write_only se define antes de escribir)
    filas = _renglones(queryset, columnas, servicio)
    encabezado = []
    for titulo in next(filas):
        celda = WriteOnlyCell(hoja, value=titulo)
        celda.font = Font(bold=True)
        encabezado.append(celda)
    hoja.append(encabezado)
    for fila in filas:
        # Todo como texto (el año como número): así Excel no le quita ceros a un código o No. Parte.
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    r = HttpResponse(salida.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r["Content-Disposition"] = f'attachment; filename="{nombre}.xlsx"'
    return r
