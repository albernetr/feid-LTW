"""Puente Node.js + Playwright MCP («--extension») para Casos UI: conectarse a una pestaña YA abierta y
logueada en el Chrome/Edge de siempre, vía su extensión, en vez de que Playwright lance su propio Chromium —
así un sitio con detección de bots (Google y otros) no lo marca como automatizado. Ver app/mcp_bridge.py y
automation.execute_ui."""
import subprocess
import pytest
from app import mcp_bridge, mcp_client


def test_mcp_server_running_true_when_initialize_succeeds(monkeypatch):
    monkeypatch.setattr(mcp_client.MCPSession, 'initialize', lambda self: {'serverInfo': {}})
    assert mcp_bridge.mcp_server_running(9931) is True


def test_mcp_server_running_false_when_nothing_is_listening(monkeypatch):
    def refuse(self):
        raise mcp_client.MCPError('nope')
    monkeypatch.setattr(mcp_client.MCPSession, 'initialize', refuse)
    assert mcp_bridge.mcp_server_running(9931) is False


def test_launch_mcp_bridge_requires_node(monkeypatch):
    monkeypatch.setattr(mcp_bridge, 'node_available', lambda: False)
    with pytest.raises(ValueError, match='Node.js'):
        mcp_bridge.launch_mcp_bridge(port=9931)


def test_launch_mcp_bridge_refuses_a_second_one_on_the_same_port(monkeypatch):
    monkeypatch.setattr(mcp_bridge, 'node_available', lambda: True)
    monkeypatch.setattr(mcp_bridge, 'mcp_server_running', lambda port, timeout=1.0: True)

    def fail_popen(*a, **k):
        raise AssertionError('no debería intentar abrir uno nuevo si ya hay uno corriendo en ese puerto')
    monkeypatch.setattr(mcp_bridge.subprocess, 'Popen', fail_popen)
    with pytest.raises(ValueError, match='Ya hay un puente MCP'):
        mcp_bridge.launch_mcp_bridge(port=9931)


def test_launch_mcp_bridge_raises_if_the_bridge_never_comes_up(monkeypatch):
    monkeypatch.setattr(mcp_bridge, 'node_available', lambda: True)
    monkeypatch.setattr(mcp_bridge, 'mcp_server_running', lambda port, timeout=1.0: False)

    class FakeProcess:
        def poll(self):
            return None  # nunca termina solo, durante toda la espera

        def terminate(self):
            pass
    monkeypatch.setattr(mcp_bridge.subprocess, 'Popen', lambda *a, **k: FakeProcess())
    with pytest.raises(ValueError, match='no terminó de abrir a tiempo'):
        mcp_bridge.launch_mcp_bridge(port=9931, timeout=0.2)


def test_launch_mcp_bridge_raises_a_clear_error_if_the_process_exits_on_its_own(monkeypatch):
    monkeypatch.setattr(mcp_bridge, 'node_available', lambda: True)
    monkeypatch.setattr(mcp_bridge, 'mcp_server_running', lambda port, timeout=1.0: False)

    class FakeProcess:
        returncode = 1

        def poll(self):
            return 1  # terminó solo (p. ej. "npx" no encontró el paquete)
    monkeypatch.setattr(mcp_bridge.subprocess, 'Popen', lambda *a, **k: FakeProcess())
    with pytest.raises(ValueError, match='no arrancó'):
        mcp_bridge.launch_mcp_bridge(port=9931, timeout=2)


def test_launch_mcp_bridge_tracks_the_process_it_started(monkeypatch):
    monkeypatch.setattr(mcp_bridge, 'node_available', lambda: True)
    calls = {'n': 0}

    def fake_running(port, timeout=1.0):
        calls['n'] += 1
        return calls['n'] > 1  # "no" la primera vez (antes de lanzar), "sí" después
    monkeypatch.setattr(mcp_bridge, 'mcp_server_running', fake_running)

    class FakeProcess:
        pass
    process = FakeProcess()
    monkeypatch.setattr(mcp_bridge.subprocess, 'Popen', lambda *a, **k: process)
    mcp_bridge.launch_mcp_bridge(port=9932, timeout=2)
    assert mcp_bridge._PROCESSES[9932] is process
    mcp_bridge._PROCESSES.pop(9932, None)


def test_close_mcp_bridge_raises_when_this_session_never_opened_it():
    with pytest.raises(ValueError, match='No hay un puente MCP'):
        mcp_bridge.close_mcp_bridge(59999)


def test_close_mcp_bridge_terminates_the_tracked_process():
    class FakeProcess:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            pass
    process = FakeProcess()
    mcp_bridge._PROCESSES[59998] = process
    mcp_bridge.close_mcp_bridge(59998)
    assert process.terminated is True
    assert 59998 not in mcp_bridge._PROCESSES


def test_close_mcp_bridge_kills_if_it_does_not_terminate_in_time():
    class FakeProcess:
        def __init__(self):
            self.killed = False

        def terminate(self):
            pass

        def wait(self, timeout=None):
            raise subprocess.TimeoutExpired(cmd='npx', timeout=timeout)

        def kill(self):
            self.killed = True
    process = FakeProcess()
    mcp_bridge._PROCESSES[59997] = process
    mcp_bridge.close_mcp_bridge(59997)
    assert process.killed is True
