from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Reutiliza la pantalla estándar de usuarios de Django y le agrega el campo `area`."""

    # fieldsets controla las secciones del formulario de edición.
    fieldsets = UserAdmin.fieldsets + (("Datos de WebDM", {"fields": ("area",)}),)
    list_display = ("username", "first_name", "last_name", "email", "area", "is_active")
    list_filter = UserAdmin.list_filter + ("area",)
