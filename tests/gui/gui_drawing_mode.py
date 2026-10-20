"""Explicit Plane/Surface mode, safe restarts and ambiguous boundary picks."""
from unittest.mock import patch

import FreeCAD as App
import FreeCADGui as Gui
import Part

from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.surfaces.line import same_surface

V=App.Vector


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance()
    c.cancel(quiet=True)
    doc=App.newDocument('DrawingModeGui')
    doc.UndoMode=1
    old_mode=c.controls.drawing_mode.currentIndex()
    old_plane=c.controls.plane.currentText()
    old_snap=c.controls.snap.isChecked()
    try:
        obj=doc.addObject('Part::Feature','Cylinder')
        obj.Shape=Part.makeCylinder(10,20)
        doc.recompute()
        view=Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),V(1,0,0)).Q)
        view.fitAll()
        Gui.updateGui()
        face=obj.Shape.Faces[0]
        cap=obj.Shape.Faces[1]
        def pos(point):
            return tuple(int(round(x)) for x in screen(view,point))

        assert c.controls.drawing_mode.currentIndex()==0  # New sessions default to Plane.
        c.controls.plane.setCurrentText('Auto')
        c.controls.snap.setChecked(False)
        for tool in ('Line','Rectangle','Circle','Polygon','Arc','Arc2Point'):
            c.start(tool)
            c.click(pos(face.valueAt(.2,10)))
            assert not c.surface_mode and c.drawing_surface is None and c.surface_frame is None
            assert c.controls.plane.isEnabled()
            c.cancel(quiet=True)

        # Changing mode discards only the unfinished preview, retaining planes.
        c.controls.plane.setCurrentText('XZ')
        c.start('Circle')
        count=doc.UndoCount
        root=c.preview.root
        c.controls.drawing_mode.setCurrentIndex(1)
        assert c.tool=='Circle' and c.surface_mode and c.anchor is None
        assert c.preview.root!=root and view.getSceneGraph().findChild(root)==-1
        assert c.controls.plane.currentText()=='XZ' and not c.controls.plane.isEnabled()
        assert doc.UndoCount==count and len(doc.Objects)==1
        c.click(pos(face.valueAt(.2,10)))
        assert c.drawing_surface is not None and c.surface_frame is not None
        c.controls.drawing_mode.setCurrentIndex(0)
        assert c.tool=='Circle' and c.anchor is None and not c.surface_mode
        assert c.controls.plane.currentText()=='XZ' and c.controls.plane.isEnabled()
        assert doc.UndoCount==count and len(doc.Objects)==1
        c.cancel(quiet=True)

        # An empty click in Surface mode never starts an XY drawing.
        c.controls.drawing_mode.setCurrentIndex(1)
        c.start('Line')
        with patch.object(c,'report') as report:
            assert c.motion((4,4)) is False
            c.click((4,4))
            report.assert_not_called()
        assert c.anchor is None and len(doc.Objects)==1 and doc.UndoCount==count
        c.cancel(quiet=True)

        # A selected side wall wins at its shared endpoint even when native
        # picking reports the adjacent flat cap. The completed line splits it.
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj,'Face1')
        c.controls.snap.setChecked(True)
        c.start('Line')
        assert c.surface_support is not None
        # Use a non-seam longitudinal line: exact rim-edge points, not vertices.
        start,end=face.valueAt(.4,0),face.valueAt(.4,20)
        with patch('simplecad.gui.controller.pick',return_value=(obj,obj.Shape.Faces[2],start,'Face3')):
            c.click(pos(start))
        assert c.anchor is not None and same_surface(c.drawing_surface[1],face)
        with patch('simplecad.gui.controller.pick',return_value=(obj,cap,end,'Face2')):
            c.click(pos(end))
        assert len(obj.Shape.Faces)==4 and obj.Shape.isValid() and obj.Shape.isClosed()
        assert len(doc.Objects)==1 and doc.UndoCount==count+1
        assert c.tool is None  # Dividing the wall closes a loop, which ends Line.

        # A later Line's mode change keeps that completed split and its Undo step.
        c.start('Line')
        c.controls.drawing_mode.setCurrentIndex(0)
        assert c.tool=='Line' and c.anchor is None and not c.surface_mode
        assert len(obj.Shape.Faces)==4 and doc.UndoCount==count+1
        c.cancel(quiet=True)
        doc.undo()
        assert len(obj.Shape.Faces)==3
        doc.redo()
        assert len(obj.Shape.Faces)==4

        # The fitted part's exact surface boundary can lie just outside the
        # 3D bounds used to index faces. A Line between its snapped corners
        # makes a valid split, which closes a loop and ends Line.
        from test_surface_line import fitted_boundary_face
        c.cancel(quiet=True)
        obj.Shape=fitted_boundary_face()
        assert obj.Shape.isValid()
        doc.recompute()
        face=obj.Shape.Faces[0]
        u0,u1,v0,v1=face.ParameterRange
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),face.normalAt((u0+u1)/2,(v0+v1)/2)).Q)
        view.fitAll()
        Gui.updateGui()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj,'Face1')
        c.controls.drawing_mode.setCurrentIndex(1)
        c.start('Line')
        first=face.Vertexes[0].Point
        opposite=max(face.Vertexes,key=lambda v:(v.Point-first).Length).Point
        for point in (first,opposite):
            c.motion(pos(point))
            assert c.controls.label.text()=='Endpoint'
            c.click(pos(point))
        assert obj.Shape.isValid() and len(obj.Shape.Faces)==2
        assert c.tool is None  # The division closes a loop, which ends Line.
        c.cancel(quiet=True)

        obj.Shape=Part.makeCylinder(10,20)
        face=obj.Shape.Faces[0]
        doc.recompute()
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),V(1,0,0)).Q)
        view.fitAll()
        Gui.updateGui()

        # Snap is not the surface-mode switch; it can be disabled independently.
        Gui.Selection.clearSelection()
        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(False)
        c.start('Circle')
        c.click(pos(face.valueAt(-.3,10)))
        assert c.surface_mode and c.surface_frame is not None
        c.cancel(quiet=True)
        c.start('Sphere')
        assert not c.surface_mode and not c.controls.drawing_mode.isVisible()
        assert c.controls.plane.isEnabled()
        c.cancel(quiet=True)

        # Surface mode carries over to another document. Where no shown
        # object has a face, a drawing tool starts on the plane instead of
        # waiting for a face that cannot be clicked.
        c.controls.drawing_mode.setCurrentIndex(1)
        empty=App.newDocument('DrawingModeNoFaces')
        empty.UndoMode=1
        try:
            hidden=empty.addObject('Part::Feature','Hidden')
            hidden.Shape=Part.makeBox(5,5,5,V(20,20,0))
            empty.recompute()
            hidden.ViewObject.Visibility=False
            other=Gui.activeDocument().activeView()
            other.viewIsometric()
            other.fitAll()
            Gui.updateGui()
            def at(point):
                return tuple(int(round(x)) for x in screen(other,point))
            c.controls.plane.setCurrentText('XY')
            with patch.object(c,'report') as report:
                c.start('Rectangle')
                assert c.tool=='Rectangle' and not c.surface_mode
                assert c.controls.drawing_mode.currentIndex()==0 and c.controls.plane.isEnabled()
                c.click(at(V()))
                assert c.anchor is not None and c.drawing_surface is None
                c.motion(at(V(6,4,0)))
                c.click(at(V(6,4,0)))
                report.assert_not_called()
            assert c.tool is None and len(empty.Objects)==2 and empty.UndoCount==1
            # Shown faces keep Surface mode, as in the first document.
            hidden.ViewObject.Visibility=True
            c.controls.drawing_mode.setCurrentIndex(1)
            c.start('Line')
            assert c.surface_mode and c.controls.drawing_mode.currentIndex()==1
            c.cancel(quiet=True)
        finally:
            c.cancel(quiet=True)
            App.closeDocument(empty.Name)
            App.setActiveDocument(doc.Name)
        App.Console.PrintMessage('PASS: explicit modes, default Plane, independent Snap, safe mode changes, retained planes, adjacent-cap boundary picks and Plane drawing where nothing has a face\n')
    finally:
        c.cancel(quiet=True)
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        c.controls.plane.setCurrentText(old_plane)
        c.controls.snap.setChecked(old_snap)
        App.closeDocument(doc.Name)
