"""Native picking, center-snapped two-segment regions, Push/Pull and Undo.

Run in a separate FreeCAD GUI process. Pointer coordinates are projected by the
native view and passed to controller handlers; no physical mouse input is used.
"""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADLineRegionsSmoke")
    doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeBox(40, 30, 10), "Center-divided block")
    view = Gui.activeDocument().activeView()
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(v)) for v in screen(view, point))

    def draw(first, second):
        before = doc.UndoCount
        c.start("Line")
        c.motion(pos(first))
        c.click(pos(first))
        assert (c.anchor - first).Length < 1e-6, (c.anchor, first)
        c.motion(pos(second))
        assert (c.point - second).Length < 1e-6, (c.point, second)
        assert doc.UndoCount == before
        c.click(pos(second))
        assert c.tool == "Line"
        assert doc.UndoCount == before + 1
        Gui.updateGui()

    a, b = V(0, 0, 10), V(40, 0, 10)
    rect = Part.Face(Part.makePolygon([a, b, V(40, 30, 10), V(0, 30, 10), a]))
    triangle = Part.Face(Part.makePolygon([a, b, V(0, 30, 10), a]))
    shell = Part.makeShell(Part.makeBox(40, 30, 10).Faces[1:])
    for title, base, region_area in (("Block", Part.makeBox(40, 30, 10), 300),
                                     ("Rectangle", rect, 300),
                                     ("Triangle", triangle, 200),
                                     ("Open block", shell, 300)):
        obj.Shape = base
        obj.Label = title
        original_faces = len(base.Faces)
        top = max(base.Faces, key=lambda f: f.CenterOfMass.z)
        center = top.CenterOfMass
        # Orbit an open block so its front/back corner projections do not
        # coincide through the missing side (full snap occlusion is separate).
        orientation = App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q
        view.getCameraNode().orientation.setValue(orientation if title == "Open block" else (0, 0, 0, 1))
        view.fitAll()
        Gui.updateGui()
        draw(a, center)
        assert len(doc.Objects) == 2
        assert len(obj.Shape.Faces) == original_faces
        # A hidden duplicate must neither take part nor get consumed.
        hidden = op.new_shape(doc, Part.makeLine(center, b), "Hidden line")
        hidden.ViewObject.Visibility = False
        hidden_name = hidden.Name
        draw(center, b)
        assert len(obj.Shape.Faces) == original_faces + 1
        assert len(doc.Objects) == 2
        assert doc.getObject(hidden_name) and not hidden.ViewObject.Visibility
        assert not Gui.Selection.getSelection()

        regions = [f for f in obj.Shape.Faces if abs(f.CenterOfMass.z - 10) < 1e-6]
        assert len(regions) == 2
        selected = min(regions, key=lambda f: f.Area)
        assert abs(selected.Area - region_area) < 1e-6
        selected_center = selected.CenterOfMass
        for face in regions:
            hit = pick(view, doc, pos(face.CenterOfMass), face_only=True)
            assert hit and hit[0] == obj and abs(hit[1].Area - face.Area) < 1e-5, hit
        for distance in (-3, 3):
            c.start("PushPull")
            c.motion(pos(selected_center))
            c.click(pos(selected_center))
            assert abs(c.face.Area - region_area) < 1e-5
            c.controls.value.setText(str(distance))
            c.numeric()
            assert c.tool is None
            expected = base.Volume + region_area * distance if base.Solids else region_area * abs(distance)
            assert abs(obj.Shape.Volume - expected) < 1e-5, obj.Shape.Volume
            assert obj.Shape.isValid()
            doc.undo()
            Gui.updateGui()
            assert len(obj.Shape.Faces) == original_faces + 1
        doc.undo()
        assert len(obj.Shape.Faces) == original_faces
        assert len(doc.Objects) == 3  # The incomplete line and hidden line return.
        doc.redo()
        assert len(obj.Shape.Faces) == original_faces + 1
        assert len(doc.Objects) == 2
        doc.removeObject(hidden_name)
        App.Console.PrintMessage("PASS: " + title + ": exact center path, hidden-line exclusion, two native regions, region-only pull both directions, Undo/Redo\n")

    # Leave a clear example of the changed behavior for visual review.
    obj.Shape = Part.makeBox(40, 30, 10)
    view.getCameraNode().orientation.setValue((0, 0, 0, 1))
    view.fitAll()
    Gui.updateGui()
    center = V(20, 15, 10)
    draw(a, center)
    draw(center, b)
    selected = next(f for f in obj.Shape.Faces if len(f.Edges) == 3)
    op.extrude(obj, selected, 9)
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    Gui.Selection.clearSelection()
    Gui.updateGui()
    if screenshot:
        view.saveImage(str(screenshot), 1100, 750, "Current")
    return doc
