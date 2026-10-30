"""Main file for NiceGUI user simulation: (re)registers every page and route for each test."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for name in [m for m in list(sys.modules) if m == 'app.main' or m.startswith('app.pages')]:
    del sys.modules[name]
importlib.import_module('app.main')
from nicegui import ui  # noqa: E402

ui.run(storage_secret='test', reload=False)
