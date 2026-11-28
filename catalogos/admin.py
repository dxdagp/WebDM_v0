from django.contrib import admin

from . import models


class PorCentroInline(admin.TabularInline):
    """Muestra almacenes, grupos de compras y planificadores dentro de la ficha del Centro."""

    extra = 0
    fields = ("codigo", "descripcion", "predeterminado", "activo")


class AlmacenInline(PorCentroInline):
    model = models.Almacen


class GrupoComprasInline(PorCentroInline):
    model = models.GrupoCompras


class PlanificadorInline(PorCentroInline):
    model = models.Planificador


@admin.register(models.Centro)
class CentroAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "centro_beneficio", "activo")
    list_filter = ("activo",)
    search_fields = ("codigo", "nombre")
    inlines = [AlmacenInline, GrupoComprasInline, PlanificadorInline]


@admin.register(models.UbicacionRefaccion, models.UMB, models.GrupoArticulos)
class CatalogoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "activo")
    list_filter = ("activo",)
    search_fields = ("codigo", "descripcion")


admin.site.register(models.TipoMaterial, CatalogoAdmin)


@admin.register(models.TipoServicio)
class TipoServicioAdmin(CatalogoAdmin):
    list_display = ("codigo", "descripcion", "umb_predeterminada", "activo")


@admin.register(models.CategoriaValoracion)
class CategoriaValoracionAdmin(CatalogoAdmin):
    list_display = ("codigo", "descripcion", "tipo_material", "activo")


@admin.register(models.Almacen, models.GrupoCompras, models.Planificador)
class PorCentroAdmin(admin.ModelAdmin):
    list_display = ("centro", "codigo", "descripcion", "predeterminado", "activo")
    list_filter = ("centro", "predeterminado", "activo")
    search_fields = ("codigo", "descripcion")
