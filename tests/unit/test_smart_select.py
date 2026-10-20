"""Grow a picked face or edge into its hole, loop, flat region or smooth surface."""
import math
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from simplecad.inspection import smart_select as ss
from simplecad.mcp.api import ModelAPI
from test_dense_deletion import dense_box
from test_measuring import plate, faceted_plate, name

V = App.Vector


def faceted_boss(sides=24):
    corners = [V(3 * math.cos(math.tau * i / sides), 3 * math.sin(math.tau * i / sides), 5) for i in range(sides)]
    return Part.makeBox(20, 20, 5, V(-10, -10, 0)).fuse(
        Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 6))).removeSplitter()


def elements(shape, names):
    return [shape.getElement(n) for n in names]


class HoleTests(unittest.TestCase):
    def test_an_analytic_hole_from_its_wall_or_rim(self):
        shape = plate()
        wall = name(shape, 'Face', lambda f: isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 3) < 1e-9)
        rim = name(shape, 'Edge', lambda e: isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 3) < 1e-9)
        self.assertEqual(ss.expand(shape, wall), ([wall], 'hole'))
        self.assertEqual(ss.expand(shape, rim), ([wall], 'hole'))

    def test_a_faceted_hole_from_one_facet_or_rim_side(self):
        shape = faceted_plate()
        facet = name(shape, 'Face', lambda f: isinstance(f.Surface, Part.Plane) and abs(f.normalAt(0, 0).z) < 1e-9
                     and (f.CenterOfMass - V(10, 10, f.CenterOfMass.z)).Length < 4)
        side = name(shape, 'Edge', lambda e: abs(e.CenterOfMass.z - 10) < 1e-9 and (e.CenterOfMass - V(10, 10, 10)).Length < 4)
        for element in (facet, side):
            with self.subTest(element=element):
                names, kind = ss.expand(shape, element)
                self.assertEqual(kind, 'hole')
                self.assertEqual(len(names), 48)
                self.assertTrue(all(abs(f.normalAt(0, 0).z) < 1e-9 for f in elements(shape, names)))

    def test_hole_mode_refuses_an_ordinary_face(self):
        shape = plate()
        top = name(shape, 'Face', lambda f: abs(f.CenterOfMass.z - 10) < 1e-9)
        with self.assertRaisesRegex(ValueError, 'not part of a hole'):
            ss.expand(shape, top, 'hole')


class LoopTests(unittest.TestCase):
    def test_a_faceted_rim_loop(self):
        shape = faceted_plate()
        side = name(shape, 'Edge', lambda e: abs(e.CenterOfMass.z - 10) < 1e-9 and (e.CenterOfMass - V(10, 10, 10)).Length < 4)
        names, kind = ss.expand(shape, side, 'loop')
        self.assertEqual(kind, 'loop')
        self.assertEqual(len(names), 48)
        self.assertTrue(all(abs(e.CenterOfMass.z - 10) < 1e-9 for e in elements(shape, names)))

    def test_a_box_edge_takes_the_loop_of_the_face_toward_the_viewer(self):
        box = Part.makeBox(10, 20, 30)
        edge = name(box, 'Edge', lambda e: abs(e.Length - 10) < 1e-9 and abs(e.CenterOfMass.z - 30) < 1e-9
                    and abs(e.CenterOfMass.y) < 1e-9)
        names, _ = ss.expand(box, edge, 'loop', view_direction=V(0, 0, -1))
        self.assertEqual(len(names), 4)
        self.assertTrue(all(abs(e.CenterOfMass.z - 30) < 1e-9 for e in elements(box, names)))
        names, _ = ss.expand(box, edge, 'loop', view_direction=V(0, 1, 0))
        self.assertTrue(all(abs(e.CenterOfMass.y) < 1e-9 for e in elements(box, names)))


