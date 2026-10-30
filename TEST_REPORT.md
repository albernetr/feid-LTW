# Informe de pruebas

Fecha: 2026-10-28 · Windows 11 · Python 3.13 · NiceGUI 3.18 · Playwright 1.64 (Chromium 156)

## Resultado automatizado

`python -m pytest -q` → **107 pruebas aprobadas, 0 fallos** (~35 s).

| Archivo | Pruebas | Qué demuestra |
|---|---|---|
| test_core.py | 9 | proyectos, filtrado, OpenAPI y `$ref`, ZIP de ida y vuelta con proyectos, ejecución HTTP |
| test_assertions.py | 7 | JSONPath, 26 tipos de aserción (caso positivo y negativo), JSON Schema, JSON inválido sin caída, contrato OpenAPI, extracciones |
| test_security.py | 11 | path traversal, enlaces simbólicos, zip bomb, duplicados, rollback transaccional, vista previa sin escritura, alcance de exportación, secretos fuera de runs/exports, variables sin resolver, logs/diagnóstico sin secretos, retención y descarga segura, recorder sin ejecutar código |
| test_e2e.py | 10 | API positiva/negativa/error de conexión, suite encadenada (login→crear→leer), política de fallo, reintentos, cancelación, **UI con Chromium real** (éxito, fallo con traza, host no autorizado, variables), script grabado ejecutado como caso, portabilidad a un workspace limpio, programaciones única/intervalo/ejecuciones perdidas, scheduler único con lock |
| test_pages.py | 6 | todas las rutas renderizan (con y sin datos), flujo de proyectos, subida OpenAPI y subida/vista previa/confirmación de ZIP con la API de NiceGUI 3, mensajes de validación |
| test_automation.py | 2 | programación diaria y registro de errores de UI |
| test_storage.py | 4 | base dentro del paquete, modo portable, respaldo y migración |
| test_release.py | 1 | el ZIP distribuible no contiene cachés, bases, evidencias ni bloqueos |

## Revisión manual de la interfaz (Chrome, servidor real)

Recorridos: inicio, proyectos, módulos, ambientes/secretos, casos API (listado y editor con pestañas), casos UI (listado y editor de pasos), suites (listado, ejecución), programaciones, historial, importar/exportar.

- Ejecución de la suite «Smoke encadenado» desde la interfaz: 4/4 casos pasaron (3 API encadenados por token + 1 UI en Chromium); el detalle del caso UI muestra pasos y la captura servida por `/evidence/…`.
- Defectos encontrados y corregidos: subida de archivos incompatible con NiceGUI 3 (OpenAPI e importación ZIP); editor UI con `id` inexistente abría un caso vacío; botones de icono sin nombre accesible; `tzdata` ausente en `requirements.txt` (en Windows las zonas IANA fallan sin él).
- No verificado: selección real de archivo con el diálogo del sistema (se probó mediante la API de subida de NiceGUI), diseño en móviles/pantallas pequeñas, otros navegadores, lectores de pantalla.

## Ejecutable (PyInstaller)

Compilado con `nicegui-pack --onedir` en un venv limpio (174 MB): arranca, sirve la interfaz, ejecuta la suite demo completa (incluido el caso UI con el Chromium instalado en el equipo) y el modo `--scheduler` rechaza una segunda instancia.
Problemas hallados y resueltos: Playwright congelado buscaba Chromium dentro del bundle (ahora usa la caché estándar `ms-playwright`); `tzdata` no estaba declarado.
No validado: instalación en un Windows limpio sin Python ni Chromium, firma/antivirus, `install.bat` de principio a fin.

## Grabador Codegen — sesión interactiva real

Se lanzó `python -m playwright codegen` (ventana real de Chromium + Inspector) sobre `sample_app/login` y se grabó un inicio de sesión (clic y escritura en Usuario, Tab, contraseña, Enter) manejando el escritorio de Windows. La salida real se guardó como `tests/fixtures/codegen_login_real.py.txt`; `test_real_codegen_recording_imports_and_runs` la importa (6 pasos, 0 no soportados) y la ejecuta con éxito en Chromium.
Hallazgos: una primera grabación con clics imprecisos produjo `page.locator("html").click()`, que el importador **reporta como no soportado** (comportamiento correcto); Codegen usa coincidencia parcial en `get_by_text`, que el ejecutor trataba como exacta (corregido). La captura manual la condujo Claude por automatización de escritorio, no una persona; la ventana del botón «Abrir grabador» de la interfaz usa el mismo comando.

