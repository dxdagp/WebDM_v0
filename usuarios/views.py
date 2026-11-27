from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy


class CambiarPassword(auth_views.PasswordChangeView):
    """Pantalla de cambio de contraseña. Se usa por gusto o porque ADMIN la restableció.

    La contraseña no caduca por tiempo (indicación de Dave, 27-nov-2026): solo se pide
    cambiarla después de un restablecimiento.
    """

    template_name = "registration/cambiar_password.html"
    success_url = reverse_lazy("inicio")

    def form_valid(self, form):
        # super() guarda la contraseña nueva y conserva esta sesión abierta (update_session_auth_hash).
        respuesta = super().form_valid(form)
        usuario = form.user
        if usuario.debe_cambiar_password:
            usuario.debe_cambiar_password = False
            usuario.save(update_fields=["debe_cambiar_password"])
        messages.success(self.request, "Contraseña cambiada.")
        return respuesta
