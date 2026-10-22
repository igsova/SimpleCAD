"""Run tests/gui/gui_*.py suites inside the FreeCAD GUI, then quit.

FreeCAD runs a Python file given on its command line after startup:

    SC_GUI_TESTS=gui_mesh_region,gui_mesh_stretch FreeCAD scripts/run_gui_tests.py

Each name is a module in tests/gui/ or tests/benchmarks/ (or an absolute path)
with a run() function. Suites may import helpers from tests/unit/.
Output goes to SC_GUI_LOG (default: simplecad-gui-tests.log in the temporary
directory). The process exits 0 only if every suite passed. Use a scratch
FreeCAD session: suites create and close their own temporary documents.
"""
import os
import runpy
import sys
import tempfile
import traceback
from pathlib import Path

import FreeCAD  # noqa: F401  Load the application before its native modules.
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

LOG = open(os.environ.get('SC_GUI_LOG', str(Path(tempfile.gettempdir())/'simplecad-gui-tests.log')), 'w', buffering=1)


def run_all():
    code = 0
    sys.stdout = sys.stderr = LOG
    from simplecad import ROOT
    folders = [ROOT/'tests'/folder for folder in ('gui', 'benchmarks', 'unit')]
    sys.path[:0] = [str(folder) for folder in folders]
    for name in [n for n in os.environ.get('SC_GUI_TESTS', 'gui_smoke').split(',') if n]:
        print('=== RUN', name, flush=True)
        try:
            # The scratch window can lose macOS activation between suites.
            # Establish Qt's active window before synthetic keyboard checks;
            # otherwise focusWidget() may be null even after setFocus().
            window = Gui.getMainWindow()
            window.raise_(); window.activateWindow()
            QtWidgets.QApplication.setActiveWindow(window)
            QtWidgets.QApplication.processEvents()
            path = name if os.path.isabs(name) else next(
                (str(folder/(name+'.py')) for folder in folders if (folder/(name+'.py')).is_file()), name)
            runpy.run_path(path)['run']()
            print('=== OK', name, flush=True)
        except BaseException:
            traceback.print_exc(); code = 1
            print('=== FAIL', name, flush=True)
    LOG.flush()
    os._exit(code)


QtCore.QTimer.singleShot(1500, run_all)
