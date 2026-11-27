from django.contrib import admin

from .models import ErrorImportacion, Importacion, MaterialCentro, MaterialSAP


class MaterialCentroInline(admin.TabularInline):
    model = MaterialCentro
    extra = 0
    readonly_fields = ("agregado",)


@admin.register(MaterialSAP)
class MaterialSAPAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "tipo_material", "umb", "es_servicio", "origen", "folio_origen")
    list_filter = ("origen", "es_servicio", "tipo_material")
    search_fields = ("codigo", "descripcion", "no_parte_original")
    inlines = [MaterialCentroInline]


class ErrorImportacionInline(admin.TabularInline):
    model = ErrorImportacion
    extra = 0
    can_delete = False
    readonly_fields = ("linea", "codigo_sap", "centro", "mensaje")


@admin.register(Importacion)
class ImportacionAdmin(admin.ModelAdmin):
    list_display = ("fecha", "usuario", "nombre_archivo", "importados", "errores")
    readonly_fields = ("usuario", "fecha", "nombre_archivo", "importados", "errores")
    inlines = [ErrorImportacionInline]

    def has_add_permission(self, request):
        # Las importaciones se hacen desde su pantalla (fase 4), no a mano aquí.
        return False
