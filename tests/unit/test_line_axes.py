"""World-axis inference against orthographic and perspective cursor rays."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
from simplecad.core import geometry as g
from simplecad.gui.snapping import AXES, Snapper, axis_point

V = App.Vector


class Camera:
    def __init__(self, perspective=False, top=False):
        self.right = V(1, 0, 0) if top else g.unit(V(1, -1, 0))
        self.up = V(0, 1, 0) if top else g.unit(V(1, 1, 2))
        self.forward = -self.right.cross(self.up)
        self.eye = -self.forward * 1000
        self.perspective = perspective

    def getPointOnScreen(self, point):
        offset = point - self.eye
        scale = 800 / offset.dot(self.forward) if self.perspective else 8
        return (400 + offset.dot(self.right) * scale, 300 + offset.dot(self.up) * scale)

    def ray(self, view, pos):
        if self.perspective:
            return self.eye, self.forward + self.right * ((pos[0] - 400) / 800) + self.up * ((pos[1] - 300) / 800)
        return (self.eye + self.right * ((pos[0] - 400) / 8)
                + self.up * ((pos[1] - 300) / 8), self.forward)

    def getCameraNode(self):
        return SimpleNamespace(isOfType=lambda _: self.perspective,
                               position=SimpleNamespace(getValue=lambda: tuple(self.eye)))

    def getViewDirection(self):
        return self.forward


class LineAxisTests(unittest.TestCase):
    def setUp(self):
        self.anchor = V(13, 27, 9)
        self.plane = g.Plane.named("XY", self.anchor)
        self.camera = Camera()
        self.snapper = Snapper(SimpleNamespace(Objects=[]), self.camera)

    def near_axis(self, point, offset=5):
        x, y = self.camera.getPointOnScreen(point)
        ax, ay = self.camera.getPointOnScreen(self.anchor)
        dx, dy = x - ax, y - ay
        length = (dx * dx + dy * dy) ** .5
        return (x - dy * offset / length, y + dx * offset / length)

    def infer(self, pos, **kwargs):
        with patch("simplecad.gui.snapping.ray", side_effect=self.camera.ray), \
                patch("simplecad.gui.snapping.pick", return_value=None):
            return self.snapper.snap_line(pos, self.plane, self.anchor, [], **kwargs)[0]

    def test_each_world_axis_snaps_in_both_directions_through_the_anchor(self):
        # Even an oblique working plane must not rotate the world axes.
        self.plane = g.Plane.from_normal(self.anchor, V(1, 2, 3))
        for name, direction in AXES:
            for sign in (-1, 1):
                target = self.anchor + direction * (30 * sign)
                with self.subTest(axis=name, sign=sign):
                    snap = self.infer(self.near_axis(target))
                    self.assertEqual(snap.label, name + " axis")
                    self.assertEqual(snap.axis, name)
                    self.assertLess((snap.point - target).Length, 1e-6)

    def test_perspective_axis_points_project_back_to_the_requested_position(self):
        self.camera = Camera(perspective=True)
        self.snapper.view = self.camera
        for name, direction in AXES:
            for distance in (-150, 150):
                target = self.anchor + direction * distance
                snap = self.infer(self.near_axis(target, 0))
                self.assertEqual(snap.axis, name)
                self.assertLess((snap.point - target).Length, 1e-6)
                near = self.infer(self.near_axis(target, 5))
                self.assertEqual(near.axis, name)
                self.assertLess((near.point - self.anchor).cross(direction).Length, 1e-7)

    def test_free_directions_and_small_pointer_movements_do_not_force_an_axis(self):
        ax, ay = self.camera.getPointOnScreen(self.anchor)
        for pos in ((ax + 60, ay), (ax + 3, ay + 2)):
            snap = self.infer(pos)
            self.assertFalse(snap.axis)
            self.assertLess(abs((snap.point - self.plane.origin).dot(self.plane.normal)), 1e-7)
        # A direction more than eight degrees off an axis is not captured even
        # when its small screen distance fits the 12-pixel capture band.
        target = self.anchor + V(3.1, 0, 0)
        with patch("simplecad.gui.snapping.ray", side_effect=self.camera.ray):
            self.assertIsNone(self.snapper.line_axis(self.near_axis(target, 4), self.plane, self.anchor))

    def test_endpoint_midpoint_and_face_center_have_priority_over_axis_inference(self):
        target = self.anchor + V(30, .3, 0)
        for label in ("Endpoint", "Midpoint", "Face center"):
            self.snapper.points = [(target, label)]
            snap = self.infer(self.camera.getPointOnScreen(target))
            self.assertEqual(snap.label, label)
            self.assertEqual(snap.point, target)
            self.assertFalse(snap.axis)

    def test_anchor_capture_prevents_accidental_double_click_backtracking(self):
        self.snapper.points = [(self.anchor, "Endpoint"), (self.anchor - V(1, 0, 0), "Midpoint")]
        snap = self.infer(self.camera.getPointOnScreen(self.anchor))
        self.assertEqual(snap.point, self.anchor)
        self.assertEqual(snap.label, "Endpoint")

    def test_snap_off_disables_automatic_axes_but_explicit_lock_still_works(self):
        pos = self.near_axis(self.anchor + V(0, 0, 30))
        snap = self.infer(pos, enabled=False)
        self.assertFalse(snap.axis)
        self.assertAlmostEqual(snap.point.z, self.anchor.z)
        locked = self.infer(pos, enabled=False, axis=V(0, 0, 1))
        self.assertEqual(locked.label, "Z axis locked")
        self.assertEqual(locked.axis, "Z")
        self.assertAlmostEqual(locked.point.x, self.anchor.x)
        self.assertAlmostEqual(locked.point.y, self.anchor.y)

    def test_each_explicit_plane_only_accepts_its_two_world_axes(self):
        for plane_name, allowed in (("XY", "XY"), ("XZ", "XZ"), ("YZ", "YZ")):
            self.plane = g.Plane.named(plane_name, self.anchor)
            for name, direction in AXES:
                pos = self.near_axis(self.anchor + direction * 30, 0)
                snap = self.infer(pos, fixed=True)
                self.assertLess(abs((snap.point - self.anchor).dot(self.plane.normal)), 1e-7)
                self.assertEqual(snap.axis, name if name in allowed else "")
                if name not in allowed:
                    with self.assertRaises(ValueError):
                        self.infer(pos, fixed=True, axis=direction)

    def test_nearer_projected_axis_wins_when_axes_are_close_on_screen(self):
        self.camera.right = g.unit(V(1, -1, 0))
        self.camera.up = g.unit(V(.01, .01, 1))
        self.camera.forward = -self.camera.right.cross(self.camera.up)
        self.camera.eye = -self.camera.forward * 1000
        # X and -Y nearly share a screen direction; at this point -Y is closer.
        target = self.anchor - V(0, 60, 0)
        snap = self.infer(self.near_axis(target, 0))
        self.assertEqual(snap.axis, "Y")
        self.assertLess((snap.point - target).Length, 1e-6)

    def test_axis_toward_camera_is_skipped_but_can_be_locked_for_typed_length(self):
        self.camera = Camera(top=True)
        self.snapper.view = self.camera
        pos = self.camera.getPointOnScreen(self.anchor + V(0, 0, 30))
        with patch("simplecad.gui.snapping.ray", side_effect=self.camera.ray):
            self.assertIsNone(axis_point(self.camera, pos, self.anchor, V(0, 0, 1)))
        snap = self.infer(pos, axis=V(0, 0, 1))
        self.assertEqual(snap.point, self.anchor)
        self.assertEqual(snap.label, "Z axis locked")

    def test_lock_at_anchor_has_no_false_direction_from_pixel_roundoff(self):
        x, y = self.camera.getPointOnScreen(self.anchor)
        for name, axis in AXES:
            snap = self.infer((x + .5, y - .5), axis=axis)
            self.assertEqual(snap.point, self.anchor)
            self.assertEqual(snap.label, name + " axis locked")

    def test_axis_point_behind_camera_is_rejected(self):
        self.camera.perspective = True
        self.camera.eye = V(0, 0, 10)
        with patch("simplecad.gui.snapping.ray", return_value=(V(0, 0, 10), V(0, 0, 1))):
            self.assertIsNone(axis_point(self.camera, (400, 300), V(), V(1, 0, 0)))

    def test_orthographic_axes_can_extend_beyond_the_current_clip_range(self):
        self.camera.forward = V(0, 0, 1)
        with patch("simplecad.gui.snapping.ray", return_value=(V(0, 0, 10), V(0, 0, 1))):
            point = axis_point(self.camera, (400, 300), V(), V(1, 0, 0))
            self.assertLess(point.Length, 1e-7)


if __name__ == "__main__":
    unittest.main()
