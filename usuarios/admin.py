from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import BitacoraSesion, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Reutiliza la pantalla estándar de usuarios y agrega Centros y el cambio obligatorio."""

    fieldsets = UserAdmin.fieldsets + (
        ("Datos de WebDM", {"fields": ("centros", "debe_cambiar_password")}),
    )
    # filter_horizontal dibuja dos listas (disponibles / elegidos) para escoger Centros.
    filter_horizontal = UserAdmin.filter_horizontal + ("centros",)
    list_display = ("username", "first_name", "last_name", "roles", "is_active", "debe_cambiar_password")
    list_filter = UserAdmin.list_filter + ("centros",)

    @admin.display(description="roles")
    def roles(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True))


@admin.register(BitacoraSesion)
class BitacoraSesionAdmin(admin.ModelAdmin):
    """Solo consulta: la bitácora la escribe el sistema, nadie la edita a mano."""

    list_display = ("usuario", "inicio", "fin", "tipo_cierre", "ip")
    list_filter = ("tipo_cierre",)
    search_fields = ("usuario__username", "ip")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
