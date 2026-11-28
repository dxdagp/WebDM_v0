"""Catálogo SAP interno (Revisión 3, secciones 9 y 12).

Es una copia de consulta de los materiales y servicios que ya existen en SAP:
qué código tienen y en qué Centros existen. Se llena de dos formas:
1. Importando un TXT exportado de SAP (origen IMPORT).
2. Cuando DM termina una partida de alta en WebDM (origen WEBDM).
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

# Un Código SAP son exactamente 6 dígitos. Lo validamos en dos niveles:
# - Este validador da un mensaje claro en formularios (nivel Django).
# - La CheckConstraint de abajo impide que entre basura aunque alguien
#   inserte directo en la base (nivel PostgreSQL).
validar_codigo_sap = RegexValidator(r"^\d{6}$", "El Código SAP debe tener exactamente 6 dígitos.")


class MaterialSAP(models.Model):
    class Origen(models.TextChoices):
        IMPORT = "IMPORT", "Importado de SAP"
        WEBDM = "WEBDM", "Alta en WebDM"

    codigo = models.CharField("Código SAP", max_length=6, validators=[validar_codigo_sap])
    descripcion = models.CharField("descripción", max_length=40)
    # Texto y no llave foránea: el TXT de SAP puede traer tipos o UMB que aún
    # no existen en los catálogos de WebDM, y la importación no debe fallar por eso.
    tipo_material = models.CharField("tipo de material", max_length=10)
    umb = models.CharField("UMB", max_length=10, blank=True)
    no_parte_original = models.CharField("No. Parte Original", max_length=40, blank=True)
    grupo_articulos = models.CharField("grupo de artículos", max_length=20, blank=True)
    # Resto de los datos del alta AMAT_ZRA (pedido de Dave): el catálogo muestra TODAS las columnas.
    # El TXT de SAP no los trae, así que en lo importado quedan vacíos; el alta en WebDM los llena.
    ubicacion = models.CharField("ubicación de la refacción", max_length=20, blank=True)
    tipo_unidad = models.CharField("tipo de unidad", max_length=40, blank=True)
    marca = models.CharField("marca de la unidad", max_length=40, blank=True)
    version = models.CharField("versión de la unidad", max_length=40, blank=True)
    anio_modelo = models.PositiveSmallIntegerField("año modelo", null=True, blank=True)
    compatibilidad = models.CharField("compatibilidad entre unidades", max_length=40, blank=True)
    es_servicio = models.BooleanField(default=False)
    origen = models.CharField(max_length=10, choices=Origen.choices)
    folio_origen = models.CharField("folio de origen", max_length=30, blank=True, help_text="Solo para origen WEBDM.")
    # La partida que dio de alta el material (origen WEBDM): de ahí salen sus imágenes.
    partida_origen = models.OneToOneField("solicitudes.Partida", on_delete=models.SET_NULL, null=True, blank=True,
                                          related_name="material_catalogo")
    importacion = models.ForeignKey("Importacion", on_delete=models.PROTECT, null=True, blank=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "material SAP"
        verbose_name_plural = "catálogo SAP"
        ordering = ["codigo"]
        constraints = [
            # `codigo ~ '^\d{6}$'` en SQL: el operador ~ de PostgreSQL compara con una expresión regular.
            models.CheckConstraint(condition=Q(codigo__regex=r"^\d{6}$"), name="materialsap_codigo_6_digitos"),
            # Materiales y servicios son catálogos independientes (Dave, 28-nov-2026): el mismo
            # código puede existir como material ZRA y como servicio. Único DENTRO de cada catálogo.
            models.UniqueConstraint(fields=["codigo", "es_servicio"], name="materialsap_codigo_unico_por_catalogo"),
        ]

    def __str__(self):
        return f"{self.codigo} · {self.descripcion}"


class MaterialCentro(models.Model):
    """En qué Centros existe cada material. Código SAP + Centro no se repite (sección 17.1)."""

    material = models.ForeignKey(MaterialSAP, on_delete=models.CASCADE, related_name="centros")
    centro = models.ForeignKey("catalogos.Centro", on_delete=models.PROTECT)
    # Datos que en SAP dependen del Centro (pedido de Dave, 28-nov-2026). Texto, como TIPO y UMB:
    # vienen del TXT de SAP y no deben fallar si aún no existen en los catálogos de WebDM.
    grupo_compras = models.CharField("grupo de compras", max_length=20, blank=True)
    categoria_valoracion = models.CharField("categoría de valoración", max_length=20, blank=True)
    cebe = models.CharField("Centro de Beneficio (CeBe)", max_length=20, blank=True)
    almacen = models.CharField("almacén", max_length=20, blank=True)
    agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "material por Centro"
        verbose_name_plural = "materiales por Centro"
        constraints = [
            models.UniqueConstraint(fields=["material", "centro"], name="material_centro_unico"),
        ]

    def __str__(self):
        return f"{self.material.codigo} en {self.centro.codigo}"


class Importacion(models.Model):
    """Una carga del TXT de SAP: quién, cuándo, qué archivo y el resumen."""

    class Catalogo(models.TextChoices):
        # Pedido de Dave (28-nov-2026): materiales y servicios son catálogos distintos,
        # con su propia importación, consulta y reportes.
        MATERIALES = "MATERIALES", "Materiales"
        SERVICIOS = "SERVICIOS", "Servicios"

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    catalogo = models.CharField("catálogo", max_length=10, choices=Catalogo.choices, default=Catalogo.MATERIALES)
    fecha = models.DateTimeField(auto_now_add=True)
    nombre_archivo = models.CharField(max_length=255)
    importados = models.PositiveIntegerField(default=0)
    errores = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "importación"
        verbose_name_plural = "importaciones"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.nombre_archivo} ({self.fecha:%Y-%m-%d %H:%M})"


class ErrorImportacion(models.Model):
    """Cada renglón del TXT que no se pudo importar, con su motivo."""

    importacion = models.ForeignKey(Importacion, on_delete=models.CASCADE, related_name="detalle_errores")
    linea = models.PositiveIntegerField("línea")
    codigo_sap = models.CharField(max_length=20, blank=True)
    centro = models.CharField(max_length=10, blank=True)
    mensaje = models.CharField(max_length=255)

    class Meta:
        verbose_name = "error de importación"
        verbose_name_plural = "errores de importación"
        ordering = ["linea"]
