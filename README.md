# Local Test Workspace

Aplicación local (Python + NiceGUI) para importar contratos OpenAPI/Swagger, definir ambientes, crear casos de prueba API y UI (Playwright), agruparlos en suites encadenadas, programarlos y exportar/importar el trabajo de forma segura.

## Instalación (Windows, con Python 3.11+ ya instalado)

La solución está orientada a **Windows** y asume que **Python 3.11 o superior está instalado y en el PATH** (`python --version`).

```bat
scripts\install.bat      :: crea .venv, instala dependencias y Chromium de Playwright
scripts\run.bat          :: abre http://127.0.0.1:8080
scripts\scheduler.bat    :: (opcional, otra ventana) activa las programaciones
scripts\test.bat         :: ejecuta la batería de pruebas
```

Manual / Linux / macOS:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python run.py                # interfaz web
python run.py --scheduler    # scheduler (un proceso por workspace)
```

**La base SQLite vive dentro del paquete**: `data\workspace.sqlite3` junto a la aplicación (o junto al `.exe`), con `data\evidence\` (capturas/trazas) y `data\logs\`. Mover o copiar la carpeta del paquete mueve también todo el trabajo. Si ya usabas una versión anterior, su base de `~\.local_test_workspace` se copia una sola vez a `data\` (el original no se borra). Variables opcionales: `TEST_WORKSPACE_HOME` (otra carpeta de datos) y `LTW_PORT` (puerto, 8080 por defecto). Si la carpeta del paquete es de solo lectura (p. ej. `Program Files`) se usa el perfil del usuario. Los secretos no van en la base: están en el Administrador de credenciales de Windows.

## Qué incluye

- **Proyectos**: todo recurso pertenece a un proyecto; la interfaz filtra por el proyecto activo.
- **Módulos**: importación OpenAPI 3 / Swagger 2 (JSON/YAML, archivo o URL). Solo `$ref` locales; las externas se rechazan.
- **Espacio de trabajo**: pantalla de tres zonas (historial persistente · petición y respuesta · inspector con body, headers, pruebas, variables, lote y destino). Edita todo a demanda sin cambiar de pantalla y **convierte** lo explorado en casos/suites de regresión.
- **Resumen ejecutivo y reporte de estatus**: semáforo, tendencia, qué falla y desde cuándo; exportable a HTML, PDF, Markdown o JSON. Ver el capítulo 13.4 del manual.
- **Asistente con modelo de lenguaje (opcional)**: tú conectas un modelo local (Ollama, Docker, LM Studio…) o uno en la nube con clave de API; explica fallos y propone casos. Apagado si no hay conexión válida. Ver el capítulo 17.6 del manual.
- **Protocolo para agentes**: especificación de entrada `ltw.spec/1`, informe de fallos `ltw.failure/1` listo para que otro agente vaya al código, CLI (`python run.py --run spec.json`) y API local con token. Ver [AGENTS.md](AGENTS.md).
- **Casos API**: editor visual de headers, query, body, **26 tipos de aserción** (estado, tiempos, headers, JSONPath, tipos, longitud, regex, comparaciones numéricas, JSON Schema, contrato OpenAPI) y extracción de variables para encadenar.
- **Casos UI**: editor visual de pasos (13 acciones, 5 tipos de locator) y **grabador híbrido**: abre Playwright Codegen, importa un subconjunto vía AST (el script nunca se ejecuta) e informa lo no soportado.
- **Suites**: orden editable, política de fallo (continuar/detener), reintentos, variables compartidas, encadenamiento de respuestas y cancelación.
- **Programaciones**: diaria, lunes-viernes, semanal, única e intervalo; zona horaria IANA; política para ejecuciones perdidas; un único scheduler por workspace.
- **Historial y evidencias**: capturas siempre, trazas Playwright en fallos, descarga segura, retención configurable.
- **Importar/Exportar**: workspace, proyecto, suites o casos (con dependencias), vista previa y transacción todo-o-nada.
- **Seguridad**: secretos en el almacén del sistema operativo (Windows Credential Manager), redacción en historial/exportaciones/logs, validación de variables sin resolver, ZIP endurecido, interfaz solo en `127.0.0.1`.
- **Diagnóstico**: paquete ZIP con versiones, conteos y logs sin secretos.

## Documentación

[MANUAL_DE_USUARIO.md](MANUAL_DE_USUARIO.md) ([HTML](docs/manual/MANUAL_DE_USUARIO.html) · [PDF](docs/manual/MANUAL_DE_USUARIO.pdf)) · [USER_GUIDE.md](USER_GUIDE.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) · [TEST_REPORT.md](TEST_REPORT.md) · [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) · [CHANGELOG.md](CHANGELOG.md) · [BACKLOG.md](BACKLOG.md)

## Uso responsable

Ejecuta pruebas solo contra sistemas propios o autorizados. Los destinos pueden ser internos; no expongas esta aplicación a redes no confiables. Las capturas, trazas y respuestas del historial pueden contener datos sensibles: trátalos como información restringida.
