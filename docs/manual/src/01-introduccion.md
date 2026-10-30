# 1. Introducción

## 1.1 ¿Qué es Local Test Workspace?

**Local Test Workspace** (LTW) es una aplicación que corre en tu propio equipo y te permite **probar, documentar y vigilar servicios web (APIs) y sitios web** sin escribir código. Con ella puedes:

- **Explorar** un servicio enviando peticiones y mirando las respuestas, como en un cliente de APIs, pero con historial, comparación de respuestas y edición rápida.
- **Convertir lo que exploras en pruebas repetibles** (casos y suites) con una respuesta esperada, para saber si «algo cambió» cuando alguien modifica el servicio.
- **Probar flujos entre varios módulos**: tomar la respuesta de un módulo, enriquecerla y usarla como entrada del siguiente.
- **Observar el tráfico real** entre módulos para descubrir qué entra y qué sale de cada uno, y avisarte cuando alguien cambia un formato sin avisar.
- **Probar interfaces web** (navegador real) con pasos que se editan visualmente o se graban.
- **Programar** ejecuciones automáticas y **compartir** el trabajo mediante paquetes (ZIP) o una base de datos compartida.
- **Trabajar con agentes**: un agente puede entregar casos de prueba en un formato definido y recibir los fallos en un formato pensado para ir directo al código a repararlos.

> **Alcance.** LTW está pensada para entornos de **desarrollo y preproducción** y para tráfico **JSON**. Funciona en **Windows** con **Python 3.11 o superior** ya instalado. Todo corre en tu equipo: no hay servicio en la nube.

## 1.2 ¿Para quién es?

| Perfil | Qué hace con LTW |
|---|---|
| **Desarrollador** | Importa su contrato (OpenAPI), crea casos y suites, comprueba sus cambios y entrega un paquete a quien probará. |
| **Tester / QA** | Recibe el paquete, cambia parámetros y datos de entrada, crea lotes y regresiones, y detecta qué cambió entre versiones. |
| **Product Owner / negocio** | Ejecuta las suites, mira si «todo sale como se espera», programa ejecuciones y revisa resultados en lenguaje claro. |
| **Agente (automatización)** | Entrega especificaciones `ltw.spec/1`, ejecuta por línea de comandos o API y recibe fallos `ltw.failure/1`. |
| **Responsable de integración** | Observa el tráfico entre módulos de distintos equipos o empresas y vigila los cambios sin aviso. |

