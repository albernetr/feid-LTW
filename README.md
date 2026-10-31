# Local Test Workspace

![Pruebas](https://github.com/albernetr/feid-LTW/actions/workflows/tests.yml/badge.svg?branch=develop)

Aplicación local (Python + NiceGUI) para importar contratos OpenAPI/Swagger, definir ambientes, crear casos de prueba API y UI (Playwright), agruparlos en suites encadenadas, programarlos y exportar/importar el trabajo de forma segura.

## Qué tan maduro está cada parte

> **Aviso de responsabilidad.** LTW se entrega tal cual, sin garantía (ver [LICENSE](LICENSE), MIT). Pruébalo solo contra sistemas propios o autorizados, revisa siempre lo que una suite o un agente va a hacer antes de confiar en el resultado, y úsalo bajo tu propia responsabilidad.

Esto no es "¿funciona?" — es "¿se probó contra algo real, más de una vez, con fallos reales encontrados y corregidos?". Se muestra también dentro de la aplicación (Inicio).

| Nivel | Qué significa | Incluye |
|---|---|---|
| 🟢 **Estable** | Probado contra sistemas reales, con pruebas automáticas y fallos reales encontrados y corregidos. | Motor de aserciones y ejecución de casos API (26 tipos) · Protocolo para agentes (`ltw.spec`/`ltw.report`/`ltw.failure`) · Importar contratos OpenAPI (archivo, URL, Swagger UI/Redoc/FastAPI) · Exploración automática de contratos · Importar/Exportar del workspace · Seguridad de secretos |
| 🟡 **Beta** | Funciona y tiene pruebas, pero con menos uso real sostenido o un límite conocido que conviene vigilar. | Suites y flujos con enriquecimiento entre componentes · Observador de interfaces (el tap/proxy en vivo, más que aprender del historial) · Resumen ejecutivo y reporte de estatus · Casos UI y el espacio de trabajo unificado · Actualización automática de token por petición HTTP · Componentes creados manualmente sin contrato |
| ⚪ **Experimental** | Usable, pero la calidad depende de algo fuera de LTW (el modelo que conectes) o de un uso que casi no se ha probado. | Asistente con modelo de lenguaje (depende del modelo que conectes) · Programaciones de larga duración sin supervisión · Actualización automática de token por comando del sistema |

Detalle de límites conocidos por sección: [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

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
- **Componentes**: las piezas de la solución (backends, frontends), con o sin contrato. Con contrato: importación OpenAPI 3 / Swagger 2 (JSON/YAML, archivo o URL; solo `$ref` locales, las externas se rechazan) y catálogo de operaciones. Sin contrato: se crean a mano (nombre, tipo, ambiente ligado) — típico de un frontend o un backend sin OpenAPI publicado.
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

El manual de usuario completo (20 capítulos) se genera a partir de [docs/manual/src/](docs/manual/src/) con `python scripts/build_manual.py`, que produce `MANUAL_DE_USUARIO.md` y, en `docs/manual/`, las versiones HTML y PDF — no están versionadas en el repositorio (son binarios reconstruibles); se publican como adjuntos en los [Releases](https://github.com/albernetr/feid-LTW/releases) de este repositorio.

[USER_GUIDE.md](USER_GUIDE.md) · [AGENTS.md](AGENTS.md) · [ARCHITECTURE.md](ARCHITECTURE.md) · [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) · [TEST_REPORT.md](TEST_REPORT.md) · [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) · [CHANGELOG.md](CHANGELOG.md) · [BACKLOG.md](BACKLOG.md)

## Uso responsable

Ejecuta pruebas solo contra sistemas propios o autorizados. Los destinos pueden ser internos; no expongas esta aplicación a redes no confiables. Las capturas, trazas y respuestas del historial pueden contener datos sensibles: trátalos como información restringida.
