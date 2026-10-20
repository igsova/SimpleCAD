"""Smooth surface fitting for mesh conversion: NumPy/SciPy only, no FreeCAD."""
import math
import unittest

import numpy as np

try:
    import scipy  # noqa: F401
    from simplecad.surfaces import fit as sf
except ImportError:  # The FreeCAD bundle ships SciPy; a bare Python may not.
    sf = None


def sheet(height, size=20.0, count=24):
    """An open grid mesh z = height(x, y), triangles facing +Z."""
    axis = np.linspace(-size/2, size/2, count+1)
    x, y = np.meshgrid(axis, axis, indexing='ij')
    points = np.c_[x.ravel(), y.ravel(), height(x.ravel(), y.ravel())]
    index = np.arange((count+1)**2).reshape(count+1, count+1)
    a, b, c, d = index[:-1, :-1].ravel(), index[1:, :-1].ravel(), index[1:, 1:].ravel(), index[:-1, 1:].ravel()
    faces = np.r_[np.c_[a, b, c], np.c_[a, c, d]]
    return points, faces


def sphere(radius=10.0, levels=3):
    """A closed icosphere with outward triangles."""
    t = (1+math.sqrt(5))/2
    points = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
              (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
             (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    points = [np.asarray(p, dtype=float) for p in points]
    for _ in range(levels):
        middle, refined = {}, []

        def split(i, j):
            key = (min(i, j), max(i, j))
            if key not in middle:
                middle[key] = len(points)
                points.append((points[i]+points[j])/2)
            return middle[key]
        for a, b, c in faces:
            ab, bc, ca = split(a, b), split(b, c), split(c, a)
            refined += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = refined
    points = np.asarray(points)
    return radius*points/np.linalg.norm(points, axis=1)[:, None], np.asarray(faces)


def tube(radius=5.0, height=10.0, sides=48, rows=6, origin=(1., -2, 3), axis=(1., 2, 3)):
    """An open faceted tube with outward triangles, and its axis."""
    origin, axis = np.asarray(origin), np.asarray(axis)/np.linalg.norm(axis)
    e1 = np.cross(axis, (1, 0, 0))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    angle, along = np.meshgrid(2*np.pi*np.arange(sides)/sides, np.linspace(0, height, rows+1))
    points = (origin+radius*(np.cos(angle.ravel())[:, None]*e1+np.sin(angle.ravel())[:, None]*e2)
              + along.ravel()[:, None]*axis)
    index = np.arange((rows+1)*sides).reshape(rows+1, sides)
    a, b = index[:-1].ravel(), np.roll(index[:-1], -1, axis=1).ravel()
    c, d = np.roll(index[1:], -1, axis=1).ravel(), index[1:].ravel()
    return points, np.r_[np.c_[a, b, c], np.c_[a, c, d]], origin, axis


def polyline_distance(points, polyline):
    a, b = polyline[:-1], polyline[1:]
    ab = b-a
    w = np.clip(np.einsum('qij,ij->qi', points[:, None, :]-a[None], ab)/np.maximum((ab*ab).sum(1), 1e-300), 0, 1)
    return np.linalg.norm(a[None]+w[..., None]*ab[None]-points[:, None, :], axis=2).min(axis=1)


@unittest.skipIf(sf is None, 'needs SciPy')
class CurveTests(unittest.TestCase):
    def test_straight_points_need_no_curve(self):
        points = np.c_[np.linspace(0, 10, 7), np.zeros(7), np.zeros(7)]
        self.assertIsNone(sf.fit_curve(points, .01))

    def test_curve_follows_the_whole_polyline_not_only_its_points(self):
        # Three points used to leave inner poles unconstrained; the minimum
        # norm solution then pulled them toward the origin, far off the path.
        for points in (np.asarray([[100., 50, 20], [101, 52, 20], [103, 52.5, 20]]),
                       np.c_[30+10*np.cos(np.linspace(0, 2, 40)), 30+10*np.sin(np.linspace(0, 2, 40)), np.full(40, 5.)]):
            fitted = sf.fit_curve(points, .025)
            curve = sf.curve_points(fitted, 2000)
            np.testing.assert_allclose(curve[[0, -1]], points[[0, -1]], atol=1e-9)
            self.assertLess(polyline_distance(curve, points).max(), .03)

    def test_two_dimensional_points(self):
        angle = np.linspace(0, math.pi, 30)
        points = np.c_[np.cos(angle), np.sin(angle)]
        curve = sf.curve_points(sf.fit_curve(points, .001), 500)
        self.assertLess(polyline_distance(np.c_[curve, np.zeros(500)], np.c_[points, np.zeros(30)]).max(), .0015)


@unittest.skipIf(sf is None, 'needs SciPy')
class FitTests(unittest.TestCase):
    def test_flat_sheet_is_one_plane(self):
        points, faces = sheet(lambda x, y: .2*x-.1*y+3)
        patches = sf.fit_patches(sf.Facets(points, faces), .1)
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0].surface.kind, 'plane')

    def test_curved_sheet_is_one_smooth_surface_within_tolerance(self):
        points, faces = sheet(lambda x, y: 4*np.sin(x/6)*np.cos(y/7))
        facets = sf.Facets(points, faces)
        patches = sf.fit_patches(facets, .05)
        self.assertEqual([patch.surface.kind for patch in patches], ['bspline'])
        surface = patches[0].surface
        self.assertLessEqual(surface.distance(points).max(), .05/2)
        # Inside every facet too, not just at its corners.
        weights = np.random.default_rng(1).dirichlet((1, 1, 1), size=(len(faces), 6))
        inside = np.einsum('tsk,tkd->tsd', weights, points[faces]).reshape(-1, 3)
        self.assertLessEqual(surface.distance(inside).max(), .05)
        # Surface parameters and points round-trip.
        np.testing.assert_allclose(surface.at(surface.parameters(points)), surface.project(points), atol=1e-9)

    def test_closed_sphere_is_covered_once_by_few_patches(self):
        points, faces = sphere()
        facets = sf.Facets(points, faces)
        patches = sf.fit_patches(facets, .1)
        covered = np.concatenate([patch.triangles for patch in patches])
        self.assertEqual(sorted(covered.tolist()), list(range(len(faces))))
        self.assertLessEqual(len(patches), 8)
        for patch in patches:
            corners = np.unique(faces[patch.triangles])
            self.assertLessEqual(patch.surface.distance(points[corners]).max(), .05+1e-9)

    def test_sharp_edges_separate_patches(self):
        points, faces = sheet(lambda x, y: np.where(x > 0, x, 0))
        patches = sf.fit_patches(sf.Facets(points, faces), .01)
        self.assertEqual(sorted(patch.surface.kind for patch in patches), ['plane', 'plane'])

    def test_needles_on_a_rim_take_its_normal_not_the_wall_at_their_tips(self):
        # Exporters close a curved hole's rim with needles from one far
        # vertex. Their long edges pair up, so no chain of them reaches a
        # real facet, and their short edges touch only the hole's wall.
        # Given the wall's normal, they joined its cylinder while their far
        # corner lay millimetres off it, and the smooth fit failed.
        rim = [1.45*np.asarray([math.cos(math.radians(a)), math.sin(math.radians(a)), 0]) for a in (49, 46, 43, 40, 37)]
        apex = np.asarray([3.078, .015, 0])
        points = np.asarray(rim+[p-(0, 0, 5) for p in rim]+[apex, apex+(-.007, .007, 0), (2.5, 2.5, 0), (2.5, -1.5, 0),
                                                                 (500, 0, 0), (501, 0, 0), (500, 1, 0)])
        a, near, x, y = 10, 11, 12, 13
        needles = [(k, k+1, a) for k in range(4)]
        faces = needles+[(0, a, near), (0, near, x), (a, 4, y), (14, 15, 16)]
        faces += [face for k in range(4) for face in ((k+1, k, 5+k), (k+1, 5+k, 6+k))]
        facets = sf.Facets(points, np.asarray(faces))
        self.assertTrue(facets.sliver[:5].all() and not facets.sliver[5:].any())
        np.testing.assert_allclose(facets.normals[:5], np.tile((0, 0, 1.), (5, 1)), atol=1e-9)
        # The wall still meets the rim at a sharp edge.
        self.assertTrue(facets.crease[[3*k for k in range(4)]].all())

    def test_non_manifold_mesh_is_rejected(self):
        points = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1.]])
        with self.assertRaises(ValueError):
            sf.Facets(points, np.asarray([[0, 1, 2], [1, 0, 3], [0, 1, 4]]))


