"""Exercise the actual MCP read/dispatch methods with an indexed mesh stand-in."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock,patch
from simplecad.mesh.region import Topology
from test_mesh_transform import box


def api_module():
    path=Path(__file__).resolve().parents[2]/'simplecad/mcp/api.py'
    spec=importlib.util.spec_from_file_location('simplecad.mcp._region_api_test',path)
    m=importlib.util.module_from_spec(spec)
    stubs={name:NS() for name in ('FreeCAD','FreeCADGui','Part','simplecad.core.geometry','simplecad.document.operations',
              'simplecad.modeling.rotation','simplecad.modeling.slicing','simplecad.modeling.joints','simplecad.core.preferences',
              'simplecad.document.visibility','simplecad.document.appearance','simplecad.document.locking')}
    stubs.update({'simplecad.mesh.conversion':NS(is_mesh=lambda obj:True,cached_fingerprints=NS(get=lambda obj:obj.fingerprint)),
                  'simplecad.gui.qt':NS(QtCore=NS(),QtWidgets=NS())})
    with patch.dict(sys.modules,stubs): spec.loader.exec_module(m)
    return m


class RegionMCPTests(unittest.TestCase):
    def setUp(self):
        self.m=api_module(); self.api=self.m.ModelAPI(); self.doc=NS(Name='D')
        self.owner=NS(Document=self.doc,Name='M',Mesh=box(),fingerprint='unchanged')
        self.api.object=lambda doc,name:self.owner
        self.api.stamp=lambda doc,**args:dict(revision='rev',**args)
        self.api.summary=lambda obj,full:dict(name=obj.Name)
        self.from_mesh=Mock(side_effect=lambda mesh:Topology(*mesh))

    def test_paging_region_growth_and_cached_geometry_invalidation(self):
        from test_mesh_region_adapter import adapter
        edit=adapter(); edit.from_mesh=self.from_mesh
        with patch.dict(sys.modules,{'simplecad.mesh.region_edit':edit,'simplecad.mesh.conversion':
                                     NS(cached_fingerprints=NS(get=lambda obj:obj.fingerprint))}):
            reply=self.api.execute('inspect_mesh_triangles',self.doc,{'object':'M','offset':2,'limit':1})
            self.assertEqual(reply['total'],12); self.assertEqual(reply['triangles'][0]['triangle'],3)
            self.assertEqual(reply['triangles'][0]['normal'],[0,0,1])
            reply=self.api.execute('inspect_mesh_region',self.doc,{'object':'M','seed_triangle':3,'limit':1})
            self.assertEqual(reply['total'],2); self.assertEqual(reply['triangles'],[3]); self.assertEqual(reply['region']['area'],100)
            reply=self.api.execute('inspect_mesh_region',self.doc,{'object':'M','triangles':[3,4],'grow':1})
            self.assertGreater(reply['total'],2); self.assertEqual(self.from_mesh.call_count,1)
            self.owner.fingerprint='changed'
            self.api.execute('inspect_mesh_triangles',self.doc,{'object':'M','offset':99})
            self.assertEqual(self.from_mesh.call_count,2)
            with self.assertRaisesRegex(ValueError,'either'):
                self.api.execute('inspect_mesh_region',self.doc,{'object':'M'})

    def test_job_dispatch_and_operation_type_checks(self):
        job=NS(operation='region',status=Mock(return_value={'job_id':'job','status':'ready'}),
               apply=Mock(return_value=NS(Name='EditedMesh')),cancel=Mock())
        jobs=NS(start_region=Mock(return_value=job),get=Mock(return_value=job))
        with patch.dict(sys.modules,{'simplecad.jobs.mesh':jobs}),patch.object(__import__('simplecad.jobs').jobs, 'mesh',jobs,create=True):
            self.api.execute('edit_mesh_region',self.doc,{'object':'M','seed_triangle':3,'mode':'Extrude','distance':2})
            jobs.start_region.assert_called_once_with(self.owner,seed_triangle=3,mode='Extrude',distance=2)
            reply=self.api.execute('finish_mesh_region',self.doc,{'job_id':'job'})
            self.assertEqual(reply['object']['name'],'EditedMesh'); job.apply.assert_called_once()
            self.api.execute('cancel_mesh_region',self.doc,{'job_id':'job'}); job.cancel.assert_called_once()
            job.operation='stretch'
            with self.assertRaisesRegex(ValueError,'not a mesh region'):
                self.api.execute('finish_mesh_region',self.doc,{'job_id':'job'})

    def test_read_selection_includes_active_preview_without_mutating_it(self):
        session=NS(closed=False,source=self.owner,selected={3,2},
                   values=lambda:dict(mode='Move',delta=[0,0,5],rings=1),
                   validation_error='Intersection detected')
        self.api.controller=lambda:NS(mesh_region_session=session)
        self.m.Gui.Selection=NS(getSelectionEx=lambda name:[])
        result=self.api.execute('get_selection',self.doc,{})
        self.assertEqual(result['targets'],[])
        region=result['mesh_region']
        self.assertEqual(region['triangles'],[3,4])
        self.assertEqual(region['parameters']['delta'],[0,0,5])
        self.assertEqual(region['validation_error'],'Intersection detected')
        self.assertFalse(region['truncated'])
        self.assertEqual(session.selected,{2,3})
        session.selected=set(range(1001))
        region=self.api.execute('get_selection',self.doc,{})['mesh_region']
        self.assertEqual(len(region['triangles']),1000)
        self.assertEqual(region['total'],1001)
        self.assertTrue(region['truncated'])
        for closed,document in ((True,self.doc),(False,NS(Name='Other'))):
            session.closed=closed; self.owner.Document=document
            self.assertNotIn('mesh_region',self.api.execute('get_selection',self.doc,{}))


if __name__=='__main__': unittest.main()
