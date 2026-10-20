"""Optional exact saved-model cut, using tree selection and a native exit click."""
import time
import FreeCAD as App
import FreeCADGui as Gui
from simplecad.document import appearance
from simplecad.core import coincident, geometry as g
from simplecad.gui.controller import instance
from simplecad.gui.snapping import screen, pick
V=App.Vector


def run(model_path, screenshot=None):
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.openDocument(str(model_path));doc.UndoMode=1
    obj=doc.getObject('SimpleShape001');original=obj.Shape
    selected=next((i,f) for i,f in enumerate(original.Faces,1)
                  if len(f.Vertexes)==3 and (f.CenterOfMass-V(0,20/3,80/3)).Length<1e-6)
    index,face=selected
    # Color the surviving triangular wedge to exercise material mapping into
    # a newly created owner as well as preservation on the large source owner.
    wedge=next(i for i,f in enumerate(original.Faces,1)
               if len(f.Vertexes)==3 and i!=index)
    appearance.commit(appearance.prepare([(obj,['Face'+str(wedge)])]),color=[0.2,0.8,0.3],opacity=57)
    original_materials=tuple(obj.ViewObject.ShapeAppearance)
    count=len(doc.Objects)
    view=Gui.activeDocument().activeView()
    view.getCameraNode().orientation.setValue(*App.Rotation(V(0,0,1),V(1,-1,1)).Q)
    view.fitAll();Gui.updateGui()
    Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,'Face'+str(index))
    c.faces.chosen=(doc.Name,obj.Name,'Face'+str(index))
    c.controls.snap.setChecked(True)
    c.start('PushPull')
    assert c.anchor is not None and coincident.same(c.face,face), (c.anchor,c.tool)
    target=V(20,10,30)
    pos=tuple(round(v) for v in screen(view,target))
    hit=pick(view,doc,pos,face_only=True)
    assert hit and hit[0]==obj and abs(hit[1].CenterOfMass.x-20)<1e-6,hit
    c.motion(pos);assert abs(c.distance+20)<1e-6,(c.distance,c.pull_reference)
    before=doc.UndoCount
    start=time.perf_counter();c.click(pos);elapsed=round((time.perf_counter()-start)*1000,1)
    assert c.tool is None and doc.UndoCount==before+1
    assert len(doc.Objects)==count+1
    pieces=[o for o in doc.Objects if o==obj or o.Label==obj.Label+' · piece 2']
    assert len(pieces)==2
    assert all(o.Shape.isValid() and o.Shape.isClosed() and len(o.Shape.Solids)==1 for o in pieces)
    assert abs(sum(o.Shape.Volume for o in pieces)-(original.Volume-4000))<1e-6
    end=face.copy();end.translate(V(20,0,0))
    assert all(o.Shape.common(end).Area<1e-6 and o.Shape.common(face).Area<1e-6 for o in pieces)
    from simplecad.document.materials import mapped
    for o in pieces:
        expected=mapped(original,o.Shape,original_materials)
        assert appearance.fingerprint(o.ViewObject.ShapeAppearance,precision=6)==appearance.fingerprint(expected,precision=6)
    doc.undo();assert len(doc.Objects)==count and abs(obj.Shape.Volume-original.Volume)<1e-6
    assert appearance.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)==appearance.fingerprint(original_materials,precision=6)
    doc.redo();assert len(doc.Objects)==count+1
    Gui.Selection.clearSelection();Gui.updateGui();view.redraw()
    if screenshot:view.saveImage(str(screenshot),1280,900,'Current')
    return {'result':'PASS','commit_ms':elapsed,'remaining_volumes':[o.Shape.Volume for o in pieces],
            'checks':'native opposite-face click, 20 mm triangular opening, two closed solids, preserved materials including wedge opacity, atomic Undo/Redo'}
