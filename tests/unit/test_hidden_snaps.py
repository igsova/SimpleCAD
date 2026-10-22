"""Snap points hidden behind the face under the pointer are not offered."""
import unittest

import FreeCAD as App
import Part
from test_center_snapping import snapshot, source

V = App.Vector


def camera(direction):
    """An orthographic projection, 10 px per mm, looking along direction."""
    d = V(direction).normalize()
    across = d.cross(V(0, 0, 1)).normalize()
    up = across.cross(d)
    return d, (lambda point: (point.dot(across) * 10, point.dot(up) * 10))


def offered(nearby, point):
    return any((p - point).Length < 1e-7 for p, _ in nearby)


def face_at(shape, center):
    return next(f for f in shape.Faces if (f.CenterOfMass - center).Length < 1e-7)


class HiddenSnapTests(unittest.TestCase):
    def setUp(self):
        # Looking down on the corner at (40, 30, 20): (0, 0, 0) is the one
        # corner hidden, behind the top. The view reports single-precision
        # directions, so the line of sight meets the top only to rounding.
        self.box = Part.makeBox(40, 30, 20)
        self.direction, self.project = camera(V(-0.5773502588272095, -0.5773502588272095, -0.5773503184318542))
        self.snapper = snapshot(source(self.box), project=self.project, direction=self.direction)
        self.top = face_at(self.box, V(20, 15, 20))
        # The top point in front of the hidden corner.
        self.hit = (None, self.top, V(20, 20, 20), "Face6")

    def at(self, point, offset=(0, 0)):
        x, y = self.project(point)
        return x + offset[0], y + offset[1]

    def test_a_corner_behind_the_hovered_face_is_not_snapped(self):
        corner = V()
        pos = self.at(corner)
        # Without the face under the pointer the corner is still offered.
        self.assertLess((self.snapper.nearby_points(pos)[0][0] - corner).Length, 1e-9)
        nearby = self.snapper.nearby_points(pos, hit=self.hit)
        self.assertFalse([p for p, _ in nearby if p.z < 20 - 1e-6], nearby)

    def test_the_hint_does_not_aim_at_a_hidden_corner(self):
        pos = self.at(V(), (30, 0))
        self.assertLess((self.snapper.endpoint_hint(pos) - V()).Length, 1e-9)
        hint = self.snapper.endpoint_hint(pos, hit=self.hit)
        self.assertTrue(hint is None or (hint - V()).Length > 1, hint)

    def test_visible_corners_and_points_in_front_are_kept(self):
        for corner in (V(40, 30, 20), V(0, 0, 20), V(40, 0, 0), V(0, 30, 0)):
            with self.subTest(corner=corner):
                hit = (None, self.top, corner, "Face6") if corner.z == 20 else None
                ranked = self.snapper.nearby_points(self.at(corner, (3, 0)), hit=hit)
                self.assertLess((ranked[0][0] - corner).Length, 1e-9)
        # A corner of a block standing on the top is in front of it.
        block = Part.makeBox(5, 5, 10, V(10, 10, 20))
        snapper = snapshot(source(self.box), source(block, "Block"), project=self.project,
                           direction=self.direction)
        corner = V(15, 15, 30)
        ranked = snapper.nearby_points(self.at(corner), hit=(None, self.top, V(20, 20, 20), "Face6"))
        self.assertLess((ranked[0][0] - corner).Length, 1e-9)

    def test_a_point_on_the_silhouette_of_the_hovered_face_is_kept(self):
        # Seen straight down, the bottom corners sit right under the top's
        # corners: the line of sight only grazes the top's outline.
        snapper = snapshot(source(self.box))
        hit = (None, self.top, V(5, 5, 20), "Face6")
        ranked = snapper.nearby_points((2, 2), hit=hit)
        self.assertLess((ranked[0][0] - V(0, 0, 20)).Length, 1e-9)
        self.assertTrue(offered(ranked, V()))

    def test_a_curved_face_hides_its_own_far_side(self):
        # Looking at a cylinder from -X and a little above: its seam, at +X,
        # is at the back.
        cylinder = Part.makeCylinder(10, 20)
        direction, project = camera(V(1, 0, -.3))
        snapper = snapshot(source(cylinder), project=project, direction=direction)
        wall = next(f for f in cylinder.Faces if not isinstance(f.Surface, Part.Plane))
        bottom, top = V(10, 0, 0), V(10, 0, 20)
        x, y = project(bottom)
        hit = (None, wall, V(-10, 0, 6), "Face1")
        self.assertTrue(offered(snapper.nearby_points((x, y)), bottom))
        self.assertFalse(offered(snapper.nearby_points((x, y), hit=hit), bottom))
        # The top of the seam shows above the near wall.
        x, y = project(top)
        ranked = snapper.nearby_points((x + 3, y), hit=(None, wall, V(-10, 0, 20), "Face1"))
        self.assertLess((ranked[0][0] - top).Length, 1e-9)


if __name__ == "__main__":
    unittest.main()
