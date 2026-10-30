# Local Test Workspace - Backlog

Estado: implementado; pendientes marcados abajo
Última actualización: 2026-10-28

## Criterios de estado

- `[x]` implementado y validado con una comprobación reproducible (ver TEST_REPORT.md)
- `[~]` parcialmente implementado o con cobertura incompleta
- `[ ]` pendiente

## P0 - Flujos principales

- [x] Proyectos: crear, seleccionar proyecto activo y persistirlo
- [x] Proyectos: editar, eliminar con confirmación y estadísticas; el borrado se bloquea si hay recursos asociados
- [x] Asociar módulos, ambientes, casos, suites y programaciones al proyecto activo; filtrado y validación de coherencia
- [x] Importar OpenAPI/Swagger JSON/YAML y listar operaciones (archivo y URL; la subida por archivo estaba rota en NiceGUI 3 y se corrigió)
- [x] Resolver `$ref` local de forma segura y rechazar/documentar límites externos
- [x] Crear y ejecutar casos API con aserciones ampliadas
- [x] Motor visual de aserciones: headers, tiempo, JSONPath, JSON Schema, comparaciones, contrato OpenAPI
- [x] Casos UI declarativos con Playwright (validado con Chromium real)
- [x] Editor visual de pasos sin depender de JSON
- [x] Grabador híbrido: lanza Codegen, importa un subconjunto mediante AST y reporta instrucciones no soportadas (validado con una sesión real de Codegen; ver TEST_REPORT.md)
- [x] Suites API/UI secuenciales
- [x] Suites: orden editable, políticas de fallo, reintentos, cancelación y variables compartidas
- [x] Encadenamiento declarativo de respuestas entre casos
- [x] Programaciones diaria, semanal y lunes-viernes
- [x] Programación única, intervalos, bloqueo entre instancias y políticas de ejecuciones perdidas
- [x] Historial y capturas UI
- [x] Evidencias: capturas, trazas en fallos, retención y descarga segura
- [x] Exportación/importación ZIP con schedules desactivados
- [x] Exportar/importar proyecto, caso y suite con vista previa y transacción

## P1 - Seguridad y calidad

- [x] Interfaz limitada a loopback por defecto
- [x] Redacción de headers sensibles y de valores de secretos registrados (límite documentado: datos sensibles no registrados en cuerpos de respuesta)
- [x] Secretos en almacenamiento seguro del sistema operativo (`keyring`)
- [x] Validación de variables no resueltas antes de ejecutar
- [x] Protección contra ejecución de código importado (AST, sin `exec`) y cobertura de AST del recorder
- [x] Pruebas de seguridad para ZIP malicioso, límites y rollback transaccional
- [x] Logs estructurados y paquete de diagnóstico sin secretos
- [x] Aplicación local de ejemplo para pruebas API/UI E2E
- [x] Pruebas E2E reales de API positiva, negativa, suite encadenada, UI, portabilidad y scheduler

## P1 - Entrega

- [x] README de instalación y limitaciones
- [x] ARCHITECTURE.md
- [x] USER_GUIDE.md
- [x] DEVELOPER_GUIDE.md
- [x] TEST_REPORT.md
- [x] KNOWN_LIMITATIONS.md
- [x] CHANGELOG.md
- [~] Scripts Windows de instalación, pruebas y ejecución (escritos; `install.bat` completo no ejecutado de principio a fin en un equipo limpio)
- [~] Empaquetado PyInstaller y validación del ejecutable en Windows (ver TEST_REPORT.md)
- [x] ZIP distribuible sin cachés, credenciales, bases personales ni evidencias privadas (`scripts/make_release.py`, con prueba)

## Laboratorio

- [x] Pantalla única de exploración: petición ad hoc, lote de parámetros → suite, conectividad, navegador con/sin grabación
- [x] Guardar respuesta observada como esperada (exacta con campos volátiles ignorados / estructura / solo código)
- [~] «Solo navegar» y grabador desde el `.exe` empaquetado sin validar

## Integración entre módulos (nueva prioridad)

- [x] Flujos entre módulos: ambiente por paso, referencias entre pasos y reglas de enriquecimiento con vista previa
- [x] Base compartida segura (conflictos, espera de escritores, sin WAL en red)
- [x] Observador de interfaces (tap opcional + historial, catálogo, línea base, detección de cambios, contrato vs realidad)
- [ ] Matriz de compatibilidad módulo → módulo y metadatos por módulo (dueño, empresa, versión)
- [ ] Modo «Ejecución» para el product owner, informe compartible y «aceptar nuevo esperado»

## Espacio de trabajo y agentes

- [x] Espacio de trabajo de tres zonas (historial persistente · petición/respuesta · inspector) con edición rápida y menú compacto
- [x] Protocolo para agentes: `ltw.spec/1` → `ltw.report/1` / `ltw.failure/1`, CLI, API local con token, JUnit, brief en Markdown
- [ ] Varias pestañas de petición abiertas a la vez; colecciones por carpetas
- [ ] Casos UI y flujos con ambiente propio dentro de `ltw.spec/1`; importar Postman/OpenAPI hacia la spec
- [ ] Modo «Ejecución» para el product owner, informe compartible y «aceptar nuevo esperado» (pendiente anterior)

## Pendiente conocido (fuera de este alcance)

- Importadores Postman/Bruno, OAuth2/Basic, reportes HTML/JUnit, ejecución en paralelo, servicio de Windows para el scheduler.
