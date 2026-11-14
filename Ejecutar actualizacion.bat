@echo off
rem Queda atendiendo el boton "Actualizar" de la app y carga sola cada dia a la hora_diaria (worker\config.toml).
cd /d "%~dp0"
".venv\Scripts\python.exe" worker\actualizar.py --escuchar
