# Protocolo para agentes

Un agente puede **entregar casos de prueba** a Local Test Workspace y **recibir los fallos** en un formato pensado para que otro agente vaya directo al código, pruebe y repare. Todo es JSON, funciona sin navegador y tiene tres puertas equivalentes: **línea de comandos**, **API HTTP local** y la pantalla **Espacio de trabajo → Agente**.

| Formato | Dirección | Qué es |
|---|---|---|
| `ltw.spec/1` | agente → herramienta | ambientes, casos y suites. Referencias **por nombre**; nunca valores de credenciales |
| `ltw.report/1` | herramienta → agente | resumen + resultados + un `ltw.failure/1` por cada fallo |
| `ltw.failure/1` | herramienta → agente | qué se envió, qué se esperaba, qué llegó, diagnóstico, dónde mirar y cómo reproducir |

Esquema oficial de la especificación: [`docs/agent/ltw.spec.schema.json`](docs/agent/ltw.spec.schema.json) (también `python run.py --schema` o `GET /agent/v1/schema`). Ejemplo completo: [`docs/agent/example.spec.json`](docs/agent/example.spec.json).

## Ciclo recomendado (arreglar un servicio)

1. El agente escribe `spec.json` con los casos que describen el comportamiento correcto (y `code_hints` si conoce dónde está el código).
2. `python run.py --validate spec.json` → corrige los errores (cada uno trae su ruta, p. ej. `$.cases[0].method`).
3. `python run.py --run spec.json --report report.json --md fallos.md`
4. Para cada elemento de `report.failures[]`: leer `diagnosis`, `where_to_look`, `request`/`response`, ir al código, corregir **el servicio**.
5. `python run.py --run spec.json --only-failed report.json` para re-ejecutar solo lo que falló. Repetir hasta código de salida `0`.
6. Regla de oro: **no debilitar ni borrar aserciones para que pase**; solo si el contrato cambió a propósito, y decirlo.

## `ltw.spec/1`

```json
{
  "format": "ltw.spec/1",
  "name": "texto libre",
  "project": "Integración",                  // proyecto donde se guarda (por defecto «Agente»)
  "default_environment": "identidad",        // por defecto, el primero de environments
  "environments": [
    {"name": "pedidos", "base_url": "http://127.0.0.1:8766",
     "variables": {"tenant": "acme"},
     "auth": {"type": "bearer", "secret": "PEDIDOS_TOKEN"}}      // NOMBRE del secreto o variable de entorno; nunca su valor
  ],
  "cases": [
    {"name": "crear pedido", "method": "POST", "path": "/api/items", "environment": "pedidos",
     "headers": {}, "query": {}, "body": {"name": "x"}, "variables": {}, "timeout": 20,
     "assertions": [{"type": "status", "expected": 201}],
     "extract": [{"name": "id", "source": "json", "path": "$.id"}],
     "tags": ["smoke"], "notes": "...",
     "code_hints": {"files": ["src/orders/routes.py"], "symbol": "create_item", "repo": "orders", "owner": "equipo-pedidos", "notes": "..."}}
  ],
  "suites": [
    {"name": "flujo", "environment": "identidad", "on_failure": "stop", "retries": 0,
     "steps": [{"case": "login", "alias": "login"},
               {"case": "crear pedido", "alias": "pedido", "environment": "pedidos",
                "enrich": [{"action": "set", "target": "headers", "path": "Authorization",
                            "source": {"type": "template", "value": "Bearer {{@login:$.token}}"}}]}]}
  ]
}
```

Reglas:

