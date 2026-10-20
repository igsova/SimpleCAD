"""Exercise rotation through the native panel, renderer, shortcuts and Undo."""
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.modeling import rotation
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADRotateSmoke"); doc.UndoMode = 1
    box = Part.makeBox(50, 25, 15)
    obj = op.new_shape(doc, box.makeFillet(2, box.Edges).Solids[0], "Rotation test")
    obj.Placement = App.Placement(V(20, 15, 5), App.Rotation(V(1, 2, 3), 27))
    view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); Gui.updateGui()

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def key(widget, value, text="", modifiers=QtCore.Qt.NoModifier):
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(kind, value, modifiers, text))
        flush()

    def start(name="", shortcut=False, objects=None):
        Gui.Selection.clearSelection()
        for target in objects or [obj]: Gui.Selection.addSelection(target, name)
        if shortcut:
            Gui.getMainWindow().activateWindow(); c.focus_view(); flush()
            widget = QtWidgets.QApplication.focusWidget()
            assert widget is not None
            key(widget, QtCore.Qt.Key_T, "t")
        else: Gui.runCommand("SimpleCAD_Rotate")
        flush()
        assert c.tool == "Rotate" and c.rotate_session is not None
        return c.rotate_session

    def update(session):
        valid = session.update_preview(); flush()
        return valid

    def save(name):
        if screenshots: view.saveImage(str(ROOT.parent.parent / "work" / name), 1100, 800, "Current")

    def restored(shape, original):
        # Native Undo serializes Placement; compare geometry, allowing quaternion
        # roundoff, rather than exact OCC location identity after serialization.
        assert len(shape.Vertexes) == len(original.Vertexes)
        for a, b in zip(shape.Vertexes, original.Vertexes): assert (a.Point - b.Point).Length < 1e-6
        assert abs(shape.Volume - original.Volume) < 1e-5

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "BeforeRotate.FCStd"; name = obj.Name
        doc.saveAs(str(path)); App.closeDocument(doc.Name)
        doc = App.openDocument(str(path)); doc.UndoMode = 1; obj = doc.getObject(name)
        view = Gui.activeDocument().activeView(); view.viewIsometric(); view.fitAll(); flush()
        original, count = obj.Shape, doc.UndoCount
        children = obj.ViewObject.RootNode.getNumChildren()
        session = start("Face1", shortcut=True)
        assert update(session) and session.preview_angle == 0
        for axis in ("X", "Y", "Z", "Main", "LocalX", "LocalY", "LocalZ"):
            session.axis.setCurrentIndex(session.axis.findData(axis))
            session.angle.setText("37.5°")
            assert update(session), session.status.text()
            assert abs(session.frames[0].axis.dot(rotation.direction(original, axis))) > .999999
            if axis == "Main" or axis.startswith("Local"):
                assert session.pivot.currentData() == "Each"
            result = session.planned[0][1]
            assert result.isValid() and result.isClosed()
        for pivot in ("Origin", "Each", "Selection"):
            session.pivot.setCurrentIndex(session.pivot.findData(pivot)); assert update(session)
        assert obj.Shape.isSame(original) and obj.ViewObject.Visibility
        assert len(doc.Objects) == 1 and doc.UndoCount == count and not Gui.activeDocument().Modified
        cached = [node for node, transform in session.preview.cached]
        frames = session.frames
        for value in (-180, -45, 0, 45, 180):
            session.slider.setValue(value); assert update(session)
            assert session.preview_angle == value
            assert session.frames is frames and [node for node, _ in session.preview.cached] == cached
        for value, button in session.presets.items():
            button.click(); assert update(session)
            assert session.preview_angle == value
        session.angle.setText("1.5707963267948966 rad"); assert update(session)
        assert abs(session.preview_angle - 90) < 1e-8
        session.axis.setCurrentIndex(session.axis.findData("Z"))
        session.pivot.setCurrentIndex(session.pivot.findData("Selection"))
        session.angle.setText("-35°"); assert update(session)
        # Renderer and commit must agree in world coordinates, including a moved,
        # rotated source. A double placement gives a radically different bound.
        # Coin's ordinary bounds rotate an already axis-aligned mesh box and can
        # overestimate it. Transform the actual mesh coordinates via scene paths.
        search = coin.SoSearchAction(); search.setType(coin.SoCoordinate3.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL); search.apply(session.preview.models)
        drawn = App.BoundBox()
        for scene_path in search.getPaths():
            action = coin.SoGetMatrixAction(coin.SbViewportRegion(1100, 800)); action.apply(scene_path)
            matrix = action.getMatrix()
            for point in scene_path.getTail().point.getValues():
                drawn.add(V(*matrix.multVecMatrix(coin.SbVec3f(*point)).getValue()))
        shape_box = session.planned[0][1].optimalBoundingBox(False)
        for actual, expected in (((drawn.XMin, drawn.YMin, drawn.ZMin), (shape_box.XMin, shape_box.YMin, shape_box.ZMin)),
                                 ((drawn.XMax, drawn.YMax, drawn.ZMax), (shape_box.XMax, shape_box.YMax, shape_box.ZMax))):
            assert (V(*actual) - V(*expected)).Length < .3, (actual, expected)
        save("rotation-preview.png")
        if screenshots: session.dialog.grab().save(str(ROOT.parent.parent / "work" / "rotation-panel.png"))
        for bad in ("", "banana", "10 mm", "nan"):
            session.angle.setText(bad); assert not update(session)
            assert not session.apply_button.isEnabled() and not session.preview.masks
            assert obj.ViewObject.RootNode.getNumChildren() == children
            assert obj.Shape.isSame(original) and not Gui.activeDocument().Modified
        session.angle.setText("450°"); assert update(session)
        key(session.angle, QtCore.Qt.Key_Escape)
        assert session.closed and c.rotate_session is None
        assert any("Face1" in item.SubElementNames for item in Gui.Selection.getSelectionEx())
        assert obj.ViewObject.RootNode.getNumChildren() == children
        assert not Gui.activeDocument().Modified and doc.UndoCount == count
        App.Console.PrintMessage("PASS: T shortcut, all axes/pivots, angle slider/presets/units, cached meshes, renderer bounds, read-only preview, invalid recovery and Esc\n")
        # Native apply and one-step Undo/Redo preserve object identity and shape.
        session = start(); session.angle.setText("-90°"); assert update(session)
        expected = [v.Point for v in session.planned[0][1].Vertexes]
        key(session.angle, QtCore.Qt.Key_Return)
        assert session.closed and c.rotate_session is None and len(doc.Objects) == 1
        assert doc.UndoCount == count + 1
        for v, point in zip(obj.Shape.Vertexes, expected): assert (v.Point - point).Length < 1e-6
        Gui.Selection.clearSelection(); view.fitAll(); flush(); save("rotation-applied.png")
        doc.undo(); flush(); restored(obj.Shape, original)
        doc.redo(); flush()
        for v, point in zip(obj.Shape.Vertexes, expected): assert (v.Point - point).Length < 1e-6
        doc.undo(); flush()
        session = start(); session.angle.setText("720°"); assert update(session)
        before = doc.UndoCount; session.apply_button.click(); flush()
        assert c.rotate_session is None and doc.UndoCount == before
        restored(obj.Shape, original)
        other = op.new_shape(doc, Part.makeBox(15, 10, 8, V(90, 15, 5)), "Other")
        session = start(objects=[obj, other]); session.angle.setText("90°"); assert update(session)
        results = [(o, [v.Point for v in s.Vertexes]) for o, s in session.planned]
        session.apply_button.click(); flush()
        for target, points in results:
            for v, point in zip(target.Shape.Vertexes, points): assert (v.Point - point).Length < 1e-6
        doc.undo(); flush(); restored(obj.Shape, original)
        session = start(objects=[obj, other]); session.pivot.setCurrentIndex(session.pivot.findData("Each"))
        session.angle.setText("45°"); assert update(session)
        for (target, _), (_, result) in zip(session.targets, session.planned):
            assert (result.CenterOfMass - target.Shape.CenterOfMass).Length < 1e-6
        c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: Enter Apply, one Undo/Redo, whole-turn no-op, multi-object rotation together and individual centers\n")
        # Every exit restores the original Coin graph and releases the session.
        session = start(); session.dialog.close(); flush(); assert session.closed
        session = start(); c.start("Move"); assert session.closed; c.cancel(quiet=True)
        session = start(); Gui.activateWorkbench("PartWorkbench"); assert session.closed
        Gui.activateWorkbench("SimpleCADWorkbench")
        session = start(); other_doc = App.newDocument("RotateOtherDoc"); c.check_context(); assert session.closed
        App.closeDocument(other_doc.Name); App.setActiveDocument(doc.Name)
        op.transform([obj], V(1, 0, 0))
        session = start(); doc.undo(); c.check_context(); assert session.closed
        doc.redo(); flush()
        session = start(); obj.Placement = App.Placement(V(1, 2, 3), App.Rotation())
        c.check_context(); assert session.closed
        session = start(); doc.removeObject(obj.Name); c.check_context(); assert session.closed
        Gui.Selection.clearSelection(); c.start("Rotate"); assert c.rotate_session is None
        # Closing the captured document safely cleans up native masks too.
        surface_doc = App.newDocument("RotateOpen")
        surface = op.new_shape(surface_doc, Part.makeShell(Part.makeBox(20, 10, 8).Faces[:-1]), "Open surface")
        session = start(objects=[surface]); session.angle.setText("45°"); assert update(session)
        session.apply_button.click(); flush(); assert not surface.Shape.Solids and surface.Shape.isValid()
        session = start(objects=[surface]); App.closeDocument(surface_doc.Name); c.check_context()
        assert session.closed and c.rotate_session is None
        App.setActiveDocument(doc.Name)
        App.Console.PrintMessage("PASS: dialog/tool/workbench/document/Undo/source-change cleanup; deleted targets and open surfaces\n")
    c.cancel(quiet=True)
    return doc
