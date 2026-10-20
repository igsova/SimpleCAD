"""Native panels, cached preview, materials, cancellation, Undo and saved solids."""
import tempfile
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Part
from simplecad import ROOT
from simplecad.document import operations as ops, appearance, visibility
from simplecad.modeling import forming
from simplecad.gui.controller import instance
from simplecad.gui.qt import QtWidgets
V=App.Vector


def run(screenshots=False):
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.newDocument('FormingGUI');doc.UndoMode=1
    view=Gui.activeDocument().activeView()
    def flush():
        for _ in range(3):QtWidgets.QApplication.processEvents();Gui.updateGui()
    def add(shape,label):return ops.new_shape(doc,shape,label)
    def start(mode,selection):
        Gui.Selection.clearSelection()
        for obj,name in selection:Gui.Selection.addSelection(obj,name)
        Gui.runCommand('SimpleCAD_'+mode);flush()
        assert c.tool==mode and c.forming_session is not None,mode
        return c.forming_session
    def update(s):
        valid=s.update_preview();flush();return valid
    try:
        box=add(Part.makeBox(10,20,30),'Scale sample')
        box.Placement=App.Placement(V(15,5,0),App.Rotation(V(0,0,1),30))
        materials=appearance.expanded(box)
        materials[2].DiffuseColor=(1.,0.,0.);materials[2].Transparency=.43
        box.ViewObject.ShapeAppearance=materials
        visibility.set_hidden(box,[5])
        original=box.Shape;colors=appearance.fingerprint(box.ViewObject.ShapeAppearance,6)
        view.viewIsometric();view.fitAll();flush()
        count=doc.UndoCount;children=box.ViewObject.RootNode.getNumChildren()
        s=start('Scale',[(box,'')]);s.linked.setChecked(False)
        s.values[0].setValue(2);s.values[1].setValue(.75);s.values[2].setValue(1.5)
        s.axes.setCurrentIndex(s.axes.findData('Local'));assert update(s),s.status.text()
        cached=[root for root,_ in s.preview.cached];begin=time.perf_counter()
        for value in (1,2,3,1.7):s.values[0].setValue(value);assert s.update_preview()
        elapsed=time.perf_counter()-begin
        assert [root for root,_ in s.preview.cached]==cached
        assert box.Shape.isSame(original) and doc.UndoCount==count
        assert appearance.fingerprint(box.ViewObject.ShapeAppearance,6)==colors
        c.cancel(quiet=True);flush()
        assert box.ViewObject.RootNode.getNumChildren()==children and box.ViewObject.Visibility
        s=start('Scale',[(box,'')]);s.linked.setChecked(False)
        s.values[0].setValue(2);s.values[1].setValue(.75);s.values[2].setValue(1.5)
        s.axes.setCurrentIndex(s.axes.findData('Local'));assert update(s)
        frame=forming.scale_frames([original],'Local')[0]
        _,origins=forming.scaled(original,frame,(2,.75,1.5))
        s.apply();flush();assert c.forming_session is None
        assert abs(box.Shape.Volume-original.Volume*2*.75*1.5)<1e-5
        now=appearance.fingerprint(box.ViewObject.ShapeAppearance,6)
        assert now==tuple(colors[i] for i in origins),(now,colors,origins)
        assert visibility.hidden_faces(box)=={i+1 for i,source in enumerate(origins) if source==4}
        assert doc.UndoCount==count+1
        doc.undo();doc.recompute();flush();assert abs(box.Shape.Volume-original.Volume)<1e-5
        assert appearance.fingerprint(box.ViewObject.ShapeAppearance,6)==colors
        assert visibility.hidden_faces(box)=={5}
        doc.redo();doc.recompute();flush()
        box.ViewObject.Visibility=False
        profiles=[add(Part.Face(Part.Wire([Part.makeCircle(r,V(0,0,z))])),'Profile '+str(i)) for i,(r,z) in enumerate([(5,0),(8,12),(3,28)])]
        before=len(doc.Objects);count=doc.UndoCount
        s=start('Loft',[(o,'') for o in profiles]);assert update(s),s.status.text()
        assert s.result.isClosed() and len(doc.Objects)==before
        s.order.setCurrentRow(1);s.reorder(-1);s.reorder(1);assert update(s),s.status.text()
        if screenshots:
            view.fitAll();flush();s.dialog.grab().save(str(ROOT.parent.parent/'work/loft-panel.png'))
        c.cancel(quiet=True);flush()
        assert all(o.ViewObject.Visibility for o in profiles) and doc.UndoCount==count
        s=start('Loft',[(o,'') for o in profiles]);assert update(s);s.apply();flush()
        loft=doc.Objects[-1];assert loft.Shape.isClosed() and len(doc.Objects)==before+1
        assert all(not o.ViewObject.Visibility for o in profiles)
        assert doc.UndoCount==count+1
        doc.undo();doc.recompute();flush();assert all(o.ViewObject.Visibility for o in profiles)
        doc.redo();doc.recompute();flush();loft=doc.Objects[-1]
        section=add(Part.Face(Part.Wire([Part.makeCircle(1,V(30,0,0))])),'Sweep section')
        path=add(Part.Arc(V(30,0,0),V(40,10,0),V(50,0,0)).toShape(),'Arc path')
        before=len(doc.Objects);count=doc.UndoCount
        s=start('Sweep',[(section,''),(path,'')]);assert update(s),s.status.text()
        assert s.result.isValid() and s.result.isClosed()
        s.frenet.setChecked(True);assert update(s),s.status.text()
        if screenshots:s.dialog.grab().save(str(ROOT.parent.parent/'work/sweep-panel.png'))
        s.apply();flush();swept=doc.Objects[-1]
        assert len(doc.Objects)==before+1 and swept.Shape.isClosed()
        assert not section.ViewObject.Visibility and not path.ViewObject.Visibility
        assert doc.UndoCount==count+1
        # Sources selected as FaceN are never hidden along with their owners.
        s=start('Loft',[(profiles[0],'Face1'),(profiles[-1],'Face1')]);assert update(s)
        before_states=[o.ViewObject.Visibility for o in profiles]
        s.apply();flush();assert before_states==[o.ViewObject.Visibility for o in profiles]
        # Changing a captured source invalidates the panel without committing.
        s=start('Scale',[(box,'')]);box.Shape=Part.makeBox(12,12,12);doc.recompute()
        c.check_context();flush();assert c.forming_session is None
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'Forming.FCStd';doc.saveAs(str(file));name=doc.Name
            saved_names=[loft.Name,swept.Name]
            App.closeDocument(name);doc=App.openDocument(str(file));flush()
            assert all(o.Shape.isValid() for o in doc.Objects)
            assert all(doc.getObject(o).Shape.isClosed() for o in saved_names)
        if screenshots:
            view=Gui.activeDocument().activeView();view.viewIsometric();view.fitAll();flush()
            view.saveImage(str(ROOT.parent.parent/'work/forming-results.png'),1200,900,'Current')
        return {'result':'PASS','preview_updates_ms':round(elapsed*1000/4,2),'checks':'Scale materials/Undo/cache, Loft ordering/cancel, Sweep arc, save/reopen'}
    finally:
        c.cancel(quiet=True)
        if doc.Name in App.listDocuments():App.closeDocument(doc.Name)
