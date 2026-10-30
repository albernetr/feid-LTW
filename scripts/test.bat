@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat || (echo Ejecuta primero scripts\install.bat & exit /b 1)
pip install -r requirements-dev.txt >nul || exit /b 1
python -m pytest -q %*
