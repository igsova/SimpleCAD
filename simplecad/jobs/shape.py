"""Run a curved-surface kernel operation in the isolated shape worker.

The worker gets a BREP snapshot and returns a BREP result; the document is
not touched here. With the GUI up, a progress dialog keeps FreeCAD responsive
and lets the user cancel; the model is unchanged until the caller applies the
result in its own transaction.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import FreeCAD as App
import Part

from .. import ROOT
from .runtime import runtime, environment

TIMEOUT = 600  # seconds


class Cancelled(ValueError):
    pass


def _wait_quietly(process, timeout):
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise ValueError('The operation took too long and was stopped; the model is unchanged.')


def _wait_with_dialog(process, folder, label, timeout):
    import FreeCADGui as Gui
    from ..gui.qt import QtCore, QtWidgets
    dialog = QtWidgets.QProgressDialog(label, 'Cancel', 0, 0, Gui.getMainWindow())
    dialog.setObjectName('SimpleCADShapeJob')
    dialog.setWindowTitle('SimpleCAD')
    dialog.setWindowModality(QtCore.Qt.WindowModal)
    dialog.setMinimumDuration(300)
    start = time.monotonic()
    try:
        while process.poll() is None:
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
            if dialog.wasCanceled():
                process.kill()
                process.wait()
                raise Cancelled('Canceled; the model is unchanged.')
            if time.monotonic() - start > timeout:
                process.kill()
                process.wait()
                raise ValueError('The operation took too long and was stopped; the model is unchanged.')
            try:
                stage = json.loads((folder / 'progress.json').read_text())['stage']
                dialog.setLabelText(label + '\n' + stage + '…')
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.02)
    finally:
        dialog.setObjectName('')  # deleted later; never found again as the live job
        dialog.close()
        dialog.deleteLater()


def run(operation, shape, options=None, profile=None, label='Working', timeout=TIMEOUT, dialog=None):
    """(result shape, report) from the worker; raises ValueError on failure."""
    folder = Path(tempfile.mkdtemp(prefix='simplecad-shape-'))
    try:
        shape.exportBrep(str(folder / 'source.brep'))
        if profile is not None:
            profile.exportBrep(str(folder / 'profile.brep'))
        (folder / 'options.json').write_text(json.dumps({'operation': operation, **(options or {})}))
        with open(folder / 'worker.log', 'w') as log:
            process = subprocess.Popen([runtime(), str(ROOT / 'scripts' / 'shape_worker.py'), str(folder)],
                                       env=environment(), stdout=log, stderr=subprocess.STDOUT)
            if App.GuiUp if dialog is None else dialog:  # MCP calls pass dialog=False
                _wait_with_dialog(process, folder, label, timeout)
            else:
                _wait_quietly(process, timeout)
        result = folder / 'result.json'
        if not result.is_file():
            details = (folder / 'worker.log').read_text(errors='replace')[-2000:]
            App.Console.PrintError('SimpleCAD shape worker (code %s):\n%s\n' % (process.returncode, details))
            raise ValueError('The kernel stopped unexpectedly on this geometry (code %s); the model is unchanged.'
                             % process.returncode)
        report = json.loads(result.read_text())
        if 'error' in report:
            raise ValueError(report['error'])
        output = Part.Shape()
        output.read(str(folder / 'result.brep'))
        if output.ShapeType == 'Compound' and len(output.Solids) == 1 and len(output.Faces) == len(output.Solids[0].Faces):
            output = output.Solids[0]
        elif output.ShapeType == 'Compound' and len(output.Faces) == 1 and not output.Shells:
            output = output.Faces[0]
        return output, report
    finally:
        shutil.rmtree(folder, ignore_errors=True)
