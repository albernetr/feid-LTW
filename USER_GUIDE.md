# Guía de usuario

> Esta es la guía resumida. El **manual completo** (con capturas, recetas por perfil, referencia y solución de problemas) está en [MANUAL_DE_USUARIO.md](MANUAL_DE_USUARIO.md), con versiones [HTML](docs/manual/MANUAL_DE_USUARIO.html) y [PDF](docs/manual/MANUAL_DE_USUARIO.pdf).

## Flujo recomendado

1. **Proyectos** → crea uno (queda activo). El selector del encabezado cambia de proyecto en cualquier momento.
2. **Módulos** → importa el OpenAPI (archivo o URL). Opcional: también puedes crear casos sin contrato.
3. **Ambientes** → URL base, autenticación y variables. Para Bearer/API Key guarda el valor en **Secretos** (almacén del sistema) y elígelo en el ambiente.
4. **Casos API** → *Nuevo caso* o *Crear caso* desde una operación del módulo.
5. **Suites** → agrupa casos, ordénalos, define política de fallo y reintentos.
6. **Programaciones** → programa una suite; deja `scripts\scheduler.bat` abierto.
7. **Historial** → revisa resultados, capturas y trazas.

## Espacio de trabajo (probar, editar y decidir sin cambiar de pantalla)

Menú **Espacio de trabajo** (el menú lateral se compacta a iconos y se expande al pasar el ratón; el botón ☰ lo oculta). Tres zonas que puedes redimensionar arrastrando los separadores (se recuerdan):

**Izquierda — Historial y Guardados**
- *Historial*: todas tus peticiones enviadas, agrupadas por día, con método, ruta y código HTTP. Clic = vuelve al editor tal como la enviaste (con su respuesta). ⭐ la conserva; el buscador filtra; el interruptor alterna entre «solo mías» y las de todos (si la base es compartida). *Limpiar historial* respeta las marcadas con estrella. Se conservan las últimas 300 por persona.
- *Guardados*: los casos y suites del proyecto activo. Clic en un caso lo abre para editarlo (y «Guardar» puede **actualizarlo**); ▶ ejecuta una suite.

**Centro — Petición y respuesta**
- Barra de petición: ambiente (o «URL completa»), método, protocolo https/http, URL, **Enviar** (**Ctrl+Enter**). Debajo, las `{{variables}}` detectadas: verde si tienen valor, ámbar si faltan.
- Botones: nueva petición · probar conectividad (DNS/TCP/TLS/HTTP) · navegador (solo navegar o grabar y convertir en caso UI) · copiar como `curl`.
- Respuesta en pestañas: **Cuerpo** (texto o árbol plegable), **Headers**, **Pruebas** (qué pasó y qué se obtuvo), **Diff** (cambios respecto a la respuesta anterior de esta misma petición), **Conectividad** y **Lote**.

**Derecha — Inspector** (riel de iconos; pasa el ratón para ver el nombre)
- **Params** y **Headers**: filas con casilla (desactivada = se conserva pero no se envía), atajos (`+ Content-Type`, `+ Bearer`) y modo **Texto** para editar en masa, una línea por elemento (`# ` desactiva).
- **Body**: editor JSON con resaltado, indicador de validez, *Formatear*, *Minificar* y *Usar la última respuesta* como body.
- **Pruebas**: aserciones visuales con ✓/✗ de la última respuesta, *Generar pruebas desde la respuesta* (exacta, estructura o solo código; los campos que suelen cambiar se sugieren solos) y extracciones para encadenar.
- **Variables**: las de esta petición. **Lote**: misma petición con varias entradas (`/api/users/{{id}}`, una fila por valor, pegado masivo); ejecuta, compara y guarda como suite de regresión.
- **Guardar**: nombre, qué debe cumplir, **destino** (proyecto existente o nuevo, y suite existente opcional) y *Guardar* (o *Actualizar* si editas un caso guardado). Nada se guarda hasta que lo decidas; sin proyecto activo también puedes explorar.
- **Agente**: ver más abajo.

Las peticiones del espacio de trabajo van a **su propio historial** (no al historial de ejecuciones de casos y suites). Si la respuesta de una petición cambia entre envíos, la pestaña *Diff* te lo muestra.

## Trabajar con agentes (entregar casos y recibir fallos)

