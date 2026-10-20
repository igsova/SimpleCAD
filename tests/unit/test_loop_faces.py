"""Drawing an edge that closes a flat loop creates its face, as in SketchUp."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.modeling import drawing
from simplecad.document import operations as ops

V = App.Vector


class LoopFaceTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('LoopFaces')
        self.doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(self.doc.Name))

    def box_without(self, *removed):
        box = Part.makeBox(20, 10, 8)
        keep = [f for f in box.Faces if not any(test(f.CenterOfMass) for test in removed)]
        return ops.new_shape(self.doc, Part.makeShell(keep), 'Opened')

    def test_edge_along_two_missing_faces_restores_them_and_the_solid(self):
        # Top and front are gone: the opening is one bent loop of six edges.
        obj = self.box_without(lambda c: abs(c.z - 8) < 1e-9, lambda c: abs(c.y) < 1e-9)
        self.assertEqual(len(drawing.open_boundary(obj.Shape)), 6)
        result, changed = ops.draw_line(self.doc, V(0, 0, 8), V(20, 0, 8), obj)
        self.assertTrue(changed)
        self.assertIs(result, obj)
        shape = obj.Shape
        self.assertEqual(len(shape.Faces), 6)
        self.assertTrue(shape.isValid() and shape.isClosed())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, 20 * 10 * 8, places=6)

    def test_missing_face_closes_with_its_open_boundary(self):
        box = Part.makeBox(20, 10, 8)
        keep = [f for f in box.Faces if abs(f.CenterOfMass.y) > 1e-9]
        shell = Part.makeShell(keep)
        obj = ops.new_shape(self.doc, shell, 'Opened')
        # The front is open; its bottom edge exists, so draw the top one.
        faces = drawing.loop_completions([obj.Shape], Part.makeLine(V(0, 0, 8), V(20, 0, 8)))
        self.assertTrue(faces)

    def test_three_loose_lines_and_a_fourth_make_a_rectangle(self):
        for a, b in ((V(0, 0, 0), V(10, 0, 0)), (V(10, 0, 0), V(10, 5, 0)), (V(10, 5, 0), V(0, 5, 0))):
            ops.draw_line(self.doc, a, b)
        result, changed = ops.draw_line(self.doc, V(0, 5, 0), V(0, 0, 0))
        self.assertTrue(changed)
        self.assertEqual(len(result.Shape.Faces), 1)
        self.assertAlmostEqual(result.Shape.Area, 50, places=6)
        self.assertFalse([o for o in self.doc.Objects if o.Shape.Edges and not o.Shape.Faces])

    def plate_with_hole(self, placement=None):
        plate = Part.makeBox(20, 20, 4).cut(Part.makeCylinder(3, 4, V(10, 10, 0)))
        if placement is not None:
            plate.Placement = placement
        return ops.new_shape(self.doc, plate, 'Plate')

    def test_line_across_a_circular_hole_covers_it_with_two_faces(self):
        obj = self.plate_with_hole()
        volume = obj.Shape.Volume
        # A chord off the center splits the hole's rim into a large and a
        # small side; each side becomes one face.
        result, changed = ops.draw_line(self.doc, V(13, 10, 4), V(10, 13, 4), obj)
        self.assertTrue(changed)
        self.assertIsNot(result, obj)  # A closed solid keeps its topology.
        self.assertEqual(len(result.Shape.Faces), 2)
        self.assertAlmostEqual(result.Shape.Area, math.pi * 9, places=6)
        self.assertTrue(obj.Shape.isValid())
        self.assertAlmostEqual(obj.Shape.Volume, volume, places=9)

    def test_hole_rim_on_a_placed_shape_splits_in_place(self):
        placement = App.Placement(V(9, -3, 2), App.Rotation(V(0, 0, 1), 30))
        obj = self.plate_with_hole(placement)
        center = placement.multVec(V(10, 10, 4))
        rim = next(e for e in obj.Shape.Edges if isinstance(e.Curve, Part.Circle)
                   and (e.Curve.Center - center).Length < 1e-6)
        first = rim.valueAt(.3)
        second = rim.valueAt(2.9)
        pieces = drawing.split_at(rim, (first, second), .1)
        self.assertEqual(len(pieces), 3)
        for piece in pieces:
            self.assertLess(rim.distToShape(piece)[0], 1e-9)
        faces = drawing.loop_completions([obj.Shape], Part.makeLine(first, second))
        self.assertEqual(len(faces), 2)
        self.assertAlmostEqual(sum(f.Area for f in faces), math.pi * 9, places=6)

    def test_profile_around_a_hole_imprints_the_face_and_keeps_the_hole(self):
        from simplecad.core import geometry as g
        obj = self.plate_with_hole()
        area, volume = obj.Shape.Area, obj.Shape.Volume
        plane = g.Plane.named("XY", V(10, 10, 4))
        hexagon = g.polygon(plane, V(10, 10, 4), V(10, 15, 4), 6)
        result, changed = ops.draw_polygon(self.doc, hexagon, obj)
        self.assertTrue(changed)
        self.assertIs(result, obj)
        # The rest of the top face keeps the hexagon as its inner boundary;
        # the ring between hexagon and hole is the new face.
        ring = [f for f in obj.Shape.Faces if abs(f.CenterOfMass.z - 4) < 1e-9
                and len(f.Wires) == 2 and f.Area < hexagon.Area]
        self.assertEqual(len(ring), 1)
        self.assertAlmostEqual(ring[0].Area, hexagon.Area - math.pi * 9, places=6)
        self.assertAlmostEqual(obj.Shape.Area, area, places=6)
        self.assertAlmostEqual(obj.Shape.Volume, volume, places=6)

    def test_erasing_the_diagonal_of_a_slightly_twisted_quad_merges_it(self):
        from simplecad.core import geometry as g
        # Converted walls can be twisted by microns: the fourth corner lies
        # 1e-5 mm off the plane of the other three.
        a, b, c, d = V(0, 0, 0), V(12, 0, 0), V(12, 0, 8), V(0, 1e-5, 8)
        shell = Part.makeShell([Part.Face(Part.makePolygon([a, b, c, a])),
                                Part.Face(Part.makePolygon([a, c, d, a]))])
        shell.sewShape()
        diagonal = next(i for i, e in enumerate(shell.Edges, 1)
                        if {tuple(v.Point) for v in e.Vertexes} == {tuple(a), tuple(c)})
        merged = g.erase_elements(shell, ['Edge%d' % diagonal])
        self.assertEqual(len(merged.Faces), 1)
        self.assertEqual(len(merged.Faces[0].Edges), 4)
        self.assertAlmostEqual(merged.Area, shell.Area, places=6)
        self.assertTrue(merged.isValid())

    def test_an_edge_closing_nothing_makes_no_face(self):
        obj = self.box_without(lambda c: abs(c.z - 8) < 1e-9)
        faces = drawing.loop_completions([obj.Shape], Part.makeLine(V(0, 0, 8), V(5, 20, 30)))
        self.assertEqual(faces, [])


if __name__ == '__main__':
    unittest.main()
