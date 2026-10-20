"""Snapping onto edges, and where a followed axis crosses an edge."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from simplecad.core import geometry as g
from simplecad.gui.snapping import Snapper
from test_line_axes import Camera

V = App.Vector


class EdgeSnappingTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(top=True)
        self.snapper = Snapper(SimpleNamespace(Objects=[]), self.camera)
        # A slanted edge on z = 0, like a face boundary the line should reach.
        self.edge = Part.makeLine(V(10, -20, 0), V(30, 20, 0))
        self.snapper.index_segments([self.edge])
        self.plane = g.Plane.named("XY")
        for target, kwargs in (("simplecad.gui.snapping.ray", {'side_effect': self.camera.ray}),
                               ("simplecad.gui.snapping.pick", {'return_value': None})):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def screen(self, point, dx=0, dy=0):
        x, y = self.camera.getPointOnScreen(point)
        return (x + dx, y + dy)

    def on_edge(self, point):
        return self.edge.distToShape(Part.Vertex(point))[0] < 1e-9

    def test_pointer_near_an_edge_lands_exactly_on_it(self):
        target = V(20, 0, 0)
        snap, _ = self.snapper.snap_line(self.screen(target, 6, 0), self.plane, V(-20, -30, 0), [])
        self.assertEqual(snap.label, "On edge")
        self.assertTrue(self.on_edge(snap.point))

    def test_following_an_axis_stops_exactly_where_it_crosses_the_edge(self):
        # From the anchor along +X, the axis meets the edge at x = 20 + 0.5 * 7.
        anchor = V(0, 7, 0)
        crossing = V(23.5, 7, 0)
        snap, _ = self.snapper.snap_line(self.screen(crossing, 5, 1), self.plane, anchor, [])
        self.assertEqual(snap.label, "X axis on edge")
        self.assertEqual(snap.axis, "X")
        self.assertLess((snap.point - crossing).Length, 1e-9)
        self.assertTrue(self.on_edge(snap.point))

    def test_a_locked_axis_also_stops_on_the_edge(self):
        anchor = V(0, 7, 0)
        crossing = V(23.5, 7, 0)
        snap, _ = self.snapper.snap_line(self.screen(crossing, 8, 0), self.plane, anchor, [], axis=V(1, 0, 0))
        self.assertEqual(snap.label, "X axis on edge")
        self.assertLess((snap.point - crossing).Length, 1e-9)

    def test_far_from_edges_the_axis_is_unchanged(self):
        anchor = V(0, 7, 0)
        snap, _ = self.snapper.snap_line(self.screen(V(8, 7, 0), 0, 1), self.plane, anchor, [])
        self.assertEqual(snap.label, "X axis")

    def test_curved_edges_snap_to_the_true_curve(self):
        circle = Part.makeCircle(5, V(60, 0, 0))
        self.snapper.index_segments([circle])
        snap, _ = self.snapper.snap_line(self.screen(V(65, 0, 0), 4, 3), self.plane, V(40, -30, 0), [])
        self.assertEqual(snap.label, "On edge")
        self.assertAlmostEqual((snap.point - V(60, 0, 0)).Length, 5, places=9)

    def test_the_setting_turns_it_off(self):
        from dataclasses import replace
        self.snapper.settings = replace(self.snapper.settings, edges=False)
        snap, _ = self.snapper.snap_line(self.screen(V(20, 0, 0), 6, 0), self.plane, V(-20, -30, 0), [])
        self.assertNotEqual(snap.label, "On edge")


if __name__ == '__main__':
    unittest.main()
