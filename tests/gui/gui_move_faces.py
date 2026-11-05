"""Move: the X, Y, Z panel, and selected faces of a solid moving on their own."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADMoveFaces"); doc.UndoMode = 1
    plate = Part.makeBox(40, 30, 4).fuse(Part.makeCylinder(3, 8, V(10, 10, 4))).cut(
        Part.makeCylinder(1, 6, V(10, 10, 6))).removeSplitter()
    tray = op.new_shape(doc, plate.Solids[0], "Tray")
    block = op.new_shape(doc, Part.makeBox(5, 5, 5, V(60, 0, 0)), "Block")
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()

    def flush():
        for _ in range(3):
            QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def type_into(field, text):
        """Type into a panel field as after clicking it: its window is active and it has focus."""
        field.window().activateWindow(); field.setFocus(); flush()
        field.selectAll(); field.clear()
        for char in text:
            for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(field, QtGui.QKeyEvent(kind, 0, QtCore.Qt.NoModifier, char))
        flush()

    def enter(widget):
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier, "\r"))
        flush()

    def boss_faces():
        return ['Face%d' % (i + 1) for i, f in enumerate(tray.Shape.Faces)
                if f.BoundBox.ZMax > 4 + 1e-6 and f.BoundBox.XLength <= 6 + 1e-6]

    try:
        # Whole objects: the panel moves by typed X, Y, Z, as one Undo step.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(block)
        c.start("Move"); flush()
        panel = c.move_panel
        assert panel is not None and c.move_faces is None
        assert panel.title.text() == "Block"
        assert not panel.apply_button.isEnabled()
        type_into(panel.fields[0], "10"); type_into(panel.fields[2], "2 mm")
        assert panel.typed and panel.apply_button.isEnabled()
        assert (c.point - c.anchor - V(10, 0, 2)).Length < 1e-9
        undo = doc.UndoCount
        enter(panel.fields[2])
        assert c.tool is None and c.move_panel is None
        assert (block.Placement.Base - V(10, 0, 2)).Length < 1e-9, block.Placement
        assert doc.UndoCount == undo + 1
        App.Console.PrintMessage("PASS: typed X, Y, Z move whole objects in one Undo step\n")

        # Keys sent to a field stay in it while the main window is the active
        # one, after the first value has set the base point.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(block)
        c.start("Move"); flush()
        panel = c.move_panel
        Gui.getMainWindow().activateWindow(); c.focus_view(); flush()
        for char in "10":
            for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(panel.fields[0], QtGui.QKeyEvent(kind, 0, QtCore.Qt.NoModifier, char))
            flush()
        assert panel.fields[0].text() == "10" and not c.size_input.boxes, (panel.fields[0].text(), c.size_input.boxes)
        assert (c.point - c.anchor - V(10, 0, 0)).Length < 1e-9
        c.cancel(quiet=True)

        # Faces of one solid: only they move; the rest of the tray stays.
        names = boss_faces()
        assert len(names) == 4, names
        # Rim edges picked along with the faces move with them.
        rim = next('Edge%d' % (i + 1) for i, e in enumerate(tray.Shape.Edges)
                   if any(e.isSame(f) for f in tray.Shape.getElement(names[0]).Edges))
        far = next('Edge%d' % (i + 1) for i, e in enumerate(tray.Shape.Edges) if e.BoundBox.XMin > 30)
        Gui.Selection.clearSelection()
        for name in names:
            Gui.Selection.addSelection(tray, name)
        Gui.Selection.addSelection(tray, far)
        c.start("Move"); flush()
        assert c.move_faces is None, "an edge off the faces keeps Move on the whole object"
        c.cancel(quiet=True)
        Gui.Selection.clearSelection()
        for name in names + [rim]:
            Gui.Selection.addSelection(tray, name)
        c.start("Move"); flush()
        panel = c.move_panel
        assert c.move_faces == (tray, names), c.move_faces
        assert panel.title.text() == "4 faces of Tray", panel.title.text()
        outline = c.moving_outline()
        assert outline and all(abs(p.x - 10) <= 3 + 1e-3 for line in outline for p in line)
        volume, undo = tray.Shape.Volume, doc.UndoCount
        type_into(panel.fields[0], "15")
        panel.apply_button.click(); flush()
        assert c.tool is None
        assert abs(tray.Shape.Volume - volume) < 1e-3
        assert tray.Placement.isIdentity()
        bosses = [f for f in tray.Shape.Faces if isinstance(f.Surface, Part.Cylinder)]
        assert sorted(round(f.Surface.Center.x, 6) for f in bosses) == [25.0, 25.0], bosses
        assert doc.UndoCount == undo + 1
        doc.undo(); flush()
        assert sorted(round(f.Surface.Center.x, 6) for f in tray.Shape.Faces
                      if isinstance(f.Surface, Part.Cylinder)) == [10.0, 10.0]
        App.Console.PrintMessage("PASS: selected faces move on their own, one Undo step\n")

        # A refused face move keeps the tool and the panel open, the model unchanged.
        Gui.Selection.clearSelection()
        for name in boss_faces():
            Gui.Selection.addSelection(tray, name)
        c.start("Move"); flush()
        panel = c.move_panel
        before = (tray.Shape.Volume, len(tray.Shape.Faces), tray.Shape.BoundBox.ZMax, doc.UndoCount)
        type_into(panel.fields[2], "30")
        panel.apply_button.click(); flush()
        assert c.tool == "Move" and c.move_panel is panel
        assert "no longer touch" in panel.status.text(), panel.status.text()
        assert (tray.Shape.Volume, len(tray.Shape.Faces), tray.Shape.BoundBox.ZMax, doc.UndoCount) == before
        c.cancel(quiet=True)
        assert c.move_panel is None and panel.dialog is None

        # Faces of two objects are refused; Copy keeps copying whole objects.
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(tray, "Face1"); Gui.Selection.addSelection(block, "Face1")
        c.start("Move"); flush()
        assert c.tool is None
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(tray, "Face1")
        c.start("Copy"); flush()
        assert c.move_faces is None and c.objects == [tray] and c.move_panel is not None
        c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: refused moves keep the model; mixed and Copy selections\n")
    finally:
        c.cancel(quiet=True)
    return doc
