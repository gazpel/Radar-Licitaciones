@echo off
REM Abre el panel del Radar de Licitaciones en http://localhost:8000
cd /d "%~dp0.."
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
