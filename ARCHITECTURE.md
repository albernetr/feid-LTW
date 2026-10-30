# Arquitectura

```
run.py ───────────► app/main.py (NiceGUI, 127.0.0.1)  ──► app/pages/*  (una página por pantalla)
   └ --scheduler ─► app/automation.serve_scheduler
                          │
app/pages/* ──► app/core.py        almacenamiento, OpenAPI, variables/secretos, aserciones,
                                    ejecución HTTP, portabilidad, evidencias
            ──► app/automation.py  ejecutor UI (Playwright), suites, programaciones, lock
            ──► app/recorder.py    Codegen → pasos (AST, sin ejecutar)
            ──► app/logs.py        logs JSON-lines y paquete de diagnóstico
sample_app/server.py               aplicación local para pruebas E2E
```

## Decisiones

- **Almacenamiento**: SQLite (WAL) en `<paquete>/data/` (portable; `core.default_root`) con una tabla por entidad `(id, payload JSON)`. Simple y portable; las importaciones usan una única transacción (`BEGIN IMMEDIATE`).
- **Núcleo sin UI**: `core`/`automation`/`recorder` no importan NiceGUI; todo es testeable sin navegador. Las páginas solo orquestan.
- **Proyectos**: cada registro lleva `project_id`; `list_project_items` filtra. Suites validan que ambiente y casos pertenezcan al mismo proyecto; programaciones heredan el de su suite.
- **Secretos**: `keyring` (Credential Manager en Windows). La base guarda solo *nombres*. Los valores usados en una ejecución se eliminan (`scrub`) de lo que se persiste.
- **Ejecución API**: `httpx`, sin redirecciones ni proxies del entorno; variables sin resolver abortan antes de enviar.
- **Ejecución UI**: Chromium headless por caso, contexto aislado, `route` que aborta navegaciones a otros hosts, traza solo en fallos, captura siempre.
- **Suites**: bucle secuencial con variables compartidas; cancelación cooperativa mediante `threading.Event`; la UI las ejecuta con `run.io_bound` para no bloquear.
- **Scheduler**: proceso aparte; un `scheduler.lock` con latido (obsoleto a los 120 s) garantiza una sola instancia. `next_run_at` avanza *antes* de ejecutar para evitar repeticiones tras un error.
- **Portabilidad**: `read_package` valida todo (rutas, enlaces simbólicos, tamaños/ratio, duplicados, ids, tipos) antes de tocar la base; `preview_import` no escribe.
- **Evidencias**: se sirven únicamente a través de `evidence_path` (UUID + nombre base + resolución dentro del directorio).
- **Red**: la app escucha en loopback; no hay autenticación propia, por eso no debe exponerse.

## Modelo de datos (campos principales)

| Tabla | Campos clave |
|---|---|
| projects | name, description |
| modules | project_id, name, operations[], source_spec |
| environments | project_id, base_url, ui_base_url, auth{type,secret,env_var,header}, variables |
| cases | project_id, type(api/ui), method, path, headers, query, body, assertions[], extract[], steps[] |
| suites | project_id, environment_id, case_ids[], on_failure, retries, retry_delay_s, variables |
| schedules | project_id, suite_id, frequency, time/run_at/interval_minutes, timezone, missed_policy, enabled, next_run_at |
| runs | type(api/ui/suite), status, assertions, steps, case_runs, screenshot, trace |
| settings | active_project_id, secret_names |
