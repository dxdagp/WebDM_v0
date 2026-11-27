# WebDM

Portal de solicitudes para Datos Maestros (SAP ECC): alta y modificación de refacciones automotrices, ampliación de materiales a Centros, y alta y modificación de servicios. Cada solicitud recibe un folio (por ejemplo `AMAT_ZRA-2026-000123`) y sus partidas pasan por validación y Datos Maestros. No se conecta directamente a SAP. El diseño funcional de referencia es el Checkpoint de Diseño Funcional del MVP, Revisión 3.

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
| 1 | Modelo de datos, roles y panel de administrador ([guía](docs/fase-1.md)) | Hecha |
| 2 | Captura tipo Excel de AMAT_ZRA y folios ([guía](docs/fase-2.md)) | Hecha |
| 3 | Flujos, bandejas de VAL_MAT y DM, Código SAP, sesiones ([guía](docs/fase-3.md)) | Hecha |
| 4 | AMPL_ZRA y exportación TXT, modificaciones, servicios, imágenes, importación SAP, duplicados, vencimientos | Pendiente |
| 5 | Despliegue en Ubuntu (Nginx, Gunicorn, systemd) | Pendiente |
