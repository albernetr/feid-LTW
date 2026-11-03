# Guía rápida: Suites y flujos

Manual paso a paso de la pantalla **Suites** (`/suites`), con lo último que se agregó: filtrar por etiqueta,
agregar varios casos de una vez, editar un caso sin salir de la suite, encadenar datos entre pasos, un
consecutivo propio por suite, y duplicar una suite entera.

Ejemplo usado en toda la guía: un flujo de 3 pasos — **Login** → **Ver pedidos** → **Crear pedido** — donde el
token que devuelve el Login se usa para autenticar el resto, y cada pedido creado necesita un nombre único.

---

## 1. Crear una suite nueva

1. Andá a **Suites** (menú lateral) → **«+ Nueva suite / flujo»**.
2. Arriba completá:
   - **Nombre**: algo descriptivo (ej. «Flujo de pedidos»).
   - **Ambiente por defecto**: el ambiente que van a usar los pasos que no elijan uno propio.
   - **Funcionalidad (opcional)**: si querés ligar esta suite a una capacidad de negocio ya creada en Funcionalidades.
   - **Política de fallo**: «Continuar tras un fallo» (sigue con los pasos siguientes aunque uno falle) o «Detener al
     primer fallo».
   - **Reintentos por caso** / **Espera entre reintentos**: cuántas veces reintentar un paso que falla, y cuánto
     esperar entre intento e intento.

---

## 2. Agregar casos al flujo

La columna izquierda («Casos disponibles») lista todos los casos API del proyecto activo.

### Buscar por nombre
Escribí en **«Filtrar por nombre»** — la lista se acota al instante.

### Filtrar por etiqueta
Si tus casos tienen etiquetas (las mismas que usa Casos API), aparecen como **chips** debajo del filtro de
nombre (ej. `auth`, `pedidos`, `usuarios`). Tocá una para acotar la lista a esa etiqueta; tocala de nuevo para
quitarla. Útil cuando el proyecto tiene cientos de casos (por ejemplo, uno explorado automáticamente desde un
contrato grande) y buscar uno por uno no es práctico.

### Agregar un caso
- Botón **➕** junto al caso: lo agrega como el último paso del flujo.
- Si un caso **ya está agregado**, se queda igual en la lista (no desaparece — a veces necesitás el mismo caso
  dos veces, por ejemplo llamar el mismo endpoint con un consecutivo distinto cada vez) pero ahora muestra un
  distintivo verde **«Agregado»** (o **«Agregado ×2»**, **«×3»**... si lo agregaste varias veces).

### Agregar varios casos de una sola vez
Cuando el filtro (nombre y/o etiqueta) deja más de un caso visible, aparece el botón
**«Agregar los N visibles»** — los suma todos al flujo en el orden en que aparecen en la lista, de un solo clic.

> **Ejemplo**: filtrás por la etiqueta `pedidos` → aparecen «Ver pedidos» y «Crear pedido» → tocás «Agregar los
> 2 visibles» → los dos quedan agregados al final del flujo.

---

## 3. Ordenar y nombrar los pasos

En la columna derecha («Orden de ejecución») cada paso tiene:

- **Nombre del paso** (el *alias*): un nombre corto para referenciarlo desde pasos posteriores (ej. `login`,
  `crear_pedido`). Se genera solo a partir del nombre del caso, pero lo podés cambiar.
- **Ambiente**: por defecto usa el «Ambiente por defecto» de la suite; podés elegir uno distinto para ese paso
  puntual (útil si el flujo cruza varios servicios/componentes).
- **↑ / ↓**: mueve el paso dentro del orden.
- **✕**: lo saca del flujo (no borra el caso, solo el paso).

> Un paso solo puede usar respuestas de pasos que estén **antes** que él. Si reordenás, se vuelve a validar al
> guardar.

---

## 4. Editar un caso sin salir de la suite

Junto a cada caso (en «Casos disponibles» o ya agregado en «Orden de ejecución») hay un ícono de **lápiz**.

1. Tocalo → la pantalla cambia a «Editando «‹nombre del caso›»», en el **mismo lugar** donde estaba la suite
   (no es una ventana emergente, y no te saca de la página).
2. Ahí podés ajustar:
   - **Nombre, Método, Ruta**.
   - **Headers** y **Query params** (agregar/quitar filas).
   - **Body (JSON)**: un editor en árbol, con flechas para plegar/desplegar cualquier sección — igual que un
     formateador de JSON — en vez de un cuadro de texto plano.
   - **Aserciones** (pestaña aparte): las reglas que definen si el caso pasa o falla.
3. **«Guardar»** graba los cambios en el caso (afecta a **todas** las suites que lo usan, no solo esta).
4. **«← Volver a la suite»** (arriba, o el botón de abajo) te devuelve al editor de la suite — lo que ya habías
   armado (pasos agregados, variables, nombre de la suite, todo lo que no hayas guardado todavía) **sigue ahí**,
   nada se pierde por entrar a editar un caso.

> El componente/contrato (de dónde vino el caso) y el **encadenamiento** (extracción, pestaña «Encadenamiento»
> en Casos API) no se editan acá — para eso abrí el caso directamente desde **Casos API**.

---

## 5. Encadenar datos entre pasos («Enriquecer»)

Esto deja que un paso use algo que devolvió un paso **anterior** — por ejemplo, el token de autenticación que
entregó el Login, para usarlo en el header del paso siguiente.

