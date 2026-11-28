from django.contrib import admin

from .models import (ErrorImportacion, HistorialMaterial, Importacion, ImportacionMateriales, ImportacionServicios,
                     MaterialCatalogo, MaterialCentro, ServicioCatalogo)


class MaterialCentroInline(admin.TabularInline):
    model = MaterialCentro
    extra = 0
    readonly_fields = ("agregado",)


class HistorialInline(admin.TabularInline):
    """Historial del material: solo lectura, lo escribe WebDM."""

    model = HistorialMaterial
    fk_name = "material"
    extra = 0
    can_delete = False
    fields = ("fecha", "tipo", "origen", "folio", "centro", "campo", "antes", "despues", "solicitante", "usuario")
    readonly_fields = fields
    ordering = ("fecha", "id")

    def has_add_permission(self, request, obj=None):
        return False


class CatalogoAdminBase(admin.ModelAdmin):
    """Base para el catálogo de materiales y el de servicios: la misma tabla, filtrada por es_servicio.

    SQL de la lista:  SELECT ... FROM catalogo_sap_materialsap WHERE es_servicio = false|true ORDER BY codigo
    """

    es_servicio = False
    exclude = ("es_servicio",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(es_servicio=self.es_servicio)

    def save_model(self, request, obj, form, change):
        obj.es_servicio = self.es_servicio  # lo que se guarde aquí queda en su catálogo
        super().save_model(request, obj, form, change)


@admin.register(MaterialCatalogo)
class MaterialCatalogoAdmin(CatalogoAdminBase):
    list_display = ("codigo", "descripcion", "tipo_material", "umb", "grupo_articulos", "origen", "folio_origen")
    list_filter = ("origen", "tipo_material")
    search_fields = ("codigo", "descripcion", "no_parte_original")
    inlines = [MaterialCentroInline, HistorialInline]


@admin.register(ServicioCatalogo)
class ServicioCatalogoAdmin(CatalogoAdminBase):
    es_servicio = True
    list_display = ("codigo", "descripcion", "tipo_material", "umb", "grupo_articulos", "origen", "folio_origen")
    list_filter = ("origen", "tipo_material")
    search_fields = ("codigo", "descripcion")
    # Los servicios no tienen Centro ni datos de refacción.
    exclude = ("es_servicio", "no_parte_original", "ubicacion", "tipo_unidad", "marca", "version", "anio_modelo", "compatibilidad")
    inlines = [HistorialInline]


class ErrorImportacionInline(admin.TabularInline):
    model = ErrorImportacion
    extra = 0
    can_delete = False
    readonly_fields = ("linea", "codigo_sap", "centro", "mensaje")

    def has_add_permission(self, request, obj=None):
        return False


class ImportacionAdminBase(admin.ModelAdmin):
    """Una importación es un registro histórico: nada se edita ni se borra (pedido de Dave, 28-nov-2026)."""

    catalogo = Importacion.Catalogo.MATERIALES
    list_display = ("fecha", "usuario", "nombre_archivo", "importados", "errores")
    readonly_fields = ("catalogo", "usuario", "fecha", "nombre_archivo", "importados", "errores")
    inlines = [ErrorImportacionInline]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(catalogo=self.catalogo)

    def has_add_permission(self, request):
        # Las importaciones se hacen desde su pantalla (fase 4), no a mano aquí.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportacionMateriales)
class ImportacionMaterialesAdmin(ImportacionAdminBase):
    pass


@admin.register(ImportacionServicios)
class ImportacionServiciosAdmin(ImportacionAdminBase):
    catalogo = Importacion.Catalogo.SERVICIOS