- **Idempotente**: se hace *upsert por nombre* dentro del proyecto. Reenviar una spec corregida actualiza en lugar de duplicar.
- **Aserciones**: 26 tipos (`status`, `status_in`, `json_equals`, `json_exists`, `json_type`, `json_regex`, `json_schema`, `json_matches`, `header_equals`, `response_time_max`, `contains`, …). Lista completa en el esquema. Rutas JSON con sintaxis `$.a.b[0].c`.
- **Variables**: `{{nombre}}` en ruta/headers/query/body; `{{secret:NOMBRE}}` toma el valor del almacén de credenciales del sistema o de una variable de entorno con ese nombre. La validación avisa si pones un valor literal en un header sensible.
- **Flujos entre módulos**: una suite puede cambiar de ambiente por paso (`environment`) y **enriquecer** el request con datos de pasos anteriores (`enrich`): acciones `set | remove | merge`, destinos `body | headers | query | path`, orígenes `literal | step | var | template` (`{{@alias:$.ruta}}`). Una regla solo puede apuntar a pasos *anteriores*; si el dato no existe, el paso termina en error **sin enviar nada**.
- Los casos que no pertenecen a ninguna suite se ejecutan sueltos, contra `environment` o `default_environment`.

## Línea de comandos

```
python run.py --validate spec.json                 # 0 válida · 2 inválida (errores por ruta en stdout)
python run.py --run spec.json [opciones]           # 0 todo pasó · 1 hay fallos · 2 spec inválida
python run.py --schema                             # imprime el JSON Schema
```

Opciones de `--run`: `--report out.json` (ltw.report/1) · `--md out.md` (briefs) · `--junit out.xml` (para CI) · `--base-url URL` (reemplaza la URL de **todos** los ambientes, útil si el servicio corre en otro puerto) · `--only-failed report.json` · `--persist` (guarda en el workspace compartido; por defecto usa una base temporal y no deja rastro) · `--project NOMBRE`.

## API HTTP local

Solo `127.0.0.1` y con token. El token se muestra en **Espacio de trabajo → Agente** (o variable `LTW_AGENT_TOKEN`). Una página web no puede llamarla (no hay CORS y exige la cabecera `Authorization`).

```
GET  /agent/v1/schema                       esquema (público)
POST /agent/v1/validate                     body: spec            → {valid, errors[], warnings[]}
POST /agent/v1/run[?base_url=URL]           body: spec            → ltw.report/1   (guarda en el proyecto de la spec)
GET  /agent/v1/failures/{run_id}[?format=md]                      → ltw.failure/1 o su brief en Markdown
```

```bash
curl -s -X POST http://127.0.0.1:8080/agent/v1/run \
  -H "Authorization: Bearer $LTW_TOKEN" -H "Content-Type: application/json" --data @spec.json
```

Errores: `401` sin/ con token incorrecto · `403` host que no es local · `422` spec inválida (`errors[]` con rutas).

## `ltw.report/1`

```json
{"format": "ltw.report/1", "generated_at": "...", "tool": {"name": "local-test-workspace", "version": "1.0.0"},
 "spec": {"name": "...", "digest": "ab12…"}, "project": "Integración",
 "summary": {"status": "failed", "total": 4, "passed": 3, "failed": 1, "error": 0, "duration_ms": 412.5},
 "results": [{"case": "login", "alias": "login", "suite": "flujo", "status": "passed", "http_status": 200,
              "duration_ms": 12.1, "environment": "identidad", "run_id": "…"}],
 "failures": [ <ltw.failure/1>, … ], "warnings": []}
```

## `ltw.failure/1`

Cada fallo es **autosuficiente**:

