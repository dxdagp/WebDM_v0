# WebDM

Portal de solicitudes de alta de materiales para Datos Maestros (SAP ECC). Cada solicitud recibe un folio (por ejemplo `ZRA_2026_00001`), pasa por validación y Datos Maestros la cierra capturando el número de material SAP. No se conecta directamente a SAP.

**Stack:** Python 3.12+, Django 5.2 LTS, PostgreSQL 16, Ubuntu 24.04 LTS.

## Arranque rápido (desarrollo)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # llena DJANGO_SECRET_KEY y DB_PASSWORD
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

La explicación paso a paso, incluida la creación de la base de datos en PostgreSQL, está en [docs/fase-0.md](docs/fase-0.md).

## Fases

| Fase | Contenido | Estado |
| --- | --- | --- |
| 0 | Proyecto base, PostgreSQL, login | Hecha |
| 1 | Modelos de solicitudes, roles y panel de administrador | Pendiente |
| 2 | Formulario dinámico y folios | Pendiente |
| 3 | Flujo y bandejas | Pendiente |
| 4 | Correo, adjuntos, búsqueda y Excel | Pendiente |
| 5 | Despliegue en Ubuntu (Nginx, Gunicorn, systemd) | Pendiente |
