---

# 6. Espacio de trabajo

El **Espacio de trabajo** es la pantalla principal de LTW: un lugar donde **probar, editar y decidir sin cambiar de pantalla**. Está dividido en tres zonas que puedes redimensionar arrastrando los separadores verticales (LTW recuerda tu disposición en ese navegador).

![Espacio de trabajo vacío: historial a la izquierda, trabajo al centro, inspector a la derecha](img/10-espacio-vacio.png)

| Zona | Qué contiene |
|---|---|
| **Izquierda** | **Historial** de tus peticiones y **Guardados** (casos y suites del proyecto). |
| **Centro** | La **barra de petición** y la **respuesta** con sus pestañas. |
| **Derecha** | El **inspector**: Params, Headers, Body, Pruebas, Variables, Lote, Guardar y Agente. Un riel de iconos a la derecha cambia de panel; al pasar el ratón sobre un icono ves su nombre. |

> **No necesitas un proyecto para explorar.** Puedes enviar peticiones sin proyecto ni ambiente. Los eliges cuando decides **guardar**. Las peticiones enviadas quedan en tu propio historial aunque no las guardes como caso.

## 6.1 La barra de petición

De izquierda a derecha:

| Control | Función |
|---|---|
| **Nombre** (arriba) | Nombre de la petición. Se usa al guardar. Un distintivo indica si viene **Del historial** o es un **Caso guardado**. |
| **Ambiente** | **URL completa** (por defecto) o un ambiente existente. Con ambiente, escribes solo la ruta (`/api/users/1`) y la URL base, las variables y la autenticación del ambiente se aplican solos. |
| **Método** | GET, POST, PUT, PATCH, DELETE, HEAD u OPTIONS. |
| **Proto.** (protocolo) | **https** por defecto, o **http**. Solo aparece cuando no hay ambiente. Si pegas una URL completa con `http://` o `https://`, el selector la sigue. |
| **URL** | Dirección completa (`ejemplo.com/api/recurso`) o ruta si hay ambiente. Admite `{{variables}}`. Si escribes solo `ejemplo.com/ruta`, se agrega el protocolo elegido. |
| **Enviar** | Envía la petición. Atajo: **Ctrl+Enter** desde cualquier campo. |

Botones de la fila superior (a la derecha del nombre):

| Botón | Acción |
|---|---|
| 📄+ **Nueva petición** | Limpia el editor. |
| 📶 **Conectividad** | Comprueba DNS, TCP, TLS (si es https) y un GET sobre la URL; el resultado se muestra en la pestaña **Conectividad** de la respuesta. No guarda nada. |
| ⌨ **Copiar como curl** | Copia el comando `curl` equivalente al portapapeles. |

> El **navegador real** (solo navegar, o navegar grabando para crear un caso UI) no está aquí: vive en **Casos UI**, porque no tiene que ver con construir una petición de API. Ver el capítulo 9.

Debajo de la barra, la fila **Variables** muestra las `{{variables}}` detectadas: en **verde** las que tienen valor (en el ambiente o en la pestaña **Variables**), en **ámbar** las que faltan.

> **Importante.** Si una variable no tiene valor, la petición **no se envía** y se te indica cuáles faltan. Nunca se manda un `{{id}}` literal a tu servicio.

## 6.2 La respuesta

![Respuesta con el cuerpo JSON](img/11-espacio-respuesta.png)

Al enviar, el centro muestra el **código HTTP** (verde 2xx, ámbar 3xx, rojo 4xx/5xx), el **tiempo** y el tamaño. Si hay pruebas, aparece un distintivo `n/m pruebas`. Si la petición no obtiene respuesta (servicio caído, tiempo agotado) verás el motivo en rojo.

Pestañas:

| Pestaña | Contenido |
|---|---|
| **Cuerpo** | El cuerpo de la respuesta. Para JSON puedes alternar **Texto** y **Árbol** (plegable). Debajo se listan los **campos que suelen cambiar** (fechas, identificadores…) que LTW sugiere ignorar. Hasta 200 000 caracteres. |
| **Headers** | Los headers de la respuesta. |
| **Pruebas** | Resultado de cada aserción: ✓ pasó o ✗ falló con el valor obtenido. |
| **Diff** | Compara con la respuesta anterior **de esta misma petición** (mismo método y URL) y lista las diferencias campo a campo. |
| **Conectividad** | Resultado de la prueba de conectividad (aparece solo si la ejecutaste). |
| **Lote** | Resultados de un lote de parámetros (aparece solo si ejecutaste un lote). |

![Árbol plegable de la respuesta](img/12-respuesta-arbol.png)

![Headers de la respuesta](img/13-respuesta-headers.png)

