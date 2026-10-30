# Changelog

## 1.0.0 — 2026-10-28

### Añadido
- **Proyectos, Ambientes y Módulos: pruebas exhaustivas y correcciones de robustez** (22 pruebas nuevas):
  - **Proyectos**: nombre duplicado rechazado (`create_project`/`update_project`, sin distinguir mayúsculas/espacios); `delete_project` lista **qué** recursos bloquean el borrado y cuántos, en vez de un mensaje genérico; `adopt_unassigned` ahora incluye `taps` (antes un proyecto con taps huérfanos no se podía borrar nunca). Pantalla rediseñada: tarjetas compactas con los campos de edición plegados por defecto (antes siempre visibles), identificador corto junto al nombre cuando hay duplicados, buscador cuando hay más de 5 proyectos.
  - **Ambientes**: `?edit=<id>` ya no permite editar/reasignar silenciosamente un ambiente de **otro** proyecto al activo (bug de integridad); la URL base rechaza credenciales incrustadas (`http://user:pass@host`) igual que el resto del motor; la URL de interfaz (`ui_base_url`) ahora también se valida; nombre duplicado rechazado dentro del proyecto; borrar un ambiente usado solo por un **paso** de una suite (no por la suite en sí) queda bloqueado, antes dejaba una referencia colgante.
  - **Módulos**: el límite de 10 MB del contrato ahora se aplica también a `import_openapi`/`parse_openapi` directos (antes solo cubría la subida por UI y la descarga por URL); una cadena de referencias `$ref` no cíclica pero muy profunda ya no puede provocar un `RecursionError` sin capturar (límite de 200 niveles con mensaje claro); reimportar el mismo origen o el mismo nombre+versión avisa en vez de duplicar en silencio; si el contrato declara variables de servidor sin resolver (`{entorno}`) se explica por qué no aparece el botón «Crear ambiente»; escribir el nombre de una cabecera de autenticación en la exploración automática sin su valor ahora avisa en vez de descartarse sin aviso.
