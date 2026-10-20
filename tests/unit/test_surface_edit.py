"""Curved-surface edits: delete & heal, rounds, imprint, fill, unwrap, curvature."""
import math
import unittest

import FreeCAD as App
import Part

from simplecad.surfaces import edit as se

V = App.Vector


def rounded_box(radius=2.0):
    box = Part.makeBox(20, 20, 10)
    return box.makeFillet(radius, box.Edges)


def notched_box():
    """An L-shaped block with every edge rounded: one inside round, many outside."""
    block = Part.makeBox(30, 20, 10).cut(Part.makeBox(15, 10, 10, V(15, 10, 0)))
    inner = [e for e in block.Edges if isinstance(e.Curve, Part.Line)
             and (e.CenterOfMass - V(15, 10, 5)).Length < 1e-6]
    block = block.makeFillet(3, inner)
    outer = [e for e in block.Edges if isinstance(e.Curve, Part.Line) and abs(e.Vertexes[0].Point.z
             - e.Vertexes[1].Point.z) > 9]
    return block.makeFillet(1, outer)


def font():
    return se.default_font() or None


class DeleteAndHealTests(unittest.TestCase):
    def test_fillet_faces_are_removed_back_to_the_box(self):
        part = rounded_box()
        rounds = [i for i, f in enumerate(part.Faces) if not isinstance(f.Surface, Part.Plane)]
        healed, report = se.remove_faces(part, rounds)
        self.assertTrue(healed.isValid())
        self.assertEqual(len(healed.Faces), 6)
        self.assertAlmostEqual(healed.Volume, 4000, places=3)
        self.assertEqual(report['removed'], len(rounds))
        self.assertEqual(report['failed'], 0)

    def test_one_round_and_the_source_is_unchanged(self):
        box = Part.makeBox(20, 20, 10)
        part = box.makeFillet(2, [box.Edges[0]])
        volume, faces = part.Volume, len(part.Faces)
        healed, report = se.remove_faces(part, [i for i, f in enumerate(part.Faces)
                                                if isinstance(f.Surface, Part.Cylinder)])
        self.assertAlmostEqual(healed.Volume, 4000, places=3)
        self.assertEqual(report['faces_after'], 6)
        self.assertEqual((part.Volume, len(part.Faces)), (volume, faces))

    def test_a_round_boxed_in_by_rounded_corners_is_refused(self):
        part = rounded_box()
        rounds = [i for i, f in enumerate(part.Faces) if isinstance(f.Surface, Part.Cylinder)]
        with self.assertRaises(ValueError):
            se.remove_faces(part, rounds[:1])  # boxed in by the rounded corners

    def test_a_face_that_cannot_heal_is_refused(self):
        box = Part.makeBox(10, 10, 10)
        with self.assertRaises(ValueError):
            se.remove_faces(box, [0])

    def test_open_shells_and_bad_indices_are_refused(self):
        with self.assertRaises(ValueError):
            se.remove_faces(Part.makeBox(5, 5, 5).Faces[0], [0])
        with self.assertRaises(ValueError):
            se.remove_faces(rounded_box(), [999])


class RoundTests(unittest.TestCase):
    def test_rounds_are_found_with_radius_and_side(self):
        part = notched_box()
        rounds = se.find_rounds(part, 5)
        self.assertEqual(len([r for r in rounds if not r['convex']]), 1)
        self.assertEqual(len([r for r in rounds if r['convex']]), 5)
        inner = next(r for r in rounds if not r['convex'])
        self.assertAlmostEqual(inner['radius'], 3, places=6)

    def test_radius_and_convexity_filter(self):
        part = notched_box()
        self.assertEqual(len(se.find_rounds(part, 2)), 5)
        self.assertEqual([r['radius'] for r in se.find_rounds(part, 5, 'concave')], [3.0])
        self.assertEqual(len(se.find_rounds(part, 5, 'convex', within={0, 1, 2})),
                         len([r for r in se.find_rounds(part, 5, 'convex') if r['index'] in (0, 1, 2)]))

    def test_holes_and_bosses_are_not_rounds(self):
        part = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(3, 10, V(10, 10, 0)))
        self.assertEqual(se.find_rounds(part, 10), [])
        self.assertEqual(se.find_rounds(Part.makeCylinder(2, 5), 10), [])

    def test_found_rounds_can_be_removed(self):
        part = notched_box()
        rounds = [r['index'] for r in se.find_rounds(part, 5)]
        healed, report = se.remove_faces(part, rounds)
        self.assertEqual(report['failed'], 0)
        self.assertAlmostEqual(healed.Volume, 30 * 20 * 10 - 15 * 10 * 10, places=3)


