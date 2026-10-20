"""Arrow-key workplanes: SketchUp colours, Auto toggling and planes through the start."""
from types import SimpleNamespace
import unittest

import FreeCAD as App
from simplecad.core import geometry as g
from simplecad.gui.snapping import Snap

try:
    from simplecad.gui.controller import Controller
except ImportError:  # FreeCADGui/pivy unavailable in this interpreter.
    Controller = None

V = App.Vector


class ArrowPlaneTests(unittest.TestCase):
    def test_arrows_face_red_green_blue_and_toggle_back_to_auto(self):
        normals = {'Right': V(1, 0, 0), 'Left': V(0, 1, 0), 'Up': V(0, 0, 1)}
        for arrow, normal in normals.items():
            name = g.arrow_plane(arrow)
            self.assertAlmostEqual(abs(g.Plane.named(name).normal.dot(normal)), 1)
            self.assertIsNone(g.arrow_plane(arrow, name))  # The same arrow again is Auto.
            self.assertIsNone(g.arrow_plane('Down', name))
        self.assertEqual(g.arrow_plane('Up', 'YZ'), 'XY')
        self.assertIsNone(g.arrow_plane('Down'))
        self.assertEqual(g.ARROW_AXES, {'Right': 'X', 'Left': 'Y', 'Up': 'Z'})

    def test_same_plane_needs_parallel_normals_and_a_shared_point(self):
        top = g.Plane.from_normal(V(5, 5, 10), V(0, 0, -1))
        self.assertTrue(g.same_plane(top, g.Plane.named('XY', V(1, 2, 10))))
        self.assertFalse(g.same_plane(top, g.Plane.named('XY', V(1, 2, 10.01))))
        self.assertFalse(g.same_plane(top, g.Plane.named('YZ', V(5, 5, 10))))

    def test_empty_space_starts_on_the_ground_unless_it_is_edge_on(self):
        iso = V(-1, 1, -1)
        for name in ('XY', 'XZ', 'YZ'):
            self.assertAlmostEqual(g.locked_start(name, iso).normal.z, 1)
            # A perspective ray is not normalized; only its slope matters.
            self.assertAlmostEqual(g.locked_start(name, iso * 250).normal.z, 1)
        front, side = V(0, 1, 0), V(-1, 0, .05)
        plane = g.locked_start('XZ', front)
        self.assertAlmostEqual(abs(plane.normal.y), 1)
        self.assertLess(plane.origin.Length, 1e-12)
        self.assertAlmostEqual(abs(g.locked_start('YZ', side).normal.x), 1)
        # XY is the ground itself; an edge-on ground is reported by intersect.
        self.assertAlmostEqual(g.locked_start('XY', front).normal.z, 1)


class Combo:
    def __init__(self, text='Auto'):
        self.text = text

    def currentText(self):
        return self.text

    def setCurrentText(self, text):
        self.text = text

    def blockSignals(self, block):
        return False


