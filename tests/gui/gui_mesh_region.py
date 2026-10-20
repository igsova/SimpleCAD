"""Run run() inside FreeCAD after restart. Uses a temporary document only."""
import tempfile
import time
from pathlib import Path
import numpy as np
import FreeCAD as App
import FreeCADGui as Gui
import Mesh
import Part
from simplecad.jobs import mesh as mesh_jobs
from simplecad.mesh.conversion import fingerprint
from simplecad.gui.controller import instance
from simplecad.mcp.api import ModelAPI
from simplecad.mcp.catalog import MUTATIONS
from simplecad.gui.qt import QtCore, QtWidgets
from simplecad.gui.snapping import screen
try:
    from PySide import QtTest
except ImportError:
    try:
        from PySide6 import QtTest
    except ImportError:
        from PySide2 import QtTest


def wait(predicate):
    until=time.monotonic()+60
    while not predicate() and time.monotonic()<until:
        QtWidgets.QApplication.processEvents(); time.sleep(.01)
    assert predicate(),'Mesh region worker timed out'


def check_existing_intersections():
    """Two overlapping boxes plus a separate editable box; no document edits."""
    from simplecad.mesh.region_edit import edit, from_mesh, intersection_geometry
    points=[]; faces=[]
    for base in (App.Vector(),App.Vector(5,5,5),App.Vector(40,0,0)):
        vertices,triangles=Part.makeBox(10,10,10,base).tessellate(.1)
        faces.extend(tuple(int(i)+len(points) for i in face) for face in triangles)
        points.extend(vertices)
    source=Mesh.Mesh((points,faces)); original=fingerprint(source)
    assert source.hasSelfIntersections() and not source.hasNonManifolds()
    baseline=intersection_geometry(source); assert baseline
    topology=from_mesh(source)
    seed=int(np.flatnonzero((topology.centers[:,0]>40) & (topology.normals[:,2]>.99))[0])+1
    selected=sorted(i+1 for i in topology.region(seed))
    for mode,parameters in (('Move',{'delta':(0,0,2)}),('Extrude',{'distance':2})):
        result,report=edit(source,selected,mode=mode,**parameters)
        assert intersection_geometry(result)==baseline
        assert report['self_intersecting_triangles']==sum(baseline.values())
        assert report['warnings'] and fingerprint(source)==original
    seed=int(np.flatnonzero((topology.centers[:,0]<10) & (topology.normals[:,2]>.99)
                            & np.isclose(topology.centers[:,2],10))[0])+1
    selected=sorted(i+1 for i in topology.region(seed))
    try:
        edit(source,selected,delta=(0,0,1))
        raise AssertionError('Changed intersecting region was accepted')
    except ValueError as error:
        assert 'self-intersections' in str(error),str(error)
    assert fingerprint(source)==original


def check_perforated_face_move():
    """The indexed correction must also pass real FreeCAD mesh validation."""
    from test_mesh_retriangulate import perforated_plate
    from simplecad.mesh.region_edit import edit, from_mesh
    points,faces=perforated_plate()
    source=Mesh.Mesh(([App.Vector(*p) for p in points.tolist()],list(map(tuple,faces.tolist()))))
    original=fingerprint(source)
    assert source.isSolid() and not source.hasSelfIntersections()
    topology=from_mesh(source)
    selected=[int(i)+1 for i in np.flatnonzero(topology.normals[:,0]>.999)]
    result,_=edit(source,selected,delta=(5,0,0))
    assert result.isSolid() and not result.hasSelfIntersections()
    assert not result.hasNonManifolds() and not result.hasNonUniformOrientedFacets()
    assert abs(result.Volume-source.Volume-100)<1e-4
    assert fingerprint(source)==original


