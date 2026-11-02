"""Local NiceGUI application. Run: python run.py"""
import os
from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app, ui
from . import core, logs
from .pages import observer_page, workspace_page, summary, home, projects, module_groups, modules, environments, cases, ui_cases, features, suites, schedules, runs, portable, llm_models, chat_page  # noqa: F401  (registers routes)

if core.migrate_legacy_data():
    logs.event('workspace.migrated', source=str(core.LEGACY_ROOT), target=str(core.ROOT))
core.initialize()
from . import agent  # noqa: E402
agent.register_api(app)


@app.get('/evidence/{run_id}/{filename}')
def evidence(run_id: str, filename: str):
    """Serves a screenshot/trace only if it is inside the evidence directory and belongs to the run."""
    try:
        return FileResponse(core.evidence_path(run_id, filename))
    except FileNotFoundError:
        raise HTTPException(404, 'Evidencia no disponible')
    except ValueError:
        raise HTTPException(400, 'Solicitud inválida')


def start(host='127.0.0.1', port=None, show=True):
    """Binds to loopback by default; never expose this app to untrusted networks."""
    port = port or int(os.environ.get('LTW_PORT', 8080))
    logs.event('app.started', host=host, port=port)
    ui.run(title='Local Test Workspace', host=host, port=port, show=show, reload=False,
           storage_secret=os.environ.get('LTW_STORAGE_SECRET', 'local-workspace-only'))
