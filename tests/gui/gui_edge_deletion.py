"""Native picking, GUI selection, and Qt Delete/Backspace smoke test.

Run run() from a fresh FreeCAD GUI. Only a separate unsaved test document is
changed. Keyboard events are sent through Qt, not a physical keyboard.
"""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADEdgeDeletionSmoke")
    shape = g.divide_face_with_line(Part.makeBox(40, 30, 10), g.V(0, 0, 10), g.V(40, 0, 0))
    obj = op.new_shape(doc, shape, "Delete test block")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(g.V(1, 1, 0), g.V(-1, 1, 2), g.V(1, -1, 1), "ZXY").Q)

    def select_at(point, kind):
        view.fitAll()
        Gui.updateGui()
        pos = tuple(int(round(value)) for value in screen(view, point))
        hit = pick(view, doc, pos, face_only=kind == "Face")
        assert hit and hit[0] == obj and hit[3].startswith(kind), hit
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, hit[3])
        selection = Gui.Selection.getSelectionEx()
        assert len(selection) == 1 and tuple(selection[0].SubElementNames) == (hit[3],)

    def keypress(key):
        c.focus_view()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        event = QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride, key, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(focus, event)
        assert event.isAccepted()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(focus, event)
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, key, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(focus, event)

    for method in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace, "Toolbar"):
        select_at(g.V(20, 0, 5), "Edge")
        if method == "Toolbar":
            Gui.runCommand("SimpleCAD_Delete")
        else:
            keypress(method)
        assert len(doc.Objects) == 1
        assert len(obj.Shape.Faces) == 6
        assert obj.Shape.isValid() and abs(obj.Shape.Volume - 12000) < 1e-5
        assert not Gui.Selection.getSelection()
        doc.undo()
        assert len(obj.Shape.Faces) == 7
    App.Console.PrintMessage("PASS: native edge selection; Delete, Backspace and toolbar merge only the selected divider; Undo\n")

    select_at(g.V(20, 0, 5), "Edge")
    Gui.runCommand("SimpleCAD_Delete")
    select_at(g.V(20, 0, 10), "Edge")
    keypress(QtCore.Qt.Key_Backspace)
    assert len(doc.Objects) == 1
    assert len(obj.Shape.Faces) == 4
    assert len(obj.Shape.Solids) == 0 and obj.Shape.isValid()
    Gui.updateGui()
    if screenshot:
        view.saveImage(str(screenshot), 1000, 700, "Current")
    doc.undo()
    assert len(obj.Shape.Faces) == 6 and len(obj.Shape.Solids) == 1
    App.Console.PrintMessage("PASS: angled edge opens the shape by removing its two faces; Undo restores the solid\n")

    select_at(g.V(20, 15, 10), "Face")
    keypress(QtCore.Qt.Key_Delete)
    assert len(obj.Shape.Faces) == 5 and len(doc.Objects) == 1
    doc.undo()
    name = obj.Name
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    Gui.runCommand("SimpleCAD_Delete")
    assert len(doc.Objects) == 0
    doc.undo()
    assert len(doc.Objects) == 1 and len(doc.getObject(name).Shape.Faces) == 6
    App.Console.PrintMessage("PASS: face selection removes one face; whole-object selection deletes the object; Undo\n")
    Gui.Selection.clearSelection()
    return doc
