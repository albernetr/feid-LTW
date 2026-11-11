"""Tipos compartidos del paquete de layouts — sin ningún import de `app.core` ni de `app.pages`, para que todo
`app/layouts/` se pueda copiar tal cual a otro proyecto."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Panel:
    """Un panel que `workspace_layout` puede mostrar — en el riel lateral (si viene en `side_panels`) o como
    ancla siempre disponible en el centro (si viene en `center_anchors`), ver `workspace.py`.

    `render` se puede invocar MÁS DE UNA VEZ EN LA MISMA PÁGINA (una vez en el panel lateral, otra si se
    arrastra una copia al centro) — debe ser seguro llamarlo dos veces, leyendo/escribiendo el mismo estado
    externo que comparta con la otra instancia, nunca asumir que es la única instancia montada."""
    key: str
    label: str
    icon: str
    render: Callable[[], None]
    draggable: bool = True