## Espacio de trabajo y protocolo para agentes

`test_agent.py` (10): esquema válido y **publicado en sincronía** con el código (`docs/agent/`), validación con rutas exactas (estructural primero, luego referencias y flujo), importación **idempotente** (upsert por nombre), ejecución de una spec contra **dos módulos reales** con un caso que falla a propósito → `ltw.report/1` con el `ltw.failure/1` completo (petición enviada, esperado vs obtenido, respuesta, diagnóstico `auth`, `code_hints`, `curl`, brief con sus secciones, JUnit parseable, sin credenciales en el informe), fallo dentro de un flujo con pasos previos y **nada enviado** al módulo siguiente, diagnóstico de red / no encontrado / variable sin resolver / contrato, **CLI** (códigos de salida 0/1/2, archivos `--report/--md/--junit`, reejecución con `--only-failed` tras «arreglar» el servicio, base temporal sin rastro vs `--persist`), y **API HTTP** (token obligatorio y rotable, rechazo de hosts no locales, 422 con rutas, fallo por id en JSON y Markdown).
`test_workspace.py` (6): filas y edición masiva, construcción del caso (ambiente, query, body, errores claros), variables definidas/faltantes, historial persistente (buscar, estrella, recorte, limpiar), diff entre respuestas, ida y vuelta caso ↔ borrador ↔ spec válida.
`test_pages.py` (+5): enviar desde la UI, historial sin guardar nada, guardar creando proyecto, errores visibles, recarga y búsqueda en el historial, importar una spec desde la pestaña Agente, redirección de `/lab`.
Hallazgos corregidos: una ruta sin ambiente (`/solo/ruta`) se convertía en `https://solo/ruta`; la clasificación de errores de conexión dependía del texto del sistema (en Windows sale en español): ahora usa el tipo de excepción; los títulos de fallo no incluían el nombre del caso.
En navegador (Chromium de Playwright): tres zonas, historial → cargar → enviar, generar pruebas, editar el body en el editor y reenviar con Ctrl+Enter, fallo visible en *Pruebas*, brief del último fallo, lote de 3 filas (200/200/404), pestaña Agente con token y `curl`, menú compacto que se expande al pasar el ratón. Se corrigieron: etiquetas del menú compacto (Tailwind `!important` ganaba a `display:none`) y desborde del inspector con contenido ancho.
No validado: la extensión de Chrome (desconectada), uso con varias personas a la vez sobre una base compartida, ni el `.exe` empaquetado con esta versión.

## Observador de interfaces

`test_observer.py` (12) y 2 de páginas: normalización de rutas, enmascarado de datos sensibles, aprendizaje de formas (tipos, opcionales, JSON Schema validado con `jsonschema`), línea base y los cuatro tipos de cambio (con conteo de repeticiones y aceptación), JSON vs no JSON, comparación con contrato OpenAPI, **tap real contra el servidor de ejemplo** (reenvío fiel de estado/cuerpo, 404, login con token, no-JSON intacto, destino caído → 502 sin romper, tap detenido de verdad), detección de un cambio de contrato simulado, validación de taps (puerto ocupado/repetido), historial como fuente (una sola vez), y caso de regresión generado que **falla cuando el módulo cambia**.
Hallazgos: el tap respondía antes de registrar (condición de carrera: el catálogo podía ir un paso atrás); ahora registra antes de responder. La lista de taps quedaba oculta tras crear uno; ahora siempre se ve.
En navegador (Chromium de Playwright): crear tap desde la UI con protocolo http, iniciarlo, tráfico por el tap, catálogo, fijar línea base, cambio simulado en el módulo → 3 cambios detectados y comparación contra el contrato.
No validado: tap con tráfico de varios consumidores a la vez en carga, destinos https con certificados propios, ni la extensión de Chrome (desconectada).

