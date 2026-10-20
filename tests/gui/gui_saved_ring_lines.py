"""Optional saved-model regression; opens in an isolated GUI, never saves it.

Expects the rectangular rim and its first loose corner bridge from the report.
"""
import time
import FreeCAD as App
import FreeCADGui as Gui
from simplecad.document import appearance
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick


def run(model_path, screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.openDocument(str(model_path)); doc.UndoMode = 1
    obj = doc.getObject('SimpleShape')
    line = doc.getObject('SimpleShape002')
    assert obj and line and not line.Shape.Faces
    endpoints = [v.Point for v in line.Shape.Vertexes]
    face = next(f for f in obj.Shape.Faces if len(f.Wires) == 2
                and all(f.distToShape(v)[0] < 1e-6 for v in line.Shape.Vertexes))
    original = obj.Shape
    count = len(doc.Objects)
    styles = appearance.fingerprint(obj.ViewObject.ShapeAppearance, precision=6)
    unchanged = [(o, o.Shape.exportBrepToString(),
                  appearance.fingerprint(o.ViewObject.ShapeAppearance, precision=6))
                 for o in doc.Objects if o not in (obj, line) and hasattr(o, 'Shape')]
    outer = [v.Point for v in face.OuterWire.OrderedVertexes]
    inner = [v.Point for w in face.Wires if not w.isSame(face.OuterWire) for v in w.OrderedVertexes]
    nearest = min(range(len(outer)), key=lambda i:min((outer[i]-p).Length for p in endpoints))
    a = outer[(nearest+1) % len(outer)]
    b = min(inner, key=lambda p:(p-a).Length)
    view = Gui.activeDocument().activeView()
    from simplecad.gui.qt import QtWidgets
    try:
        from PySide import QtTest
    except ImportError:
        from PySide6 import QtTest
    QtTest.QTest.qWait(700)
    QtWidgets.QApplication.processEvents()
    # Keep front/back corner projections distinct, as in the reported view.
    view.getCameraNode().orientation.setValue(*App.Rotation(
        App.Vector(1,1,0), App.Vector(-1,1,2), App.Vector(1,-1,1), 'ZXY').Q)
    view.fitAll(); Gui.updateGui()
    c.controls.plane.setCurrentText('Auto'); c.controls.snap.setChecked(True)
    def pos(point): return tuple(round(v) for v in screen(view, point))
    c.start('Line'); c.motion(pos(a)); c.click(pos(a))
    assert (c.anchor-a).Length < 1e-6, (c.anchor,a,pos(a),view.getSize())
    c.motion(pos(b)); assert (c.point-b).Length < 1e-6
    start = time.perf_counter(); c.click(pos(b))
    elapsed = round((time.perf_counter()-start)*1000, 1)
    assert c.tool == 'Line'
    c.cancel(quiet=True)
    assert len(obj.Shape.Faces) == len(original.Faces)+1
    assert len(doc.Objects) == count-1
    assert obj.Shape.isValid() and obj.Shape.isClosed()
    assert abs(obj.Shape.Volume-original.Volume) < 1e-6
    assert abs(obj.Shape.Area-original.Area) < 1e-6
    regions = [(i,f) for i,f in enumerate(obj.Shape.Faces,1)
               if abs(f.CenterOfMass.z-face.CenterOfMass.z) < 1e-6]
    assert len(regions) == 2
    Gui.updateGui(); view.redraw()
    for i, region in regions:
        points, triangles = region.tessellate(.1)
        largest = max(triangles, key=lambda tri:(points[tri[1]]-points[tri[0]]).cross(points[tri[2]]-points[tri[0]]).Length)
        sample = sum((points[j] for j in largest), App.Vector()) / 3
        hit = pick(view, doc, pos(sample), face_only=True)
        assert hit and hit[0] == obj and hit[3] == 'Face'+str(i), hit
    for other, brep, style in unchanged:
        assert other.Shape.exportBrepToString() == brep
        assert appearance.fingerprint(other.ViewObject.ShapeAppearance, precision=6) == style
    doc.undo()
    assert len(obj.Shape.Faces) == len(original.Faces) and len(doc.Objects) == count
    assert appearance.fingerprint(obj.ViewObject.ShapeAppearance, precision=6) == styles
    doc.redo()
    assert len(obj.Shape.Faces) == len(original.Faces)+1 and len(doc.Objects) == count-1
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(obj, 'Face'+str(min(regions,key=lambda pair:pair[1].Area)[0]))
    Gui.updateGui(); view.redraw()
    if screenshot:
        view.saveImage(str(screenshot), 1280, 900, 'Current')
    return {'result':'PASS', 'controller_commit_ms':elapsed,
            'regions':['Face'+str(i) for i,_ in regions],
            'checks':'two native selectable regions, original line consumed, valid closed solid, volume/area, materials, Undo/Redo'}
