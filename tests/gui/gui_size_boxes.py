"""Typing a size while drawing opens boxes in the 3D view, on the size labels."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.size_input import widget_point
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector
KEYS = {",": QtCore.Qt.Key_Comma, " ": QtCore.Qt.Key_Space, "\b": QtCore.Qt.Key_Backspace,
        "\r": QtCore.Qt.Key_Return, "\t": QtCore.Qt.Key_Tab, ".": QtCore.Qt.Key_Period}


def run(screenshot=None):
    Gui.activateWorkbench("SimpleCADWorkbench")
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument("SimpleCADSizeBoxes")
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

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def focus():
        return QtWidgets.QApplication.focusWidget()

    def keys(text, modifiers=QtCore.Qt.NoModifier, start_in_view=False):
        """Type ``text`` where the focus is, as the keyboard would."""
        if start_in_view:
            c.focus_view()
        for char in text:
            key = KEYS.get(char, getattr(QtCore.Qt, "Key_" + char.upper(), 0))
            shown = "" if char in "\b\r\t" else char
            for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(focus(), QtGui.QKeyEvent(kind, key, modifiers, shown))
        Gui.updateGui()

    def backtab():
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus(), QtGui.QKeyEvent(kind, QtCore.Qt.Key_Backtab,
                                                                       QtCore.Qt.ShiftModifier, ""))
        Gui.updateGui()

    def on_label(box, label):
        """The box is centred on the size label it replaces."""
        parent = box.parentWidget()
        x, y = widget_point(view, parent, label.spot)
        # Unless that would put part of it past the edge of the view.
        x = min(max(box.width() / 2, x), parent.width() - box.width() / 2)
        y = min(max(box.height() / 2, y), parent.height() - box.height() / 2)
        centre = box.geometry().center()
        assert abs(centre.x() - x) <= 2 and abs(centre.y() - y) <= 2, (centre, x, y)

    def save(suffix):
        if screenshot:
            Gui.updateGui()
            Gui.getMainWindow().grab().save(str(screenshot).replace(".png", suffix + ".png"))

    try:
        # Rectangle: Tab opens a width and a height box, each on its side's label.
        c.start("Rectangle")
        c.click(pos(V(10, 10, 100)))
        c.motion(pos(V(70, 50, 100)))
        count = doc.UndoCount
        keys("\t", start_in_view=True)
        boxes = c.size_input.boxes
        assert len(boxes) == 2 and focus() is boxes[0], (boxes, focus())
        viewport = view.graphicsView().viewport()
        for box, label in zip(boxes, c.preview.length_labels):
            assert box.parentWidget() is viewport and box.isVisible()
            on_label(box, label)
        assert [box.placeholderText() for box in boxes] == c.preview.label_texts()
        save("-rectangle")
        # Width, then a comma moves on to the height; Tab and Shift+Tab move between them.
        keys("40, 30")
        assert [box.text() for box in boxes] == ["40", "30"] and focus() is boxes[1], \
            ([box.text() for box in boxes], focus())
        assert c.controls.value.text() == "40, 30"
        save("-typed")
        assert [label.texts[1].string.getValues()[0] for label in c.preview.length_labels[:2]] \
            == ["40.00 mm", "30.00 mm"]
        backtab()
        assert focus() is boxes[0]
        keys("\t")
        assert focus() is boxes[1]
        keys("\t")
        assert focus() is boxes[0], "Tab stays between the two boxes"
        # Pointer motion moves the boxes with the labels; the typed sizes stay.
        c.motion(pos(V(80, 70, 100)))
        for box, label in zip(boxes, c.preview.length_labels):
            on_label(box, label)
        assert c.controls.value.text() == "40, 30" and doc.UndoCount == count
        keys("\r")
        assert c.tool is None and not c.size_input.boxes and doc.UndoCount == count + 1
        assert any(abs(face.Area - 1200) < 1e-6 for obj in doc.Objects for face in obj.Shape.Faces), \
            [face.Area for face in block.Shape.Faces]
        App.Console.PrintMessage("PASS: Rectangle Tab opens width and height boxes on its sides; Enter draws 40 x 30\n")

        # A digit typed over the view opens the boxes with that digit; Esc cancels.
        c.start("Rectangle")
        c.click(pos(V(20, 60, 100)))
        c.motion(pos(V(40, 80, 100)))
        keys("5", start_in_view=True)
        boxes = c.size_input.boxes
        assert len(boxes) == 2 and focus() is boxes[0] and boxes[0].text() == "5"
        assert c.controls.value.text() == "5"
        keys("\b")
        assert c.controls.value.text() == ""
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus(), QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape,
                                                                       QtCore.Qt.NoModifier))
        Gui.updateGui()
        assert c.tool is None and not c.size_input.boxes and doc.UndoCount == count + 1
        assert not viewport.findChildren(QtWidgets.QLineEdit, "SimpleCADSizeBox") or all(
            not box.isVisible() for box in viewport.findChildren(QtWidgets.QLineEdit, "SimpleCADSizeBox"))
        App.Console.PrintMessage("PASS: a typed digit opens the boxes with it; Esc cancels and closes them\n")

        # Line: one box on its length label; each segment of a chain starts afresh.
        c.start("Line")
        c.click(pos(V(10, 90, 100)))
        start = V(c.anchor)
        c.motion(pos(V(60, 90, 100)))
        keys("2", start_in_view=True)
        assert len(c.size_input.boxes) == 1 and focus() is c.size_input.boxes[0]
        on_label(c.size_input.boxes[0], c.preview.length_labels[0])
        keys("5\r")
        assert c.tool == "Line" and not c.size_input.boxes
        assert abs((c.anchor - start).Length - 25) < 1e-6, c.anchor
        assert not c.size_input.owns(focus())
        c.motion(pos(V(35, 60, 100)))
        keys("\t", start_in_view=True)
        assert len(c.size_input.boxes) == 1 and c.size_input.boxes[0].text() == ""
        keys("\t")
        assert focus() is c.size_input.boxes[0], "one box keeps the focus on Tab"
        c.cancel()
        assert not c.size_input.boxes
        App.Console.PrintMessage("PASS: Line opens one box on its length label; the chain closes it after each segment\n")

        # Circle: one radius box on the radius label.
        c.start("Circle")
        c.click(pos(V(50, 50, 100)))
        c.motion(pos(V(60, 50, 100)))
        keys("\t", start_in_view=True)
        assert len(c.size_input.boxes) == 1
        on_label(c.size_input.boxes[0], c.preview.length_labels[0])
        assert c.size_input.boxes[0].placeholderText().startswith("R ")
        c.cancel()
        App.Console.PrintMessage("PASS: Circle opens one radius box on its radius label\n")

        # Move has no size label: the box stands beside the pointer.
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(block)
        c.start("Move")
        c.click(pos(V(50, 50, 100)))
        c.motion(pos(V(60, 50, 100)))
        keys("\t", start_in_view=True)
        assert len(c.size_input.boxes) == 1
        assert c.size_input.boxes[0].placeholderText() == c.controls.value.placeholderText()
        box = c.size_input.boxes[0]
        x, y = widget_point(view, box.parentWidget(), c.last_pos)
        assert 0 < box.x() - x <= 20 and 0 < box.y() - y <= 20, (box.pos(), x, y)
        keys("1")
        assert c.controls.value.text() == "1"
        c.cancel()
        Gui.Selection.clearSelection()
        assert not c.size_input.boxes
        App.Console.PrintMessage("PASS: tools without a size label open one box beside the pointer\n")

        # Push/Pull follows the pointer through its own input; its box opens there too.
        c.start("PushPull")
        c.click(pos(V(30, 30, 100)))
        c.motion(pos(V(40, 30, 100)))
        keys("\t", start_in_view=True)
        assert c.push_pull_input is not None and len(c.size_input.boxes) == 1
        box = c.size_input.boxes[0]
        x, y = widget_point(view, box.parentWidget(), pos(V(40, 30, 100)))
        assert 0 < box.x() - x <= 20 and 0 < box.y() - y <= 20, (box.pos(), x, y)
        c.cancel()
        assert not c.size_input.boxes
        App.Console.PrintMessage("PASS: Push/Pull opens its box beside the pointer\n")

        # An edge-on drawing plane is a status-bar hint on each move, not a Report view error.
        reported = []
        c.report = reported.append
        try:
            c.controls.plane.setCurrentText("XY")
            view.getCameraNode().orientation.setValue(*App.Rotation(V(0, 0, 1), V(0, -1, 0)).Q)
            Gui.updateGui()
            c.start("Rectangle")
            event = coin.SoLocation2Event()
            event.setPosition(coin.SbVec2s(*pos(V(200, 50, 200))))

            class Callback:
                def getEvent(self):
                    return event

                def setHandled(self):
                    pass

            for _ in range(3):
                c.coin_event(Callback())
            status = Gui.getMainWindow().statusBar().currentMessage()
            assert "edge-on" in status and not reported, (status, reported)
        finally:
            del c.report
            c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: pointer moves over an edge-on plane show a hint, not Report view errors\n")
    finally:
        c.cancel(quiet=True)
        Gui.Selection.clearSelection()
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        c.controls.plane.setCurrentText(old_plane)
        App.closeDocument(doc.Name)
