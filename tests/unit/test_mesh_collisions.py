"""Preview collision estimate: exact pair tests and broad phase, NumPy only."""
import unittest
import numpy as np
from simplecad.mesh import collisions as mc
from simplecad.mesh.region import Topology, RegionPlan
from test_mesh_region import grid
from test_mesh_retriangulate import perforated_plate


def pair(a, b):
    points = np.asarray(a+b, dtype=float)
    return points, np.asarray([(0, 1, 2), (3, 4, 5)])


def hits(a, b):
    points, faces = pair(a, b)
    return len(mc.find(points, faces, [0])) == 2


class PairTests(unittest.TestCase):
    def test_crossing_and_separated_triangles(self):
        flat = [(0, 0, 0), (4, 0, 0), (0, 4, 0)]
        self.assertTrue(hits(flat, [(1, 1, -1), (1, 1, 1), (3, 3, 1)]))
        self.assertFalse(hits(flat, [(1, 1, .1), (1, 1, 1), (3, 3, 1)]))
        self.assertFalse(hits(flat, [(5, 5, -1), (5, 5, 1), (6, 6, 1)]))
        # Passes the plane beyond the triangle's hypotenuse.
        self.assertFalse(hits(flat, [(3, 3, -1), (3, 3, 1), (5, 5, 1)]))

    def test_touching_is_not_an_intersection(self):
        flat = [(0, 0, 0), (4, 0, 0), (0, 4, 0)]
        self.assertFalse(hits(flat, [(1, 1, 0), (1, 1, 2), (2, 1, 2)]))
        self.assertFalse(hits(flat, [(4, 0, 0), (8, 0, 0), (4, 4, 0)]))

    def test_coplanar_overlap_containment_and_disjoint(self):
        flat = [(0, 0, 0), (4, 0, 0), (0, 4, 0)]
        self.assertTrue(hits(flat, [(1, 1, 0), (5, 1, 0), (1, 5, 0)]))
        self.assertTrue(hits(flat, [(.5, .5, 0), (1.5, .5, 0), (.5, 1.5, 0)]))
        self.assertTrue(hits([(.5, .5, 0), (1.5, .5, 0), (.5, 1.5, 0)], flat))
        self.assertFalse(hits(flat, [(3, 3, 0), (6, 3, 0), (3, 6, 0)]))

    def test_triangles_sharing_a_vertex_are_skipped(self):
        points = np.asarray([(0, 0, 0), (4, 0, 0), (0, 4, 0), (1, 1, -1), (1, 1, 1)], dtype=float)
        faces = np.asarray([(0, 1, 2), (0, 3, 4)])
        self.assertEqual(len(mc.find(points, faces, [0, 1])), 0)


