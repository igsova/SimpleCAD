"""Optional regression against a supplied FCStd; never overwrite that file."""
import time
import FreeCAD as App
import FreeCADGui as Gui
import MeshPart
from simplecad.document import appearance, operations as op
from simplecad.core import coincident
from simplecad.gui.controller import instance


def run(model_path, output_path=None):
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.openDocument(str(model_path));doc.UndoMode=1
    obj=next(o for o in doc.Objects if hasattr(o,'Shape') and o.Shape.Faces)
    shape=obj.Shape.copy(); original=appearance.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)
    assert len(shape.Faces)==70
    selected=[shape.Edges[i-1] for i in (74,142)]
    stable=[(face,appearance.describe(obj,i)) for i,face in enumerate(shape.Faces,1)
            if not any(coincident.same(e,target) for e in face.Edges for target in selected)]
    elapsed=[];count=doc.UndoCount
    for edge in selected:
        name=next('Edge'+str(i) for i,e in enumerate(obj.Shape.Edges,1) if coincident.same(e,edge))
        Gui.Selection.clearSelection();Gui.Selection.addSelection(obj,name)
        start=time.perf_counter();Gui.runCommand('SimpleCAD_Delete',0)
        elapsed.append(round((time.perf_counter()-start)*1000,1))
        assert not any(coincident.same(e,edge) for e in obj.Shape.Edges)
        assert obj.Shape.isValid() and obj.Shape.isClosed()
        assert abs(obj.Shape.Volume-shape.Volume)<1e-6
    assert len(obj.Shape.Faces)==68 and doc.UndoCount==count+2
    obj.Shape.check(True)
    for face,style in stable:
        index=next(i for i,f in enumerate(obj.Shape.Faces,1) if coincident.same(f,face))
        assert appearance.describe(obj,index)==style
    # Raw triangulation of this fixture already has a seam defect before the
    # edit. Record it rather than claim this geometry fix repairs mesh export.
    raw_mesh_closed=[MeshPart.meshFromShape(Shape=s,LinearDeflection=.1,AngularDeflection=.2,Relative=False).isSolid()
                     for s in (shape,obj.Shape)]
    doc.undo();doc.undo()
    assert len(obj.Shape.Faces)==70 and appearance.fingerprint(obj.ViewObject.ShapeAppearance,precision=6)==original
    doc.redo();doc.redo();assert len(obj.Shape.Faces)==68
    Gui.Selection.clearSelection();c.faces.refresh();c.seams.refresh()
    if output_path:doc.saveAs(str(output_path))
    return {'result':'PASS','edge_delete_ms':elapsed,'volume':obj.Shape.Volume,'faces':len(obj.Shape.Faces),
            'checks':'closed solid, deep validity, unchanged unrelated faces/materials, Undo/Redo',
            'raw_mesh_closed_before_after':raw_mesh_closed}