def check_collision_preview(c):
    """Red preview marks match the triangles the background Apply rejects."""
    from simplecad.mesh.region_edit import from_mesh
    doc=App.newDocument('MeshRegionCollision'); doc.UndoMode=1
    try:
        # Two stacked 20 mm plates, 0.5 mm apart, on a 2 mm grid.
        grid=[(2.*x,2.*y) for y in range(11) for x in range(11)]
        points=[App.Vector(x,y,0) for x,y in grid]+[App.Vector(x,y,.5) for x,y in grid]
        cells=[(y*11+x,y*11+x+1,y*11+x+12,y*11+x+11) for y in range(10) for x in range(10)]
        plate=[t for a,b,d,e in cells for t in ((a,b,d),(a,d,e))]
        n=len(grid); faces=plate+[(a+n,d+n,b+n) for a,b,d in plate]
        source=doc.addObject('Mesh::Feature','Plates'); source.Mesh=Mesh.Mesh((points,faces)); doc.recompute()
        original=fingerprint(source.Mesh); before=doc.UndoCount
        topology=from_mesh(source.Mesh)
        seed=int(np.argmin(np.linalg.norm(topology.centers-(10,10,0),axis=1)))
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source); c.start('MeshRegion')
        s=c.mesh_region_session
        s.selection.setCurrentText('Triangle'); s.selected={seed}; s.rings.setValue(2)
        s.delta[2].setValue(1.0); assert s.update_preview()
        wait(lambda:s.collision is not None and s.collision[3] is not None)
        marked=s.preview.marked; assert len(marked),s.status.text()
        colors=np.asarray([tuple(v.getValue()) for v in s.preview.material.diffuseColor.getValues()])
        assert np.allclose(colors[marked],(.9,.08,.08),atol=1e-6) and 'Red:' in s.status.text()
        s.apply(); wait(lambda:s.job is None or s.job.state!='running')
        assert s.job.state=='failed' and 'self-intersections' in s.job.error,s.job.status()
        assert set(s.job.failed_triangles)<=set(marked.tolist()) and len(s.job.failed_triangles)
        assert len(s.preview.marked)==len(s.job.failed_triangles)
        s.delta[2].setValue(.2); assert s.update_preview()
        wait(lambda:s.collision is not None and s.collision[3] is not None)
        assert not len(s.preview.marked) and 'No collisions' in s.status.text(),s.status.text()
        c.cancel()
        assert fingerprint(source.Mesh)==original and doc.UndoCount==before and len(doc.Objects)==1
    finally:
        c.cancel(quiet=True)
        for job in list(mesh_jobs._jobs.values()):
            if job.doc==doc: job.cancel()
        App.closeDocument(doc.Name)


