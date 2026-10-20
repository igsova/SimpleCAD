"""Native viewport checks for all rectangle targets and other face centers."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    controller = instance()
    controller.cancel(quiet=True)
    doc = App.newDocument("SimpleCADCenterSnapsSmoke")
    doc.UndoMode = 1
    box = op.new_shape(doc, Part.makeBox(40, 30, 10), "Snap test block")
    view = Gui.activeDocument().activeView()
    # Looking straight at the top also makes back-face targets overlap on
    # screen. Native picking must favor the visible face's actual 3D points.
    view.getCameraNode().orientation.setValue((0, 0, 0, 1))
    view.fitAll()
    Gui.updateGui()
    controller.controls.plane.setCurrentText("Auto")
    controller.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def near(point, center):
        x, y = pos(point)
        cx, cy = pos(center)
        dx, dy = cx - x, cy - y
        length = (dx * dx + dy * dy) ** .5
        return (x + int(round(6 * dx / length)), y + int(round(6 * dy / length))) if length > 0 else (x + 5, y + 3)

    def check(point, label, center):
        target = near(point, center)
        before = doc.UndoCount
        controller.start("Line")
        controller.motion(target)
        assert controller.controls.label.text() == label, (point, controller.controls.label.text())
        marker = V(*controller.preview.marker_coords.point[0].getValue())
        assert (marker - point).Length < 1e-4, (marker, point)
        controller.click(target)
        assert (controller.anchor - point).Length < 1e-6, (controller.anchor, point)
        controller.cancel(quiet=True)
        # Test the second point too, starting on a free point inside the top face.
        controller.start("Line")
        controller.click(pos(V(8, 8, 10)))
        controller.motion(target)
        assert controller.controls.label.text() == label, controller.controls.label.text()
        assert (controller.point - point).Length < 1e-6, (controller.point, point)
        controller.cancel(quiet=True)
        assert doc.UndoCount == before

    center = V(20, 15, 10)
    expected = [(V(x, y, 10), "Endpoint") for x, y in ((0, 0), (40, 0), (40, 30), (0, 30))]
    expected += [(V(x, y, 10), "Midpoint") for x, y in ((20, 0), (40, 15), (20, 30), (0, 15))]
    expected += [(center, "Face center")]
    for point, label in expected:
        check(point, label, center)
    App.Console.PrintMessage("PASS: rectangle's four corners, four edge midpoints and center at both line ends; exact markers and labels; visible face wins over back-face projections\n")

    # Complete a line with approximate pointer positions; geometry is exact.
    controller.start("Line")
    controller.click(near(center, center))
    controller.click(near(V(20, 0, 10), center))
    assert controller.tool == "Line"
    assert len(doc.Objects) == 2
    line = next(obj for obj in doc.Objects if obj != box)
    assert line.Shape.ShapeType == "Edge" and abs(line.Shape.Length - 15) < 1e-6
    assert all(any((vertex.Point - point).Length < 1e-6 for vertex in line.Shape.Vertexes)
               for point in (center, V(20, 0, 10)))
    controller.cancel(quiet=True)
    doc.undo()
    assert len(doc.Objects) == 1
    App.Console.PrintMessage("PASS: center-to-midpoint line commits exact endpoints and length; Undo\n")

    triangle_points = [V(60, 0, 10), V(90, 0, 10), V(60, 30, 10)]
    triangle = op.new_shape(doc, Part.Face(Part.makePolygon(triangle_points + [triangle_points[0]])), "Triangle")
    circle_center = V(120, 15, 10)
    circle = op.new_shape(doc, Part.Face(Part.Wire([Part.makeCircle(12, circle_center)])), "Circle")
    view.fitAll()
    Gui.updateGui()
    for obj, point in ((triangle, V(70, 10, 10)), (circle, circle_center)):
        hit = pick(view, doc, pos(point), face_only=True)
        assert hit and hit[0] == obj, hit
        check(point, "Face center", point)

    controller.start("Line")
    controller.click(near(circle_center, circle_center))
    controller.click(pos(circle_center + V(12, 0, 0)))
    assert controller.tool == "Line" and len(doc.Objects) == 4
    radial = doc.Objects[-1]
    assert radial.Shape.ShapeType == "Edge" and abs(radial.Shape.Length - 12) < 1e-6
    controller.cancel(quiet=True)
    doc.undo()
    App.Console.PrintMessage("PASS: triangular centroid and circular center snap at both ends; circular radial line commits\n")

    controller.controls.snap.setChecked(False)
    controller.start("Line")
    controller.motion(near(circle_center, circle_center))
    assert controller.controls.label.text() != "Face center"
    controller.cancel(quiet=True)
    controller.controls.snap.setChecked(True)
    controller.start("Line")
    controller.click(near(V(70, 10, 10), V(70, 10, 10)))
    controller.motion(near(circle_center, circle_center))
    assert controller.controls.label.text() == "Face center"
    assert (controller.point - circle_center).Length < 1e-6
    Gui.Selection.clearSelection()
    Gui.updateGui()
    if screenshot:
        view.saveImage(str(screenshot), 1100, 650, "Current")
    controller.cancel(quiet=True)
    App.Console.PrintMessage("PASS: Snap switch disables center capture; center-to-center preview is exact and cancellation has no document effects\n")
    return doc
