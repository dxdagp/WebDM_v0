"""Imágenes de las partidas de alta de material (Revisión 3, sección 7.3).

- De 1 a 3 por partida. La de mínimo 1 se exige al Enviar, Reenviar y Aprobar.
- Entran JPG/JPEG, PNG o WebP de hasta 10 MB.
- Se guardan SIEMPRE como WebP, con el lado mayor de 1920 px como máximo y sin
  metadatos (EXIF: fecha, modelo de cámara, a veces ¡la ubicación GPS!).
- Quién las edita: SOL_MAT (dueño) en BORRADOR o DEVUELTA_SOL; VAL_MAT de su
  Centro en EN_VALIDACION. Desde EN_DM quedan bloqueadas.
- Se guardan en MEDIA_ROOT (variable DJANGO_MEDIA_ROOT del .env: "ruta configurable").
"""

from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from .flujo import AccionNoPermitida, roles_de
from .models import Evento, ImagenPartida, Partida

E = Partida.Estado
MAX_IMAGENES = 3
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LADO_MAYOR = 1920
FORMATOS = {"JPEG", "PNG", "WEBP"}  # el formato REAL que detecta Pillow, no la extensión del nombre


def puede_editar(usuario, partida):
    """True si `usuario` puede subir o quitar imágenes de `partida` en su estado actual."""
    if partida.solicitud.flujo != "AMAT_ZRA":
        return False
    roles = roles_de(usuario)
    if partida.estado in (E.BORRADOR, E.DEVUELTA_SOL):
        return partida.solicitud.solicitante_id == usuario.pk and bool(roles & {"SOL_MAT", "VAL_MAT"})
    if partida.estado == E.EN_VALIDACION:
        return "VAL_MAT" in roles and usuario.centros.filter(pk=partida.centro_id).exists()
    return False  # EN_DM, TERMINADA, CANCELADA: bloqueadas


def convertir_a_webp(archivo):
    """Revisa y convierte el archivo subido. Devuelve un ContentFile WebP listo para guardar.

    Pasos:
    1. Tamaño: más de 10 MB se rechaza antes de abrirlo.
    2. Image.open lee solo el encabezado; `img.format` dice el formato real del contenido.
       Así un .exe renombrado a .jpg no pasa.
    3. exif_transpose gira la foto según cómo se tomó (los celulares guardan la
       orientación en el EXIF; sin esto, al quitar el EXIF la foto saldría de lado).
    4. thumbnail reduce SIN deformar hasta que el lado mayor mida 1920 px (si ya es menor, no la toca).
    5. Al guardar como WebP no pasamos `exif=`, así que los metadatos no se copian.
    """
    if archivo.size > MAX_BYTES:
        raise AccionNoPermitida(f"«{archivo.name}» pesa más de 10 MB.")
    try:
        img = Image.open(archivo)
        formato = img.format
        img.load()  # aquí se decodifica la imagen completa; si está corrupta, falla
    except (UnidentifiedImageError, OSError):
        raise AccionNoPermitida(f"«{archivo.name}» no es una imagen válida.")
    if formato not in FORMATOS:
        raise AccionNoPermitida(f"«{archivo.name}» es {formato}; solo se aceptan JPG, PNG o WebP.")

    img = ImageOps.exif_transpose(img)
    # WebP admite transparencia (RGBA); cualquier otro modo (P, CMYK, L…) se pasa a RGB o RGBA.
    transparente = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA" if transparente else "RGB")
    img.thumbnail((LADO_MAYOR, LADO_MAYOR))

    salida = BytesIO()
    img.save(salida, format="WEBP", quality=85, method=4)
    return ContentFile(salida.getvalue())


@transaction.atomic
def agregar(usuario, partida, archivos):
    """Agrega una o varias imágenes en los lugares libres (orden 1, 2, 3)."""
    partida = Partida.objects.select_for_update().get(pk=partida.pk)
    if not puede_editar(usuario, partida):
        raise AccionNoPermitida("No puedes cambiar las imágenes de esta partida en su estado actual.")
    ocupados = set(partida.imagenes.values_list("orden", flat=True))
    libres = [o for o in range(1, MAX_IMAGENES + 1) if o not in ocupados]
    if len(archivos) > len(libres):
        raise AccionNoPermitida(f"Máximo {MAX_IMAGENES} imágenes por partida; quedan {len(libres)} lugares.")

    # Primero se convierten TODAS: si una falla, no se guarda ninguna.
    convertidas = [(a.name, convertir_a_webp(a)) for a in archivos]
    for (nombre, contenido), orden in zip(convertidas, libres):
        imagen = ImagenPartida(partida=partida, orden=orden, subida_por=usuario)
        # El nombre en disco no usa el del usuario: así no hay choques ni caracteres raros.
        imagen.archivo.save(f"partida-{partida.pk}-{orden}.webp", contenido, save=False)
        imagen.save()
        _registrar(usuario, partida, "agregada", nombre, orden)
    return len(convertidas)


@transaction.atomic
def quitar(usuario, imagen):
    partida = Partida.objects.select_for_update().get(pk=imagen.partida_id)
    if not puede_editar(usuario, partida):
        raise AccionNoPermitida("No puedes cambiar las imágenes de esta partida en su estado actual.")
    orden = imagen.orden
    archivo = imagen.archivo
    imagen.delete()
    # El archivo se borra del disco solo cuando la transacción se confirma (on_commit):
    # si algo fallara y PostgreSQL deshiciera el DELETE, el archivo seguiría existiendo.
    transaction.on_commit(lambda: archivo.storage.delete(archivo.name))
    _registrar(usuario, partida, "quitada", "", orden)


def _registrar(usuario, partida, que, nombre, orden):
    """Solo se registra si la partida ya entró al flujo: un borrador no deja trazabilidad (Rev. 3)."""
    if partida.estado == E.BORRADOR:
        return
    Evento.objects.create(
        solicitud=partida.solicitud, partida=partida, usuario=usuario, tipo=Evento.Tipo.CAMBIO_CAMPO,
        estado_anterior=partida.estado, estado_nuevo=partida.estado,
        detalle={"campo": "imagenes", "antes": "", "despues": f"imagen {orden} {que} {nombre}".strip()},
    )
