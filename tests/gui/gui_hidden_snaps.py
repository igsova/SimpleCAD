"""A corner behind the face under the pointer does not capture the click."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import pick, screen

V = App.Vector


def run():
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADHiddenSnaps")
    doc.UndoMode = 1
    old = c.controls.plane.currentText(), c.controls.snap.isChecked()
    box = op.new_shape(doc, Part.makeBox(40, 30, 20), "Box")
    view = Gui.activeDocument().activeView()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def corners():
        """(corner, face picked at its pixel) for the hidden and a visible corner."""
        hidden = visible = None
        for vertex in box.Shape.Vertexes:
            hit = pick(view, doc, pos(vertex.Point), face_only=True)
            if not hit:
                continue  # On the silhouette.
            if hit[1].distToShape(vertex)[0] > 1:
                hidden = vertex.Point, hit
            else:
                visible = vertex.Point, hit
        assert hidden and visible
        return hidden, visible

    try:
        view.getCameraNode().orientation.setValue(App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
        c.controls.plane.setCurrentText("Auto")
        c.controls.snap.setChecked(True)
        for camera in ("Orthographic", "Perspective"):
            view.setCameraType(camera)
            view.fitAll()
            Gui.updateGui()
            (corner, hit), (seen, _) = corners()
            c.start("Line")
            c.motion(pos(corner))
            snap, plane = c.drawing_start(pos(corner))
            assert (snap.point - corner).Length > 1, (camera, snap.point, snap.label)
            assert hit[1].distToShape(Part.Vertex(snap.point))[0] < 1e-6, (camera, snap.point)
            hint = c.endpoint_hint(pos(corner), snap, plane)
            assert hint is None or (hint - corner).Length > 1, (camera, hint)
            c.click(pos(corner))
            assert c.support == box and hit[1].distToShape(Part.Vertex(c.anchor))[0] < 1e-6, (camera, c.anchor)
            c.cancel(quiet=True)
            print("PASS: %s view, a click over the hidden corner starts on the face in front" % camera, flush=True)
            c.start("Line")
            c.motion(pos(seen))
            snap, _ = c.drawing_start(pos(seen))
            assert (snap.point - seen).Length < 1e-6 and snap.label == "Endpoint", (camera, snap.point, seen)
            c.cancel(quiet=True)
            print("PASS: %s view, a visible corner still snaps" % camera, flush=True)
        assert len(doc.Objects) == 1 and len(box.Shape.Faces) == 6
    finally:
        c.cancel(quiet=True)
        view.setCameraType("Orthographic")
        c.controls.plane.setCurrentText(old[0])
        c.controls.snap.setChecked(old[1])
        App.closeDocument(doc.Name)
