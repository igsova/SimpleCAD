"""Analytic spheres, independent placement, native persistence and printing."""
import math
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part
import MeshPart
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.modeling import union
V = App.Vector


class SphereTests(unittest.TestCase):
    def test_complete_analytic_solid_at_exact_center(self):
        for center, radius in ((V(), 1), (V(12, -30, 47), 7.5)):
            shape = g.sphere(center, radius)
            self.assertTrue(shape.isValid() and shape.isClosed())
            self.assertEqual(shape.ShapeType, 'Solid')
            self.assertEqual(len(shape.Faces), 1)
            self.assertIsInstance(shape.Faces[0].Surface, Part.Sphere)
            self.assertAlmostEqual(shape.Volume, 4 * math.pi * radius ** 3 / 3, places=6)
            self.assertAlmostEqual(shape.Area, 4 * math.pi * radius ** 2, places=6)
            self.assertLess((shape.CenterOfMass - center).Length, 1e-7)
            for size in (shape.BoundBox.XLength, shape.BoundBox.YLength, shape.BoundBox.ZLength):
                self.assertAlmostEqual(size, 2 * radius, places=6)

    def test_invalid_radius_and_nonfinite_center(self):
        for radius in (0, -1, 1e-10, True, math.inf, math.nan):
            with self.assertRaises(ValueError): g.sphere(V(), radius)
        for center in (V(math.inf, 0, 0), V(0, math.nan, 0)):
            with self.assertRaises(ValueError): g.sphere(center, 5)

    def test_preview_does_not_build_kernel_shapes_and_all_rings_are_centered(self):
        center = V(25, -10, 43)
        with patch.object(Part, 'makeSphere', side_effect=AssertionError('preview kernel work')):
            for radius in (0, 4):
                rings = g.sphere_points(center, radius)
                self.assertEqual(len(rings), 3)
                for ring in rings:
                    self.assertEqual(ring[0], ring[-1])
                    for point in ring:
                        self.assertAlmostEqual((point-center).Length, radius, places=7)

    def test_intersecting_sphere_stays_separate_with_undo_redo_and_save(self):
        doc = App.newDocument('SphereNative'); doc.UndoMode = 1
        try:
            host = op.new_shape(doc, Part.makeBox(20, 20, 10), 'Host')
            before = host.Shape; count = doc.UndoCount
            ball = op.new_shape(doc, g.sphere(V(10, 10, 10), 4), 'Sphere')
            name = ball.Name
            self.assertEqual(len(doc.Objects), 2)
            self.assertTrue(host.Shape.isSame(before))
            self.assertNotIn('SC_Support', ball.PropertiesList)
            self.assertEqual(doc.UndoCount, count + 1)
            doc.undo(); self.assertIsNone(doc.getObject(name))
            doc.redo(); self.assertEqual(len(doc.getObject(name).Shape.Solids), 1)
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder) / 'sphere.FCStd')
                doc.saveAs(path)
                App.closeDocument(doc.Name)
                doc = App.openDocument(path)
                shape = doc.getObject(name).Shape
                self.assertTrue(shape.isValid() and shape.isClosed())
                self.assertIsInstance(shape.Faces[0].Surface, Part.Sphere)
                self.assertLess((shape.CenterOfMass-V(10, 10, 10)).Length, 1e-7)
        finally:
            App.closeDocument(doc.Name)

    def test_union_and_printable_mesh(self):
        ball = g.sphere(V(10, 10, 10), 4)
        result = union.combine([Part.makeBox(20, 20, 10), ball])
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, 4000 + ball.Volume / 2, places=5)
        for shape in (ball, result):
            mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=.1, AngularDeflection=.2, Relative=False)
            self.assertTrue(mesh.isSolid())
