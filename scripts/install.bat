@echo off
setlocal
cd /d "%~dp0.."
where python >nul 2>nul || (echo Python 3.11+ no encontrado. Instalalo desde https://www.python.org/ & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" || (echo Se requiere Python 3.11 o superior & exit /b 1)
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || exit /b 1
pip install -r requirements.txt || exit /b 1
python -m playwright install chromium || exit /b 1
echo.
echo Instalacion completa. Ejecuta scripts\run.bat
