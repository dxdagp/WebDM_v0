from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuario de WebDM.

    Hereda todo lo de un usuario normal de Django (username, contraseña,
    nombre, correo, grupos, permisos). Lo declaramos como modelo propio para
    poder agregar campos después sin migraciones dolorosas.
    """

    # Ejemplo de campo propio: el área o planta del usuario. Es opcional
    # (blank=True) y servirá más adelante para filtrar bandejas.
    area = models.CharField("área o planta", max_length=100, blank=True)

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def __str__(self):
        # Cómo se muestra el usuario en listas y en el panel de administrador.
        return self.get_full_name() or self.username