- **Los «Guardados» del Espacio de trabajo y de Casos UI muestran todos los casos del proyecto, API y UI juntos**: un caso es un caso, sin importar dónde se creó. Clic en un caso del otro tipo navega al espacio donde se edita (`/ui-cases?id=…` o `/workspace?case=…`), con el caso ya cargado. El Historial de cada pantalla se mantuvo separado a propósito (son conceptos distintos: peticiones sueltas del Laboratorio vs. ejecuciones de casos); la vista unificada de **todas** las ejecuciones, con filtro por tipo, sigue siendo `/runs`.
- **Casos UI es ahora un espacio de trabajo, no una lista + un editor separado**: historial/guardados a la izquierda, navegador y pasos al centro, grabador (pegar script) y guardar a la derecha — la misma forma que el Espacio de trabajo de las peticiones de API, con las herramientas adaptadas a construir un caso UI. Cargar un caso guardado o una ejecución del historial sucede sin cambiar de pantalla. El navegador real (solo navegar / navegar y grabar) vive ahí, como controles del centro, en vez de un icono sin texto en el Espacio de trabajo de API.
- `recorder.open_browser`/`launch_codegen` **ya no fallan en silencio**: cuando la navegación falla (protocolo equivocado, servicio caído), la ventana se cierra y antes no se avisaba nada; ahora el error real (p. ej. `net::ERR_SSL_PROTOCOL_ERROR`) se muestra en pantalla.
- **Exploración automática de un contrato** (Módulos → Explorar automáticamente, o `python run.py --explore`): recorre un módulo importado, identifica qué lecturas (GET) son seguras de ejecutar, consigue identificadores reales desde otros listados del propio contrato, arma las aserciones (estado y JSON Schema) **a partir de lo que el contrato declara** y ejecuta de verdad. Si una extracción falla por un error de forma (p. ej. el contrato envuelve el objeto, `$.proceso.id` en vez de `$.id`), se autocorrige probando el siguiente candidato que el propio contrato ofrece, sin tocar aserciones de estado ni ocultar un hallazgo real. Clasifica cada resultado (coincide / necesita revisión / sin ejecutar por falta de datos), con el mismo diagnóstico heurístico del protocolo de agentes. Escribe un informe (`explorer.narrate`) y, si se confirma, guarda los casos en el proyecto (actualiza en el mismo lugar si se repite, no duplica). `diff_module`/`stale_cases` detectan qué casos generados quedan desactualizados cuando el contrato cambia (nuevos parámetros obligatorios, la forma de la respuesta cambió). Solo lecturas: nunca ejecuta POST/PUT/PATCH/DELETE. Módulo `app/explorer.py`.
- **Resumen ejecutivo** (`/resumen`) y **reporte de estatus**: semáforo (verde/ámbar/rojo/sin datos) con las razones, tasa de éxito frente al periodo anterior, ejecuciones por día, flujos con sus últimas ejecuciones, qué falla y **desde cuándo**, casos inestables, más lentos, cambios en interfaces observadas y estado del scheduler. Se exporta como HTML autosuficiente, PDF, Markdown o JSON (`ltw.status/1`), con comentarios del autor y resumen copiable; también por `python run.py --status-report` (código de salida 0/1 para CI). Módulo `app/reporting.py`.
- **Importar un contrato desde una página de Swagger UI / Redoc o un enlace de GitHub**, además del enlace directo: se sigue el contrato enlazado (initializer de Swagger UI, `spec-url`, rutas habituales), se guarda el origen y los servidores relativos o de Swagger 2.0 (`host`/`basePath`) se resuelven; botón **Crear ambiente con esta URL** en el módulo.
- **Asistente opcional con modelo de lenguaje** (Espacio de trabajo → Agente): explica el último fallo y genera casos (`ltw.spec/1`, validada y con una corrección automática) a partir de una descripción y, si se quiere, un contrato OpenAPI. Conexión propia: Ollama, Docker Model Runner, LM Studio u otro servidor local, Azure AI Foundry, OpenAI o Anthropic (protocolos compatible con OpenAI y Anthropic, sin SDK). Clave en el almacén de credenciales, destinos no locales bloqueados hasta permitirlos, vista previa de lo enviado sin secretos, apagado si la conexión no es válida. Módulo `app/llm.py` y modelo simulado `sample_app/fake_llm.py` para pruebas.
- **Manual de usuario completo** ([MANUAL_DE_USUARIO.md](MANUAL_DE_USUARIO.md), HTML y PDF en `docs/manual/`): 20 capítulos con 44 capturas de la aplicación, recetas por perfil, referencia y solución de problemas. Se regenera con `python scripts/build_manual.py`; una prueba lo mantiene sincronizado con el código.
- **Espacio de trabajo** (`/workspace`, reemplaza al Laboratorio; `/lab` redirige): tres zonas redimensionables (historial persistente con búsqueda, estrellas y «solo mías» · petición/respuesta con pestañas Cuerpo, Headers, Pruebas, Diff, Conectividad, Lote · inspector con Params, Headers, Body JSON con editor, Pruebas, Variables, Lote, Guardar y Agente), edición masiva de filas, Ctrl+Enter, generación de pruebas desde la respuesta, actualización de casos guardados con aviso de conflicto, menú compacto.
- **Protocolo para agentes**: `ltw.spec/1` (entrada, con validación por ruta, upsert por nombre e idempotente), `ltw.report/1` y `ltw.failure/1` (qué se envió, esperado vs obtenido, respuesta, diagnóstico heurístico, contrato OpenAPI, cambios observados, `code_hints`, `curl` de reproducción y brief en Markdown), JUnit XML, CLI (`--run`, `--validate`, `--schema`, `--only-failed`, `--base-url`, `--persist`) con códigos de salida, y API local `/agent/v1/*` con token, solo loopback.
- Detalle de ejecución: botón **Brief para agente**. Documento [AGENTS.md](AGENTS.md), esquema y ejemplo en `docs/agent/`.
- Las ejecuciones guardan el tipo de error (`error_type`, `network_error`) y el contexto de suite (`suite_id`, `alias`, `step_index`).
- **Observador de interfaces** (`/observer`): tap/proxy ligero opcional y aprendizaje desde el historial; catálogo por módulo (campos, tipos, obligatoriedad, ejemplos, JSON Schema); línea base y detección de cambios sin aviso (campo nuevo, tipo distinto, requerido ausente, código nuevo); comparación con el contrato OpenAPI; generación de casos de regresión desde una muestra; datos sensibles enmascarados.
- **Flujos entre módulos**: las suites tienen pasos con nombre, ambiente propio por paso y **reglas de enriquecimiento** (agregar/quitar/combinar campos de body, header, query o ruta con datos de pasos anteriores), con vista previa, validación (solo pasos anteriores) y error sin envío si falta un dato. El historial guarda el body/query enviado y las reglas aplicadas.
- Base compartida: aviso de conflicto al editar el mismo registro, espera a otros escritores y modo sin WAL en unidades de red.
- Selector de protocolo (https por defecto / http) en los campos de dirección del Laboratorio; se admite escribir solo el host.
- El Laboratorio ya no exige proyecto: al guardar se elige proyecto existente o nuevo y, opcionalmente, una suite existente a la que agregar casos (con validación de ambiente).
- Locators `first` y `nth` (ejecutor, editor y grabador).
- **Laboratorio** (`/lab`): peticiones ad hoc sin guardar, lote de parámetros → suite de regresión, prueba de conectividad (DNS/TCP/TLS/HTTP) y navegador con o sin grabación convertible en caso UI.
- Aserciones `json_matches` (cuerpo idéntico ignorando campos volátiles, con diferencias legibles) y `body_equals`; sugerencia automática de campos volátiles; esquema JSON inferido.
- Variables propias por caso (`case.variables`) para casos generados desde un lote.
- Proyectos con filtrado de todos los recursos, adopción de recursos heredados y proyectos en el ZIP.
- Aserciones ampliadas (26 tipos) con JSONPath, JSON Schema y validación de contrato OpenAPI; editor visual.
- Extracción de variables y encadenamiento entre casos de una suite.
- Suites: orden editable, política de fallo, reintentos, variables compartidas y cancelación.
- Editor visual de pasos UI (13 acciones, 5 locators), trazas Playwright en fallos y capturas siempre.
- Grabador híbrido (Codegen → AST) con informe de instrucciones no soportadas.
- Programaciones única e intervalo, política de ejecuciones perdidas y bloqueo de scheduler único.
- Secretos en el almacén del sistema operativo (`keyring`), `{{secret:nombre}}` y redacción en historial.
- Validación de variables sin resolver antes de enviar/ejecutar.
- Exportación de workspace/proyecto/suites/casos con dependencias; vista previa e importación transaccional.
- Endurecimiento de ZIP (traversal, enlaces simbólicos, duplicados, ratio, tamaños, ids, tipos).
- Logs JSON estructurados y paquete de diagnóstico sin secretos; retención y descarga segura de evidencias.
- Aplicación de ejemplo `sample_app`, pruebas E2E, pruebas de páginas, scripts de Windows y empaquetado.
- Documentación: ARCHITECTURE, USER_GUIDE, DEVELOPER_GUIDE, TEST_REPORT, KNOWN_LIMITATIONS.

