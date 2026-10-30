---

# 7. Proyectos, módulos y ambientes

Estos tres elementos preparan el terreno para tus pruebas. Se configuran una vez y se reutilizan.

## 7.1 Proyectos

![Pantalla de Proyectos](img/02-proyectos.png)

Un **proyecto** agrupa módulos, ambientes, casos, suites y programaciones de un mismo producto. Siempre hay **un proyecto activo** (el del selector del encabezado); las pantallas muestran y crean cosas en ese proyecto.

**Crear un proyecto.** En **Nuevo proyecto** escribe el **Nombre** (obligatorio) y una **Descripción** opcional, y pulsa **Crear proyecto**. El primero que crees queda activo automáticamente; cuando creas otros se te selecciona el nuevo.

**Cada proyecto se muestra en una tarjeta** con su nombre, descripción editable y un resumen de recursos (módulos, ambientes, casos, suites, programaciones).

| Acción | Efecto |
|---|---|
| **Guardar cambios** | Actualiza nombre y descripción. |
| **Seleccionar** | Lo convierte en el proyecto activo (también desde el selector del encabezado). |
| **Eliminar** | Pide confirmación. **Solo se puede eliminar un proyecto vacío**; si tiene módulos, ambientes, casos, suites, programaciones o taps, LTW lo impide para no perder trabajo. |

> **Recursos sin proyecto (de versiones anteriores).** Si existen elementos sin proyecto, aparece un aviso **«Asignarlos al proyecto activo»** para adoptarlos; hasta entonces no se ven al filtrar por proyecto.

> **Consejo.** Usa **un proyecto por producto o iniciativa**. Los ambientes, casos y suites no se comparten entre proyectos (al guardar desde el Espacio de trabajo en otro proyecto, el ambiente se copia).

## 7.2 Módulos (contratos OpenAPI/Swagger)

![Un módulo importado con sus operaciones](img/30-modulos.png)

Un **módulo** es la descripción de un servicio: sus operaciones (método + ruta), parámetros y respuestas. Importarlo no es obligatorio, pero habilita funciones muy útiles: crear casos con un clic desde una operación, **validar respuestas contra el contrato** y **comparar lo observado con lo declarado** (Observador).

**Importar.** En **Importar contrato** puedes:

- escribir una **URL** (`http` o `https`) y pulsar **Importar desde URL**; o
- **arrastrar un archivo** `.json`, `.yaml` o `.yml`.

La URL puede ser cualquiera de estas:

| Qué pegas | Qué hace LTW |
|---|---|
| El enlace **directo** al contrato (`…/openapi.json`, `…/swagger.json`, un `.yaml`) | Lo descarga tal cual (sigue redirecciones). |
| La **página de Swagger UI o Redoc** del servicio (por ejemplo `https://petstore3.swagger.io/`, o el `/docs` y `/redoc` de un servicio FastAPI) | Lee la página y sus scripts de arranque, encuentra el contrato que usa y lo importa. Si hay varios, prefiere los del mismo servidor. |
| Un enlace de **GitHub** de un archivo (`github.com/…/blob/…`) | Lo convierte al enlace «raw» y lo descarga. |
| Un servicio que sirve su contrato en una ruta habitual (`/openapi.json`, `/swagger.json`, `/v3/api-docs`…) | Prueba esas rutas si la página no lo enlaza. |

Al terminar, el aviso indica el **origen real** del contrato (por ejemplo, la página `https://petstore3.swagger.io/` resolvió a `…/api/v3/openapi.json`) y el módulo lo recuerda. Si la dirección escrita da error (por ejemplo, la raíz de una API sin página), también prueba esas rutas desde el mismo servidor. Si no encuentra ninguno, te lo dice y puedes pegar la URL directa o subir el archivo. Se prueban como máximo 14 direcciones.

**Servidor declarado y ambiente.** Cuando el contrato indica su servidor (OpenAPI `servers`, o `host` + `basePath` en Swagger 2.0; una dirección relativa se resuelve contra el origen; si no declara ninguno, como hace FastAPI, se usa el servidor desde el que se descargó), el módulo muestra **Servidor declarado** y el botón **Crear ambiente con esta URL**, que crea el ambiente con esa dirección base.

Se aceptan **OpenAPI 3.x** y **Swagger 2.0**, hasta **10 MB**. Tras importar verás un aviso con el nombre y el número de operaciones.

**Referencias `$ref`.** Se resuelven las **locales** (`#/components/...`). Las **externas** (otros archivos o URL) se **rechazan** con un mensaje claro; no se descarga nada desde dentro del documento por seguridad. Los modelos **recursivos** (por ejemplo, un comentario con respuestas que son comentarios) sí se aceptan: la recursión se corta en el punto en que se repite y ahí el esquema queda abierto, de modo que la validación contra el contrato es más permisiva en ese nivel.

