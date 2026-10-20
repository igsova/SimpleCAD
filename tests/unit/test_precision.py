"""Modeling precision: noise below it is flattened, merged or discarded."""
import random
import unittest

import FreeCAD as App
import Mesh
import Part

from simplecad.core import geometry as g, preferences
from simplecad.mesh import conversion as mesh_conversion, planar as mesh_planar

V = App.Vector


def noisy_plate_mesh(noise=.002, seed=7):
    """A 40 x 30 x 4 plate with a through-hole, its vertices jittered.

    Scanned or exported meshes are never exactly flat: every flat region is
    off by microns and slightly tilted, like the chassis this reproduces.
    """
    plate = Part.makeBox(40, 30, 4).cut(Part.makeCylinder(3, 4, V(20, 15, 0)))
    points, facets = plate.tessellate(.05)
    rng = random.Random(seed)
    moved = [V(p.x + rng.uniform(-noise, noise), p.y + rng.uniform(-noise, noise),
               p.z + rng.uniform(-noise, noise)) for p in points]
    return Mesh.Mesh([[moved[i] for i in facet] for facet in facets]), plate


class PrecisionPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.saved = preferences.load()
        self.addCleanup(preferences.save, self.saved)

    def test_default_is_a_tenth_of_a_millimeter(self):
        self.assertEqual(preferences.Settings().precision, 0.1)

    def test_saved_precision_is_clamped_to_its_range(self):
        from dataclasses import replace
        preferences.save(replace(self.saved, precision=0.25))
        self.assertAlmostEqual(preferences.precision(), 0.25)
        preferences.save(replace(self.saved, precision=50.0))
        self.assertAlmostEqual(preferences.precision(), preferences.RANGES['precision'][1])


class FlatteningTests(unittest.TestCase):
    def test_noisy_flat_faces_become_exact_aligned_planes(self):
        mesh, plate = noisy_plate_mesh()
        shape, report = mesh_conversion.convert(mesh, .1)
        self.assertTrue(shape.isValid() and shape.isClosed())
        caps = [f for f in shape.Faces if isinstance(f.Surface, Part.Plane) and f.Area > 500]
        self.assertEqual(len(caps), 2)
        for cap in caps:
            # Exactly axis-aligned, not tilted by micro-radians.
            self.assertEqual(abs(cap.Surface.Axis.z), 1.0)
        self.assertLess(max(v.Tolerance for v in shape.Vertexes), .005)
        shape.check(True)  # No BOP errors: booleans can use it.

    def test_booleans_on_the_converted_plate_are_exact(self):
        mesh, _ = noisy_plate_mesh()
        shape, _ = mesh_conversion.convert(mesh, .1)
        top = max(shape.Faces, key=lambda f: f.CenterOfMass.z if f.Area > 500 else -1)
        z = top.Surface.Position.z
        box = Part.makeBox(2, 2, 1, V(2, 2, z - .5))
        cut = shape.cut(box)
        self.assertEqual(len(cut.Solids), 1)
        self.assertAlmostEqual(shape.Volume - cut.Volume, 2.0, delta=1e-6)

    def test_parallel_regions_are_aligned_but_facets_of_a_curve_are_not(self):
        import numpy as np
        up = np.array([0.0, 0.0, 1.0])
        tilted = np.array([0.0, 2e-6, 1.0]) / np.linalg.norm([0.0, 2e-6, 1.0])
        facet = np.array([0.0, np.sin(np.radians(3)), np.cos(np.radians(3))])
        square = np.array([[x, y, 0.0] for x in (0.0, 10.0) for y in (0.0, 10.0)])
        planes = [(up, np.zeros(3), 100.0, square), (tilted, np.array([0.0, 0.0, .004]), 50.0, square + [0, 0, .004]),
                  (facet, np.array([0.0, 0.0, 5.0]), 10.0, square + [0, 0, 5.0])]
        normals = [tuple(np.asarray(n) / np.linalg.norm(n)) for n, *_ in planes]
        aligned = mesh_planar.regularize_planes([(n, c, w) for n, c, w, _ in planes], 20.0, .1)
        self.assertEqual(tuple(aligned[0][0]), (0.0, 0.0, 1.0))
        self.assertEqual(tuple(aligned[1][0]), (0.0, 0.0, 1.0))
        self.assertEqual(aligned[0][1], aligned[1][1])  # Same level within 0.1 mm.
        self.assertAlmostEqual(tuple(aligned[2][0])[1], normals[2][1])  # A 3 degree facet keeps its tilt.

    def test_curved_walls_keep_their_exact_tessellation(self):
        # The hole wall's vertices must stay on the true cylinder so that an
        # analytic fit later recovers the exact radius.
        body = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 20, V(20, 15, 0)))
        shape, _ = mesh_planar.reconstruct(Mesh.Mesh(body.tessellate(.25)), .01, lambda message: None)
        rim = [v.Point for v in shape.Vertexes if abs((v.Point - V(20, 15, v.Point.z)).Length - 6) < .05]
        self.assertTrue(rim)
        for point in rim:
            self.assertAlmostEqual((point - V(20, 15, point.z)).Length, 6, delta=1e-5)

    def test_weld_merges_sub_precision_slivers(self):
        mesh, _ = noisy_plate_mesh()
        points, facets = mesh.Topology
        # Split one vertex into two copies 0.01 mm apart to create slivers.
        doubled = [list(f) for f in facets]
        extra = V(points[doubled[0][0]]) + V(.01, 0, 0)
        triangles = [[V(points[i]) for i in f] for f in doubled]
        triangles[0][0] = extra
        broken = Mesh.Mesh(triangles)
        welded = mesh_conversion.weld(broken, .1)
        self.assertLess(welded.CountPoints, broken.CountPoints)
        self.assertFalse(welded.hasNonManifolds())


