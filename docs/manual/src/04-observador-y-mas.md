---

# 11. Observador de interfaces

El **Observador** responde a una pregunta difícil cuando hay varios componentes desarrollados por equipos o empresas distintas: **¿qué entra y qué sale realmente de cada uno?** Aprende, **solo de JSON**, la forma real de las llamadas y te avisa cuando alguien la cambia **sin avisar**.

![Catálogo del observador con un componente y sus interfaces](img/51-observador-catalogo.png)

## 11.1 Dos fuentes, un solo catálogo

| Fuente | Cómo funciona | Cuándo usarla |
|---|---|---|
| **Tap** (proxy ligero) | Un pequeño proxy que escucha en tu equipo y **reenvía todo** al componente destino **sin modificarlo**, registrando el JSON. Apuntas al tap el componente que llama, en lugar de apuntarlo al destino. | Quieres ver el tráfico **real** entre componentes (en pruebas o preproducción). |
| **Historial** | **Aprender del historial** usa las peticiones y respuestas de tus **ejecuciones ya registradas**. Cada ejecución cuenta una sola vez. | No puedes (o no quieres) poner un proxy. |

Las interfaces se agrupan por el **nombre del componente**: tap e historial solo se unifican si usan el mismo nombre (en el historial, el nombre del **ambiente**).

## 11.2 Crear y usar un tap

![Formulario para crear un tap](img/50-observador-tap-form.png)

En **Nuevo tap (proxy de observación)** completa:

| Campo | Descripción |
|---|---|
| **Componente (nombre)** | Nombre del servicio observado. Obligatorio. |
| **Empresa / equipo** y **Responsable** | Opcionales; se muestran en la tarjeta del componente (útil con componentes de distintos equipos). |
| **Puerto local** | Entre 1024 y 65535; no puede repetirse ni estar ocupado por otro programa. Sugiere `9101` más el número de taps ya creados. |
| **Protocolo** y **Dirección del componente destino** | `https` por defecto. Puede incluir un prefijo de ruta. |
| **Contrato OpenAPI del componente** (opcional) | Si lo eliges, las rutas se **normalizan con sus plantillas** (`/users/{userId}`) y puedes comparar lo observado con lo declarado. |

Pulsa **Crear tap** y luego **Iniciar**. El tap queda activo con su dirección `http://127.0.0.1:PUERTO → destino` y un contador de llamadas. **Detener** lo para; el 🗑 lo elimina (el catálogo aprendido se conserva).

**Para observar:** cambia la URL del componente consumidor para que apunte a `http://127.0.0.1:PUERTO` en lugar del destino. Todo lo que pase se reenvía sin cambios y se registra.

> Un tap **solo escucha en tu equipo** (`127.0.0.1`), habla HTTP simple con quien lo llama (hacia el destino sí puede usar https), reenvía una petición por conexión y rechaza cuerpos `chunked` o mayores de 5 MB. Se detiene al cerrar la aplicación.

## 11.3 El catálogo

Arriba, una **tarjeta por componente** con su empresa/responsable, número de interfaces y llamadas, y una insignia: *«n cambio(s) sin aprobar»* (rojo), *«n sin línea base»* (gris) o *«sin cambios»* (verde). Un clic en la tarjeta filtra el catálogo por ese componente.

La tabla lista cada **interfaz** (componente + método + ruta normalizada: `/api/users/42` → `/api/users/{id}`; los UUID se normalizan a `{uuid}` y las cadenas hexadecimales largas a `{hash}`) con **llamadas**, **códigos** (`200×4, 404×1`), **última vez** y **estado**. Puedes filtrar por componente y buscar por ruta; un clic en una fila abre su detalle.

## 11.4 Detalle de una interfaz

![Campos aprendidos de una interfaz](img/52-interfaz-campos.png)

Resumen: llamadas, tiempo promedio, códigos, desde/hasta cuándo, parámetros de query y respuestas **no JSON** (se cuentan pero no se analizan). Botones:

| Botón | Acción |
|---|---|
| **Fijar línea base** / **Aceptar cambios y fijar línea base** | Congela la forma actual como «lo conocido y aceptado». |
| **Crear caso de regresión desde la última muestra** | Genera un caso API con esa petición y aserciones de **estructura** (JSON Schema). Los valores sensibles enmascarados se vuelven variables `{{password}}` que **debes completar**: el caso no se ejecuta hasta entonces. |
| **Olvidar esta interfaz** | Borra lo aprendido (no afecta tus casos). |

