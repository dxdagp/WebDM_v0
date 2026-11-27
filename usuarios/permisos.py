"""El rol ADMIN da acceso al panel de administración (decisión de Dave, 27-nov-2026).

Django tiene su propio sistema de permisos para el panel: por cada tabla hay
cuatro permisos (add, change, delete, view = agregar, modificar, eliminar, ver).
WebDM no los usa para sus pantallas (ahí mandan los roles), pero el panel sí.

Para que nadie tenga que escogerlos casilla por casilla:

1. Al terminar `migrate`, el grupo ADMIN recibe siempre esta lista de permisos.
   Se hace en la señal post_migrate y no en una migración porque los permisos
   se crean justo DESPUÉS de las migraciones: en una base nueva aún no existen.
2. Quien tiene el rol ADMIN queda marcado como "staff" (puede entrar al panel),
   y al quitarle el rol deja de serlo. Lo hace la señal m2m_changed, que avisa
   cuando cambian los grupos de un usuario.

Nada se elimina desde el panel: usuarios y catálogos se DESACTIVAN (campo activo),
así se conserva la historia (Revisión 3: "lo que ya entró deja trazabilidad").
"""

# app, modelo, acciones permitidas
PERMISOS_ADMIN = [
    ("usuarios", "usuario", ["add", "change", "view"]),
    ("usuarios", "bitacorasesion", ["view"]),
    ("auth", "group", ["view"]),  # los roles son fijos: se asignan, no se inventan
    *[("catalogos", m, ["add", "change", "view"]) for m in (
        "centro", "almacen", "grupocompras", "planificador", "ubicacionrefaccion", "umb",
        "grupoarticulos", "tipomaterial", "categoriavaloracion",
    )],
    *[("catalogo_sap", m, ["view"]) for m in ("materialsap", "materialcentro", "importacion", "errorimportacion")],
    *[("solicitudes", m, ["view"]) for m in (
        "solicitud", "partida", "evento", "detallealta", "detalleampliacion", "detallemodificacion",
        "detalleservicio", "imagenpartida", "contadorfolio",
    )],
]


def sincronizar_permisos_admin(sender=None, **kwargs):
    """Deja al grupo ADMIN exactamente con PERMISOS_ADMIN. Se puede correr las veces que sea."""
    from django.contrib.auth.models import Group, Permission

    grupo, _ = Group.objects.get_or_create(name="ADMIN")
    codenames = [(app, f"{accion}_{modelo}") for app, modelo, acciones in PERMISOS_ADMIN for accion in acciones]
    permisos = [
        p for p in Permission.objects.select_related("content_type")
        if (p.content_type.app_label, p.codename) in codenames
    ]
    grupo.permissions.set(permisos)


def actualizar_staff(usuario):
    """Staff = puede entrar al panel. Lo tiene quien es superusuario o tiene el rol ADMIN."""
    staff = usuario.is_superuser or usuario.groups.filter(name="ADMIN").exists()
    if usuario.is_staff != staff:
        usuario.is_staff = staff
        usuario.save(update_fields=["is_staff"])


def al_cambiar_grupos(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in ("post_add", "post_remove", "post_clear"):
        return
    from .models import Usuario

    if not reverse:  # cambiaron los grupos de UN usuario: usuario.groups.add(...)
        actualizar_staff(instance)
    else:  # cambiaron los usuarios de UN grupo: grupo.user_set.add(...)
        for usuario in Usuario.objects.filter(pk__in=pk_set or []):
            actualizar_staff(usuario)
