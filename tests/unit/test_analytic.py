"""Manual analytic circle/cylinder fitting from polygonal selections."""
import math
import unittest

import FreeCAD as App
import Mesh
import Part

from simplecad.modeling import analytic
from simplecad.document import locking
from simplecad.mesh import planar as mesh_planar
from simplecad.document import operations as ops


def faceted(shape, deviation=.25):
    """A converted-style solid: merged planar faces, faceted curved walls.

    This is the ordinary editable output of Make mesh editable for the parts
    whose hole recognition is skipped, so rim replacement stays manual.
    """
    mesh = Mesh.Mesh(shape.tessellate(deviation))
    result, _ = mesh_planar.reconstruct(mesh, .01, lambda message: None)
    return result


def _near_hole(point, center, axis, radius, z_low, z_high, slack):
    offset = point - App.Vector(*center)
    axial = offset.dot(axis)
    radial = (offset - axis * axial).Length
    return abs(radial - radius) <= slack and z_low - slack <= axial <= z_high + slack


def hole_elements(shape, center, axis, radius, z_low, z_high, slack=.01, faces=False):
    """Subelement names of the faceted hole rims (edges) or wall (faces)."""
    names = []
    if faces:
        for index, face in enumerate(shape.Faces, 1):
            if face.Vertexes and all(_near_hole(v.Point, center, axis, radius, z_low, z_high, slack)
                                     for v in face.Vertexes):
                names.append('Face%d' % index)
    else:
        for index, edge in enumerate(shape.Edges, 1):
            if all(_near_hole(v.Point, center, axis, radius, z_low, z_high, slack)
                   for v in edge.Vertexes):
                names.append('Edge%d' % index)
    return names


AXIS = App.Vector(0, 0, 1)