class CurvatureTests(unittest.TestCase):
    def test_sphere_cylinder_and_plane(self):
        sphere = Part.makeSphere(8).Faces[0]
        result = se.curvature(sphere, V(8, 0, 0))
        self.assertAlmostEqual(result['tight'], 8, places=6)
        self.assertAlmostEqual(result['gentle'], 8, places=6)
        self.assertEqual(result['kind'], 'convex')
        side = next(f for f in Part.makeCylinder(4, 10).Faces if isinstance(f.Surface, Part.Cylinder))
        result = se.curvature(side, V(4, 0, 5))
        self.assertAlmostEqual(result['tight'], 4, places=6)
        self.assertEqual(result['gentle'], math.inf)
        self.assertEqual(result['kind'], 'convex')
        self.assertEqual(se.curvature(Part.makeBox(1, 1, 1).Faces[0])['kind'], 'flat')
        self.assertAlmostEqual(se.curvature(sphere, V(0, 0, 8))['tight'], 8, places=3)  # at the pole

    def test_curvature_map_colours_only_curved_faces(self):
        box = Part.makeBox(20, 20, 10)
        part = box.makeFillet(2, box.Edges[:1])
        points, triangles, radii = se.curvature_mesh(part)
        self.assertTrue(triangles)
        self.assertTrue(all(abs(r - 2) < 1e-6 for r in radii))
        self.assertEqual(se.curvature_mesh(Part.makeBox(1, 1, 1)), ([], [], []))
        _, _, few = se.curvature_mesh(Part.makeSphere(10), limit=1000)
        self.assertLessEqual(len(few), 1000)
        tight, gentle = se.curvature_range(100)
        self.assertEqual(se.curvature_color(tight / 2, tight, gentle), (.9, .15, .1))
        self.assertEqual(se.curvature_color(math.inf, tight, gentle), (.15, .4, .95))
        middle = se.curvature_color(math.sqrt(tight * gentle), tight, gentle)
        self.assertGreater(middle[1], .8)  # between yellow and green

    def test_curvature_map_lies_on_the_drawn_triangles(self):
        # A map of its own finer mesh sank behind hollow shaded faces in patches.
        part = Part.makeCylinder(5, 20)
        nodes, faces = [], []
        for face in part.Faces:
            points, triangles = face.tessellate(.5)
            start = len(nodes)
            nodes.extend((p.x, p.y, p.z) for p in points)
            faces.append([(a + start, b + start, c + start) for a, b, c in triangles])
        side = next(i for i, f in enumerate(part.Faces) if isinstance(f.Surface, Part.Cylinder))
        points, triangles, radii = se.curvature_mesh(part, limit=2000, drawn=(nodes, faces))
        self.assertTrue(all(abs(r - 5) < 1e-6 for r in radii))
        self.assertLessEqual(len(points), 2000)
        splits = math.sqrt(len(triangles) / len(faces[side]))
        self.assertEqual(splits, int(splits))
        self.assertGreater(splits, 1)
        drawn = [[V(*nodes[i]) for i in triangle] for triangle in faces[side]]

        def on_drawn(p):
            for a, b, c in drawn:
                normal = (b - a).cross(c - a)
                if abs((p - a).dot(normal)) > 1e-9 * normal.Length:
                    continue
                if all(((q - o).cross(p - o)).dot(normal) >= -1e-9 for o, q in ((a, b), (b, c), (c, a))):
                    return True
            return False

        self.assertTrue(all(on_drawn(V(*p)) for p in points))
        # A face the view draws no triangles for gets no colour either.
        self.assertEqual(se.curvature_mesh(part, limit=2000, drawn=(nodes, [[] for _ in faces]))[0], [])

    def test_a_hole_wall_is_concave(self):
        part = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(3, 10, V(10, 10, 0)))
        wall = next(f for f in part.Faces if isinstance(f.Surface, Part.Cylinder))
        self.assertEqual(se.curvature(wall, V(13, 10, 5))['kind'], 'concave')
        self.assertAlmostEqual(se.curvature(wall, V(13, 10, 5))['tight'], 3, places=6)


