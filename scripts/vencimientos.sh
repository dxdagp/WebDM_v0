#!/bin/sh
# Job diario de vencimientos (fase 4f) para Ubuntu. cron lo corre a la 1:00 AM; ver docs/fase-4f.md.
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
echo "==== $(date)" >> logs/vencimientos.log
.venv/bin/python manage.py vencimientos >> logs/vencimientos.log 2>&1