class NoiseRemovalTests(unittest.TestCase):
    def test_sliver_solids_below_precision_are_dropped(self):
        body = Part.makeBox(10, 10, 4)
        sliver = Part.makeBox(.001, 1, 4, V(20, 0, 0))
        kept = g.drop_noise(Part.makeCompound([body, sliver]), .1)
        self.assertEqual(len(kept.Solids), 1)
        self.assertAlmostEqual(kept.Volume, body.Volume)

    def test_real_pieces_are_kept(self):
        body = Part.makeBox(10, 10, 4)
        piece = Part.makeBox(1, 1, 4, V(20, 0, 0))
        kept = g.drop_noise(Part.makeCompound([body, piece]), .1)
        self.assertEqual(len(kept.Solids), 2)

    def test_through_push_from_a_slightly_tilted_face_leaves_no_skin(self):
        # The entry face leans by 2e-5 rad, as faces rebuilt from converted
        # meshes can; the exit face is exact. The hole must still open.
        tilt = 2.35e-5
        lo = [V(0, 0, 0), V(0, 12, 0), V(0, 12, 8), V(0, 0, 8)]
        hi = [V(9 + tilt * p.y, p.y, p.z) for p in lo]
        faces = [Part.Face(Part.makePolygon(lo + lo[:1])), Part.Face(Part.makePolygon(hi + hi[:1]))]
        for i in range(4):
            j = (i + 1) % 4
            faces.append(Part.Face(Part.makePolygon([lo[i], lo[j], hi[j], hi[i], lo[i]])))
        sewn = Part.Compound(faces)
        sewn.sewShape()
        block = Part.makeSolid(sewn.Shells[0])
        if block.Volume < 0:
            block.reverse()
        entry = max(block.Faces, key=lambda f: f.CenterOfMass.x)
        disk = Part.Face(Part.Wire(Part.makeCircle(1.7, V(9 + tilt * 6, 6, 4), g.face_normal(entry))))
        divided = block.generalFuse([disk])[0].Solids[0]
        profile = next(f for f in divided.Faces if f.CenterOfMass.x > 8 and f.Area < 10)
        stop = g.opposite_face(divided, profile)
        self.assertIsNotNone(stop)
        result = g.push_pull(divided, profile, stop.distance)
        exit_faces = [f for f in result.Faces if abs(f.CenterOfMass.x) < 1e-3]
        self.assertEqual(len(exit_faces), 1)
        self.assertEqual(len(exit_faces[0].Wires), 2)  # The exit has a hole.
        self.assertAlmostEqual(exit_faces[0].Area, 96 - profile.Area, delta=1e-3)

    def test_push_within_precision_of_the_far_face_goes_through(self):
        box = Part.makeBox(20, 20, 4)
        disk = Part.Face(Part.Wire(Part.makeCircle(3, V(10, 10, 4))))
        divided = box.generalFuse([disk])[0].Solids[0]
        face = next(f for f in divided.Faces if abs(f.CenterOfMass.z - 4) < 1e-6 and f.Area < 50)
        # 0.05 mm short of the bottom is within 0.1 mm: a clean through-hole.
        result = g.push_pull(divided, face, -3.95)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume, box.Volume - face.Area * 4, delta=1e-4)


if __name__ == '__main__':
    unittest.main()