**Pestaña Campos.** Por cada solicitud y cada código de respuesta: una tabla con **Campo** (`$.id`, `$.items[*].name`), **Tipos**, **Presencia** (cuántas veces viene, p. ej. `4/4 (100%)`), **Obligatorio** (✓) y **Ejemplos**, más el **JSON Schema observado** (desplegable). Un campo se considera **obligatorio** si apareció en **todas** las ocurrencias de su objeto, y **solo con 2 o más observaciones** (con una sola, el aviso lo recuerda).

**Pestaña Muestras.** Las últimas 5 llamadas (solicitud y respuesta) con los valores sensibles como `***`.

## 11.5 Detectar cambios sin aviso

1. Cuando la interfaz tenga suficientes observaciones, pulsa **Fijar línea base**.
2. Desde entonces, cada llamada nueva se compara con esa base. El observador registra, con el número de veces que ocurrió:

| Cambio | Significa |
|---|---|
| **Campo nuevo** | Apareció un campo que no estaba en la línea base. |
| **Tipo distinto** | Un campo cambió de tipo (por ejemplo, `integer` → `string`). |
| **Campo requerido ausente** | Un campo obligatorio en la base ya no viene siempre. |
| **Código HTTP nuevo** | Apareció un código de estado que no se había visto. |

![Cambios detectados respecto a la línea base](img/53-interfaz-cambios.png)

El estado de la interfaz pasa a **«n cambio(s)»** (rojo) en el catálogo, la tarjeta del componente y el detalle. Si el cambio es **legítimo**, pulsa **Aceptar cambios y fijar línea base**: lo nuevo pasa a ser lo conocido y la lista se vacía (queda registrado cuántos cambios se aceptaron).

> **Límite.** El observador detecta cambios de **forma** del JSON. Un cambio de **comportamiento** que no altera la forma (otro valor, otra regla de negocio) no se detecta: para eso usa los **casos de regresión**.

## 11.6 Comparar con el contrato (contrato vs realidad)

![Comparación con el contrato OpenAPI](img/54-interfaz-contrato.png)

En la pestaña **Contrato** elige un componente OpenAPI del proyecto y pulsa **Comparar con lo observado**. Se listan las diferencias: campos que se observan pero el contrato **no declara**, tipos que llegan **distintos**, campos requeridos por el contrato que **no siempre vienen** o nunca se observaron, y códigos de respuesta no declarados. Si el contrato no declara esa operación, se indica.

## 11.7 Privacidad

Los valores de campos con nombres sensibles (`password`, `pass`, `secret`, `token`, `authorization`, `api_key`, `cookie`, `credential`, `session`…) se guardan como `***`; los **headers no se guardan**. Aun así, el catálogo y las muestras contienen el JSON que pasó por el tap: **úsalo en preproducción** y con datos de prueba.

---

# 12. Programaciones

Una **programación** ejecuta una suite automáticamente en los momentos que definas.

![Programaciones](img/44-programaciones.png)

## 12.1 El scheduler

Las programaciones **solo se ejecutan mientras el scheduler esté abierto** y el equipo encendido. El recuadro superior indica si está **activo** (verde) o **detenido** (ámbar).

- Para activarlo: **`scripts\scheduler.bat`** (o `python run.py --scheduler`) y **deja esa ventana abierta**.
- **Solo puede haber un scheduler por workspace**. Un segundo se rechaza con «Ya hay otro scheduler activo». Si un scheduler se cierra de golpe, su bloqueo se **recupera solo a los 120 s**.
- No es un servicio de Windows. Si lo quieres permanente, crea una **tarea programada** de Windows que ejecute `scripts\scheduler.bat` al iniciar sesión.

## 12.2 Crear una programación

En **Nueva programación** elige la **Suite** y la **Frecuencia**:

| Frecuencia | Campos | Ejemplo |
|---|---|---|
| **Diario** | Hora, zona horaria | Todos los días a las 02:00 |
| **Lunes a viernes** | Hora, zona horaria | L–V a las 07:30 |
| **Semanal** | Día, hora, zona horaria | Los miércoles a las 18:00 |
| **Una sola vez** | Fecha y hora (`AAAA-MM-DDTHH:MM`), zona | `2026-12-01T09:30` |
| **Cada N minutos** | Cada (1 a 10 080 minutos) | Cada 30 minutos |

- **Zona horaria IANA** (por ejemplo `America/Mexico_City`, `Europe/Madrid`, `UTC`): la hora se interpreta en esa zona.
- **Si el equipo estuvo apagado:** **Ejecutar una vez al reiniciar** (si el scheduler arranca y la ejecución está vencida, se ejecuta **una vez**) u **Omitir ejecuciones perdidas** (se salta y se calcula la siguiente). Una ejecución se considera «perdida» si el scheduler la encuentra con **más de 2 minutos de retraso**.

