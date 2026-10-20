"""Real background worker, tree, Undo, cancellation, placements and MCP."""
import time
import shutil
import tempfile
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import Part
from simplecad.jobs import mesh as mesh_jobs
from simplecad.document import operations as ops
from simplecad.mesh.conversion import fingerprint
from simplecad.gui.controller import instance
from simplecad.mcp.api import ModelAPI
from simplecad.gui.tools.mesh_convert import MeshDialog
from simplecad.gui.qt import QtCore, QtWidgets


def wait(job, timeout=90):
    until = time.monotonic() + timeout
    ticks = []
    timer = QtCore.QTimer(); timer.setInterval(20); timer.timeout.connect(lambda: ticks.append(time.monotonic())); timer.start()
    while job.state == 'running' and time.monotonic() < until:
        QtWidgets.QApplication.processEvents()
        time.sleep(.01)
    timer.stop()
    assert job.state == 'ready', job.status()
    assert len(ticks) > 2, 'GUI event loop stopped during conversion'
    return ticks


def run():
    Gui.activateWorkbench('SimpleCADWorkbench')
    c = instance(); c.cancel(quiet=True)
    doc = App.newDocument('MeshConversionTest'); doc.UndoMode = 1
    source = doc.addObject('Mesh::Feature', 'ImportedSTL')
    source.Mesh = Mesh.Mesh(Part.makeBox(20, 30, 40).tessellate(.05))
    source.Placement = App.Placement(App.Vector(23, -8, 14), App.Rotation(App.Vector(1, 2, 3), 25))
    doc.recompute(); c.faces.refresh()
    item = c.faces.records[source.Name]['item']
    assert '(mesh)' in item.text(0) and item.childCount() == 0
    assert c.faces.resolve((doc.Name, source.Name, ''))[0] == source
    assert 'SimpleCAD_ConvertMesh' in Gui.listCommands()
    original = fingerprint(source.Mesh)
    expected_box = source.Mesh.BoundBox
    api = ModelAPI()
    def call(name, **args):
        args['document'] = doc.Name
        if name != 'mesh_conversion_status': args['expected_revision'] = api.revisions.get(doc)
        return api.call('simplecad_' + name, args)
    assert api.summary(source)['conversion_available']
    readonly = ModelAPI(False)
    try:
        readonly.call('simplecad_convert_mesh', {'document':doc.Name, 'expected_revision':readonly.revisions.get(doc), 'object':source.Name})
        raise AssertionError('Read-only conversion allowed')
    except ValueError as error: assert 'read-only' in str(error)
    before = doc.UndoCount
    reply = call('convert_mesh', object=source.Name)
    job = mesh_jobs.get(doc, reply['job_id'])
    wait(job)
    assert doc.UndoCount == before and len(doc.Objects) == 1 and source.ViewObject.Visibility
    status = call('mesh_conversion_status', job_id=job.id)
    assert status['report']['faces'] == 6
    reply = call('finish_mesh_conversion', job_id=job.id)
    result = doc.getObject(reply['object']['name'])
    assert result.TypeId == 'Part::Feature' and len(result.Shape.Faces) == 6
    assert result.Shape.isValid() and abs(result.Shape.Volume - 24000) < .001
    for axis in 'XYZ':
        for side in ('Min','Max'):
            assert abs(getattr(expected_box, axis+side) - getattr(result.Shape.BoundBox, axis+side)) < 1e-4
    assert fingerprint(source.Mesh) == original and not source.ViewObject.Visibility
    assert doc.UndoCount == before + 1
    try:
        call('finish_mesh_conversion', job_id=job.id)
        raise AssertionError('Repeated finish accepted')
    except ValueError: pass
    name = result.Name
    doc.undo(); assert doc.getObject(name) is None and source.ViewObject.Visibility
    doc.redo(); result = doc.getObject(name); assert result and not source.ViewObject.Visibility
    c.faces.refresh(); c.faces.populate(name)
    assert c.faces.records[name]['item'].childCount() == 6
    # The result is ordinary editable CAD topology, including a real extrusion.
    ops.extrude(result, result.Shape.Faces[0], 2)
    assert result.Shape.isValid() and abs(result.Shape.Volume - 24000) > 1
    with tempfile.TemporaryDirectory() as folder:
        path = str(Path(folder) / 'converted.FCStd')
        doc.saveAs(path)
        copy = str(Path(folder) / "reopened.FCStd")
        shutil.copyfile(path, copy)
        reopened = App.openDocument(copy)
        assert reopened.getObject(name).Shape.isValid()
        assert not reopened.getObject(source.Name).ViewObject.Visibility
        App.closeDocument(reopened.Name)
    App.setActiveDocument(doc.Name)
    # Cancel a running process, and invalidate a completed snapshot by moving source.
    undo = doc.UndoCount
    job = mesh_jobs.start(source); job.cancel()
    assert job.state == 'cancelled' and doc.UndoCount == undo
    revision = api.revisions.get(doc)
    job = mesh_jobs.start(source); wait(job)
    source.Placement.Base = App.Vector(99, 2, 3)
    assert api.revisions.get(doc) != revision
    try:
        job.apply(); raise AssertionError('Changed mesh accepted')
    except ValueError as error: assert 'changed' in str(error)
    job.cancel()
    # Smooth surfaces: a filleted box becomes a few fitted faces, in place.
    box = Part.makeBox(40, 30, 20)
    designed = box.makeFillet(4, box.Edges)
    rounded = doc.addObject('Mesh::Feature', 'RoundedSTL')
    rounded.Mesh = Mesh.Mesh(designed.tessellate(.1))
    rounded.Placement = designed.Placement = App.Placement(App.Vector(-50, 10, 5), App.Rotation(App.Vector(0, 1, 1), 40))
    doc.recompute()
    # The mesh's own box is the rotated box of its local bounds, not tight.
    expected_box, rounded_print = designed.BoundBox, fingerprint(rounded.Mesh)
    reply = call('convert_mesh', object=rounded.Name, tolerance=.1, surfaces=True)
    job = mesh_jobs.get(doc, reply['job_id']); wait(job, 180)
    report = call('mesh_conversion_status', job_id=job.id)['report']
    assert report['smooth_surfaces'] and report['faces'] <= 10 and not report['warnings'], report
    before = doc.UndoCount
    smooth = doc.getObject(call('finish_mesh_conversion', job_id=job.id)['object']['name'])
    shape = smooth.Shape
    assert shape.isValid() and shape.isClosed() and len(shape.Solids) == 1 and len(shape.Faces) == report['faces']
    for axis in 'XYZ':
        for side in ('Min', 'Max'):
            assert abs(getattr(expected_box, axis+side) - getattr(shape.BoundBox, axis+side)) < .15, (axis, side)
    assert abs(shape.Volume - rounded.Mesh.Volume) < .002*rounded.Mesh.Volume
    assert doc.UndoCount == before + 1 and not rounded.ViewObject.Visibility
    assert fingerprint(rounded.Mesh) == rounded_print
    smooth_name = smooth.Name
    doc.undo(); assert doc.getObject(smooth_name) is None and rounded.ViewObject.Visibility
    print('PASS smooth surface conversion: %d faces, placement, volume and Undo' % report['faces'], flush=True)
    # UI runs the same service and completes without blocking the event loop.
    dialog = MeshDialog(source, Gui.getMainWindow()); dialog.show()
    assert dialog.surfaces.isEnabled(); dialog.surfaces.setChecked(True); dialog.begin()
    assert not dialog.surfaces.isEnabled()
    until = time.monotonic() + 60
    while dialog.job.state == 'running' and time.monotonic() < until:
        QtWidgets.QApplication.processEvents(); time.sleep(.02)
    dialog.poll()
    assert dialog.job.state == 'applied', dialog.status.text()
    dialog.reject(); dialog.deleteLater()
    print('PASS mesh conversion: worker responsiveness, native tree, placement, Push/Pull, Undo/Redo, save/reopen, MCP, cancellation and stale source', flush=True)
    # Closing a document must release the single conversion slot.
    job = mesh_jobs.start(source)
    App.closeDocument(doc.Name)
    job.check_context()
    assert job.state == 'cancelled'
