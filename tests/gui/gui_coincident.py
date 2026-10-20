"""Native edge picking and Qt Delete/Backspace on separately stored triangles."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.core import coincident as coinc
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    controller = instance()
    controller.cancel(quiet=True)
    doc = App.newDocument("SimpleCADCoincidentSmoke")
    doc.UndoMode = 1
    a, b = V(0, 0, 10), V(40, 0, 10)

    def raw(points, label):
        obj = doc.addObject("Part::Feature", "SimpleShape")
        obj.Label = label
        obj.Shape = Part.Face(Part.makePolygon(points + [points[0]]))
        obj.ViewObject.ShapeColor = (0.76, 0.84, 0.88)
        obj.ViewObject.LineWidth = 2.0
        return obj

    first = raw([a, b, V(20, 25, 10)], "Top triangle")
    second = raw([b, a, V(20, -15, -10)], "Lower triangle")
    hidden = raw([a, b, V(20, 25, 10)], "Hidden duplicate")
    hidden.ViewObject.Visibility = False
    names = first.Name, second.Name, hidden.Name
    doc.recompute()
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()

    def select_edge():
        Gui.Selection.clearSelection()
        Gui.updateGui()
        pos = tuple(int(round(value)) for value in screen(view, (a + b) / 2))
        hit = pick(view, doc, pos)
        assert hit and hit[0].Name in names[:2] and hit[3].startswith("Edge"), hit
        Gui.Selection.addSelection(hit[0], hit[3])

    def keypress(key):
        controller.focus_view()
        focus = QtWidgets.QApplication.focusWidget()
        for event_type in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            event = QtGui.QKeyEvent(event_type, key, QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(focus, event)
            if event_type == QtCore.QEvent.ShortcutOverride:
                assert event.isAccepted()

    for method in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace, "Toolbar"):
        select_edge()
        if method == "Toolbar":
            Gui.runCommand("SimpleCAD_Delete")
        else:
            keypress(method)
        assert [obj.Name for obj in doc.Objects] == [names[2]], [obj.Name for obj in doc.Objects]
        assert not doc.Objects[0].ViewObject.Visibility
        doc.undo()
        assert len(doc.Objects) == 3
    App.Console.PrintMessage("PASS: one native edge pick + Delete, Backspace or toolbar removes both triangles; hidden copy survives; Undo\n")

    # The menu action must work on old independently built geometry as well.
    Gui.Selection.clearSelection()
    Gui.runCommand("SimpleCAD_Cleanup")
    visible = op.visible_shapes(doc)
    assert len(visible) == 1
    obj = visible[0]
    assert (len(obj.Shape.Faces), len(obj.Shape.Edges)) == (2, 5)
    assert len(doc.Objects) == 2  # Hidden object is excluded from automatic cleanup.
    assert obj.Shape.isValid()
    if screenshot:
        Gui.updateGui()
        view.saveImage(str(screenshot), 1000, 700, "Current")
    edge = Part.makeLine(a, b)
    selected = next("Edge" + str(i + 1) for i, e in enumerate(obj.Shape.Edges) if coinc.same(e, edge))
    Gui.Selection.addSelection(obj, selected)
    keypress(QtCore.Qt.Key_Backspace)
    assert [obj.Name for obj in doc.Objects] == [names[2]]
    doc.undo()
    doc.undo()
    assert len(doc.Objects) == 3
    App.Console.PrintMessage("PASS: menu cleanup sews the triangles to one shared edge; one Backspace removes both; both Undo steps restore geometry\n")
    Gui.Selection.clearSelection()
    return doc