Un agente puede entregar casos en un formato definido (`ltw.spec/1`) y recibir los fallos como `ltw.failure/1`, con todo lo necesario para ir al código, probar y reparar. Está en **Espacio de trabajo → Agente**, en la **línea de comandos** y en la **API local** (ver [AGENTS.md](AGENTS.md)):
- *Brief del último fallo*: cuando una petición con pruebas falla, aparece un brief en Markdown (qué se envió, esperado vs obtenido, respuesta, diagnóstico, dónde mirar, cómo reproducir, reglas) para copiarlo o descargar el `failure.json`. También desde el detalle de cualquier ejecución fallida: **Brief para agente**.
- *Esta petición como especificación*: exporta lo que estás editando como `ltw.spec/1`.
- *Importar una especificación*: pega una; se valida (errores y avisos con su ruta), carga el primer caso en el editor o importa todo al proyecto elegido.
- *API local y línea de comandos*: token, ejemplo de `curl` y de `python run.py --run spec.json`.

## Flujos entre módulos (enriquecer la salida de uno para alimentar a otro)

Una **suite** puede ser un flujo que cruza módulos. En el editor de la suite, cada paso tiene:
- **Nombre del paso** (alias): lo usan los pasos posteriores para referirse a su respuesta.
- **Ambiente / módulo**: por defecto el de la suite, o cualquier otro del proyecto. Así el paso 1 puede llamar al módulo A y el paso 2 al módulo B.
- **Enriquecer**: reglas para **agregar o modificar campos del request de ese paso**, usando respuestas de pasos anteriores (de cualquier módulo). Solo para eso: no cambia el caso, solo aplica dentro de la suite.

Cada regla = *acción* (Asignar/agregar, Quitar, Combinar objeto) + *destino* (Body con ruta JSON `$.cliente.id`, Header, Query o Ruta) + *origen* del valor:
- **Valor fijo** (número, true/false, JSON o texto).
- **Respuesta de un paso anterior** (`paso` + ruta `$.data.id`; vacío = respuesta completa). Conserva el tipo: un objeto se inserta como objeto, un número como número.
- **Variable** (de la suite, el ambiente o extraída antes).
- **Texto con referencias**, p. ej. `Bearer {{@login:$.token}}`.

**Vista previa** en el mismo diálogo: muestra el request que se enviaría con la última respuesta registrada de los pasos anteriores (si no hay, ejecuta la suite una vez). Los headers sensibles se ocultan.
**Garantías**: una regla solo puede apuntar a pasos *anteriores*; si una referencia no existe en la respuesta o el paso previo falló, el paso termina en *Error* **sin enviar nada** al módulo siguiente. El historial guarda lo que **salió** (body y query, con secretos ocultos) y las reglas aplicadas.

## Observador de interfaces (qué entra y qué sale de cada módulo)

Menú **Observador**. Aprende, solo de JSON, la forma real de las llamadas entre módulos, sin pedir nada a los equipos que los desarrollan.

**Dos fuentes** (usa la que convenga, ambas alimentan el mismo catálogo):
- **Tap** (proxy ligero): *Nuevo tap* → módulo, empresa/responsable (opcional), puerto local, protocolo + dirección del módulo destino y, si quieres, su contrato OpenAPI. Pulsa *Iniciar* y apunta al tap (`http://127.0.0.1:PUERTO`) a quien llama al módulo, en lugar de apuntarlo al módulo. El tap reenvía sin modificar nada y registra el JSON.
- **Historial**: *Aprender del historial* usa las peticiones y respuestas de tus ejecuciones ya registradas (cada una cuenta una sola vez). No requiere proxy. Se asocia por el nombre del ambiente, que hace de «módulo».

**Catálogo**: una fila por módulo + método + ruta normalizada (`/api/users/42` → `/api/users/{id}`; con contrato se usan sus plantillas). Al abrir una interfaz ves: campos con tipos, presencia (cuántas veces viene) y ejemplos; *obligatorio* se infiere solo con 2 o más observaciones; el **JSON Schema observado**; muestras; códigos HTTP; tiempos.

**Cambios sin aviso**: *Fijar línea base* congela lo conocido. Desde entonces el observador avisa de **campo nuevo**, **tipo distinto**, **campo requerido ausente** y **código HTTP nuevo**, con cuántas veces ocurrió. Si el cambio es legítimo, *Aceptar cambios y fijar línea base*.

**Contrato vs realidad**: pestaña *Contrato* compara lo observado con el OpenAPI del módulo (campos no declarados, tipos distintos, requeridos que no siempre vienen, códigos no declarados).

