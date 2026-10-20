"""⌘C, ⌘X and ⌘V (Ctrl on Windows and Linux) for whole objects.

They work in the 3D view and the Model tab. SimpleCAD keeps
its own copies and marks the system clipboard with a token, so copying
anything else since makes Paste do nothing. Objects SimpleCAD does not edit,
such as parametric features, go through FreeCAD's own Copy and Paste.
"""
import uuid

import FreeCAD as App
import FreeCADGui as Gui

from ..document import clipboard
from .qt import QtCore, QtWidgets

FORMAT = 'application/x-simplecad-objects'
FREECAD = 'application/x-documentobject'
KEYS = {int(QtCore.Qt.Key_C): 'Copy', int(QtCore.Qt.Key_X): 'Cut', int(QtCore.Qt.Key_V): 'Paste'}
SCOPE = ('Gui::View3DInventorViewer', 'Gui::TreeWidget')
TEXT = (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox)
_items, _token = [], b''


def command(event):
    """'Copy', 'Cut' or 'Paste' for ⌘/Ctrl with C, X or V and no other modifier."""
    modifiers = event.modifiers()
    if (not modifiers & QtCore.Qt.ControlModifier
            or modifiers & (QtCore.Qt.ShiftModifier | QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier)):
        return None
    return KEYS.get(int(event.key()))


def in_scope(controller, focus):
    """Keys typed into text fields, or into other views such as a spreadsheet, keep their own meaning."""
    if focus is None or isinstance(focus, TEXT):
        return False
    if controller.faces.contains(focus):
        return True
    widget = focus
    while widget is not None:
        if widget.metaObject().className() in SCOPE:
            return True
        widget = widget.parentWidget()
    return False


def plural(count):
    return '%d object%s' % (count, '' if count == 1 else 's')


def run(controller, name):
    if controller.tool:
        controller.cancel(quiet=True)
    try:
        if name == 'Paste':
            paste(controller)
        else:
            copy(controller, cut=name == 'Cut')
    except (ValueError, RuntimeError) as error:
        controller.report(error)


def copy(controller, cut=False):
    global _items, _token
    objects = controller.selected()
    if not objects:
        controller.message('Select objects to %s' % ('cut' if cut else 'copy'))
        return
    if not all(clipboard.copyable(obj) for obj in objects):
        if cut:
            controller.message('Cut works on plain shapes and meshes · Copy parametric features with ⌘C instead')
            return
        Gui.runCommand('Std_Copy', 0)
        controller.message('Copied %s · ⌘V pastes them' % plural(len(objects)))
        return
    items = clipboard.cut(objects) if cut else clipboard.snapshot(objects)
    _items, _token = items, uuid.uuid4().hex.encode()
    data = QtCore.QMimeData()
    data.setData(FORMAT, QtCore.QByteArray(_token))
    QtWidgets.QApplication.clipboard().setMimeData(data)
    if cut:
        Gui.Selection.clearSelection()
        controller.message('Cut %s · ⌘V pastes them · Undo with ⌘Z' % plural(len(items)))
    else:
        controller.message('Copied %s · ⌘V pastes them' % plural(len(items)))


def paste(controller):
    data = QtWidgets.QApplication.clipboard().mimeData()
    formats = data.formats() if data is not None else []
    ours = bool(_items) and FORMAT in formats and bytes(data.data(FORMAT)) == _token
    if not ours and not any(f.startswith(FREECAD) for f in formats):
        controller.message('Nothing to paste · Select objects and press ⌘C first')
        return
    doc = App.ActiveDocument or App.newDocument('SimpleCAD')
    if ours:
        results = clipboard.paste(doc, _items)
    else:
        before = {obj.Name for obj in doc.Objects}
        Gui.runCommand('Std_Paste', 0)
        results = [obj for obj in doc.Objects if obj.Name not in before]
        if not results:
            controller.message('Nothing was pasted')
            return
    Gui.Selection.clearSelection()
    for obj in results:
        Gui.Selection.addSelection(obj)
    if all(obj.TypeId == 'Part::Feature' for obj in results):
        controller.start('Move')
    if controller.tool == 'Move':
        controller.message('Pasted %s in place · Click a base point, then where to put them · Esc leaves them here'
                           % plural(len(results)))
    else:
        controller.focus_view()
        controller.message('Pasted %s in place · Undo with ⌘Z' % plural(len(results)))
