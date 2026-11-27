from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required  # si no hay sesión, redirige a LOGIN_URL
def inicio(request):
    """Página de inicio. Por ahora solo confirma quién eres y qué grupos tienes."""
    grupos = request.user.groups.values_list("name", flat=True)
    return render(request, "core/inicio.html", {"grupos": grupos})
