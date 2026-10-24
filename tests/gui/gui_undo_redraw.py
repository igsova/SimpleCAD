"""Undo followed at once by a new edit: FreeCAD deletes the undone object's
view provider before SimpleCAD's display layers let go of its nodes. Undo
with a drawing tool still open, then the next event in the view."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import appearance as a, operations as op, visibility
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
from simplecad.gui.snapping import screen

V = App.Vector


def settle(view):
    for unused in range(3):
        QtWidgets.QApplication.processEvents()
    view.redraw()
    Gui.updateGui()


def run():
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADUndoRedraw")
    doc.UndoMode = 1
    try:
        view = Gui.activeDocument().activeView()
        op.new_shape(doc, Part.makeBox(40, 30, 20), "Box")
        view.viewIsometric(); view.fitAll()
        settle(view)
        for case in ("seams", "hidden faces", "mixed opacity", "highlighted faces"):
            # A cylinder has a seam, so the seam mask and the colours follow it.
            made = op.new_shape(doc, Part.makeCylinder(5, 10, V(60, 0, 0)), "Cylinder")
            if case == "hidden faces":
                visibility.set_hidden(made, {1})
            elif case == "mixed opacity":
                a.commit(a.prepare([(made, ["Face1"])]), opacity=50)
            elif case == "highlighted faces":
                Gui.Selection.addSelection(made, "Face1")
                Gui.Selection.setPreselection(made, "Face2")
            settle(view)
            name = made.Name
            key = (doc.Name, name)
            assert key in c.viewport_style.styled, case
            Gui.Selection.clearSelection()
            # Undo the cylinder, then edit before any event runs: the new edit
            # drops the Redo history and FreeCAD deletes the cylinder's nodes.
            while doc.getObject(name) is not None:
                Gui.runCommand("Std_Undo")
            op.new_shape(doc, Part.makeBox(4, 4, 4, V(-20, 10 * len(doc.Objects), 0)), "Block")
            assert not doc.RedoCount
            # Either display layer can refresh first; the style letting go of
            # the cylinder's root first is the order that read freed nodes.
            c.viewport_style.refresh()
            c.seams.refresh()
            settle(view)
            # The block can take the cylinder's name; only its own nodes are styled.
            block = doc.getObject(name)
            entry = c.viewport_style.styled.get(key)
            assert entry is None or block is not None and entry[0] == block.ViewObject.RootNode, case
            assert key not in c.seams.records and key not in c.seams.highlights.records, case
            App.Console.PrintMessage("PASS: Undo then an immediate edit with %s redraws\n" % case)

        def pos(point):
            return tuple(int(round(value)) for value in screen(view, point))

        # ⌘Z right after a click leaves the tool open through the Undo. The
        # next event the view hands to Coin then ends the tool, which once
        # took its preview out of the scene graph Coin was walking.
        for tool, clicks in (("Line", (V(10, 10, 20), V(30, 10, 20))), ("Tape", (V(40, 30, 20), V(40, 30, 0)))):
            names = [obj.Name for obj in doc.Objects]
            c.start(tool)
            for point in clicks:
                c.motion(pos(point))
                c.click(pos(point))
            assert c.tool == tool and len(doc.Objects) > len(names), (tool, doc.Objects)
            Gui.runCommand("Std_Undo")
            assert c.tool == tool and [obj.Name for obj in doc.Objects] == names, (tool, doc.Objects)
            c.focus_view()
            for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(QtWidgets.QApplication.focusWidget(),
                                                 QtGui.QKeyEvent(kind, QtCore.Qt.Key_Shift, QtCore.Qt.NoModifier))
            settle(view)
            assert c.tool is None, (tool, c.tool)
            App.Console.PrintMessage("PASS: Undo with %s still open ends it at the next view event\n" % tool)
    finally:
        App.closeDocument(doc.Name)
        QtWidgets.QApplication.processEvents()
