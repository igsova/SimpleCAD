"""A profile drawn across regions drawn earlier on a face divides each of them."""
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op

V = App.Vector
TOP = g.Plane.named('XY', V(0, 0, 20))


def top_areas(shape, z=20):
    return sorted(round(f.Area, 6) for f in shape.Faces
                  if abs(f.CenterOfMass.z - z) < 1e-9 and abs(g.face_normal(f).z) > .999999)


class OverlappingProfileGeometryTests(unittest.TestCase):
    def setUp(self):
        self.box = Part.makeBox(40, 30, 20)
        # The first rectangle, 15 x 12 in the corner of the top.
        self.first = g.divide_face_with_profile(self.box, g.rectangle(TOP, V(0, 0, 20), V(15, 12, 20)))

    def test_rectangle_over_a_rectangle_divides_both_regions(self):
        second = g.rectangle(TOP, V(8, 6, 20), V(25, 20, 20))
        result = g.divide_face_with_profile(self.first, second)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, 24000)
        self.assertAlmostEqual(result.Area, self.box.Area)
        # First only, overlap, second only and the rest of the top.
        self.assertEqual(top_areas(result), [42, 138, 196, 824])
        overlap = next(f for f in result.Faces if abs(f.Area - 42) < 1e-6)
        pulled = g.push_pull(result, overlap, 5)
        self.assertTrue(pulled.isValid())
        self.assertAlmostEqual(pulled.Volume, 24000 + 42 * 5)

    def test_circle_and_polygon_across_earlier_divisions(self):
        halves = g.divide_face_with_line(self.box, V(0, 15, 20), V(40, 15, 20))
        circle = g.circle(TOP, V(20, 15, 20), 5)
        result = g.divide_face_with_profile(halves, circle)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 24000)
        self.assertEqual(len(top_areas(result)), 4)
        self.assertAlmostEqual(sum(a for a in top_areas(result) if a < 100), circle.Area, places=5)
        hexagon = g.polygon(TOP, V(15, 12, 20), V(20, 12, 20), 6)
        result = g.divide_face_with_profile(self.first, hexagon)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 24000)
        self.assertEqual(len(top_areas(result)), 4)
        self.assertAlmostEqual(sum(top_areas(result)), 1200, places=5)

    def test_open_surface_regions_are_divided_too(self):
        sheet = g.divide_face_with_profile(Part.makePlane(40, 30, V(0, 0, 20)),
                                           g.rectangle(TOP, V(0, 0, 20), V(15, 12, 20)))
        result = g.divide_face_with_profile(sheet, g.rectangle(TOP, V(8, 6, 20), V(25, 20, 20)))
        self.assertTrue(result.isValid())
        self.assertEqual(top_areas(result), [42, 138, 196, 824])
        self.assertAlmostEqual(result.Area, 1200)

    def test_retracing_existing_edges_changes_nothing(self):
        halves = g.divide_face_with_line(self.box, V(0, 15, 20), V(40, 15, 20))
        self.assertIsNone(g.divide_face_with_profile(halves, g.rectangle(TOP, V(0, 0, 20), V(40, 30, 20))))

    def test_outline_off_the_faces_is_still_rejected(self):
        # Past the edge of the top.
        with self.assertRaises(ValueError):
            g.divide_face_with_profile(self.first, g.rectangle(TOP, V(8, 6, 20), V(50, 20, 20)))
        # Across a slot between two flat faces at the same height.
        slotted = self.box.cut(Part.makeBox(4, 30, 10, V(18, 0, 10)))
        with self.assertRaises(ValueError):
            g.divide_face_with_profile(slotted, g.rectangle(TOP, V(10, 5, 20), V(30, 20, 20)))


class OverlappingProfileDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('SimpleCADOverlappingProfiles')
        self.doc.UndoMode = 1
        self.box = op.new_shape(self.doc, Part.makeBox(40, 30, 20), 'Box')

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_second_profile_updates_the_part_in_one_undo_step(self):
        op.draw_profile(self.doc, g.rectangle(TOP, V(0, 0, 20), V(15, 12, 20)), self.box, 'Rectangle')
        for title, profile in (('Rectangle', g.rectangle(TOP, V(8, 6, 20), V(25, 20, 20))),
                               ('Circle', g.circle(TOP, V(15, 12, 20), 4)),
                               ('Polygon', g.polygon(TOP, V(4, 12, 20), V(7, 12, 20), 5))):
            with self.subTest(title):
                count, faces = self.doc.UndoCount, len(self.box.Shape.Faces)
                result, divided = op.draw_profile(self.doc, profile, self.box, title)
                self.assertIs(result, self.box)
                self.assertTrue(divided)
                self.assertEqual(len(self.doc.Objects), 1)
                self.assertGreater(len(self.box.Shape.Faces), faces)
                self.assertTrue(self.box.Shape.isValid())
                self.assertAlmostEqual(self.box.Shape.Volume, 24000)
                self.assertEqual(self.doc.UndoCount, count + 1)
        # Undo the polygon and the circle: the two rectangles' regions remain.
        self.doc.undo()
        self.doc.undo()
        self.assertEqual(top_areas(self.box.Shape), [42, 138, 196, 824])

    def test_rejected_profile_changes_nothing(self):
        op.draw_profile(self.doc, g.rectangle(TOP, V(0, 0, 20), V(15, 12, 20)), self.box, 'Rectangle')
        count, shape = self.doc.UndoCount, self.box.Shape.copy()
        with self.assertRaises(ValueError):
            op.draw_profile(self.doc, g.rectangle(TOP, V(8, 6, 20), V(50, 20, 20)), self.box, 'Rectangle')
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertTrue(self.box.Shape.isEqual(shape) or len(self.box.Shape.Faces) == len(shape.Faces))


if __name__ == '__main__':
    unittest.main()
