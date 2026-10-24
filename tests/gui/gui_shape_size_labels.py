"""Rectangle, Circle, Polygon and Sphere show their sizes beside the preview."""
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
    doc = App.newDocument("SimpleCADShapeSizes")
    doc.UndoMode = 1
    op.new_shape(doc, Part.makeBox(100, 100, 100), "Block")
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0, 0, 1), V(1, 1, 1)).Q)
    view.fitAll()
    Gui.updateGui()
    old_mode = c.controls.drawing_mode.currentIndex()
    c.controls.drawing_mode.setCurrentIndex(0)
    c.controls.plane.setCurrentText("Auto")
    c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def shown():
        """(text, screen position) of each label on show, in order."""
        result = []
        for label in c.preview.length_labels:
            if label.switch.whichChild.getValue() != 0:
                continue
            texts = [text.string.getValues()[0] for text in label.texts]
            assert texts[0] == texts[1], texts
            result.append((texts[1], screen(view, V(*label.positions[1].translation.getValue()))))
        return result

    def beside(at, a, b, inside=None):
        """Centred on segment a-b, just clear of it, and not on the side of ``inside``."""
        a, b = screen(view, a), screen(view, b)
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        length = math.hypot(b[0] - a[0], b[1] - a[1])

        def across(p):
            return ((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / length
        along = ((at[0] - middle[0]) * (b[0] - a[0]) + (at[1] - middle[1]) * (b[1] - a[1])) / length
        assert abs(along) < 6 and 1 < abs(across(at)) < 60, (along, across(at))
        if inside is not None:
            assert across(at) * across(screen(view, inside)) < 0, (at, inside)

    def keys(text):
        for char in text:
            key = {" ": QtCore.Qt.Key_Space, ",": QtCore.Qt.Key_Comma, "\b": QtCore.Qt.Key_Backspace,
                   "\r": QtCore.Qt.Key_Return}.get(char, getattr(QtCore.Qt, "Key_" + char.upper(), 0))
            widget = QtWidgets.QApplication.focusWidget()
            for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(widget, QtGui.QKeyEvent(
                    kind, key, QtCore.Qt.NoModifier, "" if char in "\b\r" else char))

    def drawn():
        return [tuple(c.preview.coords.point[i].getValue()) for i in range(c.preview.coords.point.getNum())]

    def save(suffix):
        if screenshot:
            Gui.updateGui()
            width, height = view.getSize()
            view.saveImage(str(screenshot).replace(".png", suffix + ".png"), width, height, "Current")

    try:
        # Rectangle: width and height, each beside its side and outside the rectangle.
        c.start("Rectangle")
        c.click(pos(V(10, 10, 100)))
        c.motion(pos(V(70, 50, 100)))
        delta = c.point - c.anchor
        width, height = abs(delta.dot(c.plane.u)), abs(delta.dot(c.plane.v))
        assert c.controls.value.placeholderText() == "%.2f, %.2f mm" % (width, height)
        (w_text, w_at), (h_text, h_at) = shown()
        assert (w_text, h_text) == ("%.2f mm" % width, "%.2f mm" % height), (w_text, h_text)
        a = c.anchor
        b, corner = a + c.plane.u * delta.dot(c.plane.u), a + c.plane.u * delta.dot(c.plane.u) + c.plane.v * delta.dot(c.plane.v)
        beside(w_at, a, b, corner)
        beside(h_at, b, corner, a)
        save("")
        # Typed width, then height; the rectangle waits for Enter.
        count, before = doc.UndoCount, drawn()
        c.focus_view()
        keys("2")
        assert c.size_input.owns(QtWidgets.QApplication.focusWidget())  # the width box in the view
        keys("5")
        assert [text for text, _ in shown()] == ["25.00 mm", "%.2f mm" % height], shown()
        keys(", 1")
        assert [text for text, _ in shown()] == ["25.00 mm", "1.00 mm"], shown()
        keys("5")
        assert [text for text, _ in shown()] == ["25.00 mm", "15.00 mm"], shown()
        assert drawn() == before and doc.UndoCount == count
        save("-typed")
        c.motion(pos(V(60, 45, 100)))
        delta = c.point - c.anchor
        assert [text for text, _ in shown()] == ["%.2f mm" % abs(delta.dot(c.plane.u)),
                                                 "%.2f mm" % abs(delta.dot(c.plane.v))], shown()
        assert c.controls.value.text() == "25, 15"
        keys("\r")
        assert doc.UndoCount == count + 1
        assert any(abs(face.Area - 375) < 1e-6 for obj in doc.Objects for face in obj.Shape.Faces)
        App.Console.PrintMessage("PASS: Rectangle shows width and height outside its sides; typed sizes until the pointer moves\n")

        # Circle, Polygon and Sphere: the radius beside the radius line.
        for tool, center, edge, typed, label in (("Circle", V(70, 70, 100), V(90, 70, 100), "12", "R 12.00 mm"),
                                                 ("Polygon", V(30, 70, 100), V(30, 95, 100), "2 cm", "R 20.00 mm"),
                                                 ("Sphere", V(70, 30, 100), V(85, 30, 100), "7", "R 7.00 mm")):
            if tool == "Polygon":
                c.polygon_sides = 6
                c.controls.sides.setValue(6)
            c.start(tool)
            c.click(pos(center))
            c.motion(pos(edge))
            radius = (c.point - c.anchor).Length
            assert c.controls.value.placeholderText() == "Radius %.2f mm" % radius
            (text, at), = shown()
            assert text == "R %.2f mm" % radius, (tool, text)
            beside(at, c.anchor, c.point)
            if tool == "Circle":
                save("-circle")
            count, before = doc.UndoCount, drawn()
            c.focus_view()
            keys(typed[0])
            assert c.size_input.owns(QtWidgets.QApplication.focusWidget())  # the size box in the view
            keys(typed[1:])
            assert [text for text, _ in shown()] == [label], (tool, shown())
            assert drawn() == before and doc.UndoCount == count
            c.motion(pos(edge))
            assert [text for text, _ in shown()] == ["R %.2f mm" % (c.point - c.anchor).Length], shown()
            assert c.controls.value.text() == typed
            if tool == "Polygon":
                # Emptied, the field shows the live radius; unfinished text shows as typed.
                keys("\b" * 4)
                assert [text for text, _ in shown()] == ["R %.2f mm" % (c.point - c.anchor).Length], shown()
                keys("2 c")
                assert [text for text, _ in shown()] == ["R 2 c"], shown()
                keys("m")
            keys("\r")
            assert doc.UndoCount == count + 1, (tool, doc.UndoCount, count)
        App.Console.PrintMessage("PASS: Circle, Polygon and Sphere show the radius beside the radius line; typed radius until the pointer moves\n")
        # The Sphere drawn from a typed 7 mm radius, and Esc clears every label.
        sphere = doc.Objects[-1].Shape
        assert abs(sphere.Faces[0].Surface.Radius - 7) < 1e-9, sphere.Faces[0].Surface
        c.start("Circle")
        c.click(pos(V(70, 70, 100)))
        c.motion(pos(V(80, 70, 100)))
        assert shown()
        c.focus_view()
        focus = QtWidgets.QApplication.focusWidget()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier))
        assert c.tool is None and c.preview is None
        App.Console.PrintMessage("PASS: a typed Sphere radius is drawn on Enter; Esc removes the labels with the preview\n")

        # Draw: Surface on a cylinder labels the sizes along the surface.
        obj = doc.addObject("Part::Feature", "Cylinder")
        obj.Shape = Part.makeCylinder(10, 30, V(200, 0, 0))
        doc.recompute()
        view.getCameraNode().orientation.setValue(App.Rotation(V(0, 0, 1), V(1, 0, 0)).Q)
        view.fitAll()
        Gui.updateGui()
        c.controls.drawing_mode.setCurrentIndex(1)
        anchor = obj.Shape.Faces[0].valueAt(.35, 15)
        for tool in ("Rectangle", "Circle"):
            c.start(tool)
            c.click(pos(anchor))
            assert c.surface_frame is not None and c.drawing_surface[0] == obj
            c.motion(pos(c.surface_frame.point(V(3, 4, 0))))
            point = c.surface_point
            texts = [text for text, _ in shown()]
            if tool == "Rectangle":
                assert texts == ["%.2f mm" % abs(point.x), "%.2f mm" % abs(point.y)], texts
                assert c.controls.value.placeholderText() == "%.2f, %.2f mm on surface" % (abs(point.x), abs(point.y))
                c.controls.value.setText("3, 2")
                assert [text for text, _ in shown()] == ["3.00 mm", "2.00 mm"], shown()
            else:
                assert texts == ["R %.2f mm" % point.Length], texts
                c.controls.value.setText("4")
                assert [text for text, _ in shown()] == ["R 4.00 mm"], shown()
            c.controls.value.setText("")
            c.cancel(quiet=True)
        App.Console.PrintMessage("PASS: surface Rectangle and Circle label their sizes along the surface\n")
    finally:
        c.cancel(quiet=True)
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        App.closeDocument(doc.Name)
