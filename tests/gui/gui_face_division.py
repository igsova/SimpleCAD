"""Run run() in a fresh FreeCAD GUI; leaves a separate unsaved test block.

Uses native view projection and picking with controller handlers. Physical
mouse/trackpad events still require the hands-on checklist.
"""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick


def run():
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADFaceDivisionSmoke")
    obj = op.new_shape(doc, Part.makeBox(40, 30, 10), "Divided block")
    view = Gui.activeDocument().activeView()
    # Set the camera directly: viewIsometric() can still be animating when a
    # synchronous test projects its next click, leaving the side edge-on.
    view.getCameraNode().orientation.setValue(
        App.Rotation(g.V(1, 1, 0), g.V(-1, 1, 2), g.V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.updateGui()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)
    c.start("Line")
    c.click(pos(g.V(0, 0, 10)))
    assert (c.anchor - g.V(0, 0, 10)).Length < 1e-5, c.anchor
    c.motion(pos(g.V(40, 0, 0)))
    assert (c.point - g.V(40, 0, 0)).Length < 1e-5, c.point
    assert len(obj.Shape.Faces) == 6  # Preview does not mutate the solid.
    c.click(pos(g.V(40, 0, 0)))
    assert len(doc.Objects) == 1
    assert len(obj.Shape.Faces) == 7
    assert not Gui.Selection.getSelection()
    Gui.updateGui()
    App.Console.PrintMessage("PASS: corner snapping, Auto side-plane inference, line commit\n")

    centers = [face.CenterOfMass for face in obj.Shape.Faces
               if len(face.Edges) == 3 and abs(face.CenterOfMass.y) < 1e-6]
    assert len(centers) == 2
    for center in centers:
        for distance in (-5, 5):
            view.fitAll()
            Gui.updateGui()
            hit = pick(view, doc, pos(center), face_only=True)
            assert hit and hit[0] == obj and abs(hit[1].Area - 200) < 1e-5, hit
            c.start("PushPull")
            c.motion(pos(center))
            assert c.preview is not None
            c.click(pos(center))
            assert abs(c.face.Area - 200) < 1e-5
            c.controls.value.setText(str(distance))
            c.numeric()
            assert c.tool is None
            assert abs(obj.Shape.Volume - (12000 + distance * 200)) < 1e-5
            doc.undo()
            assert len(obj.Shape.Faces) == 7
            assert abs(obj.Shape.Volume - 12000) < 1e-5
    Gui.Selection.clearSelection()
    view.fitAll()
    Gui.updateGui()
    App.Console.PrintMessage("PASS: native picking, triangle-only Push/Pull both directions, Undo\n")
    return doc
