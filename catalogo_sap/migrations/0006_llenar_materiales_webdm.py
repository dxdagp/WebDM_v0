"""Llena las columnas nuevas de los materiales que ya se habían dado de alta en WebDM.

Antes de la 0005 el alta solo copiaba descripción, tipo, UMB… al catálogo. Aquí se toman
los demás datos de su partida (DetalleAlta con el mismo Código SAP).
"""

from django.db import migrations


def llenar(apps, schema_editor):
    MaterialSAP = apps.get_model("catalogo_sap", "MaterialSAP")
    DetalleAlta = apps.get_model("solicitudes", "DetalleAlta")
    altas = {a.codigo_sap: a for a in DetalleAlta.objects.exclude(codigo_sap=None).select_related("ubicacion", "almacen", "partida")}
    for m in MaterialSAP.objects.filter(origen="WEBDM", es_servicio=False, partida_origen=None):
        alta = altas.get(m.codigo)
        if not alta:
            continue
        m.partida_origen_id = alta.partida_id
        m.ubicacion = alta.ubicacion.codigo if alta.ubicacion else ""
        m.tipo_unidad, m.marca, m.version = alta.tipo_unidad, alta.marca, alta.version
        m.anio_modelo, m.compatibilidad = alta.anio_modelo, alta.compatibilidad
        m.save()
        if alta.almacen:
            m.centros.filter(centro_id=alta.partida.centro_id).update(almacen=alta.almacen.codigo)


class Migration(migrations.Migration):
    dependencies = [
        ("catalogo_sap", "0005_todas_las_columnas"),
    ]
    operations = [migrations.RunPython(llenar, migrations.RunPython.noop)]
