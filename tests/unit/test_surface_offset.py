"""Offset faces, shell and thicken, draft, and wrapped drawings on Part shapes."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.surfaces import edit as se, offset as so

V = App.Vector


def face_index(shape, test):
    return next(i for i, f in enumerate(shape.Faces) if test(f))


def top(shape):
    return face_index(shape, lambda f: isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > shape.BoundBox.ZMax - 1e-6)


def wall(shape):
    return face_index(shape, lambda f: isinstance(f.Surface, Part.Cylinder))


class OffsetFaceTests(unittest.TestCase):
    def test_a_flat_face_moves_out_and_in_like_push_pull(self):
        box = Part.makeBox(20, 20, 10)
        raised, report = so.offset_faces(box, [top(box)], 3)
        self.assertAlmostEqual(raised.Volume, 5200, places=6)
        self.assertEqual(len(raised.Faces), 6)  # the new walls merge with the sides
        self.assertAlmostEqual(report['volume_change'], 1200, places=6)
        lowered, _ = so.offset_faces(box, [top(box)], -3)
        self.assertAlmostEqual(lowered.Volume, 2800, places=6)
        self.assertAlmostEqual(box.Volume, 4000, places=6)  # the source is untouched

    def test_a_cylinder_wall_grows_and_shrinks_its_radius(self):
        part = Part.makeCylinder(10, 20)
        grown, _ = so.offset_faces(part, [wall(part)], 2)
        self.assertAlmostEqual(grown.Volume, math.pi * 12 ** 2 * 20, places=3)
        shrunk, _ = so.offset_faces(part, [wall(part)], -2)
        self.assertAlmostEqual(shrunk.Volume, math.pi * 8 ** 2 * 20, places=3)

    def test_outward_on_a_hole_wall_closes_the_hole_a_little(self):
        part = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(3, 10, V(10, 10, 0)))
        smaller, _ = so.offset_faces(part, [wall(part)], 1)
        self.assertAlmostEqual(smaller.Volume - part.Volume, math.pi * (9 - 4) * 10, places=3)
        larger, _ = so.offset_faces(part, [wall(part)], -1)
        self.assertAlmostEqual(larger.Volume - part.Volume, -math.pi * (16 - 9) * 10, places=3)

    def test_a_curved_face_offsets_along_its_normals(self):
        box = Part.makeBox(20, 20, 10)
        part = box.makeFillet(3, [e for e in box.Edges if abs(e.CenterOfMass.z - 10) < 1e-6
                                  and abs(e.CenterOfMass.y - 10) < 1e-6])
        rounds = [i for i, f in enumerate(part.Faces) if isinstance(f.Surface, Part.Cylinder)]
        moved, report = so.offset_faces(part, rounds[:1], 1)
        self.assertTrue(moved.isValid() and len(moved.Solids) == 1)
        # A quarter ring from radius 3 to 4 along the 20 mm round.
        self.assertAlmostEqual(report['volume_change'], math.pi / 4 * (16 - 9) * 20, places=3)

    def test_every_face_offsets_the_whole_part(self):
        box = Part.makeBox(20, 20, 10)
        grown, _ = so.offset_faces(box, range(6), 1)
        self.assertAlmostEqual(grown.Volume, 22 * 22 * 12, delta=1e-3)
        ball, _ = so.offset_faces(Part.makeSphere(10), [0], 1)
        self.assertAlmostEqual(ball.Volume, 4 / 3 * math.pi * 11 ** 3, delta=1e-2)

    def test_impossible_offsets_are_refused(self):
        box = Part.makeBox(20, 20, 10)
        with self.assertRaises(ValueError):
            so.offset_faces(box, [top(box)], -12)  # cuts through the part
        with self.assertRaises(ValueError):
            so.offset_faces(box, [top(box)], 0)
        part = Part.makeCylinder(5, 10)
        with self.assertRaises(ValueError):
            so.offset_faces(part, [wall(part)], -6)  # past the axis
        with self.assertRaises(ValueError):
            so.offset_faces(Part.makePlane(10, 10), [0], 1)  # not a solid


class ShellAndThickenTests(unittest.TestCase):
    def test_a_box_hollows_with_an_open_top(self):
        box = Part.makeBox(20, 20, 10)
        hollow, report = so.shell(box, [top(box)], 1)
        self.assertAlmostEqual(hollow.Volume, 4000 - 18 * 18 * 9, places=4)
        self.assertEqual(report['open_faces'], 1)
        self.assertEqual(len(hollow.Solids), 1)

    def test_no_open_face_leaves_a_closed_hollow(self):
        hollow, _ = so.shell(Part.makeBox(20, 20, 10), [], 1)
        self.assertAlmostEqual(hollow.Volume, 4000 - 18 * 18 * 8, places=4)
        self.assertEqual(len(hollow.Shells), 2)

    def test_a_cylinder_cup(self):
        part = Part.makeCylinder(5, 10)
        cup, _ = so.shell(part, [top(part)], 1)
        self.assertAlmostEqual(cup.Volume, math.pi * (25 * 10 - 16 * 9), places=3)

    def test_bad_shells_are_refused(self):
        box = Part.makeBox(20, 20, 10)
        for faces, thickness in (([], 0), ([top(box)], -1), (range(6), 1)):
            with self.assertRaises(ValueError):
                so.shell(box, faces, thickness)
        with self.assertRaises(ValueError):
            so.shell(box, [], 20)  # thicker than the part

    def test_a_surface_thickens_on_either_or_both_sides(self):
        sheet = Part.makePlane(20, 10)
        front, _ = so.thicken(sheet, 2, 'front')
        self.assertAlmostEqual(front.Volume, 400, places=6)
        self.assertAlmostEqual(front.BoundBox.ZMin, 0, places=6)
        back, _ = so.thicken(sheet, 2, 'back')
        self.assertAlmostEqual(back.BoundBox.ZMax, 0, places=6)
        both, _ = so.thicken(sheet, 2, 'both')
        self.assertAlmostEqual(both.Volume, 400, places=6)
        self.assertAlmostEqual(both.BoundBox.ZMin, -1, places=6)
        self.assertEqual(len(both.Solids), 1)

    def test_a_curved_panel_thickens(self):
        panel = Part.makeCylinder(10, 20).Faces[0]
        wall_, _ = so.thicken(panel, 1, 'front')
        self.assertAlmostEqual(wall_.Volume, math.pi * (121 - 100) * 20, places=3)

    def test_thicken_needs_a_surface(self):
        with self.assertRaises(ValueError):
            so.thicken(Part.makeBox(1, 1, 1), 1)
        with self.assertRaises(ValueError):
            so.thicken(Part.makePlane(1, 1), 0)


class DraftTests(unittest.TestCase):
    def sides(self, shape):
        return [i for i, f in enumerate(shape.Faces) if isinstance(f.Surface, Part.Plane)
                and abs(f.Surface.Axis.z) < 1e-6]

    def test_side_walls_lean_in_from_a_bottom_hinge(self):
        box = Part.makeBox(20, 20, 10)
        drafted, report = so.draft(box, self.sides(box), 5, (0, 0, 1))
        bottom = next(f for f in drafted.Faces if f.CenterOfMass.z < 1e-6)
        roof = next(f for f in drafted.Faces if f.CenterOfMass.z > 10 - 1e-6)
        self.assertAlmostEqual(bottom.Area, 400, places=6)  # the hinge keeps the bottom
        side = 20 - 2 * 10 * math.tan(math.radians(5))
        self.assertAlmostEqual(roof.Area, side * side, places=4)
        self.assertLess(report['volume_change'], 0)

    def test_hinge_and_taper_choices(self):
        box = Part.makeBox(20, 20, 10)
        sides = self.sides(box)
        top_hinge, _ = so.draft(box, sides, 5, (0, 0, 1), 'top')
        roof = next(f for f in top_hinge.Faces if f.CenterOfMass.z > 10 - 1e-6)
        self.assertAlmostEqual(roof.Area, 400, places=6)
        self.assertGreater(top_hinge.Volume, 4000)  # wider below a top hinge
        wider_up, _ = so.draft(box, sides, 5, (0, 0, 1), 'bottom', 'bottom')
        self.assertGreater(wider_up.Volume, 4000)

    def test_a_cylinder_becomes_a_cone(self):
        part = Part.makeCylinder(5, 10)
        drafted, _ = so.draft(part, [wall(part)], 5, (0, 0, 1))
        self.assertTrue(any(isinstance(f.Surface, Part.Cone) for f in drafted.Faces))

    def test_faces_that_cannot_draft_are_refused(self):
        box = Part.makeBox(20, 20, 10)
        with self.assertRaises(ValueError):
            so.draft(box, [top(box)], 5, (0, 0, 1))  # square to the pull
        with self.assertRaises(ValueError):
            so.draft(box, self.sides(box), 90, (0, 0, 1))
        with self.assertRaises(ValueError):
            so.draft(Part.makeSphere(5), [0], 3, (0, 0, 1))  # free-form


class WrapTests(unittest.TestCase):
    def cylinder(self):
        part = Part.makeCylinder(10, 40)
        part.rotate(V(), V(0, 0, 1), 180)  # the seam goes to the back
        index = wall(part)
        origin, normal, x = se.frame_at(part.Faces[index], V(10, 0, 20))
        return part, index, (origin, normal, x)

    def test_a_wrapped_rectangle_keeps_its_size(self):
        part, index, frame = self.cylinder()
        result, report = se.imprint(part, [index], se.outline('rectangle', width=40, height=10), -frame[1],
                                    wrapping=frame)
        self.assertTrue(report['wrapped'])
        region = result.Faces[report['regions'][0]]
        self.assertAlmostEqual(region.Area, 400, delta=.4)  # 40 mm around the curve, not 20 across
        self.assertAlmostEqual(result.Volume, part.Volume, places=6)
        # Projected straight, the same rectangle would be squashed over the curve.
        flat = se.place_outline(se.outline('rectangle', width=19, height=10), *frame, lift=5)
        projected, report = se.imprint(part, [index], flat, -frame[1])
        self.assertGreater(projected.Faces[report['regions'][0]].Area, 220)  # 19 mm across covers more surface

    def test_a_wrapped_drawing_must_fit_on_the_face(self):
        part, index, frame = self.cylinder()
        with self.assertRaisesRegex(ValueError, 'longer than the way around'):
            se.imprint(part, [index], se.outline('rectangle', width=64, height=10), -frame[1], wrapping=frame)
        with self.assertRaisesRegex(ValueError, 'runs off'):
            se.imprint(part, [index], se.outline('rectangle', width=10, height=50), -frame[1], wrapping=frame)

    def test_a_drawing_runs_across_the_seam(self):
        part = Part.makeCylinder(10, 40)  # the seam is at +X, under the drawing
        frame = se.frame_at(part.Faces[0], V(10, 0, 20))
        result, report = se.imprint(part, [0], se.outline('rectangle', width=40, height=10), -frame[1],
                                    wrapping=frame)
        self.assertEqual(len(report['regions']), 2)  # one each side of the seam
        self.assertAlmostEqual(sum(result.Faces[i].Area for i in report['regions']), 400, delta=.4)
        raised, report = se.imprint(part, [0], se.outline('rectangle', width=20, height=10), -frame[1], 'emboss',
                                    1, wrapping=frame)
        self.assertAlmostEqual(report['volume_change'], 210, delta=.5)
        self.assertTrue(raised.isValid() and len(raised.Solids) == 1)
        cone = Part.makeCone(10, 6, 20)
        face = cone.Faces[0]
        frame = se.frame_at(face, face.valueAt(face.ParameterRange[0], 10))
        result, report = se.imprint(cone, [0], se.outline('rectangle', width=20, height=6), -frame[1],
                                    wrapping=frame)
        self.assertAlmostEqual(sum(result.Faces[i].Area for i in report['regions']), 120, delta=.3)

    def test_wrapped_emboss_rises_along_the_normals(self):
        part, index, frame = self.cylinder()
        outline = se.outline('rectangle', width=20, height=10)
        raised, report = se.imprint(part, [index], outline, -frame[1], 'emboss', 1, wrapping=frame)
        # A shell 1 mm thick over a 20 x 10 mm patch of radius 10: 200 x (1 + 1/20).
        self.assertAlmostEqual(report['volume_change'], 210, delta=.5)
        sunk, report = se.imprint(part, [index], outline, -frame[1], 'deboss', 1, wrapping=frame)
        self.assertAlmostEqual(report['volume_change'], -190, delta=.5)
        self.assertTrue(raised.isValid() and sunk.isValid())

    @unittest.skipUnless(se.default_font(), 'FreeCAD bundled font not found')
    def test_wrapped_text_splits_into_letters(self):
        part, index, frame = self.cylinder()
        result, report = se.imprint(part, [index], se.outline('text', text='HI', size=8, font=se.default_font()),
                                    -frame[1], wrapping=frame)
        self.assertEqual(len(report['regions']), 2)

    def test_preview_lines_follow_the_face(self):
        part, index, (origin, normal, x) = self.cylinder()
        flat_map = se.FlatMap(part.Faces[index])
        lines = se.wrap_lines(flat_map, se.outline('circle', diameter=8), origin, normal, x)
        for point in (p for line in lines for p in line):
            self.assertAlmostEqual(math.hypot(point.x, point.y), 10, delta=.01)


if __name__ == '__main__':
    unittest.main()
