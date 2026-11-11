"""Tipos compartidos del paquete de layouts — sin ningún import de `app.core` ni de `app.pages`, para que todo
`app/layouts/` se pueda copiar tal cual a otro proyecto."""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Panel:
    """Un panel que `workspace_layout` puede mostrar — en el riel lateral (si viene en `side_panels`) o como
    ancla siempre disponible en el centro (si viene en `center_anchors`), ver `workspace.py`.

    `render` se puede invocar MÁS DE UNA VEZ EN LA MISMA PÁGINA (una vez en el panel lateral, otra si se
    arrastra una copia al centro) — debe ser seguro llamarlo dos veces, leyendo/escribiendo el mismo estado
    externo que comparta con la otra instancia, nunca asumir que es la única instancia montada.

    `on_remove`: se llama DESPUÉS de que `workspace_layout` ya sacó este panel del centro (al cerrarlo con la
    "x") — para que la página anfitriona sincronice su propio estado si hace falta (p. ej. un panel que
    también puede vivir en otro lugar de la página, y que al cerrarse del centro debería volver ahí)."""
    key: str
    label: str
    icon: str
    render: Callable[[], None]
    draggable: bool = True
    on_remove: Optional[Callable[[], None]] = None