def run():
    check_perforated_face_move()
    check_existing_intersections()
    previous=App.ActiveDocument.Name if App.ActiveDocument else None
    Gui.activateWorkbench('SimpleCADWorkbench'); c=instance(); c.cancel(quiet=True)
    doc=App.newDocument('MeshRegionTest'); doc.UndoMode=1
    try:
        source=doc.addObject('Mesh::Feature','SourceSTL')
        points,faces=Part.makeBox(20,30,40).tessellate(.1)
        source.Mesh=Mesh.Mesh((list(points),[tuple(map(int,f)) for f in faces]))
        source.Placement=App.Placement(App.Vector(50,-23,41),App.Rotation(App.Vector(1,2,3),25))
        doc.recompute(); Gui.activeDocument().activeView().viewTop(); Gui.activeDocument().activeView().fitAll()
        before=doc.UndoCount; original=fingerprint(source.Mesh)
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source); c.start('MeshRegion')
        s=c.mesh_region_session
        assert s and 'SimpleCAD_MeshRegion' in Gui.listCommands()
        normal=np.asarray(tuple(source.Placement.Rotation.multVec(App.Vector(0,0,1))))
        seed=int(np.argmax(s.topology.normals@normal))+1
        # Route through the native QWindow, as physical clicks do. Direct
        # sendEvent(viewport, ...) misses the intermediate QWidgetWindow events
        # that used to clear the pending pick before its release arrived.
        Gui.updateGui(); QtWidgets.QApplication.processEvents()
        mdi=Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        widget=next(w for w in mdi.currentSubWindow().findChildren(QtWidgets.QWidget)
                    if c.selection.is_viewport(w))
        x,y=screen(c.view,App.Vector(*s.topology.centers[seed-1].tolist()))
        width,height=c.view.getSize()
        point=QtCore.QPointF(x*widget.width()/width,widget.height()-y*widget.height()/height)
        window=widget.window().windowHandle()
        assert window is not None
        window_point=window.mapFromGlobal(widget.mapToGlobal(point.toPoint()))
        QtTest.QTest.mouseClick(window,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier,window_point)
        QtWidgets.QApplication.processEvents()
        assert s.selected==s.topology.region(seed) and len(s.selected)==2
        assert s.selection_count.text()=='2 triangles selected'
        assert all('Click the mesh to select' not in check.text() for check in s.dialog.findChildren(QtWidgets.QCheckBox))
        for field,value in zip(s.delta,normal*5): field.setValue(float(value))
        assert s.update_preview() and s.apply_button.isEnabled()
        plan=s.plan; s.update_preview(); assert s.plan is plan
        assert len(doc.Objects)==1 and doc.UndoCount==before and fingerprint(source.Mesh)==original
        s.mode.setCurrentText('Rotate'); s.angle.setValue(5)
        assert s.update_preview() and s.angle.isVisible() and not s.distance.isVisible()
        s.mode.setCurrentText('Extrude'); assert not s.update_preview()
        s.distance.setValue(5); assert s.update_preview()
        def assert_buffers():
            preview=s.preview
            assert preview.faces.coordIndex.getNum()==4*len(s.shown_faces)
            assert preview.coords.point.getNum()==len(s.shown_points)
            assert preview.material.diffuseColor.getNum()==len(s.shown_faces)
            np.testing.assert_array_equal(list(preview.faces.coordIndex.getValues()),
                [int(v) for face in s.shown_faces for v in (*face,-1)])
        assert_buffers()
        selected=s.selected.copy()
        s.selected={seed-1}; s.changed(); assert s.update_preview(); assert_buffers()
        s.clear(); assert not s.update_preview(); assert_buffers()
        s.selected=selected; s.changed(); assert s.update_preview(); assert_buffers()
        s.mode.setCurrentText('Move'); assert s.update_preview(); assert_buffers()
        s.mode.setCurrentText('Extrude'); assert s.update_preview(); assert_buffers()
        s.apply()
        wait(lambda:s.closed or (s.job and s.job.state=='failed'))
        assert s.closed,s.job.status()
        result=doc.getObject('EditedMesh')
        assert result and result.Mesh.isSolid() and not result.Mesh.hasSelfIntersections()
        assert abs(result.Mesh.Volume-27000)<.1
        assert result.Placement.isSame(source.Placement) and not source.ViewObject.Visibility
        assert doc.UndoCount==before+1 and fingerprint(source.Mesh)==original
        doc.undo(); assert doc.getObject('EditedMesh') is None and source.ViewObject.Visibility
        doc.redo(); assert doc.getObject('EditedMesh').Mesh.isSolid()
        # Cancelling a preview neither changes geometry nor adds an Undo step.
        Gui.Selection.clearSelection(); Gui.Selection.addSelection(source); before=doc.UndoCount
        c.start('MeshRegion'); c.mesh_region_session.selected={seed-1}; c.mesh_region_session.delta[0].setValue(1)
        c.mesh_region_session.update_preview(); c.cancel()
        assert fingerprint(source.Mesh)==original and doc.UndoCount==before
        api=ModelAPI()
        def call(name,**args):
            args['document']=doc.Name
            if 'simplecad_'+name in MUTATIONS: args['expected_revision']=api.revisions.get(doc)
            return api.call('simplecad_'+name,args)
        triangles=call('inspect_mesh_triangles',object=source.Name,limit=2)
        assert len(triangles['triangles'])==2
        region=call('inspect_mesh_region',object=source.Name,seed_triangle=seed)
        assert region['region']['triangles']==2
        reply=call('edit_mesh_region',object=source.Name,seed_triangle=seed,mode='Move',delta=(normal*2).tolist())
        job=mesh_jobs.get(doc,reply['job_id']); wait(lambda:job.state!='running')
        assert call('mesh_region_status',job_id=job.id)['status']=='ready',job.status()
        reply=call('finish_mesh_region',job_id=job.id)
        assert reply['object']['type']=='Mesh::Feature'
        try: call('finish_mesh_region',job_id=job.id); raise AssertionError('Repeated Apply accepted')
        except ValueError: pass
        reply=call('edit_mesh_region',object=source.Name,seed_triangle=seed,mode='Extrude',distance=2)
        call('cancel_mesh_region',job_id=reply['job_id'])
        assert call('mesh_region_status',job_id=reply['job_id'])['status']=='cancelled'
        job=mesh_jobs.start_region(source,seed_triangle=seed,mode='Extrude',distance=2)
        wait(lambda:job.state!='running'); assert job.state=='ready',job.status()
        source.Placement.Base+=App.Vector(1,0,0)
        try: job.apply(); raise AssertionError('Stale mesh accepted')
        except ValueError: pass
        job.cancel()
        job=mesh_jobs.start_region(source,seed_triangle=seed,mode='Extrude',distance=2)
        wait(lambda:job.state!='running'); assert job.state=='ready',job.status()
        source.addProperty('App::PropertyBool','SC_Locked'); source.SC_Locked=True
        try: job.apply(); raise AssertionError('Locked mesh accepted')
        except ValueError: pass
        job.cancel()
        with tempfile.TemporaryDirectory() as folder:
            filename=str(Path(folder)/'region.FCStd'); doc.saveAs(filename)
            App.closeDocument(doc.Name); doc=App.openDocument(filename)
            assert doc.getObject('EditedMesh').Mesh.isSolid()
        check_collision_preview(c)
        print('PASS mesh region preview, move/rotate/extrude, placement, background apply, Undo/Redo, Cancel, MCP, stale/locks, save/reopen and collision preview',flush=True)
    finally:
        c.cancel(quiet=True)
        for job in list(mesh_jobs._jobs.values()):
            if job.doc==doc: job.cancel()
        App.closeDocument(doc.Name)
        if previous in App.listDocuments(): App.setActiveDocument(previous)
