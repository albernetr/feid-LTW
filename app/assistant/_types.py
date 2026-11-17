"""Tipos compartidos del paquete de Asistente — sin ningún import de `app.core` ni de `app.pages`, mismo
espíritu que `app/layouts/_types.py`: todo `app/assistant/` se puede copiar tal cual a otro proyecto.

Un turno es `{'who': 'user'|'assistant', 'text': str}`. Un hilo (`thread_key`) agrupa los turnos de una
conversación puntual — la página anfitriona decide esa clave (normalmente `f'{profile.name}:{entidad_id}'`),
`MemoryAdapter` no le impone ninguna forma más allá de ser un string."""
import abc
import dataclasses
from typing import Awaitable, Callable, List, Optional, Tuple


@dataclasses.dataclass(frozen=True)
class AssistantIntent:
    """Una de las "cosas que sabe hacer" el Asistente en una página — `assistant_panel` recorre los intents
    de `AssistantProfile.intents` en orden y usa el primero cuyas `keywords` aparezcan en el texto (en
    minúsculas) o cuyo `also_match(text)` devuelva verdadero; `handler(text)` hace el trabajo (típicamente
    llama a una función de LLM) y devuelve la respuesta a mostrar como turno del Asistente."""
    keywords: Tuple[str, ...]
    handler: Callable[[str], Awaitable[str]]
    also_match: Optional[Callable[[str], bool]] = None


@dataclasses.dataclass
class AssistantProfile:
    """Lo que una página declara para que `assistant_panel` sepa cómo comportarse — ver `panel.py`.

    - `catch`: tipos de excepción que se muestran como turno "No pude: {exc}" en vez de propagarse (la
      página decide cuáles son "errores esperables de pedirle algo mal al modelo", p. ej. `ValueError` más
      la excepción propia de su cliente LLM).
    - `fallback`: se llama con `(text, history)` (el hilo ANTES del turno que se está por responder) cuando
      ningún intent coincidió — típicamente una charla libre con el modelo."""
    name: str
    placeholder: str
    empty_hint: str
    tooltip: str = ''
    intents: List[AssistantIntent] = dataclasses.field(default_factory=list)
    fallback: Optional[Callable[[str, list], Awaitable[str]]] = None
    catch: Tuple[type, ...] = (ValueError,)


class MemoryAdapter(abc.ABC):
    """Persistencia de hilos de conversación, por `thread_key`. Las 6 operaciones abstractas son el contrato
    mínimo que cualquier backend debe implementar; `append`/`compact`/`clear` ya están resueltas acá en
    términos de esas 6 — ningún adaptador concreto necesita repetirlas.

    `is_enabled`/`set_enabled` gobiernan si ESE hilo se persiste — "deshabilitado" no implica borrar lo que
    ya había, solo que nuevos turnos no se agregan (ver `append`)."""

    @abc.abstractmethod
    def load(self, thread_key: str) -> list:
        """Los turnos de este hilo, en orden — `[]` si el hilo no existe todavía."""

    @abc.abstractmethod
    def save(self, thread_key: str, turns: list) -> None:
        """Reemplaza por completo los turnos guardados de este hilo (upsert)."""

    @abc.abstractmethod
    def delete(self, thread_key: str) -> None:
        """Borra el registro entero de este hilo (turnos + su estado de habilitado)."""

    @abc.abstractmethod
    def is_enabled(self, thread_key: str, default: bool = True) -> bool:
        """Si este hilo debe seguir recibiendo turnos nuevos — `default` para un hilo que todavía no existe."""

    @abc.abstractmethod
    def set_enabled(self, thread_key: str, value: bool) -> None:
        ...

    @abc.abstractmethod
    def list_threads(self) -> list:
        """Todos los hilos conocidos por este adaptador, para la pantalla global de administración:
        `[{'id': thread_key, 'enabled': bool, 'turn_count': int, 'updated_at': str}, ...]`."""

    @abc.abstractmethod
    def clear_all(self) -> None:
        """Borra TODOS los hilos de este adaptador — pensado para ir detrás de una confirmación fuerte."""

    def append(self, thread_key: str, turn: dict) -> None:
        self.save(thread_key, self.load(thread_key) + [turn])

    def compact(self, thread_key: str, keep_last: int = 20) -> None:
        """Recorte simple a los últimos `keep_last` turnos — sin resumen, a propósito (memoria "no muy
        elaborada")."""
        turns = self.load(thread_key)
        if len(turns) > keep_last:
            self.save(thread_key, turns[-keep_last:])

    def clear(self, thread_key: str) -> None:
        self.delete(thread_key)


class InMemoryAdapter(MemoryAdapter):
    """Referencia simple para tests y para la demo (`app/pages/assistant_demo.py`) — un dict en memoria de
    proceso, se pierde al reiniciar. No usar para páginas reales (ver `app/assistant_memory.py`)."""

    def __init__(self):
        self._data = {}   # thread_key -> {'turns': [...], 'enabled': bool, 'updated_at': str}

    def load(self, thread_key):
        return list(self._data.get(thread_key, {}).get('turns', []))

    def save(self, thread_key, turns):
        import datetime
        entry = self._data.setdefault(thread_key, {'enabled': True})
        entry['turns'] = list(turns)
        entry['updated_at'] = datetime.datetime.now().astimezone().isoformat()

    def delete(self, thread_key):
        self._data.pop(thread_key, None)

    def is_enabled(self, thread_key, default=True):
        return self._data.get(thread_key, {}).get('enabled', default)

    def set_enabled(self, thread_key, value):
        self._data.setdefault(thread_key, {'turns': []})['enabled'] = value

    def list_threads(self):
        return [{'id': key, 'enabled': entry.get('enabled', True), 'turn_count': len(entry.get('turns', [])),
                 'updated_at': entry.get('updated_at')} for key, entry in self._data.items()]

    def clear_all(self):
        self._data.clear()
