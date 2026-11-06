---

# 7. Proyectos, componentes y ambientes

Estos tres elementos preparan el terreno para tus pruebas. Se configuran una vez y se reutilizan.

## 7.1 Proyectos

![Pantalla de Proyectos](img/02-proyectos.png)

Un **proyecto** agrupa componentes, ambientes, casos, suites y programaciones de un mismo producto. Siempre hay **un proyecto activo** (el del selector del encabezado); las pantallas muestran y crean cosas en ese proyecto.

**Crear un proyecto.** En **Nuevo proyecto** escribe el **Nombre** (obligatorio) y una **Descripción** opcional, y pulsa **Crear proyecto**. El primero que crees queda activo automáticamente; cuando creas otros se te selecciona el nuevo.

**Los proyectos se listan en una tabla** (nombre, descripción, recursos, estado) con buscador; cada fila lleva a una página de detalle con el formulario, el desglose de recursos (componentes, ambientes, casos, suites, programaciones) y las acciones.

| Acción | Efecto |
|---|---|
| **Guardar cambios** | Actualiza nombre y descripción. |
| **Seleccionar** | Lo convierte en el proyecto activo (también desde el selector del encabezado). |
| **Deshabilitar / Habilitar** | Mientras está deshabilitado no se puede seleccionar como activo desde ningún lado; si estaba activo, se desactiva solo. No pausa nada que ya esté corriendo, pero el scheduler omite sus programaciones. |
| **Eliminar** | Pide confirmación. **Solo elimina un proyecto vacío**; si tiene componentes, ambientes, casos, suites, programaciones o taps, ofrece un segundo diálogo que exige escribir el nombre exacto del proyecto para borrar también todo ese contenido (irreversible). |

> **Recursos sin proyecto (de versiones anteriores).** Si existen elementos sin proyecto, aparece un aviso **«Asignarlos al proyecto activo»** para adoptarlos; hasta entonces no se ven al filtrar por proyecto.

> **Consejo.** Usa **un proyecto por producto o iniciativa**. Los ambientes, casos y suites no se comparten entre proyectos (al guardar desde el Espacio de trabajo en otro proyecto, el ambiente se copia).

## 7.2 Componentes (backends, frontends, con o sin contrato)

![Un componente importado con sus operaciones](img/30-modulos.png)

Un **componente** es una pieza desplegable de tu solución: un backend, un frontend, o ambos a la vez (un monolito full-stack que sirve API y UI desde el mismo proceso). Registrar un componente **nunca es obligatorio**: puedes crear Casos API o Casos UI sin pasar por aquí.

**Registrar un componente.** En **Registrar componente** escribe un **Nombre**, marca lo que expone (**Expone backend (API)**, **Expone frontend (UI)**, o ambos) y, opcionalmente, dónde vive: elige uno o varios **ambientes existentes**, o escribe **un origen nuevo** (una URL) para que LTW registre ese ambiente de una vez. También puedes ligarlo a un **Módulo** (§7.4). Eso es todo lo que hace falta para que exista en el inventario del proyecto y puedas asociarle Casos directamente.

El **contrato OpenAPI/Swagger**, si el componente expone backend y lo tiene publicado, se importa **después**, como un paso aparte y opcional — no hace falta tenerlo a mano al registrar. Habilita funciones muy útiles: crear casos con un clic desde una operación, **validar respuestas contra el contrato**, **comparar lo observado con lo declarado** (Observador) y la **exploración automática**.

**Importar el contrato.** Desde el detalle del componente, pestaña **Operaciones** (solo visible si expone backend y aún no tiene catálogo), puedes:

- escribir una **URL** (`http` o `https`) y pulsar **Importar desde URL**; o
- **arrastrar un archivo** `.json`, `.yaml` o `.yml`.

La URL puede ser cualquiera de estas:

| Qué pegas | Qué hace LTW |
|---|---|
| El enlace **directo** al contrato (`…/openapi.json`, `…/swagger.json`, un `.yaml`) | Lo descarga tal cual (sigue redirecciones). |
| La **página de Swagger UI o Redoc** del servicio (por ejemplo `https://petstore3.swagger.io/`, o el `/docs` y `/redoc` de un servicio FastAPI) | Lee la página y sus scripts de arranque, encuentra el contrato que usa y lo importa. Si hay varios, prefiere los del mismo servidor. |
| Un enlace de **GitHub** de un archivo (`github.com/…/blob/…`) | Lo convierte al enlace «raw» y lo descarga. |
| Un servicio que sirve su contrato en una ruta habitual (`/openapi.json`, `/swagger.json`, `/v3/api-docs`…) | Prueba esas rutas si la página no lo enlaza. |

Si el contrato declara etiquetas, antes de guardar nada se pregunta **¿importar todo, o solo algunas etiquetas?** — útil con contratos grandes de los que solo interesa una parte (p. ej. 10 de 500 operaciones); si no declara etiquetas, importa todo directamente. Al terminar, el aviso indica el **origen real** del contrato (por ejemplo, la página `https://petstore3.swagger.io/` resolvió a `…/api/v3/openapi.json`); el componente lo recuerda. Si la dirección escrita da error, también prueba esas rutas habituales desde el mismo servidor; se prueban como máximo 14 direcciones. La importación **nunca cambia el nombre** que le pusiste al registrarlo, ni su Módulo/Estado: solo trae operaciones, versión y servidor. Volver a importar (el mismo origen u otro) actualiza ese mismo componente, nunca crea uno duplicado. Se aceptan **OpenAPI 3.x** y **Swagger 2.0**, hasta **10 MB**.

