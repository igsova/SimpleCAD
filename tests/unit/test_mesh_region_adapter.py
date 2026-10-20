"""Native handoff contract and rejection paths, without loading FreeCAD/Qt."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import numpy as np
from test_mesh_transform import box, volume
from test_mesh_stretch_adapter import Vector, StrictMesh


class CheckedMesh(StrictMesh):
    def hasSelfIntersections(self): return False


def diagnostic_mesh(records):
    class IntersectingMesh(CheckedMesh):
        def hasSelfIntersections(self): return True
        def getSelfIntersections(self): return records
    return IntersectingMesh


def intersecting(*pairs):
    # MeshPy::getSelfIntersections returns (facet A, facet B, Vector, Vector)
    # records, not a flat array or a matrix of triangle indices.
    return diagnostic_mesh(tuple((a,b,Vector(-1.5,0,2),Vector(3,4.25,0))
                                 for a,b in pairs))


def adapter(factory=CheckedMesh):
    path=Path(__file__).resolve().parents[2]/'simplecad/mesh/region_edit.py'
    spec=importlib.util.spec_from_file_location('simplecad.mesh._region_adapter_test',path)
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'FreeCAD':NS(Vector=Vector),'Mesh':NS(Mesh=factory),
                                'simplecad.mesh.stretch':NS(check_source=lambda source: None)}):
        spec.loader.exec_module(module)
    return module


def conversion_stub():
    # Exact fingerprints come from the document observer cache in FreeCAD.
    stub=NS(cached_fingerprints=NS(get=lambda obj: obj.fingerprint))
    return patch.dict(sys.modules,{'simplecad.mesh.conversion':stub})


class AdapterTests(unittest.TestCase):
    def source(self):
        p,f=box()
        return CheckedMesh(([Vector(*v) for v in p.tolist()],list(map(tuple,f.tolist()))))

    def test_retriangulated_move_matches_preview_at_native_handoff(self):
        from test_mesh_retriangulate import perforated_plate
        from simplecad.mesh.region import Topology, RegionPlan
        p,f=perforated_plate(); t=Topology(p,f)
        selected=set(np.flatnonzero(t.normals[:,0]>.999))
        expected,triangles=RegionPlan(t,selected).transform(delta=(5,0,0))
        source=CheckedMesh(([Vector(*v) for v in p.tolist()],list(map(tuple,f.tolist()))))
        result,_=adapter().edit(source,sorted(int(i)+1 for i in selected),delta=(5,0,0))
        np.testing.assert_allclose(np.asarray(result.Topology[0]),expected)
        np.testing.assert_array_equal(result.Topology[1],triangles)
        np.testing.assert_array_equal(source.Topology[1],f)

    def test_native_collision_check_still_rejects_after_diagonal_repair(self):
        from test_mesh_retriangulate import perforated_plate
        from simplecad.mesh.region import Topology
        p,f=perforated_plate(); t=Topology(p,f)
        selected=sorted(int(i)+1 for i in np.flatnonzero(t.normals[:,0]>.999))
        source=CheckedMesh(([Vector(*v) for v in p.tolist()],list(map(tuple,f.tolist()))))
        with self.assertRaisesRegex(ValueError,'self-intersections'):
            adapter(intersecting((0,1))).edit(source,selected,delta=(5,0,0))
        np.testing.assert_array_equal(source.Topology[0],p)

    def test_native_handoff_for_all_modes(self):
        source=self.source(); old=np.asarray(source.Topology[0]).copy()
        for mode,values,expected in [('Move',{'delta':(0,0,3)},1300),
                                     ('Rotate',{'angle':5},None),('Extrude',{'distance':3},1300)]:
            with self.subTest(mode=mode):
                result,report=adapter().edit(source,[3,4],mode=mode,**values)
                self.assertTrue(result.isSolid()); self.assertEqual(report['region']['triangles'],2)
                if expected: self.assertAlmostEqual(volume(*map(np.asarray,result.Topology)),expected)
        np.testing.assert_array_equal(source.Topology[0],old)

    def test_native_intersections_and_bad_boundaries_rejected(self):
        with self.assertRaisesRegex(ValueError,'creates or changes self-intersections'):
            adapter(intersecting((2,3))).edit(self.source(),[3,4],delta=(0,0,1))
        class Open(CheckedMesh):
            def isSolid(self): return False
        with self.assertRaisesRegex(ValueError,'preserve the mesh boundary'):
            adapter(Open).edit(self.source(),[3,4],delta=(0,0,1))

    def test_unchanged_existing_intersections_allow_edits_elsewhere(self):
        collision=intersecting((0,1))
        source=collision(self.source().Topology)
        old=np.asarray(source.Topology[0]).copy()
        _,report=adapter(collision).edit(source,[3,4],delta=(0,0,1))
        self.assertEqual(report['self_intersecting_triangles_before'],2)
        self.assertEqual(report['self_intersecting_triangles'],2)
        self.assertIn('left unchanged',report['warnings'][0])
        np.testing.assert_array_equal(source.Topology[0],old)

    def test_same_collision_count_cannot_hide_changed_or_new_intersections(self):
        source=intersecting((2,3))(self.source().Topology)
        for delta in ((0,0,1),(0,0,1e-8)):
            with self.assertRaisesRegex(ValueError,'creates or changes self-intersections'):
                adapter(intersecting((2,3))).edit(source,[3,4],delta=delta)
        source=intersecting((0,1))(self.source().Topology)
        with self.assertRaisesRegex(ValueError,'creates or changes self-intersections'):
            adapter(intersecting((0,4))).edit(source,[3,4],delta=(0,0,1))

    def test_rejection_separates_changed_intersections_from_unchanged_defects(self):
        source=intersecting((0,1))(self.source().Topology)
        old=np.asarray(source.Topology[0]).copy()
        with self.assertRaises(ValueError) as caught:
            adapter(intersecting((0,1),(0,2))).edit(source,[3,4],delta=(0,0,1))
        message=str(caught.exception)
        self.assertIn('1 new or changed intersecting triangles; 2 unchanged pre-existing',message)
        self.assertIn('grow the selected region',message)
        self.assertIn('Original mesh unchanged',message)
        np.testing.assert_array_equal(source.Topology[0],old)

    def test_extrusion_rejection_does_not_recommend_inactive_transition_rings(self):
        with self.assertRaises(ValueError) as caught:
            adapter(intersecting((0,2))).edit(self.source(),[3,4],mode='Extrude',distance=3)
        self.assertIn('extrusion distance or change its direction',str(caught.exception))
        self.assertNotIn('Transition rings',str(caught.exception))

    def test_extrusion_renumbering_preserves_exact_baseline(self):
        # Extruding the bottom moves the untouched top from facets 2/3 to 0/1.
        source=intersecting((2,3))(self.source().Topology)
        _,report=adapter(intersecting((0,1))).edit(source,[1,2],mode='Extrude',distance=3)
        self.assertEqual(report['self_intersecting_triangles'],2)

    def test_resolved_existing_intersections_do_not_require_repair(self):
        source=intersecting((2,3))(self.source().Topology)
        _,report=adapter().edit(source,[3,4],delta=(0,0,1))
        self.assertEqual(report['self_intersecting_triangles'],0)
        self.assertEqual(report['warnings'],[])

    def test_incomplete_native_diagnostics_cannot_silently_allow_intersections(self):
        endpoints=(Vector(0,0,0),Vector(1,1,1))
        for records in (None,(),(None,),((0,1),),(0,1),
                        ((-1,0,*endpoints),),((0,12,*endpoints),),
                        ((0.,1.,*endpoints),),((True,1,*endpoints),),
                        ((0,1,*endpoints),None)):
            with self.subTest(records=records),self.assertRaisesRegex(ValueError,'Could not identify'):
                adapter().edit(diagnostic_mesh(records)(self.source().Topology),[3,4],delta=(0,0,1))

    def test_native_four_field_records_only_use_unique_facet_indices(self):
        # Three records reproduce the user's ragged (3, 4) NumPy error.
        # Facet 0 appears in multiple pairs, but must only be counted once.
        source=intersecting((0,1),(0,11),(1,11))(self.source().Topology)
        points,faces=source.Topology
        geometry=adapter().intersection_geometry(source)
        self.assertEqual(sum(geometry.values()),3)
        self.assertEqual(set(geometry),
                         {tuple(sorted(points[v] for v in faces[i])) for i in (0,1,11)})

    def test_clean_mesh_does_not_request_intersection_records(self):
        source=self.source()
        source.getSelfIntersections=lambda: self.fail('Clean meshes do not need diagnostics.')
        self.assertEqual(adapter().intersection_geometry(source),{})

    def test_duplicate_triangles_are_counted_not_hidden_by_coordinate_matching(self):
        points,faces=self.source().Topology
        original=intersecting((0,1))((points,faces))
        duplicate=intersecting((0,1),(1,12))((points,faces+[faces[0]]))
        m=adapter()
        self.assertEqual(sum((m.intersection_geometry(duplicate)-m.intersection_geometry(original)).values()),1)

    def test_noop_rejected(self):
        for mode in ('Move','Rotate'):
            with self.assertRaisesRegex(ValueError,'nonzero'):
                adapter().edit(self.source(),[3,4],mode=mode)

    def test_world_parameters_become_local_vectors_and_points(self):
        rotation=np.asarray([[0,0,1],[0,1,0],[-1,0,0.]])
        base=np.asarray([53.,-17,29]); points,faces=box()
        source=NS(Mesh=CheckedMesh(([Vector(*p) for p in (points@rotation.T+base).tolist()],list(map(tuple,faces.tolist())))),
                  Document=NS(Name='D'),Name='M',fingerprint='placed')
        inv=NS(multVec=lambda v: Vector(*(rotation.T@(np.asarray(v)-base))),
               Rotation=NS(multVec=lambda v: Vector(*(rotation.T@v))))
        source.Placement=NS(inverse=lambda:inv)
        with conversion_stub():
            params=adapter().parameters(source,seed_triangle=3,mode='Rotate',axis=rotation@(0,0,1),angle=5,pivot=base+(rotation@(5,5,10)))
            self.assertEqual(params['triangles'],[3,4]); np.testing.assert_allclose(params['axis'],(0,0,1))
            np.testing.assert_allclose(params['pivot'],(5,5,10))
            params=adapter().parameters(source,triangles=[3,4],delta=rotation@(2,3,4))
        np.testing.assert_allclose(params['delta'],(2,3,4))

    def test_topology_is_shared_until_the_mesh_or_placement_changes(self):
        module=adapter(); points,faces=box(); built=[]
        source=NS(Mesh=CheckedMesh(([Vector(*p) for p in points.tolist()],list(map(tuple,faces.tolist())))),
                  Document=NS(Name='D'),Name='M',fingerprint='first')
        identity=NS(multVec=lambda v: v,Rotation=NS(multVec=lambda v: v))
        source.Placement=NS(inverse=lambda: identity)
        build=module.from_mesh
        module.from_mesh=lambda mesh: built.append(mesh) or build(mesh)
        with conversion_stub():
            first=module.topology_for(source)
            self.assertIs(module.topology_for(source),first)
            module.parameters(source,triangles=[3,4],delta=(0,0,1))
            self.assertEqual(len(built),1)
            source.fingerprint='moved'
            self.assertIsNot(module.topology_for(source),first)
            self.assertEqual(len(built),2)


if __name__=='__main__': unittest.main()
