"""Print-joint panel, cached preview, atomic Apply and the separate fit-test document."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADJointSmoke"); doc.UndoMode = 1
    box = Part.makeBox(50, 36, 28)
    obj = op.new_shape(doc, box.makeFillet(2, box.Edges).Solids[0], "Print joint")
    obj.Placement = App.Placement(V(10, 20, 5), App.Rotation(V(0, 0, 1), 20))
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def start():
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj)
        Gui.runCommand("SimpleCAD_Slice"); flush()
        session = c.slice_session
        assert session is not None and session.planned
        session.joint.enabled.setChecked(True)
        assert update(session), session.status.text()
        return session

    def update(session):
        result = session.update_preview(); flush()
        return result

    def save(name):
        if screenshots: view.saveImage(str(ROOT.parent.parent / "work" / name), 1100, 800, "Current")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "JointBefore.FCStd"; name = obj.Name
        doc.saveAs(str(path)); App.closeDocument(doc.Name)
        doc = App.openDocument(str(path)); doc.UndoMode = 1; obj = doc.getObject(name)
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        original = obj.Shape; count = doc.UndoCount; children = obj.ViewObject.RootNode.getNumChildren()
        assert not Gui.activeDocument().Modified
        session = start()
        assert session.joint.body.isVisible() and session.separation.isChecked()
        cut = session.cut_pieces; joint = session.joint_pieces
        for amount in (12, 16, 20):
            session.gap.setText("%s mm" % amount); assert update(session)
            assert session.cut_pieces is cut and session.joint_pieces is joint
        for count_studs in (1, 2, 4):
            session.joint.pattern.setCurrentIndex(session.joint.pattern.findData(count_studs))
            assert update(session), session.status.text()
            male = session.joint_pieces[0][1][0][1]
            assert len([f for f in male.Faces if isinstance(f.Surface, Part.Cylinder)]) >= count_studs
        session.joint.more.setChecked(True); flush()
        session.joint.fields["spacing"].setText("12 mm"); assert update(session)
        session.joint.fields["diameter"].setText("0.8 cm"); assert update(session)
        session.joint.fields["across"].setText("1 mm"); assert update(session)
        session.joint.fields["up"].setText("1 mm"); assert update(session)
        for clearance in ("-0.05 mm", "0 mm", "0.10 mm"):
            session.joint.fields["clearance"].setText(clearance); assert update(session)
        session.joint.flip.setChecked(True); assert update(session)
        assert session.joint_pieces[0][1][1][1].Volume > cut[0][1][1][1].Volume
        session.joint.flip.setChecked(False); assert update(session)
        assert obj.Shape.isSame(original) and doc.UndoCount == count and len(doc.Objects) == 1
        assert obj.ViewObject.Visibility and not Gui.activeDocument().Modified
        # More space makes the male pins and female openings readable together.
        save("joint-preview.png")
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "joint-panel.png"))
        for field, bad in (("length", "100 mm"), ("clearance", "nan"), ("across", "50 mm"), ("spacing", "2 mm")):
            widget = session.joint.fields[field]; previous = widget.text(); widget.setText(bad)
            assert not update(session) and not session.apply_button.isEnabled()
            assert not session.preview.masks and session.planned is None
            assert obj.ViewObject.RootNode.getNumChildren() == children and obj.Shape.isSame(original)
            widget.setText(previous); assert update(session), session.status.text()
        # Switching the optional joint off is an ordinary slice again.
        session.joint.enabled.setChecked(False); assert update(session)
        assert abs(sum(s.Volume for s in session.planned[0][1]) - original.Volume) < 1e-6
        session.joint.enabled.setChecked(True); assert update(session)
        App.Console.PrintMessage("PASS: joint patterns, units, fit/spacing/offsets/flip, cached gap previews, no document writes and invalid-joint recovery\n")
        QtWidgets.QApplication.sendEvent(session.joint.fields["diameter"], QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
        flush(); assert c.slice_session is None and obj.Shape.isSame(original)
        assert obj.ViewObject.RootNode.getNumChildren() == children
        session = start(); expected = [p.Volume for p in session.planned[0][1]]
        field = session.joint.fields["length"]
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(field, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))
        flush(); assert c.slice_session is None and len(doc.Objects) == 2 and doc.UndoCount == count + 1
        for result, volume in zip(doc.Objects, expected):
            assert result.Shape.isValid() and result.Shape.isClosed() and abs(result.Shape.Volume - volume) < 1e-5
            assert result.TypeId == "Part::Feature"
        Gui.Selection.clearSelection(); view.fitAll(); flush(); save("joint-applied.png")
        doc.undo(); flush(); assert len(doc.Objects) == 1 and abs(obj.Shape.Volume - original.Volume) < 1e-6
        doc.redo(); flush(); assert len(doc.Objects) == 2
        doc.undo(); flush()
        App.Console.PrintMessage("PASS: Esc restores native state; Enter commits the joint and cut together; one Undo/Redo\n")
        # Making a coupon cancels only the preview and opens a distinct document.
        old_count = doc.UndoCount; old_shape = obj.Shape
        session = start(); session.joint.test_button.click(); flush()
        fit = App.ActiveDocument
        assert fit != doc and fit.Name.startswith("SimpleCADFitTest")
        assert session.closed and c.slice_session is None and len(fit.Objects) == 6
        assert obj.Shape.isSame(old_shape) and doc.UndoCount == old_count
        assert obj.ViewObject.RootNode.getNumChildren() == children
        assert all(o.Shape.isValid() and o.Shape.isClosed() and abs(o.Shape.BoundBox.ZMin) < 1e-6 for o in fit.Objects)
        if screenshots: Gui.activeDocument().activeView().saveImage(str(ROOT.parent.parent / "work" / "joint-fit-test.png"), 1100, 800, "Current")
        App.closeDocument(fit.Name); App.setActiveDocument(doc.Name); flush()
        # Existing Slice remains usable on surfaces; joints explain why disabled.
        surface_doc = App.newDocument("JointSurfaceGuard")
        surface = op.new_shape(surface_doc, Part.makeShell(Part.makeBox(50, 30, 20).Faces[:-1]), "Surface")
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(surface); c.start("Slice")
        session = c.slice_session; assert session is not None and session.planned
        session.joint.enabled.setChecked(True); assert not update(session)
        assert "closed solid" in session.status.text()
        session.joint.enabled.setChecked(False); assert update(session)
        c.cancel(quiet=True); App.closeDocument(surface_doc.Name); App.setActiveDocument(doc.Name)
        session = start(); c.start("Select"); assert session.closed
        session = start(); Gui.activateWorkbench("PartWorkbench"); assert session.closed
        Gui.activateWorkbench("SimpleCADWorkbench")
        App.Console.PrintMessage("PASS: separate fit-test document and preserved model; surface guard/no-joint recovery; tool/workbench cleanup\n")
    c.cancel(quiet=True)
    return doc