**Usar un módulo.** Cada módulo aparece como un desplegable con su nombre, versión y número de operaciones. Dentro, cada operación muestra su **método**, **ruta** y resumen, con el botón **Crear caso**, que abre el editor de caso API con el método y la ruta ya rellenados.

**Eliminar un módulo.** Se bloquea si algún caso lo usa (te dice cuántos).

## 7.3 Ambientes y secretos

![Ambientes y secretos](img/31-ambientes.png)

Un **ambiente** define *dónde* se ejecutan las pruebas.

### Crear o editar un ambiente

| Campo | Descripción |
|---|---|
| **Nombre** | Por ejemplo `QA`, `Preproducción`. |
| **URL base (API)** | Obligatoria, con `http://` o `https://`. Ej.: `https://qa.empresa.com`. |
| **URL base de la interfaz** | Opcional. Solo si tu sitio web está en otra dirección que la API; la usan los **casos UI**. |
| **Autenticación** | **Sin autenticación**, **Bearer token** o **API Key**. |
| **Secreto guardado en el sistema** | Elige un secreto de la lista (ver abajo). |
| **…o variable de entorno** | Alternativa: el nombre de una variable de entorno del sistema (por ejemplo `QA_TOKEN`). |
| **Header (solo API Key)** | Nombre del header donde viaja la clave (por defecto `X-API-Key`). |
| **Variables** | Pares nombre/valor disponibles como `{{nombre}}` en rutas, headers, query, body y pasos UI. |

Pulsa **Nuevo ambiente** y luego **Guardar ambiente**. La lista es una tabla: haz clic en una fila (o en su icono ✎) para editarlo; el 🗑 lo elimina (no se puede si alguna suite lo usa).

Con **Bearer**, LTW envía `Authorization: Bearer <valor del secreto>`; con **API Key**, el header elegido con el valor del secreto. Si falta el secreto o la variable de entorno, el caso termina en **Error** con ese mensaje y **no se envía**.

### Actualización automática de token (opcional)

Con **Bearer** o **API Key** activos, puedes activar «Actualizar automáticamente si falta, expira, o el servicio responde 401»:

| Mecanismo | Qué hace |
|---|---|
| **Petición HTTP** (beta) | Llama a un endpoint (típico de OAuth2: método, URL, headers y body, admiten `{{variables}}` y `{{secret:NOMBRE}}`), extrae el token de la respuesta con una ruta JSONPath (`$.access_token` por defecto) y, si das la ruta de duración (`expires_in`), recuerda cuándo vuelve a vencer. |
| **Comando del sistema** (experimental) | Ejecuta un comando local y toma su salida estándar como el token. El scheduler lo corre sin supervisión en esta máquina: úsalo solo con scripts de confianza. |

El token resultante se guarda en el secreto que indiques (o en el mismo que ya usa el ambiente, si lo dejas vacío). LTW refresca el token **antes** de ejecutar si no hay uno guardado o si ya venció, y además **reintenta una vez** si el servicio responde `401`, sin que tengas que hacer nada. El botón **Probar ahora** lo ejecuta de inmediato (requiere guardar el ambiente primero) para verificar que funciona antes de confiar en él en una programación.

### Secretos (almacén seguro del sistema)

La sección **Secretos** guarda valores sensibles en el **Administrador de credenciales de Windows** (no en la base de datos ni en exportaciones).

1. Escribe el **Nombre** (letras, números, `.`, `_`, `-`) y el **Valor** (campo con ojo para mostrarlo).
2. Pulsa **Guardar secreto**.

Se usan:

- en la autenticación de un ambiente (campo **Secreto guardado en el sistema**);
- en cualquier parte de una petición como **`{{secret:NOMBRE}}`** (por ejemplo, `Authorization: Bearer {{secret:TOKEN_QA}}`).

La lista solo muestra los **nombres** (con `••••••••`); el valor nunca se muestra. Si no existe un secreto con ese nombre, LTW busca una **variable de entorno** con el mismo nombre. Los valores usados **se eliminan** de lo que se guarda en el historial y de los informes.

---

# 8. Casos API

Un **caso API** es una petición HTTP guardada con las **aserciones** que debe cumplir su respuesta. Se crean desde el **Espacio de trabajo** (lo más cómodo) o desde esta pantalla.

## 8.1 La lista de casos

![Lista de casos API](img/32-casos-api.png)