class ImprintTests(unittest.TestCase):
    def cylinder(self):
        part = Part.makeCylinder(20, 40)
        part.rotate(V(), V(0, 0, 1), 180)  # keep the seam away from the drawing
        wall = next(i for i, f in enumerate(part.Faces) if isinstance(f.Surface, Part.Cylinder))
        return part, wall

    def drawn(self, kind='rectangle', **values):
        part, wall = self.cylinder()
        origin, normal, x = se.frame_at(part.Faces[wall], V(20, 0, 20))
        profile = se.place_outline(se.outline(kind, **values), origin, normal, x, lift=5)
        return part, wall, profile, -normal

    def test_imprint_splits_only_the_front_of_the_wall(self):
        part, wall, profile, direction = self.drawn(width=10, height=10)
        result, report = se.imprint(part, [wall], profile, direction)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), len(part.Faces) + 1)
        self.assertEqual(len(report['regions']), 1)
        region = result.Faces[report['regions'][0]]
        self.assertGreater(region.CenterOfMass.x, 15)
        self.assertAlmostEqual(result.Volume, part.Volume, places=6)

    def test_emboss_and_deboss_change_volume_by_the_depth(self):
        part, wall, profile, direction = self.drawn(width=10, height=10)
        raised, report = se.imprint(part, [wall], profile, direction, 'emboss', 2)
        self.assertTrue(raised.isValid() and len(raised.Solids) == 1)
        self.assertAlmostEqual(report['volume_change'], 200, delta=1)
        sunk, report = se.imprint(part, [wall], profile, direction, 'deboss', 2)
        self.assertTrue(sunk.isValid() and len(sunk.Solids) == 1)
        self.assertAlmostEqual(report['volume_change'], -200, delta=1)

    def test_circle_and_polygon_outlines(self):
        for kind, values in (('circle', {'diameter': 8}), ('polygon', {'diameter': 8, 'sides': 5})):
            part, wall, profile, direction = self.drawn(kind, **values)
            result, report = se.imprint(part, [wall], profile, direction)
            self.assertTrue(result.isValid())
            self.assertEqual(len(report['regions']), 1, kind)

    @unittest.skipUnless(font(), 'FreeCAD bundled font not found')
    def test_text_is_imprinted_as_letters(self):
        part, wall, profile, direction = self.drawn('text', text='HI', size=8, font=font())
        result, report = se.imprint(part, [wall], profile, direction)
        self.assertTrue(result.isValid())
        self.assertGreaterEqual(len(report['regions']), 2)

    def test_inside_a_hole_only_the_near_wall_is_drawn_on(self):
        part = Part.makeBox(40, 40, 30).cut(Part.makeCylinder(10, 30, V(20, 20, 0)))
        wall = next(i for i, f in enumerate(part.Faces) if isinstance(f.Surface, Part.Cylinder))
        origin, normal, x = se.frame_at(part.Faces[wall], V(20, 10, 15))  # away from the seam at +X
        self.assertGreater(normal.y, .99)  # the outside of a hole wall faces the axis
        profile = se.place_outline(se.outline('circle', diameter=6), origin, normal, x)
        result, report = se.imprint(part, [wall], profile, -normal)
        self.assertEqual(len(report['regions']), 1)
        self.assertLess(result.Faces[report['regions'][0]].CenterOfMass.y, 12)

    def test_outline_away_from_the_faces_is_refused(self):
        part, wall = self.cylinder()
        profile = se.place_outline(se.outline('rectangle', width=5, height=5), V(0, 0, 200), V(0, 0, 1), V(1, 0, 0))
        with self.assertRaises(ValueError):
            se.imprint(part, [wall], profile, V(1, 0, 0))

    def test_bad_outlines_are_refused(self):
        for kind, values in (('rectangle', {'width': 0}), ('circle', {'diameter': -1}),
                             ('polygon', {'sides': 2}), ('text', {'text': ' '}), ('star', {})):
            with self.assertRaises(ValueError):
                se.outline(kind, **values)


