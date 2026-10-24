"""Measure Tape leaves dashed guides that drawing snaps to, without changing the model."""
import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.document import guides, operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, snap_targets
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector
KEYS = {"\r": QtCore.Qt.Key_Return, "\t": QtCore.Qt.Key_Tab, ".": QtCore.Qt.Key_Period,
        "\x1b": QtCore.Qt.Key_Escape, "\x7f": QtCore.Qt.Key_Delete}


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADMeasureTape")
    doc.UndoMode = 1
    block = op.new_shape(doc, Part.makeBox(100, 100, 100), "Block")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0, 0, 1), V(1, 1, 1)).Q)
    view.fitAll()
    Gui.updateGui()
    old_mode, old_plane = c.controls.drawing_mode.currentIndex(), c.controls.plane.currentText()
    c.controls.drawing_mode.setCurrentIndex(0)
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)
    volume = block.Shape.Volume
    reload_path = os.path.join(tempfile.mkdtemp(), "guides.FCStd")

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def keys(text, modifiers=QtCore.Qt.NoModifier, start_in_view=False):
        """Type ``text`` where the focus is, as the keyboard would."""
        if start_in_view:
            c.focus_view()
        for char in text:
            key = KEYS.get(char, getattr(QtCore.Qt, "Key_" + char.upper(), 0))
            shown = "" if char in KEYS and char != "." else char
            for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(QtWidgets.QApplication.focusWidget(),
                                                 QtGui.QKeyEvent(kind, key, modifiers, shown))
        Gui.updateGui()

    def hover(point):
        """Move the pointer before a first click; return the snap label and point."""
        c.motion(pos(point))
        return c.controls.label.text(), c.drawing_start(pos(point))[0].point

    def guide_objects():
        return [obj for obj in doc.Objects if guides.is_guide(obj)]

    def close(a, b, tolerance=1e-6):
        return (a - b).Length <= tolerance

    def save(suffix):
        if screenshot:
            Gui.updateGui()
            Gui.getMainWindow().grab().save(str(screenshot).replace(".png", suffix + ".png"))

    try:
        # T starts the tape; Q is Rotate and Shift+Q is Loft, as in SketchUp.
        started = []
        c.start, start = started.append, c.start
        try:
            keys("q", start_in_view=True)
            keys("Q", QtCore.Qt.ShiftModifier, start_in_view=True)
            keys("t", start_in_view=True)
        finally:
            c.start = start
        assert started == ["Rotate", "Loft", "Tape"], started
        keys("t", start_in_view=True)
        assert c.tool == "Tape", c.tool
        App.Console.PrintMessage("PASS: T starts Measure Tape, Q Rotate and Shift+Q Loft\n")

        # From an edge, the tape measures straight out from it; a typed distance
        # places a parallel guide, and the tool stays ready for the next one.
        height = view.getCameraNode().height.getValue()
        count = doc.UndoCount
        c.motion(pos(V(100, 30, 100)))
        assert c.controls.label.text() == "On edge", c.controls.label.text()
        c.click(pos(V(100, 30, 100)))
        assert c.tape_input.along is not None and abs(abs(c.tape_input.along.y) - 1) < 1e-9, c.tape_input.along
        c.motion(pos(V(70, 45, 100)))
        assert close(c.tape_input.end, V(70, 30, 100), 0.5), c.tape_input.end
        save("-parallel")
        keys("25\r", start_in_view=True)
        found = guide_objects()
        assert len(found) == 1 and doc.UndoCount == count + 1, (found, doc.UndoCount, count)
        point, direction = guides.line(found[0])
        # The guide passes through the clicked spot, 25 mm in from the edge.
        assert abs(point.x - 75) < 1e-6 and abs(point.z - 100) < 1e-6 and abs(abs(direction.y) - 1) < 1e-9, \
            (point, direction)
        assert c.tool == "Tape" and c.anchor is None and found[0].Label == "Guide"
        assert abs(block.Shape.Volume - volume) < 1e-9 and len(doc.Objects) == 3, doc.Objects
        App.Console.PrintMessage("PASS: from an edge, 25 mm typed leaves a parallel guide line in one Undo step\n")

        # From a corner, the tape measures to the pointer and leaves a guide point.
        c.click(pos(V(100, 100, 100)))
        assert c.tape_input.along is None and close(c.anchor, V(100, 100, 100))
        c.motion(pos(V(100, 100, 50)))
        keys("40\r", start_in_view=True)
        found = guide_objects()
        point, direction = guides.line(found[-1])
        assert len(found) == 2 and direction is None and close(point, V(100, 100, 60)), (found, point, direction)
        assert found[-1].Label == "Guide point" and doc.UndoCount == count + 2
        App.Console.PrintMessage("PASS: from a corner, 40 mm typed leaves a guide point toward the pointer\n")

        # A second guide from the far top edge, then the tape snaps to the first guide.
        c.click(pos(V(30, 100, 100)))
        c.motion(pos(V(30, 80, 100)))
        keys("20\r", start_in_view=True)
        point, direction = guides.line(guide_objects()[-1])
        assert len(guide_objects()) == 3 and abs(point.y - 80) < 1e-6 and abs(abs(direction.x) - 1) < 1e-9, \
            (point, direction)
        label, point = hover(V(75, 55, 100))
        assert label == "On guide" and abs(point.x - 75) < 1e-6, (label, point)
        # From a guide line, the next guide steps out parallel to it.
        c.click(pos(V(75, 55, 100)))
        assert c.tape_input.along is not None and abs(abs(c.tape_input.along.y) - 1) < 1e-9
        c.motion(pos(V(60, 55, 100)))
        keys("10\r", start_in_view=True)
        point, direction = guides.line(guide_objects()[-1])
        assert len(guide_objects()) == 4 and abs(point.x - 65) < 1e-6 and abs(abs(direction.y) - 1) < 1e-9, \
            (point, direction)
        doc.undo()
        c.cancel()
        assert c.tool is None and len(guide_objects()) == 3
        save("-guides")
        App.Console.PrintMessage("PASS: the tape measures out from an earlier guide; Esc ends it and keeps the guides\n")

        # Fit All frames the model, not the guide lines that run far past it.
        view.fitAll()
        Gui.updateGui()
        assert abs(view.getCameraNode().height.getValue() - height) < 0.02 * height, \
            (view.getCameraNode().height.getValue(), height)
        App.Console.PrintMessage("PASS: Fit All ignores the guide lines\n")

        # Lines snap to guides, guide points and where guides cross edges and each other.
        c.start("Line")
        for target, expected in ((V(75, 80, 100), "Intersection"), (V(75, 100, 100), "Intersection"),
                                 (V(100, 100, 60), "Guide point")):
            label, point = hover(target)
            assert label == expected and close(point, target), (label, point, target)
        c.click(pos(V(75, 80, 100)))
        assert close(c.anchor, V(75, 80, 100)), c.anchor
        c.motion(pos(V(76, 50, 100)))
        assert abs(c.point.x - 75) < 1e-6 and abs(c.point.z - 100) < 1e-6, (c.controls.label.text(), c.point)
        end = V(c.point)
        c.click(pos(V(76, 50, 100)))
        c.cancel()
        ends = sorted((tuple(edge.Vertexes[0].Point), tuple(edge.Vertexes[-1].Point))
                      for obj in doc.Objects if hasattr(obj, "Shape") for edge in obj.Shape.Edges)
        assert any({V(*a).sub(V(75, 80, 100)).Length < 1e-6, V(*b).sub(end).Length < 1e-6} == {True}
                   or {V(*b).sub(V(75, 80, 100)).Length < 1e-6, V(*a).sub(end).Length < 1e-6} == {True}
                   for a, b in ends), ends
        App.Console.PrintMessage("PASS: Line snaps to guide crossings, guide points and along a guide\n")

        # Guides are not geometry: no snap target, shape or selection window includes them.
        assert not any(guides.is_guide(obj) or guides.is_group(obj) for obj in snap_targets(doc, ()))
        assert not any(hasattr(obj, "Shape") for obj in guide_objects())
        App.Console.PrintMessage("PASS: guides are ignored by the geometry tools\n")

        # A guide line can be clicked and deleted; Undo brings it back.
        guide = guide_objects()[0]
        # The view draws the guide where it runs nearer than the model, and it can
        # be clicked away from its point, over a face behind it.
        view.redraw()
        Gui.updateGui()
        camera = view.getCameraNode()
        ahead = V(*camera.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1)).getValue())
        depth = (V(75, 140, 100) - V(*camera.position.getValue().getValue())).dot(ahead)
        assert camera.nearDistance.getValue() < depth < camera.farDistance.getValue(), \
            (camera.nearDistance.getValue(), depth, camera.farDistance.getValue())
        info = view.getObjectInfo(pos(V(75, 110, 100)))
        assert info and info["Object"] == guide.Name, info
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(guide)
        keys("\x7f", start_in_view=True)
        assert guide_objects() and guide.Name not in [obj.Name for obj in guide_objects()]
        assert "Guides deleted" in Gui.getMainWindow().statusBar().currentMessage()
        doc.undo()
        assert len(guide_objects()) == 3
        App.Console.PrintMessage("PASS: a clicked guide deletes with Delete and returns with Undo\n")

        # Guides are saved with the model and look the same when it is reopened.
        doc.saveAs(reload_path)
        name = doc.Name
        App.closeDocument(name)
        doc = App.openDocument(reload_path)
        Gui.updateGui()
        reopened = guide_objects()
        assert len(reopened) == 3 and all(obj.ViewObject.Proxy is not None for obj in reopened), reopened
        assert any(abs(guides.line(obj)[0].x - 75) < 1e-6 for obj in reopened)
        view = Gui.activeDocument().activeView()
        App.Console.PrintMessage("PASS: guides are saved and reopened with the model\n")

        # Deleting the Guides group removes every guide in one Undo step.
        group = next(obj for obj in doc.Objects if guides.is_group(obj))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(group)
        c.start("Delete")
        assert not guide_objects() and not any(guides.is_group(obj) for obj in doc.Objects)
        doc.undo()
        assert len(guide_objects()) == 3
        App.Console.PrintMessage("PASS: deleting the Guides group removes all guides; Undo restores them\n")
    finally:
        c.cancel(quiet=True)
        Gui.Selection.clearSelection()
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        c.controls.plane.setCurrentText(old_plane)
        App.closeDocument(doc.Name)
        if os.path.exists(reload_path):
            os.remove(reload_path)
