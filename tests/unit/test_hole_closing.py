"""Deleting a hole's wall closes the hole, as in SketchUp."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.core import geometry as g
from simplecad.document import operations as ops

V = App.Vector


def plate(faceted=False):
    body = Part.makeBox(30, 20, 10)
    if faceted:
        corners = [V(10 + 1.7 * math.cos(math.tau * i / 48), 10 + 1.7 * math.sin(math.tau * i / 48), -1)
                   for i in range(48)]
        tool = Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 12))
    else:
        tool = Part.makeCylinder(1.7, 12, V(10, 10, -1))
    return body.cut(tool).cut(Part.makeCylinder(1.7, 12, V(20, 10, -1))).Solids[0]


def wall(shape, x):
    return ['Face%d' % (i + 1) for i, f in enumerate(shape.Faces)
            if f.Vertexes and all(abs((v.Point - V(x, 10, v.Point.z)).Length - 1.7) < 1e-3 for v in f.Vertexes)]


def rims(shape, x):
    return ['Edge%d' % (i + 1) for i, e in enumerate(shape.Edges)
            if all(abs((v.Point - V(x, 10, v.Point.z)).Length - 1.7) < 1e-3 and v.Point.z in (0, 10)
                   for v in e.Vertexes)]


class HoleClosingTests(unittest.TestCase):
    def check_closed(self, shape, result, removed_volume):
        self.assertEqual(result.ShapeType, 'Solid')
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume, shape.Volume + removed_volume, delta=1e-6)
        caps = [f for f in result.Faces if abs(abs(f.CenterOfMass.z - 5) - 5) < 1e-9]
        self.assertEqual(sorted(len(f.Wires) for f in caps), [2, 2])  # Only the other hole remains.

    def test_deleting_a_cylinder_wall_closes_the_hole(self):
        shape = plate()
        result = g.erase_elements(shape, wall(shape, 10))
        self.check_closed(shape, result, math.pi * 1.7 ** 2 * 10)

    def test_deleting_a_faceted_wall_with_its_rims_closes_the_hole(self):
        shape = plate(faceted=True)
        names = wall(shape, 10)
        self.assertEqual(len(names), 48)
        polygon = Part.Face(Part.makePolygon([V(10 + 1.7 * math.cos(math.tau * i / 48),
                                                10 + 1.7 * math.sin(math.tau * i / 48), 0)
                                              for i in range(49)])).Area
        result = g.erase_elements(shape, names + rims(shape, 10))
        self.check_closed(shape, result, polygon * 10)

    def test_deleting_the_faceted_half_of_a_bore_leaves_the_rest_blind(self):
        # A converted bore: faceted from the top down to z = 6, a true
        # cylinder below. Deleting the facets fills the top half; the lower
        # half stays, now closed by a flat cap at z = 6.
        body = Part.makeBox(30, 20, 10)
        corners = [V(10 + 1.7 * math.cos(math.tau * i / 48), 10 + 1.7 * math.sin(math.tau * i / 48), 6)
                   for i in range(48)]
        upper = Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 5))
        shape = body.cut(upper).cut(Part.makeCylinder(1.7, 7, V(10, 10, -1))).Solids[0]
        facets = ['Face%d' % (i + 1) for i, f in enumerate(shape.Faces)
                  if isinstance(f.Surface, Part.Plane) and f.BoundBox.ZMin > 5.9 and f.BoundBox.ZLength > 3.9
                  and abs(abs(f.normalAt(0, 0).z)) < 1e-9 and (f.CenterOfMass - V(10, 10, f.CenterOfMass.z)).Length < 2]
        self.assertEqual(len(facets), 48)
        result = g.erase_elements(shape, facets)
        self.assertEqual(result.ShapeType, 'Solid')
        self.assertTrue(result.isValid() and result.isClosed())
        top = next(f for f in result.Faces if abs(f.CenterOfMass.z - 10) < 1e-9)
        self.assertEqual(len(top.Wires), 1)  # The top is closed again.
        lower = [f for f in result.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual(len(lower), 1)  # The round lower bore is kept.
        self.assertAlmostEqual(result.Volume, 6000 - math.pi * 1.7 ** 2 * 6, delta=1e-6)

    def test_deleting_a_counterbore_wall_keeps_the_narrow_hole_below_it(self):
        shape = Part.makeBox(30, 20, 10).cut(Part.makeCylinder(3, 5, V(10, 10, 6))).cut(
            Part.makeCylinder(1.5, 12, V(10, 10, -1))).Solids[0]
        wall = next('Face%d' % (i + 1) for i, f in enumerate(shape.Faces)
                    if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 3) < 1e-9)
        result = g.erase_elements(shape, [wall])
        self.assertEqual(result.ShapeType, 'Solid')
        self.assertTrue(result.isValid() and result.isClosed())
        # The counterbore's space is filled: the narrow hole now ends at the
        # old step, capped there, and the top is closed.
        self.assertAlmostEqual(result.Volume, 6000 - math.pi * 1.5 ** 2 * 6, delta=1e-6)
        bores = [f for f in result.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual([round(f.Surface.Radius, 6) for f in bores], [1.5])
        self.assertAlmostEqual(bores[0].BoundBox.ZMax, 6)
        top = next(f for f in result.Faces if abs(f.CenterOfMass.z - 10) < 1e-9)
        self.assertEqual(len(top.Wires), 1)

    def test_part_of_a_wall_still_opens_the_solid(self):
        shape = plate(faceted=True)
        result = g.erase_elements(shape, wall(shape, 10)[:5])
        self.assertFalse(result.Solids)

    def test_deleting_a_rod_in_a_hole_leaves_the_part_alone(self):
        # A separate faceted rod sits in a plate's hole, its top rim exactly
        # on the hole's rim. A box selection takes the rod's faces and edges.
        doc = App.newDocument('RodInHole')
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        doc.UndoMode = 1
        body = ops.new_shape(doc, plate(faceted=True), 'Plate')
        corners = [V(10 + 1.7 * math.cos(math.tau * i / 48), 10 + 1.7 * math.sin(math.tau * i / 48), 4)
                   for i in range(48)]
        rod = ops.new_shape(doc, Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 6)), 'Rod')
        before = body.Shape.copy()
        side = [i for i, f in enumerate(rod.Shape.Faces) if abs(f.normalAt(0, 0).z) < .1]
        edges = sorted({j for i in side for e in rod.Shape.Faces[i].Edges
                        for j, x in enumerate(rod.Shape.Edges) if x.isSame(e)})
        ops.delete_selection([(rod, ['Face%d' % (i + 1) for i in side] + ['Edge%d' % (j + 1) for j in edges])])
        self.assertEqual(len(body.Shape.Faces), len(before.Faces))
        self.assertAlmostEqual(body.Shape.Volume, before.Volume, places=9)
        self.assertIsNone(doc.getObject('Rod'))

    def test_delete_is_one_undo_step(self):
        doc = App.newDocument('HoleClosing')
        doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        obj = ops.new_shape(doc, plate(), 'Plate')
        volume = obj.Shape.Volume
        ops.delete_selection([(obj, wall(obj.Shape, 20))])
        self.assertGreater(obj.Shape.Volume, volume)
        self.assertTrue(obj.Shape.isClosed())
        doc.undo()
        self.assertAlmostEqual(obj.Shape.Volume, volume, places=9)


if __name__ == '__main__':
    unittest.main()
