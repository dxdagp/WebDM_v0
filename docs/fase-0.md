# Fase 0: base del proyecto, paso a paso

Esta fase deja un proyecto Django que arranca, se conecta a PostgreSQL y pide usuario y contraseña. Todavía no hay solicitudes ni folios: esos llegan en las fases 1 y 2. Aquí se explica qué hace cada archivo y cada comando, en el orden en que los usarías en tu propia máquina Ubuntu.

## 1. Instalar lo que necesita el sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip postgresql git
```

- `python3-venv` permite crear **entornos virtuales**: una carpeta con su propio Python y sus propias librerías, separada del Python del sistema. Así WebDM no choca con otros programas del servidor.
- `postgresql` instala el servidor de base de datos. Ubuntu 24.04 trae la versión 16.

## 2. Crear la base de datos y su usuario

```bash
sudo -u postgres psql
```

Esto abre la consola de PostgreSQL como el superusuario `postgres`. Dentro escribe:

```sql
CREATE ROLE webdm LOGIN PASSWORD 'pon-una-contraseña-segura';
CREATE DATABASE webdm OWNER webdm;
ALTER ROLE webdm CREATEDB;
\q
```

- `CREATE ROLE webdm LOGIN` crea un usuario de base de datos que puede conectarse. WebDM nunca usa el superusuario `postgres`; si alguien lograra abusar del portal, solo tendría acceso a su propia base.
- `OWNER webdm` hace a ese usuario dueño de la base, así puede crear tablas.
- `CREATEDB` solo hace falta en desarrollo: las pruebas automáticas crean una base temporal (`test_webdm`) y la borran al terminar. En producción puedes omitirlo.

## 3. Descargar el código y preparar el entorno

```bash
git clone https://github.com/dxdagp/WebDM_v0.git
cd WebDM_v0
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

- `python3 -m venv .venv` crea el entorno virtual en la carpeta `.venv`.
- `source .venv/bin/activate` lo activa: verás `(.venv)` al inicio de la línea. Desde ahí, `python` y `pip` son los del entorno. Hay que activarlo cada vez que abras una terminal nueva.
- `requirements.txt` lista tres librerías: **Django** (el framework), **psycopg** (el conector que permite a Python hablar con PostgreSQL) y **python-dotenv** (lee el archivo `.env`).

## 4. Configurar las variables: el archivo `.env`

```bash
cp .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

Copia la clave que imprime el segundo comando en `DJANGO_SECRET_KEY` y pon la contraseña del paso 2 en `DB_PASSWORD`.

**Por qué un `.env` y no escribir las contraseñas en el código:** el código se sube a GitHub y cualquiera con acceso al repositorio lo vería. `.env` está en `.gitignore`, así que nunca sale de tu máquina. Además, el mismo código sirve en desarrollo y en producción cambiando solo el `.env`.

## 5. Crear las tablas y el primer administrador

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

- `migrate` lee las **migraciones** (archivos que describen cómo crear o cambiar tablas) y las aplica en PostgreSQL. Crea las tablas de usuarios, grupos, permisos y sesiones.
- `createsuperuser` te pide usuario, correo y contraseña del primer administrador.
- `runserver` arranca un servidor de desarrollo en http://127.0.0.1:8000. Al abrirlo te manda al login; después de entrar verás "Hola, …". En http://127.0.0.1:8000/admin/ está el panel de administración. **`runserver` es solo para desarrollo**; en producción usaremos Gunicorn y Nginx (fase 5).

## 6. Correr las pruebas

```bash
python manage.py test
```

Corre las 3 pruebas de `core/tests/test_inicio.py` sobre una base temporal. Deben terminar en `OK`.

---

## Qué hay en cada archivo

```
WebDM_v0/
├── manage.py              # punto de entrada de los comandos (migrate, runserver, test…)
├── requirements.txt       # librerías de Python
├── .env.example           # plantilla de variables; se copia a .env
├── .gitignore             # lo que nunca se sube a GitHub
├── config/                # configuración del proyecto
│   ├── settings.py        # ajustes: base de datos, apps, idioma, seguridad
│   ├── urls.py            # qué vista atiende cada dirección
│   ├── wsgi.py / asgi.py  # puntos de entrada para Gunicorn (producción)
├── usuarios/              # app: modelo de usuario propio
│   ├── models.py
│   ├── admin.py
│   └── migrations/0001_initial.py
├── core/                  # app: páginas generales
│   ├── views.py
│   ├── templates/core/inicio.html
│   └── tests/test_inicio.py
├── templates/             # plantillas compartidas
│   ├── base.html          # esqueleto de todas las páginas
│   └── registration/login.html
└── static/css/webdm.css   # estilos propios
```

Django organiza un proyecto en **apps**: carpetas con una responsabilidad cada una. En la fase 1 agregaremos la app `solicitudes`.

### `config/settings.py`

Lo más importante, de arriba abajo:

1. **`BASE_DIR`**: la carpeta raíz. `Path(__file__)` es la ruta de `settings.py`; subir dos niveles (`.parent.parent`) llega a la raíz. Se usa para armar otras rutas sin escribirlas a mano.
2. **`load_dotenv(BASE_DIR / ".env")`**: carga el `.env` en las variables de entorno del proceso.
3. **`env()`**: una función pequeña que lee una variable. Si es obligatoria y falta, detiene el arranque con un mensaje claro ("Falta la variable DB_PASSWORD"), en vez de que Django falle después con un error confuso.
4. **`DEBUG`**: en `true` Django muestra errores detallados en el navegador. Útil al programar, peligroso en producción porque muestra código y configuración.
5. **`INSTALLED_APPS`**: las apps activas. Las de `django.contrib` vienen con Django (admin, usuarios, sesiones); al final van las nuestras.
6. **`DATABASES`**: el motor `postgresql` y los datos de conexión, todos tomados del `.env`. `CONN_MAX_AGE = 60` reutiliza la conexión 60 segundos en lugar de abrir una nueva en cada petición.
7. **`AUTH_USER_MODEL = "usuarios.Usuario"`**: le dice a Django que nuestro modelo de usuario es el propio. Ver la siguiente sección.
8. **`LANGUAGE_CODE = "es-mx"`** y **`TIME_ZONE`**: el panel sale en español y las fechas se muestran en hora de la Ciudad de México. Con `USE_TZ = True` se guardan en UTC en la base, lo cual evita problemas con horario de verano.
9. **`STATIC_ROOT`** y **`MEDIA_ROOT`**: dónde quedan los archivos del portal (CSS) y los adjuntos que suban los usuarios. En producción Nginx los sirve directamente.

### `usuarios/models.py`

```python
class Usuario(AbstractUser):
    area = models.CharField("área o planta", max_length=100, blank=True)
