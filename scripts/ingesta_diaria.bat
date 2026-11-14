@echo off
REM Ingesta diaria del Radar de Licitaciones (la ejecuta el Programador de tareas de Windows).
REM Deja el resultado de cada ejecucion en data\logs\ingesta_AAAA-MM-DD.txt
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m scripts.ingesta >> "data\logs\ingesta_%date:~-4%-%date:~3,2%-%date:~0,2%.txt" 2>&1
