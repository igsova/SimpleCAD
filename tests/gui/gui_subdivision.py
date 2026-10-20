"""Native subdivision panel, region picking, Push/Pull, Delete and lifecycle."""
import math
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSubdivideSmoke"); doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeBox(60, 40, 15), "Block")
    obj.Placement = App.Placement(V(10, 20, 5), App.Rotation(V(1, 2, 0), 15))
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def key(widget, value, text=""):
        assert widget is not None, "The test window must have focus before injecting a key"
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(kind, value, QtCore.Qt.NoModifier, text))
        flush()

    def start(name="Face6", shortcut=False, target=None):
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(target or obj, name)
        if shortcut:
            Gui.getMainWindow().activateWindow(); c.focus_view(); flush()
            key(QtWidgets.QApplication.focusWidget(), QtCore.Qt.Key_D, "d")
        else: Gui.runCommand("SimpleCAD_Subdivide")
        flush(); assert c.tool == "Subdivide" and c.subdivide_session is not None
        return c.subdivide_session

    def update(session):
        value = session.update_preview(); flush(); return value

    def pos(point):
        return tuple(round(value) for value in screen(view, point))

    def save(name):
        if screenshots: view.saveImage(str(ROOT.parent.parent / "work" / name), 1100, 800, "Current")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "BeforeSubdivide.FCStd"; name = obj.Name
        doc.saveAs(str(path)); App.closeDocument(doc.Name)
        doc = App.openDocument(str(path)); doc.UndoMode = 1; obj = doc.getObject(name)
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        original, count = obj.Shape, doc.UndoCount
        children = obj.ViewObject.RootNode.getNumChildren()
        session = start(shortcut=True)
        assert session.pattern.currentData() == "spaced"
        # Keep coverage of the previous equal-area layout as an explicit option.
        session.pattern.setCurrentIndex(session.pattern.findData("equal_area"))
        assert update(session) and len(session.regions) == 9
        assert session.rows.value() == session.columns.value() == 3
        assert not session.rows.isEnabled() and session.total.isEnabled()
        for total, dimensions in ((12, (3, 4)), (7, (1, 7)), (1, (1, 1)), (9, (3, 3))):
            session.total.setValue(total); assert update(session), session.status.text()
            assert (session.rows.value(), session.columns.value()) == dimensions
            assert len(session.regions) == total
        save("subdivision-preview.png")
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "subdivision-panel.png"))
        session.total.setValue(12); session.mode.setCurrentIndex(1)
        assert (session.rows.value(), session.columns.value()) == (3, 4)
        assert not session.total.isEnabled() and session.rows.isEnabled()
        session.rows.setValue(2); session.columns.setValue(5); session.angle.setValue(30)
        assert update(session), session.status.text()
        assert len(session.regions) == 10
        assert all(abs(f.Area - original.Faces[5].Area / 10) < 1e-5 for f in session.regions)
        planned = session.planned; assert update(session) and session.planned is planned
        assert obj.Shape.isSame(original) and obj.ViewObject.Visibility
        assert len(doc.Objects) == 1 and doc.UndoCount == count and not Gui.activeDocument().Modified
        session.rows.setValue(100); session.columns.setValue(100)
        assert not update(session) and not session.apply_button.isEnabled()
        assert not session.preview.masks and obj.ViewObject.RootNode.getNumChildren() == children
        session.rows.setValue(2); session.columns.setValue(2); assert update(session)
        key(session.rows, QtCore.Qt.Key_Escape)
        assert session.closed and c.subdivide_session is None
        assert any("Face6" in item.SubElementNames for item in Gui.Selection.getSelectionEx())
        assert not Gui.activeDocument().Modified and doc.UndoCount == count
        session = start(); regions = list(session.regions)
        session.apply_button.click(); flush()
        assert c.subdivide_session is None and len(doc.Objects) == 1
        assert len(obj.Shape.Faces) == 14 and doc.UndoCount == count + 1
        assert abs(obj.Shape.Volume - original.Volume) < 1e-5
        # All nine pieces are native selectable faces, not drawn overlays.
        names = set()
        for region in regions:
            hit = pick(view, doc, pos(region.CenterOfMass), face_only=True)
            assert hit and hit[0] == obj and abs(hit[1].Area - region.Area) < 1e-5, hit
            names.add(hit[3])
        assert len(names) == 9
        save("subdivision-applied.png")
        doc.undo(); flush(); assert len(obj.Shape.Faces) == 6
        doc.redo(); flush(); assert len(obj.Shape.Faces) == 14
        App.Console.PrintMessage("PASS: D/command, count factoring, row/column/angle controls, cached read-only preview, invalid recovery, Esc, Apply and nine native pickable faces with Undo/Redo\n")
        # Existing interactive tools must edit just the picked cell.
        region = regions[4]; point = pos(region.CenterOfMass)
        for distance in (-2, 2):
            c.start("PushPull"); c.click(point)
            assert abs(c.face.Area - region.Area) < 1e-5
            c.controls.value.setText(str(distance)); c.numeric(); flush()
            assert c.tool is None and obj.Shape.isValid()
            assert abs(obj.Shape.Volume - (original.Volume + region.Area * distance)) < 1e-5
            doc.undo(); flush()
        hit = pick(view, doc, point, face_only=True)
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj, hit[3])
        Gui.getMainWindow().activateWindow(); c.focus_view(); flush()
        key(QtWidgets.QApplication.focusWidget(), QtCore.Qt.Key_Backspace)
        assert not obj.Shape.Solids and abs(obj.Shape.Area - (original.Area - region.Area)) < 1e-5
        doc.undo(); flush(); assert len(obj.Shape.Faces) == 14
        # Subdivide an existing cell; a whole-part 1-division operation is a no-op.
        hit = pick(view, doc, point, face_only=True)
        session = start(name=hit[3]); session.total.setValue(4); assert update(session)
        session.apply_button.click(); flush(); assert len(obj.Shape.Faces) == 17
        doc.undo(); flush(); hit = pick(view, doc, point, face_only=True)
        session = start(name=hit[3]); session.total.setValue(1); assert update(session)
        before = doc.UndoCount; session.apply_button.click(); flush(); assert doc.UndoCount == before
        App.Console.PrintMessage("PASS: native region Push/Pull in both directions, Backspace face removal, Undo, subdivision of a cell and single-part no-op\n")
        # A gallery also exercises actual polygon/curved-face GUI Apply paths.
        gallery = App.newDocument("SubdivideShapes")
        gallery_view = Gui.activeDocument().activeView()
        for index, sides in enumerate((4, 3, 5, 6)):
            points = [V(index * 55 + 20 * math.cos(i * 2 * math.pi / sides),
                        20 * math.sin(i * 2 * math.pi / sides), 0) for i in range(sides)]
            face = Part.Face(Part.makePolygon(points + points[:1]))
            item = op.new_shape(gallery, face, "%d-sided face" % sides)
            session = start(name="", target=item); assert update(session), session.status.text()
            session.apply_button.click(); flush()
            expected = 9 if sides in (3, 4) else sides
            assert len(item.Shape.Faces) == expected
            assert all(abs(f.Area - face.Area / expected) < 1e-5 for f in item.Shape.Faces)
        Gui.Selection.clearSelection(); gallery_view.viewTop(); gallery_view.fitAll(); flush()
        if screenshots: gallery_view.saveImage(str(ROOT.parent.parent / "work" / "subdivision-polygons.png"), 1400, 600, "Current")
        circle = op.new_shape(gallery, g.circle(g.Plane.named(), V(0, 60, 0), 15), "Disk")
        session = start(name="", target=circle); session.divisions.setValue(4); assert update(session)
        session.apply_button.click(); flush(); assert len(circle.Shape.Faces) == 4
        # Triangle and polygon defaults follow the outline; grid modes keep spacing.
        points = [V(0, 70, 0), V(60, 70, 0), V(30, 110, 0)]
        triangle = op.new_shape(gallery, Part.Face(Part.makePolygon(points + points[:1])), "Triangle patterns")
        before_shape, before_undo = triangle.Shape, gallery.UndoCount
        session = start(name="", target=triangle)
        assert session.pattern.currentData() == "triangles" and len(session.regions) == 9
        assert not session.divisions.isHidden() and session.mode.isHidden() and session.angle.isHidden()
        session.divisions.setValue(4); assert update(session) and len(session.regions) == 16
        assert all(len(f.Edges) == 3 for f in session.regions)
        session.pattern.setCurrentIndex(session.pattern.findData("fan"))
        assert update(session) and len(session.regions) == 3
        session.divisions.setValue(2); assert update(session) and len(session.regions) == 12
        session.pattern.setCurrentIndex(session.pattern.findData("triangles"))
        assert session.divisions.value() == 4 and update(session) and len(session.regions) == 16
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "subdivision-triangle-panel.png"))
        session.pattern.setCurrentIndex(session.pattern.findData("spaced"))
        session.mode.setCurrentIndex(2); session.rows.setValue(4)
        assert update(session) and len(session.regions) == 4
        assert session.columns.isHidden() and session.total.isHidden() and not session.rows.isHidden()
        assert all(abs(f.BoundBox.YLength - 10) < 1e-5 for f in session.regions)
        session.mode.setCurrentIndex(3); session.columns.setValue(5)
        assert update(session) and len(session.regions) == 5
        assert session.rows.isHidden() and not session.columns.isHidden()
        assert all(abs(f.BoundBox.XLength - 12) < 1e-5 for f in session.regions)
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "subdivision-strips-panel.png"))
        session.mode.setCurrentIndex(1); session.rows.setValue(3); session.columns.setValue(3)
        assert update(session) and len(session.regions) == 7
        assert "7 faces" in session.status.text()
        assert triangle.Shape.isSame(before_shape) and gallery.UndoCount == before_undo
        session.apply_button.click(); flush(); assert len(triangle.Shape.Faces) == 7
        gallery.undo(); flush(); assert len(triangle.Shape.Faces) == 1
        session = start(name="", target=triangle); session.divisions.setValue(3); assert update(session)
        session.apply_button.click(); flush(); assert len(triangle.Shape.Faces) == 9
        gallery_view.viewTop(); gallery_view.fitAll(); flush()
        for face in triangle.Shape.Faces:
            pixel = tuple(round(value) for value in screen(gallery_view, face.CenterOfMass))
            hit = pick(gallery_view, gallery, pixel, face_only=True)
            assert hit and hit[0] == triangle and abs(hit[1].Area - face.Area) < 1e-5
        App.Console.PrintMessage("PASS: triangle/fan defaults and pattern switching, remembered per-side counts, rows-only/columns-only equal spacing, actual clipped face count, Apply/Undo and pickable triangles\n")
        session = start(name="Face1", target=circle); App.closeDocument(gallery.Name); c.check_context(); assert session.closed
        App.setActiveDocument(doc.Name); flush()
        # Lifecycle guards restore original rendering on every exit.
        session = start("Face1"); session.dialog.close(); flush(); assert session.closed
        session = start("Face1"); c.start("Select"); assert session.closed
        session = start("Face1"); Gui.activateWorkbench("PartWorkbench"); assert session.closed
        Gui.activateWorkbench("SimpleCADWorkbench")
        session = start("Face1"); other = App.newDocument("SubdivideOther"); c.check_context(); assert session.closed
        App.closeDocument(other.Name); App.setActiveDocument(doc.Name)
        op.transform([obj], V(1, 0, 0))
        session = start("Face1"); doc.undo(); c.check_context(); assert session.closed
        doc.redo(); flush()
        session = start("Face1"); obj.Placement = App.Placement(V(1, 2, 3), App.Rotation()); c.check_context(); assert session.closed
        session = start("Face1"); doc.removeObject(obj.Name); c.check_context(); assert session.closed
        Gui.Selection.clearSelection(); c.start("Subdivide"); assert c.subdivide_session is None
        App.Console.PrintMessage("PASS: triangle/pentagon/hexagon/disk Apply, close/tool/workbench/document/Undo/source/deletion cleanup\n")
    c.cancel(quiet=True)
    return doc
