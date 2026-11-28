"""Menú lateral según los roles del usuario (pedido de Dave, 27-nov-2026).

Un *context processor* es una función que Django llama en CADA página y cuyo
resultado queda disponible en todas las plantillas. Así base.html puede
dibujar el menú sin que cada vista lo tenga que mandar.

Cada opción dice qué roles la ven. Si `url` es None, la pantalla aún no existe
y se muestra como "próximamente".
"""

from django.urls import reverse

from solicitudes import bandejas

OPCIONES = [
    # (grupo, etiqueta, nombre de la ruta o None, roles que la ven)
    ("Mi trabajo", "Pendientes de mi atención", "solicitudes:pendientes", {"SOL_MAT", "VAL_MAT", "DM"}),
    ("Mi trabajo", "Mis solicitudes", "solicitudes:mis_solicitudes", {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Crear materiales", "solicitudes:nueva_amat", {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Ampliar a Centro", "solicitudes:nueva_ampl", {"SOL_MAT", "VAL_MAT"}),
    ("Materiales", "Modificar materiales", ("solicitudes:nueva_mod", "materiales"), {"SOL_MAT", "VAL_MAT"}),
    ("Servicios", "Crear servicios", "solicitudes:nueva_aser", {"SOL_MAT", "VAL_MAT"}),
    ("Servicios", "Modificar servicios", ("solicitudes:nueva_mod", "servicios"), {"SOL_MAT", "VAL_MAT"}),
    ("Consulta", "Catálogo de materiales", "catalogo_sap:consulta", {"SOL_MAT", "VAL_MAT", "DM", "ADMIN"}),
    ("Consulta", "Catálogo de servicios", "catalogo_sap:servicios", {"SOL_MAT", "VAL_MAT", "DM", "ADMIN"}),
    ("Administración", "Usuarios, roles y catálogos", "admin:index", {"ADMIN"}),
    ("Administración", "Importar catálogo SAP", "catalogo_sap:importar", {"ADMIN", "DM"}),
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
        # Una ruta con argumento se escribe como tupla: ("solicitudes:nueva_mod", "materiales").
        url = (reverse(ruta[0], args=ruta[1:]) if isinstance(ruta, tuple) else reverse(ruta)) if ruta else None
        grupos.setdefault(grupo, []).append({
            "etiqueta": etiqueta,
            "url": url,
            "activa": False,
            # Contador de pendientes (fase 3): un COUNT por rol en cada página.
            "contador": bandejas.contar(request.user) if ruta == "solicitudes:pendientes" else None,
        })
    # Marca como activa la opción cuya URL coincide más largo con la página actual
    # (así /solicitudes/amat/nueva/ activa "Crear materiales" y no "Mis solicitudes").
    # Un borrador (/solicitudes/mod/materiales/7/) también activa su opción (/solicitudes/mod/materiales/nueva/).
    base = lambda url: url.removesuffix("nueva/")  # noqa: E731
    candidatas = [op for ops in grupos.values() for op in ops if op["url"] and request.path.startswith(base(op["url"]))]
    if candidatas:
        max(candidatas, key=lambda op: len(base(op["url"])))["activa"] = True
    return {"menu_grupos": grupos, "menu_roles": " · ".join(sorted(roles))}
