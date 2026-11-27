# Correr WebDM en Windows (desarrollo)

Esta guía instala WebDM en una PC con Windows 10 u 11 para desarrollar y probar. Más adelante el mismo código se lleva a Ubuntu (sección 9). Los comandos son de **PowerShell**: ábrelo con Inicio, escribe "PowerShell" y Enter. No hace falta abrirlo como administrador salvo donde se indica.

> En otras guías verás comandos de Linux (`source .venv/bin/activate`, `cp`). En Windows usa los equivalentes de esta página.

## 1. Instalar los tres programas

| Programa | Dónde | Al instalar |
| --- | --- | --- |
| **Python 3.13** | https://www.python.org/downloads/windows/ | Marca **"Add python.exe to PATH"** en la primera pantalla. |
| **PostgreSQL 16** | https://www.postgresql.org/download/windows/ (instalador de EDB) | Anota la contraseña que te pide para el usuario `postgres`. Puerto 5432. Stack Builder no hace falta. |
| **Git** | https://git-scm.com/download/win | Deja las opciones por omisión. |

Cierra y vuelve a abrir PowerShell, y comprueba:

```powershell
py --version        # Python 3.13.x
git --version
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" --version
```

- `py` es el lanzador de Python para Windows. Si tienes varias versiones, `py -3.13` elige esa.
- `psql` no queda en el PATH; por eso se llama con su ruta completa. `&` le dice a PowerShell "ejecuta este programa" cuando la ruta lleva espacios.

