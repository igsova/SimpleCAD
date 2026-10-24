"""A rectangle drawn on a face divides it, as a circle or polygon does."""
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op

V = App.Vector
TOP = g.Plane.named('XY', V(0, 0, 20))
# Corners and area on the top of a 40 x 30 x 20 box: inside it, flush with
# one edge, in a corner, and across it from edge to edge.
CASES = {'inside': (V(10, 10, 20), V(25, 20, 20), 150),
         'edge': (V(10, 0, 20), V(20, 10, 20), 100),
         'corner': (V(0, 0, 20), V(10, 10, 20), 100),
         'strip': (V(10, 0, 20), V(20, 30, 20), 300)}


class RectangleRegionTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('SimpleCADRectangleRegions')
        self.doc.UndoMode = 1
        self.box = op.new_shape(self.doc, Part.makeBox(40, 30, 20), 'Box')

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def draw(self, first, second):
        rectangle = g.rectangle(TOP, first, second)
        result, divided = op.draw_profile(self.doc, rectangle, self.box, 'Rectangle')
        return rectangle, result, divided

    def region(self, rectangle):
        return next(f for f in self.box.Shape.Faces if coinc.same(f, rectangle))

    def restore(self, count):
        # Each case starts on the plain box, even after a failed one.
        while self.doc.UndoCount > count:
            self.doc.undo()
        self.assertEqual(len(self.box.Shape.Faces), 6)

    def test_rectangle_divides_the_top_in_one_undo_step(self):
        for name, (first, second, _) in CASES.items():
            count = self.doc.UndoCount
            with self.subTest(name):
                rectangle, result, divided = self.draw(first, second)
                self.assertTrue(divided)
                self.assertIs(result, self.box)
                self.assertEqual(len(self.doc.Objects), 1)
                self.assertTrue(self.box.Shape.isValid())
                self.assertAlmostEqual(self.box.Shape.Volume, 24000)
                self.region(rectangle)
                self.assertEqual(self.doc.UndoCount, count + 1)
            self.restore(count)

    def test_pulled_region_matches_a_separate_profile(self):
        # The volume and face count a separate profile on the box gave: sides
        # flush with the box's sides merge into them instead of keeping a seam.
        faces = {('inside', -5): 11, ('inside', 5): 11, ('edge', -5): 10, ('edge', 5): 10,
                 ('corner', -5): 9, ('corner', 5): 9, ('strip', -5): 10, ('strip', 5): 10}
        for (name, distance), count in faces.items():
            undo = self.doc.UndoCount
            with self.subTest(name=name, distance=distance):
                first, second, area = CASES[name]
                rectangle, _, _ = self.draw(first, second)
                op.extrude(self.box, self.region(rectangle), distance)
                self.assertTrue(self.box.Shape.isValid())
                self.assertAlmostEqual(self.box.Shape.Volume, 24000 + area * distance)
                self.assertEqual(len(self.box.Shape.Faces), count)
            self.restore(undo)

    def test_flush_boss_side_is_one_face(self):
        rectangle, _, _ = self.draw(*CASES['edge'][:2])
        op.extrude(self.box, self.region(rectangle), 5)
        front = [f for f in self.box.Shape.Faces if g.face_normal(f).y < -.999999]
        self.assertEqual(len(front), 1)
        self.assertAlmostEqual(front[0].Area, 40 * 20 + 10 * 5)

    def test_neighboring_region_survives_the_pull(self):
        first, _, _ = self.draw(*CASES['edge'][:2])
        second, _, _ = self.draw(V(20, 0, 20), V(30, 10, 20))
        op.extrude(self.box, self.region(first), 5)
        self.assertTrue(self.box.Shape.isValid())
        self.assertAlmostEqual(self.box.Shape.Volume, 24500)
        self.region(second)

    def test_rectangle_past_the_face_edge_divides_it_and_adds_the_rest(self):
        # As in SketchUp: the top is divided where the rectangle overlaps it,
        # and the part beyond the box's edge becomes a face of its own.
        count = self.doc.UndoCount
        _, result, divided = self.draw(V(30, 10, 20), V(50, 20, 20))
        self.assertTrue(divided)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(len(self.box.Shape.Faces), 7)
        self.assertAlmostEqual(self.box.Shape.Volume, 40 * 30 * 20, places=6)
        beyond = [o for o in self.doc.Objects if o != self.box]
        self.assertEqual(len(beyond), 1)
        self.assertAlmostEqual(beyond[0].Shape.Area, 100, places=6)
        self.assertAlmostEqual(beyond[0].Shape.BoundBox.XMin, 40, places=6)


if __name__ == '__main__':
    unittest.main()
