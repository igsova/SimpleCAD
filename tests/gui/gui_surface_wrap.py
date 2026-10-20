"""Real viewport picks across faces, orbiting a Line chain and wrapped profiles."""
import time
from unittest.mock import patch

import FreeCAD as App
import FreeCADGui as Gui
import Part

from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen
from simplecad.surfaces.line import covered, preserves_volume
from simplecad.surfaces.wrap import WrapFrame
from surface_fixtures import fitted_surface_loop

V=App.Vector


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance(); c.cancel(quiet=True)
    doc=App.newDocument('SurfaceWrapGui'); doc.UndoMode=1
    obj=doc.addObject('Part::Feature','Box')
    old=(c.controls.drawing_mode.currentIndex(),c.controls.plane.currentText(),c.controls.snap.isChecked())
    view=Gui.activeDocument().activeView()

    def position(p):
        return tuple(int(round(x)) for x in screen(view,p))

    def camera(normal):
        view.getCameraNode().orientation.setValue(App.Rotation(V(0,0,1),normal).Q)
        view.fitAll(); Gui.updateGui()

    def reset():
        c.cancel(quiet=True)
        for other in list(doc.Objects):
            if other!=obj:
                doc.removeObject(other.Name)
        obj.Shape=Part.makeBox(20,20,20,V(-10,-10,-10))
        doc.recompute(); Gui.Selection.clearSelection()
        c.controls.drawing_mode.setCurrentIndex(1)
        c.controls.snap.setChecked(False)
        camera(V(1,1,.35))

    try:
        reset()
        count=doc.UndoCount
        c.start('Line'); c.click(position(V(10,0,0)))
        root=c.preview.root
        with patch.object(WrapFrame,'curves',side_effect=AssertionError('saved curve built during hover')):
            c.motion(position(V(0,10,0)))
        assert c.point is not None and c.surface_point.Length>15
        skin=c.surface_skin
        c.click(position(V(0,10,0)))
        assert c.tool=='Line' and c.preview.root==root
        # The open segment left the box unchanged, so its skin carries on.
        assert c.surface_skin is skin and skin.shape.isEqual(obj.Shape)
        curve=next(o.Shape for o in doc.Objects if o!=obj)
        assert len(curve.Edges)>=2 and covered(obj.Shape,curve)
        assert doc.UndoCount==count+1
        # Orbit while the same chain is live and continue onto the back wall.
        camera(V(-1,1,.35))
        c.click(position(V(-10,0,0)))
        assert c.tool=='Line' and c.preview.root==root
        assert doc.UndoCount==count+2
        assert obj.Shape.isValid() and obj.Shape.isClosed()
        assert preserves_volume(Part.makeBox(20,20,20,V(-10,-10,-10)),obj.Shape)
        c.cancel(quiet=True)

        reset()
        c.start('Line'); c.click(position(V(10,0,0)))
        start=V(c.anchor); count=doc.UndoCount
        c.motion(position(V(0,10,0)))
        c.controls.value.setText('-3 mm'); c.numeric()
        assert c.tool=='Line' and c.anchor.y<start.y
        assert abs((c.anchor-start).Length-3)<1e-6
        assert doc.UndoCount==count+1
        c.cancel(quiet=True)

        for tool,size in (('Circle','4 mm'),('Rectangle','5 mm, 4 mm'),('Polygon','4 mm')):
            reset()
            count=doc.UndoCount
            c.start(tool); c.click(position(V(10,8,0)))
            assert c.surface_frame is not None
            c.motion(position(V(8,10,2)))
            assert c.point is not None
            c.controls.value.setText(size); c.numeric()
            assert c.tool is None, tool
            assert len(doc.Objects)==1 and len(obj.Shape.Faces)>6
            assert obj.Shape.isValid() and obj.Shape.isClosed()
            assert preserves_volume(Part.makeBox(20,20,20,V(-10,-10,-10)),obj.Shape)
            assert doc.UndoCount==count+1
            doc.undo(); assert len(obj.Shape.Faces)==6
            doc.redo(); assert len(obj.Shape.Faces)>6

        for tool in ('Arc','Arc2Point'):
            reset()
            c.start(tool); c.click(position(V(10,8,0)))
            count=doc.UndoCount
            c.motion(position(V(8,10,2)))
            c.controls.value.setText('4 mm'); c.numeric()
            assert c.arc_input.second is not None
            c.controls.value.setText('150 deg' if tool=='Arc' else '1 mm'); c.numeric()
            assert c.tool is None and len(doc.Objects)==2
            curve=next(o.Shape for o in doc.Objects if o!=obj)
            assert covered(obj.Shape,curve) and len(curve.Edges)>1
            assert doc.UndoCount==count+1

        # A disconnected component within the same object cannot be a target.
        reset()
        separate=Part.makeBox(20,20,20,V(40,-10,-10))
        obj.Shape=Part.makeCompound([obj.Shape,separate]); doc.recompute(); view.fitAll(); Gui.updateGui()
        c.start('Line'); c.click(position(V(10,0,0)))
        count=doc.UndoCount
        assert c.motion(position(V(60,0,0))) is False
        c.click(position(V(60,0,0)))
        assert doc.UndoCount==count and len(doc.Objects)==1
        c.cancel(quiet=True)

        # Hovering before the first click must not capture the wrong object.
        reset()
        other=doc.addObject('Part::Feature','OtherBox')
        other.Shape=Part.makeBox(20,20,20,V(40,-10,-10))
        doc.recompute(); view.fitAll(); Gui.updateGui()
        c.start('Circle')
        c.motion(position(V(10,0,0)))
        c.click(position(V(60,0,0)))
        assert c.anchor is not None and c.drawing_surface[0]==other
        assert c.surface_skin.shape.isSame(other.Shape)
        c.cancel(quiet=True)

        # Equal underlying planes still do not connect separate components.
        reset()
        obj.Shape=Part.makeCompound([Part.makePlane(10,10),Part.makePlane(10,10,V(20,0,0))])
        doc.recompute(); camera(V(0,0,1))
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(obj,'Face1')
        c.start('Line')
        with patch.object(c,'report') as report:
            c.click(position(V(25,5,0)))
            assert c.anchor is None
            report.assert_not_called()
        c.cancel(quiet=True)

        # Close the reported fitted-hood loop with real viewport endpoint snaps.
        reset()
        source,segments=fitted_surface_loop()
        obj.Shape=source
        for segment in segments[:2]:
            line=doc.addObject('Part::Feature','SurfaceLine');line.Shape=segment
        doc.recompute(); camera(V(0,-1,1))
        c.controls.snap.setChecked(True)
        start,end=segments[2].Vertexes[0].Point,segments[0].Vertexes[0].Point
        count=doc.UndoCount
        c.start('Line'); c.click(position(start))
        assert c.anchor is not None and (c.anchor-start).Length<1e-5
        c.motion(position(end))
        assert c.point is not None and (c.point-end).Length<1e-5
        with patch.object(c,'report',wraps=c.report) as report:
            c.click(position(end))
            report.assert_not_called()
        # The closing segment divided the face, which ends Line.
        assert c.tool is None and c.surface_skin is None and not c.guide_timer.isActive()
        assert len(obj.Shape.Faces)==4
        assert len(doc.Objects)==1 and doc.UndoCount==count+1
        assert obj.Shape.isValid()
        c.cancel(quiet=True)
        doc.undo(); assert len(obj.Shape.Faces)==2 and len(doc.Objects)==3
        doc.redo(); assert len(obj.Shape.Faces)==4 and len(doc.Objects)==1

        # A segment that closes nothing continues on the same skin; its frame
        # meshes the fitted guide after the click returns.
        doc.undo()
        c.start('Line'); c.click(position(start))
        edge=segments[2].Edges[0]; middle=edge.valueAt((edge.FirstParameter+edge.LastParameter)/2)
        c.controls.snap.setChecked(False)  # the start vertex is a few pixels away
        c.motion(position(middle))
        skin=c.surface_skin
        with patch.object(c,'report',wraps=c.report) as report:
            c.click(position(middle))
            frame=c.surface_frame
            assert c.tool=='Line' and c.surface_skin is skin
            assert frame is not None and not frame.analytic and frame._mesh is None
            assert c.guide_timer.isActive()
            deadline=time.perf_counter()+10
            while frame._mesh is None and time.perf_counter()<deadline:
                Gui.updateGui(); time.sleep(.01)
            assert frame._mesh is not None and c.surface_frame is frame
            report.assert_not_called()
        assert len(obj.Shape.Faces)==2 and len(doc.Objects)==4 and doc.UndoCount==count+1
        c.cancel(quiet=True)
        doc.undo(); assert len(obj.Shape.Faces)==2 and len(doc.Objects)==3
        App.Console.PrintMessage('PASS: cross-face Line, orbit continuation, fitted loop endpoint closure ends Line, continuing fitted guide meshes after the click, wrapped profiles, native Undo/Redo and disconnected component refusal\n')
    finally:
        c.cancel(quiet=True)
        c.controls.drawing_mode.setCurrentIndex(old[0]); c.controls.plane.setCurrentText(old[1]); c.controls.snap.setChecked(old[2])
        App.closeDocument(doc.Name)
