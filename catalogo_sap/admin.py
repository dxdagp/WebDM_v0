from django.contrib import admin

from .models import ErrorImportacion, HistorialMaterial, Importacion, MaterialCentro, MaterialSAP


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


@admin.register(MaterialSAP)
class MaterialSAPAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "tipo_material", "umb", "es_servicio", "origen", "folio_origen")
    list_filter = ("origen", "es_servicio", "tipo_material")
    search_fields = ("codigo", "descripcion", "no_parte_original")
    inlines = [MaterialCentroInline, HistorialInline]


class ErrorImportacionInline(admin.TabularInline):
    model = ErrorImportacion
    extra = 0
    can_delete = False
    readonly_fields = ("linea", "codigo_sap", "centro", "mensaje")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Importacion)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ("fecha", "catalogo", "usuario", "nombre_archivo", "importados", "errores")
    list_filter = ("catalogo",)
    # Una importación es un registro histórico: nada se edita ni se borra (pedido de Dave, 28-nov-2026).
    readonly_fields = ("catalogo", "usuario", "fecha", "nombre_archivo", "importados", "errores")
    inlines = [ErrorImportacionInline]

    def has_add_permission(self, request):
        # Las importaciones se hacen desde su pantalla (fase 4), no a mano aquí.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