**Servidor declarado y ambiente.** Cuando el contrato indica su servidor (OpenAPI `servers`, o `host` + `basePath` en Swagger 2.0; una dirección relativa se resuelve contra el origen; si no declara ninguno, como hace FastAPI, se usa el servidor desde el que se descargó), LTW **registra el ambiente automáticamente** al importar (lo crea, o reutiliza uno existente con esa misma URL) y lo liga al componente. Si en su momento no se pudo resolver, la pestaña **Ambientes** del componente muestra **Servidor declarado** y el botón **Crear ambiente con esta URL** para hacerlo a mano.

**Referencias `$ref`.** Se resuelven las **locales** (`#/components/...`). Las **externas** (otros archivos o URL) se **rechazan** con un mensaje claro; no se descarga nada desde dentro del documento por seguridad. Los modelos **recursivos** (por ejemplo, un comentario con respuestas que son comentarios) sí se aceptan: la recursión se corta en el punto en que se repite y ahí el esquema queda abierto, de modo que la validación contra el contrato es más permisiva en ese nivel.

**El detalle de un componente** se organiza en pestañas:

| Pestaña | Qué tiene |
|---|---|
| **Resumen** | Identidad (nombre, qué expone — editable incluso si viene de un contrato), Módulo/Estado, y tarjetas con el conteo de ambientes, casos y funcionalidades (clic y te lleva a esa pestaña). |
| **Ambientes** | Todos los ambientes ligados (puede ser más de uno: dev, QA, producción…), con **Verificar conexión** por ambiente individual o para todos a la vez, y el selector para ligar/desligar. |
| **Catálogo** | El aviso de Casos UI si expone frontend; si expone backend y ya tiene operaciones, dos sub-pestañas **Automático** (exploración automática) y **Manual** (agregar/editar/quitar endpoints a mano) — el catálogo completo del contrato (filtrable por **etiqueta**, con «Probar» y «Crear caso» por fila) se ve en las dos, el modo elegido solo decide qué herramienta adicional ofrece; o el formulario para importar el contrato si todavía no lo tiene. |
| **Casos y funcionalidades** | Los Casos generados desde este componente, y las **Funcionalidades** que dependen de él (§7.5) — si este componente se cae, qué le afecta al negocio. |

**La lista de componentes** es una tabla (Nombre, Tipo, Módulo, Estado, Operaciones, Ambiente, Casos generados); haz clic en una fila para ver su detalle.

**Catálogo manual, antes de tener un Caso.** En la pestaña Catálogo, un componente que expone backend puede «Agregar un endpoint a mano» (método, ruta, resumen opcional) aunque no tenga contrato — se guarda junto a las operaciones del contrato, con una etiqueta «a mano» que las distingue y las protege de borrarse al reimportar. Si el componente ya tiene operaciones (de un contrato), el formulario de agregar y los endpoints ya agregados a mano viven en la sub-pestaña **Manual**, separados del catálogo completo del contrato (sub-pestaña **Automático**) — así no hay que buscar uno entre cientos de filas para quitarlo; un icono de editar permite cambiarle método, ruta o resumen sin borrarlo y crearlo de nuevo. Cada fila del catálogo completo también tiene «Probar», que abre el **Espacio de trabajo** (§13) en una pestaña nueva con el método, la ruta y un ambiente ya precargados, para ejecutar la petición ad hoc y ajustar parámetros, headers o body ahí mismo antes de decidir si conviene un Caso. Uno que expone frontend puede catalogar **Vistas** (nombre y ruta); su botón «Crear caso UI» abre el grabador con el nombre y la navegación inicial ya puestos, un icono copia la URL completa al portapapeles, y «Verificar» carga la ruta en un navegador real (headless) e inspecciona el contenido ya renderizado — no solo el código HTTP, porque en una SPA con ruteo del lado del cliente el servidor suele responder 200 para cualquier ruta aunque la propia aplicación muestre «página no encontrada». Es un paso intermedio entre «sé que esto existe» y «ya tengo el Caso que lo prueba». Un icono junto a «Copiar URL» abre la vista en una pestaña nueva. «Detectar vistas automáticamente» recorre el sitio del ambiente ligado siguiendo sus enlaces ya renderizados (con una barra de progreso mientras escanea) y propone las rutas nuevas que encuentra para elegir cuáles agregar — por defecto hasta 15 páginas desde la raíz, pero un campo «Ruta inicial» lo acota a una sección (p. ej. «/admin») y «Escaneo completo» sube el límite a 200; no reemplaza una revisión manual, pero ahorra tipearlas una por una.

**Eliminar un componente.** Se bloquea si algún caso lo usa (te dice cuántos).

**Mover un componente a otro proyecto.** Como ningún formulario de creación tiene selector de proyecto (todo nace en el **Proyecto activo** del encabezado), si un componente terminó en el proyecto equivocado, «Mover a otro proyecto» (pestaña Resumen) lo corrige: elige el destino y confirma. Se bloquea si el componente ya tiene Casos (muévelos o bórralos primero); los Ambientes y Módulos ligados se desvinculan, no se transfieren, porque pertenecen al proyecto anterior.

## 7.3 Ambientes y secretos

![Ambientes y secretos](img/31-ambientes.png)

Un **ambiente** define *dónde* se ejecutan las pruebas.

### Crear o editar un ambiente

| Campo | Descripción |
|---|---|
| **Nombre** | Por ejemplo `QA`, `Preproducción`. |
| **URL base (API)** | Obligatoria, con `http://` o `https://`. Ej.: `https://qa.empresa.com`. |
| **URL base de la interfaz** | Opcional. Solo si tu sitio web está en otra dirección que la API; la usan los **casos UI**. |
| **Hosts adicionales de confianza** | Opcional. Dominios extra a los que un Caso UI puede navegar (SSO/MFA) — ver más abajo. |
| **Autenticación** | **Sin autenticación**, **Bearer token** o **API Key**. |
| **Secreto guardado en el sistema** | Elige un secreto de la lista (ver abajo). |
| **…o variable de entorno** | Alternativa: el nombre de una variable de entorno del sistema (por ejemplo `QA_TOKEN`). |
| **Header (solo API Key)** | Nombre del header donde viaja la clave (por defecto `X-API-Key`). |
| **Variables** | Pares nombre/valor disponibles como `{{nombre}}` en rutas, headers, query, body y pasos UI. |