Pulsa **Programar**. Si algún dato no es válido (hora, fecha pasada, zona desconocida…) se te explica el motivo.

## 12.3 La lista

Cada programación muestra la suite, su frecuencia, la **próxima** ejecución, la **última** y su resultado («ejecutada» u «omitida (perdida)»), y estos botones:

| Botón | Acción |
|---|---|
| **Pausar / Activar** | Detiene o reanuda (al activar recalcula la próxima ejecución). |
| ▶ | **Ejecutar ahora**, sin esperar. |
| 🗑 | Eliminar. |

Una programación **«Una sola vez»** se **desactiva sola** tras ejecutarse. Los resultados quedan en el **Historial**.

---

# 13. Historial de ejecuciones y evidencias

El menú **Historial** reúne los resultados de **casos y suites ejecutados** (manualmente o por programación). Es distinto del historial de peticiones del Espacio de trabajo (ver [3.2](#cap-3)).

![Historial de ejecuciones](img/45-historial-ejecuciones.png)

## 13.1 Buscar y filtrar

- **Estado** (Pasó, Falló, Error, Cancelada, Omitido), **Tipo** (API, UI, Flujo, Suite) y **Buscar por nombre**.
- La tabla muestra **Inicio**, **Tipo**, **Nombre**, **Estado** y **Detalle** (código y tiempo, o número de casos). Ordena por fecha y pagina de 15 en 15.
- Se muestran las ejecuciones del proyecto activo (y las que no tienen proyecto).

## 13.2 Ver el detalle

![Detalle de una ejecución fallida](img/46-detalle-ejecucion.png)

Un clic en una fila abre su detalle:

- **Flujo:** la lista de pasos con su estado, alias, ambiente e intentos, y **Ver detalle** de cada uno.
- **Suite** (grupo): cada Flujo o Caso suelto miembro, con su propio estado y **Ver detalle**.
- **Caso API:** petición, **reglas de enriquecimiento aplicadas**, **petición enviada**, aserciones ✓/✗ con lo obtenido, variables extraídas y la respuesta.
- **Caso UI:** cada paso con ✓/✗, la **captura de pantalla** (visible en el cuadro y descargable con **Descargar captura**) y la **traza de Playwright** (si falló; **Descargar traza**). Para abrirla: `python -m playwright show-trace archivo.zip`.
- Si falló: **Brief para agente** (ver [capítulo 17](#cap-17)).

![Brief para agente de una ejecución fallida](img/47-brief-agente.png)

Las evidencias se sirven **solo desde el directorio de evidencias** de LTW; no es posible pedir otros archivos del equipo.

## 13.3 Evidencia descargable y envío a Jira/Azure DevOps

El detalle de cualquier ejecución (Caso API, Caso UI, Flujo o **Suite**) tiene **«Descargar evidencia»**, con cuatro formatos — mismo contenido en los cuatro (petición enviada, respuesta, aserciones ✓/✗, capturas de UI, paso a paso): **HTML**, **PDF**, **Word** y **Markdown**. En un Flujo o una Suite, cada paso o miembro se expande con su propio detalle; si un miembro de una Suite es a su vez un Flujo, sus pasos quedan anidados adentro (en Markdown, como encabezados más profundos). El Word y el Markdown usan un formato simple (sin buscar igualar el diseño del PDF), pensados para adjuntar a mano a un ticket o pegar en un comentario/wiki.

Para adjuntarlo **automáticamente** sin descargar nada, configura primero una integración en **Integraciones** (menú lateral): elige la plataforma (**Jira**, Cloud en `atlassian.net`, o **Azure DevOps**), guarda el token/PAT como **secreto** del sistema (igual que la autenticación de un Ambiente) y pulsa **«Probar conexión»** para confirmar que los datos son correctos antes de usarla. Luego, desde el detalle de cualquier ejecución, **«Enviar a Jira/Azure DevOps»** pide la integración, el ticket (Jira, p. ej. `PROJ-123`) o el work item (Azure DevOps, un número) y el formato, y adjunta el archivo con tus propias credenciales.

## 13.4 Retención y limpieza

En **Retención de evidencias** indica **Conservar (días)** (30 por defecto) y pulsa **Purgar ahora** (pide confirmación). Se eliminan las ejecuciones **más antiguas** que ese número de días **y sus archivos** (capturas, trazas), y se conservan como máximo las 1000 más recientes. Las ejecuciones guardan el cuerpo enviado y la respuesta (hasta 50 000 caracteres): trátalas como información restringida y úsalas con datos de preproducción.

## 13.5 Resumen ejecutivo y reporte de estatus

Pensado para quien **no** quiere leer ejecuciones una por una —product owner, líder, dirección—: responde en una pantalla *¿cómo estamos?, ¿mejora o empeora?, ¿qué falla y desde cuándo?*. Está en **Resumen** (menú lateral).

![Resumen ejecutivo del proyecto](img/56-resumen-ejecutivo.png)

**Semáforo.** El banner superior da el estado general con las razones concretas:

| Color | Cuándo |
|---|---|
| **VERDE** | La tasa de éxito del periodo es de **95 %** o más, ningún flujo falla en su última ejecución, no hay casos fallando ni cambios pendientes en las interfaces observadas. |
| **ÁMBAR** | Hay casos fallando, la tasa está entre 80 % y 95 %, hay cambios sin aviso en interfaces observadas, o hay programaciones vencidas sin ejecutarse. |
| **ROJO** | Algún **flujo** (suite) falla en su última ejecución, o la tasa de éxito baja de **80 %**. |
| **SIN DATOS** | Todavía no hay ejecuciones: no se inventa un color. |

Las ejecuciones **canceladas u omitidas** no cuentan: no dicen nada sobre la salud.

**Periodo.** Elige **7, 14, 30 o 90 días**. Todo se compara con el periodo anterior de la misma duración (por ejemplo, los 14 días previos), y verás flechas ▲/▼ con los puntos de diferencia.

**Qué muestra**

- **Indicadores:** tasa de éxito (con su cambio), flujos sanos (*2 de 3*), casos fallando, casos que nunca se han ejecutado, ejecuciones y respuesta media.
- **Ejecuciones por día:** barras verdes (pasaron) y rojas (fallaron). Pasa el ratón por una barra para ver el detalle del día.
- **Flujos:** estado de la última ejecución de cada suite, sus últimas 12 ejecuciones como cuadritos de color, el porcentaje de éxito y el cambio frente al periodo anterior.
- **Qué está fallando y desde cuándo:** cada caso cuya última ejecución no pasó, con la fecha de la **primera** falla de la racha, cuántas ejecuciones seguidas lleva fallando, el motivo y el responsable si el autor lo indicó en `code_hints`. **Detalle** abre la ejecución.
- **Casos inestables:** pasan y fallan alternadamente (al menos dos cambios de estado) sin que nadie toque la prueba. Conviene revisarlos antes de confiar en ellos.
- **Más lentos:** los 5 casos con mayor tiempo medio de respuesta.
- **Interfaces observadas y programaciones:** componentes con cambios sin aviso (con su empresa y responsable, si se registraron en el tap) y estado del scheduler.

**Reporte de estatus.** Pulsa **Reporte de estatus** y elige el formato:

| Formato | Para qué |
|---|---|
| **Página web (.html)** | Un solo archivo autosuficiente (gráfico incluido): se abre en cualquier navegador y se adjunta a un correo. |
| **PDF** | Para presentar o archivar (usa el Chromium que ya instaló la herramienta). |
| **Markdown (.md)** | Para pegarlo en un wiki, Azure DevOps o un PR. |
| **Datos (.json)** | Formato `ltw.status/1`, para otras herramientas. |

![El reporte de estatus exportado](img/57-reporte-estatus.png)

Escribe antes, en **Comentarios para el reporte**, el contexto que los números no dicen (riesgos, decisiones): se incluye en el archivo. **Copiar resumen** deja en el portapapeles un texto corto —estado, razones y los principales fallos— listo para un correo o un chat.

**Desde la línea de comandos** (por ejemplo, programado cada mañana):

```
python run.py --status-report reporte.html --project "Mi proyecto" --days 14 --notes "Texto opcional"
```

La extensión elige el formato (`.html`, `.pdf`, `.md`, `.json`). Código de salida: `0` verde o sin datos, `1` ámbar o rojo, `2` error de uso.

> **Qué no hace.** El resumen refleja lo que **se ejecutó**: si nadie ejecuta las pruebas (o el scheduler está detenido), el semáforo no sabe lo que pasa. Cuanto más regulares sean las ejecuciones programadas, más fiable es la tendencia.

---

# 14. Importar / Exportar

![Importar y exportar](img/55-importar-exportar.png)

Los **paquetes ZIP** sirven para pasar trabajo entre personas o equipos (por ejemplo, del desarrollador al tester) o para respaldarlo.

## 14.1 Exportar

Elige **Qué exportar**:

| Opción | Contenido |
|---|---|
| **Todo el workspace** | Todos los proyectos y sus recursos. Con **Incluir historial** agrega las ejecuciones **sin** cuerpos de petición ni respuesta. |
| **Solo el proyecto activo** | El proyecto y todo lo suyo. |
| **Suites seleccionadas** | Las suites elegidas **más sus dependencias** (casos, ambientes —también los de cada paso—, componentes y proyecto). |
| **Casos seleccionados** | Los casos elegidos más sus dependencias. |

Pulsa **Exportar (.zip)** y se descarga.

**Qué NO se exporta (a propósito):** los **secretos**, las variables de ambiente cuyo nombre sea sensible (`token`, `password`, `secret`, `key`, `authorization`, `cookie`), los headers de **autorización/cookies** de los casos, los cuerpos de ejecuciones, y las **programaciones viajan desactivadas**.

## 14.2 Importar

1. Elige la **Estrategia**:

| Estrategia | Efecto |
|---|---|
| **Fusionar (omite lo que ya existe)** | Agrega lo nuevo y deja intacto lo existente (por identificador). |
| **Reemplazar coincidencias** | Sobrescribe lo que ya existe con lo del paquete. |
| **Importar como copia nueva** | Crea todo con **identificadores nuevos** (una copia independiente; las relaciones entre elementos se conservan). |

2. **Elige o arrastra** un `.zip` (hasta 50 MB).
3. Aparece una **Vista previa**: cuántos elementos hay de cada tipo (nuevos y existentes), el alcance del paquete y **advertencias** (referencias que no existen y se vaciarán, casos faltantes en una suite, programaciones que se importan desactivadas). **Aún no se ha escrito nada.**
4. Pulsa **Confirmar importación**. Es **todo o nada**: si algo falla, no queda ningún cambio parcial.

**Seguridad del paquete.** Antes de importar se valida todo: se rechazan rutas peligrosas (`..`, rutas absolutas), enlaces simbólicos, entradas duplicadas, archivos que se expanden de forma sospechosa (zip bomb), entradas de más de 10 MB, paquetes de más de 5000 entradas o 100 MB descomprimidos, y registros con formato inválido.

## 14.3 Diagnóstico

**Descargar diagnóstico** genera un ZIP con versiones, conteos, ambientes (sin secretos) y los registros recientes **ya sin secretos**, para reportar un problema.

---

# 15. Trabajo en equipo y base de datos compartida

LTW es **local**; para trabajar con otras personas hay dos mecanismos que pueden combinarse.

## 15.1 Paquetes (traspaso)

El desarrollador exporta un **paquete** (suites o casos con sus dependencias) y el tester lo **importa** (con vista previa). Es el modo más simple y no requiere infraestructura compartida. Recuerda que los **secretos no viajan**: cada persona crea los suyos con el mismo nombre en **Ambientes → Secretos**.

## 15.2 Base de datos compartida

Lo único que se comparte es la **base de datos** SQLite. Para usarla, apunta `TEST_WORKSPACE_HOME` de cada persona a la **misma carpeta compartida** antes de arrancar:

```bat
set TEST_WORKSPACE_HOME=\\servidor\compartido\ltw
scripts\run.bat
```

Qué hace LTW para que sea seguro con pocas personas a la vez:

- Si la carpeta está en un **recurso de red**, evita el modo WAL de SQLite (inseguro en red) y usa el modo clásico.
- Cada operación **espera** a que otra persona termine de escribir en lugar de fallar con «base bloqueada».
- **Detección de conflictos:** si dos personas editan el **mismo caso, caso UI o suite**, la segunda al guardar recibe un aviso y **no sobrescribe** el trabajo de la primera.
- El historial del Espacio de trabajo guarda el **autor** (usuario de Windows); el interruptor «solo mías» filtra.

**Qué no se comparte:** los **secretos** (están en el Administrador de credenciales de cada equipo) y las posiciones de los paneles.

> **Límites.** Está pensado para **pocas personas simultáneas**, no para uso intensivo concurrente. Algunos NAS no respetan bien los bloqueos de archivos; si ves comportamientos extraños, trabajad por paquetes. El token de la API local para agentes también vive en la base: con una base compartida, quien tenga acceso a ella lo ve (puedes regenerarlo). Haz **copias de seguridad** copiando la carpeta `data\` con la aplicación cerrada.
