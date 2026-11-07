"""Puente Node.js + Playwright MCP (`--extension`) para Casos UI: a diferencia de «Navegador en vivo» (CDP,
ver recorder.py), que necesita que Playwright lance su propio Chromium con una bandera de depuración puesta
desde el arranque, este modo se engancha a una pestaña YA abierta en el Chrome/Edge de siempre del usuario, vía
la extensión «Playwright Extension» (Chrome Web Store) — así un sitio con detección de bots (Google y otros) ve
el navegador de siempre, no uno automatizado. Lanza `npx @playwright/mcp@latest --extension` como proceso
aparte; mcp_client.py habla el protocolo con él y mcp_steps.py traduce los pasos de un Caso UI a sus
herramientas.
"""
import shutil
import subprocess
import sys
import time
from . import mcp_client

DEFAULT_MCP_PORT = 8931

_PROCESSES = {}  # puerto -> subprocess.Popen, solo de los que lanzó ESTA sesión de LTW (ver close_mcp_bridge)


def node_available():
    return shutil.which('npx') is not None


def mcp_server_running(port, timeout=1.0):
    """True si hay un servidor Playwright MCP respondiendo en ese puerto."""
    try:
        mcp_client.MCPSession(port, timeout=timeout).initialize()
        return True
    except Exception:
        return False


def launch_mcp_bridge(port=DEFAULT_MCP_PORT, profile_dir_name=None, timeout=30):
    """Lanza `npx @playwright/mcp@latest --extension` apuntando a este puerto — Casos UI posteriores se
    conectan a él en vivo (ver mcp_steps.run_mcp_steps) en lugar de que Playwright abra su propio Chromium."""
    if not node_available():
        raise ValueError('Esto necesita Node.js instalado (https://nodejs.org) — no se encontró "npx" en el PATH.')
    if mcp_server_running(port):
        raise ValueError(f'Ya hay un puente MCP abierto en el puerto {port} — cerralo primero si querés reiniciarlo.')
    args = ['npx', '-y', '@playwright/mcp@latest', '--extension', '--host', '127.0.0.1', '--port', str(port)]
    if profile_dir_name:
        args += ['--profile-dir-name', profile_dir_name]
    popen_kwargs = {'close_fds': True}
    if sys.platform == 'win32':
        popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'DETACHED_PROCESS', 0)
    else:
        popen_kwargs['start_new_session'] = True
    process = subprocess.Popen(args, **popen_kwargs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if mcp_server_running(port):
            _PROCESSES[port] = process
            return
        if process.poll() is not None:
            raise ValueError(f'El puente MCP no arrancó (terminó solo con código {process.returncode}).')
        time.sleep(0.3)
    process.terminate()
    raise ValueError('El puente MCP no terminó de abrir a tiempo (¿el puerto ya estaba ocupado por otra cosa?).')


def close_mcp_bridge(port):
    """A diferencia del navegador en vivo (que se cierra pidiéndoselo al propio Chromium vía CDP), el servidor
    MCP no tiene una herramienta para «apagate vos mismo» — solo se puede terminar el proceso, y solo si lo
    lanzó esta misma sesión de LTW (si lo abrió otra sesión, o se reinició LTW, no hay forma de rastrearlo acá:
    hay que cerrarlo a mano)."""
    process = _PROCESSES.pop(port, None)
    if process is None:
        raise ValueError(f'No hay un puente MCP en el puerto {port} que esta sesión haya abierto — '
                          'cerralo a mano (Administrador de tareas) si sigue corriendo.')
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