**Del catálogo a una prueba**: *Crear caso de regresión desde la última muestra* genera un caso con esa petición y aserciones de estructura (JSON Schema). Los valores sensibles enmascarados se vuelven variables `{{password}}` que debes completar: el caso se niega a ejecutarse hasta entonces.

**Privacidad**: los valores de campos con nombres sensibles (`password`, `token`, `secret`, `authorization`, `api_key`, `cookie`, `session`…) se guardan como `***`; los headers no se guardan. Está pensado para preproducción.

## Base de datos compartida

Lo único que se comparte es la base SQLite: apunta `TEST_WORKSPACE_HOME` a una carpeta compartida. Si la carpeta está en un recurso de red, la aplicación evita el modo WAL (inseguro en red) y espera a que otro usuario termine de escribir. Si dos personas editan el mismo caso o suite, la segunda en guardar recibe un aviso de conflicto y no sobrescribe en silencio. Pensado para pocas personas a la vez, no para uso intensivo concurrente.

## Variables y secretos

- `{{nombre}}` se sustituye en ruta, headers, query, body y pasos UI. Fuentes: variables del ambiente, variables de la suite y valores extraídos por casos anteriores.
- `{{secret:nombre}}` toma el valor del almacén seguro (o de una variable de entorno con ese nombre).
- Si queda alguna variable sin resolver, el caso **no se envía** y se marca *Error* indicando cuáles faltan.

## Aserciones (casos API)

El caso pasa si todas pasan. Rutas JSON con sintaxis `$.a.b[0].c` (también `a.b.0.c` y `[*]`). Tipos disponibles: código HTTP (igual / en lista), tiempo máximo, header (existe / igual / contiene), JSONPath (existe / no existe / igual / distinto / tipo / longitud / regex / contiene / comparaciones numéricas), cuerpo (contiene / no contiene / regex / vacío / no vacío) y **JSON Schema**. Con un módulo asociado, *Agregar validación del contrato* inserta el schema de la respuesta 2xx del OpenAPI.

## Encadenamiento

Pestaña *Encadenamiento* del caso: extrae `token = $.token` (o un header, el código HTTP o un regex). En los casos siguientes de la **misma suite** usa `Bearer {{token}}`. Solo se propagan valores de casos que pasaron. El orden de la suite importa.

## Casos UI y grabador

Acciones: ir a URL, clic, escribir, presionar tecla, marcar/desmarcar, elegir opción, esperar visible, verificar visible/oculto/texto/valor/URL. Locators: etiqueta, texto, rol ARIA (+ nombre), `data-testid`, placeholder. Texto/etiqueta/placeholder coinciden por contenido parcial (como Playwright; `exact` lo hace exacto). Si varios elementos coinciden, marca **1º** (primero) o usa `nth` para evitar el error de «strict mode».

**Grabador**: pestaña *Grabador* → URL → *Abrir grabador* (ventana de Chromium). Al cerrarla, el script se analiza (no se ejecuta) y verás los pasos importados y las líneas **no soportadas** (locators CSS/encadenados, `evaluate`, imports ajenos…). Revisa y agrega los pasos al caso.

La navegación solo se permite dentro del host del ambiente; redirecciones a otros hosts se bloquean.

## Suites

- *Continuar tras un fallo* o *Detener al primer fallo* (el resto queda *Omitido*).
- Reintentos 0–5 por caso con espera configurable.
- *Cancelar* detiene la suite al terminar el caso en curso (el resto queda *Cancelada*).

## Programaciones

Diaria, lunes-viernes, semanal, **única** (`AAAA-MM-DDTHH:MM` en la zona indicada) e **intervalo** (cada N minutos). Si el equipo estuvo apagado: *ejecutar una vez al reiniciar* u *omitir*. Solo corren con el scheduler abierto; un segundo scheduler es rechazado.

## Importar / Exportar

Exporta todo, un proyecto, suites o casos (incluye sus dependencias). Nunca se exportan secretos, variables con nombres sensibles (`token`, `password`, `key`…) ni headers de autorización; las programaciones viajan desactivadas. Al importar verás una **vista previa** (nuevos, existentes, advertencias) y confirmas; la escritura es todo-o-nada. Estrategias: fusionar, reemplazar, copia nueva (ids nuevos).

## Evidencias

Capturas en cada caso UI; trazas Playwright (`.zip`, ábrelas con `python -m playwright show-trace`) en fallos. *Historial → Retención* purga por antigüedad. La descarga solo sirve archivos dentro del directorio de evidencias.
