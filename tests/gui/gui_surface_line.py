"""Line uses actual curved-face view hits, continuing previews and native Undo."""
import math
from unittest.mock import patch

import FreeCAD as App
import FreeCADGui as Gui
import Part

from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen

V=App.Vector


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance()
    c.cancel(quiet=True)
    doc=App.newDocument('SurfaceLineGui')
    doc.UndoMode=1
    old_plane=c.controls.plane.currentText()
    old_snap=c.controls.snap.isChecked()
    old_mode=c.controls.drawing_mode.currentIndex()
    try:
        obj=doc.addObject('Part::Feature','Cylinder')
        obj.Shape=Part.makeCylinder(10,20)
        doc.recompute()
        view=Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),V(1,0,0)).Q)
        view.fitAll()
        Gui.updateGui()
        c.controls.plane.setCurrentText('Auto')
        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(False)

        def pos(point):
            return tuple(int(round(x)) for x in screen(view,point))

        face=next(f for f in obj.Shape.Faces if isinstance(f.Surface,Part.Cylinder))
        points=[face.valueAt(u,z) for u,z in ((-.5,5),(.5,5),(.5,15),(-.5,15))]
        c.start('Line')
        c.click(pos(points[0]))
        assert c.drawing_surface is not None
        root=c.preview.root
        count=doc.UndoCount
        c.motion(pos(points[1]))
        c.preview.show_endpoint(c.point,True)
        with patch.object(c,'report') as report:
            for _ in range(20):
                assert c.motion((4,4)) is False
            assert c.point is None
            assert c.preview.endpoint_guide.switch.whichChild.getValue()==-1
            c.click((4,4))
            c.controls.value.setText('3 mm')
            c.numeric()
            report.assert_not_called()
        assert doc.UndoCount==count and len(doc.Objects)==1
        c.controls.value.clear()
        for endpoint in points[1:]:
            c.motion(pos(endpoint))
            assert abs(math.hypot(c.point.x,c.point.y)-10)<1e-7
            assert 'on surface' in c.controls.value.placeholderText()
            c.click(pos(endpoint))
            assert c.tool=='Line' and c.drawing_surface is not None
            assert c.preview.root==root
        c.motion(pos(points[0]))
        c.click(pos(points[0]))
        assert c.tool is None  # The segment that closes the loop ends Line.
        assert len(doc.Objects)==1, len(doc.Objects)
        assert len(obj.Shape.Faces)>3
        assert obj.Shape.isValid() and obj.Shape.isClosed()
        assert abs(obj.Shape.Volume-math.pi*100*20)<1e-5
        assert doc.UndoCount==count+4
        c.cancel(quiet=True)
        doc.undo()
        assert len(doc.Objects)>1
        doc.redo()
        assert len(doc.Objects)==1

        # Typed length follows the surface and leaves the continuing tool live.
        c.controls.snap.setChecked(True)
        c.start('Line')
        c.click(pos(face.valueAt(-.3,8)))
        c.motion(pos(face.valueAt(.3,8)))
        c.controls.value.setText('3 mm')
        c.numeric()
        assert c.tool=='Line' and c.drawing_surface is not None
        assert abs(math.hypot(c.anchor.x,c.anchor.y)-10)<1e-7
        c.cancel(quiet=True)

        # An explicit workplane remains a free straight line even over a cylinder.
        c.controls.drawing_mode.setCurrentIndex(0)
        c.controls.plane.setCurrentText('YZ')
        c.start('Line')
        c.click(pos(points[0]))
        assert c.drawing_surface is None
        c.cancel(quiet=True)

        # The reported closing triangle also needs a solid with a fitted face:
        # changing its trims changes OCC's scalar volume integration slightly.
        for previous in doc.Objects:
            previous.ViewObject.Visibility=False
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.1*x*x+.065*y*y) for y in (0,5,10,15)] for x in (0,5,10,15)])
        skin=spline.toShape()
        fitted=doc.addObject('Part::Feature','FittedSolid')
        fitted.Shape=skin.extrude(V(0,0,-5))
        doc.recompute()
        face=max(fitted.Shape.Faces,key=lambda f:f.common(skin).Area)
        u0,u1,v0,v1=face.ParameterRange
        points=[face.valueAt(u0+u*(u1-u0),v0+v*(v1-v0))
                for u,v in ((.2,.3),(.4,.7),(.2,.7),(.2,.3))]
        normal=face.normalAt(u0+.3*(u1-u0),v0+.5*(v1-v0))
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),normal).Q)
        view.fitAll()
        Gui.updateGui()
        c.controls.plane.setCurrentText('Auto')
        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(False)
        c.start('Line')
        c.click(pos(points[0]))
        for endpoint in points[1:]:
            c.click(pos(endpoint))
        assert len(fitted.Shape.Faces)==7
        assert fitted.Shape.isValid() and fitted.Shape.isClosed()
        assert not [obj for obj in doc.Objects if obj!=fitted and obj.ViewObject.Visibility]
        c.cancel(quiet=True)
        App.Console.PrintMessage('PASS: curved Auto Line, seam and fitted-solid loops, quiet invalid hover, preview, typed length, Undo/Redo and explicit planes\n')
    finally:
        c.cancel(quiet=True)
        c.controls.plane.setCurrentText(old_plane)
        c.controls.snap.setChecked(old_snap)
        c.controls.drawing_mode.setCurrentIndex(old_mode)
        App.closeDocument(doc.Name)