- **Nuevo caso** abre el editor vacío.
- **Ejecutar en ambiente** elige el ambiente para los botones ▶ de la lista. Si no hay ambientes se te avisa.
- Cada tarjeta muestra el **método**, el **nombre**, la **ruta** y el número de aserciones, y estos botones:

| Botón | Acción |
|---|---|
| ▶ **Ejecutar** | Ejecuta el caso en el ambiente elegido y muestra el resultado. |
| ✎ **Editar** | Abre el editor. |
| ⧉ **Duplicar** | Crea «nombre (copia)». |
| 🗑 **Eliminar** | Pide confirmación; no se puede si el caso está en una suite. |

## 8.2 El editor de casos

Se abre con **Nuevo caso**, **Editar** o **Crear caso** desde una operación de un módulo.

![Editor de caso: pestaña Petición](img/33-caso-peticion.png)

**Datos generales**

| Campo | Descripción |
|---|---|
| **Nombre del caso** | Obligatorio. |
| **Método** | GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS. |
| **Ruta** | Obligatoria; admite `{{variables}}` (por ejemplo `/api/users/{{id}}`). |
| **Timeout (s)** | Tiempo máximo de espera (1–300; por defecto 20). |
| **Módulo (opcional)** y **Operación del contrato** | Al elegir una operación se rellenan método y ruta, y se habilita «validación del contrato». |

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

- Clic en una fila de **Guardados** de un caso UI lo carga completo (nombre, pasos) para seguir editándolo. Clic en un **caso API** te lleva al [Espacio de trabajo](#cap-6) con ese caso ya cargado: un caso es un caso, sin importar dónde se creó.
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

# 10. Suites y flujos entre módulos

Una **suite** es una lista ordenada de casos (API y UI) que se ejecutan **en secuencia**. Un **flujo** es una suite cuyos pasos apuntan a **distintos ambientes (módulos)** y se alimentan unos de otros.

## 10.1 La lista de suites

![Lista de suites](img/40-suites.png)

Cada tarjeta muestra el nombre y un resumen: número de casos, **ruta de ambientes** (`Identidad → Pedidos` si cruza módulos), política de fallo, reintentos y cuántos pasos están enriquecidos. Botones: ▶ **Ejecutar**, ✎ **Editar**, 🗑 **Eliminar** (no se puede si tiene programaciones).

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
| **Ambiente / módulo** | **Ambiente por defecto** u otro del proyecto: así un paso puede llamar al módulo A y el siguiente al módulo B. |
| **Enriquecer** | Abre las reglas de enriquecimiento (solo casos API). Muestra cuántas reglas tiene. |
| ⬆ ⬇ ✕ | Reordenar o quitar. |

**Variables compartidas iniciales** (desplegable): valores disponibles como `{{nombre}}` en todos los casos. Además, **los valores extraídos** por un caso que pasó (pestaña *Encadenamiento* del caso) se suman para los pasos siguientes.

**Guardar**, **Guardar y ejecutar** o **Volver**. Si alguien más modificó la suite mientras la editabas, LTW lo detecta y no sobrescribe.

> Un paso solo puede usar respuestas de pasos que estén **antes** que él; si reordenas, se vuelve a validar al guardar.

## 10.3 Enriquecer un paso (pasar datos de un módulo a otro)

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

**Garantías.** Una regla solo puede apuntar a pasos *anteriores* (se valida al guardar). Si en la ejecución falta el dato o el paso previo falló, el paso termina en **Error** con el motivo (por ejemplo, «`$.token` no existe en la respuesta del paso `login`») **sin enviar nada** al módulo siguiente. El historial guarda lo que **salió** (body y query, con secretos ocultos) y las reglas aplicadas.

## 10.4 Ejemplo completo de flujo

*«Iniciar sesión en Identidad y crear un pedido en Pedidos con el token y el nombre del usuario.»*

1. Casos: **Login** (POST `/api/login`; extrae `token` y `usuario`) y **Crear pedido (módulo Pedidos)** (POST `/api/items`, espera 201).
2. Suite **Flujo identidad → pedidos**, ambiente por defecto **Catálogo/Identidad**:
   - Paso 1: `login`, ambiente por defecto.
   - Paso 2: `pedido`, ambiente **Pedidos**, con tres reglas:
     1. Asignar **Header** `Authorization` ← **Texto** `Bearer {{@login:$.token}}`.
     2. Asignar **Body** `$.name` ← **Respuesta del paso** `login`, ruta `$.user.name`.
     3. Asignar **Body** `$.origen` ← **Valor fijo** `web`.
3. **Vista previa** para confirmar, **Guardar y ejecutar**.
