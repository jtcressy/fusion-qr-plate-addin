"""QR Plate — Fusion add-in entry point.

Deliberately tiny. Fusion caches an add-in's entry module across Stop/Run, so
any code living here would keep running the version loaded when Fusion
started; the dialog and geometry live in modules that ui.py reloads, which
makes restarting the add-in enough to pick up source edits.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ui = None


def run(_context):
    global _ui
    import ui as ui_module

    _ui = importlib.reload(ui_module)
    _ui.start()


def stop(_context):
    if _ui:
        _ui.stop()
