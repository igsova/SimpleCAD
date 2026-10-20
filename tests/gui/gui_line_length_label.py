"""Line shows its length beside the midpoint of the segment being drawn."""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADLineLength")
    doc.UndoMode = 1
    op.new_shape(doc, Part.makeBox(100, 100, 100), "Block")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0, 0, 1), V(1, 1, 1)).Q)
    view.fitAll()
    Gui.updateGui()
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def enter(text):
        c.controls.value.setText(text)
        c.controls.value.setFocus()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(c.controls.value, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier))

    def shown():
        label = c.preview.length_labels[0]
        if label.switch.whichChild.getValue() != 0:
            return None
        texts = [text.string.getValues()[0] for text in label.texts]
        assert texts[0] == texts[1], texts
        return texts[1], V(*label.positions[1].translation.getValue())

    c.start("Line")
    c.click(pos(V(0, 0, 100)))
    # Off the block in the air, across the top face, and down its side.
    for target in (V(-70, 0, 100), V(60, 45, 100), V(0, 0, 40)):
        c.motion(pos(target))
        expected = "%.2f mm" % (c.point - c.anchor).Length
        assert c.controls.value.placeholderText() == expected, c.controls.value.placeholderText()
        text, at = shown()
        assert text == expected, (text, expected)
        # Centred on the midpoint, just clear of the line.
        a, b = screen(view, c.anchor), screen(view, c.point)
        middle = screen(view, (c.anchor + c.point) / 2)
        x, y = screen(view, at)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        across = ((x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])) / length
        along = ((x - middle[0]) * (b[0] - a[0]) + (y - middle[1]) * (b[1] - a[1])) / length
        assert abs(along) < 6 and 1 < abs(across) < 60, (target, along, across)
        if screenshot and target.x < 0:
            Gui.updateGui()
            width, height = view.getSize()
            view.saveImage(str(screenshot), width, height, "Current")
    App.Console.PrintMessage("PASS: the length beside the line matches the typed-length field and follows its midpoint\n")

    count = doc.UndoCount
    c.motion(pos(V(-70, 0, 100)))
    enter("25")
    assert c.tool == "Line" and doc.UndoCount == count + 1
    assert (c.anchor - V(-25, 0, 100)).Length < 1e-6, c.anchor
    c.motion(pos(V(-25, -60, 100)))
    text, at = shown()
    assert text == "%.2f mm" % (c.point - c.anchor).Length
    App.Console.PrintMessage("PASS: after a typed length the label measures the next segment\n")

    def keys(text, widget):
        for char in text:
            key = {" ": QtCore.Qt.Key_Space, "\b": QtCore.Qt.Key_Backspace, "\r": QtCore.Qt.Key_Return}.get(
                char, getattr(QtCore.Qt, "Key_" + char.upper(), 0))
            for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(widget(), QtGui.QKeyEvent(
                    kind, key, QtCore.Qt.NoModifier, "" if char in "\b\r" else char))

    # A digit typed over the view starts the field; the label shows the
    # typed length while the line keeps its own until Enter.
    start, drawn, live = V(c.anchor), V(c.point), c.controls.value.placeholderText()
    c.focus_view()
    keys("8", QtWidgets.QApplication.focusWidget)
    assert QtWidgets.QApplication.focusWidget() == c.controls.value
    keys("0", lambda: c.controls.value)
    assert c.controls.value.text() == "80" and shown()[0] == "80.00 mm", shown()
    assert (c.point - drawn).Length < 1e-9 and c.controls.value.placeholderText() == live
    assert doc.UndoCount == count + 1
    if screenshot:
        Gui.updateGui()
        width, height = view.getSize()
        view.saveImage(str(screenshot).replace(".png", "-typed.png"), width, height, "Current")
    # Moving the pointer shows the line's own length; the field keeps 80.
    c.motion(pos(V(-25, -50, 100)))
    text, _ = shown()
    assert text == c.controls.value.placeholderText() != "80.00 mm", text
    assert c.controls.value.text() == "80"
    # Units, unfinished text and an emptied field.
    keys(" c", lambda: c.controls.value)
    assert shown()[0] == "80 c", shown()
    keys("m", lambda: c.controls.value)
    assert shown()[0] == "800.00 mm", shown()
    keys("\b" * 5, lambda: c.controls.value)
    assert c.controls.value.text() == "" and shown()[0] == c.controls.value.placeholderText()
    keys("40\r", lambda: c.controls.value)
    assert c.tool == "Line" and doc.UndoCount == count + 2
    assert abs((c.anchor - start).Length - 40) < 1e-6, c.anchor
    App.Console.PrintMessage("PASS: typed lengths show beside the line until the pointer moves; Enter draws them\n")

    c.controls.value.clearFocus()
    c.focus_view()
    focus = QtWidgets.QApplication.focusWidget()
    for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
    assert c.tool is None and c.preview is None
    App.Console.PrintMessage("PASS: Esc removes the label with the preview\n")
    App.closeDocument(doc.Name)
