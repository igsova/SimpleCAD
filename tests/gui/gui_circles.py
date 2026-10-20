"""Circle command, real viewport snaps/previews, Qt keys and Push/Pull."""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADCircleSmoke")
    doc.UndoMode = 1
    block = op.new_shape(doc, Part.makeBox(40, 30, 12), "Circle test block")
    center = V(20, 15, 12)
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue((0, 0, 0, 1))
    view.fitAll()
    Gui.updateGui()
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def keypress(key, text="", field=None):
        if field is None:
            c.focus_view()
        else:
            field.setFocus()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier, text))

    def exact(value):
        keypress(QtCore.Qt.Key_Tab)
        assert QtWidgets.QApplication.focusWidget() == c.controls.value
        c.controls.value.setText(value)
        keypress(QtCore.Qt.Key_Return, field=c.controls.value)

    assert "SimpleCAD_Circle" in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT / "Resources/icons/circle.svg")).pixmap(56, 56).isNull()
    keypress(QtCore.Qt.Key_O, "o")
    assert c.tool == "Circle"
    x, y = pos(center)
    c.motion((x + 25, y))
    assert c.controls.label.text() == "Face center"
    assert c.preview.center_guide.texts[-1].string[0] == "Center snapped"
    c.click((x + 25, y))
    assert (c.anchor - center).Length < 1e-6
    assert c.support == block
    count = doc.UndoCount
    overlay = c.preview.root
    c.motion((x + 15, y))
    assert (c.point - center).Length > .1
    assert c.controls.label.text() != "Face center"
    assert c.preview.lines.numVertices[0] > 2
    c.motion(pos(V(20, 0, 12)))
    assert c.controls.label.text() == "Midpoint"
    assert c.preview.midpoint_guide.texts[-1].string[0] == "Midpoint snapped"
    assert (c.point - V(20, 0, 12)).Length < 1e-6
    assert "Radius 15.00" in c.controls.value.placeholderText()
    assert doc.UndoCount == count and len(doc.Objects) == 1
    c.controls.snap.setChecked(False)
    c.motion(pos(V(25, 15, 12)))
    assert c.preview.center_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    assert c.preview.midpoint_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    keypress(QtCore.Qt.Key_Escape)
    assert c.tool is None and view.getSceneGraph().findChild(overlay) == -1
    assert doc.UndoCount == count and len(doc.Objects) == 1
    App.Console.PrintMessage("PASS: Circle button/icon and O key, exact center/midpoint snaps, live radius, Snap off, Escape and no preview writes\n")

    c.controls.snap.setChecked(True)
    Gui.runCommand("SimpleCAD_Circle", 0)
    assert c.tool == "Circle"
    c.click(pos(center))
    for bad in ("0", "-3", "30 deg"):
        exact(bad)
        assert c.tool == "Circle" and doc.UndoCount == count
    exact("5 mm")  # No pointer movement needed for an exact radius.
    assert c.tool is None and len(doc.Objects) == 1
    assert len(block.Shape.Faces) == 7
    circle = min(block.Shape.Faces, key=lambda face: face.Area)
    assert abs(circle.Area - math.pi * 25) < 1e-6
    assert (circle.CenterOfMass - center).Length < 1e-6
    assert len(circle.Edges) == 1 and isinstance(circle.Edges[0].Curve, Part.Circle)
    assert doc.UndoCount == count + 1
    Gui.updateGui()
    hit = pick(view, doc, pos(center), face_only=True)
    assert hit[0] == block and abs(hit[1].Area - circle.Area) < 1e-6
    c.start("PushPull")
    c.click(pos(center))
    exact("-4")
    assert c.tool is None and len(doc.Objects) == 1
    assert abs(block.Shape.Volume - (14400 - math.pi * 100)) < 1e-5
    doc.undo()
    Gui.updateGui()
    assert len(block.Shape.Faces) == 7 and abs(block.Shape.Volume - 14400) < 1e-5
    c.start("PushPull")
    c.click(pos(center))
    exact("8")
    assert abs(block.Shape.Volume - (14400 + math.pi * 200)) < 1e-5
    App.Console.PrintMessage("PASS: typed radius without pointer motion, invalid input recovery, native region picking, circular pocket/boss and one-step Undo\n")

    # A free circle on a chosen vertical plane stays on it throughout sizing.
    block.ViewObject.Visibility = False
    c.controls.plane.setCurrentText("YZ")
    c.controls.snap.setChecked(False)
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), "ZXY").Q)
    view.getCameraNode().position.setValue(0, 0, 0)
    view.getCameraNode().height = 100
    Gui.updateGui()
    c.start("Circle")
    c.click(pos(V()))
    anchor = V(c.anchor)
    c.motion(pos(V(0, 8, 6)))
    assert abs(c.point.x) < 1e-6
    radius = (c.point - anchor).Length
    assert abs(radius - 10) < .2
    c.click(pos(V(0, 8, 6)))
    assert c.tool is None
    disk = next(obj for obj in doc.Objects if obj != block)
    assert "SC_Support" not in disk.PropertiesList
    assert abs(disk.Shape.Area - math.pi * radius ** 2) < 1e-5
    assert abs(disk.Shape.CenterOfMass.x) < 1e-6
    assert isinstance(disk.Shape.Edges[0].Curve, Part.Circle)
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)
    view.fitAll()
    Gui.updateGui()
    c.start("PushPull")
    c.click(pos(disk.Shape.CenterOfMass))
    exact("2 cm")
    assert len(disk.Shape.Solids) == 1
    assert abs(disk.Shape.Volume - math.pi * radius ** 2 * 20) < 1e-4
    disk.ViewObject.Visibility = False
    block.ViewObject.Visibility = True
    view.fitAll()
    Gui.updateGui()
    App.Console.PrintMessage("PASS: mouse-sized circle on YZ, fixed plane, native analytic disk and standalone cylinder with unit-bearing length\n")

    # Auto follows an oblique face, and its plane cannot change after center.
    block.Placement = App.Placement(V(), App.Rotation(V(0, 0, 1), 20))
    view.setCameraType("Perspective")
    view.fitAll()
    Gui.updateGui()
    front = block.Placement.multVec(V(20, 0, 6))
    hit = pick(view, doc, pos(front), face_only=True)
    assert hit and hit[0] == block, hit
    c.start("Circle")
    c.click(pos(front))
    normal, anchor = V(c.plane.normal), V(c.anchor)
    assert (anchor - front).Length < 1e-6
    assert abs(normal.x) > .1 and abs(normal.y) > .1
    c.controls.plane.setCurrentText("XY")
    c.motion(pos(anchor + c.plane.u * 4))
    assert abs((c.point - anchor).dot(normal)) < 1e-6
    assert (c.point - anchor).Length > 1
    if screenshot:
        Gui.Selection.clearSelection()
        Gui.updateGui()
        view.saveImage(str(screenshot), 1100, 750, "Current")
    exact("4")
    assert len(doc.Objects) == 2
    circle = next(face for face in block.Shape.Faces if abs(face.Area - math.pi * 16) < 1e-6)
    assert abs(circle.normalAt(0, 0).dot(normal)) > .999999
    assert (circle.CenterOfMass - anchor).Length < 1e-6
    c.controls.plane.setCurrentText("Auto")
    Gui.Selection.clearSelection()
    App.Console.PrintMessage("PASS: perspective oblique-face Auto circle, captured plane, visible small-radius preview and native circular region\n")
    return doc
