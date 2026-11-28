"""Catálogos administrativos de WebDM (Revisión 3, sección 13).

Todos los catálogos comparten una regla: un valor ya usado no se borra, se
desactiva (`activo = False`). Por eso las llaves foráneas que apuntan aquí usan
on_delete=PROTECT: PostgreSQL impedirá borrar un valor que alguna partida usa.
"""

from django.db import models
from django.db.models import Q


class Catalogo(models.Model):
    """Base abstracta: código, descripción y activo/inactivo.

    `abstract = True` significa que Django NO crea una tabla para esta clase;
    solo copia sus campos a cada clase que la hereda.
    """

    codigo = models.CharField("código", max_length=20, unique=True)
    descripcion = models.CharField("descripción", max_length=100)
    activo = models.BooleanField(default=True, help_text="Desmarca para ocultarlo en capturas nuevas sin borrarlo.")

    class Meta:
        abstract = True
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} · {self.descripcion}"


class Centro(models.Model):
    """Centro (planta o CEDIS). Cada Centro tiene exactamente un Centro Beneficio (CeBe)."""

    codigo = models.CharField("código", max_length=4, unique=True, help_text="Ejemplo: MTTU")
    nombre = models.CharField(max_length=100)
    centro_beneficio = models.CharField("Centro Beneficio (CeBe)", max_length=20)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]

    def __str__(self):
        return self.codigo


class UbicacionRefaccion(Catalogo):
    class Meta(Catalogo.Meta):
        verbose_name = "ubicación de refacción"
        verbose_name_plural = "ubicaciones de refacción"


class UMB(Catalogo):
    class Meta(Catalogo.Meta):
        verbose_name = "unidad de medida base"
        verbose_name_plural = "unidades de medida base"


class GrupoArticulos(Catalogo):
    class Meta(Catalogo.Meta):
        verbose_name = "grupo de artículos"
        verbose_name_plural = "grupos de artículos"


class TipoMaterial(Catalogo):
    # Pedido de Dave (28-nov-2026): al crear un servicio se propone la UMB predeterminada de su tipo (ZSA).
    umb_predeterminada = models.ForeignKey(
        UMB, on_delete=models.PROTECT, null=True, blank=True, verbose_name="UMB predeterminada",
        help_text="Se propone al crear servicios de este tipo.",
    )

    class Meta(Catalogo.Meta):
        verbose_name = "tipo de material"
        verbose_name_plural = "tipos de material"


class CategoriaValoracion(Catalogo):
    """Cada categoría determina el Tipo de Material (relación Categoría -> Tipo)."""

    tipo_material = models.ForeignKey(TipoMaterial, on_delete=models.PROTECT, verbose_name="tipo de material")

    class Meta(Catalogo.Meta):
        verbose_name = "categoría de valoración"
        verbose_name_plural = "categorías de valoración"


class PorCentro(models.Model):
    """Base abstracta para catálogos que pertenecen a un Centro y tienen un predeterminado.

    Reglas:
    - El mismo código no se repite dentro de un Centro (sí puede repetirse en otro).
    - Cada Centro tiene como máximo UN registro predeterminado.
    Ambas las protege PostgreSQL con restricciones (ver Meta de cada clase).
    """

    centro = models.ForeignKey(Centro, on_delete=models.PROTECT)
    codigo = models.CharField("código", max_length=20)
    descripcion = models.CharField("descripción", max_length=100, blank=True)
    predeterminado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ["centro__codigo", "codigo"]

    def __str__(self):
        return f"{self.centro.codigo} · {self.codigo}"


def reglas_por_centro(nombre):
    """Genera las dos restricciones de PorCentro con nombres únicos por tabla.

    La segunda es un índice único PARCIAL: solo cuenta las filas donde
    predeterminado = TRUE. Así puede haber muchos no predeterminados, pero
    nunca dos predeterminados en el mismo Centro.
    """
    return [
        models.UniqueConstraint(fields=["centro", "codigo"], name=f"{nombre}_codigo_unico_por_centro"),
        models.UniqueConstraint(
            fields=["centro"], condition=Q(predeterminado=True), name=f"{nombre}_un_predeterminado_por_centro"
        ),
    ]


class Almacen(PorCentro):
    class Meta(PorCentro.Meta):
        verbose_name = "almacén"
        verbose_name_plural = "almacenes"
        constraints = reglas_por_centro("almacen")


class GrupoCompras(PorCentro):
    class Meta(PorCentro.Meta):
        verbose_name = "grupo de compras"
        verbose_name_plural = "grupos de compras"
        constraints = reglas_por_centro("grupocompras")


class Planificador(PorCentro):
    class Meta(PorCentro.Meta):
        verbose_name = "planificador"
        verbose_name_plural = "planificadores"
        constraints = reglas_por_centro("planificador")
