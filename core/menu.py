"""Menú lateral según los roles del usuario (pedido de Dave, 27-nov-2026).

Un *context processor* es una función que Django llama en CADA página y cuyo
resultado queda disponible en todas las plantillas. Así base.html puede
dibujar el menú sin que cada vista lo tenga que mandar.

Cada opción dice qué roles la ven. Si `url` es None, la pantalla aún no existe
y se muestra como "próximamente".
"""

from django.urls import reverse

OPCIONES = [
    # (grupo, etiqueta, nombre de la ruta o None, roles que la ven)
    ("Mi trabajo", "Pendientes de mi atención", None, {"SOL_MAT", "VAL_MAT", "DM"}),
    ("Mi trabajo", "Mis solicitudes", "solicitudes:mis_solicitudes", {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Crear materiales", "solicitudes:nueva_amat", {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Ampliar a Centro", None, {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Modificar materiales", None, {"SOL_MAT", "VAL_MAT"}),
    ("Servicios", "Crear servicios", None, {"SOL_MAT", "VAL_MAT"}),
    ("Servicios", "Modificar servicios", None, {"SOL_MAT", "VAL_MAT"}),
    ("Consulta", "Catálogo SAP", None, {"SOL_MAT", "VAL_MAT", "DM", "ADMIN"}),
    ("Administración", "Usuarios, roles y catálogos", "admin:index", {"ADMIN"}),
    ("Administración", "Importar catálogo SAP", None, {"ADMIN"}),
]


def menu(request):
    if not request.user.is_authenticated:
        return {}
    roles = set(request.user.groups.values_list("name", flat=True))
    if request.user.is_superuser:
        roles.add("ADMIN")

    grupos = {}  # dict conserva el orden de inserción: los grupos salen en el orden de OPCIONES
    for grupo, etiqueta, ruta, visibles_para in OPCIONES:
        if not roles & visibles_para:  # & = intersección de conjuntos: ¿comparte algún rol?
            continue
        url = reverse(ruta) if ruta else None
        grupos.setdefault(grupo, []).append({
            "etiqueta": etiqueta,
            "url": url,
            "activa": False,
        })
    # Marca como activa la opción cuya URL coincide más largo con la página actual
    # (así /solicitudes/amat/nueva/ activa "Crear materiales" y no "Mis solicitudes").
    candidatas = [op for ops in grupos.values() for op in ops if op["url"] and request.path.startswith(op["url"])]
    if candidatas:
        max(candidatas, key=lambda op: len(op["url"]))["activa"] = True
    return {"menu_grupos": grupos, "menu_roles": " · ".join(sorted(roles))}