class AnalyticFitTests(unittest.TestCase):
    def test_two_polygonal_rims_fit_a_cylinder(self):
        points = []
        for z in (0, 12):
            points.append([App.Vector(7 * math.cos(i * math.tau / 48),
                                      7 * math.sin(i * math.tau / 48), z)
                           for i in range(48)])
        edges = []
        for ring in points:
            edges.extend(Part.makeLine(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))
        fit = analytic._fit_cloud(analytic._unique_points(edges))
        self.assertAlmostEqual(fit['height'], 12, places=9)
        self.assertAlmostEqual(fit['radius'], 7, places=6)
        self.assertLess(fit['residual'], 1e-8)

    def test_one_polygonal_rim_fits_a_circle(self):
        points = [App.Vector(4 * math.cos(i * math.tau / 32),
                             4 * math.sin(i * math.tau / 32), 3)
                  for i in range(32)]
        edges = [Part.makeLine(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
        fit = analytic._fit_cloud(analytic._unique_points(edges))
        self.assertEqual(fit['height'], 0)
        self.assertAlmostEqual(fit['radius'], 4, places=6)


class AnalyticHoleTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('AnalyticHoles'); self.doc.UndoMode = 1
        self.body = Part.makeBox(40, 30, 20).cut(
            Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        self.obj = ops.new_shape(self.doc, faceted(self.body), 'Plate')
        self.facets = len(self.obj.Shape.Faces)

    def tearDown(self):
        locking.forget_document(self.doc.Name)
        App.closeDocument(self.doc.Name)

    def rim_names(self, **kwargs):
        return hole_elements(self.obj.Shape, (20, 15, 0), AXIS, 6, 0, 20, **kwargs)

    def test_both_rims_replace_the_faceted_hole_in_place(self):
        names = tuple(self.rim_names())
        self.assertGreaterEqual(len(names), 16)
        target = analytic.prepare([(self.obj, names)])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        self.assertAlmostEqual(target['radius'], 6, places=4)
        self.assertAlmostEqual(target['height'], 20, places=4)
        result = analytic.apply(target, 'hole')
        self.assertIs(result, self.obj)
        shape = self.obj.Shape
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        curved = [face for face in shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(curved[0].Surface.Radius, 6, places=5)
        for height in (0, 20):
            face = next(f for f in shape.Faces
                        if abs(f.CenterOfMass.z - height) < 1e-6 and f.Area > 1000)
            circles = [edge for edge in face.Edges
                       if isinstance(edge.Curve, Part.Circle)
                       and abs(edge.Curve.Radius - 6) < 1e-6]
            self.assertEqual(len(circles), 1, 'rim at z=%d must become one circle' % height)
        self.assertAlmostEqual(shape.Volume, self.body.Volume, delta=.3)
        self.assertLess(len(shape.Faces), self.facets)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), self.facets)  # facets restored

    def test_single_rim_is_paired_with_the_opposite_rim(self):
        top = tuple(name for name in self.rim_names()
                    if all(abs(v.Point.z - 20) < 1e-6 for v in
                           self.obj.Shape.Edges[int(name[4:]) - 1].Vertexes))
        self.assertGreaterEqual(len(top), 8)
        target = analytic.prepare([(self.obj, top)])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        self.assertAlmostEqual(target['height'], 20, places=4)
        analytic.apply(target, 'hole')
        curved = [face for face in self.obj.Shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(self.obj.Shape.Volume, self.body.Volume, delta=.3)
        self.assertTrue(self.obj.Shape.isValid() and self.obj.Shape.isClosed())

    def test_selected_wall_facets_replace_the_hole(self):
        walls = tuple(self.rim_names(faces=True))
        self.assertGreaterEqual(len(walls), 8)
        target = analytic.prepare([(self.obj, walls)])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        analytic.apply(target, 'hole')
        curved = [face for face in self.obj.Shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertTrue(self.obj.Shape.isValid() and self.obj.Shape.isClosed())
        self.assertAlmostEqual(self.obj.Shape.Volume, self.body.Volume, delta=.3)

    def test_blind_hole_keeps_its_depth(self):
        blind = Part.makeBox(40, 30, 20).cut(
            Part.makeCylinder(6, 10, App.Vector(20, 15, 10)))
        self.obj.Shape = faceted(blind)
        walls = tuple(hole_elements(self.obj.Shape, (20, 15, 10), AXIS, 6, 0, 10,
                                    faces=True))
        self.assertGreaterEqual(len(walls), 8)
        target = analytic.prepare([(self.obj, walls)])
        self.assertTrue(target['can_cut'])
        analytic.apply(target, 'hole')
        shape = self.obj.Shape
        curved = [face for face in shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        # The flat hole bottom survives, now bounded by the analytic circle.
        bottom = sum(f.Area for f in shape.Faces if abs(f.CenterOfMass.z - 10) < 1e-6 and abs(f.normalAt(0, 0).z) > .9)
        self.assertAlmostEqual(bottom, math.pi * 36, delta=.05)
        self.assertAlmostEqual(shape.Volume, blind.Volume, delta=.3)
        # Nothing was cut deeper than the original hole.
        self.assertTrue(shape.isInside(App.Vector(20, 15, 9.5), 1e-7, True))
        self.assertFalse(shape.isInside(App.Vector(20, 15, 10.5), 1e-7, False))

    def test_boss_wall_is_rebuilt_in_place_too(self):
        # The rebuild is symmetric: a faceted boss becomes an analytic cylinder
        # the same way a hole does, without adding or removing its slivers.
        boss = Part.makeBox(20, 20, 5).fuse(
            Part.makeCylinder(4, 10, App.Vector(10, 10, 5)))
        self.obj.Shape = faceted(boss)
        walls = tuple(hole_elements(self.obj.Shape, (10, 10, 5), AXIS, 4, 0, 10,
                                    faces=True))
        self.assertGreaterEqual(len(walls), 8)
        target = analytic.prepare([(self.obj, walls)])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        analytic.apply(target, 'hole')
        shape = self.obj.Shape
        curved = [face for face in shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(curved[0].Surface.Radius, 4, places=5)
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        self.assertAlmostEqual(shape.Volume, boss.Volume, delta=.3)
        # The boss top disk and the plate face around its base both carry the
        # analytic circle now.
        circles = [edge for edge in shape.Edges
                   if isinstance(edge.Curve, Part.Circle)
                   and abs(edge.Curve.Radius - 4) < 1e-6]
        self.assertEqual(len(circles), 2)

    def test_partial_rim_selection_stays_conservative(self):
        def angle(name):
            point = self.obj.Shape.Edges[int(name[4:]) - 1].Vertexes[0].Point
            return math.atan2(point.y - 15, point.x - 20) % math.tau
        partial = tuple(name for name in self.rim_names() if angle(name) < .55 * math.tau)
        self.assertGreaterEqual(len(partial), 12)
        target = analytic.prepare([(self.obj, partial)])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertFalse(target['can_cut'])
        volume = self.obj.Shape.Volume
        with self.assertRaisesRegex(ValueError, 'hole'):
            analytic.apply(target, 'hole')
        self.assertAlmostEqual(self.obj.Shape.Volume, volume)

    def test_locked_faces_block_the_in_place_replacement(self):
        face_name = self.rim_names(faces=True)[0]
        locking.set_locked([(self.obj, (face_name,))], True)
        target = analytic.prepare([(self.obj, tuple(self.rim_names()))])
        self.assertFalse(target['can_cut'])
        with self.assertRaisesRegex(ValueError, 'hole'):
            analytic.apply(target, 'hole')
        self.assertTrue(locking.state(self.obj)[0])

    def test_single_face_on_chamfered_hole_replaces_in_place(self):
        chamfered = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        for edge in chamfered.Edges:
            if isinstance(edge.Curve, Part.Circle) and abs(edge.Curve.Center.z - 20) < 1e-5:
                chamfered = chamfered.makeChamfer(1.0, [edge])
                break
        self.obj.Shape = faceted(chamfered, deviation=0.1)
        wall_face_idx = None
        for i, f in enumerate(self.obj.Shape.Faces, 1):
            if abs(f.normalAt(0, 0).z) < 0.05 and 2 < f.CenterOfMass.z < 18:
                wall_face_idx = i
                break
        self.assertIsNotNone(wall_face_idx)
        target = analytic.prepare([(self.obj, ('Face%d' % wall_face_idx,))])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        self.assertAlmostEqual(target['radius'], 6, places=4)
        self.assertAlmostEqual(target['height'], 19, delta=0.1)
        analytic.apply(target, 'hole')
        shape = self.obj.Shape
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        curved = [f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(shape.Volume, chamfered.Volume, delta=0.5)

    def test_single_edge_on_chamfered_hole_rim_pairs_and_replaces(self):
        chamfered = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        for edge in chamfered.Edges:
            if isinstance(edge.Curve, Part.Circle) and abs(edge.Curve.Center.z - 20) < 1e-5:
                chamfered = chamfered.makeChamfer(1.0, [edge])
                break
        self.obj.Shape = faceted(chamfered, deviation=0.1)
        edge_idx = None
        for i, e in enumerate(self.obj.Shape.Edges, 1):
            if all(abs(v.Point.z) < 1e-5 for v in e.Vertexes):
                c = (e.Vertexes[0].Point + e.Vertexes[1].Point) * 0.5
                rad = ((c.x - 20)**2 + (c.y - 15)**2)**0.5
                if abs(rad - 6) < 0.2:
                    edge_idx = i
                    break
        self.assertIsNotNone(edge_idx)
        target = analytic.prepare([(self.obj, ('Edge%d' % edge_idx,))])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        analytic.apply(target, 'hole')
        shape = self.obj.Shape
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        curved = [f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)

    def test_single_edge_on_blind_hole_rim_pairs_and_replaces(self):
        blind = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 10, App.Vector(20, 15, 10)))
        self.obj.Shape = faceted(blind, deviation=0.1)
        edge_idx = None
        for i, e in enumerate(self.obj.Shape.Edges, 1):
            if all(abs(v.Point.z - 20) < 1e-5 for v in e.Vertexes):
                c = (e.Vertexes[0].Point + e.Vertexes[1].Point) * 0.5
                rad = ((c.x - 20)**2 + (c.y - 15)**2)**0.5
                if abs(rad - 6) < 0.2:
                    edge_idx = i
                    break
        self.assertIsNotNone(edge_idx)
        target = analytic.prepare([(self.obj, ('Edge%d' % edge_idx,))])
        self.assertEqual(target['kind'], 'cylinder')
        self.assertTrue(target['can_cut'])
        analytic.apply(target, 'hole')
        shape = self.obj.Shape
        self.assertTrue(shape.isValid() and shape.isClosed() and shape.Solids)
        curved = [f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(shape.Volume, blind.Volume, delta=0.5)

    def test_replace_rim_in_place(self):
        """A faceted polygonal rim wire on a flat face is replaced by a native circle edge in place."""
        rim_names = [name for name in self.rim_names()
                     if all(abs(v.Point.z - 20) < 1e-5
                            for v in self.obj.Shape.Edges[int(name[4:]) - 1].Vertexes)]
        self.assertGreater(len(rim_names), 8)

        target = analytic.prepare([(self.obj, tuple(rim_names))])
        self.assertTrue(target['can_replace_rim'])
        self.assertIsNotNone(target['carrying_face'])
        self.assertIsNotNone(target['target_wire'])

        analytic.apply(target, 'replace_rim')
        new_shape = self.obj.Shape
        self.assertTrue(new_shape.isValid())
        circles = [e for e in new_shape.Edges if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 6) < 0.1]
        self.assertGreaterEqual(len(circles), 1)

    def test_quadrant_circle_arcs_fit_and_expand(self):
        """Selecting a single quadrant arc expands around the circular loop."""
        arcs = [
            Part.makeCircle(5, App.Vector(20, 15, 10), App.Vector(0, 0, 1), 0, 90),
            Part.makeCircle(5, App.Vector(20, 15, 10), App.Vector(0, 0, 1), 90, 180),
            Part.makeCircle(5, App.Vector(20, 15, 10), App.Vector(0, 0, 1), 180, 270),
            Part.makeCircle(5, App.Vector(20, 15, 10), App.Vector(0, 0, 1), 270, 360),
        ]
        wire = Part.Wire(arcs)
        face = Part.Face(wire)
        test_obj = ops.new_shape(self.doc, face, 'ArcDisc')

        # Select just 1 quadrant arc
        target = analytic.prepare([(test_obj, ('Edge1',))])
        self.assertEqual(target['kind'], 'circle')
        self.assertAlmostEqual(target['radius'], 5.0, places=2)
        self.assertAlmostEqual(target['residual'], 0.0, places=4)
        self.assertAlmostEqual(target['largest_gap'], 0.0, delta=0.2)

        # Select all 4 arcs
        target4 = analytic.prepare([(test_obj, ('Edge1', 'Edge2', 'Edge3', 'Edge4'))])
        self.assertEqual(target4['kind'], 'circle')
        self.assertAlmostEqual(target4['radius'], 5.0, places=2)
        self.assertAlmostEqual(target4['residual'], 0.0, places=4)


if __name__ == '__main__':
    unittest.main()



