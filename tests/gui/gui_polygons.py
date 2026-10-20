"""Polygon command, side controls, viewport previews and native face editing."""
import math
import FreeCAD as App
import FreeCADGui as Gui
import Part
from pivy import coin
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.core import geometry as g, coincident as coinc
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('PolygonSmoke'); doc.UndoMode = 1
    host = op.new_shape(doc, Part.makeBox(60, 40, 15), 'Block')
    view = Gui.activeDocument().activeView(); view.viewTop(); view.fitAll()
    Gui.getMainWindow().activateWindow(); c.focus_view(); Gui.updateGui()
    center = V(30, 20, 15)
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)

    def flush():
        for _ in range(3): QtWidgets.QApplication.processEvents(); Gui.updateGui()

    def pos(point):
        return tuple(round(x) for x in screen(view, point))

    def key(keycode, text='', field=None):
        Gui.getMainWindow().activateWindow()
        if field is None: c.focus_view()
        else: field.setFocus()
        flush(); focus = QtWidgets.QApplication.focusWidget(); assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, keycode, QtCore.Qt.NoModifier, text))
        flush()

    def exact(text):
        key(QtCore.Qt.Key_Tab)
        assert QtWidgets.QApplication.focusWidget() == c.controls.value
        c.controls.value.setText(text); key(QtCore.Qt.Key_Return, field=c.controls.value)

    assert 'SimpleCAD_Polygon' in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT / 'Resources/icons/polygon.svg')).pixmap(56, 56).isNull()
    key(QtCore.Qt.Key_G, 'g'); assert c.tool == 'Polygon'
    assert not c.controls.sides.isHidden() and c.controls.sides.value() == 6
    before, original = doc.UndoCount, host.Shape
    x, y = pos(center); c.motion((x + 20, y))
    assert c.controls.label.text() == 'Face center'
    assert c.preview.center_guide.texts[-1].string[0] == 'Center snapped'
    c.click((x + 20, y)); assert (c.anchor - center).Length < 1e-6
    assert c.support == host
    c.controls.sides.setValue(3)  # No radius yet: no invalid preview face.
    c.motion((x + 12, y)); assert (c.point - center).Length > .1
    assert c.preview.lines.numVertices[0] == 4
    c.motion(pos(V(30, 0, 15)))
    assert c.controls.label.text() == 'Midpoint'
    assert c.preview.midpoint_guide.texts[-1].string[0] == 'Midpoint snapped'
    c.controls.snap.setChecked(False)
    c.motion(pos(center + V(5, 5, 0)))
    assert c.preview.center_guide.switch.whichChild.getValue() == coin.SO_SWITCH_NONE
    for sides in (4, 5, 8, 100, 6):
        c.controls.sides.setValue(sides)
        assert c.preview.lines.numVertices[0] == sides + 1
    assert doc.UndoCount == before and host.Shape.isSame(original) and len(doc.Objects) == 1
    if screenshots:
        flush(); c.controls.grab().save(str(ROOT.parent.parent / 'work/polygon-controls.png'))
        view.saveImage(str(ROOT.parent.parent / 'work/polygon-preview.png'), 1100, 750, 'Current')
    key(QtCore.Qt.Key_Escape, field=c.controls.sides)
    assert c.tool is None and c.controls.sides.isHidden() and doc.UndoCount == before

    # Typed side count does not commit a polygon; typed radius preserves angle.
    Gui.runCommand('SimpleCAD_Polygon'); c.controls.snap.setChecked(True)
    c.click(pos(center)); c.controls.snap.setChecked(False)
    c.motion(pos(center + V(6, 8, 0)))
    direction = g.unit(c.point - c.anchor)
    edit = c.controls.sides.findChild(QtWidgets.QLineEdit)
    edit.setText('5'); key(QtCore.Qt.Key_Return, field=c.controls.sides)
    assert c.tool == 'Polygon' and c.polygon_sides == 5
    assert c.preview.lines.numVertices[0] == 6 and doc.UndoCount == before
    for bad in ('0', '-3', '5 deg', 'nonsense'):
        exact(bad); assert c.tool == 'Polygon' and doc.UndoCount == before
    exact('5 mm'); assert c.tool is None and c.controls.sides.isHidden()
    poly = g.polygon(g.Plane.named('XY', center), center, center + direction * 5, 5)
    assert len(doc.Objects) == 1 and len(host.Shape.Faces) == 7 and doc.UndoCount == before + 1
    assert any(coinc.same(f, poly) for f in host.Shape.Faces)
    hit = pick(view, doc, pos(center), face_only=True)
    assert hit and hit[0] == host and coinc.same(hit[1], poly)
    for distance in (-2, 2):
        c.start('PushPull'); c.click(pos(center)); exact(str(distance))
        assert abs(host.Shape.Volume - (original.Volume + poly.Area * distance)) < 1e-5
        doc.undo(); flush()
    name = next('Face%d' % (i + 1) for i, f in enumerate(host.Shape.Faces) if coinc.same(f, poly))
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(host, name)
    key(QtCore.Qt.Key_Backspace)
    assert abs(host.Shape.Area - (original.Area - poly.Area)) < 1e-5 and not host.Shape.Solids
    doc.undo(); flush()
    assert len(host.Shape.Faces) == 7
    doc.undo(); flush(); assert len(host.Shape.Faces) == 6
    App.Console.PrintMessage('PASS: G/icon, side controls and live preview, exact center/midpoint snapping, numeric orientation, region picking, Push/Pull/Delete and Undo\n')

    # Free polygon on YZ uses its clicked first vertex and the captured plane.
    host.ViewObject.Visibility = False
    c.controls.plane.setCurrentText('YZ'); c.controls.snap.setChecked(False)
    view.viewIsometric(); view.getCameraNode().height = 100; flush()
    c.start('Polygon'); assert c.controls.sides.value() == 5
    c.controls.sides.setValue(7); c.click(pos(V()))
    anchor, plane = V(c.anchor), c.plane
    c.controls.plane.setCurrentText('XY')
    c.motion(pos(anchor + V(0, 8, 6))); expected = g.polygon(plane, anchor, c.point, 7)
    c.click(pos(c.point)); assert c.tool is None
    free = next(o for o in doc.Objects if o != host)
    assert len(free.Shape.Edges) == 7 and abs(free.Shape.CenterOfMass.x) < 1e-6
    assert coinc.same(free.Shape, expected) and 'SC_Support' not in free.PropertiesList
    free.ViewObject.Visibility = False; host.ViewObject.Visibility = True
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)
    view.viewTop(); view.fitAll(); flush()
    # Exact radius also works without any pointer movement.
    c.start('Polygon'); c.controls.sides.setValue(6); c.click(pos(center)); exact('3')
    assert len(host.Shape.Faces) == 7
    hexagon = next(f for f in host.Shape.Faces if len(f.Edges) == 6 and f.Area < 100)
    assert abs(hexagon.Area - 27 * math.sin(math.pi / 3)) < 1e-6
    doc.undo(); flush()
    # Partial support fails cleanly and leaves the tool editable for retry.
    c.start('Polygon'); c.click(pos(center)); exact('1000')
    assert c.tool == 'Polygon' and len(host.Shape.Faces) == 6
    exact('4'); assert c.tool is None and len(host.Shape.Faces) == 7
    doc.undo(); flush()
    # Tool/Undo/document/workbench exits remove the side control and preview.
    c.start('Polygon'); c.click(pos(center)); c.start('Circle'); assert c.controls.sides.isHidden()
    c.cancel(quiet=True)
    c.start('Polygon'); doc.undo(); c.check_context(); assert c.tool is None
    doc.redo(); flush()
    c.start('Polygon'); other = App.newDocument('PolygonOther'); c.check_context()
    assert c.tool is None and c.controls.sides.isHidden()
    App.closeDocument(other.Name); App.setActiveDocument(doc.Name)
    c.start('Polygon'); Gui.activateWorkbench('PartWorkbench'); assert not c.active and c.tool is None
    Gui.activateWorkbench('SimpleCADWorkbench'); assert c.controls.sides.value() == 6 and c.controls.sides.isHidden()
    App.Console.PrintMessage('PASS: standalone YZ polygon, captured plane, exact radius without motion, containment rejection/recovery, and tool/Undo/document/workbench cleanup\n')
    return doc
