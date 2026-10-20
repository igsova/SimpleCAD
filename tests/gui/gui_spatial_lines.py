"""Native viewport check for a line connecting vertices on different faces."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSpatialLineSmoke")
    a, b, joint = g.V(0, 0, 0), g.V(30, 20, 15), g.V(30, 0, 0)
    left = Part.Face(Part.makePolygon([a, joint, g.V(0, -20, -10), a]))
    right = Part.Face(Part.makePolygon([joint, b, g.V(50, 20, -5), joint]))
    obj = op.new_shape(doc, Part.makeCompound([left, right]), "Cross-face triangle")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(g.V(1, 1, 0), g.V(-1, 1, 2), g.V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)
    c.start("Line")
    c.click(pos(a))
    assert (c.anchor - a).Length < 1e-6
    assert not any(g.point_on_face(face, b) for face in c.line_faces)
    assert abs((b - c.plane.origin).dot(c.plane.normal)) > 1
    c.motion(pos(b))
    assert (c.point - b).Length < 1e-6, c.point
    assert c.controls.label.text() == "Endpoint"
    assert len(obj.Shape.Faces) == 2  # Only a preview until the second click.
    c.click(pos(b))
    assert c.tool is None  # Completing the triangle closes a loop, which ends Line.
    assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == 3
    assert obj.Shape.isValid()
    Gui.updateGui()
    center = (a + b + joint) / 3
    hit = pick(view, doc, pos(center), face_only=True)
    assert hit and hit[0] == obj and abs(hit[1].Area - 375) < 1e-5, hit
    if screenshot:
        Gui.Selection.addSelection(obj, hit[3])
        Gui.updateGui()
        view.saveImage(str(screenshot), 1000, 700, "Current")
        Gui.Selection.clearSelection()
    c.cancel(quiet=True)
    doc.undo()
    assert len(obj.Shape.Faces) == 2
    doc.redo()
    assert len(obj.Shape.Faces) == 3
    App.Console.PrintMessage("PASS: 3D cross-face endpoint snap, triangle creation and native picking, Undo/Redo\n")
    return doc
