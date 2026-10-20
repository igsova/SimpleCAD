"""Continuous Line, world axes, typed lengths, native keys and changing faces."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.previews.overlay import AXIS_COLORS, LINE_COLOR
from simplecad.gui.snapping import screen, pick, screen_distance
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADContinuousAxesSmoke")
    doc.UndoMode = 1
    op.new_shape(doc, Part.Vertex(V()), "Start point")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.fitAll()
    view.getCameraNode().height = 160
    Gui.updateGui()
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def near_axis(target):
        x, y = pos(target)
        ax, ay = pos(c.anchor)
        length = screen_distance((x, y), (ax, ay))
        return (x - round((y - ay) * 4 / length), y + round((x - ax) * 4 / length))

    def keypress(key, text="", field=None):
        if field is None:
            c.focus_view()
        else:
            field.setFocus()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            event = QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier, text)
            QtWidgets.QApplication.sendEvent(focus, event)

    def color_is(expected):
        actual = c.preview.color.rgb[0].getValue()
        assert all(abs(a - b) < 1e-6 for a, b in zip(actual, expected)), actual

    c.start("Line")
    c.click(pos(V()))
    assert c.anchor.Length < 1e-6
    root, callback = c.preview.root, c.callback
    nodes = view.getSceneGraph().getNumChildren()
    count = doc.UndoCount
    for name, delta in (("X", V(25, 0, 0)), ("Y", V(0, 30, 0)),
                        ("Z", V(0, 0, 20)), ("X", V(-20, 0, 0))):
        before = V(c.anchor)
        target = near_axis(before + delta)
        c.motion(target)
        assert c.controls.label.text() == name + " axis", c.controls.label.text()
        color_is(AXIS_COLORS[name])
        end = V(c.point)
        assert (end - before).cross(delta).Length < 1e-6
        assert (end - before).dot(delta) > 0
        if screenshot and name == "Z":
            Gui.updateGui()
            view.saveImage(str(screenshot), 1100, 750, "Current")
        c.click(target)
        count += 1
        assert c.tool == "Line" and (c.anchor - end).Length < 1e-4, (name, c.tool, c.anchor, end)
        assert c.preview.root == root and c.callback == callback
        assert view.getSceneGraph().getNumChildren() == nodes
        assert doc.UndoCount == count
        assert any((point - c.anchor).Length < 1e-6 for point, _ in c.snapper.points)
        assert not Gui.Selection.getSelection()
    App.Console.PrintMessage("PASS: continuous X/Y/Z/-X segments, colored axis previews, one Undo per segment, refreshed snaps and one persistent overlay/callback\n")

    view.setCameraType("Perspective")
    view.fitAll()
    Gui.updateGui()
    c.motion(near_axis(c.anchor + V(0, 0, 15)))
    assert c.controls.label.text() == "Z axis"
    color_is(AXIS_COLORS["Z"])
    assert (c.point - c.anchor).cross(V(0, 0, 1)).Length < 1e-6
    App.Console.PrintMessage("PASS: native perspective view keeps an exact Z-aligned preview\n")

    # Pressing Enter in the measurement field commits in the current direction
    # and puts keyboard focus back into the continuing line session.
    before = V(c.anchor)
    c.motion(near_axis(before - V(0, 20, 0)))
    c.controls.value.setText("12")
    keypress(QtCore.Qt.Key_Return, field=c.controls.value)
    assert c.tool == "Line" and (c.anchor - (before - V(0, 12, 0))).Length < 1e-6
    assert c.controls.value.text() == ""
    assert QtWidgets.QApplication.focusWidget() != c.controls.value
    before = V(c.anchor)
    c.motion(near_axis(before - V(30, 0, 0)))
    keypress(QtCore.Qt.Key_X, "x")
    assert c.controls.label.text() == "X axis locked"
    c.controls.value.setText("1 cm")
    keypress(QtCore.Qt.Key_Return, field=c.controls.value)
    assert c.tool == "Line" and (c.anchor - (before - V(10, 0, 0))).Length < 1e-6
    assert c.axis is None  # The next segment starts without a forced axis.
    count = doc.UndoCount
    c.click(pos(c.anchor))
    assert doc.UndoCount == count  # Repeated endpoint click creates no tiny line.
    App.Console.PrintMessage("PASS: typed lengths and negative-direction axis lock continue the chain; repeat click is harmless\n")

    c.controls.snap.setChecked(False)
    c.motion(near_axis(c.anchor + V(0, 0, 30)))
    assert c.controls.label.text() == "Plane"
    color_is(LINE_COLOR)
    c.controls.snap.setChecked(True)
    c.motion(near_axis(c.anchor + V(0, 0, 30)))
    assert c.controls.label.text() == "Z axis"
    keypress(QtCore.Qt.Key_Escape)
    assert c.tool is None and c.preview is None and c.callback is None
    assert view.getSceneGraph().findChild(root) == -1
    assert doc.UndoCount == count and len(doc.Objects) == 7
    doc.undo()
    assert len(doc.Objects) == 6
    doc.redo()
    assert len(doc.Objects) == 7
    c.start("Line")
    c.click(pos(V()))
    doc.undo()
    c.check_context()
    assert c.tool is None  # Toolbar/menu Undo also invalidates the snapshot.
    doc.redo()
    App.Console.PrintMessage("PASS: Snap switch, Esc preserves committed lines, Undo/Redo per segment, menu Undo ends stale sessions\n")
    App.closeDocument(doc.Name)

    doc = App.newDocument("SimpleCADContinuousRegionsSmoke")
    doc.UndoMode = 1
    obj = op.new_shape(doc, Part.makeBox(40, 30, 10), "Continuous face regions")
    view = Gui.activeDocument().activeView()
    # Tilted, so the top corners do not sit on the bottom ones on screen.
    view.getCameraNode().orientation.setValue(App.Rotation(V(1, 0, 0), 25).Q)
    view.fitAll()
    Gui.updateGui()
    a, center, b, d, e = V(0, 0, 10), V(20, 15, 10), V(40, 0, 10), V(0, 30, 10), V(40, 30, 10)
    c.start("Line")
    c.click(pos(a))
    root, callback = c.preview.root, c.callback
    c.click(pos(center))
    assert c.tool == "Line" and len(doc.Objects) == 2 and len(obj.Shape.Faces) == 6
    # Closing a loop into a face ends the chain, as in SketchUp.
    c.click(pos(b))
    assert c.tool is None and c.preview is None and len(doc.Objects) == 1 and len(obj.Shape.Faces) == 7
    assert view.getSceneGraph().findChild(root) == -1
    assert "Loop closed" in Gui.getMainWindow().statusBar().currentMessage()
    c.start("Line")
    c.click(pos(b))
    c.click(pos(d))  # A later Line divides the refreshed topology.
    assert c.tool is None and len(obj.Shape.Faces) == 8
    c.start("Line")
    c.click(pos(d))
    count = doc.UndoCount
    c.click(pos(center))  # Retracing an existing boundary adds no Undo step and continues.
    assert c.tool == "Line" and doc.UndoCount == count and (c.anchor - center).Length < 1e-6
    assert all(any(f.isSame(current) for current in obj.Shape.Faces) for f in c.line_faces)
    c.click(pos(e))
    assert c.tool is None and len(obj.Shape.Faces) == 9
    top = [f for f in obj.Shape.Faces if abs(f.CenterOfMass.z - 10) < 1e-6]
    assert len(top) == 4 and all(abs(f.Area - 300) < 1e-6 for f in top)
    selected = top[0].CenterOfMass
    hit = pick(view, doc, pos(selected), face_only=True)
    assert hit and abs(hit[1].Area - 300) < 1e-6
    c.start("PushPull")
    c.click(pos(selected))
    c.controls.value.setText("3")
    c.numeric()
    assert c.tool is None and abs(obj.Shape.Volume - 12900) < 1e-6
    doc.undo()
    assert len(obj.Shape.Faces) == 9
    Gui.updateGui()
    App.Console.PrintMessage("PASS: corner-center-corner path divides a face and ends Line; later Lines divide refreshed topology; retracing continues; independent region picking and Push/Pull\n")

    # A fixed drawing plane cannot be escaped through an axis shortcut.
    c.controls.plane.setCurrentText("XY")
    c.start("Line")
    c.click(pos(V(-20, -20, 0)))
    keypress(QtCore.Qt.Key_Z, "z")
    assert c.axis is None
    keypress(QtCore.Qt.Key_X, "x")
    assert c.axis == V(1, 0, 0)
    keypress(QtCore.Qt.Key_X, "x")
    assert c.axis is None
    c.cancel(quiet=True)
    c.controls.plane.setCurrentText("Auto")
    c.start("Line")
    # Use the new interior vertex: outer front/back corners overlap in top
    # view, which is an existing snap-occlusion limitation.
    c.click(pos(center))
    assert (c.anchor - center).Length < 1e-6, (c.anchor, center)
    keypress(QtCore.Qt.Key_Z, "z")  # Z points at the camera in this top view.
    c.controls.value.setText("5")
    keypress(QtCore.Qt.Key_Return, field=c.controls.value)
    assert c.tool == "Line" and (c.anchor - (center + V(0, 0, 5))).Length < 1e-6, (c.tool, c.anchor, c.controls.label.text())
    c.cancel(quiet=True)
    doc.undo()
    Gui.Selection.clearSelection()
    App.Console.PrintMessage("PASS: fixed-plane axis filtering, lock toggle, view-parallel Z lock with typed length\n")
    return doc
