"""Real viewport sphere placement, radius controls and native sphere picking."""
import math
import time
from unittest.mock import patch
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as op
from simplecad.core import geometry as geo
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
from simplecad.gui.qt import QtCore, QtGui, QtWidgets
V = App.Vector


def run(screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('SimpleCADSphereSmoke'); doc.UndoMode = 1
    block = op.new_shape(doc, Part.makeBox(40, 30, 12), 'Sphere reference')
    original = block.Shape
    center = V(20, 15, 12)
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue((0, 0, 0, 1))
    view.fitAll(); Gui.updateGui()
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)

    def pos(point):
        return tuple(int(round(value)) for value in screen(view, point))

    def keypress(key, text='', field=None):
        if field is None: c.focus_view()
        else: field.setFocus()
        focus = QtWidgets.QApplication.focusWidget()
        assert focus is not None
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(focus, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier, text))

    def exact(text):
        keypress(QtCore.Qt.Key_Tab)
        assert QtWidgets.QApplication.focusWidget() == c.controls.value
        c.controls.value.setText(text)
        keypress(QtCore.Qt.Key_Return, field=c.controls.value)

    assert 'SimpleCAD_Sphere' in Gui.listCommands()
    assert not QtGui.QIcon(str(ROOT/'Resources/icons/sphere.svg')).pixmap(56, 56).isNull()
    keypress(QtCore.Qt.Key_B, 'b'); assert c.tool == 'Sphere'
    x, y = pos(center)
    c.motion((x+20, y))
    assert c.controls.label.text() == 'Face center'
    c.click((x+20, y)); assert (c.anchor-center).Length < 1e-6 and c.support is None
    count = doc.UndoCount
    overlay = c.preview.root
    with patch.object(geo, 'sphere', side_effect=AssertionError('preview built a solid')):
        start = time.perf_counter()
        for i in range(30): c.motion((x+15+i, y+5))
        preview_ms = (time.perf_counter()-start)*1000/30
    assert len(c.preview.lines.numVertices.getValues()) == 4
    assert (c.point-center).Length > .1
    c.motion(pos(V(20, 0, 12)))
    assert c.controls.label.text() == 'Midpoint'
    assert 'Radius 15.00' in c.controls.value.placeholderText()
    assert len(doc.Objects) == 1 and doc.UndoCount == count
    keypress(QtCore.Qt.Key_Escape)
    assert c.tool is None and view.getSceneGraph().findChild(overlay) == -1
    assert doc.UndoCount == count

    Gui.runCommand('SimpleCAD_Sphere', 0); c.click(pos(center))
    for bad in ('0', '-3', '30 deg'):
        exact(bad); assert c.tool == 'Sphere' and doc.UndoCount == count
    exact('0.5 cm')
    assert c.tool is None and len(doc.Objects) == 2 and doc.UndoCount == count+1
    ball = next(o for o in doc.Objects if o != block); name = ball.Name
    assert ball.Label == 'Sphere' and 'SC_Support' not in ball.PropertiesList
    assert block.Shape.isSame(original)
    assert ball.Shape.isValid() and ball.Shape.isClosed() and len(ball.Shape.Faces) == 1
    assert abs(ball.Shape.Volume-4*math.pi*125/3) < 1e-6
    assert (ball.Shape.CenterOfMass-center).Length < 1e-6
    Gui.Selection.clearSelection(); Gui.updateGui()
    assert pick(view, doc, pos(center), face_only=True)[0] == ball
    doc.undo(); assert doc.getObject(name) is None
    doc.redo(); ball = doc.getObject(name)

    # A second sphere can start on a curved surface; it is never a support edit.
    c.controls.snap.setChecked(False)
    c.start('Sphere'); c.click(pos(center))
    assert c.support is None and c.anchor.z > center.z + 4.9
    surface_center = V(c.anchor)
    exact('2')
    small = next(o for o in doc.Objects if o not in (ball, block))
    assert (small.Shape.CenterOfMass-surface_center).Length < 1e-6
    assert abs(ball.Shape.Volume-4*math.pi*125/3) < 1e-6
    small.ViewObject.Visibility = False; ball.ViewObject.Visibility = False

    # Mouse placement and radius on a fixed vertical plane.
    block.ViewObject.Visibility = False
    c.controls.plane.setCurrentText('YZ')
    view.getCameraNode().orientation.setValue(App.Rotation(V(1,1,0), V(-1,1,2), V(1,-1,1), 'ZXY').Q)
    view.getCameraNode().position.setValue(0,0,0); view.getCameraNode().height = 100
    Gui.updateGui()
    c.start('Sphere'); c.click(pos(V()))
    anchor = V(c.anchor)
    c.motion(pos(V(0,8,6))); radius = (c.point-anchor).Length
    assert abs(c.point.x) < 1e-6 and abs(radius-10) < .2
    c.click(pos(V(0,8,6))); assert c.tool is None
    vertical = next(o for o in doc.Objects if o not in (ball, small, block))
    assert (vertical.Shape.CenterOfMass-anchor).Length < 1e-6
    assert abs(vertical.Shape.Volume-4*math.pi*radius**3/3) < 1e-5
    # An external Undo cancels a cached placement without leaving an overlay.
    vertical_name = vertical.Name
    c.start('Sphere'); c.click(pos(V())); overlay = c.preview.root
    doc.undo(); c.check_context()
    assert c.tool is None and view.getSceneGraph().findChild(overlay) == -1
    doc.redo()
    doc.getObject(vertical_name).ViewObject.Visibility = False
    block.ViewObject.Visibility = True; ball.ViewObject.Visibility = True
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)
    view.viewAxonometric(); view.fitAll(); Gui.Selection.clearSelection(); Gui.updateGui()
    c.seams.refresh()
    if screenshot: view.saveImage(str(screenshot), 1100, 750, 'Current')
    result = {'preview_ms_per_move': round(preview_ms, 2), 'sphere_volume': ball.Shape.Volume,
              'checks': 'button/B, snaps, preview, Esc, units, bad input, Undo/Redo, native pick, curved anchor, mouse radius on YZ, context cancellation'}
    App.Console.PrintMessage('PASS sphere GUI: '+str(result)+'\n')
    return result
