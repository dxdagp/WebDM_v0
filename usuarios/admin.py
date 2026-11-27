from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import sesiones
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

    def user_change_password(self, request, id, form_url=""):
        """Restablecer contraseña (Revisión 3, sección 14).

        Es la pantalla estándar de Django ("Cambiar contraseña" en la ficha del usuario).
        Si la guarda ADMIN para OTRO usuario, ese usuario deberá cambiarla al entrar,
        y sus sesiones abiertas se anotan como SESION_INVALIDADA.
        """
        respuesta = super().user_change_password(request, id, form_url)
        if request.method == "POST" and respuesta.status_code == 302:  # 302 = se guardó y redirige
            usuario = self.get_object(request, id)
            if usuario and usuario.pk != request.user.pk:
                usuario.debe_cambiar_password = True
                usuario.save(update_fields=["debe_cambiar_password"])
                sesiones.invalidar(usuario)
        return respuesta

    @admin.display(description="roles")
    def roles(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True))


@admin.register(BitacoraSesion)
class BitacoraSesionAdmin(admin.ModelAdmin):
    """Solo consulta: la bitácora la escribe el sistema, nadie la edita a mano."""

    list_display = ("usuario", "inicio", "ultima_actividad", "fin", "tipo_cierre", "ip")
    list_filter = ("tipo_cierre", "usuario")
    date_hierarchy = "inicio"
    search_fields = ("usuario__username", "ip")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
