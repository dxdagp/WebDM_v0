from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_migrate


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "usuarios"

    def ready(self):
        # ready() corre una vez al arrancar Django: buen lugar para conectar señales.
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        from . import permisos, sesiones
        from .models import Usuario

        user_logged_in.connect(sesiones.al_entrar, dispatch_uid="webdm_bitacora_entrar")
        user_logged_out.connect(sesiones.al_salir, dispatch_uid="webdm_bitacora_salir")
        # El rol ADMIN da acceso al panel (usuarios/permisos.py). Sin `sender`: post_migrate avisa
        # una vez por cada app, y los permisos de cada app se crean en su propio aviso. Así, en el
        # último aviso ya existen todos. La función es rápida y se puede repetir sin problema.
        post_migrate.connect(permisos.sincronizar_permisos_admin, dispatch_uid="webdm_permisos_admin")
        m2m_changed.connect(permisos.al_cambiar_grupos, sender=Usuario.groups.through, dispatch_uid="webdm_staff")
