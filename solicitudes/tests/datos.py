"""Datos de prueba compartidos de la fase 3: catálogos, usuarios por rol y solicitudes enviadas."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from catalogos.models import (
    Almacen, CategoriaValoracion, Centro, GrupoArticulos, GrupoCompras, TipoMaterial, UbicacionRefaccion, UMB,
)
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image

from solicitudes.models import DetalleAlta, Evento, Flujo, ImagenPartida, Partida, Solicitud


def imagen_png(ancho=40, alto=30, color=(200, 30, 30)):
    """Bytes de un PNG pequeño, hecho en memoria con Pillow."""
    salida = BytesIO()
    Image.new("RGB", (ancho, alto), color).save(salida, format="PNG")
    return salida.getvalue()


def poner_imagen(partida, usuario, orden=1):
    """Una imagen ya guardada (sin pasar por la conversión), para las pruebas que solo la necesitan presente."""
    imagen = ImagenPartida(partida=partida, orden=orden, subida_por=usuario)
    imagen.archivo.save(f"prueba-{partida.pk}-{orden}.png", ContentFile(imagen_png()), save=False)
    imagen.save()
    return imagen


def crear_catalogos():
    c = {}
    c["mttu"] = Centro.objects.create(codigo="MTTU", nombre="MTTU", centro_beneficio="CEBE-MTTU")
    c["meix"] = Centro.objects.create(codigo="MEIX", nombre="MEIX", centro_beneficio="CEBE-MEIX")
    c["almacen"] = Almacen.objects.create(centro=c["mttu"], codigo="RC01", predeterminado=True)
    Almacen.objects.create(centro=c["meix"], codigo="RC01", predeterminado=True)
    c["grupo_compras"] = GrupoCompras.objects.create(centro=c["mttu"], codigo="G01", predeterminado=True)
    c["ubicacion"] = UbicacionRefaccion.objects.create(codigo="MOTOR", descripcion="Motor")
    c["umb"] = UMB.objects.create(codigo="PZA", descripcion="Pieza")
    c["grupo_art"] = GrupoArticulos.objects.create(codigo="GA1", descripcion="Filtros")
    c["tipo"] = TipoMaterial.objects.create(codigo="ZRA", descripcion="Refacciones")
    c["categoria"] = CategoriaValoracion.objects.create(codigo="CV1", descripcion="Refacción", tipo_material=c["tipo"])
    return c


def crear_usuario(nombre, *roles, centros=()):
    usuario = get_user_model().objects.create_user(nombre, password="clave-segura-123")
    for rol in roles:
        usuario.groups.add(Group.objects.get_or_create(name=rol)[0])
    usuario.centros.add(*centros)
    return usuario


def crear_enviada(c, solicitante, n=2, estado=Partida.Estado.EN_VALIDACION, centro=None, folio="AMAT_ZRA-2026-000001",
                  con_imagen=True, **cambios):
    """Una solicitud ya enviada con `n` partidas completas (con 1 imagen cada una) en `estado`."""
    centro = centro or c["mttu"]
    solicitud = Solicitud.objects.create(
        flujo=Flujo.AMAT_ZRA, solicitante=solicitante, folio=folio, estado=Solicitud.Estado.EN_PROCESO
    )
    for i in range(n):
        partida = Partida.objects.create(solicitud=solicitud, numero=10 * (i + 1), centro=centro, estado=estado)
        datos = dict(
            descripcion=f"FILTRO {i}", ubicacion=c["ubicacion"], no_parte_original=f"ABC-{i}", tipo_unidad="TRACTO",
            marca="MARCA", version="V1", anio_modelo=2024, umb=c["umb"], grupo_articulos=c["grupo_art"],
            categoria_valoracion=c["categoria"], tipo_material=c["tipo"], almacen=c["almacen"],
            grupo_compras=c["grupo_compras"],
        )
        datos.update(cambios)
        DetalleAlta.objects.create(partida=partida, **datos)
        if con_imagen:
            poner_imagen(partida, solicitante)
        Evento.objects.create(solicitud=solicitud, partida=partida, usuario=solicitante, tipo=Evento.Tipo.ENVIO,
                              estado_anterior="BORRADOR", estado_nuevo=estado)
    return solicitud
