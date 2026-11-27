"""Bitácora de sesiones y cambio obligatorio de contraseña (Revisión 3, sección 14).

Tres piezas:

1. Señales (signals). Django "avisa" cuando alguien entra (`user_logged_in`) o sale
   (`user_logged_out`). Conectamos una función a cada aviso para escribir la bitácora.
   Se conectan en `usuarios/apps.py`.

2. Cierre por inactividad. Cuando la sesión vence (30 minutos sin usar WebDM) nadie
   avisa: el navegador simplemente deja de mandar peticiones. Por eso, la próxima vez
   que esa persona entra, revisamos sus registros abiertos: si su sesión ya no existe
   o venció, la cerramos como TIMEOUT con la hora de su última actividad.

3. Un middleware: una función por la que pasa CADA petición antes de llegar a la vista.
   Guarda la última actividad y, si el usuario debe cambiar su contraseña, lo manda a
   esa pantalla sin dejarlo usar nada más.
"""

from django.conf import settings
from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .models import BitacoraSesion

T = BitacoraSesion.TipoCierre

# Para no escribir en la base en cada clic, la última actividad se actualiza como máximo una vez por minuto.
CADA_SEGUNDOS = 60


def cerrar_vencidas(usuario):
    """Cierra como TIMEOUT los registros abiertos del usuario cuya sesión ya no está viva."""
    ahora = timezone.now()
    for registro in BitacoraSesion.objects.filter(usuario=usuario, fin__isnull=True):
        viva = Session.objects.filter(session_key=registro.session_key, expire_date__gt=ahora).exists()
        if not viva:
            registro.fin = registro.ultima_actividad or registro.inicio
            registro.tipo_cierre = T.TIMEOUT
            registro.save(update_fields=["fin", "tipo_cierre"])


def invalidar(usuario):
    """ADMIN restableció la contraseña: las sesiones abiertas de ese usuario dejan de valer.

    Django ya las invalida solo (cada sesión guarda un resumen de la contraseña y, si
    cambia, la sesión deja de servir). Aquí lo dejamos anotado en la bitácora.
    """
    BitacoraSesion.objects.filter(usuario=usuario, fin__isnull=True).update(
        fin=timezone.now(), tipo_cierre=T.SESION_INVALIDADA
    )


def al_entrar(sender, request, user, **kwargs):
    cerrar_vencidas(user)
    registro = BitacoraSesion.objects.create(
        usuario=user,
        # REMOTE_ADDR es la IP que ve el servidor. Detrás de Nginx (fase 5) se configurará para que sea la real.
        ip=request.META.get("REMOTE_ADDR") or None,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        session_key=request.session.session_key or "",
        ultima_actividad=timezone.now(),
    )
    request.session["bitacora_id"] = registro.pk


def al_salir(sender, request, user, **kwargs):
    bitacora_id = request.session.get("bitacora_id") if request else None
    if user and bitacora_id:
        BitacoraSesion.objects.filter(pk=bitacora_id, fin__isnull=True).update(
            fin=timezone.now(), tipo_cierre=T.LOGOUT_MANUAL
        )


class SesionMiddleware:
    """Va después de AuthenticationMiddleware en settings.MIDDLEWARE (necesita request.user)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        usuario = request.user
        if usuario.is_authenticated:
            self._registrar_actividad(request)
            if usuario.debe_cambiar_password and not self._permitida(request.path):
                return redirect("cambiar_password")
        return self.get_response(request)

    def _registrar_actividad(self, request):
        ahora = timezone.now().timestamp()
        bitacora_id = request.session.get("bitacora_id")
        if bitacora_id and ahora - request.session.get("actividad", 0) > CADA_SEGUNDOS:
            BitacoraSesion.objects.filter(pk=bitacora_id).update(ultima_actividad=timezone.now())
            request.session["actividad"] = ahora

    @staticmethod
    def _permitida(ruta):
        """Mientras debe cambiar la contraseña, solo puede cambiarla, salir o cargar estilos."""
        return ruta in (reverse("cambiar_password"), reverse("logout")) or ruta.startswith("/" + settings.STATIC_URL)
