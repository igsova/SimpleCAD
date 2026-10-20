"""Heal to precision: align faces and holes without changing the design."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.core import geometry as g
from simplecad.repair import healing, holes
from simplecad.mesh import planar as mesh_planar
from simplecad.document import operations as ops

V = App.Vector
TILT = 2.35e-5


def tilted_block(hole=True):
    """A 9 x 12 x 8 block whose x = 9 face leans by TILT, with a hole along X.

    It is the situation left by a wall filled in on a converted part: the
    hole was cut square to the exact face, so it meets the tilted one as an
    ellipse.
    """
    lo = [V(0, 0, 0), V(0, 12, 0), V(0, 12, 8), V(0, 0, 8)]
    hi = [V(9 + TILT * p.y, p.y, p.z) for p in lo]
    faces = [Part.Face(Part.makePolygon(lo + lo[:1])), Part.Face(Part.makePolygon(hi + hi[:1]))]
    for i in range(4):
        j = (i + 1) % 4
        faces.append(Part.Face(Part.makePolygon([lo[i], lo[j], hi[j], hi[i], lo[i]])))
    sewn = Part.Compound(faces)
    sewn.sewShape()
    block = Part.makeSolid(sewn.Shells[0])
    if block.Volume < 0:
        block.reverse()
    if hole:
        block = block.cut(Part.makeCylinder(1.7, 20, V(-5, 6, 4), V(1, 0, 0))).Solids[0]
    return block


class AlignmentTests(unittest.TestCase):
    def test_tilted_face_and_its_hole_become_exact(self):
        block = tilted_block()
        healed, report = healing.heal(block, .1)
        self.assertTrue(healed.isValid() and healed.isClosed())
        self.assertEqual(len(healed.Faces), len(block.Faces))
        for face in healed.Faces:
            if isinstance(face.Surface, Part.Plane):
                self.assertEqual(max(abs(c) for c in face.Surface.Axis), 1.0)
        self.assertEqual(report['aligned_holes'], 1)
        rims = [e for e in healed.Edges if not isinstance(e.Curve, (Part.Line, Part.Circle))]
        self.assertEqual(rims, [])  # The elliptical rim is a circle again.
        self.assertLess(report['max_vertex_move'], 1e-3)
        self.assertAlmostEqual(healed.Volume, block.Volume, delta=1e-6)

    def test_face_order_is_kept(self):
        block = tilted_block()
        healed, _ = healing.heal(block, .1)
        for before, after in zip(block.Faces, healed.Faces):
            self.assertLess((before.CenterOfMass - after.CenterOfMass).Length, 1e-3)

    def test_through_push_after_healing_opens_cleanly(self):
        healed, _ = healing.heal(tilted_block(hole=False), .1)
        entry = max(healed.Faces, key=lambda f: f.CenterOfMass.x)
        level = entry.Surface.Position.x  # The healed face sits at its mean level.
        disk = Part.Face(Part.Wire(Part.makeCircle(1.7, V(level, 6, 4), V(1, 0, 0))))
        divided = healed.generalFuse([disk])[0].Solids[0]
        profile = next(f for f in divided.Faces if f.CenterOfMass.x > 8 and f.Area < 10)
        result = g.push_pull(divided, profile, g.opposite_face(divided, profile).distance)
        exit_face = next(f for f in result.Faces if abs(f.CenterOfMass.x) < 1e-6)
        self.assertEqual(len(exit_face.Wires), 2)
        self.assertEqual(entry.Surface.Axis, V(1, 0, 0))

    def test_real_steps_are_not_merged(self):
        # Two top faces 0.05 mm apart are a step in the design, below the
        # 0.1 mm precision but far above micron drift: both must stay put.
        step = Part.makeBox(10, 10, 4).fuse(Part.makeBox(10, 10, 4.05, V(10, 0, 0))).removeSplitter()
        healed, report = healing.heal(step, .1)
        tops = sorted(round(f.CenterOfMass.z, 6) for f in healed.Faces
                      if isinstance(f.Surface, Part.Plane) and abs(f.Surface.Axis.z) == 1.0 and f.CenterOfMass.z > 3.9)
        self.assertEqual(tops, [4.0, 4.05])
        self.assertAlmostEqual(healed.Volume, step.Volume, places=9)

    def test_opposite_sides_of_a_thin_wall_do_not_collapse(self):
        planes = [((0, 0, 1.0), (0, 0, 0.0), 10.0), ((0, 0, -1.0), (0, 0, -0.05), 10.0)]
        import numpy as np
        aligned = mesh_planar.regularize_planes([(np.array(n), np.array(c), w) for n, c, w in planes], 10.0, .1)
        self.assertNotAlmostEqual(abs(aligned[0][1]), abs(aligned[1][1]))

    def test_clean_shape_is_unchanged(self):
        box = Part.makeBox(10, 20, 30).cut(Part.makeCylinder(2, 30, V(5, 10, 0)))
        healed, report = healing.heal(box, .1)
        self.assertEqual(report['moved_vertices'], 0)
        self.assertAlmostEqual(healed.Volume, box.Volume, places=9)


def fragmented_hole():
    """A plate whose faceted hole was cut again by a cylinder tilted 1.5e-5 rad.

    Old conversions did this: the wall falls apart into cylinder strips and
    zero-width facet remnants, and the rims into arcs and hairline edges.
    """
    plate = Part.makeBox(20, 20, 4)
    corners = [V(10 + 1.7 * math.cos(math.tau * i / 48), 10 + 1.7 * math.sin(math.tau * i / 48), -1)
               for i in range(48)]
    faceted = plate.cut(Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 6))).Solids[0]
    axis = V(1.5e-5, 1.5e-5, 1)
    axis.normalize()
    return faceted.cut(Part.makeCylinder(1.7, 8, V(10, 10, -2), axis)).Solids[0]


class HoleTests(unittest.TestCase):
    def test_fragmented_hole_becomes_one_cylinder(self):
        broken = fragmented_hole()
        self.assertGreater(sum(isinstance(f.Surface, Part.Cylinder) for f in broken.Faces), 1)
        rebuilt, count = holes.rebuild_fragmented(broken, .1)
        self.assertEqual(count, 1)
        self.assertTrue(rebuilt.isValid() and rebuilt.isClosed())
        walls = [f for f in rebuilt.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertEqual(len(walls), 1)
        self.assertEqual(walls[0].Surface.Axis, V(0, 0, 1))  # Squared to the plate.
        self.assertEqual(len(rebuilt.Faces), 7)
        self.assertEqual([e for e in rebuilt.Edges if e.Length < 1e-3], [])
        top = next(f for f in rebuilt.Faces if abs(f.CenterOfMass.z - 4) < 1e-6)
        self.assertEqual(sorted(type(e.Curve).__name__ for e in top.Wires[1].Edges)[0], 'Circle')
        self.assertAlmostEqual(rebuilt.Volume, 1600 - math.pi * 1.7 ** 2 * 4, delta=1e-3)

    def test_a_clean_hole_is_left_alone(self):
        plate = Part.makeBox(20, 20, 4).cut(Part.makeCylinder(1.7, 4, V(10, 10, 0)))
        _, count = holes.rebuild_fragmented(plate, .1)
        self.assertEqual(count, 0)

    def test_heal_rebuilds_the_hole(self):
        healed, report = healing.heal(fragmented_hole(), .1)
        self.assertEqual(report['rebuilt_holes'], 1)
        self.assertEqual(sum(isinstance(f.Surface, Part.Cylinder) for f in healed.Faces), 1)

    def test_a_rim_split_by_a_hairline_arc_is_rebuilt_for_printing(self):
        # A hole rim split into a full arc and a 0.00001 mm one, as edits on
        # converted plates leave. Meshed, the hairline collapses and slicers
        # report non-manifold edges there.
        plate = Part.makeBox(20, 20, 4).cut(Part.makeCylinder(2, 6, V(10, 10, -1))).Solids[0]
        split = [Part.Vertex(V(10 + 2 * math.cos(t), 10 + 2 * math.sin(t), 4)) for t in (1.0, 1.0 + 5e-6)]
        broken = plate.generalFuse(split)[0].Solids[0]
        self.assertTrue(any(e.Length < 1e-4 for e in broken.Edges))
        self.assertGreater(healing.mesh_issues(broken), 0)
        rebuilt, count = holes.rebuild_fragmented(broken, .1)
        self.assertEqual(count, 1)
        self.assertEqual([e for e in rebuilt.Edges if e.Length < 1e-3], [])
        self.assertEqual(healing.mesh_issues(rebuilt), 0)
        self.assertAlmostEqual(rebuilt.Volume, plate.Volume, delta=1e-6)
        healed, report = healing.heal(broken, .1)
        self.assertEqual((report['rebuilt_holes'], report['mesh_issues_after']), (1, 0))
        self.assertGreater(report['mesh_issues_before'], 0)

    def test_a_clean_part_meshes_without_bad_edges(self):
        self.assertEqual(healing.mesh_issues(Part.makeBox(10, 10, 4).cut(Part.makeCylinder(2, 6, V(5, 5, -1)))), 0)

    def test_invalid_shapes_count_as_worse_than_any_valid_one(self):
        good = Part.makeBox(5, 5, 5)
        bad = Part.Face(Part.makePolygon([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0), V(0, 0, 0)]))
        bad = Part.Face(bad.Surface, [bad.OuterWire, Part.Wire(Part.makePolygon([V(2, 2, 0), V(3, 2, 0), V(3, 3, 0), V(2, 2, 0)]))])
        self.assertFalse(bad.isValid())
        self.assertEqual(healing.check_errors(bad), math.inf)
        self.assertEqual(healing.verdict(bad, good)['check_issues_before'], -1)
        with self.assertRaises(ValueError):
            healing.verdict(good, bad)


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Healing')
        self.doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(self.doc.Name))

    def test_heal_runs_isolated_and_undoes_in_one_step(self):
        obj = ops.new_shape(self.doc, tilted_block(), 'Block')
        before = obj.Shape.copy()
        reports = ops.heal(self.doc, [obj])
        self.assertTrue(reports[0]['healed'], reports[0])
        tilted = [f for f in obj.Shape.Faces if isinstance(f.Surface, Part.Plane)
                  and max(abs(c) for c in f.Surface.Axis) < 1.0]
        self.assertEqual(tilted, [])
        self.doc.undo()
        self.assertTrue(obj.Shape.isPartner(before) or abs(obj.Shape.Volume - before.Volume) < 1e-9)
        self.assertTrue(any(isinstance(f.Surface, Part.Plane) and max(abs(c) for c in f.Surface.Axis) < 1.0
                            for f in obj.Shape.Faces))

    def test_a_shape_that_cannot_be_improved_is_left_unchanged(self):
        obj = ops.new_shape(self.doc, Part.makeBox(5, 5, 5), 'Box')
        original = obj.Shape.copy()
        undo = self.doc.UndoCount
        from unittest.mock import patch
        with patch('simplecad.repair.healing.heal_isolated', side_effect=ValueError('cannot improve')):
            reports = ops.heal(self.doc, [obj])
        self.assertFalse(reports[0]['healed'])
        self.assertEqual(reports[0]['reason'], 'cannot improve')
        self.assertTrue(obj.Shape.isSame(original) or obj.Shape.isPartner(original)
                        or abs(obj.Shape.Volume - original.Volume) < 1e-12)
        self.assertEqual(self.doc.UndoCount, undo)  # No transaction was recorded.


if __name__ == '__main__':
    unittest.main()
