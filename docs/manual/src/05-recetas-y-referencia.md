---

# 16. Recetas por perfil

Ejemplos paso a paso para los usos más comunes. Cada receta indica en qué pantalla se hace cada paso.

## 16.1 Desarrollador: de mi contrato a un paquete para el tester

**Objetivo:** dejar listas pruebas de mi servicio y pasárselas a quien las ejecutará.

1. **Proyectos → Crear proyecto** con el nombre de tu producto.
2. **Componentes → Importar** tu OpenAPI (URL o archivo).
3. **Ambientes → Nuevo ambiente**: `Local` con la URL de tu servicio; si usa token, guárdalo en **Secretos** y elígelo.
4. En **Componentes**, abre la operación y pulsa **Crear caso**. En el editor agrega aserciones: **Código HTTP**, y con **Agregar validación del contrato** el JSON Schema de la respuesta.
   - Alternativa rápida: en el **Espacio de trabajo** envía la petición, **Pruebas → Generar pruebas** y **Guardar**.
5. Encadena casos que dependan unos de otros (login → crear → consultar) usando **Encadenamiento** y agrúpalos en una **Suite** con política **Detener al primer fallo**.
6. Ejecuta la suite hasta que pase.
7. **Importar / Exportar → Suites seleccionadas → Exportar (.zip)** y envía el archivo. Avisa qué **secretos** debe crear el tester (los nombres, nunca los valores).

## 16.2 Tester: variar parámetros y detectar regresiones

**Objetivo:** probar un endpoint con muchos valores y saber, después, si algo cambió.

1. **Importar / Exportar → Importar** el paquete: elige **Fusionar**, revisa la **vista previa** y confirma. Crea tus secretos con los nombres indicados.
2. **Espacio de trabajo → Guardados**: abre un caso, cambia el **Body** o **Params** a tu gusto y pulsa **Enviar**. Mira **Cuerpo**, **Pruebas** y **Diff**.
3. Para varios valores de entrada, escribe `{{id}}` en la URL, abre **Lote**, **Actualizar columnas**, **Cargar filas** (un valor por línea) y **Ejecutar lote**.
4. **Guardar lote como flujo** (modo **Respuesta exacta**, ignorando los campos que sugiera). Queda un **flujo de regresión** con un caso por fila.
5. Cuando haya una versión nueva del sistema, **ejecuta el flujo**: las filas que fallen te dicen **qué campo cambió** (`$.name: obtenido "USER" (esperado "user1")`).
6. Si el cambio es **intencional**, vuelve a la petición en el Espacio de trabajo, envíala, **Generar pruebas** con la nueva respuesta y **Guardar** con **Actualizar el caso guardado**.

## 16.3 Product Owner: ejecutar y saber si «todo sale como se espera»

**Objetivo:** ejecutar las pruebas acordadas y entender el resultado sin leer código.

1. **Flujos**: busca el flujo acordado (por ejemplo *Smoke del catálogo*) y pulsa ▶. Espera el cuadro de resultado.
2. Verde **Pasó** = todo cumple lo esperado. **Falló** = el servicio respondió, pero no como se esperaba. **Error** = no se pudo ni probar (servicio caído, dato faltante).
3. **Ver detalle** en un paso fallido: verás **qué se esperaba y qué se obtuvo** en frases (por ejemplo «Código HTTP igual a 201 → 401»).
4. Para avisar al equipo técnico, en el detalle pulsa **Brief para agente** y **Copiar Markdown**: es un resumen completo del fallo que cualquier persona (o agente) puede usar.
5. **Programaciones**: pide que programen el flujo (por ejemplo, L–V a las 07:30).
6. **Resumen** (menú lateral): cada mañana mira el **semáforo** y la lista *Qué está fallando y desde cuándo*. Para un comité o un correo, **Reporte de estatus** genera el documento (HTML o PDF) con tus comentarios, y **Copiar resumen** un texto corto (ver 13.5).

> Mantén abierto `scripts\scheduler.bat` en el equipo que ejecuta las programaciones.

## 16.4 Responsable de integración: vigilar 8 componentes de distintos equipos

