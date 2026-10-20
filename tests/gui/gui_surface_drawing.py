"""Surface drawing through real viewport hits, controller previews and Qt input."""
import math
from unittest.mock import patch

import FreeCAD as App
import FreeCADGui as Gui
import Part

from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.surfaces.drawing import SurfaceFrame
from simplecad.surfaces.line import covered
from simplecad.gui.qt import QtCore, QtGui, QtWidgets

V = App.Vector


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance()
    c.cancel(quiet=True)
    doc = App.newDocument('SurfaceDrawingGui')
    doc.UndoMode = 1
    old_plane,old_snap = c.controls.plane.currentText(),c.controls.snap.isChecked()
    old_mode = c.controls.drawing_mode.currentIndex()
    try:
        obj = doc.addObject('Part::Feature','Cylinder')
        view = Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),V(1,0,0)).Q)
        c.controls.plane.setCurrentText('Auto')
        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(True)

        def reset():
            c.cancel(quiet=True)
            for other in list(doc.Objects):
                if other != obj:
                    doc.removeObject(other.Name)
            obj.Shape = Part.makeCylinder(10,30)
            doc.recompute()
            Gui.Selection.clearSelection()
            view.fitAll()
            Gui.updateGui()
            face = obj.Shape.Faces[0]
            return face,face.valueAt(.35,15)

        def pos(point):
            return tuple(int(round(x)) for x in screen(view,point))

        def exact(text):
            # macOS may deactivate the scratch window between native redraws.
            # Establish focus before testing the actual Tab/Return key route.
            window=Gui.getMainWindow()
            window.activateWindow()
            QtWidgets.QApplication.setActiveWindow(window)
            QtWidgets.QApplication.processEvents()
            c.focus_view()
            QtWidgets.QApplication.processEvents()
            focus = QtWidgets.QApplication.focusWidget()
            assert focus is not None
            for event in (QtCore.QEvent.ShortcutOverride,QtCore.QEvent.KeyPress):
                QtWidgets.QApplication.sendEvent(focus,QtGui.QKeyEvent(event,QtCore.Qt.Key_Tab,QtCore.Qt.NoModifier))
            assert QtWidgets.QApplication.focusWidget() == c.controls.value
            c.controls.value.setText(text)
            QtWidgets.QApplication.sendEvent(c.controls.value,QtGui.QKeyEvent(
                QtCore.QEvent.KeyPress,QtCore.Qt.Key_Return,QtCore.Qt.NoModifier))

        for tool,size in (('Rectangle','3 mm, 4 mm'),('Circle','2 mm'),('Polygon','2 mm')):
            face,anchor = reset()
            c.polygon_sides = 6
            c.controls.sides.setValue(6)
            c.start(tool)
            c.click(pos(anchor))
            assert c.surface_frame is not None and c.drawing_surface[0] == obj
            count = doc.UndoCount
            frame = c.surface_frame
            with patch.object(SurfaceFrame,'curves',side_effect=AssertionError('native curve built during motion')):
                c.motion(pos(frame.point(V(2,3,0))))
            assert 'on surface' in c.controls.value.placeholderText()
            for point in c.preview.coords.point.getValues():
                assert abs(math.hypot(point[0],point[1])-10) < 1e-5
            assert doc.UndoCount == count and len(doc.Objects) == 1
            exact(size)
            assert c.tool is None, tool
            assert obj.Shape.isValid() and obj.Shape.isClosed()
            assert len(doc.Objects) == 1 and len(obj.Shape.Faces) == 4
            region = min(obj.Shape.Faces,key=lambda f:f.Area)
            # Measure the actual outline. OCC's scalar area integration of a
            # trimmed spline can drift even on an exactly unrolled cylinder.
            if tool == 'Rectangle':
                for corner in (V(),V(3,0,0),V(3,4,0),V(0,4,0)):
                    assert min((v.Point-frame.point(corner)).Length for v in region.Vertexes)<1e-5
            else:
                points = (region.Edges[0].discretize(32) if tool == 'Circle'
                          else [v.Point for v in region.Vertexes])
                assert all(abs(frame.local(p).Length-2)<1e-5 for p in points)
            assert doc.UndoCount == count+1
            doc.undo()
            assert len(obj.Shape.Faces) == 3
            doc.redo()
            assert len(obj.Shape.Faces) == 4

        # A large typed size must not fold to the nearest periodic endpoint.
        face,anchor = reset()
        c.start('Rectangle')
        c.click(pos(anchor))
        exact('40 mm, 4 mm')
        assert c.tool is None
        assert any(abs(f.Area-160)<1e-4 for f in obj.Shape.Faces)
        face,anchor = reset()
        c.start('Circle')
        c.click(pos(anchor))
        count = doc.UndoCount
        with patch.object(c,'report') as report:
            exact('40 mm')
            assert report.call_count == 1
        assert c.tool == 'Circle' and doc.UndoCount == count and len(obj.Shape.Faces) == 3
        exact('2 mm')
        assert c.tool is None and len(obj.Shape.Faces) == 4

        for tool in ('Rectangle','Circle','Polygon','Arc','Arc2Point'):
            face,anchor = reset()
            c.start(tool)
            c.click(pos(anchor))
            count = doc.UndoCount
            root = c.preview.root
            with patch.object(c,'report') as report:
                for _ in range(20):
                    assert c.motion((4,4)) is False
                c.click((4,4))
                c.controls.value.setText('2 mm')
                c.numeric()
                c.polygon_sides_changed(6)
                report.assert_not_called()
            assert c.point is None and doc.UndoCount == count and len(doc.Objects) == 1
            c.cancel(quiet=True)
            assert view.getSceneGraph().findChild(root) == -1

        for tool in ('Arc','Arc2Point'):
            face,anchor = reset()
            c.start(tool)
            c.click(pos(anchor))
            frame = c.surface_frame
            count = doc.UndoCount
            if tool == 'Arc2Point':
                c.motion(pos(frame.point(V(0,4,0))))
            exact('2 mm' if tool == 'Arc' else '4 mm')
            assert c.arc_input.second is not None and doc.UndoCount == count
            exact('120 deg' if tool == 'Arc' else '1 mm')
            assert c.tool is None and len(doc.Objects) == 2
            edge = next(o.Shape for o in doc.Objects if o != obj)
            assert covered(face,edge)
            expected = math.tau*2/3 if tool == 'Arc' else 2.5*4*math.atan(.5)
            assert abs(edge.Length-expected)<1e-5, (tool,edge.Length,expected)
            assert doc.UndoCount == count+1
            doc.undo()
            assert len(doc.Objects) == 1
            doc.redo()
            assert len(doc.Objects) == 2

        # Explicit planes and Sphere retain their existing creation semantics.
        c.controls.drawing_mode.setCurrentIndex(0)
        for tool in ('Rectangle','Circle','Polygon','Arc','Arc2Point'):
            face,anchor = reset()
            c.controls.plane.setCurrentText('YZ')
            c.start(tool)
            c.click(pos(anchor))
            assert c.drawing_surface is None and c.surface_frame is None
            c.cancel(quiet=True)
            c.controls.plane.setCurrentText('Auto')
        face,anchor = reset()
        c.start('Sphere')
        c.click(pos(anchor))
        assert c.drawing_surface is None and c.surface_frame is None
        c.cancel(quiet=True)

        # The same toolbar inputs retain planar drawing, including both arcs.
        view.getCameraNode().orientation.setValue((0,0,0,1))
        for tool,size in (('Rectangle','3, 4'),('Circle','2'),('Polygon','2'),
                          ('Arc','2'),('Arc2Point','4')):
            c.cancel(quiet=True)
            for other in list(doc.Objects):
                if other != obj:
                    doc.removeObject(other.Name)
            obj.Shape = Part.makeBox(30,30,10)
            doc.recompute()
            view.fitAll()
            Gui.updateGui()
            c.start(tool)
            c.click(pos(V(15,15,10)))
            assert c.surface_frame is None and c.drawing_surface is None
            count = doc.UndoCount
            exact(size)
            if tool in ('Arc','Arc2Point'):
                assert doc.UndoCount == count
                exact('90 deg' if tool == 'Arc' else '1 mm')
                edge = next(o.Shape for o in doc.Objects if o != obj)
                assert isinstance(edge.Edges[0].Curve,Part.Circle)
            assert c.tool is None and doc.UndoCount == count+1
            assert obj.Shape.isValid() and obj.Shape.isClosed()
        App.Console.PrintMessage('PASS: surface Rectangle/Circle/Polygon, both arcs, preview, Qt dimensions, periodic sizes, quiet misses, Cancel, Undo/Redo and explicit planes\n')
    finally:
        c.cancel(quiet=True)
        c.controls.plane.setCurrentText(old_plane)
        c.controls.snap.setChecked(old_snap)
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        App.closeDocument(doc.Name)
