@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat || (echo Ejecuta primero scripts\install.bat & exit /b 1)
pip install -r requirements-dev.txt || exit /b 1
if exist dist\LocalTestWorkspace rmdir /s /q dist\LocalTestWorkspace
if exist build rmdir /s /q build
nicegui-pack --onedir --name LocalTestWorkspace --add-data "app\default_spec_templates.json;app" run.py || exit /b 1
echo Ejecutable en dist\LocalTestWorkspace\LocalTestWorkspace.exe  (puerto con LTW_PORT, scheduler con --scheduler)
echo Chromium no se incluye: ejecuta "python -m playwright install chromium" en el equipo destino para casos UI.
echo Nota: ruta de compilacion corta (p. ej. C:\build) evita errores de rutas largas de Windows.