Pulsa **Nuevo ambiente** y luego **Guardar ambiente**. La lista es una tabla: haz clic en una fila (o en su icono ✎) para editarlo; el 🗑 lo elimina (no se puede si alguna suite lo usa).

Con **Bearer**, LTW envía `Authorization: Bearer <valor del secreto>`; con **API Key**, el header elegido con el valor del secreto. Si falta el secreto o la variable de entorno, el caso termina en **Error** con ese mensaje y **no se envía**.

### Hosts adicionales y sesión guardada (SSO/MFA, como PingID)

Un **Caso UI** solo puede navegar dentro del host de la **URL base**: cualquier otro dominio se bloquea a nivel de red, para que un caso nunca termine en un sitio ajeno por accidente. Un login real detrás de **SSO/MFA** (PingID, Okta, Azure AD…) típicamente redirige a OTRO dominio y además pide una aprobación (push al teléfono, código) que **ninguna herramienta puede scriptear** — ni LTW ni ninguna otra, porque depende de un humano o de la API propia del proveedor.

Dos campos resuelven esto:

- **Hosts adicionales de confianza**: lista separada por coma de los dominios a los que un Caso UI puede navegar además de la URL base (p. ej. `auth.miempresa.com, miempresa.pingone.com`). Sin esto, la redirección al proveedor de SSO se corta ahí.
- **Sesión guardada**: en vez de automatizar el login (imposible con MFA), lo evitás — inicias sesión **una sola vez, a mano**, en una ventana real que abre **«Capturar sesión ahora»** (requiere guardar el ambiente primero). Cerrá la ventana una vez logueado y LTW guarda las cookies/sesión resultantes en el **Administrador de credenciales** de esta máquina. Desde ese momento, cualquier Caso UI contra este ambiente **arranca ya autenticado**, sin pasar por el formulario de login. **Borrar sesión** la quita (pide confirmación); volver a guardar el ambiente no la pierde.

> La sesión vive en esta máquina, no viaja en exportaciones ni se comparte entre ambientes: cada persona del equipo que necesite correr Casos UI contra un sistema con SSO tiene que capturar la suya.

### Obtención de token o clave (opcional)

Con **Bearer** o **API Key** activos, aparecen los mismos campos para describir cómo se obtiene el valor — el mecanismo es igual para los dos (ambos terminan siendo un valor guardado que se inyecta en un header), pero la pantalla lo llama «token» con Bearer y «clave» con API Key, porque en la práctica suelen obtenerse distinto (un Bearer casi siempre por login; una API Key casi siempre es estática, pegada desde un panel). Dejar los campos en blanco equivale a «no aplica»; completarlos **no** lo activa automáticamente, solo lo deja listo:

| Mecanismo | Qué hace |
|---|---|
| **Petición HTTP** (beta) | Llama a un endpoint (típico de OAuth2: método, URL, headers y body, admiten `{{variables}}` y `{{secret:NOMBRE}}`), extrae el token de la respuesta con una ruta JSONPath (`$.access_token` por defecto) y, si das la ruta de duración (`expires_in`), recuerda cuándo vuelve a vencer. |
| **Comando del sistema** (experimental) | Ejecuta un comando local y toma su salida estándar como el token. El scheduler lo corre sin supervisión en esta máquina: úsalo solo con scripts de confianza. |

El token resultante se guarda en el secreto que indiques (o en el mismo que ya usa el ambiente, si lo dejas vacío). Una vez configurado, el botón **Obtener token ahora** lo ejecuta de inmediato (requiere guardar el ambiente primero) — sirve tanto para probarlo como para pedir un token puntual sin automatizar nada.

Un segundo checkbox, **«Además, actualizarlo automáticamente si falta, expira, o el servicio responde 401»** (marcado por defecto al configurar el mecanismo), decide si esto corre solo: con él activo, LTW refresca el token **antes** de ejecutar un caso si no hay uno guardado o ya venció, y además **reintenta una vez** si el servicio responde `401`. Desmarcarlo deja el mecanismo configurado y disponible vía «Obtener token ahora», pero nunca se dispara por sí solo — útil para mantener el control manual de cuándo se pide un token nuevo.

### Secretos (almacén seguro del sistema)

La sección **Secretos** guarda valores sensibles en el **Administrador de credenciales de Windows** (no en la base de datos ni en exportaciones).

1. Escribe el **Nombre** (letras, números, `.`, `_`, `-`) y el **Valor** (campo con ojo para mostrarlo).
2. Pulsa **Guardar secreto**.

Se usan:

- en la autenticación de un ambiente (campo **Secreto guardado en el sistema**);
- en cualquier parte de una petición como **`{{secret:NOMBRE}}`** (por ejemplo, `Authorization: Bearer {{secret:TOKEN_QA}}`).

La lista solo muestra los **nombres** (con `••••••••`); el valor nunca se muestra. Si no existe un secreto con ese nombre, LTW busca una **variable de entorno** con el mismo nombre. Los valores usados **se eliminan** de lo que se guarda en el historial y de los informes.

Un ambiente también declara **qué sirve**: backend (API), frontend (UI), o ambos — por defecto ambos, para no restringir nada hasta que lo acotes a propósito. Un servidor de desarrollo de frontend (p. ej. `localhost:4200`) normalmente no tiene API propia: desmarcar «backend» evita que se ofrezca en la exploración automática de un contrato.

