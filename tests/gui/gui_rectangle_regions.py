"""A rectangle drawn on a box top divides the top, in the real viewport."""
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.core import coincident as coinc, geometry as g
from simplecad.document import operations as op
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
    doc = App.newDocument('RectangleRegions')
    doc.UndoMode = 1
    old = c.controls.plane.currentText(), c.controls.snap.isChecked(), c.controls.drawing_mode.currentIndex()
    box = op.new_shape(doc, Part.makeBox(40, 30, 20), 'Box')
    view = Gui.activeDocument().activeView()
    status = Gui.getMainWindow().statusBar()

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def keypress(key, field=None):
        c.focus_view() if field is None else field.setFocus()
        focus = QtWidgets.QApplication.focusWidget()
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, Qt.NoModifier, ''))
        Gui.updateGui()

    def regions(first, second):
        expected = g.rectangle(g.Plane.named('XY', first), first, second)
        return [f for f in box.Shape.Faces if coinc.same(f, expected)]

    try:
        # Set the camera directly: viewIsometric() can animate, and a click
        # during the animation lands elsewhere.
        view.getCameraNode().orientation.setValue(App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), 'ZXY').Q)
        view.fitAll()
        Gui.updateGui()
        c.controls.plane.setCurrentText('Auto')
        c.controls.drawing_mode.setCurrentIndex(0)
        c.controls.snap.setChecked(False)

        # Auto plane, two clicks: the top is divided, no object is added, and
        # one Undo restores the plain top.
        count = doc.UndoCount
        first, second = V(10, 8, 20), V(26, 20, 20)
        c.start('Rectangle')
        c.motion(pos(first))
        c.click(pos(first))
        assert c.support == box and abs(c.anchor.z - 20) < 1e-9, (c.support, c.anchor)
        anchor = V(c.anchor)
        c.motion(pos(second))
        corner = V(c.point)
        c.click(pos(second))
        assert c.tool is None
        assert len(doc.Objects) == 1 and len(box.Shape.Faces) == 7, [o.Name for o in doc.Objects]
        assert len(regions(anchor, corner)) == 1, (anchor, corner, [f.Area for f in box.Shape.Faces])
        assert box.Shape.isValid() and abs(box.Shape.Volume - 24000) < 1e-6
        assert 'Face updated' in status.currentMessage(), status.currentMessage()
        assert doc.UndoCount == count + 1
        doc.undo()
        assert len(box.Shape.Faces) == 6 and len(doc.Objects) == 1
        print('PASS: two clicks on the box top divide it; one Undo restores it', flush=True)

        # Exact size through Tab: the region is exactly the typed rectangle.
        start = V(10, 0, 20)
        c.start('Rectangle')
        c.motion(pos(start + V(0, 2, 0)))
        c.click(pos(start + V(0, 2, 0)))
        anchor = V(c.anchor)
        keypress(Qt.Key_Tab)
        field = QtWidgets.QApplication.focusWidget()
        assert c.size_input.owns(field)  # the width box in the view
        field.insert('12, 6')  # the comma moves on to the height box
        assert c.controls.value.text() == '12, 6'
        keypress(Qt.Key_Return, field)
        assert c.tool is None
        assert len(doc.Objects) == 1 and len(box.Shape.Faces) == 7
        assert len(regions(anchor, anchor + V(12, 6, 0))) == 1, [f.Area for f in box.Shape.Faces]
        print('PASS: Tab size on the box top divides it into exactly that rectangle', flush=True)

        # Across that region: both regions are divided, and the overlap is
        # a region of its own.
        first = V(16, 5, 20)
        c.start('Rectangle')
        c.motion(pos(first))
        c.click(pos(first))
        assert c.support == box, c.support
        overlap = V(c.anchor)
        c.motion(pos(V(30, 20, 20)))
        c.click(pos(V(30, 20, 20)))
        assert c.tool is None
        assert len(doc.Objects) == 1 and len(box.Shape.Faces) == 9, [f.Area for f in box.Shape.Faces]
        expected = (anchor.x + 12 - overlap.x) * (anchor.y + 6 - overlap.y)
        assert any(abs(f.Area - expected) < 1e-6 for f in box.Shape.Faces), (expected, [f.Area for f in box.Shape.Faces])
        assert box.Shape.isValid() and abs(box.Shape.Volume - 24000) < 1e-6
        print('PASS: a rectangle across an earlier one divides both regions', flush=True)
    finally:
        c.cancel(quiet=True)
        c.controls.plane.setCurrentText(old[0])
        c.controls.snap.setChecked(old[1])
        c.controls.drawing_mode.setCurrentIndex(old[2])
        App.closeDocument(doc.Name)