## Flujos entre módulos y base compartida

`test_flow.py` (11), con **dos servidores independientes** como módulos A y B:
- Login en A → request a B con header `Authorization` y body enriquecidos con la respuesta de A (tipos conservados); B recibe lo esperado, A no se toca y el token no queda guardado.
- Referencia inexistente o paso previo fallido → el paso termina en *Error* y **nada llega a B**.
- Validaciones al guardar (referencia hacia adelante, a sí mismo, alias repetido/ inválido, ambiente de otro proyecto, ruta sin `$`).
- Operaciones: asignar con creación de rutas, índices, quitar, combinar, header, query, ruta con plantilla; no sobrescribe un valor escalar en silencio.
- Vista previa con respuestas registradas (y qué pasos no tienen historial); headers ocultos.
- Exportar/importar un flujo como copia nueva (ids de casos y ambientes por paso remapeados) y ejecutarlo; agregar casos a un flujo conserva sus pasos.
- Conflicto de edición (dos personas, mismo registro) y selección de modo de journal según unidad de red.
Se encontró y corrigió un bug propio: la clave `steps` de los casos UI se confundía con los pasos de flujo en la importación (lo detectó una prueba de páginas ya existente).
Interfaz verificada con Chromium de Playwright (la extensión de Chrome estaba desconectada): editor de pasos, diálogo de enriquecimiento con vista previa, ejecución contra dos módulos y detalle con «petición enviada».
No validado: base SQLite en un recurso de red real con varios usuarios simultáneos (solo la lógica de modo y conflictos).

## Laboratorio

`test_lab.py` (7) y 3 pruebas de página: peticiones sin persistir, entorno desde URL, conectividad por pasos (éxito, puerto cerrado, DNS inexistente), campos volátiles, modos de captura, y el escenario completo **lote → respuestas esperadas → suite → pasa dos veces → cambio simulado del servidor → la suite detecta las filas afectadas**.
En Chrome real: URL parametrizada, 3 filas (200, 200, 404), sugerencia automática de `$.requested_at`, guardado como suite, ejecución OK; tras reiniciar la app de ejemplo con respuesta distinta, 2 filas fallan mostrando el campo y el 404 sigue pasando. El botón **Navegar y grabar** de la pestaña Navegador abrió Codegen real, se grabó un login (manejado por Claude vía escritorio) y se convirtió en caso UI (6 pasos, 0 no soportados).
No validado: **Solo navegar** (no se pulsó), y el lanzamiento de Codegen/«Solo navegar» desde el `.exe` empaquetado (hay una ruta específica para ejecutables que no se ha probado; el `.exe` ya no corresponde a esta versión).

## Prueba con sitios reales (Google y YouTube)

Ejecutada con el ejecutor UI en un workspace temporal (un ambiente por sitio).
- **Google**: la búsqueda cargó la página de detección de tráfico automatizado («unusual traffic»). El caso marcó *Pasó* (solo verificaba la URL): **falso positivo del caso**, no del sitio. No se reintentó ni se intentó evadir la verificación.
- **YouTube**: dos búsquedas (Bohemian Rhapsody Queen, Imagine John Lennon). Una primera versión del caso (solo `assert_url`) «pasó» con la página aún en el cuadro de sugerencias; se reforzó esperando el primer enlace del resultado (requirió locators `first`) y verificando que no aparece el aviso de bloqueo: 11 pasos OK y la captura muestra los resultados de «Imagine».
- No se reprodujeron canciones (solo búsqueda). Las pruebas automáticas no dependen de internet.

## Almacenamiento en el paquete

`test_storage.py` (4 pruebas): ruta por defecto `<paquete>/data`, modo congelado junto al `.exe`, sustitución por `TEST_WORKSPACE_HOME`, respaldo si el paquete es de solo lectura, y migración única sin borrar ni sobrescribir.

## No cubierto

Linux/macOS; el botón «Abrir grabador» de la UI no se pulsó (se probó el mismo comando por separado); cargas grandes; scheduler como proceso de larga duración durante horas.
