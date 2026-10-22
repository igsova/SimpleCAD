"""Native Part geometry with a simple screen projection for snap ranking."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.gui.snapping import Snapper

V = App.Vector


def source(shape, name="Shape", visible=True, type_id="Part::Feature", parents=()):
    return SimpleNamespace(Name=name, Shape=shape, TypeId=type_id, InList=parents,
                           ViewObject=SimpleNamespace(Visibility=visible))


def snapshot(*objects, exclude=(), project=None, direction=(0, 0, -1)):
    view = SimpleNamespace(getPointOnScreen=project or (lambda point: (point.x * 10, point.y * 10)),
                           getViewDirection=lambda: direction)
    return Snapper(SimpleNamespace(Objects=objects), view, exclude)


class CenterSnappingTests(unittest.TestCase):
    def assert_point(self, actual, expected):
        self.assertLess((actual - expected).Length, 1e-7)

    def snap_to(self, snapper, point, label, offset=(5, 3)):
        projected = snapper.view.getPointOnScreen(point)
        pos = (projected[0] + offset[0], projected[1] + offset[1])
        with patch("simplecad.gui.snapping.pick", return_value=None):
            start, plane = snapper.snap_start(pos, g.Plane.named())
            end, _ = snapper.snap_line(pos, plane, V(-200, -200, -200), [])
        self.assert_point(start.point, point)
        self.assert_point(end.point, point)
        self.assertEqual(start.label, label)
        self.assertEqual(end.label, label)
        return plane

    def test_rectangle_has_all_nine_targets_at_both_line_ends(self):
        face = Part.makePlane(40, 30)
        snapper = snapshot(source(face))
        expected = [(V(x, y, 0), "Endpoint") for x, y in ((0, 0), (40, 0), (40, 30), (0, 30))]
        expected += [(V(x, y, 0), "Midpoint") for x, y in ((20, 0), (40, 15), (20, 30), (0, 15))]
        expected += [(V(20, 15, 0), "Face center")]
        self.assertEqual(len(snapper.points), 9)
        for point, label in expected:
            with self.subTest(point=point, label=label):
                self.snap_to(snapper, point, label)

    def test_scalene_triangle_uses_centroid_not_bounding_box_center(self):
        points = [V(), V(60, 0, 0), V(0, 30, 0)]
        face = Part.Face(Part.makePolygon(points + [points[0]]))
        expected = sum(points, V()) / 3
        self.assertGreater((face.BoundBox.Center - expected).Length, 5)
        snapper = snapshot(source(face))
        self.snap_to(snapper, expected, "Face center")
        for i in range(3):
            self.snap_to(snapper, (points[i] + points[(i + 1) % 3]) / 2, "Midpoint")

    def test_disk_uses_circle_center(self):
        center = V(25, -30, 12)
        face = Part.Face(Part.Wire([Part.makeCircle(15, center)]))
        snapper = snapshot(source(face))
        plane = self.snap_to(snapper, center, "Face center")
        self.assertLess(abs((center - plane.origin).dot(plane.normal)), 1e-7)

    def test_trapezoid_uses_area_centroid(self):
        vertices = [V(), V(40, 0, 0), V(30, 20, 0), V(0, 20, 0)]
        face = Part.Face(Part.makePolygon(vertices + [vertices[0]]))
        twice_area = cx = cy = 0.0
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            cross = a.x * b.y - b.x * a.y
            twice_area += cross
            cx += (a.x + b.x) * cross
            cy += (a.y + b.y) * cross
        center = V(cx / (3 * twice_area), cy / (3 * twice_area), 0)
        self.snap_to(snapshot(source(face)), center, "Face center")

    def test_midpoint_of_trimmed_arc_is_halfway_along_arc(self):
        edge = Part.makeCircle(20, V(), V(0, 0, 1), 20, 100)
        expected = V(20 * math.cos(math.radians(60)), 20 * math.sin(math.radians(60)), 0)
        self.snap_to(snapshot(source(edge)), expected, "Midpoint")
        chord_middle = (edge.Vertexes[0].Point + edge.Vertexes[-1].Point) / 2
        self.assertGreater((chord_middle - expected).Length, 1)

    def test_centers_and_midpoints_follow_rotated_translated_geometry(self):
        face = Part.makePlane(40, 30)
        placement = App.Placement(V(70, -30, 12), App.Rotation(V(1, 2, 3), 37))
        face.Placement = placement
        snapper = snapshot(source(face), project=lambda p: (p.x * 10, p.y * 10 + p.z * 3))
        for point, label in ((V(20, 15, 0), "Face center"), (V(20, 0, 0), "Midpoint")):
            plane = self.snap_to(snapper, placement.multVec(point), label)
            self.assertGreater(abs(plane.normal.dot(placement.Rotation.multVec(V(0, 0, 1)))), .999999)

    def test_ring_center_in_hole_still_supplies_its_actual_plane(self):
        disk = Part.Face(Part.Wire([Part.makeCircle(20)]))
        hole = Part.Face(Part.Wire([Part.makeCircle(5)]))
        ring = disk.cut(hole).Faces[0]
        placement = App.Placement(V(30, 40, 50), App.Rotation(V(1, 0, 0), 55))
        ring.Placement = placement
        center = placement.multVec(V())
        self.assertFalse(g.point_on_face(ring, center))
        snapper = snapshot(source(ring), project=lambda p: (p.x * 10, p.y * 10 + p.z * 3))
        plane = self.snap_to(snapper, center, "Face center")
        self.assertGreater(abs(plane.normal.dot(placement.Rotation.multVec(V(0, 0, 1)))), .999999)
        self.assertEqual(len(snapper.faces_at(center)), 1)

    def test_fixed_plane_filters_off_plane_centers_and_snap_off_disables_them(self):
        snapper = snapshot(source(Part.makePlane(40, 30, V(0, 0, 10))))
        plane = g.Plane.named("XY")
        pos = (205, 153)
        with patch("simplecad.gui.snapping.ray", return_value=(V(20.5, 15.3, 100), V(0, 0, -1))), \
                patch("simplecad.gui.snapping.pick", return_value=None):
            fixed = snapper.snap(pos, plane)
            spatial = snapper.snap(pos, plane, spatial=True)
            disabled, _ = snapper.snap_start(pos, plane, enabled=False)
        self.assert_point(fixed.point, V(20.5, 15.3, 0))
        self.assert_point(spatial.point, V(20, 15, 10))
        self.assertEqual(spatial.label, "Face center")
        self.assertEqual(disabled.label, "Plane")
        self.assert_point(disabled.point, fixed.point)

    def test_auto_line_connects_centers_on_different_planes_without_projection(self):
        first = Part.makePlane(40, 30)
        second = Part.makePlane(40, 30, V(60, 60, 40), V(0, -1, 0))
        snapper = snapshot(source(first), source(second, "Second"), project=lambda p: (p.x * 10, p.y * 10 + p.z * 3))
        target = second.CenterOfMass
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, _ = snapper.snap_line(snapper.view.getPointOnScreen(target), g.Plane.from_face(first),
                                        first.CenterOfMass, snapper.faces_at(first.CenterOfMass))
        self.assert_point(snap.point, target)
        self.assertEqual(snap.label, "Face center")

    def test_hovered_face_wins_over_almost_overlapping_back_center(self):
        back = Part.makePlane(40, 30)
        front = Part.makePlane(40, 30, V(0, 0, 10))
        snapper = snapshot(source(back), source(front, "Front"), project=lambda p: (p.x * 10 + p.z * .1, p.y * 10))
        center = front.CenterOfMass
        # The back center is one pixel closer, but the visible front face owns the snap.
        with patch("simplecad.gui.snapping.pick", return_value=(None, front, center, "Face1")):
            snap, _ = snapper.snap_start((200, 150), g.Plane.named())
        self.assert_point(snap.point, center)
        self.assertEqual(snap.label, "Face center")

    def test_tie_priorities_and_capture_radius_do_not_steal_distant_targets(self):
        snapper = snapshot(source(Part.makePlane(40, 30)))
        snapper.points = [(V(20, 15, 0), "Face center"), (V(20, 15, 0), "Midpoint"), (V(20, 15, 0), "Endpoint")]
        self.assertEqual([label for _, label in snapper.nearby_points((200, 150))], ["Endpoint", "Midpoint", "Face center"])
        self.assertEqual(snapper.nearby_points((241, 150)), [])
        front = Part.makePlane(40, 30, V(0, 0, 10))
        snapper.points = [(V(20, 15, 20), "Endpoint"), (V(21, 15, 10), "Face center")]
        # Native face ownership is only a tiebreak within two pixels. (The
        # endpoint is in front of the face: one behind it would be hidden.)
        nearby = snapper.nearby_points((200, 150), hit=(None, front, front.CenterOfMass, "Face1"))
        self.assertEqual(nearby[0][1], "Endpoint")

    def test_center_capture_is_forty_pixels_and_edge_targets_twenty_four(self):
        snapper = snapshot(source(Part.makePlane(40, 30)))
        for offset in ((32, 0), (-39, 0), (0, 39), (0, -40)):
            self.snap_to(snapper, V(20, 15, 0), "Face center", offset)
        self.snap_to(snapper, V(20, 0, 0), "Midpoint", (0, 23))
        self.snap_to(snapper, V(), "Endpoint", (-23, 0))
        self.assertFalse(snapper.nearby_points((241, 150)))
        self.assertFalse(snapper.nearby_points((-25, 0)))

    def test_larger_center_radius_does_not_override_a_closer_endpoint(self):
        snapper = snapshot(source(Part.makePlane(40, 30)))
        snapper.points.append((V(23, 15, 0), "Endpoint"))
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, _ = snapper.snap_start((228, 150), g.Plane.named())
        self.assertEqual(snap.label, "Endpoint")
        self.assert_point(snap.point, V(23, 15, 0))

    def test_center_hint_is_available_before_entering_the_capture_radius(self):
        face = Part.makePlane(40, 30)
        snapper = snapshot(source(face))
        self.assertFalse(snapper.nearby_points((140, 150)))
        with patch("simplecad.gui.snapping.pick", return_value=(None, face, V(14, 15, 0), "Face1")):
            self.assert_point(snapper.center_hint((140, 150)), V(20, 15, 0))
            self.assertIsNone(snapper.center_hint((140, 150), g.Plane.named("XY", V(0, 0, 10))))

    def test_center_hint_requires_a_hovered_face_in_the_editable_snapshot(self):
        face = Part.makePlane(40, 30)
        snapper = snapshot(source(face))
        with patch("simplecad.gui.snapping.pick", return_value=None):
            self.assertIsNone(snapper.center_hint((200, 150)))
        other = Part.makePlane(40, 30)
        with patch("simplecad.gui.snapping.pick", return_value=(None, other, V(20, 15, 0), "Face1")):
            self.assertIsNone(snapper.center_hint((200, 150)))

    def test_midpoint_guide_finds_hovered_edge_or_nearby_face_boundary(self):
        face = Part.makePlane(40, 30)
        snapper = snapshot(source(face))
        midpoint = V(20, 0, 0)
        edge = next(e for e in face.Edges if (e.CenterOfMass - midpoint).Length < 1e-7)
        with patch("simplecad.gui.snapping.pick", return_value=(None, edge, V(5, 0, 0), "Edge1")):
            self.assert_point(snapper.midpoint_hint((50, 0)), midpoint)
        with patch("simplecad.gui.snapping.pick", return_value=(None, face, V(20, 5, 0), "Face1")):
            self.assert_point(snapper.midpoint_hint((200, 55)), midpoint)
            self.assertIsNone(snapper.midpoint_hint((200, 65)))
            self.assertFalse(snapper.nearby_points((200, 55)))  # Guidance does not increase capture.

    def test_midpoint_guide_filters_missing_foreign_hidden_and_off_plane_geometry(self):
        edge = Part.makeLine(V(0, 0, 10), V(40, 0, 10))
        snapper = snapshot(source(edge))
        with patch("simplecad.gui.snapping.pick", return_value=(None, edge, V(20, 0, 10), "Edge1")):
            self.assertIsNone(snapper.midpoint_hint((200, 0), g.Plane.named("XY")))
            hidden = snapshot(source(edge, visible=False))
            self.assertIsNone(hidden.midpoint_hint((200, 0)))
        foreign = Part.makeLine(V(0, 0, 10), V(40, 0, 10))
        with patch("simplecad.gui.snapping.pick", return_value=(None, foreign, V(20, 0, 10), "Edge1")):
            self.assertIsNone(snapper.midpoint_hint((200, 0)))
        with patch("simplecad.gui.snapping.pick", return_value=None):
            self.assertIsNone(snapper.midpoint_hint((200, 0)))

    def test_curved_edge_guide_matches_the_exact_half_length_snap(self):
        edge = Part.makeCircle(20, V(), V(0, 0, 1), 20, 100)
        midpoint = V(10, 20 * math.sin(math.radians(60)), 0)
        snapper = snapshot(source(edge))
        with patch("simplecad.gui.snapping.pick", return_value=(None, edge, edge.Vertexes[0].Point, "Edge1")):
            self.assert_point(snapper.midpoint_hint((150, 100)), midpoint)
        self.snap_to(snapper, midpoint, "Midpoint")

    def test_hidden_excluded_parametric_and_container_objects_are_not_targets(self):
        face = Part.makePlane(40, 30)
        hidden = source(face, "Hidden", visible=False)
        excluded = source(face, "Excluded")
        parametric = source(face, "Parametric", type_id="Part::Box")
        parent = SimpleNamespace(hasExtension=lambda _: True)
        contained = source(face, "Contained", parents=[parent])
        snapper = snapshot(hidden, excluded, parametric, contained, exclude=[excluded])
        self.assertEqual(snapper.points, [])

    def test_cylinder_offers_flat_cap_centers_but_no_center_inside_curved_wall(self):
        snapper = snapshot(source(Part.makeCylinder(10, 20)))
        centers = [point for point, label in snapper.points if label == "Face center"]
        self.assertEqual(len(centers), 2)
        for expected in (V(), V(0, 0, 20)):
            self.assertTrue(any((point - expected).Length < 1e-7 for point in centers))


if __name__ == "__main__":
    unittest.main()


class CircleCenterTests(unittest.TestCase):
    """Move and Copy land exactly on hole centers, round or faceted."""

    def plate(self):
        body = Part.makeBox(60, 40, 4).cut(Part.makeCylinder(2, 10, V(10, 10, -1)))
        corners = [V(40 + 2 * math.cos(math.tau * i / 48), 20 + 2 * math.sin(math.tau * i / 48), -1) for i in range(48)]
        return body.cut(Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 10))).Solids[0]

    def move_snap(self, snapper, point, offset=(4, 3)):
        projected = snapper.view.getPointOnScreen(point)
        pos = (projected[0] + offset[0], projected[1] + offset[1])
        with patch("simplecad.gui.snapping.pick", return_value=None), \
                patch("simplecad.gui.snapping.ray", return_value=(V(point.x, point.y, 100), V(0, 0, -1))):
            return snapper.snap(pos, g.Plane.from_normal(point, V(0, 0, 1)), anchor=V(-50, -50, -50), spatial=True)

    def test_round_and_faceted_hole_centers_are_snap_targets(self):
        from simplecad.gui.snapping import circle_centers
        centers = circle_centers(self.plate(), self.plate().Faces)
        for expected in (V(10, 10, 4), V(10, 10, 0), V(40, 20, 4), V(40, 20, 0)):
            self.assertTrue(any((c - expected).Length < 1e-4 for c in centers), expected)
        # The plate's rectangular outline is not round.
        self.assertEqual(len(centers), 4)

    def test_move_snaps_to_a_hole_center(self):
        snapper = snapshot(source(self.plate()))
        for center in (V(10, 10, 4), V(40, 20, 4)):
            snap = self.move_snap(snapper, center)
            self.assertEqual(snap.label, "Circle center")
            self.assertLess((snap.point - center).Length, 1e-4)

    def test_a_many_sided_non_round_loop_has_no_center(self):
        from simplecad.gui.snapping import circle_center
        # A notched rectangle drawn with many short sides.
        points = [V(x, 0, 0) for x in range(6)] + [V(5, y, 0) for y in range(1, 4)] + [V(x, 3, 0) for x in range(4, -1, -1)]
        edges = Part.makePolygon(points + [V(0, 1, 0), points[0]]).Edges
        self.assertGreaterEqual(len(edges), 8)
        self.assertIsNone(circle_center(edges))


class VertexPriorityTests(unittest.TestCase):
    def crowded(self):
        # A thin triangle at a vertex: its short edge's midpoint and its face
        # center sit on screen almost on top of the vertex.
        sliver = Part.Face(Part.makePolygon([V(0, 0, 0), V(3, .2, 0), V(3, -.2, 0), V(0, 0, 0)]))
        return snapshot(source(sliver))

    def test_a_vertex_wins_close_to_the_pointer(self):
        snapper = self.crowded()
        ranked = snapper.nearby_points((8, 0))
        self.assertEqual(ranked[0][1], "Endpoint")
        self.assertLess((ranked[0][0] - V()).Length, 1e-9)
        # Without the vertex rule the edge midpoint, nearer the pointer, would win.
        self.assertIn("Midpoint", [label for _, label in ranked])

    def test_farther_away_the_nearest_target_still_wins(self):
        snapper = self.crowded()
        ranked = snapper.nearby_points((20, 0))  # On the face center, 20 px from the vertex.
        self.assertNotEqual(ranked[0][1], "Endpoint")

    def test_the_nearest_vertex_is_shown_before_capture(self):
        snapper = self.crowded()
        hint = snapper.endpoint_hint((0, 35))
        self.assertIsNotNone(hint)
        self.assertLess((hint - V()).Length, 1e-9)
        self.assertIsNone(snapper.endpoint_hint((0, 80)))


class PointerMoveCostTests(unittest.TestCase):
    def test_one_pointer_move_asks_the_view_for_its_objects_once(self):
        from simplecad.gui import snapping
        calls = []
        view = SimpleNamespace(getObjectsInfo=lambda pos: calls.append(pos) or [])
        doc = SimpleNamespace(Name='Doc')
        with snapping.shared_picks():
            for options in ({}, {'face_only': True}, {'prefer_boundary': True}):
                self.assertIsNone(snapping.pick(view, doc, (3, 4), **options))
            snapping.pick(view, doc, (5, 4))
        self.assertEqual(calls, [(3, 4), (5, 4)])
        # Outside a pointer move the scene may have changed: ask again.
        snapping.pick(view, doc, (3, 4))
        self.assertEqual(len(calls), 3)

    def test_only_targets_tied_with_the_nearest_measure_the_hovered_face(self):
        face = Part.makePlane(40, 30)
        snapper = snapshot(source(face))
        hit = (None, face, V(), 'Face1')
        with patch('simplecad.gui.snapping.point_on_face', wraps=g.point_on_face) as measured:
            ranked = snapper.nearby_points((3, 0), hit=hit)
        self.assertEqual(ranked[0][1], 'Endpoint')
        near = sum(1 for distance, _, _ in snapper.screen_points((3, 0), 1e9)
                   if distance <= 3 + 2)
        self.assertEqual(measured.call_count, near)

    def test_a_face_plane_is_measured_once_per_snapshot(self):
        holed = Part.makePlane(40, 30).cut(Part.makeCylinder(3, 1, V(10, 10, -.5)))
        face = holed.Faces[0]
        snapper = snapshot(source(holed))
        with patch('simplecad.core.geometry.face_normal', wraps=g.face_normal) as measured:
            plane = snapper.face_plane(face)
            snapper.face_plane(face)
            self.assertLess((snapper.face_center(face) - face.CenterOfMass).Length, 1e-12)
        self.assertEqual(measured.call_count, 1)
        expected = g.Plane.from_face(face)
        for name in ('origin', 'u', 'v', 'normal'):
            self.assertEqual(tuple(getattr(plane, name)), tuple(getattr(expected, name)))
        reversed_face = face.copy()
        reversed_face.reverse()
        self.assertEqual(tuple(snapper.face_plane(reversed_face).normal), tuple(g.Plane.from_face(reversed_face).normal))
        plane.origin.x += 5  # Callers may move their plane; the cache keeps its own.
        self.assertEqual(tuple(snapper.face_plane(face).origin), tuple(expected.origin))
        curved = Part.makeCylinder(2, 3).Faces[0]
        with self.assertRaises(ValueError):
            snapper.face_plane(curved)