- **Reiniciar workspace** (Importar/Exportar → Zona de peligro, o `python run.py --reset-workspace --yes`): borra la base SQLite y, por defecto, las evidencias, para empezar de cero. Irreversible; en la interfaz exige escribir «REINICIAR» para confirmar y en la CLI el flag `--yes`. Los secretos del Administrador de credenciales no se tocan. `core.reset_workspace()`.

### Cambiado
- La base SQLite, evidencias y logs viven en `data/` **dentro del paquete** (modo portable); migración única y no destructiva desde `~/.local_test_workspace`.
- El ejecutor UI trata `get_by_text/label/placeholder` como Codegen (coincidencia parcial) salvo `exact=True`.
- Interfaz rediseñada: navegación lateral, selector de proyecto en el encabezado, listas con acciones, diálogos de detalle de ejecución, estados vacíos y confirmaciones.
- `run.py --scheduler` reemplaza el uso directo de `scheduler.py` (que sigue funcionando).
- Dependencias: NiceGUI ≥ 3, `jsonschema`, `keyring`; se elimina `apscheduler` (no se usaba).

### Corregido
- Subida de OpenAPI por archivo e importación de ZIP **no funcionaban con NiceGUI 3** (`e.content` ya no existe).
- El ejecutor UI no resolvía URLs absolutas de pasos `navigate` (las concatenaba a la base).
- Un `id` inexistente abría el editor de casos UI vacío como si fuera nuevo.
- Botones de solo icono sin nombre accesible.
- La importación podía dejar datos parciales si fallaba a mitad; ahora es todo-o-nada.

## 0.2 / 0.1
Versiones previas (MVP): importación OpenAPI, casos API, suites básicas, programación diaria/semanal, ZIP.
