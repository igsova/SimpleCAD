"""Two-plane mesh transforms: watertight connectivity and mechanical dimensions."""
import unittest
from collections import Counter
import numpy as np
from simplecad.mesh.transform import Plan


def box():
    points = np.asarray([(x,y,z) for z in (0.,10.) for y in (0.,10.) for x in (0.,10.)])
    faces = [(0,2,3),(0,3,1),(4,5,7),(4,7,6),(0,1,5),(0,5,4),
             (2,6,7),(2,7,3),(0,4,6),(0,6,2),(1,3,7),(1,7,5)]
    return points, np.asarray(faces)


def volume(points, faces):
    tri = points[faces]
    return np.einsum('ij,ij->i', tri[:,0], np.cross(tri[:,1],tri[:,2])).sum()/6


def box_with_collinear_facet():
    # Subdivide a vertical face while retaining a collinear triangle along
    # its old edge, as found in exported STL files. All edges remain paired.
    points, faces = box()
    points = np.vstack((points, (points[0]+points[4])/2))
    faces = np.vstack((np.delete(faces, 8, axis=0), [(0,8,6), (8,4,6), (0,4,8)]))
    return points, faces


class MeshTransformTests(unittest.TestCase):
    def plan(self, lower=3, upper=7, reverse=False, normal=(0,0,1)):
        return Plan(*box(), (0,0,0), normal, lower, upper, reverse)

    def test_control_planes_split_crossing_triangles_with_shared_vertices(self):
        plan = self.plan()
        directed = Counter((a,b) for tri in plan.triangles.tolist() for a,b in zip(tri,tri[1:]+tri[:1]))
        self.assertTrue(all(n == 1 and directed[b,a] == 1 for (a,b),n in directed.items()))
        levels = plan.points[plan.triangles, 2]
        for plane in (3,7):
            self.assertFalse(np.any((levels.min(axis=1) < plane-1e-10) & (levels.max(axis=1) > plane+1e-10)))
        self.assertAlmostEqual(volume(plan.points, plan.triangles), 1000)
        self.assertEqual(len(plan.points) - len(directed)//2 + len(plan.triangles), 2)

    def test_extension_preserves_end_dimensions_and_volume(self):
        plan = self.plan(); moved = plan.transform((0,0,6))
        np.testing.assert_array_equal(moved[plan.weights == 0], plan.points[plan.weights == 0])
        np.testing.assert_allclose(moved[plan.weights == 1], plan.points[plan.weights == 1] + (0,0,6))
        self.assertAlmostEqual(volume(moved, plan.triangles), 1600)
        self.assertAlmostEqual(np.ptp(moved[:,2]), 16)
        np.testing.assert_array_equal(plan.transform((0,0,0)), plan.points)

    def test_sideways_region_move_preserves_volume_and_end_shapes(self):
        plan = self.plan(); moved = plan.transform((8,-4,0))
        self.assertAlmostEqual(volume(moved, plan.triangles), 1000)
        np.testing.assert_allclose(moved[plan.weights == 1] - plan.points[plan.weights == 1],
                                   np.tile((8,-4,0), (np.count_nonzero(plan.weights == 1),1)))

    def test_negative_side_and_compression(self):
        plan = self.plan(reverse=True)
        moved = plan.transform((0,0,-5))
        self.assertAlmostEqual(volume(moved,plan.triangles), 1500)
        np.testing.assert_array_equal(moved[plan.points[:,2] >= 7],plan.points[plan.points[:,2] >= 7])
        self.assertAlmostEqual(volume(plan.transform((0,0,2)),plan.triangles),800)
        for delta in ((0,0,4),(0,0,5)):
            with self.assertRaisesRegex(ValueError,'collapse'): plan.transform(delta)

    def test_planes_through_existing_vertices_and_edges(self):
        p,f = box()
        plan = Plan(p,f,(0,0,0),(1,1,1),10/np.sqrt(3),20/np.sqrt(3))
        edges = Counter(tuple(sorted((a,b))) for tri in plan.triangles.tolist() for a,b in zip(tri,tri[1:]+tri[:1]))
        self.assertTrue(all(n == 2 for n in edges.values()))
        tri = plan.points[plan.triangles]
        self.assertTrue(np.all(np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1) > 1e-12))
        self.assertAlmostEqual(volume(plan.points,plan.triangles),1000)

    def test_rigidly_rotated_input_is_equivariant(self):
        p,f = box(); rotation = np.asarray([[0,0,1],[0,1,0],[-1,0,0.]])
        origin = np.asarray([53.,-17.,29.])
        plan = Plan(p@rotation.T+origin, f, origin, rotation@(0,0,1),3,7)
        baseline = self.plan()
        np.testing.assert_allclose(plan.transform(rotation@(2,1,6)),baseline.transform((2,1,6))@rotation.T+origin)

    def test_untouched_triangles_are_retained_and_source_arrays_unchanged(self):
        p,f = box(); oldp,oldf = p.copy(),f.copy()
        plan = Plan(p,f,(0,0,0),(0,0,1),3,7)
        retained = set(map(tuple,plan.triangles.tolist()))
        self.assertTrue(set(map(tuple,f[:4])).issubset(retained))
        plan.transform((0,0,4))
        np.testing.assert_array_equal(p,oldp); np.testing.assert_array_equal(f,oldf)

    def test_invalid_parameters_and_collapsing_result_rejected(self):
        for low,high in ((7,3),(3,3),(-1,7),(3,11),(float('nan'),7),(False,7)):
            with self.assertRaises(ValueError): self.plan(low,high)
        with self.assertRaises(ValueError): self.plan(normal=(0,0,0))
        with self.assertRaises(ValueError): self.plan(reverse=1)
        for delta in ((0,0,-4),(0,0,-10),(float('inf'),0,0),(True,0,0),(0,0)):
            with self.assertRaises(ValueError): self.plan().transform(delta)

    def test_dense_mesh_preview_reuses_connectivity(self):
        p,f = box()
        # 1100 separate boxes exercise 13,200 triangles with no CAD objects.
        points=np.concatenate([p+(i*12,0,0) for i in range(1100)])
        faces=np.concatenate([f+8*i for i in range(1100)])
        plan=Plan(points,faces,(0,0,0),(1,0,0),4000,8000)
        topology=plan.triangles
        for delta in ((10,0,0),(20,0,0),(-10,0,0)):
            moved=plan.transform(delta)
            self.assertIs(plan.triangles,topology)
            self.assertEqual(moved.shape,plan.points.shape)

    def test_existing_collinear_facets_survive_both_plane_cuts(self):
        p, f = box_with_collinear_facet(); before = p.copy()
        for reverse, delta in ((False,(0,0,17)), (True,(0,0,-17)), (False,(3,4,0))):
            with self.subTest(reverse=reverse, delta=delta):
                plan = Plan(p,f,(0,0,0),(0,0,1),3,7,reverse)
                moved = plan.transform(delta)
                self.assertEqual(plan.degenerate_before,1)
                self.assertGreater(plan.validate_areas(moved),1)
                directed = Counter((a,b) for tri in plan.triangles.tolist() for a,b in zip(tri,tri[1:]+tri[:1]))
                self.assertTrue(all(n == 1 and directed[b,a] == 1 for (a,b),n in directed.items()))
                self.assertAlmostEqual(volume(moved,plan.triangles),1000+100*abs(delta[2]))
        np.testing.assert_array_equal(p,before)

    def test_unchanged_collinear_facets_at_rigid_ends_are_allowed(self):
        p,f = box_with_collinear_facet()
        plan = Plan(p,f,(0,0,0),(1,0,0),3,7)
        self.assertEqual(plan.validate_areas(plan.transform((17,0,0))),1)

    def test_existing_degeneracy_does_not_allow_new_collapsed_facets(self):
        p,f = box_with_collinear_facet()
        plan = Plan(p,f,(0,0,0),(0,0,1),3,7)
        moved = plan.transform((0,0,17))
        healthy = plan.triangles[np.flatnonzero(~plan.inherited_degenerate)[0]]
        moved[healthy[1]] = moved[healthy[0]]
        with self.assertRaisesRegex(ValueError,'created a collapsed triangle'):
            plan.validate_areas(moved)

    def test_cut_slivers_are_not_mistaken_for_original_degeneracy(self):
        plan = self.plan(lower=1e-10)
        self.assertEqual(plan.degenerate_before,0)
        with self.assertRaisesRegex(ValueError,'created a collapsed triangle'):
            plan.validate_areas(plan.transform((0,0,17)))


if __name__ == '__main__': unittest.main()