```

- `AbstractUser` es el usuario completo de Django (usuario, contraseña cifrada, nombre, correo, grupos, permisos). Al heredar de él, `Usuario` tiene todo eso sin escribirlo.
- **Por qué un modelo propio aunque casi no agregue nada:** la documentación de Django recomienda hacerlo antes de la primera migración. Cambiar de modelo de usuario cuando ya hay datos obliga a rehacer tablas y relaciones. Ahora cuesta tres líneas.
- `area` es un ejemplo de campo propio (opcional, `blank=True`). Servirá si después quieres asignar validadores por área o planta.
- `__str__` define cómo se muestra el usuario en listas: su nombre completo, o el usuario si no tiene nombre.

La migración `usuarios/migrations/0001_initial.py` la generó el comando `python manage.py makemigrations usuarios`. No se edita a mano: Django la escribe comparando el modelo con el estado anterior.

### `usuarios/admin.py`

`@admin.register(Usuario)` muestra los usuarios en el panel. `UsuarioAdmin` hereda la pantalla estándar de usuarios (con cambio de contraseña, grupos y permisos) y solo le agrega una sección "Datos de WebDM" con el campo `area`, más columnas y un filtro por área en la lista.

### `config/urls.py`

Cada `path()` une una dirección con una vista:

| Dirección | Vista | Qué hace |
| --- | --- | --- |
| `/` | `inicio` | Página de inicio (requiere sesión) |
| `/login/` | `LoginView` de Django | Formulario de inicio de sesión |
| `/logout/` | `LogoutView` de Django | Cierra la sesión |
| `/admin/` | Panel de administración | Usuarios, grupos y, en la fase 1, tipos de solicitud |

El parámetro `name` permite referirse a la dirección por nombre (`{% url 'inicio' %}`) en vez de escribir la ruta; si la ruta cambia, no hay que buscarla en todo el código.

### `core/views.py`

```python
@login_required
def inicio(request):
    grupos = request.user.groups.values_list("name", flat=True)
    return render(request, "core/inicio.html", {"grupos": grupos})
```

- Una **vista** es una función que recibe la petición (`request`) y devuelve una respuesta.
- `@login_required` es un decorador: antes de ejecutar la función revisa si hay sesión. Si no, redirige a `/login/?next=/`, y después de entrar regresa a donde iba.
- `request.user.groups.values_list("name", flat=True)` trae los nombres de los grupos del usuario. Los grupos serán los roles (Solicitante, Validador, Datos Maestros, Administrador).
- `render` combina la plantilla con esos datos y devuelve el HTML.

### Plantillas

- **`templates/base.html`** es el esqueleto común: carga Bootstrap 5 (estilos listos), dibuja la barra superior y deja un hueco `{% block contenido %}` que cada página llena. El botón "Salir" es un formulario POST porque desde Django 5 cerrar sesión con un simple enlace ya no se permite (evita que un sitio externo te cierre la sesión).
- **`templates/registration/login.html`** es el formulario de login. `LoginView` lo busca en esa ruta por convención. `{% csrf_token %}` agrega un token de seguridad que Django exige en todo formulario POST, contra ataques CSRF.
- **`core/templates/core/inicio.html`** extiende `base.html` (`{% extends %}`) y solo define su contenido.

### `core/tests/test_inicio.py`

Tres pruebas automáticas que confirman lo básico: sin sesión te manda al login, con sesión ves el saludo, y Django usa nuestro modelo de usuario. Cada prueba corre en una base temporal que se borra al terminar, así no tocan tus datos.

---

## Siguiente: fase 1

Modelos `TipoSolicitud`, `CampoDefinicion`, `Solicitud` y compañía, los cuatro grupos de roles creados automáticamente, y el panel para que el administrador dé de alta ZRA y ZSA con sus campos.