## 7.4 Módulos (agrupar por dominio)

Un **Módulo** (`/module-groups`) agrupa Componentes por dominio o propiedad técnica — quién es dueño de qué, dónde vive —, independiente de qué exponen técnicamente. Un componente puede pertenecer a más de un Módulo a la vez (p. ej. un backend compartido entre dos dominios). Se liga desde el propio Componente (pestaña Resumen → Clasificación). Un Módulo con componentes ligados no se puede eliminar hasta desligarlos.

## 7.5 Funcionalidades (trazabilidad de negocio)

Una **Funcionalidad** (`/features`) es una capacidad de negocio que puede cruzar varios Componentes y Módulos a la vez (p. ej. «Checkout» usa Pagos, Inventario y Notificaciones) — un eje distinto e independiente del Módulo. Se valida con una o más **Suites/flujos** ligadas a ella (al editar una suite, el campo «Funcionalidad»); su detalle muestra cada suite con el estado de su última corrida y un resumen agregado («3/4 pasan»).

---

# 8. Casos API

Un **caso API** es una petición HTTP guardada con las **aserciones** que debe cumplir su respuesta. Se crean desde el **Espacio de trabajo** (lo más cómodo) o desde esta pantalla.

## 8.1 La lista de casos

![Lista de casos API](img/32-casos-api.png)

- **Nuevo caso** abre el editor vacío.
- **Ejecutar en ambiente** elige el ambiente para los botones ▶ de la lista. Si no hay ambientes se te avisa.
- **Componente** y **Módulo** filtran la lista por el componente del caso o por el módulo (grupo) al que pertenece ese componente — aparecen solo si hay algo que filtrar. Se combinan entre sí y con las **etiquetas del contrato**, de abajo.
- Cada tarjeta muestra el **método**, el **nombre** (con el **estado de su última ejecución** al lado, si ya corrió alguna vez), la **ruta** y el número de aserciones, y estos botones:

| Botón | Acción |
|---|---|
| ▶ **Ejecutar** | Ejecuta el caso en el ambiente elegido y muestra el resultado. |
| ✎ **Editar** | Abre el editor. |
| ⧉ **Duplicar** | Crea «nombre (copia)». |
| 🗑 **Eliminar** | Pide confirmación; no se puede si el caso está en una suite. |

## 8.2 El editor de casos

Se abre con **Nuevo caso**, **Editar** o **Crear caso** desde una operación de un componente.

![Editor de caso: pestaña Petición](img/33-caso-peticion.png)

**Datos generales**

| Campo | Descripción |
|---|---|
| **Nombre del caso** | Obligatorio. |
| **Método** | GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS. |
| **Ruta** | Obligatoria; admite `{{variables}}` (por ejemplo `/api/users/{{id}}`). |
| **Timeout (s)** | Tiempo máximo de espera (1–300; por defecto 20). |
| **Componente (opcional)** y **Operación del contrato** | Al elegir una operación se rellenan método y ruta, y se habilita «validación del contrato». |

**Pestaña Petición**

- **Headers** y **Query params**: filas con nombre y valor (✕ para quitar, **Agregar** para añadir).
- **Body JSON**: cuerpo de la petición. Se valida al guardar; si no es JSON válido se te indica el error.

**Pestaña Aserciones**

![Editor de aserciones](img/34-caso-aserciones.png)

