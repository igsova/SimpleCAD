"""Document edits of the curved-surface tools: one Undo step, Placement kept."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.modeling import patterns
from simplecad.surfaces import edit as se, operations as so

V = App.Vector


class DocumentCase(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('SurfaceOps')
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def add(self, shape, placement=None):
        obj = self.doc.addObject('Part::Feature', 'Part')
        obj.Shape = shape
        if placement is not None:
            obj.Placement = placement
        self.doc.recompute()
        return obj


class SurfaceEditTests(DocumentCase):
    def test_delete_and_heal_keeps_placement_and_undoes_in_one_step(self):
        box = Part.makeBox(20, 20, 10)
        placement = App.Placement(V(5, 6, 7), App.Rotation(V(0, 0, 1), 30))
        obj = self.add(box.makeFillet(2, [box.Edges[0]]), placement)
        undo = self.doc.UndoCount
        names = ['Face%d' % (i + 1) for i, f in enumerate(obj.Shape.Faces) if isinstance(f.Surface, Part.Cylinder)]
        report = so.heal_faces(obj, names)
        self.assertEqual(report['removed'], 1)
        self.assertTrue(obj.Placement.isSame(placement, 1e-9))
        self.assertEqual(len(obj.Shape.Faces), 6)
        self.assertAlmostEqual(obj.Shape.Volume, 4000, places=3)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.assertEqual(len(obj.Shape.Faces), 7)

    def test_failure_leaves_the_object_unchanged(self):
        obj = self.add(Part.makeBox(10, 10, 10))
        undo = self.doc.UndoCount
        with self.assertRaises(ValueError):
            so.heal_faces(obj, ['Face1'])
        self.assertEqual((len(obj.Shape.Faces), self.doc.UndoCount), (6, undo))

    def test_remove_rounds(self):
        box = Part.makeBox(20, 20, 10)
        obj = self.add(box.makeFillet(1.5, box.Edges[:4]))
        self.assertEqual(len(so.rounds(obj, 2)), 4)
        self.assertEqual(so.rounds(obj, 1), [])
        report = so.remove_rounds(obj, 2)
        self.assertEqual((report['found'], report['removed']), (4, 4))
        self.assertAlmostEqual(obj.Shape.Volume, 4000, places=3)
        with self.assertRaises(ValueError):
            so.remove_rounds(obj, 2)

    def test_remove_rounds_keeps_a_rounded_pocket_and_counts_what_stays(self):
        from test_surface_edit import rounded_pocket
        obj = self.add(rounded_pocket())
        report = so.remove_rounds(obj, 3)
        self.assertAlmostEqual(obj.Shape.Volume, 40 * 30 * 20 - 20 * 8 * 10, delta=1)
        left = len(so.rounds(obj, 3))
        self.assertEqual((report['found'], report['removed'], report['failed']), (12, 12 - left, left))

    def test_imprint_on_a_moved_cylinder_selects_the_new_region(self):
        cylinder = Part.makeCylinder(20, 40)
        placement = App.Placement(V(100, 0, 0), App.Rotation(V(1, 0, 0), 90))
        obj = self.add(cylinder, placement)
        wall = next('Face%d' % (i + 1) for i, f in enumerate(obj.Shape.Faces) if isinstance(f.Surface, Part.Cylinder))
        point = placement.multVec(V(0, 20, 20))  # away from the seam at +X
        report = so.imprint(obj, [wall], se.outline('circle', diameter=8), point)
        self.assertEqual(len(report['regions']), 1)
        region = obj.Shape.getElement(report['regions'][0])
        self.assertLess((region.CenterOfMass - point).Length, 1.0)
        self.assertTrue(obj.Placement.isSame(placement, 1e-9))
        self.assertAlmostEqual(obj.Shape.Volume, cylinder.Volume, delta=cylinder.Volume * 1e-6)

    def test_emboss_raises_the_outline(self):
        obj = self.add(Part.makeBox(40, 40, 10))
        top = next('Face%d' % (i + 1) for i, f in enumerate(obj.Shape.Faces) if f.CenterOfMass.z > 9.9)
        so.imprint(obj, [top], se.outline('rectangle', width=10, height=5), mode='emboss', depth=2)
        self.assertAlmostEqual(obj.Shape.Volume, 16000 + 100, places=3)
        self.assertAlmostEqual(obj.Shape.BoundBox.ZMax, 12, places=6)

    def test_fill_hole_turns_an_open_box_into_a_solid(self):
        box = Part.makeBox(10, 10, 10)
        obj = self.add(Part.Shell(box.Faces[:5]))
        self.assertEqual(len(so.openings(obj)), 1)
        report = so.fill_holes(obj)
        self.assertTrue(report['closed'])
        self.assertEqual(len(obj.Shape.Solids), 1)
        self.assertAlmostEqual(obj.Shape.Volume, 1000, places=4)

    def test_unwrap_makes_a_new_flat_object_beside_the_part(self):
        half = Part.makeCylinder(10, 30, V(), V(0, 0, 1), 180)
        obj = self.add(half)
        wall = next('Face%d' % (i + 1) for i, f in enumerate(half.Faces) if isinstance(f.Surface, Part.Cylinder))
        flat, report = so.unwrap(obj, wall)
        self.assertNotEqual(flat, obj)
        self.assertAlmostEqual(flat.Shape.Area, math.pi * 10 * 30, delta=10)
        self.assertGreater(flat.Shape.BoundBox.XMin, obj.Shape.BoundBox.XMax)
        self.assertLess(flat.Shape.BoundBox.ZLength, 1e-6)


class OffsetShellDraftTests(DocumentCase):
    def name_of(self, obj, test):
        return next('Face%d' % (i + 1) for i, f in enumerate(obj.Shape.Faces) if test(f))

    def test_offset_face_keeps_placement_and_undoes_in_one_step(self):
        placement = App.Placement(V(5, 6, 7), App.Rotation(V(1, 0, 0), 90))
        obj = self.add(Part.makeCylinder(10, 20), placement)
        wall = self.name_of(obj, lambda f: isinstance(f.Surface, Part.Cylinder))
        undo = self.doc.UndoCount
        report = so.offset_faces(obj, [wall], 2)
        self.assertAlmostEqual(obj.Shape.Volume, math.pi * 144 * 20, places=3)
        self.assertAlmostEqual(report['volume_change'], math.pi * 44 * 20, places=3)
        self.assertTrue(obj.Placement.isSame(placement, 1e-9))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.assertAlmostEqual(obj.Shape.Volume, math.pi * 100 * 20, places=3)

    def test_refused_offset_leaves_the_object_unchanged(self):
        obj = self.add(Part.makeBox(20, 20, 10))
        top = self.name_of(obj, lambda f: f.CenterOfMass.z > 9.9)
        undo = self.doc.UndoCount
        with self.assertRaises(ValueError):
            so.offset_faces(obj, [top], -15)
        self.assertEqual((round(obj.Shape.Volume, 6), self.doc.UndoCount), (4000, undo))

    def test_shell_opens_the_selected_face(self):
        obj = self.add(Part.makeBox(20, 20, 10))
        top = self.name_of(obj, lambda f: f.CenterOfMass.z > 9.9)
        report = so.shell(obj, [top], 1)
        self.assertEqual(report['open_faces'], 1)
        self.assertAlmostEqual(obj.Shape.Volume, 4000 - 18 * 18 * 9, places=4)

    def test_a_surface_object_is_thickened_into_a_solid(self):
        obj = self.add(Part.makePlane(20, 10))
        self.assertTrue(so.is_surface(obj))
        so.thicken(obj, 2, 'both')
        self.assertEqual(len(obj.Shape.Solids), 1)
        self.assertAlmostEqual(obj.Shape.Volume, 400, places=6)
        self.assertFalse(so.is_surface(obj))

    def test_draft_uses_the_world_axis_of_a_turned_part(self):
        # Lying on its side, the part's local Y points up in the world.
        obj = self.add(Part.makeBox(20, 20, 10), App.Placement(V(), App.Rotation(V(1, 0, 0), 90)))
        sides = ['Face%d' % (i + 1) for i, f in enumerate(obj.Shape.Faces) if abs(f.Surface.Axis.z) < 1e-6]
        self.assertEqual(len(sides), 4)
        so.draft(obj, sides, 5, 'Z')
        box = obj.Shape.BoundBox
        roof = next(f for f in obj.Shape.Faces if f.CenterOfMass.z > box.ZMax - 1e-6)
        floor = next(f for f in obj.Shape.Faces if f.CenterOfMass.z < box.ZMin + 1e-6)
        self.assertLess(roof.Area, floor.Area)

    def test_wrapped_text_lands_on_one_face(self):
        obj = self.add(Part.makeCylinder(20, 40), App.Placement(V(50, 0, 0), App.Rotation()))
        wall = self.name_of(obj, lambda f: isinstance(f.Surface, Part.Cylinder))
        point = V(50, 20, 20)
        report = so.imprint(obj, [wall], se.outline('rectangle', width=30, height=8), point, wrap=True)
        region = obj.Shape.getElement(report['regions'][0])
        self.assertAlmostEqual(region.Area, 240, delta=.5)
        self.assertLess(region.distToShape(Part.Vertex(point))[0], 1e-6)


class PatternTests(DocumentCase):
    def test_grid_radial_and_path(self):
        obj = self.add(Part.makeBox(2, 2, 2), App.Placement(V(10, 0, 0), App.Rotation()))
        copies = so.pattern([obj], so.placements('grid', [obj], counts=(3, 2, 1), spacing=(5, 4, 0)))
        self.assertEqual(len(copies), 5)
        self.assertEqual(sorted((round(c.Placement.Base.x), round(c.Placement.Base.y)) for c in copies),
                         [(10, 4), (15, 0), (15, 4), (20, 0), (20, 4)])
        undo = self.doc.UndoCount
        copies = so.pattern([obj], so.placements('radial', [obj], count=4, axis=(0, 0, 1), center=(0, 0, 0)))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        centers = sorted((round(c.Shape.BoundBox.Center.x, 3), round(c.Shape.BoundBox.Center.y, 3)) for c in copies)
        self.assertEqual(centers, [(-11.0, -1.0), (-1.0, 11.0), (1.0, -11.0)])
        path = Part.makeLine(V(0, 0, 0), V(0, 30, 0))
        placements = so.placements('path', [obj], path=path, count=4)
        self.assertEqual([round(p.Base.y) for p in placements], [10, 20, 30])

    def test_path_follows_and_turns_with_a_curve(self):
        arc = Part.makeCircle(10, V(), V(0, 0, 1), 0, 180)
        placements = patterns.along(arc, 3, align=True)
        self.assertEqual(len(placements), 2)
        end = placements[-1].multVec(V(10, 0, 0))
        self.assertLess((end - V(-10, 0, 0)).Length, 1e-3)
        self.assertAlmostEqual(math.degrees(placements[-1].Rotation.Angle), 180, delta=1)

    def test_bad_patterns_are_refused(self):
        with self.assertRaises(ValueError):
            patterns.grid((1, 1, 1), (5, 5, 5))
        with self.assertRaises(ValueError):
            patterns.grid((3, 1, 1), (0, 0, 0))
        with self.assertRaises(ValueError):
            patterns.radial(1, V(0, 0, 1), V())
        with self.assertRaises(ValueError):
            patterns.grid((30, 30, 1), (1, 1, 1))
        with self.assertRaises(ValueError):
            patterns.along(Part.makeCompound([Part.makeLine(V(), V(1, 0, 0)), Part.makeLine(V(5, 0, 0), V(6, 0, 0))]), 3)


if __name__ == '__main__':
    unittest.main()
