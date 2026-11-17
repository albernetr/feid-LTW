"""Asistente de IA reutilizable y portable (sin ningún import de `app.core` ni de `app.pages`) — se puede
copiar esta carpeta entera a otro proyecto.

El contrato (`AssistantProfile`/`AssistantIntent`) lo declara cada página; `MemoryAdapter` es la interfaz de
persistencia (ver `app/assistant_memory.py` para los adaptadores concretos de este proyecto); el chrome de UI
(`assistant_panel`/`assistant_header`/`assistant_memory_menu_items`) se monta como el render de un `Panel`
más dentro de `workspace_layout` (Nivel 1, en `app/layouts/`).

Ver `app/pages/assistant_demo.py` para un ejemplo de uso completo."""
from ._types import AssistantIntent, AssistantProfile, InMemoryAdapter, MemoryAdapter
from .panel import assistant_header, assistant_memory_menu_items, assistant_panel

__all__ = ['AssistantIntent', 'AssistantProfile', 'MemoryAdapter', 'InMemoryAdapter',
           'assistant_panel', 'assistant_header', 'assistant_memory_menu_items']
