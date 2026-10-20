"""⌘C/⌘X/⌘V (Ctrl on Windows and Linux) copy, cut and paste whole objects."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui import clipboard
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector
Qt = QtCore.Qt


def run():
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADClipboard")
    doc.UndoMode = 1
    block = op.new_shape(doc, Part.makeBox(20, 10, 10), "Block")
    view = Gui.activeDocument().activeView()
    view.viewIsometric()
    view.fitAll()
    Gui.updateGui()
    c.controls.snap.setChecked(False)
    status = Gui.getMainWindow().statusBar()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def press(key, modifiers=Qt.ControlModifier, widget=None):
        if widget is None:
            c.focus_view()
        else:
            widget.setFocus()
        QtWidgets.QApplication.processEvents()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, modifiers, ""))
        Gui.updateGui()

    def select(*objects):
        Gui.Selection.clearSelection()
        for obj in objects:
            # A click in the view selects a face; the whole object is copied.
            Gui.Selection.addSelection(doc.Name, obj.Name, "Face1")

    def names():
        return [obj.Name for obj in doc.Objects]

    # Copy changes nothing in the model; Paste adds a copy in place, selects
    # it and starts Move, so the next two clicks place it.
    select(block)
    count = doc.UndoCount
    press(Qt.Key_C)
    assert clipboard.FORMAT in QtWidgets.QApplication.clipboard().mimeData().formats()
    assert doc.UndoCount == count and names() == [block.Name]
    assert "Copied 1 object" in status.currentMessage(), status.currentMessage()
    press(Qt.Key_V)
    assert doc.UndoCount == count + 1 and len(doc.Objects) == 2, names()
    pasted = doc.Objects[-1]
    assert pasted.TypeId == "Part::Feature" and pasted.Name != block.Name
    assert abs(pasted.Shape.Volume - 2000) < 1e-6 and pasted.Shape.BoundBox.isInside(V(10, 5, 5))
    assert [item.Object for item in Gui.Selection.getSelectionEx()] == [pasted]
    assert c.tool == "Move" and c.objects == [pasted], (c.tool, c.objects)
    assert "Pasted 1 object" in status.currentMessage(), status.currentMessage()
    c.click(pos(V(10, 5, 10)))
    c.motion(pos(V(10, 35, 10)))
    c.click(pos(V(10, 35, 10)))
    assert c.tool is None and doc.UndoCount == count + 2
    assert abs(pasted.Shape.BoundBox.YMin - block.Shape.BoundBox.YMin) > 1, pasted.Shape.BoundBox
    assert block.Shape.BoundBox.YMin == 0
    App.Console.PrintMessage("PASS: ⌘C then ⌘V pastes a copy in place and lets two clicks place it\n")

    # Esc after a paste leaves the copy where it was pasted.
    press(Qt.Key_V)
    third = doc.Objects[-1]
    assert c.tool == "Move" and len(doc.Objects) == 3 and doc.UndoCount == count + 3
    press(Qt.Key_Escape, Qt.NoModifier)
    assert c.tool is None and third.Name in names() and abs(third.Shape.BoundBox.XMin) < 1e-9
    doc.undo()
    assert len(doc.Objects) == 2

    # Cut removes the selection in one Undo step; Paste puts it back.
    select(block)
    count, name = doc.UndoCount, block.Name
    press(Qt.Key_X)
    assert name not in names()
    assert doc.UndoCount == count + 1 and doc.UndoNames[0] == "SimpleCAD: Cut", doc.UndoNames[:2]
    assert not Gui.Selection.getSelectionEx()
    press(Qt.Key_V)
    restored = doc.Objects[-1]
    assert restored.Label.startswith("Block") and abs(restored.Shape.BoundBox.XLength - 20) < 1e-9
    assert c.tool == "Move"
    press(Qt.Key_Escape, Qt.NoModifier)
    App.Console.PrintMessage("PASS: ⌘X cuts in one Undo step and ⌘V pastes it back\n")

    # The Model tab, SimpleCAD's object and face browser, takes the same keys.
    tree = c.faces.tree
    assert tree is not None and tree.isVisible()
    select(restored)
    before, name = len(doc.Objects), restored.Name
    press(Qt.Key_X, widget=tree)
    assert len(doc.Objects) == before - 1 and name not in names()
    doc.undo()
    assert len(doc.Objects) == before
    restored = doc.getObject(name)
    App.Console.PrintMessage("PASS: the keys work with the Model tab focused\n")

    # Text fields keep their own copy and paste.
    QtWidgets.QApplication.clipboard().setText("unrelated")
    select(restored)
    c.controls.value.setText("12")
    c.controls.value.selectAll()
    press(Qt.Key_C, widget=c.controls.value)
    assert QtWidgets.QApplication.clipboard().text() == "12"
    assert clipboard.FORMAT not in QtWidgets.QApplication.clipboard().mimeData().formats()
    c.controls.value.clear()
    # Something else on the clipboard is not pasted into the model.
    count, before = doc.UndoCount, names()
    press(Qt.Key_V)
    assert names() == before and doc.UndoCount == count and c.tool is None
    assert "Nothing to paste" in status.currentMessage(), status.currentMessage()
    App.Console.PrintMessage("PASS: text fields keep their own ⌘C; other clipboard content is not pasted\n")

    # Parametric features go through FreeCAD's own Copy and Paste, and are
    # not cut.
    feature = doc.addObject("Part::Box", "Parametric")
    feature.Placement = App.Placement(V(0, 40, 0), App.Rotation())
    doc.recompute()
    select(feature)
    press(Qt.Key_X)
    assert feature.Name in names() and "Cut works on plain shapes" in status.currentMessage()
    press(Qt.Key_C)
    assert any(f.startswith(clipboard.FREECAD) for f in QtWidgets.QApplication.clipboard().mimeData().formats())
    before = names()
    press(Qt.Key_V)
    added = [obj for obj in doc.Objects if obj.Name not in before]
    assert len(added) == 1 and added[0].TypeId == "Part::Box", [obj.TypeId for obj in added]
    assert c.tool is None and "Pasted 1 object in place" in status.currentMessage(), status.currentMessage()
    App.Console.PrintMessage("PASS: parametric features use FreeCAD's copy and paste\n")
    c.controls.snap.setChecked(True)
    App.closeDocument(doc.Name)
