"""Panel de solicitudes. En el MVP la operación diaria se hace en las pantallas
de WebDM (fases 2 y 3); aquí ADMIN solo consulta. Por eso casi todo es de solo lectura."""

from django.contrib import admin

from . import models


class SoloLecturaMixin:
    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        """Todo de solo lectura. Así los campos que Django llena solo (auto_now_add, como
        ImagenPartida.subida o Evento.fecha) se pueden listar en `fields` sin el error
        "'subida' cannot be specified ... non-editable field"."""
        # Sin la llave primaria: el ID interno no le dice nada a ADMIN (pedido de Dave, 28-nov-2026).
        return self.fields or [f.name for f in self.model._meta.fields if not f.primary_key]


class PartidaInline(SoloLecturaMixin, admin.TabularInline):
    model = models.Partida
    fields = ("numero", "centro", "estado", "ultima_devolucion")
    show_change_link = True


class EventoInline(SoloLecturaMixin, admin.TabularInline):
    model = models.Evento
    fields = ("fecha", "partida", "tipo", "usuario", "estado_anterior", "estado_nuevo", "motivo")


@admin.register(models.Solicitud)
class SolicitudAdmin(SoloLecturaMixin, admin.ModelAdmin):
    list_display = ("__str__", "flujo", "solicitante", "centro_origen", "estado", "creada", "enviada")
    list_filter = ("flujo", "estado")
    search_fields = ("folio", "solicitante__username")
    inlines = [PartidaInline, EventoInline]


class DetalleInline(SoloLecturaMixin, admin.StackedInline):
    can_delete = False


class DetalleAltaInline(DetalleInline):
    model = models.DetalleAlta


class DetalleAmpliacionInline(DetalleInline):
    model = models.DetalleAmpliacion


class DetalleModificacionInline(DetalleInline):
    model = models.DetalleModificacion


class DetalleServicioInline(DetalleInline):
    model = models.DetalleServicio


class BitacoraPartidaInline(SoloLecturaMixin, admin.TabularInline):
    """La bitácora de UNA partida en su ficha, de la más antigua a la más reciente."""

    model = models.Evento
    fields = ("fecha", "tipo", "quien", "estado_anterior", "estado_nuevo", "motivo", "detalle")
    ordering = ("fecha", "id")
    verbose_name_plural = "bitácora de la partida"
    extra = 0

    @admin.display(description="usuario")
    def quien(self, evento):
        return evento.usuario or "Sistema"  # usuario vacío = lo hizo WebDM (por ejemplo, el job de vencimientos)


class ImagenInline(SoloLecturaMixin, admin.TabularInline):
    model = models.ImagenPartida
    fields = ("orden", "archivo", "subida", "subida_por")


@admin.register(models.Partida)
class PartidaAdmin(SoloLecturaMixin, admin.ModelAdmin):
    list_display = ("__str__", "centro", "estado", "ultima_devolucion")
    list_filter = ("estado", "solicitud__flujo", "centro")
    search_fields = ("solicitud__folio",)

    def get_inlines(self, request, obj):
        """Muestra solo el detalle que corresponde al flujo de la solicitud."""
        por_flujo = {
            models.Flujo.AMAT_ZRA: [DetalleAltaInline, ImagenInline],
            models.Flujo.AMPL_ZRA: [DetalleAmpliacionInline],
            models.Flujo.MOD_ZRA: [DetalleModificacionInline],
            models.Flujo.MOD_ZSA: [DetalleModificacionInline],
            models.Flujo.ASER_ZSA: [DetalleServicioInline],
        }
        return por_flujo.get(obj.solicitud.flujo, []) + [BitacoraPartidaInline] if obj else []


@admin.register(models.ContadorFolio)
class ContadorFolioAdmin(SoloLecturaMixin, admin.ModelAdmin):
    list_display = ("flujo", "anio", "ultimo")