Las recetas paso a paso para cada perfil están en el [capítulo 16](#16-recetas-por-perfil).

## 1.3 Lo que **no** es

- No es una herramienta de **pruebas de carga** ni de rendimiento intensivo (mide tiempos de respuesta de una llamada, no soporta miles de usuarios).
- No analiza ni lee tu **código fuente**; trabaja con lo que el servicio responde.
- No reemplaza a un servidor de integración continua: puede ejecutarse por línea de comandos y producir JUnit, pero no orquesta pipelines.
- No es multiusuario con inicio de sesión: es local; lo único que se comparte es la **base de datos** (ver [capítulo 15](#15-trabajo-en-equipo-y-base-de-datos-compartida)).

## 1.4 Cómo está organizado este manual

| Si quieres… | Ve a |
|---|---|
| Instalar y arrancar | [Capítulo 2](#2-instalación-y-puesta-en-marcha) |
| Entender los conceptos básicos | [Capítulo 3](#3-conceptos-clave) |
| Hacer tu primera prueba en 10 minutos | [Capítulo 5](#5-guía-rápida-tu-primera-prueba-en-10-minutos) |
| Conocer cada pantalla a fondo | Capítulos 6 al 14 |
| Compartir trabajo con otras personas | [Capítulo 15](#15-trabajo-en-equipo-y-base-de-datos-compartida) |
| Ver ejemplos por rol | [Capítulo 16](#16-recetas-por-perfil) |
| Trabajar con agentes | [Capítulo 17](#17-protocolo-para-agentes) |
| Resolver un problema | [Capítulo 19](#19-solución-de-problemas) |
| Consultar tablas de referencia | [Capítulo 20](#20-referencia) |

Convenciones: los nombres de botones, pestañas y campos aparecen en **negrita** tal como se ven en pantalla; el código, las rutas y los valores literales van en `este formato`; los recuadros **Nota**, **Importante** y **Consejo** destacan información adicional.

---

# 2. Instalación y puesta en marcha

## 2.1 Requisitos

| Requisito | Detalle |
|---|---|
| Sistema operativo | **Windows 10 u 11** (la solución está orientada a Windows). |
| Python | **3.11 o superior**, instalado y disponible en el `PATH` (comprueba con `python --version`). |
| Navegador | Un navegador moderno (Chrome, Edge, Firefox) para usar la interfaz de LTW. |
| Chromium de Playwright | Solo para **casos UI**, grabador y «Navegar». Se instala con un comando (ver abajo). |
| Espacio en disco | Unos 500 MB (dependencias + Chromium). |

## 2.2 Instalación

1. Descomprime el paquete `local-test-workspace-1.0.0.zip` en una carpeta de tu elección (por ejemplo `C:\Herramientas\local-test-workspace`). **La base de datos vivirá dentro de esa carpeta**, así que elige una ubicación con permiso de escritura.
2. Abre la carpeta y haz doble clic en **`scripts\install.bat`**. El script:
   - comprueba que Python sea 3.11 o superior;
   - crea un entorno virtual `.venv`;
   - instala las dependencias de `requirements.txt`;
   - descarga Chromium para Playwright (`python -m playwright install chromium`).
3. Espera el mensaje *«Instalacion completa»*.

> **Instalación manual** (si prefieres no usar el script):
> ```bat
> python -m venv .venv
> .venv\Scripts\activate
> pip install -r requirements.txt
> python -m playwright install chromium
> ```

## 2.3 Arrancar la aplicación

| Para… | Haz esto |
|---|---|
| Abrir la interfaz | Doble clic en **`scripts\run.bat`** (o `python run.py`). Abre **http://127.0.0.1:8080** en tu navegador. |
| Activar las **programaciones** | En otra ventana, doble clic en **`scripts\scheduler.bat`** (o `python run.py --scheduler`). Debe quedar abierta. |
| Ejecutar la batería de pruebas de la herramienta | **`scripts\test.bat`** |
| Generar el ejecutable | **`scripts\build_exe.bat`** (opcional; ver [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)) |

La aplicación escucha **solo en tu equipo** (`127.0.0.1`). No la expongas a otras redes: no tiene inicio de sesión.

## 2.4 Dónde se guardan los datos

Por defecto, **dentro de la carpeta del paquete**, en `data\`:

| Ruta | Contenido |
|---|---|
| `data\workspace.sqlite3` | Toda la información: proyectos, módulos, ambientes, casos, suites, programaciones, historial, observador. |
| `data\evidence\` | Capturas de pantalla y trazas de los casos UI. |
| `data\logs\` | Registros de la aplicación en formato JSON (con secretos ocultos). |

Mover o copiar la carpeta del paquete mueve también todo tu trabajo. Los **secretos** (tokens, claves) **no** están en la base: se guardan en el **Administrador de credenciales de Windows**.

> **Si venías de una versión anterior:** si existe `~\.local_test_workspace`, su base se **copia una sola vez** a `data\` al iniciar. El original no se borra ni se sobrescribe.

> **Si la carpeta del paquete es de solo lectura** (por ejemplo, `Program Files`), LTW usa tu perfil de usuario automáticamente.

## 2.5 Variables de entorno opcionales

| Variable | Para qué sirve | Por defecto |
|---|---|---|
| `LTW_PORT` | Puerto de la interfaz | `8080` |
| `TEST_WORKSPACE_HOME` | Carpeta de datos alternativa (por ejemplo, una carpeta compartida) | `<paquete>\data` |
| `LTW_AGENT_TOKEN` | Token fijo para la API local de agentes | se genera uno y se guarda |
| `LTW_LLM_API_KEY` | Clave del asistente con modelo de lenguaje (alternativa al almacén de credenciales) | ninguna |
| `LTW_STORAGE_SECRET` | Secreto de sesión del navegador (solo recuerda posiciones de paneles) | valor local |

Ejemplo para usar otro puerto: `set LTW_PORT=8090` y luego `python run.py`.

## 2.6 Actualizar y desinstalar

- **Actualizar:** descomprime la nueva versión en otra carpeta y copia tu carpeta `data\` encima de la nueva (o apunta `TEST_WORKSPACE_HOME` a la carpeta de datos antigua).
- **Desinstalar:** cierra la aplicación y borra la carpeta. Los secretos guardados quedan en el Administrador de credenciales (servicio `local-test-workspace`); bórralos desde ahí o desde la pantalla **Ambientes → Secretos**.

---

# 3. Conceptos clave

Antes de usar la herramienta conviene conocer su vocabulario. Cada término se explica con detalle en su capítulo.

| Concepto | Qué es | Ejemplo |
|---|---|---|
| **Proyecto** | Agrupa todo lo que pertenece a un mismo producto o iniciativa. Todo lo que ves (módulos, ambientes, casos…) pertenece al **proyecto activo**. | «Tienda en línea» |
| **Módulo** | Un contrato OpenAPI/Swagger importado: la lista de operaciones que ofrece un servicio. También se usa como nombre de un servicio en el Observador. | «Tienda API» |
| **Ambiente** | Dónde se ejecutan las pruebas: URL base, autenticación y variables. | «QA» → `https://qa.empresa.com` |
| **Caso API** | Una petición HTTP con sus **aserciones** (lo que debe cumplir la respuesta). | «Usuario 1 devuelve su ficha» |
| **Caso UI** | Una secuencia de pasos en un navegador real (navegar, escribir, hacer clic, verificar). | «Login en la web» |
| **Aserción** (prueba) | Una regla sobre la respuesta: «el código es 200», «`$.id` es un entero», «el cuerpo es idéntico al esperado»… | `status = 200` |
| **Suite / flujo** | Una lista ordenada de casos. Cada paso puede apuntar a otro ambiente (módulo) y **enriquecer** su petición con datos de pasos anteriores. | «Flujo identidad → pedidos» |
| **Ejecución** | El resultado de correr un caso o una suite: pasó, falló o error. Queda en el **Historial**. | — |
| **Programación** | Ejecución automática de una suite (diaria, semanal, cada N minutos…). | «L–V 07:30» |
| **Variable** | Un valor con nombre usado como `{{nombre}}` en rutas, headers, query o body. | `{{id}}` |
| **Secreto** | Un valor sensible (token, clave) guardado en el almacén seguro del sistema y usado como `{{secret:NOMBRE}}`. | `{{secret:TOKEN_QA}}` |
| **Campo volátil** | Un campo de la respuesta que cambia en cada llamada (fechas, identificadores, tokens). Se ignora al comparar. | `$.requested_at` |
| **Tap** | Un proxy ligero que observa el tráfico entre dos módulos sin modificarlo. | `127.0.0.1:9301 → módulo` |
| **Interfaz observada** | Una operación (método + ruta) aprendida del tráfico: sus campos, tipos y cambios. | `GET /api/users/{id}` |
| **Línea base** | La forma «conocida y aceptada» de una interfaz. Lo que se aparte de ella se reporta como cambio. | — |
| **Spec (`ltw.spec/1`)** | El formato JSON con el que un agente entrega casos de prueba. | — |
| **Brief / `ltw.failure/1`** | La descripción completa de un fallo, lista para que un agente (o una persona) lo repare. | — |

## 3.1 Cómo se relacionan

```
Proyecto
 ├─ Módulos (contratos OpenAPI)
 ├─ Ambientes ── variables, autenticación (secretos en el sistema)
 ├─ Casos API / Casos UI ── aserciones, extracciones
 ├─ Suites / flujos ── pasos (caso + ambiente + enriquecimiento)
 │    └─ Programaciones
 ├─ Observador ── taps, interfaces observadas
 └─ Historial de ejecuciones y evidencias
Espacio de trabajo: historial propio de peticiones sueltas (no necesita proyecto)
```

## 3.2 Dos historiales distintos

| | Qué contiene | Dónde se ve |
|---|---|---|
| **Historial del espacio de trabajo** | Las peticiones sueltas que envías mientras exploras. Persistente, por persona. | Panel izquierdo del **Espacio de trabajo** |
| **Historial de ejecuciones** | Los resultados de **casos y suites** ejecutados (incluidos los programados). | Menú **Historial** |

---

# 4. Recorrido por la interfaz

![Pantalla de inicio](img/01-inicio.png)

## 4.1 Elementos comunes

- **Encabezado.** A la izquierda, el botón **☰** que muestra u oculta el menú. A la derecha, el selector **Proyecto activo**: cambiar de proyecto actualiza todo lo que ves. Si no hay proyectos aparece el botón **Crear primer proyecto**.
- **Menú lateral.**

| Opción | Para qué sirve |
|---|---|
| **Inicio** | Resumen del proyecto, primeros pasos y últimas ejecuciones. |
| **Resumen** | Semáforo, tendencia, qué falla y desde cuándo; exporta el reporte de estatus. |
| **Espacio de trabajo** | Pantalla principal para enviar peticiones, editarlas y guardarlas. |
| **Proyectos** | Crear, editar, seleccionar y eliminar proyectos. |
| **Módulos** | Importar contratos OpenAPI/Swagger. |
| **Ambientes** | Ambientes, variables y secretos. |
| **Casos API** | Casos de petición HTTP guardados. |
| **Casos UI** | Casos de navegador con pasos y grabador. |
| **Suites** | Suites y flujos entre módulos. |
| **Observador** | Taps, catálogo de interfaces y cambios. |
| **Programaciones** | Ejecuciones automáticas. |
| **Historial** | Resultados de ejecuciones y evidencias. |
| **Importar / Exportar** | Paquetes ZIP y diagnóstico. |

- **Menú compacto.** En el **Espacio de trabajo** el menú se reduce a iconos para dejar espacio y **se expande al pasar el ratón** (imagen). En las demás pantallas se muestra completo.

![Menú expandido al pasar el ratón en el Espacio de trabajo](img/27-menu-expandido.png)

- **Mensajes.** Las confirmaciones aparecen abajo en verde; los errores, en rojo, con una explicación de qué corregir. Las acciones destructivas (eliminar, purgar) piden confirmación.
- **Pestañas animadas.** Al cambiar de pestaña el contenido se desliza un instante; si una captura o lectura parece «cortada», espera medio segundo.

## 4.2 Orden recomendado de trabajo

1. **Proyectos** → crea o elige uno.
2. **Módulos** → importa tu contrato (opcional pero muy útil).
3. **Ambientes** → registra dónde se prueba.
4. **Espacio de trabajo** → explora y guarda casos.
5. **Suites** → agrupa casos; **Programaciones** → automatiza.
6. **Observador** → vigila el tráfico y los cambios.

> **Consejo.** No necesitas seguir este orden para empezar a probar: puedes abrir el **Espacio de trabajo**, escribir una URL y enviarla sin tener proyecto ni ambiente. Los eliges al **guardar**.

---

# 5. Guía rápida: tu primera prueba en 10 minutos

Esta guía usa la aplicación de ejemplo incluida. Si prefieres usar tu propio servicio, sustituye las URL.

## 5.1 Prepara el servicio de ejemplo (opcional)

En una terminal, dentro de la carpeta del paquete:

```bat
.venv\Scripts\activate
python -m sample_app.server 8765
```

Queda un pequeño servicio en `http://127.0.0.1:8765` con `/health`, `/api/users/{id}`, `/api/login` y `/api/items`.

## 5.2 Envía tu primera petición

1. Abre **Espacio de trabajo** en el menú.
2. En la barra de petición deja el método en **GET**, escribe en la URL `http://127.0.0.1:8765/api/users/1` y pulsa **Enviar** (o **Ctrl+Enter**).
3. En el centro verás el código **200**, el tiempo y el cuerpo JSON. A la izquierda, la petición ya está en el **Historial**.

![Espacio de trabajo con una respuesta](img/11-espacio-respuesta.png)

## 5.3 Conviértela en una prueba

1. En el **inspector** (derecha) abre el icono **Pruebas** y pulsa **Generar pruebas**. LTW crea reglas a partir de la respuesta y **sugiere ignorar** los campos que cambian solos (por ejemplo `$.requested_at`).
2. Pulsa **Enviar** otra vez: junto a cada regla aparece ✓ o ✗.
3. Abre **Guardar**, escribe un nombre, elige **Crear proyecto nuevo…** con el nombre que quieras y pulsa **Guardar**.

Ya tienes un **caso de prueba** guardado, con su proyecto y su ambiente (creado automáticamente a partir de la URL).

## 5.4 Detecta un cambio

1. Cambia el servicio (por ejemplo, reinícialo con `set SAMPLE_DRIFT_USERS=1` antes de `python -m sample_app.server 8765`: ahora devuelve un `id` de texto y quita `role`).
2. En **Casos API**, pulsa ▶ junto a tu caso: **fallará** y te dirá qué campo cambió.
3. En el **Espacio de trabajo**, reenvía la petición y abre la pestaña **Diff**: verás las diferencias con la respuesta anterior.

## 5.5 Agrúpala en una suite y prográmala

1. **Suites → Nueva suite / flujo**: pon nombre, agrega tu caso desde «Casos disponibles» y **Guardar**.
2. **Programaciones**: elige la suite, frecuencia **Lunes a viernes**, hora `07:30`, tu zona horaria y **Programar**.
3. Deja abierto `scripts\scheduler.bat` para que se ejecute.

¡Listo! Ya recorriste el ciclo **explorar → guardar → vigilar → automatizar**. Los siguientes capítulos explican cada pantalla.
