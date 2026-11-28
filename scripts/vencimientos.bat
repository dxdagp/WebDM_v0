@echo off
rem Job diario de vencimientos (fase 4f). Lo corre el Programador de tareas de Windows a la 1:00 AM.
rem Se ubica en la carpeta del proyecto (la de arriba de scripts\) y deja el resultado en logs\vencimientos.log.
cd /d "%~dp0.."
if not exist logs mkdir logs
echo ==== %date% %time% >> logs\vencimientos.log
.venv\Scripts\python.exe manage.py vencimientos >> logs\vencimientos.log 2>&1
