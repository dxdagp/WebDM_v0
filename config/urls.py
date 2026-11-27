"""Mapa de direcciones (URLs) de WebDM: qué vista atiende cada ruta."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.views import inicio
from usuarios.views import CambiarPassword

urlpatterns = [
    path("", inicio, name="inicio"),
    path("solicitudes/", include("solicitudes.urls")),
    # Vistas de inicio y cierre de sesión que ya trae Django.
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("cuenta/contrasena/", CambiarPassword.as_view(), name="cambiar_password"),
    # Panel de administrador.
    path("admin/", admin.site.urls),
]

# Textos del panel de administrador.
admin.site.site_header = "WebDM · Administración"
admin.site.site_title = "WebDM"
admin.site.index_title = "Datos maestros"