![Diff contra la respuesta anterior tras un cambio en el servicio](img/28-respuesta-diff.png)

## 6.3 El panel izquierdo

### Historial

Cada petición que envías se guarda **automáticamente**, aunque no la guardes como caso.

- **Agrupado por día** (Hoy, Ayer, fechas), con el método, el nombre (o la ruta), el host y el código de respuesta.
- **Un clic** carga la petición en el editor **tal como la enviaste** (URL, headers, body, pruebas) junto con la respuesta que obtuvo.
- **⭐ Estrella**: marca la petición para conservarla; las marcadas no se borran al limpiar ni por antigüedad.
- **Buscar**: filtra por nombre o ruta.
- **Interruptor «solo mías»**: con la base de datos compartida, alterna entre tus peticiones y las de todas las personas (se muestra el autor).
- **Limpiar historial**: borra tus peticiones no marcadas (pide confirmación).
- Se conservan las últimas **300** por persona; el cuerpo de respuesta guardado se limita a 100 000 caracteres.

### Guardados

![Casos (API y UI) y suites guardados](img/14-izquierda-guardados.png)

Lista las **suites** y **todos los casos** del proyecto activo — **API y UI juntos**: un caso es un caso, sea cual sea el tipo de prueba. Cada uno se distingue por su insignia (método HTTP) o por el icono 🌐.

