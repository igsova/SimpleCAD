"""Native cylinder seam selection and safe keyboard/toolbar deletion."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g, preferences as prefs
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    from dataclasses import replace
    previous = prefs.load()
    prefs.save(replace(previous, show_seams=True))
    Gui.activateWorkbench("SimpleCADWorkbench")
    instance().seams.configure(True)
    try:
        return run_visible(screenshot)
    finally:
        prefs.save(previous)
        instance().seams.configure(previous.show_seams)


def run_visible(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSeamSmoke")
    doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeCylinder(8, 25), "Cylinder")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()
    seam = next("Edge" + str(i + 1) for i, edge in enumerate(obj.Shape.Edges)
                if g.is_seam_edge(obj.Shape, edge))
    edge = obj.Shape.getElement(seam)
    midpoint = edge.valueAt(edge.getParameterByLength(edge.Length / 2))
    pos = tuple(int(round(value)) for value in screen(view, midpoint))
    hits = view.getObjectsInfo(pos) or []
    assert any(hit.get("Object") == obj.Name and hit.get("Component") == seam for hit in hits), hits
    count = doc.UndoCount
    volume = obj.Shape.Volume

    def select():
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, seam)

    def keypress(key):
        c.focus_view()
        focus = QtWidgets.QApplication.focusWidget()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier))

    for key in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
        select()
        keypress(key)
        assert obj.Shape.isValid() and len(obj.Shape.Solids) == 1
        assert len(obj.Shape.Faces) == 3 and abs(obj.Shape.Volume - volume) < 1e-6
        assert doc.UndoCount == count
        assert "surface seam" in Gui.getMainWindow().statusBar().currentMessage()
        assert not Gui.Selection.getSelection()
    select()
    Gui.runCommand("SimpleCAD_Delete", 0)
    assert doc.UndoCount == count and len(obj.Shape.Solids) == 1
    App.Console.PrintMessage("PASS: native seam picking, Delete/Backspace/toolbar protection, explanatory status, no geometry or Undo changes\n")

    line = op.new_shape(doc, Part.makeLine(V(30, 0, 0), V(40, 0, 0)), "Drawn line")
    name = line.Name
    count = doc.UndoCount
    select()
    Gui.Selection.addSelection(line, "Edge1")
    keypress(QtCore.Qt.Key_Delete)
    assert doc.getObject(name) is None and len(obj.Shape.Solids) == 1
    assert doc.UndoCount == count + 1
    assert "seams kept" in Gui.getMainWindow().statusBar().currentMessage()
    doc.undo()
    assert doc.getObject(name) is not None
    doc.redo()
    assert doc.getObject(name) is None
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    obj_name = obj.Name
    keypress(QtCore.Qt.Key_Backspace)
    assert doc.getObject(obj_name) is None
    doc.undo()
    obj = doc.getObject(obj_name)
    assert len(obj.Shape.Solids) == 1
    App.Console.PrintMessage("PASS: mixed selection deletes only drawn geometry, one Undo/Redo; explicit whole-cylinder deletion remains available\n")
    Gui.Selection.clearSelection()
    view.fitAll()
    Gui.updateGui()
    if screenshot:
        view.saveImage(str(screenshot), 1000, 750, "Current")
    return doc
