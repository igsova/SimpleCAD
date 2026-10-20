"""Visible edge midpoint targets at both ends of Line, using native picking."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen, screen_distance

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADMidpointVisibilitySmoke")
    doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeBox(40, 30, 20), "Midpoint target test")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()
    center = V(20, 0, 10)
    front = next("Face" + str(i + 1) for i, f in enumerate(obj.Shape.Faces)
                 if (f.CenterOfMass - center).Length < 1e-7)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, front)
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)
    before = doc.UndoCount

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def approach(point, offset):
        x, y = pos(point)
        cx, cy = pos(center)
        length = screen_distance((x, y), (cx, cy))
        return (x + round((cx - x) * offset / length), y + round((cy - y) * offset / length))

    def check(point, snapped):
        guide = c.preview.midpoint_guide
        assert guide.switch.whichChild.getValue() == 0
        assert (V(*guide.dot_coords.point[0].getValue()) - point).Length < 1e-5
        assert guide.texts[-1].string[0] == ("Midpoint snapped" if snapped else "Midpoint")
        assert all(dot.numPoints.getValue() == int(snapped) for dot in guide.dots)
        tip = V(*guide.coords.point[0].getValue())
        assert abs(screen_distance(pos(point), pos(tip)) - 12) <= 1.5
        if snapped:
            assert c.controls.label.text() == "Midpoint"
            assert (V(*c.preview.marker_coords.point[0].getValue()) - point).Length < 1e-5
        hit = pick(view, doc, pos(point))
        # Integer projection can land just inside an adjacent face. Either
        # native element is valid; the overlay must never intercept the pick.
        assert hit and hit[0] == obj and hit[1].ShapeType in ("Edge", "Face"), hit
        assert hit[1].distToShape(Part.Vertex(point))[0] < 1e-6
        assert doc.UndoCount == before

    points = [V(20, 0, 20), V(20, 0, 0), V(0, 0, 10), V(40, 0, 10)]
    for point in points:
        c.start("Line")
        c.motion(approach(point, 45))
        check(point, False)
        c.motion(approach(point, 16))
        check(point, True)
        c.click(approach(point, 16))
        assert (c.anchor - point).Length < 1e-6
        c.cancel(quiet=True)
        c.start("Line")
        c.click(pos(center))
        c.motion(approach(point, 45))
        check(point, False)
        c.motion(approach(point, 16))
        check(point, True)
        assert (c.point - point).Length < 1e-6
        c.cancel(quiet=True)
    App.Console.PrintMessage("PASS: all four face-edge midpoints show a 24-pixel diamond and label before capture; exact snapped confirmation at both line ends; native edge picking unaffected\n")

    point = points[0]
    c.start("Line")
    c.click(pos(center))
    c.motion(approach(point, 16))
    check(point, True)
    if screenshot:
        Gui.updateGui()
        view.saveImage(str(screenshot), 1100, 750, "Current")
    view.getCameraNode().height = view.getCameraNode().height.getValue() * .8
    Gui.updateGui()
    c.motion(approach(point, 16))
    check(point, True)
    view.setCameraType("Perspective")
    view.fitAll()
    Gui.updateGui()
    c.motion(approach(point, 16))
    check(point, True)
    c.controls.snap.setChecked(False)
    c.motion(approach(point, 16))
    assert c.preview.midpoint_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    assert c.preview.center_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    c.controls.snap.setChecked(True)
    c.motion(approach(point, 16))
    check(point, True)
    overlay = c.preview.root
    c.cancel(quiet=True)
    assert view.getSceneGraph().findChild(overlay) == -1
    assert doc.UndoCount == before
    App.Console.PrintMessage("PASS: midpoint glyph stays the same size after zoom and perspective changes; Snap off and cancel remove guidance without edits\n")

    c.start("Line")
    c.click(pos(center))
    c.click(approach(point, 16))
    assert c.tool == "Line" and len(doc.Objects) == 2
    line = next(other for other in doc.Objects if other != obj)
    assert line.Shape.ShapeType == "Edge" and abs(line.Shape.Length - 10) < 1e-6
    assert any((v.Point - point).Length < 1e-6 for v in line.Shape.Vertexes)
    assert doc.UndoCount == before + 1
    c.cancel(quiet=True)
    doc.undo()
    assert len(doc.Objects) == 1
    Gui.Selection.clearSelection()
    App.Console.PrintMessage("PASS: approximate click commits the exact edge midpoint; one-step Undo\n")
    return doc
