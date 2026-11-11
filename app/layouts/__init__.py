"""Layouts de NiceGUI reutilizables y portables (sin ningún import de `app.core` ni de `app.pages`) — se
puede copiar esta carpeta entera a otro proyecto.

Nivel 0 (`app_shell`): header + drawer colapsable + columna de contenido.
Nivel 1 (`workspace_layout`): splitter documento/centro vs. panel lateral con riel de íconos, arrastrar al
centro, alternar pestañas/dividido — se monta DENTRO de `app_shell`.

Ver `app/pages/layouts_demo.py` para un ejemplo de uso completo."""
from ._types import Panel
from .shell import app_shell
from .workspace import WorkspaceHandle, workspace_layout

__all__ = ['Panel', 'app_shell', 'workspace_layout', 'WorkspaceHandle']