## 2. Crear la base de datos y su usuario

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres
```

Te pide la contraseña de `postgres` del paso 1. Dentro escribe:

```sql
CREATE ROLE webdm LOGIN PASSWORD 'pon-una-contraseña-segura' CREATEDB;
CREATE DATABASE webdm OWNER webdm ENCODING 'UTF8' TEMPLATE template0;
\q
```

- `CREATE ROLE webdm LOGIN` crea el usuario con el que se conecta WebDM. Nunca usa `postgres`: si alguien abusara del portal, solo tocaría su propia base.
- `CREATEDB` permite a las pruebas crear y borrar su base temporal `test_webdm`.
- **`ENCODING 'UTF8' TEMPLATE template0` es importante en Windows.** El instalador suele crear las bases con la codificación del idioma de Windows (WIN1252). Con UTF8 te aseguras de que la Ñ y cualquier carácter se guarden bien, igual que en Ubuntu. `template0` es una plantilla limpia que permite elegir esa codificación.

Si `psql` muestra un aviso de "página de códigos", ignóralo; no afecta a WebDM.

## 3. Descargar el código con Git (no copiando archivos)

Elige una carpeta, por ejemplo `C:\proyectos`:

```powershell
mkdir C:\proyectos
cd C:\proyectos
git clone https://github.com/dxdagp/WebDM_v0.git
cd WebDM_v0
```

**Por qué clonar en lugar de copiar archivos a mano:**

- Te trae **exactamente** lo que está en GitHub, sin olvidar ningún archivo.
- Para recibir las fases siguientes basta con `git pull`; no hay que volver a copiar nada.
- Si cambias algo por error, `git status` te dice qué cambió y `git checkout -- archivo` lo regresa.
- Hay dos cosas que **nunca** se copian entre máquinas, y Git ya las excluye (`.gitignore`): la carpeta `.venv` (es propia de cada sistema operativo) y el archivo `.env` (tiene contraseñas).

## 4. Crear el entorno virtual e instalar las librerías

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

- `py -3.13 -m venv .venv` crea la carpeta `.venv` con un Python solo para WebDM.
- `Activate.ps1` lo activa: verás `(.venv)` al inicio de la línea. **Hay que activarlo cada vez que abras PowerShell** para trabajar en WebDM. (En Linux es `source .venv/bin/activate`.)
- `requirements.txt` instala Django, psycopg (conector a PostgreSQL), python-dotenv (lee `.env`) y Pillow (imágenes). En Windows Django instala además `tzdata`, porque Windows no trae la tabla de zonas horarias que usa `America/Mexico_City`.

**Si `Activate.ps1` da error "la ejecución de scripts está deshabilitada"**, PowerShell bloquea scripts por omisión. Permítelos solo para tu usuario, una sola vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

`RemoteSigned` permite los scripts creados en tu PC y exige firma a los descargados de internet. Responde `S` y vuelve a activar.

## 5. Configurar el archivo `.env`

```powershell
Copy-Item .env.example .env
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
notepad .env
```

En el Bloc de notas:

- Pega la clave que imprimió el segundo comando en `DJANGO_SECRET_KEY=`.
- Pon la contraseña del paso 2 en `DB_PASSWORD=`.
- Lo demás se queda igual. Guarda y cierra.

`.env` guarda los datos que cambian de una máquina a otra. El código es el mismo en Windows y en Ubuntu; solo cambia este archivo.

## 6. Crear las tablas, datos de prueba y arrancar

```powershell
python manage.py migrate
python manage.py datos_demo
python manage.py createsuperuser
python manage.py runserver
```

- `migrate` aplica todas las migraciones: crea las tablas de usuarios, catálogos, catálogo SAP y solicitudes, y los 4 roles (SOL_MAT, VAL_MAT, DM, ADMIN).
- `datos_demo` carga los Centros MTTU y MEIX, sus almacenes y grupos de compras, los catálogos de ejemplo y tres usuarios: `solicitante`, `validador` y `dm`, todos con la contraseña `demo-webdm-2026`.
- `createsuperuser` crea tu administrador (te pide usuario y contraseña; el correo puede ir vacío).
- `runserver` arranca el servidor de desarrollo. Abre **http://127.0.0.1:8000** en el navegador. Para detenerlo, `Ctrl + C`.

Si Windows pregunta si permites a Python usar la red, acepta solo "Redes privadas".

## 7. Correr las pruebas

```powershell
python manage.py test
```

Deben salir las 30 pruebas con `OK`.

## 8. El día a día

Cada vez que vuelvas a trabajar:

```powershell
cd C:\proyectos\WebDM_v0
.\.venv\Scripts\Activate.ps1
git pull                          # trae la fase nueva, si la hay
pip install -r requirements.txt   # por si se agregó alguna librería
python manage.py migrate          # por si hay tablas nuevas
python manage.py runserver
```

## 9. Más adelante: pasar a Ubuntu

No copias la carpeta de Windows. En el servidor:

1. Haces los pasos de [fase-0.md](fase-0.md) (instalar, `git clone`, `.venv`, `.env` nuevo con sus propias contraseñas, `migrate`).
2. Si quieres llevarte los **datos** que capturaste en Windows (no solo el código), los exportas con PostgreSQL:

   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -U webdm -Fc -f webdm.dump webdm
   ```

   Pasas `webdm.dump` al servidor y ahí lo cargas sobre la base vacía con
   `pg_restore -U webdm -d webdm --no-owner webdm.dump` (en lugar de correr `migrate` y `datos_demo`).

El despliegue definitivo (Gunicorn, Nginx, servicio de systemd) es la fase 5.

## Problemas comunes

| Mensaje | Causa y solución |
| --- | --- |
| `'py' no se reconoce…` | Python no quedó en el PATH. Reinstala marcando "Add python.exe to PATH". |
| `password authentication failed for user "webdm"` | `DB_PASSWORD` en `.env` no coincide con la del paso 2. |
| `connection refused … port 5432` | El servicio de PostgreSQL no está corriendo: Inicio, "Servicios", busca `postgresql-x64-16` e inícialo. |
| `UnicodeDecodeError` al conectar | Suele ser un error de contraseña que PostgreSQL reporta en español con otra codificación. Revisa usuario y contraseña del `.env`. |
| `Falta la variable de entorno DJANGO_SECRET_KEY` | No existe `.env` en la carpeta del proyecto, o le falta la clave. |
| La página se ve sin estilos | Bootstrap se carga de internet; revisa tu conexión. |