class RegionTests(unittest.TestCase):
    def test_a_flat_region_of_triangles(self):
        shape = dense_box(8)
        top = name(shape, 'Face', lambda f: abs(f.CenterOfMass.z - 8) < 1e-9)
        names, kind = ss.expand(shape, top)
        self.assertEqual(kind, 'flat')
        self.assertEqual(len(names), 128)
        self.assertAlmostEqual(sum(f.Area for f in elements(shape, names)), 64)

    def test_a_flat_region_spans_leaning_triangles_but_stops_at_a_fold(self):
        a, b, c, d, e = V(0, 0, 0), V(10, 0, 0), V(10, 10, .0002), V(0, 10, 0), V(20, 5, 10 * math.tan(math.radians(2)))
        shell = Part.makeShell([Part.Face(Part.makePolygon(points + [points[0]]))
                                for points in ([a, b, d], [b, c, d], [b, e, c])])
        names, _ = ss.expand(shell, 'Face1', 'flat')
        self.assertEqual(sorted(names), ['Face1', 'Face2'])

    def test_a_smooth_faceted_surface_stops_at_sharp_edges(self):
        boss = faceted_boss()
        facet = name(boss, 'Face', lambda f: abs(f.normalAt(0, 0).z) < 1e-9 and (f.CenterOfMass - V(0, 0, f.CenterOfMass.z)).Length < 4)
        names, kind = ss.expand(boss, facet, 'smooth')
        self.assertEqual((kind, len(names)), ('smooth', 24))
        self.assertEqual(ss.expand(boss, facet)[1], 'hole')  # Smart mode knows the cylinder.

    def test_the_adjacency_is_listed_once_per_shape(self):
        shape = dense_box(6)
        ss._adjacencies.clear()
        with patch.object(ss.Adjacency, '__init__', wraps=ss.Adjacency.__init__, autospec=True) as built:
            for element in ('Face1', 'Face20', 'Edge5'):
                ss.expand(shape, element)
        self.assertEqual(built.call_count, 1)


class FilterTests(unittest.TestCase):
    def test_the_selection_filter_keeps_only_its_kind(self):
        from simplecad.gui.tools.selection import DragSelection
        selection = NS(filter='All')
        obj = NS(Name='Part', Document=NS(Name='Doc'))
        hits = [(obj, 'Face1'), (obj, 'Edge2'), (obj, 'Vertex3')]
        for mode, expected in (('All', hits), ('Faces', hits[:1]), ('Edges', hits[1:2]),
                               ('Vertices', hits[2:]), ('Objects', [(obj, '')])):
            selection.filter = mode
            self.assertEqual(DragSelection.filtered(selection, hits), expected)

    def test_hidden_faces_are_left_out(self):
        from simplecad.gui.tools import selection as selection_ui
        box = Part.makeBox(1, 1, 1)
        obj = NS(Name='Box', Shape=box, Document=NS(Name='Hidden'))
        self.addCleanup(selection_ui.visibility.forget_document, 'Hidden')
        with patch.object(selection_ui.visibility, 'hidden_faces', return_value={2}):
            self.assertEqual(selection_ui.visible_names(obj, ['Face1', 'Face2', 'Face3']), ['Face1', 'Face3'])


class ExpandCommandTests(unittest.TestCase):
    def test_the_ai_connection_expands_without_selecting(self):
        doc = App.newDocument('Expand')
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        obj = doc.addObject('Part::Feature', 'Plate')
        obj.Shape = faceted_plate()
        facet = name(obj.Shape, 'Face', lambda f: isinstance(f.Surface, Part.Plane) and abs(f.normalAt(0, 0).z) < 1e-9
                     and (f.CenterOfMass - V(10, 10, f.CenterOfMass.z)).Length < 4)
        result = ModelAPI().execute('expand_selection', doc, {'object': 'Plate', 'element': facet, 'select': False})
        self.assertEqual(result['kind'], 'hole')
        self.assertEqual(len(result['elements']), 48)


if __name__ == '__main__':
    unittest.main()
