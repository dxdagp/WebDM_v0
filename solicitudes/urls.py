from django.urls import path

from . import views

# app_name permite nombrar las rutas como "solicitudes:mis_solicitudes".
app_name = "solicitudes"

urlpatterns = [
    path("", views.mis_solicitudes, name="mis_solicitudes"),
    path("amat/nueva/", views.capturar_amat, name="nueva_amat"),
    path("amat/<int:pk>/", views.capturar_amat, name="editar_amat"),
    path("ampl/nueva/", views.capturar_ampl, name="nueva_ampl"),
    path("ampl/<int:pk>/", views.capturar_ampl, name="editar_ampl"),
    path("ampl/material/", views.material_ampl, name="material_ampl"),
    path("<int:pk>/ampliacion-dm/", views.ampliacion_dm, name="ampliacion_dm"),
    path("<int:pk>/", views.detalle, name="detalle"),
    # Fase 3
    path("<int:pk>/corregir/", views.corregir, name="corregir"),
    path("pendientes/", views.pendientes, name="pendientes"),
    path("pendientes/accion/", views.accion_en_bloque, name="accion"),
    path("pendientes/terminar/", views.terminar_dm, name="terminar_dm"),
    path("pendientes/exportar-ampl/", views.exportar_ampl, name="exportar_ampl"),
    path("pendientes/finalizar-ampl/", views.finalizar_ampl, name="finalizar_ampl"),
    path("partida/<int:pk>/", views.partida, name="partida"),
    path("partida/<int:pk>/corregir-codigo/", views.corregir_codigo, name="corregir_codigo"),
    # Fase 4
    path("partida/<int:pk>/imagenes/", views.subir_imagenes, name="subir_imagenes"),
    path("imagen/<int:pk>/", views.ver_imagen, name="ver_imagen"),
    path("imagen/<int:pk>/quitar/", views.quitar_imagen, name="quitar_imagen"),
    path("coincidencias/", views.coincidencias, name="coincidencias"),
]
