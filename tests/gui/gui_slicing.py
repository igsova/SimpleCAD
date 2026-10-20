"""Native slicing panel, read-only preview, separate objects and session cleanup."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSliceSmoke"); doc.UndoMode = 1
    box = Part.makeBox(60, 30, 20)
    obj = op.new_shape(doc, box.makeFillet(2, box.Edges).Solids[0], "Slice test")
    obj.Placement = App.Placement(V(10, 20, 5), App.Rotation(V(0, 0, 1), 20))
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def start(name="", shortcut=False):
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj, name)
        if shortcut:
            Gui.getMainWindow().activateWindow()
            c.focus_view(); flush()
            widget = QtWidgets.QApplication.focusWidget()
            assert widget is not None, "The test window must have keyboard focus before injecting a key"
            for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(kind, QtCore.Qt.Key_U, QtCore.Qt.NoModifier, "u"))
        else:
            Gui.runCommand("SimpleCAD_Slice")
        flush()
        assert c.slice_session is not None and c.tool == "Slice"
        return c.slice_session

    def update(session):
        result = session.update_preview(); flush()
        return result

    def save(name):
        if screenshots: view.saveImage(str(ROOT.parent.parent / "work" / name), 1000, 750, "Current")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "SliceBefore.FCStd"; name = obj.Name
        doc.saveAs(str(path)); App.closeDocument(doc.Name)
        doc = App.openDocument(str(path)); doc.UndoMode = 1; obj = doc.getObject(name)
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        original = obj.Shape; count = doc.UndoCount
        children = obj.ViewObject.RootNode.getNumChildren()
        assert not Gui.activeDocument().Modified
        session = start("Face1", shortcut=True)
        assert session.planned is not None, session.status.text()
        assert len(session.planned[0][1]) == 2
        assert not session.separation.isChecked() and not session.gap.isEnabled()
        # Main axis follows the rotated long side. World choices recenter the cut.
        assert abs(session.plane.normal.dot(obj.Placement.Rotation.multVec(V(1, 0, 0)))) > .99999
        for axis in ("X", "Y", "Z", "Main"):
            session.axis.setCurrentIndex(session.axis.findData(axis))
            assert update(session), session.status.text()
            assert all(p.isValid() and p.ShapeType == "Solid" for p in session.planned[0][1])
        session.position_slider.setValue(650)
        assert update(session), session.status.text()
        assert float(session.offset.text().split()[0]) > 0
        session.separation.setChecked(True); session.gap.setText("1 cm")
        assert update(session), session.status.text()
        pieces = session.cut_pieces
        assert abs(session.planned[0][1][0].distToShape(session.planned[0][1][1])[0] - 10) < 1e-5
        session.gap_slider.setValue(180); assert update(session)
        assert session.cut_pieces is pieces, "Gap must not repeat the Boolean cut"
        assert obj.Shape.isSame(original) and obj.ViewObject.Visibility
        assert len(doc.Objects) == 1 and doc.UndoCount == count and not Gui.activeDocument().Modified
        save("slice-preview.png")
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "slice-panel.png"))
        for field, bad in ((session.offset, "2000 mm"), (session.offset, "banana"),
                           (session.gap, "-5 mm"), (session.gap, "nan")):
            old = field.text(); field.setText(bad)
            assert not update(session) and not session.apply_button.isEnabled()
            assert session.planned is None and not session.preview.masks
            assert obj.Shape.isSame(original) and obj.ViewObject.RootNode.getNumChildren() == children
            field.setText(old); assert update(session), session.status.text()
        App.Console.PrintMessage("PASS: U shortcut, plane choices, cut-position/gap sliders, units, cached cut, unchanged document and invalid-input recovery\n")
        # Esc restores original picking, source selection and the saved state.
        QtWidgets.QApplication.sendEvent(session.offset, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
        flush(); assert session.closed and c.slice_session is None
        assert any("Face1" in item.SubElementNames for item in Gui.Selection.getSelectionEx())
        assert not Gui.activeDocument().Modified and obj.Shape.isSame(original)
        Gui.Selection.clearSelection()
        hit = view.getObjectsInfo(tuple(round(v) for v in screen(view, original.Faces[0].CenterOfMass))) or []
        assert any(item.get("Object") == obj.Name for item in hit), hit
        # Enter applies the current units once, leaving independent native solids.
        session = start(); session.separation.setChecked(True); session.gap.setText("12 mm")
        assert update(session); expected = [p.CenterOfMass for p in session.planned[0][1]]
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(session.gap, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))
        flush(); assert c.slice_session is None and len(doc.Objects) == 2
        assert doc.UndoCount == count + 1
        for result, center in zip(doc.Objects, expected):
            assert result.TypeId == "Part::Feature" and result.Shape.isValid() and result.Shape.isClosed()
            assert (result.Shape.CenterOfMass - center).Length < 1e-6
            assert tuple(result.ViewObject.ShapeColor) == tuple(obj.ViewObject.ShapeColor)
        assert abs(sum(o.Shape.Volume for o in doc.Objects) - original.Volume) < 1e-5
        Gui.Selection.clearSelection(); view.fitAll(); flush(); save("slice-applied.png")
        doc.undo(); flush(); assert len(doc.Objects) == 1 and abs(obj.Shape.Volume - original.Volume) < 1e-5
        doc.redo(); flush(); assert len(doc.Objects) == 2
        doc.undo(); flush()
        # Zero gap is a real unweld: separate objects touching at the same cut.
        session = start(); assert update(session)
        session.apply_button.click(); flush(); assert len(doc.Objects) == 2
        assert doc.Objects[0].Shape.distToShape(doc.Objects[1].Shape)[0] < 1e-6
        doc.undo(); flush()
        App.Console.PrintMessage("PASS: cancel restores picking/selection; Enter applies separate closed solids; one Undo/Redo; zero-gap unweld\n")
        session = start(); session.dialog.close(); flush(); assert session.closed
        session = start(); c.start("Select"); assert session.closed
        session = start(); Gui.activateWorkbench("PartWorkbench"); assert session.closed
        Gui.activateWorkbench("SimpleCADWorkbench")
        session = start(); other = App.newDocument("SliceOther"); c.check_context(); assert session.closed
        App.closeDocument(other.Name); App.setActiveDocument(doc.Name)
        op.transform([obj], V(1, 0, 0))
        session = start(); doc.undo(); c.check_context(); assert session.closed
        doc.redo(); flush()
        session = start(); op.transform([obj], V(3, 0, 0)); c.check_context(); assert session.closed
        # The open-surface workflow is also exercised through the native panel.
        surface_doc = App.newDocument("SliceOpenSurface")
        surface = op.new_shape(surface_doc, Part.makeShell(Part.makeBox(50, 20, 15).Faces[:-1]), "Open surfaces")
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(surface)
        c.start("Slice"); session = c.slice_session
        assert session is not None and session.planned, session.status.text() if session else "not started"
        session.separation.setChecked(True); assert update(session)
        assert all(not p.Solids for p in session.planned[0][1])
        session.apply_button.click(); flush(); assert len(surface_doc.Objects) == 2
        assert abs(sum(o.Shape.Area for o in surface_doc.Objects) - 3100) < 1e-5
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(surface)
        c.start("Slice"); closing = c.slice_session
        App.closeDocument(surface_doc.Name); c.check_context()
        assert closing.closed and c.slice_session is None
        App.setActiveDocument(doc.Name)
        App.Console.PrintMessage("PASS: panel/tool/workbench/document close, Undo/source-change cleanup and native open-surface slicing\n")
    c.cancel(quiet=True)
    return doc
