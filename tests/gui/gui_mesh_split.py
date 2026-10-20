"""Native mesh-only UI, background jobs, MCP, Undo and STL export."""
import tempfile
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Mesh
from simplecad.jobs import mesh as mesh_jobs
from simplecad.mesh.conversion import fingerprint
from simplecad.gui.controller import instance
from simplecad.mcp.api import ModelAPI
from simplecad.gui.qt import QtWidgets


def wait(job):
    until=time.monotonic()+45
    while job.state=='running' and time.monotonic()<until:
        QtWidgets.QApplication.processEvents();time.sleep(.01)
    assert job.state=='ready',job.status()


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c=instance();c.cancel(quiet=True)
    doc=App.newDocument('MeshSplitTest');doc.UndoMode=1
    source=doc.addObject('Mesh::Feature','SourceSTL');source.Mesh=Mesh.createBox(20,30,40)
    source.Placement=App.Placement(App.Vector(50,-23,41),App.Rotation(App.Vector(1,2,3),25))
    doc.recompute();Gui.activeDocument().activeView().viewAxonometric();Gui.activeDocument().activeView().fitAll()
    original=fingerprint(source.Mesh);before=doc.UndoCount
    Gui.Selection.addSelection(source);c.start('Slice')
    session=c.mesh_split_session
    assert session and c.tool=='MeshSplit'
    assert 'SimpleCAD_MeshSplit' in Gui.listCommands()
    assert not hasattr(session,'joint')
    session.axis.setCurrentIndex(session.axis.findData('LocalZ'))
    session.gap.setValue(8)
    session.begin();wait(session.job);session.poll()
    assert session.apply_button.isEnabled() and len(doc.Objects)==1 and doc.UndoCount==before
    assert fingerprint(source.Mesh)==original
    session.apply()
    pieces=[o for o in doc.Objects if o!=source]
    assert len(pieces)==2 and all(o.TypeId=='Mesh::Feature' and o.Mesh.isSolid() for o in pieces)
    assert not source.ViewObject.Visibility and doc.UndoCount==before+1
    axis=source.Placement.Rotation.multVec(App.Vector(0,0,1))
    assert abs((pieces[1].Placement.Base-pieces[0].Placement.Base).dot(axis)-8)<1e-5
    assert fingerprint(source.Mesh)==original
    with tempfile.TemporaryDirectory() as folder:
        for i,obj in enumerate(pieces):
            path=str(Path(folder)/('side%d.stl'%i));obj.Mesh.write(path)
            exported=Mesh.Mesh(path);assert exported.isSolid() and exported.CountFacets==obj.Mesh.CountFacets
        name=doc.Name;path=str(Path(folder)/'mesh-split.FCStd');doc.saveAs(path)
        App.closeDocument(name);doc=App.openDocument(path);source=doc.getObject('SourceSTL')
        assert len(doc.Objects)==3 and all(o.TypeId=='Mesh::Feature' for o in doc.Objects)
        # Undo is verified in the original document before save/reopen below.
    # A fresh split supports one-step native Undo/Redo without any Part object.
    App.setActiveDocument(doc.Name);doc.UndoMode=1
    job=mesh_jobs.start_split(source,'X',gap=0);wait(job);results=job.apply();names=[o.Name for o in results]
    doc.undo();assert all(doc.getObject(name) is None for name in names)
    doc.redo();assert all(doc.getObject(name).Mesh.isSolid() for name in names)
    c.faces.refresh()
    assert all(name in c.faces.records for name in names)
    api=ModelAPI()
    def call(name,**args):
        args['document']=doc.Name
        if name!='mesh_split_status':args['expected_revision']=api.revisions.get(doc)
        return api.call('simplecad_'+name,args)
    reply=call('split_mesh',object=source.Name,axis='Z',offset=2)
    job=mesh_jobs.get(doc,reply['job_id']);wait(job)
    assert call('mesh_split_status',job_id=job.id)['status']=='ready'
    reply=call('finish_mesh_split',job_id=job.id)
    assert len(reply['objects'])==2 and all(o['type']=='Mesh::Feature' for o in reply['objects'])
    try:call('finish_mesh_split',job_id=job.id);raise AssertionError('Repeated split finish accepted')
    except ValueError:pass
    job=mesh_jobs.start_split(source,'X');job.cancel();assert job.state=='cancelled'
    job=mesh_jobs.start_split(source,'X');wait(job)
    source.Placement.Base+=App.Vector(1,0,0)
    try:job.apply();raise AssertionError('Stale source accepted')
    except ValueError:pass
    job.cancel()
    # Cancel a shaded preview and restore native visibility with no Undo entry.
    Gui.Selection.clearSelection();Gui.Selection.addSelection(source);source.ViewObject.Visibility=True
    before=doc.UndoCount;c.start('MeshSplit');session=c.mesh_split_session;session.begin();wait(session.job);session.poll()
    c.cancel();assert doc.UndoCount==before and source.ViewObject.Visibility
    App.closeDocument(doc.Name)
    print('PASS mesh-only UI, Slice dispatch, cap preview, placement/gap, STL export, FCStd reopen, Undo/Redo, MCP, stale source and cancel',flush=True)
