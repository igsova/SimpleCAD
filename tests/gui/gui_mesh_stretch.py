"""Run inside FreeCAD after restart: tests only a temporary document."""
import tempfile
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import Part
from simplecad.jobs import mesh as mesh_jobs
from simplecad.mesh.conversion import fingerprint
from simplecad.gui.controller import instance
from simplecad.mcp.api import ModelAPI
from simplecad.gui.qt import QtWidgets
from simplecad.gui.snapping import screen
from simplecad.mesh.handles import rotations
from simplecad.mesh import stretch as mesh_stretch


def wait(predicate):
    until = time.monotonic() + 45
    while not predicate() and time.monotonic() < until:
        QtWidgets.QApplication.processEvents(); time.sleep(.01)
    assert predicate(), 'Timed out waiting for mesh worker'


def run():
    previous = App.ActiveDocument.Name if App.ActiveDocument else None
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('MeshStretchTest'); doc.UndoMode = 1
    try:
        source = doc.addObject('Mesh::Feature', 'SourceSTL')
        source.Mesh = Mesh.Mesh(Part.makeBox(20,30,40).tessellate(.1))
        source.Placement = App.Placement(App.Vector(50,-23,41), App.Rotation(App.Vector(1,2,3),25))
        doc.recompute(); Gui.activeDocument().activeView().fitAll()
        original = fingerprint(source.Mesh); before = doc.UndoCount
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source)
        c.start('MeshStretch'); session = c.mesh_stretch_session
        assert session and 'SimpleCAD_MeshStretch' in Gui.listCommands()
        session.axis.setCurrentIndex(session.axis.findData('LocalZ'))
        session.lower.setValue(-10); session.upper.setValue(10); session.distance.setValue(10)
        assert session.update_preview() and session.apply_button.isEnabled()
        plan = session.plan
        session.distance.setValue(11); session.update_preview(); assert session.plan is plan
        # Plane handles keep the numeric inputs and native preview synchronized.
        assert len(session.handles.lines) == 2
        handle = App.Vector(*map(float, session.handles.markers[('plane',0)]))
        down = screen(c.view,handle)
        session.handles.begin(('plane',0),down)
        session.handles.move(screen(c.view,handle+session.plane.normal*2))
        assert abs(session.lower.value()+8) < .2  # Screen coordinates are integer pixels.
        session.update_preview(); assert session.plan is plan  # No triangle re-splitting mid-drag.
        session.handles.finish(restore=True)
        assert (session.lower.value(),session.upper.value()) == (-10,10)
        session.mouse_mode.setCurrentIndex(1)
        assert len(session.handles.lines) == 3
        _, axes = rotations(session.angles())
        direction = c.view.getViewDirection()
        index = max(range(3),key=lambda i:abs(App.Vector(*map(float,axes[i])).dot(direction)))
        ring = session.handles.lines[('rotate',index)]
        down = screen(c.view,App.Vector(*map(float,ring[0])))
        end = screen(c.view,App.Vector(*map(float,ring[5])))
        session.handles.begin(('rotate',index),down); session.handles.move(end)
        assert abs(session.rotation[index].value()-25) < 2
        assert (session.lower.value(),session.upper.value()) == (-10,10)
        session.handles.finish(restore=True)
        session.rotation[1].setValue(12); assert session.update_preview()
        prepared = mesh_stretch.parameters(source,**session.values())
        # Background worker uses the same rotated world-space planes as preview.
        normal = source.Placement.Rotation.multVec(App.Vector(*prepared['normal']))
        assert (normal-session.plane.normal).Length < 1e-9
        session.rotation[1].setValue(0); session.update_preview()
        assert len(doc.Objects) == 1 and doc.UndoCount == before and fingerprint(source.Mesh) == original
        session.distance.setValue(-20)
        assert not session.update_preview() and not session.apply_button.isEnabled()
        session.distance.setValue(10); session.apply()
        wait(lambda: session.closed or session.job.state == 'failed')
        assert session.closed, session.job.status()
        result = doc.getObject('StretchedMesh')
        assert result and result.TypeId == 'Mesh::Feature' and result.Mesh.isSolid()
        assert abs(result.Mesh.Volume - 30000) < .1
        assert result.Placement.isSame(source.Placement)
        assert not source.ViewObject.Visibility and doc.UndoCount == before+1
        assert fingerprint(source.Mesh) == original
        doc.undo(); assert doc.getObject('StretchedMesh') is None and source.ViewObject.Visibility
        doc.redo(); assert doc.getObject('StretchedMesh').Mesh.isSolid()
        # Cancel a preview without changing the document or Undo stack.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source)
        before = doc.UndoCount; c.start('MeshStretch'); c.mesh_stretch_session.distance.setValue(5)
        c.mesh_stretch_session.update_preview(); c.cancel()
        assert doc.UndoCount == before and fingerprint(source.Mesh) == original
        api = ModelAPI()
        def call(name, **args):
            args['document'] = doc.Name
            if name not in ('mesh_axis','mesh_stretch_status'):
                args['expected_revision'] = api.revisions.get(doc)
            return api.call('simplecad_'+name,args)
        info = call('mesh_axis',object=source.Name,axis='LocalZ')
        assert abs(info['minimum']+20) < 1e-4 and abs(info['maximum']-20) < 1e-4
        angled = call('mesh_axis',object=source.Name,axis='LocalZ',rotation=[0,15,0])
        assert (App.Vector(*angled['normal'])-App.Vector(*info['normal'])).Length > .01
        reply = call('stretch_mesh',object=source.Name,axis='LocalZ',lower=-10,upper=10,distance=5)
        job = mesh_jobs.get(doc,reply['job_id']); wait(lambda: job.state != 'running')
        assert call('mesh_stretch_status',job_id=job.id)['status'] == 'ready'
        reply = call('finish_mesh_stretch',job_id=job.id)
        assert reply['object']['type'] == 'Mesh::Feature'
        try: call('finish_mesh_stretch',job_id=job.id); raise AssertionError('Repeated apply accepted')
        except ValueError: pass
        job = mesh_jobs.start_stretch(source,axis='LocalZ',distance=2); job.cancel()
        assert job.state == 'cancelled'
        job = mesh_jobs.start_stretch(source,axis='LocalZ',distance=2); wait(lambda: job.state != 'running')
        source.Placement.Base += App.Vector(1,0,0)
        try: job.apply(); raise AssertionError('Stale source accepted')
        except ValueError: pass
        job.cancel()
        # Late locks must also invalidate prepared jobs.
        job = mesh_jobs.start_stretch(source,axis='LocalZ',distance=2); wait(lambda: job.state != 'running')
        source.addProperty('App::PropertyBool','SC_Locked'); source.SC_Locked = True
        try: job.apply(); raise AssertionError('Locked source accepted')
        except ValueError: pass
        job.cancel()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'stretch.FCStd'); doc.saveAs(path)
            name = doc.Name; App.closeDocument(name); doc = App.openDocument(path)
            assert doc.getObject('StretchedMesh').Mesh.isSolid()
        print('PASS mesh stretch preview, reuse, invalid input, background apply, placement, Undo/Redo, MCP, stale/locked source, Cancel and FCStd reopen',flush=True)
    finally:
        c.cancel(quiet=True)
        for job in list(mesh_jobs._jobs.values()):
            if job.doc == doc: job.cancel()
        App.closeDocument(doc.Name)
        if previous in App.listDocuments(): App.setActiveDocument(previous)
