"""Valid surface pole edges must not prevent drawing elsewhere in the scene."""
import math
import unittest

import FreeCAD as App
import Part
from simplecad.modeling import arcs, drawing
from simplecad.document import operations as op

V = App.Vector


class DegenerateDrawingTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('DegenerateDrawingTest')
        self.doc.UndoMode = 1
        self.sphere = op.new_shape(self.doc, Part.makeSphere(5, V(100, 100, 100)), 'Sphere')
        self.before = self.sphere.Shape
        self.poles = [e for e in self.before.Edges if e.Degenerated]
        self.assertTrue(self.poles)
        # Exercise the real kernel topology responsible for the reported crash.
        with self.assertRaises(TypeError):
            _ = self.poles[0].Curve

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assert_sphere_unchanged(self):
        self.assertTrue(self.sphere.Shape.isSame(self.before))
        self.assertTrue(self.sphere.Shape.isValid())
        self.assertEqual(len([e for e in self.sphere.Shape.Edges if e.Degenerated]), len(self.poles))

    def test_free_line_undo_redo_with_unrelated_sphere(self):
        result, changed = op.draw_line(self.doc, V(), V(10, 0, 0))
        self.assertFalse(changed)
        self.assertFalse(result.Shape.Faces)
        self.assertAlmostEqual(result.Shape.Length, 10)
        name = result.Name
        self.assert_sphere_unchanged()
        self.doc.undo()
        self.assertIsNone(self.doc.getObject(name))
        self.doc.redo()
        self.assertAlmostEqual(self.doc.getObject(name).Shape.Length, 10)
        self.assert_sphere_unchanged()

    def test_triangle_completion_still_finds_real_segments(self):
        op.draw_line(self.doc, V(), V(10, 0, 0))
        op.draw_line(self.doc, V(10, 0, 0), V(0, 10, 0))
        result, changed = op.draw_line(self.doc, V(0, 10, 0), V())
        self.assertTrue(changed)
        self.assertEqual(len(result.Shape.Faces), 1)
        self.assertAlmostEqual(result.Shape.Area, 50)
        self.assert_sphere_unchanged()

    def test_border_connection_then_partition_with_sphere(self):
        ring = Part.makeBox(30, 30, 10).cut(Part.makeBox(20, 20, 12, V(5, 5, -1)))
        obj = op.new_shape(self.doc, ring, 'Frame')
        first, changed = op.draw_line(self.doc, V(0, 0, 10), V(5, 5, 10), obj)
        self.assertFalse(changed)  # One bridge across a ring does not enclose a region.
        self.assertFalse(first.Shape.Faces)
        name = first.Name
        result, changed = op.draw_line(self.doc, V(5, 5, 10), V(30, 0, 10), obj)
        self.assertTrue(changed)
        self.assertEqual(result, obj)
        self.assertEqual(len(obj.Shape.Faces), len(ring.Faces) + 1)
        self.assertIsNone(self.doc.getObject(name))
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume, ring.Volume)
        self.assert_sphere_unchanged()

    def test_arc_loop_ignores_loose_degenerate_edges(self):
        arc = arcs.two_point(V(-5, 0, 0), V(5, 0, 0), V(0, 0, 1), 5).edge()
        diameter = Part.makeLine(V(-5, 0, 0), V(5, 0, 0))
        for newest, existing in ((arc, diameter), (diameter, arc)):
            faces = arcs.completions([self.before], newest, self.poles + [existing])
            self.assertEqual(len(faces), 1)
            self.assertAlmostEqual(faces[0].Area, math.pi * 25 / 2)
        self.assertEqual(drawing.triangle_completions([self.before], V(), V(1, 0, 0)), [])
        self.assert_sphere_unchanged()

    def test_two_separate_corner_bridges_partition_ring(self):
        ring = Part.makeBox(30, 30, 10).cut(Part.makeBox(20, 20, 12, V(5, 5, -1)))
        obj = op.new_shape(self.doc, ring, 'Frame')
        first, changed = op.draw_line(self.doc, V(0, 0, 10), V(5, 5, 10), obj)
        self.assertFalse(changed)
        name = first.Name
        result, changed = op.draw_line(self.doc, V(30, 0, 10), V(25, 5, 10), obj)
        self.assertTrue(changed)
        self.assertEqual(result, obj)
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(len(obj.Shape.Faces), len(ring.Faces) + 1)
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume, ring.Volume)
        self.assertAlmostEqual(obj.Shape.Area, ring.Area)
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(name))
        self.assertEqual(len(obj.Shape.Faces), len(ring.Faces))
        self.doc.redo()
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(len(obj.Shape.Faces), len(ring.Faces) + 1)
        self.assert_sphere_unchanged()
