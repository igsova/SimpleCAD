"""Run run() from FreeCAD's console. Uses real camera, picking, Coin, and Qt.

Calls tool handlers directly; this does not certify physical mouse/trackpad events.
Leaves a separate, unsaved SimpleCADSmoke document for visual inspection.
"""
import FreeCAD as App
import FreeCADGui as Gui
from simplecad.gui.controller import instance
from simplecad.core import geometry as g
from simplecad.gui.snapping import screen, Snapper, pick


def run():
    update = Gui.updateGui
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSmoke")
    view = Gui.activeDocument().activeView()
    view.viewIsometric()
    view.getCameraNode().height = 120
    update()
    marks = []

    def passed(name):
        marks.append(name)
        App.Console.PrintMessage("PASS: " + name + "\n")

    def pos(point):
        return tuple(int(round(x)) for x in screen(view, point))

    c.start("Rectangle")
    nodes = view.getSceneGraph().getNumChildren()
    c.click(pos(g.V()))
    c.motion(pos(g.V(40, 30, 0)))
    assert c.preview is not None
    assert len(doc.Objects) == 0
    c.controls.value.setText("40, 30")
    c.numeric()
    assert len(doc.Objects) == 1
    obj = doc.Objects[0]
    assert abs(obj.Shape.Area - 1200) < 1e-6
    assert view.getSceneGraph().getNumChildren() == nodes - 1
    passed("Rectangle preview, numeric size, commit, overlay removal")

    view.fitAll()
    update()
    c.start("PushPull")
    c.click(pos(obj.Shape.CenterOfMass))
    c.motion((c.down_pos[0], c.down_pos[1] + 50))
    assert abs(c.distance) > 0
    assert len(obj.Shape.Solids) == 0
    c.controls.value.setText("20")
    c.numeric()
    assert abs(obj.Shape.Volume - 24000) < 1e-5
    passed("Face picking, live extrusion preview, solid creation")

    view.fitAll()
    update()
    top = max(obj.Shape.Faces, key=lambda f: f.CenterOfMass.z)
    c.start("PushPull")
    c.click(pos(top.CenterOfMass))
    c.controls.value.setText("-5")
    c.numeric()
    assert abs(obj.Shape.Volume - 18000) < 1e-5
    doc.undo()
    assert abs(obj.Shape.Volume - 24000) < 1e-5
    view.fitAll()
    passed("Inward face cut and Undo")

    update()
    top = max(obj.Shape.Faces, key=lambda f: f.CenterOfMass.z)
    center = top.CenterOfMass
    c.start("Rectangle")
    c.click(pos(center))
    c.controls.value.setText("5, 5")
    c.numeric()
    # The rectangle divides the top face, as Circle and Polygon do; a separate
    # face lying on it flickered against the top in the viewport.
    assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == 7
    region = next(f for f in obj.Shape.Faces if abs(f.Area - 25) < 1e-9)
    assert abs(obj.Shape.Volume - 24000) < 1e-5
    update()
    assert pick(view, doc, pos(region.CenterOfMass), True)[0] == obj
    c.start("PushPull")
    c.click(pos(region.CenterOfMass))
    c.controls.value.setText("-4")
    c.numeric()
    assert len(doc.Objects) == 1
    assert abs(obj.Shape.Volume - 23900) < 1e-5
    passed("Draw a rectangle on a face, divide it, cut pocket")

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj)
    center = max(obj.Shape.Faces, key=lambda f: f.Area).CenterOfMass
    c.start("Copy")
    c.click(pos(center))
    c.axis = g.V(1, 0, 0)
    c.controls.value.setText("60")
    c.numeric()
    assert len(doc.Objects) == 2
    clone = doc.Objects[-1]
    assert abs(clone.Shape.BoundBox.XMin - obj.Shape.BoundBox.XMin - 60) < 1e-5
    passed("Copy with exact axis distance")

    c.start("Move")
    c.click(pos(clone.Shape.CenterOfMass))
    c.axis = g.V(0, 1, 0)
    c.controls.value.setText("15")
    c.numeric()
    assert abs(clone.Shape.BoundBox.YMin - obj.Shape.BoundBox.YMin - 15) < 1e-5
    c.start("Delete")
    assert len(doc.Objects) == 1
    doc.undo()
    assert len(doc.Objects) == 2
    passed("Move, Delete, and Undo")

    view.fitAll()
    update()
    snapper = Snapper(doc, view)
    vertex = obj.Shape.Vertexes[0].Point
    plane = g.Plane.named("XY", vertex)
    assert snapper.snap(pos(vertex), plane).label == "Endpoint"
    edge = obj.Shape.Edges[0]
    middle = edge.valueAt(edge.getParameterByLength(edge.Length / 2))
    assert snapper.snap(pos(middle), g.Plane.named("XY", middle)).label == "Midpoint"
    passed("Endpoint and midpoint inference")

    c.start("Line")
    c.controls.plane.setCurrentText("XY")
    c.click(pos(g.V(-30, -30, 0)))
    c.motion(pos(g.V(-10, -30, 0)))
    c.commit()
    assert len(doc.Objects) == 3
    assert doc.Objects[-1].Shape.ShapeType == "Edge"
    assert c.tool == "Line"
    c.cancel(quiet=True)
    passed("Line drawing")

    count = view.getSceneGraph().getNumChildren()
    c.start("Rectangle")
    c.cancel()
    assert view.getSceneGraph().getNumChildren() == count
    assert c.callback is None and c.preview is None
    c.start("Rectangle")
    other = App.newDocument("SimpleCADContextTest")
    c.check_context()
    assert c.tool is None
    App.closeDocument(other.Name)
    App.setActiveDocument(doc.Name)
    c.controls.plane.setCurrentText("Auto")
    Gui.Selection.clearSelection()
    Gui.activeDocument().activeView().fitAll()
    passed("Cancel and document-switch cleanup")
    App.Console.PrintMessage("SimpleCAD GUI smoke: %d checks passed\n" % len(marks))
    return marks
