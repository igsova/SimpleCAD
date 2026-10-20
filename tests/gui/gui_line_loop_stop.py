"""Line keeps clicking until a segment closes a loop into a face, then stops."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    old_plane, old_snap = c.controls.plane.currentText(), c.controls.snap.isChecked()
    doc = App.newDocument("SimpleCADLineLoopStop")
    doc.UndoMode = 1
    try:
        op.new_shape(doc, Part.Vertex(V(-30, -30, 0)), "Anchor")
        view = Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue((0, 0, 0, 1))
        view.fitAll()
        view.getCameraNode().height = 120
        Gui.updateGui()
        c.controls.plane.setCurrentText("Auto")
        c.controls.snap.setChecked(True)
        status = Gui.getMainWindow().statusBar()

        def pos(point):
            return tuple(int(round(x)) for x in screen(view, point))

        def faces():
            return sum(o.Shape.countElement("Face") for o in doc.Objects if o.TypeId == "Part::Feature")

        # An open chain keeps going; the segment back to the start closes it.
        corners = [V(0, 0, 0), V(30, 0, 0), V(30, 20, 0), V(0, 20, 0)]
        c.start("Line")
        c.click(pos(corners[0]))
        root = c.preview.root
        for corner in corners[1:]:
            c.click(pos(corner))
            assert c.tool == "Line" and (c.anchor - corner).Length < .5 and faces() == 0  # pixel-rounded clicks
        c.click(pos(corners[0]))
        assert c.tool is None and c.preview is None and view.getSceneGraph().findChild(root) == -1
        assert faces() == 1 and "Loop closed" in status.currentMessage()
        face = next(o for o in doc.Objects if o.Shape.Faces)
        assert abs(face.Shape.Area - 600) < 30
        count = doc.UndoCount
        doc.undo()
        assert faces() == 0 and doc.UndoCount == count - 1
        doc.redo()
        assert faces() == 1
        App.Console.PrintMessage("PASS: open Line chain continues; closing the loop makes a face and ends Line\n")

        # The styled vertex has no faces; hover and selection tints skip it.
        style = c.viewport_style
        assert style.active()
        Gui.Selection.addSelection(face)
        style.style_objects()
        Gui.Selection.clearSelection()
        style.style_objects()
        App.Console.PrintMessage("PASS: viewport style tints with a faceless object present\n")

        # L starts a fresh chain.
        c.start("Line")
        c.click(pos(corners[1]))
        c.click(pos(V(45, 0, 0)))
        assert c.tool == "Line" and faces() == 1
        c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: a later Line starts a fresh chain from an existing corner\n")

        # On a box's top, a loop of four lines divides the face and ends Line.
        for o in doc.Objects:
            o.ViewObject.Visibility = False
        box = op.new_shape(doc, Part.makeBox(40, 30, 10, V(100, 0, 0)), "Box")
        view.fitAll()
        Gui.updateGui()
        loop = [V(110, 8, 10), V(130, 8, 10), V(130, 22, 10), V(110, 22, 10)]
        c.start("Line")
        c.click(pos(loop[0]))
        for corner in loop[1:]:
            c.click(pos(corner))
            assert c.tool == "Line" and len(box.Shape.Faces) == 6
        c.click(pos(loop[0]))
        assert c.tool is None and len(box.Shape.Faces) == 7 and box.Shape.isValid()
        assert "P: Push/Pull" in status.currentMessage()
        assert not [o for o in doc.Objects if o != box and o.ViewObject.Visibility]
        App.Console.PrintMessage("PASS: a loop drawn on a face divides it and ends Line\n")

        # Typing the closing length ends the chain the same way.
        triangle = [V(0, 40, 0), V(20, 40, 0)]
        for o in doc.Objects:
            o.ViewObject.Visibility = o != box
        view.fitAll()
        Gui.updateGui()
        c.start("Line")
        c.click(pos(triangle[0]))
        c.click(pos(triangle[1]))
        c.click(pos(V(0, 60, 0)))
        c.motion(pos(triangle[0]))  # aligns with the Y axis
        c.controls.value.setText("20")
        c.numeric()
        assert c.tool is None and faces() == 9, (c.tool, faces(), c.anchor, status.currentMessage())  # rectangle, box, triangle
        App.Console.PrintMessage("PASS: a typed closing length ends Line\n")
    finally:
        c.cancel(quiet=True)
        c.controls.plane.setCurrentText(old_plane)
        c.controls.snap.setChecked(old_snap)
        App.closeDocument(doc.Name)
