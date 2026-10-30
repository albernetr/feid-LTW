# Guía de desarrollo

## Entorno

```bat
scripts\install.bat
.venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q          :: ~45 pruebas, ~35 s (incluye Chromium real)
```

Las pruebas usan un workspace temporal y un almacén de secretos en memoria (`tests/conftest.py`); nunca tocan tu `~/.local_test_workspace` ni Credential Manager.

## Estructura de pruebas

| Archivo | Cubre |
|---|---|
| `test_core.py`, `test_automation.py` | proyectos, OpenAPI, ZIP básico, ejecución HTTP |
| `test_assertions.py` | JSONPath, catálogo de aserciones, JSON Schema, extracciones |
| `test_security.py` | ZIP malicioso, rollback, secretos, logs, retención, evidencias, recorder |
| `test_e2e.py` | API positiva/negativa, suite encadenada, políticas, UI real, portabilidad, scheduler |
| `test_pages.py` | todas las páginas (simulación NiceGUI), subidas, validaciones |
| `test_agent.py`, `test_workspace.py` | protocolo de agentes (spec, informe, CLI, API) y lógica del espacio de trabajo |
| `test_flow.py`, `test_observer.py` | flujos entre módulos y observador de interfaces |

`sample_app/` es un servidor local (`python -m sample_app.server`) con API (`/health`, `/api/login`, `/api/items`) y UI (`/login`, `/clientes`). `scripts/seed_demo.py` crea un proyecto demo contra él (útil con `TEST_WORKSPACE_HOME` apuntando a una carpeta vacía).

## Manual de usuario

Las fuentes están en `docs/manual/src/*.md` y las capturas en `docs/manual/img/`. Para regenerar `MANUAL_DE_USUARIO.md`, el HTML autocontenido y el PDF: `python scripts/build_manual.py` (`--no-pdf` omite el PDF). `tests/test_manual.py` falla si el manual cita una imagen o enlace inexistente, o si deja de mencionar una aserción, acción UI, pantalla o variable de entorno que existe en el código: al añadir una función, documenta y regenera.

## Añadir un tipo de aserción

1. Entrada en `core.ASSERTION_TYPES` (etiqueta y campos requeridos).
2. Rama en `core._evaluate`.
3. Validación específica en `core.validate_assertion_rule` si aplica.
4. Prueba en `tests/test_assertions.py`. El editor visual la ofrece automáticamente.

## Añadir una acción UI

`automation.STEP_ACTIONS` (etiqueta + campos), rama en `execute_ui`, y si Codegen la genera, mapeo en `recorder.ACTIONS/EXPECTS`.

## Añadir una página

Módulo en `app/pages/`, `@ui.page(...)`, usar `with frame(titulo, ruta)`, `guard(...)` en handlers y registrar el import en `app/main.py` y la ruta en `common.NAV`.

## Convenciones

- Mensajes al usuario en español; errores de validación como `ValueError`.
- Nada que escriba secretos en SQLite, logs o exportaciones.
- Cualquier cambio de formato del ZIP exige subir `schema_version`.

## Empaquetado

`scripts\build_exe.bat` (PyInstaller vía `nicegui-pack`). Si PyInstaller se queja del paquete `pathlib`, desinstálalo del entorno (`pip uninstall pathlib`) o compila en un venv limpio. `python scripts/make_release.py 1.0.0` genera el ZIP distribuible en `dist/`.
