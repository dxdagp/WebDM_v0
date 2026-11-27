"""Comando `python manage.py datos_demo`: llena catálogos y usuarios de PRUEBA.

Sirve para practicar en tu máquina sin capturar todo a mano. No lo corras en
producción: los valores son inventados (salvo MTTU y MEIX, que vienen de tu
documento de diseño).

Un comando propio de Django es una clase `Command` en
<app>/management/commands/<nombre>.py con un método `handle`.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogos.models import (
    Almacen, CategoriaValoracion, Centro, GrupoArticulos, GrupoCompras, Planificador, TipoMaterial,
    UbicacionRefaccion, UMB,
)

CLAVE_DEMO = "demo-webdm-2026"


class Command(BaseCommand):
    help = "Crea catálogos y usuarios de prueba (solo para desarrollo)."

    @transaction.atomic
    def handle(self, *args, **opciones):
        # get_or_create: si ya existe no lo duplica, así el comando se puede correr varias veces.
        centros = {}
        for codigo, cebe in [("MTTU", "CEBE-MTTU"), ("MEIX", "CEBE-MEIX")]:
            centros[codigo], _ = Centro.objects.get_or_create(
                codigo=codigo, defaults={"nombre": f"Centro {codigo}", "centro_beneficio": cebe}
            )
            centro = centros[codigo]
            Almacen.objects.get_or_create(centro=centro, codigo="RC01", defaults={"predeterminado": True})
            GrupoCompras.objects.get_or_create(centro=centro, codigo="G01", defaults={"predeterminado": True})
            GrupoCompras.objects.get_or_create(centro=centro, codigo="G02")
            Planificador.objects.get_or_create(centro=centro, codigo="P01", defaults={"predeterminado": True})

        for modelo, valores in [
            (UbicacionRefaccion, [("MOTOR", "Motor"), ("FRENOS", "Frenos"), ("SUSP", "Suspensión")]),
            (UMB, [("PZA", "Pieza"), ("JGO", "Juego"), ("LT", "Litro")]),
            (GrupoArticulos, [("REF01", "Filtros"), ("REF02", "Frenos")]),
        ]:
            for codigo, descripcion in valores:
                modelo.objects.get_or_create(codigo=codigo, defaults={"descripcion": descripcion})

        zra, _ = TipoMaterial.objects.get_or_create(codigo="ZRA", defaults={"descripcion": "Refacciones"})
        CategoriaValoracion.objects.get_or_create(codigo="CV01", defaults={"descripcion": "Refacción nueva", "tipo_material": zra})

        Usuario = get_user_model()
        for username, roles in [("solicitante", ["SOL_MAT"]), ("validador", ["SOL_MAT", "VAL_MAT"]), ("dm", ["DM"])]:
            usuario, creado = Usuario.objects.get_or_create(username=username, defaults={"first_name": username.title()})
            if creado:
                usuario.set_password(CLAVE_DEMO)  # set_password guarda el HASH, nunca el texto
                usuario.save()
            usuario.groups.set(Group.objects.filter(name__in=roles))
            usuario.centros.set(centros.values())

        self.stdout.write(self.style.SUCCESS(
            f"Listo. Usuarios: solicitante, validador y dm, todos con contraseña {CLAVE_DEMO}"
        ))
