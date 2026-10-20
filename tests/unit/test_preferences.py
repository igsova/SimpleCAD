"""Persisted SimpleCAD preferences and their effect on exact snap capture."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import preferences as prefs, geometry as g
from simplecad.gui.snapping import Snapper
from test_center_snapping import source
from test_line_axes import Camera


class PreferenceTests(unittest.TestCase):
    def test_defaults_persistence_and_bounds_in_separate_parameter_group(self):
        path = "User parameter:BaseApp/Preferences/Mod/SimpleCAD_TestPreferences"
        parent = App.ParamGet("User parameter:BaseApp/Preferences/Mod")
        parent.RemGroup("SimpleCAD_TestPreferences")
        try:
            with patch.object(prefs, "PARAMETER_PATH", path):
                self.assertEqual(prefs.load(), prefs.Settings())
                custom = prefs.Settings(show_seams=True, centers=False, axes=False, midpoint_radius=55)
                prefs.save(custom)
                self.assertEqual(prefs.load(), custom)
                App.ParamGet(path).SetInt("center_radius", 10000)
                App.ParamGet(path).SetInt("axis_radius", -5)
                self.assertEqual(prefs.load().center_radius, 120)
                self.assertEqual(prefs.load().axis_radius, 2)
                prefs.save(prefs.Settings())
                self.assertEqual(prefs.load(), prefs.Settings())
        finally:
            parent.RemGroup("SimpleCAD_TestPreferences")

    def snapper(self, settings):
        self.face = Part.makePlane(100, 100)
        doc = SimpleNamespace(Objects=[source(self.face)])
        return Snapper(doc, SimpleNamespace(getPointOnScreen=lambda p: (p.x * 10, p.y * 10)),
                       settings=settings)

    def test_each_point_type_can_be_disabled_without_losing_drawing_planes(self):
        for name, label in (("endpoints", "Endpoint"), ("midpoints", "Midpoint"), ("centers", "Face center")):
            with self.subTest(name=name):
                snapper = self.snapper(replace(prefs.Settings(), **{name: False}))
                self.assertNotIn(label, [label for _, label in snapper.points])
                self.assertEqual(len(snapper.faces), 1)
                with patch("simplecad.gui.snapping.pick", side_effect=AssertionError("Disabled guide should not pick")):
                    if name == "centers":
                        self.assertIsNone(snapper.center_hint((500, 500)))
                    elif name == "midpoints":
                        self.assertIsNone(snapper.midpoint_hint((500, 0)))

    def test_independent_radii_change_capture_not_target_coordinates(self):
        settings = prefs.Settings(endpoint_radius=10, midpoint_radius=50, center_radius=70)
        snapper = self.snapper(settings)
        for point, label, radius in ((App.Vector(), "Endpoint", 10), (App.Vector(50, 0, 0), "Midpoint", 50),
                                     (App.Vector(50, 50, 0), "Face center", 70)):
            x, y = snapper.view.getPointOnScreen(point)
            found = snapper.nearby_points((x, y + radius - 1))
            self.assertEqual(found[0][1], label)
            self.assertLess((found[0][0] - point).Length, 1e-7)
            self.assertFalse(snapper.nearby_points((x, y + radius + 1)))

    def test_hidden_seam_midpoint_is_not_a_drawing_target(self):
        shape = Part.makeCylinder(8, 25)
        edge = next(e for e in shape.Edges if g.is_seam_edge(shape, e))
        midpoint = edge.CenterOfMass
        for show in (False, True):
            snapper = Snapper(SimpleNamespace(Objects=[source(shape)]), Camera(),
                              settings=prefs.Settings(show_seams=show))
            self.assertFalse(any((p - midpoint).Length < 1e-7 for p, _ in snapper.points))

    def test_disabled_axes_leave_free_drawing_and_explicit_locks_available(self):
        camera = Camera(top=True)
        snapper = Snapper(SimpleNamespace(Objects=[]), camera, settings=prefs.Settings(axes=False))
        plane = g.Plane.named()
        pos = camera.getPointOnScreen(App.Vector(50, 1, 0))
        with patch("simplecad.gui.snapping.ray", side_effect=camera.ray), patch("simplecad.gui.snapping.pick", return_value=None):
            free, _ = snapper.snap_line(pos, plane, App.Vector(), [])
            locked, _ = snapper.snap_line(pos, plane, App.Vector(), [], axis=App.Vector(1, 0, 0))
            other = snapper.snap(pos, plane, anchor=App.Vector())
        self.assertFalse(free.axis)
        self.assertAlmostEqual(free.point.y, 1)
        self.assertEqual(locked.axis, "X")
        self.assertAlmostEqual(locked.point.y, 0)
        self.assertAlmostEqual(other.point.y, 1)

    def test_axis_radius_changes_capture_band(self):
        camera = Camera(top=True)
        pos = camera.getPointOnScreen(App.Vector(50, 2, 0))  # 16 px off X
        with patch("simplecad.gui.snapping.ray", side_effect=camera.ray):
            for radius, expected in ((12, False), (24, True)):
                snapper = Snapper(SimpleNamespace(Objects=[]), camera, settings=prefs.Settings(axis_radius=radius))
                self.assertEqual(bool(snapper.line_axis(pos, g.Plane.named(), App.Vector())), expected)


class LongPressMenuTests(unittest.TestCase):
    def test_drawing_suspends_and_restores_only_what_it_turned_off(self):
        root = "User parameter:BaseApp/Preferences/SimpleCAD_TestLongPress"
        parent = App.ParamGet("User parameter:BaseApp/Preferences")
        self.addCleanup(parent.RemGroup, "SimpleCAD_TestLongPress")
        with patch.object(prefs, "PARAMETER_PATH", root + "/Own"), patch.object(prefs, "VIEW_PATH", root + "/View"):
            view = App.ParamGet(root + "/View")
            prefs.suspend_long_press_menu()
            self.assertFalse(view.GetBool(prefs.LONG_PRESS, True))
            prefs.suspend_long_press_menu()  # A second tool does not lose the original.
            prefs.restore_long_press_menu()
            self.assertTrue(view.GetBool(prefs.LONG_PRESS, False))
            # A menu the user turned off stays off.
            view.SetBool(prefs.LONG_PRESS, False)
            prefs.suspend_long_press_menu()
            prefs.restore_long_press_menu()
            self.assertFalse(view.GetBool(prefs.LONG_PRESS, True))
