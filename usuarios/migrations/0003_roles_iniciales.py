"""Migración de DATOS: crea los cuatro roles como grupos de Django.

Las migraciones normalmente cambian la ESTRUCTURA (tablas, columnas). Esta
inserta FILAS. Así cualquier base nueva (desarrollo, pruebas, producción)
nace con los roles ya creados, sin depender de que alguien los dé de alta a mano.
"""

from django.db import migrations

ROLES = ["SOL_MAT", "VAL_MAT", "DM", "ADMIN"]


def crear_roles(apps, schema_editor):
    # apps.get_model da la versión del modelo tal como estaba en ESTA migración,
    # no la del código actual. Es la forma segura de usar modelos en migraciones.
    Group = apps.get_model("auth", "Group")
    for nombre in ROLES:
        Group.objects.get_or_create(name=nombre)


def borrar_roles(apps, schema_editor):
    """Lo contrario, por si alguien revierte la migración (`migrate usuarios 0002`)."""
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("usuarios", "0002_remove_usuario_area_usuario_centros_and_more"),
    ]

    operations = [migrations.RunPython(crear_roles, borrar_roles)]
