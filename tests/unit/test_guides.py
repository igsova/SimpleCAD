"""Measure Tape guides: stored without shapes, snapped to, deleted and undone."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from simplecad.core import geometry as g
from simplecad.document import guides
from simplecad.gui import command_state as state
from simplecad.gui.command_state import Context, Target, reason
from simplecad.gui.snapping import Snapper, closest_on_lines, straight
from test_line_axes import Camera

V = App.Vector


class LineMathTests(unittest.TestCase):
    def test_crossing_lines_meet_at_one_point(self):
        point = closest_on_lines(V(0, 10, 0), V(1, 0, 0), V(25, -4, 0), g.unit(V(0, 1, 0)))
        self.assertLess((point - V(25, 10, 0)).Length, 1e-9)

    def test_parallel_and_skew_lines_do_not_meet(self):
        self.assertIsNone(closest_on_lines(V(0, 0, 0), V(1, 0, 0), V(0, 5, 0), V(-1, 0, 0)))
        self.assertIsNone(closest_on_lines(V(0, 0, 0), V(1, 0, 0), V(0, 0, 3), V(0, 1, 0)))

    def test_only_straight_edges_give_a_direction(self):
        direction = straight(Part.makeLine(V(1, 1, 0), V(1, 9, 0)))
        self.assertLess((direction - V(0, 1, 0)).Length, 1e-12)
        self.assertIsNone(straight(Part.makeCircle(5)))


class GuideSnappingTests(unittest.TestCase):
    def setUp(self):
        self.camera = Camera(top=True)
        self.snapper = Snapper(SimpleNamespace(Objects=[]), self.camera)
        self.edge = Part.makeLine(V(40, -20, 0), V(40, 20, 0))
        self.snapper.index_segments([self.edge])
        self.snapper.guide_lines = [(V(0, 10, 0), V(1, 0, 0)), (V(25, 0, 0), V(0, 1, 0))]
        self.plane = g.Plane.named("XY")
        for target, kwargs in (("simplecad.gui.snapping.ray", {'side_effect': self.camera.ray}),
                               ("simplecad.gui.snapping.pick", {'return_value': None})):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def screen(self, point, dx=0, dy=0):
        x, y = self.camera.getPointOnScreen(point)
        return (x + dx, y + dy)

    def test_guides_cross_edges_and_each_other(self):
        found = self.snapper.crossings()
        for expected in (V(40, 10, 0), V(25, 10, 0)):
            self.assertTrue(any((point - expected).Length < 1e-9 for point in found), (expected, found))
        self.assertEqual(len(found), 2, found)

    def test_a_line_lands_exactly_on_a_guide_and_follows_an_axis_onto_it(self):
        snap, _ = self.snapper.snap_line(self.screen(V(10, 10, 0), 0, 5), self.plane, V(-20, -30, 0), [])
        self.assertEqual(snap.label, "On guide")
        self.assertAlmostEqual(snap.point.y, 10, places=9)
        self.assertLess((snap.direction - V(1, 0, 0)).Length, 1e-12)
        snap, _ = self.snapper.snap_line(self.screen(V(5, 10, 0), 1, 4), self.plane, V(5, -20, 0), [])
        self.assertEqual(snap.label, "Y axis on guide")
        self.assertLess((snap.point - V(5, 10, 0)).Length, 1e-9)

    def test_the_tape_starts_on_a_guide_with_its_direction(self):
        snap, plane = self.snapper.snap_start(self.screen(V(25, -8, 0), 4, 0), self.plane)
        self.assertEqual(snap.label, "On guide")
        self.assertAlmostEqual(snap.point.x, 25, places=9)
        self.assertLess((snap.direction - V(0, 1, 0)).Length, 1e-12)
        snap, _ = self.snapper.snap_start(self.screen(V(40, -8, 0), 4, 0), self.plane)
        self.assertEqual(snap.label, "On edge")
        self.assertLess((snap.direction - V(0, 1, 0)).Length, 1e-12)


class GuideDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADGuides")
        self.doc.UndoMode = 1
        self.addCleanup(App.closeDocument, self.doc.Name)

    def guides(self):
        return [obj for obj in self.doc.Objects if guides.is_guide(obj)]

    def test_guides_have_no_shape_and_share_one_group(self):
        line = guides.add(self.doc, V(1, 2, 3), V(0, 0, 4))
        point = guides.add(self.doc, V(5, 5, 5))
        group = next(obj for obj in self.doc.Objects if guides.is_group(obj))
        self.assertEqual(sorted(obj.Name for obj in group.Group), sorted([line.Name, point.Name]))
        self.assertFalse(any(hasattr(obj, "Shape") for obj in (line, point, group)))
        self.assertEqual((line.Label, point.Label), ("Guide", "Guide point"))
        shown = list(guides.visible(self.doc))
        self.assertEqual(len(shown), 2)
        self.assertLess((shown[0][1] - V(0, 0, 1)).Length, 1e-12)
        self.assertIsNone(shown[1][1])
        with self.assertRaises(ValueError):
            guides.add(self.doc, V(), V())

    def test_each_guide_and_each_delete_is_one_undo_step(self):
        guides.add(self.doc, V(), V(1, 0, 0))
        guides.add(self.doc, V(0, 5, 0), V(1, 0, 0))
        self.doc.undo()
        self.assertEqual(len(self.guides()), 1)
        guides.add(self.doc, V(0, 5, 0), V(1, 0, 0))
        self.assertTrue(guides.remove(self.guides()[:1]))
        self.assertEqual(len(self.guides()), 1)
        group = next(obj for obj in self.doc.Objects if guides.is_group(obj))
        self.assertTrue(guides.remove([group]))
        self.assertEqual(self.doc.Objects, [])
        self.doc.undo()
        self.assertEqual(len(self.guides()), 1)
        self.assertFalse(guides.remove([]))


class GuideAvailabilityTests(unittest.TestCase):
    def test_measure_tape_needs_nothing(self):
        self.assertFalse(reason('Tape', Context()))

    def test_guides_can_be_deleted_alone_or_with_cad(self):
        guide = Target('guide')
        self.assertFalse(reason('Delete', Context(document=True, selected=(guide,))))
        self.assertFalse(reason('Delete', Context(document=True, selected=(guide, Target('cad', ('Edge1',))))))
        self.assertTrue(reason('Delete', Context(document=True, selected=(guide, Target('mesh')))))
        self.assertTrue(reason('Move', Context(document=True, selected=(guide,))))
        groups = dict(state.context_groups(Context(document=True, selected=(guide,))))
        self.assertEqual((groups['Modify'], 'Tape' in groups['Inspect']), (('Delete',), True))

    def test_guides_are_their_own_kind(self):
        def obj(*properties):
            return SimpleNamespace(PropertiesList=list(properties), isDerivedFrom=lambda name: False)
        self.assertEqual(state.kind(obj('Point', 'SC_Guide')), 'guide')
        self.assertEqual(state.kind(obj('Group', 'SC_Guides')), 'guide')
        self.assertEqual(state.kind(obj('Shape')), 'cad')


if __name__ == '__main__':
    unittest.main()
