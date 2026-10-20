"""Native checkbox, reversible preview, side labels and MCP glue settings."""
import time
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
        QtWidgets.QApplication.processEvents();time.sleep(.005)
    assert job.state=='ready',job.status()


def run():
    Gui.activateWorkbench('SimpleCADWorkbench');c=instance();c.cancel(quiet=True)
    doc=App.newDocument('MeshGlueTest');doc.UndoMode=1
    source=doc.addObject('Mesh::Feature','SourceSTL');source.Mesh=Mesh.createBox(20,3,16)
    source.Placement=App.Placement(App.Vector(12,-8,30),App.Rotation(App.Vector(1,2,3),20))
    doc.recompute();before=doc.UndoCount;original=fingerprint(source.Mesh)
    Gui.Selection.clearSelection();Gui.Selection.addSelection(source);c.start('MeshSplit');s=c.mesh_split_session
    assert not s.glue.isChecked() and not s.glue_controls.isVisible()
    s.axis.setCurrentIndex(s.axis.findData('LocalZ'));s.glue.setChecked(True)
    assert s.glue_controls.isVisible() and s.cap.isChecked() and not s.cap.isEnabled()
    s.glue_clearance.setValue(.1);s.begin();wait(s.job);s.poll()
    assert s.apply_button.isEnabled() and s.job.report['glue']['clearance']==.1
    assert len(doc.Objects)==1 and doc.UndoCount==before and fingerprint(source.Mesh)==original
    old=s.job;s.glue_flip.setChecked(True)
    assert old.state=='cancelled' and s.job is None and not s.apply_button.isEnabled()
    s.begin();wait(s.job);s.poll();s.apply()
    pieces=[o for o in doc.Objects if o!=source]
    assert len(pieces)==2 and all(o.TypeId=='Mesh::Feature' and o.Mesh.isSolid() for o in pieces)
    assert pieces[0].Label.endswith('groove') and pieces[1].Label.endswith('ridge')
    assert not source.ViewObject.Visibility and fingerprint(source.Mesh)==original
    assert doc.UndoCount==before+1
    doc.undo();assert len(doc.Objects)==1 and source.ViewObject.Visibility
    doc.redo();assert len(doc.Objects)==3 and not source.ViewObject.Visibility
    api=ModelAPI()
    def call(name,**args):
        args.update(document=doc.Name,expected_revision=api.revisions.get(doc))
        return api.call('simplecad_'+name,args)
    options={'object':source.Name,'axis':'LocalZ','glue':{'depth':1,'clearance':.1,'flip':False}}
    api.allow_changes=False
    try:call('split_mesh',**options);raise AssertionError('Read-only glue accepted')
    except ValueError:pass
    api.allow_changes=True
    reply=call('split_mesh',**options);job=mesh_jobs.get(doc,reply['job_id']);wait(job)
    result=call('finish_mesh_split',job_id=job.id)
    assert result['report']['glue']['depth']==1 and len(result['objects'])==2
    try:call('split_mesh',**{**options,'cap':False});raise AssertionError('Open glue cap accepted')
    except ValueError:pass
    Gui.Selection.clearSelection();Gui.Selection.addSelection(source);source.ViewObject.Visibility=True
    before=doc.UndoCount;c.start('MeshSplit');s=c.mesh_split_session;s.glue.setChecked(True)
    s.axis.setCurrentIndex(s.axis.findData('LocalZ'));s.begin();wait(s.job);s.poll()
    s.glue.setChecked(False);assert not s.glue_controls.isVisible() and s.cap.isEnabled()
    c.cancel();assert source.ViewObject.Visibility and doc.UndoCount==before
    App.closeDocument(doc.Name)
    print('PASS glue checkbox, controls, side swap, preview cancellation, native mesh results, labels, Undo/Redo, MCP and read-only guard',flush=True)
