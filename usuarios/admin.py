from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from . import permisos, sesiones
from .models import BitacoraSesion, Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Reutiliza la pantalla estándar de usuarios y agrega Centros y el cambio obligatorio."""

    # La ficha del usuario muestra solo lo que importa en WebDM. Se quitan las casillas
    # técnicas del panel de Django: "Es staff" se calcula solo a partir del rol ADMIN y los
    # "Permisos de usuario" por tabla no se usan (los da el rol). Ver usuarios/permisos.py.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Datos personales", {"fields": ("first_name", "last_name", "email")}),
        ("Acceso a WebDM", {"fields": ("is_active", "groups", "centros", "debe_cambiar_password")}),
        ("Solo superusuario", {"fields": ("is_superuser",)}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    # filter_horizontal dibuja dos listas (disponibles / elegidos) para escoger Centros.
    filter_horizontal = UserAdmin.filter_horizontal + ("centros",)
    list_display = ("username", "first_name", "last_name", "roles", "is_active", "debe_cambiar_password")
    list_filter = ("is_active", "groups", "centros")

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is not None and not request.user.is_superuser:
            # Un ADMIN no puede hacerse (ni hacer a nadie) superusuario.
            fieldsets = [f for f in fieldsets if f[0] != "Solo superusuario"]
        return fieldsets

    def get_queryset(self, request):
        # Un ADMIN no ve ni edita a los superusuarios (por ejemplo, no puede cambiarles la contraseña).
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(is_superuser=False)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        textos = {
            "groups": "Roles de WebDM. SOL_MAT crea solicitudes; VAL_MAT además valida; DM asigna Código SAP; "
                      "ADMIN entra a este panel.",
            "is_active": "Desmárcalo para impedir que entre, en lugar de borrar al usuario: así se conserva su historia.",
            "is_superuser": "Puede todo en este panel sin importar su rol. Úsalo solo para el responsable del sistema.",
        }
        for campo, texto in textos.items():
            if campo in form.base_fields:
                form.base_fields[campo].help_text = texto
        return form

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Al quitar el último grupo, m2m_changed puede no avisar; se recalcula aquí también.
        permisos.actualizar_staff(form.instance)

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
