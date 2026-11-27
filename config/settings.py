"""
Configuración principal de WebDM.

Regla de oro: nada secreto ni nada que cambie entre servidores (contraseñas,
modo DEBUG, nombre del servidor) se escribe aquí. Todo eso se lee de variables
de entorno, que en desarrollo vienen del archivo .env (ver .env.example).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# BASE_DIR es la carpeta raíz del proyecto (donde está manage.py).
# __file__ = config/settings.py -> .parent = config/ -> .parent = raíz.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carga el archivo .env (si existe) a las variables de entorno del proceso.
# En producción normalmente no hay .env: systemd define las variables.
load_dotenv(BASE_DIR / ".env")


def env(nombre, default=None, obligatoria=False):
    """Lee una variable de entorno. Si es obligatoria y falta, detiene el arranque
    con un mensaje claro en vez de fallar más adelante de forma confusa."""
    valor = os.environ.get(nombre, default)
    if obligatoria and not valor:
        raise ImproperlyConfigured(f"Falta la variable de entorno {nombre}. Revisa tu archivo .env")
    return valor


def env_bool(nombre, default=False):
    """Convierte textos como 'true', '1', 'si' en True."""
    return str(env(nombre, default)).lower() in ("1", "true", "si", "sí", "yes")


# --- Seguridad básica -------------------------------------------------------

# Clave usada para firmar sesiones y tokens. Debe ser larga, aleatoria y secreta.
SECRET_KEY = env("DJANGO_SECRET_KEY", obligatoria=True)

# DEBUG muestra errores detallados en el navegador. Solo en desarrollo.
DEBUG = env_bool("DJANGO_DEBUG", False)

# Nombres de servidor desde los que se acepta tráfico, separados por coma.
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]


# --- Aplicaciones -----------------------------------------------------------

INSTALLED_APPS = [
    # Aplicaciones que trae Django
    "django.contrib.admin",  # panel de administrador
    "django.contrib.auth",  # usuarios, grupos y permisos
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Aplicaciones de WebDM
    "usuarios",  # usuario propio, Centros autorizados, bitácora de sesiones
    "catalogos",  # Centros, almacenes, UMB, grupos… (catálogos de ADMIN)
    "catalogo_sap",  # catálogo SAP interno e importaciones
    "solicitudes",  # solicitudes, partidas, detalles por flujo y eventos
    "core",  # páginas generales (inicio)
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Carpeta templates/ en la raíz para plantillas compartidas (base.html, login).
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.menu.menu",  # menú lateral según roles (core/menu.py)
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Base de datos: PostgreSQL ----------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "webdm"),
        "USER": env("DB_USER", "webdm"),
        "PASSWORD": env("DB_PASSWORD", obligatoria=True),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        # Reutiliza la conexión hasta 60 s en vez de abrir una por petición.
        "CONN_MAX_AGE": 60,
    }
}


# --- Usuarios ---------------------------------------------------------------

# Usamos un modelo de usuario propio desde el primer día. Cambiarlo después de
# la primera migración es muy difícil; definirlo ahora cuesta casi nada.
AUTH_USER_MODEL = "usuarios.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # Revisión 3, sección 14: mínimo 8 caracteres.
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# La sesión expira tras 30 minutos SIN actividad (Revisión 3, sección 14).
# SESSION_COOKIE_AGE fija la duración; SESSION_SAVE_EVERY_REQUEST reinicia el
# reloj en cada petición, así que solo expira si el usuario deja de usar WebDM.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# A dónde mandar al usuario para iniciar sesión, y a dónde después de entrar o salir.
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "inicio"
LOGOUT_REDIRECT_URL = "login"


# --- Idioma y zona horaria --------------------------------------------------

LANGUAGE_CODE = "es-mx"
TIME_ZONE = env("DJANGO_TIME_ZONE", "America/Mexico_City")
USE_I18N = True
# Las fechas se guardan en UTC en la base y se muestran en TIME_ZONE.
USE_TZ = True


# --- Archivos estáticos y adjuntos ------------------------------------------

# Estáticos = CSS, JS, imágenes del propio portal.
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
# En producción, `collectstatic` copia todo aquí y Nginx lo sirve directamente.
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media = archivos que suben los usuarios (adjuntos de solicitudes).
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