- **Un clic en un caso API** lo abre aquí mismo, en el editor, para modificarlo. Al guardar puedes **actualizarlo** (ver 6.5).
- **Un clic en un caso UI** te lleva a [Casos UI](#cap-9) con ese caso ya cargado: ahí viven sus herramientas (navegador, pasos).
- **▶ junto a una suite** la ejecuta y muestra el resultado.

> La pantalla de **Casos UI** tiene el mismo panel, con la misma lista completa: un clic en un caso API desde ahí te trae de vuelta aquí, con ese caso cargado (`/workspace?case=…`).

## 6.4 El inspector (derecha)

El riel de iconos (a la derecha) cambia el panel. De arriba abajo:

| Icono | Panel | Resumen |
|---|---|---|
| ⚙ | **Params** | Parámetros de la query. |
| ☰ | **Headers** | Cabeceras de la petición. |
| `{ }` | **Body** | Cuerpo JSON con editor. |
| ✓ | **Pruebas** | Aserciones y generación automática. |
| `[ ]` | **Variables** | Variables y extracciones. |
| ▤ | **Lote** | Misma petición con varias entradas. |
| 💾 | **Guardar** | Destino y modo de guardado. |
| 🤖 | **Agente** | Protocolo para agentes. |

### Params y Headers

![Panel de Params](img/15-inspector-params.png)

![Panel de Headers con la fila de autorización agregada](img/16-inspector-headers.png)

Ambos paneles funcionan igual:

- Cada fila tiene una **casilla** (activa = se envía; desactivada = se conserva pero **no** se envía), un **nombre**, un **valor** y una **✕** para quitarla.
- **Agregar** crea una fila vacía. En **Headers** hay atajos: **+ Content-Type**, **+ Accept** y **+ Bearer** (agrega `Authorization: Bearer {{secret:TOKEN}}`).
- El interruptor **Texto** cambia a **edición masiva**: una línea por elemento con el formato `Nombre: valor` (también `nombre=valor`). Una línea que empieza con `#` queda **desactivada**. Al salir del cuadro se aplican los cambios.
- Los parámetros que escribas dentro de la URL (`?pagina=2`) se **combinan** con los de **Params**.
- La autenticación del ambiente (Bearer o API Key) se agrega sola; no hace falta escribirla.
- Puedes usar `{{variables}}` y `{{secret:NOMBRE}}` en nombres y valores.

### Body

![Editor de body JSON](img/17-inspector-body.png)

- Editor con **resaltado** de JSON y numeración de líneas.
- El distintivo indica **vacío**, **JSON válido** o **JSON inválido** (al pasar el ratón ves el error).
- Botones: **Formatear** (sangría de 2 espacios), **Minificar** y **Usar la última respuesta** (copia el cuerpo de la respuesta actual como body de la petición; útil para reenviar lo recibido con cambios).
- Solo se admite **JSON**. Dentro de textos puedes usar `{{variables}}`.

### Pruebas

![Panel de Pruebas con reglas generadas](img/18-inspector-pruebas.png)

Define lo que debe cumplir la respuesta.

- Cada **regla** tiene un tipo (lista completa en el [capítulo 20](#cap-20)), sus campos y una ✕ para quitarla. Tras **Enviar**, un icono ✓/✗ aparece junto a cada regla y, si falla, el valor obtenido.
- **Agregar prueba** crea una regla `Código HTTP igual a 200`.
- **Generar desde la respuesta actual** crea reglas a partir de lo que respondió el servicio:
  - **Respuesta exacta (ignorando campos volátiles)**: el cuerpo JSON debe ser **idéntico**, salvo los campos listados en **Ignorar campos**.
  - **Solo estructura (JSON Schema)**: debe tener los mismos campos y tipos.
  - **Solo código HTTP**.
  Los **campos que suelen cambiar** (fechas, UUID, tokens, marcas de tiempo) se rellenan solos en **Ignorar campos** tras enviar. Puedes editarlos (JSONPath separados por coma, por ejemplo `$.requested_at, $.items[*].id`).
- **Generar pruebas reemplaza** las reglas actuales.

![Pestaña Pruebas de la respuesta](img/19-respuesta-pruebas.png)

> **Pruebas deterministas.** «Respuesta exacta» funciona bien cuando las **entradas son fijas** (el mismo id, el mismo cuerpo): lo que cambie en el servicio, o un campo volátil que no ignoraste, hará fallar la prueba. Si la respuesta depende de datos que cambian en el sistema probado (por ejemplo, una lista que crece), usa datos de prueba estables o la opción **Solo estructura**.

### Variables

![Panel de Variables](img/20-inspector-variables.png)

- **Variables de esta petición**: pares nombre/valor disponibles como `{{nombre}}` en la URL, headers, query y body. Se guardan con el caso.
- **Extraer de la respuesta** (para encadenar en una suite): **Guardar como** + **Ruta** (por ejemplo `$.token`). Cuando el caso se ejecute dentro de una suite, el valor queda disponible como `{{nombre}}` en los casos siguientes.
- Orden de prioridad de las variables (de menor a mayor): **integradas → ambiente → caso → suite/valores extraídos**.
- **Variables integradas**: `{{now_date}}`, `{{now_time}}`, `{{now_iso}}`, `{{now_epoch}}`, `{{uuid}}` y `{{seq}}` (consecutivo global, avanza en cada envío) no requieren configurarlas en ningún lado — se calculan solas en el momento de enviar. Útiles para fechas/horas de proceso, identificadores de correlación o nombres que no pueden repetirse entre ejecuciones. Si defines una variable con el mismo nombre en el ambiente, el caso o la suite, esa gana.

### Chat (conversar en vivo)

Pensada para un chatbot, una API conversacional o cualquier servicio de mensajería (WhatsApp, un agente de IA): a diferencia de una suite, acá **no armas los turnos de antemano** — escribís un mensaje, ves la respuesta como burbuja, y seguís la conversación como en un chat real.

1. La primera vez, indica cuatro rutas JSON (según el contrato del bot): dónde va el **mensaje saliente**, dónde va el **id de hilo en la petición**, dónde viene el **id de hilo en la respuesta**, y dónde viene la **respuesta del bot**. El resto de la petición (método, URL, headers, autenticación) es el que ya armaste en las otras pestañas.
2. **Activar chat**: a partir de ahí, escribe y pulsa Enter (o el botón de enviar). Cada mensaje se arma solo con lo que escribiste más el id de hilo actual, se envía, y la respuesta se extrae y aparece como burbuja del bot (con el código HTTP). El id de hilo se actualiza solo para el siguiente turno.
3. **Guardar como suite**: convierte la conversación real en una suite de regresión — un caso por mensaje que escribiste, encadenados con el mismo mecanismo de enriquecimiento que cualquier otra suite (el id de hilo del turno anterior se inyecta en el siguiente). Se guarda en el proyecto elegido en la pestaña **Guardar**.
4. **Reiniciar** borra los mensajes y el id de hilo sin tocar la configuración; **Configurar de nuevo** vuelve al formulario de las cuatro rutas (por ejemplo, para apuntar a otro endpoint).

La configuración del chat se guarda con el caso: si vuelves a abrir un caso ya configurado, el chat está listo para escribir sin repetir las rutas.

### Lote (misma petición, varias entradas)

![Lote de parámetros: tres filas con sus resultados](img/22-lote.png)

1. Escribe `{{variables}}` en la petición, por ejemplo `http://servicio/api/users/{{id}}`.
2. Abre **Lote** y pulsa **Actualizar columnas**: aparece una columna por variable.
3. Completa una **fila por valor** (**Agregar fila**), o pega varias líneas (un valor por línea; varias columnas separadas por coma) y pulsa **Cargar filas**.
4. **Ejecutar lote**: cada fila se envía; los resultados aparecen en la pestaña **Lote** de la respuesta (código, tiempo y cuerpo desplegable) y como código junto a cada fila.
5. **Guardar lote como suite**: cada fila se convierte en un **caso** con sus variables fijas y la **respuesta observada como esperada** (según el modo elegido: exacta, estructura o solo código; campos a ignorar). Los casos se agrupan en una **suite de regresión** (o se agregan a una suite existente elegida en **Guardar**).

> Así pruebas **un mismo endpoint con distintos parámetros** y quedas con una suite que, al volver a ejecutarla, te dice **qué filas cambiaron y en qué campo**.

### Guardar

![Panel de Guardar](img/21-inspector-guardar.png)

| Campo | Función |
|---|---|
| **Nombre del caso** | Nombre con que se guarda. |
| **Qué debe cumplir** | **Las pruebas del panel «Pruebas»** (usa las reglas que tienes), **Respuesta exacta**, **Solo estructura** o **Solo código HTTP** (los tres últimos generan las reglas desde la respuesta actual). |
| **Ignorar campos** | Solo con «Respuesta exacta». |
| **Proyecto** | Un proyecto existente o **➕ Crear proyecto nuevo…** (se crea al guardar). |
| **Agregar a una suite existente** | Opcional: agrega el caso al final de esa suite. La suite debe ejecutarse contra el **mismo servidor** que tu petición; si no, LTW lo explica y **no guarda nada**. |
| **Actualizar el caso guardado** | Aparece si abriste un caso desde **Guardados**: guarda los cambios sobre el mismo caso en vez de crear otro. |
| **Guardar** | Crea (o actualiza) el caso. |

Detalles útiles:

- Si no eliges ambiente, LTW **busca o crea** un ambiente en el proyecto destino con el servidor de tu URL (por ejemplo `127.0.0.1:8765`).
- Si usaste un ambiente de **otro proyecto**, se **copia** al proyecto destino (con su autenticación y variables).
- **Conflictos**: si alguien más modificó el mismo caso mientras lo editabas, LTW lo detecta y **no sobrescribe** (verás un aviso para recargar).

## 6.5 Probar conectividad

![Resultado de conectividad: DNS, TCP y HTTP](img/23-conectividad.png)

El botón 📶 comprueba paso a paso por qué un destino responde o no:

| Paso | Qué comprueba |
|---|---|
| **DNS** | Que el nombre se resuelva a una dirección. |
| **TCP** | Que se pueda abrir conexión al puerto. |
| **TLS** | (solo https) Que el certificado y el protocolo se negocien; muestra versión y vencimiento. |
| **HTTP** | Que un `GET` obtenga respuesta; muestra código, tamaño y servidor. |

Cada paso muestra su tiempo. Si uno falla, los siguientes no se ejecutan y el mensaje indica el motivo (por ejemplo, `WRONG_VERSION_NUMBER` al usar **https** contra un servidor que solo habla **http**: cambia el protocolo).

## 6.6 Pestaña Agente

![Pestaña Agente con el brief del último fallo](img/26-inspector-agente.png)

Reúne todo lo relacionado con agentes (se explica en el [capítulo 17](#cap-17)):

- **Brief del último fallo**: cuando una petición con pruebas falla, aquí aparece un informe en Markdown (qué se envió, esperado vs obtenido, respuesta, diagnóstico, dónde mirar, cómo reproducir). Puedes **copiarlo** o **descargar el `failure.json`**.
- **Esta petición como especificación**: exporta lo que estás editando como `ltw.spec/1`.
- **Importar una especificación**: pega un `ltw.spec/1`; se valida (errores y avisos con su ruta) y puedes **cargar el primer caso en el editor** o **importar todo al proyecto** elegido en **Guardar**.
- **API local y línea de comandos**: el **token** (copiar, mostrar, regenerar) y ejemplos de uso.
- **Asistente con modelo de lenguaje**: explica el último fallo o genera casos con un modelo. El selector **Modelo activo** elige, sin volver a pegar URL ni clave, entre los modelos registrados en **Modelos de IA** (menú lateral); «Conexión directa (sin registrar)» sigue disponible para un modelo puntual que no amerita registrarse.

![Una prueba que falla: se ve en rojo qué esperaba y qué obtuvo](img/25-pruebas-fallan.png)

## 6.8 Atajos y trucos

| Acción | Cómo |
|---|---|
| Enviar | **Ctrl+Enter** (en cualquier campo) |
| Rehacer una petición anterior | Clic en el historial → **Enviar** |
| Comparar con la respuesta anterior | Pestaña **Diff** |
| Reenviar lo recibido con cambios | **Body → Usar la última respuesta** |
| Desactivar un header sin borrarlo | Quita la casilla de su fila (o `# ` en modo Texto) |
| Probar rápido un servicio nuevo | Escribe solo `host:puerto/ruta`, elige **http** si no usa TLS y envía |
| Menú | Pasa el ratón por el borde izquierdo para expandirlo |