**Objetivo:** saber qué entra y qué sale de cada componente y enterarse cuando algo cambia.

1. **Observador → Nuevo tap** por componente importante (con **Empresa/equipo** y **Responsable**) y, si tienes su OpenAPI, asócialo.
2. Pon el consumidor a hablar con el tap en lugar de con el componente (en preproducción) y deja pasar tráfico representativo.
3. Revisa el **catálogo** y, por interfaz, la pestaña **Campos**: ya sabes qué envían y qué reciben, aunque nadie te lo haya documentado.
4. **Fijar línea base** de cada interfaz importante.
5. Revisa periódicamente el catálogo: las insignias rojas **«n cambio(s)»** indican qué componente cambió su formato. Abre la pestaña **Cambios** y **Contrato** para ver el detalle y contactar al responsable.
6. Para **pasar datos de un componente a otro** de forma verificable, crea un **flujo** (capítulo 10) con **enriquecimiento** y prográmalo.
7. Convierte interfaces críticas en **casos de regresión** con **Crear caso de regresión desde la última muestra**.

## 16.5 Agente: ciclo para reparar un servicio

Ver el [capítulo 17](#cap-17). En resumen: el agente escribe una `spec.json`, ejecuta `python run.py --run spec.json --report report.json`, lee `failures[]`, corrige el servicio y repite con `--only-failed` hasta que el código de salida sea `0`.

## 16.6 Probar un sitio web (casos UI)

1. **Casos UI → Navegador → Navegar y grabar** con la URL de tu sitio.
2. Haz el recorrido (iniciar sesión, buscar, comprar…) y **cierra el navegador**.
3. Revisa los **pasos importados**; **Convertir en caso UI**.
4. En **Casos UI**, abre el caso: ajusta locators, agrega **Verificar visible/texto** al final y usa `{{variables}}` / `{{secret:…}}` para los datos de acceso.
5. En **Ambientes**, define la **URL base de la interfaz** si es distinta de la de la API.
6. **Guardar y ejecutar**: se abre el resultado con los pasos, la captura y, si falló, la traza.

---

# 17. Protocolo para agentes

Un agente (otro programa o asistente de IA) puede **entregar casos de prueba** a LTW y **recibir los fallos** en un formato diseñado para que vaya **directo al código**, pruebe y repare. Todo es JSON, funciona **sin navegador** y tiene tres puertas equivalentes: **línea de comandos**, **API HTTP local** y la pantalla **Espacio de trabajo → Agente**. La especificación completa, con todos los campos y ejemplos, está en [AGENTS.md](AGENTS.md); el esquema JSON está en `docs/agent/ltw.spec.schema.json` y un ejemplo en `docs/agent/example.spec.json`.

| Formato | Dirección | Qué es |
|---|---|---|
| **`ltw.spec/1`** | agente → LTW | Ambientes, casos y suites. Referencias **por nombre**; **nunca** valores de credenciales. |
| **`ltw.report/1`** | LTW → agente | Resumen, resultados y un `ltw.failure/1` por cada fallo. |
| **`ltw.failure/1`** | LTW → agente | Qué se envió, qué se esperaba, qué llegó, diagnóstico, dónde mirar y cómo reproducir. |

## 17.1 La especificación de entrada

```json
{
  "format": "ltw.spec/1",
  "name": "Contrato de usuarios",
  "default_environment": "usuarios",
  "environments": [{"name": "usuarios", "base_url": "http://127.0.0.1:8765"}],
  "cases": [
    {"name": "ficha de usuario", "method": "GET", "path": "/api/users/1",
     "assertions": [{"type": "status", "expected": 200},
                    {"type": "json_type", "path": "$.id", "expected": "integer"}],
     "code_hints": {"files": ["src/users/routes.py"], "symbol": "get_user", "owner": "equipo-usuarios"}}
  ]
}
```

Puntos clave:

- **Se importa por nombre** (upsert): reenviar una spec corregida **actualiza** en vez de duplicar.
- **`code_hints`** (archivos, símbolo, repositorio, responsable) lo escribe quien conoce el código; LTW lo **repite en cada fallo** para orientar al agente.
- Puede incluir **suites** con pasos que cambian de ambiente y **reglas de enriquecimiento**, igual que en la interfaz (capítulo 10).
- **Valida antes de ejecutar:** cada error trae su **ruta exacta** (`$.cases[0].method: 'FETCH' is not one of [...]`).

## 17.2 Línea de comandos

```bat
python run.py --validate spec.json
python run.py --run spec.json --report report.json --md fallos.md --junit junit.xml
python run.py --run spec.json --only-failed report.json
python run.py --schema
```

| Opción | Efecto |
|---|---|
| `--report` | Informe `ltw.report/1` (con un `ltw.failure/1` por fallo). |
| `--md` | Los briefs de los fallos en Markdown. |
| `--junit` | JUnit XML para paneles de CI. |
| `--base-url URL` | Reemplaza la URL de **todos** los ambientes (útil si el servicio corre en otro puerto). |
| `--only-failed report.json` | Re-ejecuta **solo** lo que falló en un informe anterior. |
| `--persist`, `--project NOMBRE` | Guarda en tu workspace (por defecto usa una **base temporal** y no deja rastro). |

**Códigos de salida:** `0` todo pasó · `1` hay fallos · `2` especificación inválida o uso incorrecto.

## 17.3 API HTTP local

Solo en `127.0.0.1` y con **token**: el token se muestra (y se regenera) en **Espacio de trabajo → Agente → API local y línea de comandos**, o se fija con `LTW_AGENT_TOKEN`. Una página web **no** puede llamarla (no hay CORS y exige la cabecera `Authorization`).

| Método y ruta | Función |
|---|---|
| `GET /agent/v1/schema` | Esquema de `ltw.spec/1` (público). |
| `POST /agent/v1/validate` | Valida una spec → `{valid, errors, warnings}`. |
| `POST /agent/v1/run[?base_url=URL]` | Importa y ejecuta una spec → `ltw.report/1` (guarda en el proyecto de la spec). |
| `GET /agent/v1/failures/{run_id}[?format=md]` | Un fallo en JSON o como brief en Markdown. |

```bash
curl -s -X POST http://127.0.0.1:8080/agent/v1/run \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" --data @spec.json
```

Respuestas de error: `401` token ausente o incorrecto · `403` host que no es local · `422` spec inválida (con la lista de errores por ruta).

## 17.4 Qué contiene un fallo

| Campo | Contenido |
|---|---|
| `kind` | `assertion`, `error`, `connection`, `unresolved_variable`, `enrichment`, `extraction`. |
| `title`, `fix_goal` | Una frase y el objetivo («hacer que pase **sin debilitar** sus aserciones: …»). |
| `request` | Método, URL final, headers (secretos ocultos), query y body **tal como salió**. |
| `expected` | Las reglas del caso, las que **fallaron** (con el valor obtenido) y cuántas sí pasaron. |
| `response` | Estado, tiempo, headers y cuerpo (JSON o extracto, máx. 4000 caracteres). |
| `diagnosis` | **Heurístico**: `auth`, `not_found`, `validation`, `server_error`, `contract_mismatch`, `data_mismatch`, `network`, `test_setup`, `flow`, más sugerencias. |
| `where_to_look` | Tus `code_hints`, el **contrato OpenAPI** (operación y schema esperado) y los **cambios observados** en el tráfico. |
| `repro` | Un comando `curl` y el comando para re-ejecutar. |
| `brief_markdown` | Todo lo anterior como texto listo para pegar en otro agente. |

> El diagnóstico **orienta, no decide**, y LTW **no lee tu código**: `where_to_look` solo contiene lo que el autor de la spec puso en `code_hints`, el contrato importado y lo observado.

## 17.5 Desde la interfaz

- **Detalle de una ejecución fallida → Brief para agente:** muestra el brief, con **Copiar Markdown** y **Descargar failure.json**.
- **Espacio de trabajo → Agente:** brief del último fallo, exportar la petición actual como `ltw.spec/1`, importar una spec (se valida y se carga el primer caso o se importa todo) y el token con ejemplos.

## 17.6 Asistente con modelo de lenguaje (opcional)

LTW **no incluye ningún modelo ni llama a uno por su cuenta**. Si quieres ayuda de un modelo, lo conectas tú, desde **Espacio de trabajo → Agente → Conexión al modelo**. Mientras no haya una conexión válida, el asistente permanece **apagado** y todo lo demás funciona igual.

**Qué puedes conectar**

| Opción | Datos que necesitas |
|---|---|
| **Ollama**, **Docker Model Runner**, **LM Studio**, **Otro servidor local** (Podman, vLLM, llama.cpp…) | Solo la URL (hay valores por defecto) y el nombre del modelo. Sin clave |
| **Azure AI Foundry / Azure OpenAI** | URL del recurso, nombre del despliegue y clave |
| **OpenAI** | Clave de API |
| **Anthropic** | Clave de API |
| Personalizado | Cualquier servicio compatible con OpenAI |

> **Importante.** Las suscripciones de chat (Claude Max, ChatGPT Plus o Pro) **no incluyen clave de API** y sus condiciones no permiten reutilizarlas desde otra aplicación. Necesitas una clave de API (de pago por uso) o un modelo local.

**Cómo se conecta.** Elige el proveedor (rellena protocolo, URL y autenticación), escribe el modelo, pega la clave si hace falta y pulsa **Probar conexión**. La clave se guarda en el **Administrador de credenciales de Windows**, nunca en la base de datos; también puedes darla con la variable `LTW_LLM_API_KEY`. Si algo está mal, el aviso te dice qué (credenciales rechazadas, modelo inexistente, servidor apagado, tiempo agotado).

**Privacidad.** Un destino que **no es local** queda bloqueado hasta que actives **Permitir enviar datos fuera de esta máquina**. Antes de enviar, **Ver exactamente lo que se enviará** muestra el texto, ya sin los valores de tus secretos. La insignia indica si el modelo es **local** o está en la **nube**.

**Qué hace**

- **Explicar el último fallo:** envía el brief del fallo y devuelve *qué pasó*, *causa más probable*, *dónde corregir* y *siguiente paso*. Corrige siempre el servicio, no debilita las aserciones.
- **Generar casos:** describes lo que quieres probar (y, si quieres, eliges un contrato OpenAPI importado como contexto) y el modelo devuelve una `ltw.spec/1`. LTW la **valida** con el mismo validador de siempre, pide una corrección automática al modelo si falla y te la muestra. **No se guarda nada** hasta que pulses **Cargar el primer caso** o **Importar todo al proyecto**.

> **Consejo.** Con un modelo local pequeño, sube el tiempo de espera (por defecto 120 s) y usa descripciones cortas. Revisa siempre lo generado: es una propuesta, no una verdad.

---

# 18. Seguridad y buenas prácticas

## 18.1 Seguridad

| Tema | Cómo lo trata LTW |
|---|---|
| **Acceso** | La aplicación escucha solo en `127.0.0.1` y **no tiene inicio de sesión**: no la expongas a otras redes. |
| **Secretos** | En el almacén seguro del sistema; no se guardan en la base, el historial, los informes ni las exportaciones (los valores usados se eliminan; los headers de autorización se ocultan). |
| **Variables sin resolver** | Nunca se envía un `{{x}}` literal a tu servicio. |
| **Importación de paquetes** | Validación estricta y todo o nada (ver 14.2). |
| **Grabador** | Lee el script como texto; nunca lo ejecuta. |
| **Casos UI** | Solo navegan al host del ambiente; las redirecciones a otros hosts se bloquean. |
| **API de agentes** | Solo loopback, con token. |
| **Tap** | Solo loopback; reenvía sin modificar; enmascara campos sensibles. |
| **Evidencias** | Solo se sirven desde su directorio. |

## 18.2 Qué datos usar

- LTW está pensada para **preproducción**. El historial y las muestras del observador guardan **cuerpos enviados y recibidos**: usa **datos de prueba**, no datos personales reales.
- Escribe credenciales solo como **`{{secret:NOMBRE}}`** o en la autenticación del ambiente; no pongas valores literales en headers o bodies.
- Ejecuta pruebas **solo contra sistemas propios o autorizados**.

## 18.3 Buenas prácticas

1. **Un proyecto por producto**; nombres claros y consistentes (verbo + recurso: «Crear pedido»).
2. **Cada caso con al menos una aserción** y, si puedes, **una de contenido** (no solo el código HTTP).
3. **Ignora los campos volátiles** (fechas, ids generados, tokens) al comparar respuestas exactas.
4. **Entradas deterministas**: usa datos de prueba estables para que una diferencia signifique «algo cambió».
5. **Aliases cortos** en los pasos de una suite (`login`, `pedido`) y un caso por responsabilidad.
6. **Política «Detener al primer fallo»** en flujos donde un paso depende del anterior; **«Continuar»** en baterías independientes.
7. **Reintentos con moderación** (0–2): un caso que solo pasa con reintentos suele ocultar un problema.
8. En casos UI, **verifica contenido** al final del recorrido y **un caso por sitio**.
9. **Fija línea base** de las interfaces del Observador cuando las conozcas bien y revisa los cambios con regularidad.
10. **Respalda** copiando `data\` con la aplicación cerrada.

---

# 19. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| No abre `http://127.0.0.1:8080` | La aplicación no está corriendo o el puerto está ocupado por otra aplicación. | Ejecuta `scripts\run.bat`. Si el puerto está ocupado, usa otro: `set LTW_PORT=8090` y vuelve a arrancar. |
| «Address already in use» / error de puerto | Otra instancia o programa usa el puerto. | Cierra la otra instancia o cambia `LTW_PORT`. |
| Casos UI: «Executable doesn't exist… playwright install» | Falta Chromium de Playwright. | `python -m playwright install chromium` (con el entorno virtual activo). |
| «Zona horaria inválida» en una programación | En Windows falta el paquete `tzdata`. | `pip install tzdata` (el instalador ya lo incluye). |
| Caso en **Error**: «Variables sin resolver: x» | La ruta/headers/body usa `{{x}}` sin valor. | Define `x` en **Variables** del caso, del ambiente o de la suite. |
| Caso en **Error**: «Falta el secreto/variable de entorno de autenticación» | El ambiente apunta a un secreto que no existe. | Créalo en **Ambientes → Secretos** (mismo nombre) o define la variable de entorno. |
| Respuesta **401 / 403** | Credenciales ausentes, vencidas o de otro ambiente. | Revisa la autenticación del ambiente y el secreto. |
| `[SSL: WRONG_VERSION_NUMBER]` o fallo en el paso TLS | Usaste **https** contra un servidor que habla **http**. | Cambia **Proto.** a **http** (o corrige la URL). |
| «URL inválida (use http:// o https://)» | Falta el protocolo o la URL está mal escrita. | Elige el protocolo o escribe la URL completa. |
| «Con “URL completa” escribe una URL…» | Escribiste solo una ruta sin elegir ambiente. | Elige un ambiente o escribe la URL completa. |
| El caso **Falló** y no tiene aserciones | Un caso sin aserciones nunca pasa. | Agrega al menos una aserción. |
| «El body no es JSON válido» | JSON mal formado (comas, comillas). | Usa **Formatear** para ver dónde falla. |
| Caso UI: «Navegación fuera del host autorizado» | Un paso o redirección intenta ir a otro host. | Un caso por sitio; ajusta la **URL base de la interfaz** del ambiente. |
| Caso UI **pasa** pero la página no es la correcta | Solo verificabas la URL. | Agrega **Verificar visible/texto** sobre contenido propio de la página. |
| Sitios como Google muestran «unusual traffic» | Detección de bots del sitio. | LTW no la evade ni la resuelve; usa sitios propios o autorizados. |
| «Ya hay otro scheduler activo para este workspace» | Hay otro `scheduler.bat` abierto. | Usa el existente; si se cerró de golpe, espera 120 s. |
| Las programaciones no se ejecutan | El scheduler está cerrado, el equipo apagado o la programación **pausada**. | Abre `scripts\scheduler.bat`, revisa el recuadro de la pantalla **Programaciones** y su estado (**Activa**). |
| «Otra persona modificó este registro…» | Conflicto de edición con base compartida. | Recarga la página y vuelve a aplicar tus cambios. |
| «database is locked» o lentitud con base compartida | Muchas escrituras simultáneas o red lenta. | Reduce el número de personas simultáneas o trabajad por paquetes (cap. 15). |
| Importación rechazada («Entrada ZIP inválida», «Formato incompatible», «demasiado grande») | El ZIP no es un paquete de LTW, es de otra versión o excede los límites. | Exporta de nuevo desde LTW; revisa el tamaño (50 MB). |
| «El ambiente no pertenece al proyecto activo» / «Un caso no pertenece…» | Mezclaste recursos de proyectos distintos en una suite. | Usa casos y ambientes del mismo proyecto. |
| «La suite “X” se ejecuta contra … este destino es …» | Intentaste agregar un caso a una suite que apunta a otro servidor. | Elige otra suite o guarda sin agregar a una suite. |
| «Ejecuta el lote completo … antes de guardarlo» | Faltan resultados del lote o hubo errores de conexión. | Pulsa **Ejecutar lote** y revisa que todas las filas tengan respuesta. |
| Tap: «No se pudo abrir el puerto…» | El puerto está ocupado. | Elige otro **Puerto local**. |
| El Observador no muestra nada | No hay tráfico por el tap ni ejecuciones aprendidas. | Inicia el tap y genera tráfico, o pulsa **Aprender del historial**. |
| El menú lateral solo muestra iconos | Es el modo compacto de las pantallas de trabajo (Espacio de trabajo, Chat, Casos UI, Componentes). | Pasa el ratón para expandirlo, o usa ☰. |
| No aparece el botón Grabar/Navegador | Faltan Chromium o permisos. | Instala Chromium (ver arriba) y reinicia. |
| Al compilar el ejecutable, PyInstaller se queja del paquete `pathlib` | Un paquete obsoleto del mismo nombre en tu Python. | Compila en un entorno virtual limpio (ver KNOWN_LIMITATIONS.md). |

**¿Sigue sin resolverse?** En **Importar / Exportar → Descargar diagnóstico** obtienes un ZIP con versiones, conteos y registros recientes (sin secretos) para reportar el problema.

---

# 20. Referencia

## 20.1 Aserciones (26 tipos)

Un caso pasa solo si **todas** sus aserciones pasan. Las rutas JSON usan la sintaxis de [20.2](#cap-20).

| Etiqueta en pantalla | Tipo interno | Campos | Se cumple cuando… |
|---|---|---|---|
| **Código HTTP igual a** | `status` | esperado | El código es exactamente ese. |
| **Código HTTP en lista (200,201)** | `status_in` | esperado | El código es uno de la lista (separados por coma). |
| **Tiempo máximo (ms)** | `response_time_max` | esperado | La respuesta tardó como máximo ese tiempo. |
| **Header existe** | `header_exists` | nombre | El header viene en la respuesta. |
| **Header igual a** | `header_equals` | nombre, esperado | Su valor es exactamente el esperado. |
| **Header contiene** | `header_contains` | nombre, esperado | Su valor contiene el texto. |
| **JSONPath existe** | `json_exists` | ruta | La ruta existe en el cuerpo JSON. |
| **JSONPath no existe** | `json_not_exists` | ruta | La ruta **no** existe. |
| **JSONPath igual a** | `json_equals` | ruta, esperado | El valor es igual (el esperado se interpreta como JSON si es posible: `5`, `true`, `"x"`). |
| **JSONPath distinto de** | `json_not_equals` | ruta, esperado | El valor es distinto. |
| **JSONPath es de tipo** | `json_type` | ruta, tipo | El valor es `string`, `number`, `integer`, `boolean`, `array`, `object` o `null`. |
| **JSONPath longitud igual a** | `json_length` | ruta, esperado | La lista, texto u objeto tiene esa longitud. |
| **JSONPath cumple regex** | `json_regex` | ruta, esperado | El valor (como texto) coincide con la expresión regular. |
| **JSONPath contiene** | `json_contains` | ruta, esperado | La lista/objeto contiene el elemento, o el texto contiene la subcadena. |
| **JSONPath mayor que** | `numeric_greater` | ruta, esperado | El valor numérico es mayor que el esperado. |
| **JSONPath mayor o igual que** | `numeric_greater_equal` | ruta, esperado | Mayor o igual. |
| **JSONPath menor que** | `numeric_less` | ruta, esperado | Menor. |
| **JSONPath menor o igual que** | `numeric_less_equal` | ruta, esperado | Menor o igual. |
| **Cuerpo cumple JSON Schema** | `json_schema` | schema | El cuerpo valida contra el JSON Schema (borrador 2020-12). Un schema inválido hace fallar la aserción. |
| **Cuerpo JSON idéntico al esperado (ignorando campos)** | `json_matches` | esperado (JSON), ignorar (rutas) | El cuerpo es idéntico, tras quitar de ambos los campos ignorados. Al fallar lista las diferencias. |
| **Cuerpo idéntico al texto esperado** | `body_equals` | esperado | El cuerpo (texto) es exactamente ese. |
| **Cuerpo contiene texto** | `contains` | esperado | El cuerpo contiene la subcadena. |
| **Cuerpo no contiene texto** | `not_contains` | esperado | El cuerpo **no** contiene la subcadena. |
| **Cuerpo cumple regex** | `regex` | esperado | El cuerpo coincide con la expresión regular. |
| **Cuerpo no vacío** | `non_empty` | — | El cuerpo tiene contenido. |
| **Cuerpo vacío** | `empty` | — | El cuerpo no tiene contenido. |

Una aserción mal formada **no rompe** la ejecución: simplemente falla y muestra el motivo.

## 20.2 Rutas JSON (JSONPath)

| Sintaxis | Significado | Ejemplo |
|---|---|---|
| `$` | La raíz del cuerpo. | `$` |
| `$.a.b` | Campo `b` dentro de `a`. | `$.user.name` |
| `$.lista[0]` | Elemento por posición (desde 0). | `$.items[0].id` |
| `$['clave con espacios']` | Campo con caracteres especiales. | `$['x-total']` |
| `$.items[*].id` | **Todos** los elementos (devuelve una lista). | `$.items[*].price` |
| `a.b.0` | Forma corta heredada (sin `$`). | `data.0.id` |

**No** se soportan filtros (`?()`) ni búsqueda recursiva (`..`).

## 20.3 Variables y secretos

| Forma | Origen |
|---|---|
| `{{nombre}}` | Variable del **ambiente**, del **caso**, de la **suite** o **extraída** por un caso anterior. |
| `{{secret:NOMBRE}}` | Valor guardado en el almacén seguro del sistema (o en una variable de entorno con ese nombre). |
| `{{@alias:$.ruta}}` | Solo en **reglas de enriquecimiento**: valor de la respuesta de un paso anterior. |

**Prioridad** (de menor a mayor): ambiente → caso → suite y valores extraídos. Se sustituyen en la ruta, headers, query, body y pasos UI.

## 20.4 Límites

| Elemento | Límite |
|---|---|
| Contrato OpenAPI importado | 10 MB |
| Paquete ZIP a importar | 50 MB subida · 5000 entradas · 100 MB descomprimido · 10 MB por entrada |
| Historial del Espacio de trabajo | 300 peticiones por persona (las marcadas con ⭐ no cuentan) · cuerpo guardado hasta 100 000 caracteres |
| Cuerpo de respuesta en una ejecución | 50 000 caracteres |
| Visor de respuestas | 200 000 caracteres |
| Timeout de un caso API | 1 a 300 s (20 por defecto) |
| Reintentos / espera entre reintentos | 0–5 / 0–300 s |
| Cada N minutos (programación) | 1 a 10 080 |
| Puerto de un tap | 1024 a 65535 · cuerpos hasta 5 MB |
| Observador | 5 muestras por interfaz · 3 ejemplos por campo · hasta 50 elementos de lista por observación |
| Alias de un paso | letras, números, `_` y `-`; hasta 41 caracteres; único por suite |
| Bloqueo del scheduler | se recupera a los 120 s sin latido |

## 20.5 Archivos y comandos

| Elemento | Ubicación o comando |
|---|---|
| Base de datos | `data\workspace.sqlite3` |
| Evidencias | `data\evidence\` |
| Registros | `data\logs\workspace.log` (rotativo) |
| Instalar | `scripts\install.bat` |
| Arrancar | `scripts\run.bat` · `python run.py` |
| Scheduler | `scripts\scheduler.bat` · `python run.py --scheduler` |
| Pruebas de la herramienta | `scripts\test.bat` |
| Servicio de ejemplo | `python -m sample_app.server 8765` |
| Datos de demostración | `python scripts/seed_demo.py` (con `TEST_WORKSPACE_HOME` apuntando a una carpeta vacía) |
| Paquete distribuible | `python scripts/make_release.py 1.0.0` |
| Agentes | `python run.py --run / --validate / --schema` |
| Reporte de estatus | `python run.py --status-report reporte.html [--project N] [--days 14] [--notes T]` |

## 20.6 Atajos y trucos

| Acción | Cómo |
|---|---|
| Enviar la petición | **Ctrl+Enter** |
| Mostrar/ocultar el menú | Botón **☰** · pasa el ratón para expandir el menú compacto |
| Redimensionar zonas | Arrastra los separadores del Espacio de trabajo |
| Editar headers/params en masa | Interruptor **Texto**; `# ` desactiva una línea |
| Conservar una petición del historial | ⭐ |
| Ver qué cambió entre dos respuestas | Pestaña **Diff** |

## 20.7 Glosario

| Término | Significado |
|---|---|
| **API** | Servicio que otros programas consumen mediante peticiones. |
| **Aserción** | Regla que debe cumplir una respuesta para que el caso pase. |
| **Alias** | Nombre corto de un paso dentro de una suite. |
| **Base de datos compartida** | La misma base SQLite usada por varias personas. |
| **Brief** | Resumen de un fallo en texto, listo para entregarlo a un agente o persona. |
| **Campo volátil** | Campo que cambia en cada llamada (fecha, id, token). |
| **Caso** | Una prueba: petición + aserciones (API) o pasos de navegador (UI). |
| **Contrato (OpenAPI)** | Descripción formal de lo que ofrece un servicio. |
| **Enriquecimiento** | Reglas que añaden o modifican campos del request de un paso con datos de pasos anteriores. |
| **Flujo** | Suite cuyos pasos cruzan ambientes (componentes). |
| **JSON Schema** | Formato para describir la estructura de un JSON. |
| **JSONPath** | Notación para señalar un campo dentro de un JSON. |
| **Línea base** | Forma conocida y aceptada de una interfaz observada. |
| **Componente** | Un backend o un frontend: con contrato importado, o creado a mano (nombre, tipo, ambiente); también el nombre de un servicio observado por un tap. |
| **Observador / tap** | Aprendizaje del tráfico real; el tap es el proxy que lo captura. |
| **Preproducción** | Entorno de pruebas previo a producción. |
| **Proyecto** | Agrupa todos los recursos de un producto. |
| **Regresión** | Que algo que funcionaba deje de hacerlo o cambie. |
| **Scheduler** | Proceso que ejecuta las programaciones. |
| **Secreto** | Valor sensible guardado en el almacén seguro del sistema. |
| **Spec (`ltw.spec/1`)** | Especificación JSON de casos para agentes. |
| **Suite** | Lista ordenada de casos que se ejecutan en secuencia. |
| **Traza** | Grabación detallada de una ejecución UI fallida (Playwright). |

## 20.8 Acerca de esta versión

**Local Test Workspace 1.0.0** · Windows · Python 3.11+ · interfaz NiceGUI · navegador de pruebas Playwright/Chromium. Documentos relacionados: [AGENTS.md](AGENTS.md) (protocolo para agentes), [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) (límites conocidos), [ARCHITECTURE.md](ARCHITECTURE.md), [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md), [TEST_REPORT.md](TEST_REPORT.md) y [CHANGELOG.md](CHANGELOG.md).
