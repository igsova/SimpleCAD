"""Move, Copy and Vertex Move points clicked on a face lie on that face."""
import math
import struct
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from test_center_snapping import snapshot, source

V = App.Vector


def single(point):
    """The single-precision point the 3D view reports for a click."""
    return V(*(struct.unpack('f', struct.pack('f', value))[0] for value in point))


class FaceClickTests(unittest.TestCase):
    def click(self, shape, face, exact, anchor=None, sight=V(0, 0, -1), project=None):
        picked = single(exact)
        self.assertGreater((picked - exact).Length, 1e-7)
        snapper = snapshot(source(shape), project=project)
        pos = snapper.view.getPointOnScreen(exact)
        with patch("simplecad.gui.snapping.pick", return_value=(source(shape), face, picked, "Face")), \
                patch("simplecad.gui.snapping.ray", return_value=(exact - sight * 1000, sight)):
            return snapper.snap(pos, g.Plane.from_normal(picked, -sight), anchor, spatial=True)

    def test_a_click_on_a_flat_face_lies_on_its_plane(self):
        # The level of the slot top in the reported model.
        top = 299.3590717632093
        box = Part.makeBox(100, 80, top)
        face = next(f for f in box.Faces if g.face_normal(f).z > .5)
        for anchor in (None, V(-50, -70, 20)):
            with self.subTest(anchor=anchor):
                snap = self.click(box, face, V(37.3, 41.7, top), anchor)
                self.assertEqual(snap.label, "Face")
                self.assertEqual(snap.point.z, top)
                self.assertLess((snap.point - V(37.3, 41.7, top)).Length, 1e-4)

    def test_a_click_on_a_curved_face_lies_on_its_surface(self):
        radius = 7.3
        cylinder = Part.makeCylinder(radius, 20, V(150, 210, 280))
        face = next(f for f in cylinder.Faces if isinstance(f.Surface, Part.Cylinder))
        angle = math.radians(250)
        exact = V(150 + radius * math.cos(angle), 210 + radius * math.sin(angle), 291.37)
        # Seen from the front, away from its seam and rims.
        snap = self.click(cylinder, face, exact, sight=V(0, 1, 0), project=lambda p: (p.x * 10, p.z * 10))
        self.assertEqual(snap.label, "Face")
        self.assertLess(abs(math.hypot(snap.point.x - 150, snap.point.y - 210) - radius), 1e-9)


if __name__ == "__main__":
    unittest.main()