@unittest.skipIf(Controller is None, 'FreeCADGui is not importable here')
class ControllerArrowTests(unittest.TestCase):
    def controller(self, tool='Rectangle', anchor=None):
        c = SimpleNamespace(tool=tool, anchor=anchor, plane_lock=None, plane_restore=None, start_plane=None,
                            surface_mode=False, arc_input=None, axis=None, auto_line=False, last_pos=(5, 5),
                            plane=None, support=None, messages=[], moves=[], drawing_surface=None,
                            controls=SimpleNamespace(plane=Combo(), snap=SimpleNamespace(isChecked=lambda: True)))
        c.message = c.messages.append
        c.motion = c.moves.append
        for name in ('free_start', 'drawing_start', 'arrow_key', 'lock_axis', 'plane_chosen'):
            setattr(c, name, getattr(Controller, name).__get__(c))
        return c

    def test_locked_start_turns_the_auto_plane_through_the_snapped_point(self):
        corner = V(10, 0, 10)
        top = g.Plane.from_normal(V(5, 5, 10), V(0, 0, 1))
        c = self.controller()
        box = object()

        def drawing_plane(pos):
            c.support = box
            return top
        c.drawing_plane = drawing_plane
        c.snapper = SimpleNamespace(snap_start=lambda pos, plane, enabled: (Snap(corner, 'Endpoint'), top))
        snap, plane = c.drawing_start((1, 2))
        self.assertIs(plane, top)
        self.assertIs(c.support, box)
        for name, normal in (('YZ', V(1, 0, 0)), ('XZ', V(0, 1, 0))):
            c.plane_lock = name
            snap, plane = c.drawing_start((1, 2))
            self.assertAlmostEqual(abs(plane.normal.dot(normal)), 1)
            self.assertLess((plane.origin - corner).Length, 1e-12)
            self.assertIsNone(c.support)  # A wall standing on the top face is no imprint.
            self.assertEqual(c.start_plane, (top, box))
        c.plane_lock = 'XY'
        snap, plane = c.drawing_start((1, 2))
        self.assertTrue(g.same_plane(plane, top))
        self.assertIs(c.support, box)  # The locked plane is the face: keep the imprint.

    def test_fixed_selector_plane_keeps_world_origin_and_in_plane_snaps(self):
        c = self.controller()
        c.controls.plane.text = 'XZ'
        c.drawing_plane = lambda pos: g.Plane.named('XZ')
        c.snapper = SimpleNamespace(snap=lambda pos, plane, enabled: Snap(V(3, 0, 4), 'Plane'))
        snap, plane = c.drawing_start((1, 2))
        self.assertLess(plane.origin.Length, 1e-12)
        self.assertEqual(c.start_plane, (plane, None))

    def test_arrows_turn_a_started_drawing_about_its_first_point(self):
        anchor = V(2, 3, 10)
        top = g.Plane.from_normal(anchor, V(0, 0, 1))
        box = object()
        c = self.controller(anchor=anchor)
        c.plane, c.support, c.start_plane = top, box, (top, box)
        c.arrow_key('Right')
        self.assertEqual((c.plane_lock, c.controls.plane.text, c.plane_restore), ('YZ', 'YZ', 'Auto'))
        self.assertAlmostEqual(abs(c.plane.normal.x), 1)
        self.assertLess((c.plane.origin - anchor).Length, 1e-12)
        self.assertIsNone(c.support)
        self.assertEqual(c.moves, [(5, 5)])  # The preview follows at once.
        self.assertIn('YZ plane locked', c.messages[-1])
        c.arrow_key('Left')
        self.assertEqual(c.controls.plane.text, 'XZ')
        self.assertAlmostEqual(abs(c.plane.normal.y), 1)
        c.arrow_key('Left')  # The active arrow again returns to Auto.
        self.assertEqual((c.plane_lock, c.controls.plane.text), (None, 'Auto'))
        self.assertIs(c.plane, top)
        self.assertIs(c.support, box)
        c.arrow_key('Up')
        self.assertTrue(g.same_plane(c.plane, top))
        self.assertIs(c.support, box)
        c.arrow_key('Down')
        self.assertEqual((c.plane_lock, c.controls.plane.text, c.plane_restore), (None, 'Auto', 'Auto'))
        c.plane_chosen(0)
        self.assertIsNone(c.plane_restore)

    def test_an_arc_keeps_the_plane_of_its_first_two_points(self):
        c = self.controller('Arc', V())
        c.start_plane = (g.Plane.named('XY'), None)
        c.plane = c.start_plane[0]
        c.arc_input = SimpleNamespace(second=V(5, 0, 0))
        c.arrow_key('Left')  # XZ still contains both points.
        self.assertEqual(c.plane_lock, 'XZ')
        c.arrow_key('Right')  # YZ does not.
        self.assertEqual(c.plane_lock, 'XZ')
        self.assertAlmostEqual(abs(c.plane.normal.y), 1)
        self.assertIn('fix its plane', c.messages[-1])

    def test_line_arrows_lock_axes_after_the_first_click(self):
        c = self.controller('Line')
        c.arrow_key('Up')  # Before the first click: the plane, as for other tools.
        self.assertEqual(c.plane_lock, 'XY')
        c.anchor, c.plane, c.auto_line = V(), g.Plane.named('XZ'), False
        c.arrow_key('Right')
        self.assertEqual(c.axis, V(1, 0, 0))
        self.assertEqual(c.plane_lock, 'XY')
        c.arrow_key('Right')
        self.assertIsNone(c.axis)
        c.arrow_key('Up')
        self.assertEqual(c.axis, V(0, 0, 1))
        c.arrow_key('Down')
        self.assertIsNone(c.axis)
        c.arrow_key('Left')  # Y is off the fixed XZ plane, exactly as the Y key.
        self.assertIsNone(c.axis)
        self.assertIn('drawing plane', c.messages[-1])

    def test_surface_mode_ignores_arrows_with_a_reason(self):
        c = self.controller()
        c.surface_mode = True
        c.arrow_key('Right')
        self.assertIsNone(c.plane_lock)
        self.assertEqual(c.controls.plane.text, 'Auto')
        self.assertIn('Draw: Surface', c.messages[-1])


if __name__ == '__main__':
    unittest.main()
