"""Visible center guidance and a larger magnet on a tilted, selected face."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen, screen_distance
from pivy import coin

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    controller = instance()
    controller.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSnapVisibilitySmoke")
    doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeBox(40, 30, 20), "Center target test")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()
    center = V(20, 0, 10)
    front = next("Face" + str(i + 1) for i, face in enumerate(obj.Shape.Faces)
                 if (face.CenterOfMass - center).Length < 1e-7)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, front)
    controller.controls.plane.setCurrentText("Auto")
    controller.controls.snap.setChecked(True)
    count = doc.UndoCount

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def moved(offset):
        x, y = pos(center)
        target = (x + offset, y)
        hit = pick(view, doc, target, face_only=True)
        assert hit and hit[0] == obj and hit[3] == front, hit
        controller.motion(target)
        return target

    controller.start("Line")
    controller.click(pos(V(0, 0, 20)))
    moved(60)
    assert controller.controls.label.text() != "Face center"
    assert controller.preview.center_guide.switch.whichChild.getValue() == 0
    assert controller.preview.center_guide.texts[-1].string[0] == "Center"
    assert all(dot.numPoints.getValue() == 0 for dot in controller.preview.center_guide.dots)
    App.Console.PrintMessage("PASS: amber target locates the selected tilted face's center from outside the capture radius\n")

    def check_capture():
        moved(32)  # More than twice the old 12-pixel radius.
        assert controller.controls.label.text() == "Face center"
        assert (controller.point - center).Length < 1e-6
        assert controller.preview.center_guide.texts[-1].string[0] == "Center snapped"
        assert all(dot.numPoints.getValue() == 1 for dot in controller.preview.center_guide.dots)
        hint_edge = V(*controller.preview.center_guide.coords.point[0].getValue())
        assert abs(screen_distance(pos(center), pos(hint_edge)) - 11) <= 1.5
        # The overlay must not intercept native face picking.
        hit = pick(view, doc, pos(center), face_only=True)
        assert hit and hit[3] == front and hit[0] == obj, hit
        assert doc.UndoCount == count

    check_capture()
    if screenshot:
        Gui.updateGui()
        view.saveImage(str(screenshot), 1100, 750, "Current")
    view.getCameraNode().height = view.getCameraNode().height.getValue() * .7
    Gui.updateGui()
    check_capture()
    view.setCameraType("Perspective")
    view.fitAll()
    Gui.updateGui()
    check_capture()
    App.Console.PrintMessage("PASS: 32-pixel approach snaps exactly; filled target and Center snapped text; constant-size glyph under zoom and perspective; native picking unaffected\n")

    controller.controls.snap.setChecked(False)
    moved(32)
    assert controller.preview.center_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    assert controller.controls.label.text() != "Face center"
    controller.controls.snap.setChecked(True)
    check_capture()
    overlay = controller.preview.root
    controller.cancel(quiet=True)
    assert view.getSceneGraph().findChild(overlay) == -1
    assert doc.UndoCount == count
    # A click within the new radius also commits the exact center as an endpoint.
    controller.start("Line")
    controller.click(pos(V(0, 0, 20)))
    x, y = pos(center)
    controller.click((x + 32, y))
    assert controller.tool == "Line" and len(doc.Objects) == 2
    line = next(other for other in doc.Objects if other != obj)
    assert line.Shape.ShapeType == "Edge"
    assert any((vertex.Point - center).Length < 1e-6 for vertex in line.Shape.Vertexes)
    controller.cancel(quiet=True)
    doc.undo()
    assert len(doc.Objects) == 1
    Gui.Selection.clearSelection()
    App.Console.PrintMessage("PASS: Snap off hides the hint, cancel removes the overlay, enlarged-radius click commits an exact line, Undo\n")
    return doc