class FillTests(unittest.TestCase):
    def test_flat_opening_closes_into_a_solid(self):
        box = Part.makeBox(10, 10, 10)
        shell = Part.Shell(box.Faces[1:])
        result, report = se.fill(shell)
        self.assertEqual(report['filled'], 1)
        self.assertTrue(report['closed'])
        self.assertAlmostEqual(result.Volume, 1000, places=6)

    def test_curved_window_gets_a_smooth_patch(self):
        sphere = Part.makeSphere(10)
        cap = [f for f in sphere.Faces]
        cut = sphere.cut(Part.makeBox(30, 30, 30, V(-15, -15, 6)))
        faces = [f for f in cut.Faces if not isinstance(f.Surface, Part.Plane)]
        shell = Part.Shell(faces)
        self.assertTrue(cap)
        result, report = se.fill(shell)
        self.assertTrue(result.isValid())
        self.assertTrue(report['closed'])
        self.assertEqual(report['solids'], 1)
        self.assertAlmostEqual(result.Volume, cut.Volume, delta=cut.Volume * .02)

    def test_a_flat_opening_with_an_island_keeps_it_open(self):
        part = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(3, 10, V(10, 10, 0)))
        top = next(f for f in part.Faces if isinstance(f.Surface, Part.Plane) and f.CenterOfMass.z > 9.9)
        shell = Part.Shell([f for f in part.Faces if not f.isSame(top)])
        result, report = se.fill(shell)
        self.assertEqual(report['filled'], 1)
        self.assertTrue(report['closed'])
        self.assertAlmostEqual(result.Volume, part.Volume, places=4)

    def test_a_curved_opening_with_an_island_is_refused_but_the_island_can_be_filled(self):
        dome = Part.makeSphere(20).cut(Part.makeBox(60, 60, 60, V(-30, -30, -60)))
        dome = dome.cut(Part.makeCylinder(4, 40, V(0, 0, 0)))
        skin = next(f for f in dome.Faces if isinstance(f.Surface, Part.Sphere))
        rest = Part.Shell([f for f in dome.Faces if not f.isSame(skin)])
        with self.assertRaises(ValueError):
            se.fill(rest)
        loops = se.open_loops(rest)
        inner = min(loops, key=lambda w: w.Length)
        edge = next(i for i, e in enumerate(rest.Edges) if any(e.isSame(x) for x in inner.Edges))
        result, report = se.fill(rest, [edge])
        self.assertEqual(report['filled'], 1)

    def test_a_patch_that_would_cut_through_the_part_is_refused(self):
        box = Part.makeBox(10, 10, 10)
        post = Part.makeBox(2, 2, 8, V(4, 4, 6))
        with self.assertRaises(ValueError):
            se.fill(Part.makeCompound([Part.Shell(box.Faces[:5]), post]))

    def test_closed_solid_has_nothing_to_fill(self):
        with self.assertRaises(ValueError):
            se.fill(Part.makeBox(1, 1, 1))

    def test_open_loops_lists_each_opening(self):
        box = Part.makeBox(10, 10, 10)
        self.assertEqual(len(se.open_loops(Part.Shell([box.Faces[i] for i in (0, 1, 2, 3)]))), 2)


class UnwrapTests(unittest.TestCase):
    def test_half_cylinder_flattens_to_its_area(self):
        half = Part.makeCylinder(20, 40, V(), V(0, 0, 1), 180)
        wall = next(f for f in half.Faces if isinstance(f.Surface, Part.Cylinder))
        flat, report = se.unwrap(wall)
        self.assertTrue(flat.isValid())
        self.assertAlmostEqual(flat.Area, wall.Area, delta=wall.Area * .01)
        self.assertLess(abs(flat.BoundBox.ZLength), 1e-6)
        self.assertAlmostEqual(max(report['width'], report['height']), math.pi * 20, delta=1)

    def test_flat_face_is_laid_on_xy(self):
        face = Part.makeBox(10, 4, 3).Faces[0]
        flat, report = se.unwrap(face)
        self.assertAlmostEqual(flat.Area, 12, places=6)
        self.assertLess(flat.BoundBox.ZLength, 1e-6)
        self.assertAlmostEqual(report['area_change'], 0, places=6)


if __name__ == '__main__':
    unittest.main()