@unittest.skipIf(sf is None, 'needs SciPy')
class CylinderTests(unittest.TestCase):
    def test_faceted_tube_is_one_cylinder_through_its_chords(self):
        points, faces, origin, axis = tube()
        patches = sf.fit_patches(sf.Facets(points, faces), .1)
        self.assertEqual([patch.surface.kind for patch in patches], ['cylinder'])
        cylinder = patches[0].surface
        self.assertTrue(cylinder.outward)
        self.assertAlmostEqual(abs(float(cylinder.axis @ axis)), 1, places=9)
        offset = cylinder.origin-origin
        self.assertLess(np.linalg.norm(offset-(offset @ axis)*axis), 1e-9)
        # The vertices are on the circle and the facets inside it; the
        # radius splits the difference.
        self.assertLess(cylinder.radius, 5)
        self.assertGreater(cylinder.radius, 5*math.cos(math.pi/48))
        centers = points[faces].mean(axis=1)
        self.assertLessEqual(max(cylinder.distance(points).max(), cylinder.distance(centers).max()), .075)
        np.testing.assert_allclose(cylinder.at(cylinder.parameters(points)), cylinder.project(points), atol=1e-9)

    def test_other_regions_are_not_cylinders(self):
        for points, faces in (sphere(), sheet(lambda x, y: .2*x+.1*y), sheet(lambda x, y: x*x/20)):
            facets = sf.Facets(points, faces)
            self.assertIsNone(sf.fit_cylinder(facets, np.arange(len(faces)), .1))
        # Nor is a tube thinner than its own faceting allows.
        points, faces, _, _ = tube(sides=12)
        self.assertIsNone(sf.fit_cylinder(sf.Facets(points, faces), np.arange(len(faces)), .1))

    def test_rims_without_corners_are_single_closed_chains(self):
        points, faces, _, axis = tube()
        facets = sf.Facets(points, faces)
        height = points[faces].mean(axis=1) @ axis
        labels = (height > height.mean()).astype(np.int64)
        chains, loops = sf.boundaries(facets, labels)
        self.assertEqual(len(chains), 3)
        for chain in chains:
            self.assertTrue(chain.loose)
            self.assertEqual(chain.vertices[0], chain.vertices[-1])
            self.assertEqual(len(chain.vertices), 49)
        self.assertEqual(sorted(len(runs) for patch_loops in loops.values() for runs in patch_loops), [1, 1, 1, 1])


