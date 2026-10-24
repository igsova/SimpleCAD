"""Arrow keys choose the drawing plane through the start point, in the real viewport."""
import math

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.core import geometry as g
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector
Qt = QtCore.Qt


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance()
    c.cancel(quiet=True)
    print('SimpleCAD', ROOT, flush=True)
    doc = App.newDocument('ArrowPlanes')
    doc.UndoMode = 1
    old = c.controls.plane.currentText(), c.controls.snap.isChecked(), c.controls.drawing_mode.currentIndex()
    box = op.new_shape(doc, Part.makeBox(20, 20, 10), 'Box')
    free_end = V(40, 30, 25)
    op.new_shape(doc, Part.makeLine(free_end, V(40, 30, 35)), 'Free line')
    view = Gui.activeDocument().activeView()
    status = Gui.getMainWindow().statusBar()
    camera = view.getCameraNode()

    def reset_view():
        camera.orientation.setValue(App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), 'ZXY').Q)
        view.fitAll()
        Gui.updateGui()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def keypress(key, field=None):
        c.focus_view() if field is None else field.setFocus()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        before = camera.position.getValue().getValue()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, Qt.NoModifier, ''))
        Gui.updateGui()
        return before != camera.position.getValue().getValue()  # FreeCAD panned the view.

    def exact(text):
        assert not keypress(Qt.Key_Tab)
        box = QtWidgets.QApplication.focusWidget()
        assert c.size_input.owns(box)  # the size box in the view
        box.insert(text)  # as typed: the boxes fill the status-bar field
        keypress(Qt.Key_Return, box)

    def corners(obj):
        return [v.Point for v in getattr(obj, 'Shape', obj).Vertexes]

    def normal_is(plane, axis):
        return abs(plane.normal.dot(axis)) > 1 - 1e-12

    def hide(*objects):
        # Each case starts on the bare box top; earlier results are not picked.
        for obj in objects:
            obj.ViewObject.Visibility = False
        Gui.updateGui()

    try:
        reset_view()
        c.controls.plane.setCurrentText('Auto')
        c.controls.drawing_mode.setCurrentIndex(0)

        # Without a drawing tool, or in another tool, the arrows stay FreeCAD's.
        assert keypress(Qt.Key_Left) and keypress(Qt.Key_Up)
        c.focus_view()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier, '')
        assert c.eventFilter(QtWidgets.QApplication.focusWidget(), event) is False
        c.start('PushPull')
        assert c.tool == 'PushPull' and keypress(Qt.Key_Right)
        assert c.plane_lock is None and c.controls.plane.currentText() == 'Auto'
        c.cancel(quiet=True)
        reset_view()
        print('PASS: arrows pan the view without a drawing tool and in Push/Pull', flush=True)

        # Before the first click: Right/Left/Up lock YZ/XZ/XY, the same arrow
        # again or Down returns to Auto, and the selector shows each choice.
        c.controls.snap.setChecked(False)
        top = V(14, 6, 10)
        c.start('Rectangle')
        c.motion(pos(top))
        for key, name in ((Qt.Key_Right, 'YZ'), (Qt.Key_Right, None), (Qt.Key_Left, 'XZ'), (Qt.Key_Up, 'XY'),
                          (Qt.Key_Down, None), (Qt.Key_Up, 'XY'), (Qt.Key_Up, None)):
            assert not keypress(key), name  # Consumed: the camera stays.
            assert c.plane_lock == name and c.controls.plane.currentText() == (name or 'Auto'), (name, c.plane_lock)
            assert (name + ' plane locked' if name else 'Auto plane') in status.currentMessage(), status.currentMessage()
            assert c.tool == 'Rectangle' and c.anchor is None
        print('PASS: arrows before the first click lock YZ/XZ/XY and toggle back to Auto', flush=True)

        # Rectangles after Right/Left/Up start on the box top and lie in
        # YZ/XZ/XY through that start; only XY lies on the top and divides it.
        count = doc.UndoCount
        cases = ((Qt.Key_Right, 'YZ', V(14, 6, 10), (V(0, 6, 0), V(0, 0, 8))),
                 (Qt.Key_Left, 'XZ', V(6, 14, 10), (V(6, 0, 0), V(0, 0, 8))),
                 (Qt.Key_Up, 'XY', V(4, 4, 10), (V(6, 0, 0), V(0, 8, 0))))
        for key, name, start, (u, v) in cases:
            c.start('Rectangle')
            c.motion(pos(start))
            keypress(key)
            c.click(pos(start))
            anchor = V(c.anchor)
            assert abs(anchor.z - 10) < 1e-9 and (anchor - start).Length < 1, anchor
            assert normal_is(c.plane, g.Plane.named(name).normal)
            assert abs((anchor - c.plane.origin).dot(c.plane.normal)) < 1e-12
            exact('6, 8')
            assert c.tool is None and c.controls.plane.currentText() == 'Auto'  # The lock ends with the drawing.
            if name == 'XY':
                rectangle = next(f for f in box.Shape.Faces if abs(f.Area - 48) < 1e-9)
                assert box.Shape.isValid() and len(box.Shape.Faces) == 7 and len(doc.Objects) == 4
            else:
                rectangle = doc.Objects[-1]
                assert rectangle.Shape.isValid() and abs(rectangle.Shape.Area - 48) < 1e-9
                assert 'SC_Support' not in rectangle.PropertiesList, name
                hide(rectangle)
            expected = [anchor, anchor + u, anchor + u + v, anchor + v]
            for point in expected:
                assert min((point - p).Length for p in corners(rectangle)) < 1e-9, (name, point, corners(rectangle))
        assert doc.UndoCount == count + 3
        doc.undo()
        assert len(doc.Objects) == 4 and len(box.Shape.Faces) == 6
        doc.redo()
        assert len(box.Shape.Faces) == 7
        doc.undo()  # The cases below start on the bare box top again.
        hide(*doc.Objects[2:])
        print('PASS: Right/Left/Up rectangles lie in YZ/XZ/XY through a start on the box top; XY divides it; one Undo each', flush=True)

        # A snapped start is a 3D target off every world plane; the lock turns
        # about it. The fixed XY/XZ/YZ selector entries keep the world origin.
        c.controls.snap.setChecked(True)
        c.start('Rectangle')
        c.motion(pos(free_end))
        keypress(Qt.Key_Right)
        c.motion(pos(free_end))
        assert c.controls.label.text() == 'Endpoint', c.controls.label.text()
        c.click(pos(free_end))
        assert (c.anchor - free_end).Length < 1e-9 and abs(c.plane.origin.x - 40) < 1e-9
        exact('5, 5')
        assert all(abs(p.x - 40) < 1e-9 for p in corners(doc.Objects[-1]))
        hide(doc.Objects[-1])
        c.controls.plane.setCurrentText('YZ')
        c.start('Rectangle')
        c.motion(pos(free_end))
        assert c.controls.label.text() != 'Endpoint'
        c.click(pos(free_end))
        assert abs(c.anchor.x) < 1e-9 and c.plane.origin.Length < 1e-12
        c.cancel(quiet=True)
        print('PASS: a locked plane starts at a snapped 3D endpoint; fixed YZ stays through the origin', flush=True)

        # Esc restores the selector's own choice; choosing in it drops a lock.
        c.start('Rectangle')
        keypress(Qt.Key_Up)
        assert c.controls.plane.currentText() == 'XY' and c.plane_lock == 'XY'
        assert not keypress(Qt.Key_Escape)
        assert c.tool is None and c.controls.plane.currentText() == 'YZ' and c.plane_lock is None
        c.start('Circle')
        keypress(Qt.Key_Left)
        c.controls.plane.setCurrentIndex(0)
        c.controls.plane.activated.emit(0)
        assert c.plane_lock is None
        c.cancel(quiet=True)
        assert c.controls.plane.currentText() == 'Auto'
        print('PASS: Esc restores a fixed selector choice; a selector choice replaces the arrow lock', flush=True)

        # During a drawing the preview turns about the first point at once.
        # Down returns to the Auto plane and its support face.
        c.controls.snap.setChecked(False)
        start, target = V(5, 5, 10), V(12, 9, 10)
        c.start('Rectangle')
        c.click(pos(start))
        anchor = V(c.anchor)
        assert normal_is(c.plane, V(0, 0, 1)) and c.support == box
        c.motion(pos(target))
        assert abs(c.point.z - 10) < 1e-9
        assert not keypress(Qt.Key_Right)
        assert normal_is(c.plane, V(1, 0, 0)) and c.support is None and c.controls.plane.currentText() == 'YZ'
        assert abs(c.point.x - anchor.x) < 1e-9 and abs(c.point.z - 10) > 1, c.point
        shown = [V(*p.getValue()) for p in c.preview.coords.point.getValues()]
        assert len(shown) == 5 and all(abs(p.x - anchor.x) < 1e-5 for p in shown), shown  # Coin floats.
        assert not keypress(Qt.Key_Down)
        assert normal_is(c.plane, V(0, 0, 1)) and c.support == box and c.controls.plane.currentText() == 'Auto'
        assert (c.point - target).Length < 1, c.point
        keypress(Qt.Key_Left)
        assert normal_is(c.plane, V(0, 1, 0)) and abs(c.point.y - anchor.y) < 1e-9
        c.motion(pos(anchor + V(7, 0, 6)))
        c.click(pos(anchor + V(7, 0, 6)))
        assert c.tool is None
        wall = doc.Objects[-1]
        assert all(abs(p.y - anchor.y) < 1e-9 for p in corners(wall)) and wall.Shape.Area > 20
        assert 'SC_Support' not in wall.PropertiesList and len(box.Shape.Faces) == 6
        hide(wall)
        print('PASS: mid-drawing arrows turn the preview about the first point; Down restores Auto and its support', flush=True)

        # In empty space a lock starts on the ground, as Auto does. Where the
        # view looks along the ground, it starts on the locked world plane.
        ground = V(-10, 40, 0)
        c.start('Rectangle')
        keypress(Qt.Key_Right)
        c.motion(pos(ground))
        c.click(pos(ground))
        assert abs(c.anchor.z) < 1e-9 and (c.anchor - ground).Length < 1 and normal_is(c.plane, V(1, 0, 0))
        assert abs(c.plane.origin.x - c.anchor.x) < 1e-12
        c.cancel(quiet=True)
        camera.orientation.setValue(App.Rotation(V(1, 0, 0), 90).Q)  # Front view, without animation.
        view.fitAll()
        Gui.updateGui()
        point = V(-30, 0, 20)
        c.start('Rectangle')
        keypress(Qt.Key_Left)
        c.motion(pos(point))
        c.click(pos(point))
        assert abs(c.anchor.y) < 1e-9 and (c.anchor - point).Length < 1 and normal_is(c.plane, V(0, 1, 0)), c.anchor
        exact('4, 3')
        assert all(abs(p.y) < 1e-9 for p in corners(doc.Objects[-1])) and abs(doc.Objects[-1].Shape.Area - 12) < 1e-9
        hide(doc.Objects[-1])
        reset_view()
        print('PASS: empty-space locks start on the ground, or on the locked world plane in a front view', flush=True)

        # Circle and Sphere follow the same lock; an arc keeps the plane of
        # its first two points.
        c.start('Circle')
        c.click(pos(start))
        center = V(c.anchor)
        assert c.support == box
        keypress(Qt.Key_Left)
        exact('3')
        disk = doc.Objects[-1]
        assert c.tool is None and abs(disk.Shape.Area - math.pi * 9) < 1e-6
        assert abs(disk.Shape.Faces[0].normalAt(0, 0).y) > 1 - 1e-9
        assert (disk.Shape.CenterOfMass - center).Length < 1e-9 and 'SC_Support' not in disk.PropertiesList
        hide(disk)
        c.start('Sphere')
        keypress(Qt.Key_Right)
        c.click(pos(start))
        assert normal_is(c.plane, V(1, 0, 0)) and c.plane_lock == 'YZ'
        c.cancel(quiet=True)
        c.start('Arc')
        c.click(pos(start))
        keypress(Qt.Key_Right)
        c.motion(pos(anchor + V(0, 0, 6)))
        c.click(pos(anchor + V(0, 0, 6)))
        assert c.arc_input.second is not None and abs(c.arc_input.second.x - anchor.x) < 1e-9
        keypress(Qt.Key_Up)
        assert c.plane_lock == 'YZ' and normal_is(c.plane, V(1, 0, 0)) and 'fix its plane' in status.currentMessage()
        c.cancel(quiet=True)
        print('PASS: Circle, Sphere and Arc use the lock; an arc keeps the plane of its first two points', flush=True)

        # Tab entry keeps its own arrow keys; Esc there still cancels.
        c.start('Rectangle')
        keypress(Qt.Key_Right)
        c.click(pos(start))
        keypress(Qt.Key_Tab)
        c.controls.value.setText('4, 5')
        c.controls.value.setCursorPosition(4)
        keypress(Qt.Key_Left, c.controls.value)
        keypress(Qt.Key_Up, c.controls.value)
        assert c.plane_lock == 'YZ' and c.controls.value.text() == '4, 5' and c.controls.value.cursorPosition() < 4
        keypress(Qt.Key_Escape, c.controls.value)
        assert c.tool is None and c.controls.plane.currentText() == 'Auto'
        print('PASS: arrows in the size field edit the text, not the plane', flush=True)

        # Line: before the first click arrows choose its plane; afterwards
        # Right/Left/Up lock X/Y/Z exactly as the letter keys do.
        c.start('Line')
        c.click(pos(start))
        anchor = V(c.anchor)
        assert c.auto_line
        for key, axis, label in ((Qt.Key_Right, V(1, 0, 0), 'X'), (Qt.Key_Left, V(0, 1, 0), 'Y'),
                                 (Qt.Key_Up, V(0, 0, 1), 'Z')):
            assert not keypress(key)
            assert c.axis == axis and c.controls.plane.currentText() == 'Auto', (label, c.axis)
            assert c.controls.label.text() == label + ' axis locked', c.controls.label.text()
        keypress(Qt.Key_Up)
        assert c.axis is None
        keypress(Qt.Key_Up)
        keypress(Qt.Key_Down)
        assert c.axis is None and 'Axis unlocked' in status.currentMessage()
        keypress(Qt.Key_Up)
        exact('5')
        assert c.tool == 'Line' and (c.anchor - (anchor + V(0, 0, 5))).Length < 1e-9
        segment = doc.Objects[-1].Shape
        assert abs(segment.Length - 5) < 1e-9
        c.cancel(quiet=True)
        c.start('Line')
        keypress(Qt.Key_Left)
        assert c.plane_lock == 'XZ'
        c.click(pos(start))
        assert not c.auto_line and normal_is(c.plane, V(0, 1, 0)) and abs(c.plane.origin.y - c.anchor.y) < 1e-12
        keypress(Qt.Key_Right)
        assert c.axis == V(1, 0, 0)
        keypress(Qt.Key_Left)  # Y is off the locked XZ plane, as with the Y key.
        assert c.axis == V(1, 0, 0) and 'drawing plane' in status.currentMessage()
        keypress(Qt.Key_Down)
        assert c.axis is None and c.plane_lock == 'XZ'
        keypress(Qt.Key_Escape)
        assert c.tool is None and c.controls.plane.currentText() == 'Auto'
        print('PASS: Line arrows choose its plane before the first click and lock X/Y/Z after it', flush=True)

        # Draw: Surface disables the plane selector; arrows explain and change nothing.
        c.controls.drawing_mode.setCurrentIndex(1)
        c.start('Rectangle')
        assert c.surface_mode and not c.controls.plane.isEnabled()
        assert not keypress(Qt.Key_Right)
        assert c.plane_lock is None and c.controls.plane.currentText() == 'Auto'
        assert 'Draw: Surface' in status.currentMessage()
        c.cancel(quiet=True)
        c.controls.drawing_mode.setCurrentIndex(0)
        print('PASS: Surface mode keeps its plane selector disabled and explains the arrows', flush=True)
    finally:
        c.cancel(quiet=True)
        c.controls.plane.setCurrentText(old[0])
        c.controls.snap.setChecked(old[1])
        c.controls.drawing_mode.setCurrentIndex(old[2])
        App.closeDocument(doc.Name)
