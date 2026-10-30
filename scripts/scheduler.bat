@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat || (echo Ejecuta primero scripts\install.bat & exit /b 1)
python run.py --scheduler
