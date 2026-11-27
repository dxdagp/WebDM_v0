from django.urls import path

from . import views

# app_name permite nombrar las rutas como "solicitudes:mis_solicitudes".
app_name = "solicitudes"

urlpatterns = [
    path("", views.mis_solicitudes, name="mis_solicitudes"),
    path("amat/nueva/", views.capturar_amat, name="nueva_amat"),
    path("amat/<int:pk>/", views.capturar_amat, name="editar_amat"),
    path("<int:pk>/", views.detalle, name="detalle"),
]
