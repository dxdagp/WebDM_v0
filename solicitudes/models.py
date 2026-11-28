"""Solicitudes, partidas y su trazabilidad (Revisión 3, secciones 7 a 11, 15 y 16).

Estructura:

    Solicitud (cabecera: flujo, folio, solicitante)
      └── Partida (10, 20, 30…: estado propio, Centro)
            ├── un detalle según el flujo: DetalleAlta | DetalleAmpliacion
            │                              | DetalleModificacion | DetalleServicio
            ├── ImagenPartida (1 a 3, solo altas de material)
            └── Evento (bitácora: envíos, aprobaciones, devoluciones…)

Por qué una tabla Partida común + un detalle por flujo:
las bandejas, los vencimientos y la bitácora trabajan con Partida sin
importar el flujo, mientras que cada flujo guarda solo sus propios campos.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from catalogo_sap.models import validar_codigo_sap


class Flujo(models.TextChoices):
    """Los cinco flujos del MVP. El valor es también el prefijo del folio."""

    AMAT_ZRA = "AMAT_ZRA", "Alta de refacciones automotrices"
    AMPL_ZRA = "AMPL_ZRA", "Ampliación de material a Centro"
    MOD_ZRA = "MOD_ZRA", "Modificación de materiales"
    ASER_ZSA = "ASER_ZSA", "Alta de servicios automotrices"
    MOD_ZSA = "MOD_ZSA", "Modificación de servicios"


class Solicitud(models.Model):
    """Cabecera. Su estado se calcula a partir de sus partidas (sección 11)."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        TERMINADA = "TERMINADA", "Terminada"

    flujo = models.CharField(max_length=10, choices=Flujo.choices)
    # null=True: un borrador todavía no tiene folio. En PostgreSQL varios NULL
    # no chocan con UNIQUE, así que muchos borradores pueden convivir.
    folio = models.CharField(max_length=30, unique=True, null=True, blank=True)
    solicitante = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="solicitudes")
    centro_origen = models.ForeignKey(
        "catalogos.Centro", on_delete=models.PROTECT, null=True, blank=True, verbose_name="Centro de origen"
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    creada = models.DateTimeField(auto_now_add=True)
    enviada = models.DateTimeField(null=True, blank=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "solicitud"
        verbose_name_plural = "solicitudes"
        ordering = ["-creada"]

    def __str__(self):
        return self.folio or f"{self.flujo} (borrador #{self.pk})"


class ContadorFolio(models.Model):
    """Último consecutivo usado por flujo y año (sección 16). Se usa en la fase 2."""

    flujo = models.CharField(max_length=10, choices=Flujo.choices)
    anio = models.PositiveSmallIntegerField("año")
    ultimo = models.PositiveIntegerField("último consecutivo", default=0)

    class Meta:
        verbose_name = "contador de folios"
        verbose_name_plural = "contadores de folios"
        constraints = [models.UniqueConstraint(fields=["flujo", "anio"], name="contador_unico_por_flujo_y_anio")]

    def __str__(self):
        return f"{self.flujo}-{self.anio}: {self.ultimo}"


class Partida(models.Model):
    """Unidad operativa: después del primer envío, cada partida avanza por su cuenta."""

    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        EN_VALIDACION = "EN_VALIDACION", "En validación"
        DEVUELTA_SOL = "DEVUELTA_SOL", "Devuelta al solicitante"
        EN_DM = "EN_DM", "En Datos Maestros"
        TERMINADA = "TERMINADA", "Terminada"
        CANCELADA = "CANCELADA", "Cancelada"
        EXCLUIDA = "EXCLUIDA", "Excluida"  # solo AMPL_ZRA

    solicitud = models.ForeignKey(Solicitud, on_delete=models.CASCADE, related_name="partidas")
    numero = models.PositiveIntegerField("número de partida")
    # Centro de la partida (en AMPL_ZRA, el Centro destino). Define quién la ve.
    centro = models.ForeignKey("catalogos.Centro", on_delete=models.PROTECT, null=True, blank=True)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.BORRADOR)
    # Los 15/30 días de vencimiento se cuentan desde la devolución más reciente.
    ultima_devolucion = models.DateTimeField("última devolución", null=True, blank=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["solicitud", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["solicitud", "numero"], name="partida_numero_unico_en_solicitud"),
            models.CheckConstraint(condition=Q(numero__gt=0), name="partida_numero_positivo"),
        ]

    def __str__(self):
        return f"{self.solicitud} / {self.numero}"


class DetalleAlta(models.Model):
    """Campos de AMAT_ZRA (sección 7.2).

    Casi todo admite vacío (null/blank) porque "Guardar borrador" permite datos
    incompletos. Lo obligatorio se exige al ENVIAR, en la lógica de la fase 3.
    """

    partida = models.OneToOneField(Partida, on_delete=models.CASCADE, primary_key=True, related_name="alta")
    descripcion = models.CharField("descripción técnica", max_length=40, blank=True)
    ubicacion = models.ForeignKey("catalogos.UbicacionRefaccion", on_delete=models.PROTECT, null=True, blank=True)
    no_parte_original = models.CharField("No. Parte Original", max_length=40, blank=True)
    tipo_unidad = models.CharField("tipo de unidad", max_length=40, blank=True)
    marca = models.CharField("marca de la unidad", max_length=40, blank=True)
    version = models.CharField("versión de la unidad", max_length=40, blank=True)
    anio_modelo = models.PositiveSmallIntegerField(
        "año modelo", null=True, blank=True, validators=[MinValueValidator(1900), MaxValueValidator(2100)]
    )
    compatibilidad = models.CharField("compatibilidad entre unidades", max_length=40, blank=True)
    umb = models.ForeignKey("catalogos.UMB", on_delete=models.PROTECT, null=True, blank=True, verbose_name="UMB")
    grupo_articulos = models.ForeignKey("catalogos.GrupoArticulos", on_delete=models.PROTECT, null=True, blank=True)
    categoria_valoracion = models.ForeignKey(
        "catalogos.CategoriaValoracion", on_delete=models.PROTECT, null=True, blank=True
    )
    tipo_material = models.ForeignKey("catalogos.TipoMaterial", on_delete=models.PROTECT, null=True, blank=True)
    almacen = models.ForeignKey("catalogos.Almacen", on_delete=models.PROTECT, null=True, blank=True)
    grupo_compras = models.ForeignKey("catalogos.GrupoCompras", on_delete=models.PROTECT, null=True, blank=True)
    codigo_sap = models.CharField(
        "Código SAP", max_length=6, unique=True, null=True, blank=True, validators=[validar_codigo_sap]
    )

    class Meta:
        verbose_name = "detalle de alta de material"
        verbose_name_plural = "detalles de alta de material"


class DetalleAmpliacion(models.Model):
    """Campos de AMPL_ZRA (sección 10.2). El Centro destino es `partida.centro`."""

    partida = models.OneToOneField(Partida, on_delete=models.CASCADE, primary_key=True, related_name="ampliacion")
    # Lo que el usuario escribió o pegó. `material` es el del catálogo con ese código (se resuelve al guardar).
    codigo_sap = models.CharField("Código SAP", max_length=6, blank=True)
    material = models.ForeignKey("catalogo_sap.MaterialSAP", on_delete=models.PROTECT, null=True, blank=True)
    centro_origen = models.ForeignKey(
        "catalogos.Centro", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    almacen_modelo = models.ForeignKey(
        "catalogos.Almacen", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    almacen_destino = models.ForeignKey(
        "catalogos.Almacen", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    planificador = models.ForeignKey("catalogos.Planificador", on_delete=models.PROTECT, null=True, blank=True)
    grupo_compras = models.ForeignKey("catalogos.GrupoCompras", on_delete=models.PROTECT, null=True, blank=True)
    motivo_exclusion = models.TextField("motivo de exclusión", blank=True)

    class Meta:
        verbose_name = "detalle de ampliación"
        verbose_name_plural = "detalles de ampliación"


class DetalleModificacion(models.Model):
    """MOD_ZRA y MOD_ZSA: un material existente, el dato a cambiar y su valor nuevo."""

    class Campo(models.TextChoices):
        DESCRIPCION = "DESCRIPCION", "Descripción técnica"
        GRUPO_ARTICULOS = "GRUPO_ARTICULOS", "Grupo de artículos"
        UBICACION = "UBICACION", "Ubicación de refacción"
        NO_PARTE = "NO_PARTE", "No. Parte Original"
        TIPO_UNIDAD = "TIPO_UNIDAD", "Tipo de Unidad"
        MARCA = "MARCA", "Marca"
        VERSION = "VERSION", "Versión"
        ANIO_MODELO = "ANIO_MODELO", "Año Modelo"
        COMPATIBILIDAD = "COMPATIBILIDAD", "Compatibilidad"
        # Datos que en SAP dependen del Centro (Dave, 28-nov-2026): piden Centro.
        GRUPO_COMPRAS = "GRUPO_COMPRAS", "Grupo de compras"
        ALMACEN = "ALMACEN", "Almacén"
        CEBE = "CEBE", "CeBe"

    # Servicios solo pueden modificar estos dos (indicación de Dave, 27-nov-2026).
    CAMPOS_SERVICIO = {Campo.DESCRIPCION, Campo.GRUPO_ARTICULOS}
    # Los únicos que se capturan con Centro; los demás son generales del material.
    CAMPOS_POR_CENTRO = {Campo.GRUPO_COMPRAS, Campo.ALMACEN, Campo.CEBE}

    partida = models.OneToOneField(Partida, on_delete=models.CASCADE, primary_key=True, related_name="modificacion")
    # Lo que escribió el usuario; `material` es el del catálogo que le corresponde (igual que en AMPL).
    codigo_sap = models.CharField("Código SAP", max_length=6, blank=True)
    material = models.ForeignKey("catalogo_sap.MaterialSAP", on_delete=models.PROTECT, null=True, blank=True)
    campo = models.CharField("dato a modificar", max_length=20, choices=Campo.choices, blank=True)
    # Foto del catálogo al capturar: así VAL_MAT y DM ven qué cambia, aunque luego cambie el catálogo.
    valor_actual = models.CharField("valor actual", max_length=40, blank=True)
    valor_nuevo = models.CharField("valor nuevo", max_length=40, blank=True)

    class Meta:
        verbose_name = "detalle de modificación"
        verbose_name_plural = "detalles de modificación"


class DetalleServicio(models.Model):
    """ASER_ZSA: solo descripción y grupo de artículos; DM asigna el Código SAP."""

    partida = models.OneToOneField(Partida, on_delete=models.CASCADE, primary_key=True, related_name="servicio")
    descripcion = models.CharField("descripción", max_length=40, blank=True)
    grupo_articulos = models.ForeignKey("catalogos.GrupoArticulos", on_delete=models.PROTECT, null=True, blank=True)
    codigo_sap = models.CharField(
        "Código SAP", max_length=6, unique=True, null=True, blank=True, validators=[validar_codigo_sap]
    )

    class Meta:
        verbose_name = "detalle de alta de servicio"
        verbose_name_plural = "detalles de alta de servicio"


class ImagenPartida(models.Model):
    """De 1 a 3 imágenes por partida de alta de material (sección 7.3)."""

    partida = models.ForeignKey(Partida, on_delete=models.CASCADE, related_name="imagenes")
    orden = models.PositiveSmallIntegerField()
    archivo = models.ImageField(upload_to="imagenes/%Y/%m/")
    subida = models.DateTimeField(auto_now_add=True)
    subida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        verbose_name = "imagen"
        verbose_name_plural = "imágenes"
        ordering = ["partida", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["partida", "orden"], name="imagen_orden_unico_en_partida"),
            # orden solo puede ser 1, 2 o 3: así es imposible guardar una cuarta imagen.
            models.CheckConstraint(condition=Q(orden__gte=1, orden__lte=3), name="imagen_orden_1_a_3"),
        ]


class Evento(models.Model):
    """Bitácora de lo relevante (sección 15). No se registra cada clic."""

    class Tipo(models.TextChoices):
        CREACION = "CREACION", "Creación"
        ENVIO = "ENVIO", "Envío"
        APROBACION = "APROBACION", "Aprobación"
        DEVOLUCION = "DEVOLUCION", "Devolución"
        CANCELACION = "CANCELACION", "Cancelación"
        EXCLUSION = "EXCLUSION", "Exclusión"
        CAMBIO_CAMPO = "CAMBIO_CAMPO", "Cambio de campo"
        CODIGO_SAP = "CODIGO_SAP", "Asignación de Código SAP"
        CORRECCION_CODIGO_SAP = "CORRECCION_CODIGO_SAP", "Corrección de Código SAP"
        TERMINACION = "TERMINACION", "Terminación"
        VENCIMIENTO = "VENCIMIENTO", "Cancelada por vencimiento"

    solicitud = models.ForeignKey(Solicitud, on_delete=models.CASCADE, related_name="eventos")
    partida = models.ForeignKey(Partida, on_delete=models.CASCADE, null=True, blank=True, related_name="eventos")
    # null = lo hizo el sistema (por ejemplo, el job de vencimientos).
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    tipo = models.CharField(max_length=25, choices=Tipo.choices)
    estado_anterior = models.CharField(max_length=15, blank=True)
    estado_nuevo = models.CharField(max_length=15, blank=True)
    motivo = models.TextField(blank=True)
    # Datos extra según el tipo, por ejemplo {"campo": "MARCA", "antes": "X", "despues": "Y"}.
    detalle = models.JSONField(default=dict, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventos"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.solicitud}"