@unittest.skipIf(sf is None, 'needs SciPy')
class LabelTests(unittest.TestCase):
    def test_sliver_joins_the_patch_across_its_long_edge(self):
        # A T-junction: vertex 4 lies on edge 0-1, closed by a zero-area
        # sliver. Left below that edge, it would spike the lower outline.
        points = np.asarray([[0, 0, 0], [4, 0, 0], [2, 2, 0], [2, -2, 0], [1.5, 0, 0]], dtype=float)
        faces = np.asarray([[0, 1, 2], [1, 0, 4], [0, 3, 4], [4, 3, 1]])
        facets = sf.Facets(points, faces)
        self.assertTrue(facets.sliver[1])
        labels = sf.settle_slivers(facets, np.asarray([0, 1, 1, 1]))
        self.assertEqual(labels.tolist(), [0, 0, 1, 1])

    def test_tooth_triangle_rejoins_the_patch_around_it(self):
        points, faces = sheet(lambda x, y: 0*x, count=4)
        facets = sf.Facets(points, faces)
        plane = sf.fit(facets, np.arange(len(faces)), .1)
        straight = (points[faces].mean(axis=1)[:, 0] < 0).astype(np.int64)
        neighbors = np.where(facets.twin >= 0, facets.owner[np.maximum(facets.twin, 0)], -1).reshape(-1, 3)
        tooth = next(t for t in np.flatnonzero(straight == 0) if any(straight[n] == 1 for n in neighbors[t] if n >= 0))
        labels = straight.copy()
        labels[tooth] = 1
        np.testing.assert_array_equal(sf.tidy(facets, labels, [plane, plane], .1), straight)
        # A surface that does not fit the triangle keeps it where it is.
        tilted = sf.PlaneFit(np.zeros(3), np.asarray([0, .6, .8]), 0)
        np.testing.assert_array_equal(sf.tidy(facets, labels, [tilted, plane], .1), labels)

    def test_boundaries_share_chains_and_orient_loops(self):
        points, faces = sheet(lambda x, y: 0*x, count=6)
        facets = sf.Facets(points, faces)
        centers = points[faces].mean(axis=1)
        labels = (centers[:, 0] > 0).astype(np.int64)
        chains, loops = sf.boundaries(facets, labels)
        shared = [chain for chain in chains if chain.right >= 0]
        self.assertTrue(shared and all(chain.smooth is False for chain in chains if chain.right < 0))
        for patch, patch_loops in loops.items():
            self.assertEqual(len(patch_loops), 1)
            outline = np.vstack([points[chains[c].vertices if forward else chains[c].vertices[::-1]][:-1]
                                 for c, forward in patch_loops[0]])
            x, y = outline[:, 0], outline[:, 1]
            self.assertGreater(np.sum(x*np.roll(y, -1)-np.roll(x, -1)*y), 0)
            for c, forward in patch_loops[0]:
                self.assertIn(patch, (chains[c].left, chains[c].right))


if __name__ == '__main__':
    unittest.main()
