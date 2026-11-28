"""Llena el historial con lo que ya había antes de esta migración (28-nov-2026).

- Alta: cada material, con su fecha de creación, su folio o su importación.
- Ampliaciones: cada Centro que no es el del alta. Si una AMPL_ZRA terminada lo agregó,
  se toma su folio; si no, vino de una importación: la última que se hizo hasta 10 minutos antes
  de que se agregara el Centro (los Centros no guardaban su importación).
- Modificaciones y correcciones de código: de la bitácora de las partidas (Evento).

Se puede deshacer: al revertir, borra todo el historial.
"""

from datetime import timedelta

from django.db import migrations


def llenar(apps, schema_editor):
    MaterialSAP = apps.get_model("catalogo_sap", "MaterialSAP")
    MaterialCentro = apps.get_model("catalogo_sap", "MaterialCentro")
    Historial = apps.get_model("catalogo_sap", "HistorialMaterial")
    Partida = apps.get_model("solicitudes", "Partida")
    Evento = apps.get_model("solicitudes", "Evento")
    Importacion = apps.get_model("catalogo_sap", "Importacion")
    importaciones = list(Importacion.objects.order_by("-fecha"))

    def importacion_de(agregado):
        return next((i for i in importaciones if i.fecha <= agregado <= i.fecha + timedelta(minutes=10)), None)
    filas = []

    def de_partida(p):
        return {"origen": "WEBDM", "partida_id": p.pk, "folio": p.solicitud.folio or "", "solicitante_id": p.solicitud.solicitante_id}

    # Quién terminó cada partida (DM): el evento de terminación o de código SAP más reciente.
    atendio = {}
    for e in Evento.objects.filter(tipo__in=["TERMINACION", "CODIGO_SAP"], partida__isnull=False).order_by("fecha"):
        atendio[e.partida_id] = (e.usuario_id, e.fecha)

    centros_alta = {}
    for m in MaterialSAP.objects.select_related("importacion", "partida_origen__solicitud", "partida_origen__centro"):
        primero = m.centros.select_related("centro").order_by("agregado", "id").first()
        fila = {"material_id": m.pk, "tipo": "ALTA", "fecha": m.creado, "usuario_id": m.creado_por_id}
        if m.origen == "WEBDM" and m.partida_origen:
            fila.update(de_partida(m.partida_origen), centro=m.partida_origen.centro.codigo if m.partida_origen.centro else "")
        else:
            fila.update(origen=m.origen, folio=(m.importacion.nombre_archivo[:30] if m.importacion else m.folio_origen),
                        importacion_id=m.importacion_id, centro=primero.centro.codigo if primero else "")
        centros_alta[m.pk] = fila["centro"]
        filas.append(Historial(**fila))

    # Ampliaciones hechas con AMPL_ZRA terminadas, por (material, centro).
    ampl = {}
    for p in Partida.objects.filter(solicitud__flujo="AMPL_ZRA", estado="TERMINADA").select_related(
            "solicitud", "centro", "ampliacion"):
        if p.ampliacion.material_id and p.centro_id:
            ampl[(p.ampliacion.material_id, p.centro.codigo)] = p
    for mc in MaterialCentro.objects.select_related("centro", "material__importacion"):
        if mc.centro.codigo == centros_alta.get(mc.material_id):
            continue
        p = ampl.get((mc.material_id, mc.centro.codigo))
        fila = {"material_id": mc.material_id, "tipo": "AMPLIACION", "fecha": mc.agregado, "centro": mc.centro.codigo}
        if p:
            fila.update(de_partida(p), usuario_id=atendio.get(p.pk, (None,))[0])
        else:
            imp = importacion_de(mc.agregado)
            fila.update(origen="IMPORT", folio=imp.nombre_archivo[:30] if imp else "Importación",
                        importacion_id=imp.pk if imp else None, usuario_id=imp.usuario_id if imp else None)
        filas.append(Historial(**fila))

    # Modificaciones terminadas: el evento de terminación trae campo, antes y después.
    for e in Evento.objects.filter(tipo="TERMINACION", partida__solicitud__flujo__in=["MOD_ZRA", "MOD_ZSA"]).select_related(
            "partida__solicitud", "partida__centro", "partida__modificacion"):
        p, d = e.partida, e.detalle or {}
        if p.modificacion.material_id is None:
            continue
        filas.append(Historial(material_id=p.modificacion.material_id, tipo="MODIFICACION", fecha=e.fecha, usuario_id=e.usuario_id,
                               centro=p.centro.codigo if p.centro else "", campo=d.get("campo", "")[:40],
                               antes=str(d.get("antes", ""))[:100], despues=str(d.get("despues", ""))[:100], **de_partida(p)))

    # Correcciones de Código SAP de altas terminadas.
    for e in Evento.objects.filter(tipo="CORRECCION_CODIGO_SAP").select_related("partida__solicitud"):
        m = MaterialSAP.objects.filter(partida_origen_id=e.partida_id).first()
        if m:
            d = e.detalle or {}
            filas.append(Historial(material_id=m.pk, tipo="CORRECCION_CODIGO", fecha=e.fecha, usuario_id=e.usuario_id,
                                   campo="Código SAP", antes=d.get("antes", ""), despues=d.get("despues", ""), **de_partida(e.partida)))
    Historial.objects.bulk_create(filas, batch_size=1000)


def vaciar(apps, schema_editor):
    apps.get_model("catalogo_sap", "HistorialMaterial").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("catalogo_sap", "0007_historial_material"),
        ("solicitudes", "0006_servicio_tipo_servicio"),
    ]
    operations = [migrations.RunPython(llenar, vaciar)]
