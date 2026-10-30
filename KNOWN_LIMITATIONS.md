# Limitaciones conocidas

> Qué tan maduro está cada sección (estable / beta / experimental), con el aviso de responsabilidad completo: [README.md](README.md#qué-tan-maduro-está-cada-parte).

## Seguridad y alcance
- **Sin autenticación propia**: la interfaz escucha solo en `127.0.0.1`, pero cualquier proceso local puede usarla. No la expongas a la red.
- Los ambientes pueden apuntar a hosts internos (por diseño). Ejecuta solo contra sistemas autorizados.
- La redacción de secretos elimina los **valores registrados** (almacén/variables de entorno de autenticación) y los headers sensibles conocidos. Un dato sensible que el servidor devuelva en el cuerpo y que no sea un secreto registrado (p. ej. un token de sesión de una respuesta de login) se guarda en el historial. Trata el historial como restringido y usa *Retención*.
- Los valores *escritos* en pasos UI como texto literal (sin `{{secret:…}}`) quedan en el caso y en el historial.
- El bloqueo de hosts del ejecutor UI cubre navegaciones; no es un sandbox: recursos secundarios (imágenes, scripts) de otros hosts siguen cargándose.
- En Linux sin servicio de secretos (sin Secret Service/KWallet) `keyring` puede fallar; se usa la variable de entorno del mismo nombre como alternativa.

## Protocolo para agentes y espacio de trabajo
- El diagnóstico de los fallos es **heurístico** (categorías por código HTTP, forma de la respuesta y tipo de error): orienta, no decide. `where_to_look` solo contiene lo que el autor de la spec puso en `code_hints`, el contrato OpenAPI importado y los cambios observados; la herramienta **no lee tu código**.
- `POST /agent/v1/run` es síncrono (una suite larga mantiene la petición abierta) y guarda en el proyecto de la spec; para no dejar rastro usa la CLI sin `--persist`.
- La spec cubre casos API (no casos UI) y no importa Postman/OpenAPI: eso lo hace el agente generando la spec.
- El token de la API local vive en la base del workspace: con una base compartida, quien tenga acceso a ella lo ve. Regéneralo si hace falta.
- El historial del espacio de trabajo guarda el cuerpo enviado y la respuesta (hasta 100 000 caracteres) de cada envío, también en una base compartida: usa datos de preproducción.
- Una petición a la vez en el editor (no hay varias pestañas de borrador); los separadores recuerdan su posición por navegador.
- El editor JSON no ofrece autocompletado; el visor de respuestas limita el texto a 200 000 caracteres.

## Observador de interfaces
- Solo JSON. Respuestas o cuerpos que no son JSON se cuentan pero no se analizan; no hay WebSockets ni streaming.
- El tap escucha solo en `127.0.0.1`, habla HTTP simple con quien llama (no termina TLS; hacia el destino sí puede usar https), reenvía una petición por conexión y rechaza cuerpos `chunked` o de más de 5 MB. Se detiene al cerrar la aplicación.
- Un tap añade una escritura a la base por llamada: no es para carga alta.
- El enmascarado se basa en nombres de campo; un dato sensible con un nombre no previsto se guardaría en los ejemplos y muestras. Úsalo en preproducción.
- Lo «obligatorio» y los cambios se infieren de lo observado: un campo que aún no apareció no se conoce, y un cambio de comportamiento que no altera la forma del JSON no se detecta (para eso están los casos de regresión).
- Las interfaces se identifican por el nombre del módulo: tap e historial solo se unifican si usan el mismo nombre.

## Reiniciar workspace
- Borra la base y, por defecto, las evidencias; **no se puede deshacer** y no hay papelera. Exporta antes (`/portable`) si quieres conservar algo.
- No toca los secretos del Administrador de credenciales: son por nombre, no por workspace, y podrían usarse en otro ambiente.
- Por línea de comandos (`python run.py --reset-workspace --yes`) actúa sobre el workspace que `TEST_WORKSPACE_HOME` (o el valor por defecto) resuelva en ese momento; cierra el scheduler y la interfaz antes, o puede fallar por archivo en uso.

## Base de datos compartida
- SQLite sobre un recurso de red depende de que el sistema de archivos respete los bloqueos; algunos NAS no lo hacen bien. Para uso concurrente intenso se necesitaría un servidor de base de datos (no incluido).
- La detección de conflictos cubre la edición de casos, casos UI y suites; el resto de pantallas escribe «el último gana».
- Los pasos con ambiente propio y el enriquecimiento aplican a casos API; los casos UI no usan reglas de enriquecimiento.
- El historial guarda el body enviado y las respuestas completas (hasta 50 000 caracteres): pensado para preproducción; no uses datos personales reales.

## Sitios de terceros
- **Google bloquea la automatización**: una búsqueda en `google.com` desde el ejecutor devolvió su página «unusual traffic» (detección de bots). La herramienta no intenta evadir ni resolver esas verificaciones; para pruebas usa sitios propios o autorizados.
- Un caso solo puede navegar dentro del host de su ambiente: probar dos sitios distintos requiere dos casos/ambientes.
- **Cuidado con aserciones débiles**: `assert_url` solo mira la URL, que cambia antes de que cargue la página (y también en páginas de bloqueo). Para dar por buena una navegación, espera un elemento del contenido (`assert_visible` / `assert_text`) y, si aplica, verifica que *no* aparece un mensaje de error.

## Funcionalidad
- Sin importadores Postman/Bruno, sin OAuth2/Basic, sin reportes HTML/JUnit, sin ejecución en paralelo.
- **Exploración automática**: solo ejecuta lecturas (GET); nunca llama POST/PUT/PATCH/DELETE. El emparejamiento de identificadores con parámetros de ruta es por **nombre** (`dataset_id` ↔ un listado llamado `datasets`), no por tipo: puede tomar un identificador del formato equivocado para una ruta cuyo parámetro se llama parecido, lo que aparece como un «400 formato inválido» en vez de un hallazgo real — conviene revisarlo antes de dar por buena esa fila. No autentica por sí sola: si el servicio requiere token, pásalo con `--header "Authorization: Bearer …"` (CLI) o con las cabeceras del caso antes de explorar.
- JSONPath es un subconjunto (`$.a.b[0]['k'][*]`); no soporta filtros `?()` ni recursión `..`.
- El grabador importa solo locators directos (`get_by_label/text/role/test_id/placeholder`) y las acciones listadas; selectores CSS, `.first/.nth`, `filter`, `evaluate`, esperas y expresiones regulares se **reportan** y deben recrearse a mano.
- Los OpenAPI con `$ref` externos se rechazan. Los `$ref` circulares (modelos recursivos) se aceptan cortando la recursión donde se repite: ahí el esquema queda abierto y la validación contra el contrato es más permisiva.
- La cancelación de una suite es cooperativa: espera a que termine el caso en curso.
- La suite se ejecuta en el proceso de la interfaz; cerrar la pestaña no la detiene, cerrar la aplicación sí.
- Las ejecuciones perdidas se evalúan por programación al iniciar el scheduler (una vez, o se omiten según política); no se recuperan todas las ocurrencias intermedias.
- El scheduler no es un servicio de Windows: hay que mantener `scheduler.bat` abierto (o crear una tarea programada propia).
- El lock del scheduler se recupera 120 s después del último latido si el proceso murió sin liberarlo.

## Plataformas y entrega
- Alcance actual: **Windows con Python 3.11+ instalado**. Probado en Windows 11 con Python 3.13; Linux/macOS no se han validado.
- La base está en `data/` dentro del paquete: no se ejecuta desde ubicaciones de solo lectura sin caer al perfil del usuario, y los secretos **no** viajan con el paquete (están en el Administrador de credenciales de cada equipo).
- El ejecutable PyInstaller no incluye Chromium de Playwright: los casos UI requieren `python -m playwright install chromium` en el equipo destino (o una instalación previa de Playwright). Ver `TEST_REPORT.md` para el estado de validación del ejecutable.
- NiceGUI 3.x es requisito (la subida de archivos cambió respecto a 2.x).
