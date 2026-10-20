"""Drawing at free line vertices above XY, through the real viewport/controller."""
import math
import time

import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick

V = App.Vector


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument('DrawingStartSnaps')
    doc.UndoMode = 1
    top, corner, end = V(0, 0, 60), V(0, 0, 20), V(35, 0, 20)
    op.new_shape(doc, g.circle(g.Plane.named('XY', top), top, 12), 'Upper circle')
    op.new_shape(doc, Part.makeLine(top, corner), 'Vertical line')
    op.new_shape(doc, Part.makeLine(corner, end), 'Horizontal line')
    view = Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(
        App.Rotation(V(1, 1, 0), V(-1, 1, 2), V(1, -1, 1), 'ZXY').Q)
    view.fitAll()
    Gui.updateGui()
    c.controls.plane.setCurrentText('Auto')
    c.controls.snap.setChecked(True)

    def pos(point, dx=0, dy=0):
        x, y = screen(view, point)
        return int(round(x + dx)), int(round(y + dy))

    # Deliberately miss the thin line by several pixels: use the snap radius,
    # not a native vertex pick. Preview and click must agree in world space.
    count = doc.UndoCount
    elapsed = []
    for tool in ('Circle', 'Rectangle', 'Polygon', 'Arc', 'Arc2Point', 'Sphere', 'Line'):
        c.start(tool)
        target = pos(corner, -12, -6)
        start = time.perf_counter()
        c.motion(target)
        elapsed.append(time.perf_counter() - start)
        assert c.controls.label.text() == 'Endpoint', (tool, c.controls.label.text())
        marker = V(*c.preview.marker_coords.point[0].getValue())
        assert (marker - corner).Length < 1e-5, (tool, marker)
        c.click(target)
        assert (c.anchor - corner).Length < 1e-7, (tool, c.anchor)
        assert abs((corner - c.plane.origin).dot(c.plane.normal)) < 1e-7
        assert c.support is None
        c.cancel(quiet=True)
    assert doc.UndoCount == count

    # Commit a circle at the junction. Its radius snaps to the free line's
    # midpoint on the new plane, while the upper endpoint must stay off-plane.
    c.start('Circle')
    c.click(pos(corner, -12, -6))
    c.motion(pos((corner + end) / 2, 9, 4))
    assert c.controls.label.text() == 'Midpoint', c.controls.label.text()
    assert abs((c.point - corner).Length - 17.5) < 1e-7
    c.motion(pos(top))
    assert abs(c.point.z - corner.z) < 1e-7, c.point
    c.click(pos((corner + end) / 2, 9, 4))
    assert c.tool is None and len(doc.Objects) == 4
    disk = doc.Objects[-1]
    assert disk.Shape.isValid()
    assert (disk.Shape.CenterOfMass - corner).Length < 1e-7
    assert abs(disk.Shape.Area - math.pi * 17.5**2) < 1e-6
    assert doc.UndoCount == count + 1
    doc.undo()
    assert len(doc.Objects) == 3
    doc.redo()
    assert len(doc.Objects) == 4
    doc.undo()

    # Free midpoints are also valid starts at their exact 3D position.
    midpoint = (corner + end) / 2
    c.start('Circle')
    c.motion(pos(midpoint, 10, 5))
    assert c.controls.label.text() == 'Midpoint'
    c.click(pos(midpoint, 10, 5))
    assert (c.anchor - midpoint).Length < 1e-7
    c.cancel(quiet=True)

    # Explicit workplanes and Snap off retain their existing restrictions.
    for plane, enabled in (('XY', True), ('Auto', False)):
        c.controls.plane.setCurrentText(plane)
        c.controls.snap.setChecked(enabled)
        c.start('Circle')
        c.motion(pos(corner, -12, -6))
        assert c.controls.label.text() != 'Endpoint'
        c.click(pos(corner, -12, -6))
        assert abs(c.anchor.z) < 1e-7
        c.cancel(quiet=True)
    c.controls.plane.setCurrentText('Auto')
    c.controls.snap.setChecked(True)
    # A background face under a floating vertex must not become the support
    # of the new circle. Otherwise commit rejects the correctly snapped plane.
    floor = op.new_shape(doc, Part.makePlane(250, 250, V(-125, -125, 0)), 'Background')
    Gui.updateGui()
    target = pos(corner, -12, -6)
    hit = pick(view, doc, target, face_only=True)
    assert hit and hit[0] == floor, hit
    c.start('Circle')
    c.motion(target)
    c.click(target)
    assert (c.anchor - corner).Length < 1e-7
    assert c.support is None
    c.controls.value.setText('5 mm')
    c.numeric()
    assert c.tool is None
    assert (doc.Objects[-1].Shape.CenterOfMass - corner).Length < 1e-7
    assert len(floor.Shape.Faces) == 1
    print('PASS: free 3D endpoints for seven drawing tools; circle midpoint sizing, '
          'fixed radius plane, exact geometry, Undo/Redo, Snap off, explicit XY and background support; '
          'max start preview %.2f ms' % (max(elapsed) * 1000), flush=True)
    return doc
