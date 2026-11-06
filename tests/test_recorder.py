"""Navegador en vivo (CDP) para Casos UI: conectarse a un Chromium ya abierto y logueado en lugar de repetir
cookies capturadas en un contexto nuevo — pensado para proveedores de identidad que atan la sesión al
navegador/dispositivo concreto. Ver app/recorder.py y automation.execute_ui."""
import httpx
import pytest
from app import core, recorder


def test_live_browser_running_true_when_the_cdp_endpoint_answers(monkeypatch):
    monkeypatch.setattr(recorder.httpx, 'get', lambda url, timeout=None: httpx.Response(200))
    assert recorder.live_browser_running(9222) is True


def test_live_browser_running_false_when_nothing_is_listening(monkeypatch):
    def refused(url, timeout=None):
        raise httpx.ConnectError('refused')
    monkeypatch.setattr(recorder.httpx, 'get', refused)
    assert recorder.live_browser_running(9222) is False


def test_launch_live_browser_refuses_a_second_one_on_the_same_port(monkeypatch):
    monkeypatch.setattr(recorder, 'live_browser_running', lambda port, timeout=1.0: True)

    def fail_popen(*a, **k):
        raise AssertionError('no debería intentar abrir uno nuevo si ya hay uno corriendo en ese puerto')
    monkeypatch.setattr(recorder.subprocess, 'Popen', fail_popen)
    with pytest.raises(ValueError, match='Ya hay un navegador en vivo'):
        recorder.launch_live_browser('env-1', 'https://qa.example.com', port=9222)


def test_launch_live_browser_raises_if_the_cdp_port_never_comes_up(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(recorder, 'live_browser_running', lambda port, timeout=1.0: False)
    monkeypatch.setattr(recorder, '_chromium_executable', lambda: 'chromium-stub')
    monkeypatch.setattr(recorder.subprocess, 'Popen', lambda *a, **k: None)   # nunca arranca de verdad
    with pytest.raises(ValueError, match='no terminó de abrir a tiempo'):
        recorder.launch_live_browser('env-1', 'https://qa.example.com', port=9222, timeout=0.2)


def test_launch_live_browser_rejects_an_invalid_url(monkeypatch):
    monkeypatch.setattr(recorder, 'live_browser_running', lambda port, timeout=1.0: False)
    with pytest.raises(ValueError, match='URL inválida'):
        recorder.launch_live_browser('env-1', 'no-es-una-url', port=9222)


def test_delete_live_profile_does_not_fail_when_there_was_none(tmp_path, monkeypatch):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    recorder.delete_live_profile('env-sin-perfil')   # no debe tirar, aunque nunca se haya abierto un navegador en vivo
