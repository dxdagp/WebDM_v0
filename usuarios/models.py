from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuario de WebDM.

    Hereda todo lo de un usuario normal de Django (username, contraseña con
    hash, nombre, correo, grupos, permisos). Los ROLES son grupos de Django
    (SOL_MAT, VAL_MAT, DM, ADMIN): dicen QUÉ puede hacer. Los CENTROS
    autorizados dicen DÓNDE, y aplican a todos sus roles (Revisión 3, sección 4).
    """

    centros = models.ManyToManyField(
        "catalogos.Centro",
        blank=True,
        related_name="usuarios",
        verbose_name="Centros autorizados",
    )
    # Se activa cuando ADMIN restablece la contraseña: al entrar, el usuario
    # debe cambiarla antes de hacer cualquier otra cosa.
    debe_cambiar_password = models.BooleanField("debe cambiar contraseña", default=False)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        return self.get_full_name() or self.username

    def tiene_rol(self, rol):
        """True si el usuario pertenece al grupo `rol` (por ejemplo 'VAL_MAT')."""
        return self.groups.filter(name=rol).exists()


class BitacoraSesion(models.Model):
    """Registro de inicio y cierre de sesión (Revisión 3, sección 14)."""

    class TipoCierre(models.TextChoices):
        LOGOUT_MANUAL = "LOGOUT_MANUAL", "Cierre manual"
        TIMEOUT = "TIMEOUT", "Expiró por inactividad"
        SESION_INVALIDADA = "SESION_INVALIDADA", "Sesión invalidada"

    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name="sesiones")
    inicio = models.DateTimeField(auto_now_add=True)
    fin = models.DateTimeField(null=True, blank=True)
    tipo_cierre = models.CharField(max_length=20, choices=TipoCierre.choices, blank=True)
    ip = models.GenericIPAddressField("IP vista por el servidor", null=True, blank=True)
    user_agent = models.TextField(blank=True)
    # Opcional: un navegador normalmente no revela el nombre del equipo.
    nombre_equipo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = "sesión"
        verbose_name_plural = "bitácora de sesiones"
        ordering = ["-inicio"]

    def __str__(self):
        return f"{self.usuario} · {self.inicio:%Y-%m-%d %H:%M}"