Cada regla se evalúa contra la respuesta; **el caso pasa solo si todas pasan**. Elige el tipo en el desplegable y completa sus campos (JSONPath, header, valor esperado…). Los 26 tipos están en el [capítulo 20](#cap-20). Botones:

- **Agregar aserción**: nueva regla (código HTTP 200 por defecto).
- **Agregar validación del contrato**: toma el **JSON Schema de la respuesta 2xx** de la operación del contrato elegida y lo agrega como aserción. Si el contrato no declara schema para esa operación, se te dice.

Para el tipo **«Cuerpo JSON idéntico al esperado»** se muestra un área con el JSON esperado y un campo **Ignorar (JSONPath, coma)**.

**Pestaña Encadenamiento**

![Encadenamiento: extraer valores de la respuesta](img/35-caso-encadenamiento.png)

Sirve para **extraer valores de la respuesta** y usarlos como `{{variables}}` en los casos siguientes de una suite (por ejemplo, el token de un login).

| Campo | Descripción |
|---|---|
| **Guardar como** | Nombre de la variable (`token`). |
| **Origen** | **JSONPath del body**, **Header**, **Código HTTP** o **Regex del body** (usa el primer grupo de captura si existe). |
| **Ruta / nombre / patrón** | `$.token`, el nombre del header, o la expresión regular. |

Si una extracción no encuentra el valor, el caso termina como **Falló** indicando qué no se pudo extraer.

**Barra inferior**

- **Ambiente de prueba**: ambiente para **Guardar y ejecutar**.
- **Guardar**: valida y guarda (se verifica nombre, ruta, que cada aserción esté completa, que haya **al menos una aserción**, que el body sea JSON y que las extracciones tengan nombre y ruta).
- **Guardar y ejecutar**: guarda y ejecuta de inmediato en el ambiente elegido.
- **Volver**.

> Cuando abres un caso para editarlo, LTW detecta si **otra persona lo modificó mientras tanto** y, en ese caso, no sobrescribe: te pide recargar.

## 8.3 El resultado de una ejecución

Al ejecutar un caso se abre un cuadro con:

- El **estado** (**Pasó**, **Falló** o **Error**), el nombre y la fecha.
- Código HTTP y tiempo; la petición (`MÉTODO URL`).
- Las **reglas de enriquecimiento aplicadas** (en flujos), con ✎.
- **Petición enviada (lo que salió)**: query y body tal como se enviaron (secretos ocultos).
- Cada **aserción** con ✓/✗ y, si falló, el valor obtenido.
- Las **variables extraídas**.
- **Respuesta** (desplegable) con el cuerpo.
- Si falló: **Brief para agente** (ver [capítulo 17](#cap-17)).

**Estados**

| Estado | Significado |
|---|---|
| **Pasó** | Todas las aserciones y extracciones se cumplieron. |
| **Falló** | Hubo respuesta pero alguna aserción o extracción no se cumplió (o el caso no tiene aserciones). |
| **Error** | No hubo respuesta o no se pudo enviar: servicio caído, tiempo agotado, **variable sin resolver**, secreto faltante, URL inválida, regla de enriquecimiento imposible. |

> **Variables sin resolver.** Si la ruta, headers, query o body contienen `{{algo}}` sin valor, el caso **no se envía** y termina en **Error** indicando cuáles faltan. Define la variable en el ambiente, el caso o la suite.

---

# 9. Casos UI (pruebas de navegador)

Un **caso UI** ejecuta una secuencia de pasos en un **navegador real** (Chromium, sin ventana) y comprueba que la página se comporte como esperas. Requiere Chromium instalado (`python -m playwright install chromium`).

## 9.1 Un solo espacio de trabajo

![El espacio de trabajo de Casos UI: historial/guardados a la izquierda, pasos al centro, herramientas a la derecha](img/58-casos-ui-workspace.png)

Casos UI es, como el [Espacio de trabajo](#cap-6) de las peticiones de API, **una sola pantalla con tres zonas** en vez de una lista y un editor separados: navegar, grabar, editar los pasos y guardar ocurren sin cambiar de página.

| Zona | Qué tiene |
|---|---|
| **Izquierda** | Pestañas **Historial** (ejecuciones de casos UI, agrupadas por día) y **Guardados** (**todos** los casos del proyecto, API y UI juntos — el mismo panel que el Espacio de trabajo). Clic en una fila para cargarla. |
| **Centro** | El nombre del caso, los controles de **Navegador** y la lista de **Pasos** (el contenido del caso). |
| **Derecha** | Herramientas: **Grabador** (pegar un script) y **Guardar** (ambiente, timeout, guardar/ejecutar/eliminar). |

- Clic en una fila de **Guardados** de un caso UI lo carga completo (nombre, pasos) para seguir editándolo. Clic en un **caso API** te lleva al [Espacio de trabajo](#cap-6) con ese caso ya cargado: un caso es un caso, sin importar dónde se creó. Cada fila muestra, junto al nombre, el **estado de su última ejecución** si ya corrió alguna vez.
- Clic en una fila de **Historial** carga una **copia editable** de los pasos que se ejecutaron entonces (útil para ajustar y volver a intentar sin tocar el caso guardado) y abre el detalle de esa ejecución (capturas, traza).
- El icono 📄+ junto al nombre empieza un caso nuevo en blanco.

> **Por qué el historial no se mezcla y los guardados sí.** Un caso guardado es el mismo concepto, sea API o UI: por eso **Guardados** los lista juntos. El **Historial** de cada pantalla, en cambio, muestra cosas distintas a propósito (aquí, ejecuciones de casos UI; en el Espacio de trabajo, cada petición que mandaste, guardada o no). Para ver **todas** las ejecuciones juntas, con filtro por tipo, está [Historial](#cap-13) en el menú principal.

## 9.2 Navegador: solo navegar o grabar

Arriba, separado a propósito de construir una petición de API (eso vive en el Espacio de trabajo): abre un **navegador real y aparte, en tu escritorio** (no dentro de la pantalla de LTW).

- **Protocolo** y **Dirección**: por ejemplo `http` y `localhost:4200/auth/login`.
- **Navegar**: abre una ventana para que explores el sitio con tus manos; no cambia el caso.
- **Grabar**: abre el navegador **con el grabador de Playwright (Codegen)**. Haz en la ventana lo que quieras probar y **ciérrala**: LTW importa la grabación y **agrega los pasos al final** de los que ya tenías, con un aviso de cuántos se importaron y cuáles instrucciones no se soportaron.

> Si la dirección no responde, o el protocolo está mal (por ejemplo `https` contra un servicio que solo habla `http`), el aviso en pantalla dice el motivo exacto (p. ej. `net::ERR_SSL_PROTOCOL_ERROR`): no hace falta adivinar por qué la ventana se cerró sola.

## 9.3 Los pasos

![Un caso cargado, con sus pasos reales listos para editar](img/59-casos-ui-pasos-cargados.png)

Los pasos son el contenido principal del caso, en el centro de la pantalla. Cada paso es una tarjeta con:

| Elemento | Descripción |
|---|---|
| **Acción** | Qué hacer (tabla abajo). |
| **Tipo de locator** | Cómo encontrar el elemento: **Etiqueta (label)**, **Texto**, **Rol ARIA**, **data-testid** o **Placeholder**. |
| **Valor** del locator | Para **Rol ARIA**: el **rol** (button, link, heading, textbox…) y el **nombre accesible**. |
| **1º** | Casilla: usa solo el **primer** elemento que coincida (evita el error cuando hay varios). |
| Campos de la acción | URL, valor a escribir, valor esperado… según la acción. |
| ⬆ ⬇ 🗑 | Subir, bajar, quitar el paso. |

**Acciones disponibles**

| Acción | Qué hace | Campos |
|---|---|---|
| **Ir a URL** | Navega a una ruta del ambiente o a una URL completa **del mismo host**. | URL |
| **Clic** | Hace clic. | locator |
| **Escribir texto** | Rellena un campo. | locator, valor |
| **Presionar tecla** | Pulsa una tecla (`Enter`, `Tab`…). | locator, valor |
| **Marcar / Desmarcar casilla** | Casillas de verificación. | locator |
| **Elegir opción** | Selecciona una opción de una lista. | locator, valor |
| **Esperar visible** | Espera a que aparezca el elemento. | locator |
| **Verificar visible / oculto** | Comprueba (esperando hasta el timeout) que se vea o no. | locator |
| **Verificar texto** | El texto del elemento contiene lo esperado. | locator, esperado |
| **Verificar valor** | El valor de un campo es el esperado. | locator, esperado |
| **Verificar URL contiene** | La URL actual contiene el texto. | esperado |

Los valores admiten `{{variables}}` y `{{secret:NOMBRE}}`. El texto, la etiqueta y el placeholder coinciden por **contenido parcial** (como Playwright); un locator `exact` es una opción de las grabaciones.

> **Verifica contenido, no solo la URL.** Un paso «Verificar URL contiene» puede pasar aunque la página aún no haya cargado o sea una página de error. Termina tus casos con **Verificar visible** o **Verificar texto** sobre algo propio de la página correcta.

**Seguridad del navegador.** Durante la ejecución solo se permiten navegaciones al **host del ambiente** (su **URL base de la interfaz** o, si no hay, la URL base). Si una redirección o paso intenta ir a otro host, se **bloquea** y el caso falla con «Navegación fuera del host autorizado». Esto impide, por ejemplo, probar Google y YouTube en un mismo caso: usa **un caso por sitio**.

**Evidencias.** Cada ejecución guarda una **captura de pantalla** (siempre) y una **traza de Playwright** si falló; se descargan desde el detalle de la ejecución.

## 9.4 Grabador: pegar un script (sin abrir un navegador)

![La pestaña Grabador del panel derecho](img/60-casos-ui-grabador-rail.png)

En el panel derecho, la pestaña 🎬 **Grabador** es la alternativa a grabar en vivo: pega el **script de Codegen** que ya tengas (de otra sesión, de un compañero, de un archivo) y pulsa **Analizar script**. Muestra cuántos pasos se reconocieron y una lista de **instrucciones no soportadas** (con línea y motivo; por ejemplo selectores CSS, `evaluate`, `wait_for_timeout`); **Agregar pasos al caso** los suma a los que ya tenías.

**Qué se importa** (en vivo o pegado): navegar, clic, escribir, presionar tecla, marcar/desmarcar, elegir opción y verificaciones de visibilidad/texto/valor, con locators `label`, `texto`, `rol`, `testid` o `placeholder` (con `.first` / `.nth(n)`). **Lo demás se informa pero no se importa.**

> **El script nunca se ejecuta.** LTW lo analiza como texto; cualquier otra llamada, `import` o código se ignora y se te avisa. Revisa los pasos importados y añade tus verificaciones de contenido.

## 9.5 Guardar y ejecutar

En la pestaña 💾 **Guardar** del panel derecho: **Ambiente de prueba**, **Timeout por paso (ms)** (por defecto 10 000), y los botones **Guardar**, **Guardar y ejecutar** (abre el resultado con los pasos, captura y traza) y, si el caso ya existe, **Eliminar caso**.

---

# 10. Suites y flujos entre componentes

Una **suite** es una lista ordenada de casos (API y UI) que se ejecutan **en secuencia**. Un **flujo** es una suite cuyos pasos apuntan a **distintos ambientes (componentes)** y se alimentan unos de otros — por ejemplo, un frontend que inicia sesión y dos backends que responden a esa sesión.

## 10.1 La lista de suites

![Lista de suites](img/40-suites.png)

Cada tarjeta muestra el nombre (con el **estado de su última ejecución** al lado, si ya corrió alguna vez) y un resumen: número de casos, **ruta de ambientes** (`Identidad → Pedidos` si cruza componentes), política de fallo, reintentos y cuántos pasos están enriquecidos. Botones: ▶ **Ejecutar**, ✎ **Editar**, 🗑 **Eliminar** (no se puede si tiene programaciones). Con el checkbox de cada tarjeta marcado, **Ejecutar seleccionados** corre solo esos; **Eliminar seleccionados** los borra de una vez (misma confirmación, y el mismo límite: no borra uno con programaciones).

![Resultado de ejecutar una suite](img/41-suite-resultado.png)

**Ejecutar** abre un cuadro con el progreso («n de m casos terminados») y un botón **Cancelar ejecución**. Al terminar muestra el resultado de cada paso (alias, caso, ambiente, intentos) con **Ver detalle** para abrir cada uno.

## 10.2 El editor de suites

![Editor de suite o flujo](img/42-suite-editor.png)

**Parte superior**

| Campo | Descripción |
|---|---|
| **Nombre** | Nombre de la suite. |
| **Ambiente por defecto** | Donde corren los pasos que no indican otro. |
| **Política de fallo** | **Continuar tras un fallo** (ejecuta todo) o **Detener al primer fallo** (el resto queda **Omitido**). |
| **Reintentos por caso** | 0 a 5: cuántas veces reintentar un caso que no pasa. |
| **Espera entre reintentos (s)** | 0 a 300. |

**Casos disponibles** (izquierda): lista filtrable de los casos del proyecto; **＋** agrega uno **al final** de la suite. **Orden de ejecución** (derecha): los pasos, cada uno con:

| Elemento | Descripción |
|---|---|
| **Nombre del paso** (alias) | Identifica el paso; los pasos posteriores lo usan para referirse a su respuesta (`login`, `pedido`). Letras, números, `_` y `-`; único en la suite. |
| **Ambiente** | **Ambiente por defecto** u otro del proyecto: así un paso puede llamar al componente A y el siguiente al componente B. |
| **Enriquecer** | Abre las reglas de enriquecimiento (solo casos API). Muestra cuántas reglas tiene. |
| ⬆ ⬇ ✕ | Reordenar o quitar. |

**Variables compartidas iniciales** (desplegable): valores disponibles como `{{nombre}}` en todos los casos. Además, **los valores extraídos** por un caso que pasó (pestaña *Encadenamiento* del caso) se suman para los pasos siguientes.

**Guardar**, **Guardar y ejecutar** o **Volver**. Si alguien más modificó la suite mientras la editabas, LTW lo detecta y no sobrescribe.

> Un paso solo puede usar respuestas de pasos que estén **antes** que él; si reordenas, se vuelve a validar al guardar.

## 10.3 Enriquecer un paso (pasar datos de un componente a otro)

![Diálogo de enriquecimiento con vista previa](img/43-suite-enriquecer.png)

El **enriquecimiento** modifica **lo que se enviará en ese paso**, usando datos de **pasos anteriores**. Es una herramienta para **personas técnicas**, pensada **solo** para agregar los campos que necesita la siguiente entrada o modificar la petición siguiente. No cambia el caso: solo aplica dentro de esa suite.

Cada **regla** tiene:

| Parte | Opciones |
|---|---|
| **Acción** | **Asignar / agregar** · **Quitar** · **Combinar objeto** |
| **Destino** | **Body** (con ruta JSON `$.cliente.id`) · **Header** (nombre) · **Query** (nombre) · **Ruta** (reemplaza la ruta de la petición) |
| **Origen del valor** (para Asignar y Combinar) | **Valor fijo** (número, `true/false`, JSON o texto) · **Respuesta de un paso anterior** (paso + ruta, p. ej. `login` + `$.token`; vacío = toda la respuesta) · **Variable** · **Texto con referencias** (p. ej. `Bearer {{@login:$.token}}`) |

Notas:

- Un valor tomado de una respuesta **conserva su tipo**: un objeto se inserta como objeto, un número como número.
- `{{@paso:$.ruta}}` inserta un valor de la respuesta del paso dentro de un texto. `{{variable}}` y `{{secret:NOMBRE}}` también funcionan.
- **Asignar** crea los niveles intermedios si no existen (`$.cliente.direccion.ciudad`). No sobrescribe en silencio un valor que no sea objeto/lista.
- **Combinar** mezcla un objeto de origen dentro del objeto indicado (o del body completo).

**Vista previa.** Pulsa **Vista previa** para ver el request resultante (método y ruta, headers —con tokens ocultos—, query y body) con la **última respuesta registrada** de cada paso anterior, las reglas aplicadas (✓), los problemas (✗) y qué pasos aún no tienen datos («ejecuta la suite una vez»). **No envía nada.**

**Garantías.** Una regla solo puede apuntar a pasos *anteriores* (se valida al guardar). Si en la ejecución falta el dato o el paso previo falló, el paso termina en **Error** con el motivo (por ejemplo, «`$.token` no existe en la respuesta del paso `login`») **sin enviar nada** al componente siguiente. El historial guarda lo que **salió** (body y query, con secretos ocultos) y las reglas aplicadas.

## 10.4 Ejemplo completo de flujo

*«Iniciar sesión en Identidad y crear un pedido en Pedidos con el token y el nombre del usuario.»*

1. Casos: **Login** (POST `/api/login`; extrae `token` y `usuario`) y **Crear pedido (componente Pedidos)** (POST `/api/items`, espera 201).
2. Suite **Flujo identidad → pedidos**, ambiente por defecto **Catálogo/Identidad**:
   - Paso 1: `login`, ambiente por defecto.
   - Paso 2: `pedido`, ambiente **Pedidos**, con tres reglas:
     1. Asignar **Header** `Authorization` ← **Texto** `Bearer {{@login:$.token}}`.
     2. Asignar **Body** `$.name` ← **Respuesta del paso** `login`, ruta `$.user.name`.
     3. Asignar **Body** `$.origen` ← **Valor fijo** `web`.
3. **Vista previa** para confirmar, **Guardar y ejecutar**.

## 10.5 Chat (conversar en vivo con un chatbot o API conversacional)

Pantalla propia en el menú (**Chat**), separada del Espacio de trabajo: pensada para un chatbot, un agente de IA o cualquier servicio de mensajería (WhatsApp), donde armar los turnos de antemano como una suite no sirve para **explorar** — acá escribís un mensaje a la vez y ves la respuesta como burbuja, como en un chat real.

![Chat: URL arriba, parámetros colapsables, conversación al centro, barra de escribir siempre visible abajo](img/23-chat.png)

- **Arriba**: ambiente, método y URL (igual que el Espacio de trabajo), más un selector para **abrir un caso guardado** y empezar desde ahí.
- **Parámetros** (panel colapsable): headers de la petición, y el **mapeo del chat** — cuatro rutas JSON según el contrato del bot: dónde va el **mensaje saliente**, dónde va el **id de hilo en la petición**, dónde viene el **id de hilo en la respuesta**, y dónde viene la **respuesta del bot**. Se completa una sola vez por caso; **Guardar configuración** la deja lista y colapsa el panel. Hay una quinta ruta **opcional**, **«Ruta de las opciones de respuesta»**: si el bot manda botones de respuesta rápida (una lista de opciones para elegir, en vez de solo texto libre), poné ahí la ruta a esa lista — p. ej. `$.conversation.replies[0].options` — y quedan pintados como botones tocables debajo de esa respuesta (ver más abajo). Como el campo donde viaja esa lista cambia de bot en bot, no está fijo: cada acepta `{"label": "..."}` / `{"text": "..."}` / `{"id": "..."}` / un string suelto — lo que tenga, se usa como texto del botón. Vacío si el bot no manda opciones.
- **Conversación** (área central): cada mensaje se arma con lo que escribiste más el id de hilo actual, se envía, y la respuesta se extrae y aparece como burbuja del bot (con el código HTTP) — la pantalla sigue el scroll automáticamente a cada turno nuevo, no hace falta bajar a mano para ver lo último. El id de hilo (mostrado arriba, junto a **Reiniciar conversación**) se actualiza solo para el siguiente turno. Si esa respuesta trae opciones (según la ruta configurada arriba), aparecen como botones debajo de la burbuja — tocar uno manda su texto como tu próximo mensaje, igual que si lo hubieras tipeado.
- **Íconos de acción** (al lado derecho de cada turno respondido, compactos, con leyenda al pasar el mouse):
  - 🔖 **Guardar este intercambio como caso**: convierte ESE turno puntual en un caso y lo agrega como paso a la suite de la conversación en el momento, sin esperar a terminar de conversar ni guardar turnos que no sirvieron. Un turno ya guardado muestra un ✓ en su lugar (con el número de turno en la leyenda).
  - 🔍 **Ver detalle y evidencia** (también en cualquier error de ese turno): abre el mismo detalle que usa el Historial, con petición, respuesta y aserciones, y las mismas descargas (HTML, PDF, Word, Markdown) y «Enviar a Jira/Azure DevOps» — aunque el Chat **no guarda** sus turnos en el Historial (pensado para explorar, no para quedar registrado). El detalle solo vive mientras la pantalla está abierta: se arma al vuelo, no al reabrir una conversación retomada. Como un turno de chat no define aserciones (eso solo pasa a tenerlas si lo guardás como caso), un turno con una respuesta HTTP sin error se marca **Pasó**, no «Falló» — a diferencia de un caso guardado, donde sin aserciones nunca hay nada que confirmar.
  - `</>` **Petición/Respuesta**: revela, debajo de ESE turno (lo que se mandó + lo que llegó, una sola llamada), el JSON exacto enviado y recibido — para depurar sin abrir el diálogo de evidencia. Oculto por defecto para no ocupar espacio en pantalla. Debajo de la conversación queda además **Petición / Respuesta (último turno)**, con lo mismo del mensaje más reciente, visible sin desplazarse por todo el historial.
- **Acciones de la conversación** (ícono **+**, tanto arriba junto a «Nombre del flujo» como abajo pegado a la barra de escribir — las dos copias se abren y cierran juntas): cuatro íconos compactos, siempre al alcance sin tener que scrollear una conversación larga.
  - 📋 **Guardar todo lo pendiente**: guarda de una sola vez todos los turnos que aún no se guardaron — un caso por mensaje, encadenados con el mismo mecanismo de enriquecimiento que cualquier otra suite (el id de hilo del turno anterior se inyecta en el siguiente, ver [10.3](#s-10-3)) — bajo el nombre del campo **«Nombre del flujo»** (arriba, al lado del **+**).
  - 🔍 **Evidencia de la conversación**: un solo reporte con **todos los turnos respondidos** hasta ese momento, no uno por uno. Abre un diálogo con un casillero por turno (tildados todos por defecto, destildá los que no quieras incluir) y las mismas cuatro descargas (HTML, PDF, Word, Markdown); cada turno incluido trae su petición, respuesta y código HTTP, igual que «Ver detalle y evidencia» de un turno suelto.
  - ▶ **Reproducir conversación** y 🎬 **Retomar un Flujo guardado**: ver más abajo.
- **La conversación se puede retomar**: después de cada turno se guarda en el caso (mensajes, id de hilo y qué se guardó ya como caso); cerrar la pantalla y volver a abrir el mismo caso restaura todo tal como quedó, listo para seguir escribiendo — no hace falta terminar de una sola vez. Por eso mismo, elegir una Plantilla o «Retomar conversación» deja el id del caso en la URL (`/chat?case=...`): si la pestaña queda un rato sin usarse y el navegador se reconecta recargando la página — lo más común si no se estuvo escribiendo —, la conversación se restaura en vez de aparecer en blanco.
- **Reiniciar conversación** borra los mensajes y el hilo (también lo que estaba guardado para retomar) sin tocar la configuración del mapeo. **Nuevo chat** (icono junto al nombre) empieza de cero en otro caso; abrir uno que ya tiene el mapeo guardado va directo a la conversación, sin repetir las cuatro rutas.
- **Reproducir conversación** / **Retomar un Flujo guardado** (dentro de «Acciones de la conversación», arriba): reenvían, en orden y en vivo contra el bot, los mensajes que ya escribiste (el primero) o los de un Flujo guardado con este chat (el segundo) — sin tener que volver a tipearlos. Ambos reemplazan lo que haya en pantalla de ahí en adelante y ofrecen las mismas dos opciones: **usar un hilo nuevo** (el bot arranca de cero, recomendado para repetir la conversación tal cual) o seguir en el hilo actual, y **empezar pausado** (paso a paso — se detiene antes de CADA turno, incluido el primero, como una casetera parada) o arrancar en reproducción continua. Mientras reproduce aparece una barra con el turno actual y controles ▶ reproducir seguido, ❙❙ pausar, ⏭ un paso, ⏩ **saltar**, ■ detener acá. **Saltar** no reenvía el texto grabado de ese paso — para cuando ya lo respondiste vos a mano (con un texto distinto del grabado, escribiéndolo en la barra de abajo) y querés que la reproducción siga con la próxima pregunta en vez de repetir la que ya contestaste. Útil también para retomar una conversación larga desde un punto intermedio sin repetir manualmente todo lo anterior.