class BroadPhaseTests(unittest.TestCase):
    def test_pairs_match_brute_force_once_each(self):
        rng = np.random.default_rng(4)
        for size in (1, 7, 40):
            points = rng.uniform(0, 10, (3*size*5, 3))
            # Mix small triangles with a few long slivers and large plates.
            points[::7] *= 3
            faces = np.arange(len(points)).reshape(-1, 3)
            tri = points[faces]
            candidates = rng.choice(len(faces), max(1, len(faces)//3), replace=False)
            a, b = mc.candidate_pairs(tri, candidates, 1e-6, budget=17)
            found = {tuple(sorted(p)) for p in zip(a.tolist(), b.tolist())}
            self.assertEqual(len(found), len(a))
            low, high = tri.min(axis=1)-1e-6, tri.max(axis=1)+1e-6
            expected = {tuple(sorted((int(i), int(j)))) for i in candidates for j in range(len(faces))
                        if i != j and np.all(low[i] <= high[j]) and np.all(high[i] >= low[j])}
            self.assertEqual(found, expected)

    def test_changed_triangles_for_move_flips_and_extrusion(self):
        t = Topology(*perforated_plate())
        selected = set(np.flatnonzero(t.normals[:, 0] > .999))
        plan = RegionPlan(t, selected)
        moved, faces = plan.transform(delta=(5, 0, 0))
        changed = mc.changed_triangles(t.points, moved, t.triangles, faces)
        moved_vertex = np.any(moved != t.points, axis=1)
        expected = moved_vertex[faces].any(axis=1) | np.any(faces != t.triangles, axis=1)
        np.testing.assert_array_equal(changed, np.flatnonzero(expected))
        p, f = grid(4); t = Topology(p, f); plan = RegionPlan(t, {0, 1})
        moved, faces = plan.transform('Extrude', distance=2)
        changed = mc.changed_triangles(t.points, moved, t.triangles, faces)
        # Untouched source triangles keep their numbers ahead of cap and walls.
        self.assertEqual(changed.min(), len(f)-2)
        self.assertEqual(changed.max(), len(faces)-1)


class EditTests(unittest.TestCase):
    def test_folding_a_plate_into_its_neighbor_is_found(self):
        p, f = grid(6)
        # Two stacked plates 0.5 apart; pushing a patch of the lower one up
        # by 1 passes through the upper plate.
        points = np.vstack((p, p+(0, 0, .5)))
        faces = np.vstack((f, f[:, ::-1]+len(p)))
        t = Topology(points, faces)
        selected = {2*(2*6+2), 2*(2*6+2)+1}
        plan = RegionPlan(t, selected, 2)
        moved, out = plan.transform(delta=(0, 0, 1))
        changed = mc.changed_triangles(t.points, moved, t.triangles, out)
        found = mc.find(moved, out, changed)
        self.assertTrue(len(found) and np.any(found >= len(f)))
        moved, out = plan.transform(delta=(0, 0, .2))
        self.assertEqual(len(mc.find(moved, out, mc.changed_triangles(t.points, moved, t.triangles, out))), 0)

    def test_too_many_candidates_defers_to_apply(self):
        p, f = grid(3)
        self.assertIsNone(mc.find(p, f, np.arange(len(f)), limit=5))


if __name__ == '__main__':
    unittest.main()


try:
    import FreeCAD as App
    import Mesh  # noqa: F401  Checked with the other native modules.
    import MeshPart
    import Part
except ImportError:
    App = None


@unittest.skipIf(App is None, 'needs FreeCAD')
class NativeAgreementTests(unittest.TestCase):
    """The preview estimate must agree with FreeCAD's Apply check."""

    @classmethod
    def setUpClass(cls):
        body = Part.makeCylinder(30, 15).cut(Part.makeCylinder(27, 15, App.Vector(0, 0, 2)))
        body = body.fuse(Part.makeBox(80, 12, 3, App.Vector(-40, -6, 0)))
        for x in (-34, 34):
            body = body.cut(Part.makeCylinder(2, 6, App.Vector(x, 0, -1)))
        body = body.cut(Part.makeCylinder(3, 8, App.Vector(0, 25, 8), App.Vector(0, 1, 0)))
        cls.mesh = MeshPart.meshFromShape(Shape=body.removeSplitter(), LinearDeflection=.05,
                                          AngularDeflection=.1, Relative=False)
        from simplecad.mesh.region_edit import from_mesh, CollisionError, edit
        cls.edit, cls.CollisionError = staticmethod(edit), CollisionError
        cls.t = from_mesh(cls.mesh)

    def patch(self, mask):
        return self.t.region(int(np.flatnonzero(mask)[0])+1)

    def test_preview_matches_native_self_intersections(self):
        t = self.t; c, n = t.centers, t.normals
        self.assertTrue(self.mesh.isSolid() and not self.mesh.hasSelfIntersections())
        patches = [self.patch((n[:, 0] < -.999) & (c[:, 0] < -39.9)),
                   self.patch((n[:, 2] > .999) & (abs(c[:, 2]-3) < 1e-3) & (c[:, 0] < -32)),
                   self.patch((n[:, 1] < -.999) & (c[:, 0] < -32) & (c[:, 2] < 3))]
        outcomes = set()
        for selected in patches:
            for rings in (1, 3):
                for delta in ((0, 3, 0), (0, -3, 0), (3, 0, 0), (0, 0, 2), (0, .3, 0)):
                    plan = RegionPlan(t, selected, rings)
                    moved, faces = plan.transform(delta=delta)
                    try:
                        plan.validate(moved, faces, 'Move')
                    except ValueError:
                        continue
                    found = mc.find(moved, faces, mc.changed_triangles(t.points, moved, t.triangles, faces))
                    triangles = sorted(int(i)+1 for i in plan.selected)
                    try:
                        self.edit(self.mesh, triangles, rings=rings, delta=delta)
                        native = set()
                    except self.CollisionError as error:
                        native = set(error.triangles)
                        self.assertTrue(native)
                    outcomes.add(bool(native))
                    self.assertEqual(bool(len(found)), bool(native), (rings, delta))
                    if native:
                        # Pairs only touching within tolerance may differ.
                        self.assertGreaterEqual(len(native & set(found.tolist())), .95*len(native))
        self.assertEqual(outcomes, {True, False})