1. En el paso que necesita el dato (ej. «Crear pedido»), tocá **«Enriquecer»**.
2. **«+ Agregar regla»** y completá:
   - **Acción**: `Asignar / agregar` (lo más común), `Quitar`, o `Combinar`.
   - **Destino**: `Body`, `Header`, `Query` o `Ruta`.
   - Si el destino admite una ruta (Body/Header/Query), completá dónde va (ej. el nombre del header,
     `Authorization`).
   - **Origen**, con cuatro formas de traer el valor:
     | Origen | Para qué sirve |
     |---|---|
     | **Valor fijo** | Un texto/número/booleano fijo, siempre el mismo. |
     | **Respuesta de un paso anterior** | Toma un valor (o toda la respuesta) de un paso previo — elegís el paso y, opcionalmente, una ruta JSON dentro de su respuesta (ej. `$.token`). |
     | **Variable** | Usa una de las «Variables compartidas iniciales» de la suite (ver sección 6). |
     | **Texto con referencias** | Un texto libre que puede incluir `{{@paso:$.ruta}}` (para mezclar con otro texto, ej. `Bearer {{@login:$.token}}`) y `{{variable}}`. |
3. **«Vista previa»**: muestra qué se mandaría, usando la **última respuesta registrada** de los pasos
   anteriores. Si todavía no corriste la suite, va a avisar «Sin datos registrados de: ‹paso›» — normal la
   primera vez; corré la suite una vez y la vista previa ya tiene datos reales para mostrar.
4. **«Listo»** cierra el diálogo. El botón del paso ahora dice **«Enriquecer (N)»** con la cantidad de reglas
   que tiene.

> Esto **no modifica el caso** — solo aplica dentro de esta suite, en este paso puntual.

---

## 6. Variables compartidas y consecutivo propio

Sección **«Variables compartidas iniciales»**, debajo del flujo.

### Variables compartidas
Una tabla nombre/valor disponible como `{{nombre}}` en **todos** los casos de la suite, desde el primer paso.
Además, lo que un caso **extrae** de su respuesta (pestaña «Encadenamiento» del caso) se suma automáticamente a
este mismo pool para los pasos siguientes — no hace falta declararlo acá también.

### Consecutivo propio de esta suite
Campo **«Consecutivo propio de esta suite (opcional)»**. Si lo completás con un número:

- `{{seq}}` en cualquier caso de esta suite arranca en ese número.
- Sube de a uno **por paso** (no por cada uso de `{{seq}}` dentro de un mismo paso) en cada corrida de la suite.
- Es propio de esta suite — no toca el consecutivo global de `{{seq}}` que usa el resto de la app (ese nunca se
  reinicia).

> Si dejás el campo vacío, `{{seq}}` en esta suite usa el consecutivo global de siempre.

> ¿Necesitás un consecutivo que seguir usando **fuera** de una suite (por ejemplo, en Casos API o en Chat) y que
> una suite después continúe exactamente donde quedó, en vez de reiniciarse? Usá `{{seq:nombre}}` (con un nombre
> a elección, ej. `{{seq:conversacion}}`) en el caso — es un consecutivo con nombre propio, independiente del
> global y del de la suite, que retoma donde quedó sin importar desde dónde se use.

---

## 7. Guardar, ejecutar y ver el resultado

- **«Guardar»**: graba la suite y vuelve a la lista.
- **«Guardar y ejecutar»**: graba y corre el flujo ahí mismo. Al terminar, muestra un resumen con **Pasó/Falló**
  por paso.
- **«Ver detalle»** de un paso: método, URL, las reglas de enriquecimiento aplicadas, **«Petición enviada (lo
  que salió)»** (el body/headers ya resueltos, con `{{variables}}` y `{{seq}}` reemplazados), el resultado de
  cada aserción, y la respuesta completa.
- **«Volver»**: sale sin guardar.

Desde la lista de **Suites**, el botón ▶ (play) corre una suite ya guardada sin entrar a editarla.

---

## 8. Duplicar una suite

En la lista de **Suites**, junto a Ejecutar/Editar/Eliminar, hay un ícono de **copiar** (dos hojas superpuestas).
Tocalo y se crea una copia completa — mismos pasos, mismo enriquecimiento, mismas variables y el mismo
consecutivo propio — con el nombre original más « (copia)» al final. Útil para armar una variante de un flujo
existente sin arriesgar el original.

---

## Resumen de atajos

| Qué querés hacer | Dónde |
|---|---|
| Encontrar casos entre muchos | Filtro por nombre + chips de etiqueta, en «Casos disponibles» |
| Agregar varios casos juntos | «Agregar los N visibles» |
| Usar el mismo caso dos veces en el flujo | Tocá «➕» de nuevo — se permite, y queda marcado «Agregado ×2» |
| Ajustar un header/body/aserción sin salir de la suite | Lápiz junto al caso → editás → «← Volver a la suite» |
| Pasar un dato de un paso a otro (ej. un token) | «Enriquecer» en el paso que lo necesita |
| Un valor fijo disponible en toda la suite | «Variables compartidas iniciales» |
| Un `{{seq}}` que arranca en un número elegido y se reinicia cada corrida | «Consecutivo propio de esta suite» |
| Un consecutivo que sigue donde quedó, incluso fuera de la suite | `{{seq:nombre}}` en el caso |
| Clonar un flujo entero para variarlo | Ícono «Duplicar» en la lista de Suites |
