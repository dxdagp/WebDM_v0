from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "usuarios"

    def ready(self):
        # ready() corre una vez al arrancar Django: buen lugar para conectar señales.
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        from . import sesiones

        user_logged_in.connect(sesiones.al_entrar, dispatch_uid="webdm_bitacora_entrar")
        user_logged_out.connect(sesiones.al_salir, dispatch_uid="webdm_bitacora_salir")
