"""Native picking and controller events for pulling joined/open surfaces."""
from types import SimpleNamespace

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    controller = instance()
    controller.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSurfacePullSmoke")
    doc.UndoMode = 1
    a, b = V(0, 0, 10), V(40, 0, 10)
    faces = [Part.Face(Part.makePolygon([a, b, V(20, 25, 10), a])),
             Part.Face(Part.makePolygon([b, a, V(20, -15, -10), b]))]
    for face in faces:
        op.new_shape(doc, face, "Triangle")
    op.cleanup(doc)
    assert len(doc.Objects) == 1
    obj = doc.Objects[0]
    assert obj.Shape.ShapeType == "Shell" and not obj.Shape.Solids
    obj.ViewObject.ShapeColor = (0.76, 0.84, 0.88)
    obj.ViewObject.LineColor = (0.15, 0.23, 0.29)
    obj.ViewObject.LineWidth = 2.0
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    for index in range(2):
        for distance in (-4, 5):
            view.fitAll()
            Gui.updateGui()
            face = obj.Shape.Faces[index]
            other = obj.Shape.Faces[1 - index]
            center = face.CenterOfMass
            hit = pick(view, doc, pos(center), face_only=True)
            assert hit and hit[0] == obj and coinc.same(hit[1], face), hit
            count = doc.UndoCount
            controller.start("PushPull")
            controller.motion(pos(center))
            controller.click(pos(center))
            controller.controls.value.setText(str(distance))
            controller.numeric()
            assert controller.tool is None
            assert len(doc.Objects) == 2
            assert obj.Shape.ShapeType == "Solid" and obj.Shape.isValid()
            assert abs(obj.Shape.Volume - face.Area * abs(distance)) < 1e-5
            rest = next(other_obj for other_obj in doc.Objects if other_obj != obj)
            assert coinc.same(rest.Shape, other)
            assert tuple(rest.ViewObject.ShapeColor) == tuple(obj.ViewObject.ShapeColor)
            assert abs(rest.ViewObject.LineWidth - 2.0) < 1e-6
            assert doc.UndoCount == count + 1
            doc.undo()
            assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == 2
            assert not obj.Shape.Solids
    App.Console.PrintMessage("PASS: both native triangle picks complete numeric Push/Pull in both directions; neighboring face and appearance preserved; Undo\n")

    view.fitAll()
    Gui.updateGui()
    face = obj.Shape.Faces[0]
    center = face.CenterOfMass
    count = doc.UndoCount
    controller.start("PushPull")

    def mouse(state, point):
        event = coin.SoMouseButtonEvent()
        event.setButton(coin.SoMouseButtonEvent.BUTTON1)
        event.setState(state)
        event.setPosition(coin.SbVec2s(*point))
        controller.coin_event(SimpleNamespace(getEvent=lambda: event, setHandled=lambda: None))

    mouse(coin.SoButtonEvent.DOWN, pos(center))
    target = pos(center + controller.normal * 8)
    controller.motion(target)
    distance = controller.distance
    assert abs(distance) > 1
    assert doc.UndoCount == count and len(obj.Shape.Faces) == 2
    mouse(coin.SoButtonEvent.UP, target)
    assert controller.tool is None
    assert abs(obj.Shape.Volume - face.Area * abs(distance)) < 1e-5
    assert doc.UndoCount == count + 1 and len(doc.Objects) == 2
    Gui.Selection.clearSelection()
    view.fitAll()
    Gui.updateGui()
    if screenshot:
        view.saveImage(str(screenshot), 1000, 700, "Current")
    doc.undo()
    assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == 2
    doc.redo()
    assert len(doc.Objects) == 2 and len(obj.Shape.Solids) == 1
    doc.undo()
    App.Console.PrintMessage("PASS: drag/release controller path commits a solid; preview has no writes; Undo/Redo\n")

    # Cancellation and an outward normal on an oppositely oriented closed shell.
    controller.start("PushPull")
    view.fitAll()
    Gui.updateGui()
    controller.click(pos(obj.Shape.Faces[0].CenterOfMass))
    controller.motion(pos(center + controller.normal * 5))
    count = doc.UndoCount
    controller.cancel(quiet=True)
    assert doc.UndoCount == count and len(doc.Objects) == 1
    shell = Part.makeBox(40, 30, 10).Shells[0]
    shell.reverse()
    obj.Shape = shell
    doc.recompute()
    view.fitAll()
    Gui.updateGui()
    controller.start("PushPull")
    controller.click(pos(V(20, 15, 10)))
    assert controller.normal.z > 0.99
    controller.controls.value.setText("5")
    controller.numeric()
    assert controller.tool is None and len(doc.Objects) == 1
    assert abs(obj.Shape.Volume - 18000) < 1e-5
    doc.undo()
    assert obj.Shape.ShapeType == "Shell"
    App.Console.PrintMessage("PASS: cancel has no document effects; closed shell preview and commit use outward direction and preserve enclosed volume\n")
    Gui.Selection.clearSelection()
    return doc
