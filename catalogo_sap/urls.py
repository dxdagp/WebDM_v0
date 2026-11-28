from django.urls import path

from . import views

app_name = "catalogo_sap"

urlpatterns = [
    path("", views.consulta, name="consulta"),  # = materiales
    path("servicios/", views.consulta, {"catalogo": "servicios"}, name="servicios"),
    path("material/<int:pk>/", views.material, name="material"),
    path("importar/", views.importar_txt, name="importar"),
    path("importar/<int:pk>/", views.importacion, name="importacion"),
]
