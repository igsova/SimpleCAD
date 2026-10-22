"""Native cursor references away from the extrusion axis, exact commit and Undo."""
import time
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad.document import operations as op
from simplecad.core import preferences
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen

V = App.Vector


def run(screenshot=None):
    previous=preferences.load(); preferences.save(preferences.Settings())
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.newDocument('PullReferenceSmoke');doc.UndoMode=1
    try:
        obj=op.new_shape(doc,Part.makeBox(10,10,20),'Pull this block')
        floor=op.new_shape(doc,Part.makePlane(40,40,V(30,0,5)),'Reference level')
        original=floor.Shape.exportBrepToString()
        view=Gui.activeDocument().activeView()
        view.getCameraNode().orientation.setValue(*App.Rotation(V(1,1,0),V(-1,1,2),V(1,-1,1),'ZXY').Q)
        view.fitAll();Gui.updateGui()
        c.controls.snap.setChecked(True)
        def pos(point):return tuple(round(v) for v in screen(view,point))
        def start():
            c.start('PushPull');c.click(pos(V(5,5,20)))
            assert c.obj==obj and abs(c.anchor.z-20)<1e-6
        start()
        target=pos(V(50,20,5))
        before=doc.UndoCount
        begin=time.perf_counter()
        for _ in range(100):c.motion(target)
        elapsed=(time.perf_counter()-begin)*10
        assert c.distance==-15 and c.pull_reference.label=='Face level', (c.distance,c.pull_reference)
        assert c.preview.pull_guide.texts[-1].string[0]=='Face level snapped'
        assert doc.UndoCount==before
        if screenshot:view.saveImage(str(screenshot),1280,900,'Current')
        c.click(target)
        assert c.tool is None and obj.Shape.isValid() and obj.Shape.isClosed()
        assert abs(obj.Shape.BoundBox.ZMax-5)<1e-6 and abs(obj.Shape.Volume-500)<1e-6
        assert floor.Shape.exportBrepToString()==original
        doc.undo();Gui.updateGui()
        assert abs(obj.Shape.Volume-2000)<1e-6
        start()
        edge_target=pos(V(50,0,5))
        # The full edge attracts at 20 pixels, not just its midpoint glyph.
        edge_target=(edge_target[0],edge_target[1]-20)
        c.motion(edge_target)
        assert c.distance==-15 and c.pull_reference.label=='Edge level',(c.distance,c.pull_reference)
        assert c.preview.pull_guide.texts[-1].string[0]=='Edge level snapped'
        c.controls.snap.setChecked(False);c.motion(edge_target)
        assert c.pull_reference is None
        assert c.preview.pull_guide.switch.whichChild.getValue()==-1
        c.controls.snap.setChecked(True);c.motion(target)
        c.controls.value.setText('-14.7 mm');c.numeric()
        assert abs(obj.Shape.BoundBox.ZMax-5.3)<1e-6
        doc.undo();doc.redo()
        assert abs(obj.Shape.BoundBox.ZMax-5.3)<1e-6
        return {'result':'PASS','preview_ms':round(elapsed,2),
                'checks':'face interior and full-edge references, exact height commit, numeric override, Snap off, Undo/Redo, unchanged reference'}
    finally:
        c.cancel(quiet=True);preferences.save(previous)