| Campo | Contenido |
|---|---|
| `kind` | `assertion`, `error`, `connection`, `unresolved_variable`, `enrichment`, `extraction` |
| `title`, `fix_goal` | frase corta y el objetivo («hacer que pase **sin debilitar** sus aserciones: …») |
| `case` | nombre, método, ruta, `tags`, `notes` |
| `suite_step`, `previous_steps` | paso dentro del flujo y estado de los pasos anteriores |
| `environment` | nombre y `base_url` |
| `request` | método, URL final, headers (**secretos ocultos**), query, body **tal como salió** |
| `enrichment_applied` | reglas de enriquecimiento aplicadas a ese request |
| `expected` | reglas del caso, las que **fallaron** (con valor obtenido) y cuántas sí pasaron |
| `response` | estado, tiempo, headers y cuerpo (JSON o extracto de texto, máx. 4000 caracteres) |
| `diagnosis` | `category` (`auth`, `not_found`, `validation`, `server_error`, `contract_mismatch`, `data_mismatch`, `network`, `test_setup`, `flow`) + `hints[]`. **Heurístico**: orienta, no decide |
| `where_to_look` | `code_hints` que dio el autor de la spec · operación y schema del **contrato OpenAPI** si el módulo está importado · **cambios observados** en el tráfico (Observador) |
| `repro` | comando `curl` y comando para re-ejecutar |
| `brief_markdown` | todo lo anterior como texto listo para pegar en otro agente |

## Seguridad y privacidad

- Las especificaciones **no llevan credenciales**: solo nombres de secretos. Los valores usados se eliminan de lo que se guarda y de los informes.
- El historial y los informes contienen el cuerpo enviado y recibido: úsalo con datos de **preproducción**, no con datos personales reales.
- Regenera el token desde la pantalla Agente si lo compartiste por error.

## Versionado

El número del formato (`/1`) solo cambia con cambios incompatibles. Se pueden **añadir** campos a `ltw.report/1` y `ltw.failure/1` sin cambiar la versión: ignora los que no conozcas.

## Especificación: Historias de usuario y Casos de prueba (`ltw.spec_bundle/1`)

Aparte del protocolo de arriba (que es para **casos ejecutables**: API/UI, pensados para correr y fallar), hay un segundo protocolo, independiente, para la sección **Especificación** (`/stories`, `/test-specs`): Historias de usuario con sus Criterios de aceptación, y Casos de prueba como documento de planificación (precondición, pasos, resultado esperado) — existan o no todavía como un Caso ejecutable. Útil para que un agente externo (p. ej. uno que lee requisitos o tickets) alimente o lea esta sección sin pasar por la UI.

```json
{
  "format": "ltw.spec_bundle/1",
  "project": "Integración",
  "stories": [
    {"title": "Recuperar contraseña por email", "as_a": "usuario registrado",
     "i_want": "poder recuperar el acceso a mi cuenta si olvido la contraseña",
     "so_that": "no perder el acceso a mis datos", "priority": "high",
     "criteria": [{"text": "Dado un email válido, se envía un enlace de recuperación", "status": "pending"}],
     "test_cases": [{"title": "Solicitar recuperación con email válido", "preconditions": "Cuenta activa",
                      "steps": [{"action": "Ingresar el email", "expected": "Se confirma el envío"}],
                      "priority": "high", "type": "functional"}]}
  ]
}
```

- **Idempotente**: upsert por **título**, dentro del proyecto — las Historias por su propio título, los Casos de prueba por su título dentro de la Historia a la que pertenecen (el mismo título puede repetirse en otra Historia sin pisarla). Reenviar un bundle corregido actualiza en lugar de duplicar.
- `GET /agent/v1/specs/schema` — el JSON Schema de `ltw.spec_bundle/1`.
- `POST /agent/v1/specs/import[?project=NOMBRE]` — body: el bundle → crea/actualiza Historias y Casos de prueba; responde `{format, project, stories: [título…], test_cases: [título…]}` (o `422` con `errors[]` si el bundle no valida).
- `GET /agent/v1/specs/export?project=NOMBRE` — devuelve el bundle actual de ese proyecto (todas sus Historias y Casos de prueba), en el mismo formato — para que un agente lea lo que ya existe antes de enriquecerlo.

Mismo guard que el resto de la API (`127.0.0.1` + `Authorization: Bearer <token>`, mostrado en **Espacio de trabajo → Agente**). Esto **no** reemplaza `ltw.spec/1`: ese sigue siendo el protocolo para casos ejecutables (API/UI) con sus aserciones; este es solo para el documento de planificación de la Especificación.
