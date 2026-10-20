"""Measure reads holes, faces, edges and points without changing the model."""
import math
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from simplecad.inspection import measuring as m
from simplecad.modeling import analytic
from simplecad.mcp.api import ModelAPI

V = App.Vector


def plate():
    """A 40 x 20 x 10 plate with a 6 mm hole at (10, 10) and a 5 mm hole at (30, 10)."""
    return Part.makeBox(40, 20, 10).cut(Part.makeCylinder(3, 12, V(10, 10, -1))).cut(
        Part.makeCylinder(2.5, 12, V(30, 10, -1))).Solids[0]


def faceted_plate(sides=48):
    corners = [V(10 + 3 * math.cos(math.tau * i / sides), 10 + 3 * math.sin(math.tau * i / sides), -1)
               for i in range(sides)]
    return Part.makeBox(40, 20, 10).cut(Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 12))).Solids[0]


def name(shape, kind, test):
    items = {'Face': shape.Faces, 'Edge': shape.Edges, 'Vertex': shape.Vertexes}[kind]
    return next(kind + str(i + 1) for i, item in enumerate(items) if test(item))


def rows(measurement):
    return {row.name: row.value for row in measurement.rows}


def wall(shape, radius):
    return name(shape, 'Face', lambda f: isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - radius) < 1e-9)


class HoleTests(unittest.TestCase):
    def test_a_hole_wall_reports_diameter_center_axis_and_depth(self):
        shape = plate()
        target = m.resolve(shape, wall(shape, 3))
        self.assertEqual(target.kind, 'Circle')
        self.assertTrue(target.label.startswith('Hole Ø6.000'))
        values = rows(m.describe(target))
        self.assertAlmostEqual(values['Diameter'], 6)
        self.assertAlmostEqual(values['Depth'], 10)
        self.assertLess((values['Center'] - V(10, 10, 0)).Length, 1e-9)
        self.assertAlmostEqual(abs(values['Axis'].z), 1)

    def test_a_rim_edge_reports_its_circle(self):
        shape = plate()
        rim = name(shape, 'Edge', lambda e: isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 2.5) < 1e-9
                   and abs(e.Curve.Center.z - 10) < 1e-9)
        values = rows(m.describe(m.resolve(shape, rim)))
        self.assertAlmostEqual(values['Diameter'], 5)
        self.assertLess((values['Center'] - V(30, 10, 10)).Length, 1e-9)

    def test_a_boss_is_a_cylinder_not_a_hole(self):
        boss = Part.makeBox(20, 20, 5).fuse(Part.makeCylinder(3, 10, V(10, 10, 5))).removeSplitter()
        self.assertTrue(m.resolve(boss, wall(boss, 3)).label.startswith('Cylinder'))

    def test_one_facet_or_rim_side_of_a_faceted_hole_reports_the_hole(self):
        shape = faceted_plate()
        facet = name(shape, 'Face', lambda f: isinstance(f.Surface, Part.Plane) and abs(f.normalAt(0, 0).z) < 1e-9
                     and (f.CenterOfMass - V(10, 10, f.CenterOfMass.z)).Length < 4)
        side = name(shape, 'Edge', lambda e: abs(e.CenterOfMass.z - 10) < 1e-9
                    and (e.CenterOfMass - V(10, 10, 10)).Length < 4)
        for element in (facet, side):
            with self.subTest(element=element):
                target = m.resolve(shape, element)
                self.assertEqual(target.kind, 'Circle')
                self.assertIn('faceted', target.label)
                self.assertTrue(target.label.startswith('Hole'))
                self.assertAlmostEqual(2 * target.radius, 6, delta=.01)
                self.assertLess((V(target.point.x, target.point.y, 0) - V(10, 10, 0)).Length, 1e-3)

    def test_an_ordinary_flat_face_does_not_search_for_a_wall(self):
        shape = plate()
        top = name(shape, 'Face', lambda f: abs(f.CenterOfMass.z - 10) < 1e-9)
        with patch.object(analytic, '_expand_wall_faces', side_effect=AssertionError('Searched a wall')):
            target = m.resolve(shape, top)
        self.assertEqual(target.kind, 'Face')
        self.assertAlmostEqual(rows(m.describe(target))['Area'], 800 - math.pi * (9 + 6.25))


    def test_a_facet_of_a_large_curved_surface_is_not_a_hole(self):
        # Facets 26 mm wide belong to a 400 mm drum, far beyond hole size.
        corners = [V(200 * math.cos(math.tau * i / 48), 200 * math.sin(math.tau * i / 48), 0) for i in range(48)]
        drum = Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 30))
        facet = name(drum, 'Face', lambda f: abs(f.normalAt(0, 0).z) < 1e-9)
        with patch.object(analytic, '_expand_wall_faces', side_effect=AssertionError('Searched the drum')):
            self.assertEqual(m.resolve(drum, facet).kind, 'Face')


class PairTests(unittest.TestCase):
    def test_a_curved_face_reports_its_bend_at_the_clicked_point(self):
        sphere = Part.makeSphere(8)
        rows = {row.name: row for row in m.describe(m.resolve(sphere, 'Face1', V(0, 8, 0))).rows}
        self.assertEqual(rows['Curvature'].text(), 'Bulges outward (convex)')
        self.assertAlmostEqual(rows['Tightest radius'].value, 8, places=6)
        self.assertAlmostEqual(rows['Gentlest radius'].value, 8, places=6)
        saddle = Part.makeTorus(10, 3)
        inner = m.describe(m.resolve(saddle, 'Face1', V(7, 0, 0))).rows
        rows = {row.name: row.text() for row in inner}
        self.assertEqual(rows['Curvature'], 'Saddle: bends both ways')
        self.assertEqual(rows['Tightest radius'], '3.000 mm')
        self.assertEqual(rows['Gentlest radius'], '7.000 mm')
        cone = Part.makeCone(5, 2, 10)
        face = name(cone, 'Face', lambda f: isinstance(f.Surface, Part.Cone))
        rows = {row.name: row.text() for row in m.describe(m.resolve(cone, face, V(5, 0, 0))).rows}
        self.assertEqual(rows['Gentlest radius'], 'Flat (no bend)')

    def test_two_holes_give_center_spacing_and_the_wall_between(self):
        shape = plate()
        values = rows(m.between(m.resolve(shape, wall(shape, 3)), m.resolve(shape, wall(shape, 2.5))))
        self.assertAlmostEqual(values['Center spacing'], 20)
        self.assertAlmostEqual(values['Across the axes'], 20)
        self.assertAlmostEqual(values['Wall between'], 14.5)
        self.assertAlmostEqual(values['Minimum distance'], 14.5)
        self.assertLess((values['Delta'] - V(20, 0, 0)).Length, 1e-9)

    def test_parallel_and_perpendicular_faces(self):
        shape = plate()
        top = m.resolve(shape, name(shape, 'Face', lambda f: abs(f.CenterOfMass.z - 10) < 1e-9))
        bottom = m.resolve(shape, name(shape, 'Face', lambda f: abs(f.CenterOfMass.z) < 1e-9))
        side = m.resolve(shape, name(shape, 'Face', lambda f: abs(f.CenterOfMass.x) < 1e-9))
        parallel = m.between(top, bottom)
        self.assertAlmostEqual(rows(parallel)['Distance between faces'], 10)
        self.assertAlmostEqual(rows(parallel)['Angle'], 0)
        self.assertAlmostEqual(parallel.line[0].z + parallel.line[1].z, 10)  # Drawn from face to face.
        self.assertAlmostEqual(rows(m.between(top, side))['Angle'], 90)

    def test_points_edges_and_a_point_over_a_face(self):
        box = Part.makeBox(10, 20, 30)
        corner = m.resolve(box, name(box, 'Vertex', lambda v: v.Point.Length < 1e-9))
        far = m.resolve(box, name(box, 'Vertex', lambda v: (v.Point - V(10, 20, 30)).Length < 1e-9))
        self.assertLess((rows(m.describe(far))['Position'] - V(10, 20, 30)).Length, 1e-9)
        values = rows(m.between(corner, far))
        self.assertAlmostEqual(values['Distance'], math.sqrt(1400))
        self.assertLess((values['Delta'] - V(10, 20, 30)).Length, 1e-9)
        edge = m.resolve(box, name(box, 'Edge', lambda e: abs(e.Length - 30) < 1e-9))
        self.assertAlmostEqual(rows(m.describe(edge))['Length'], 30)
        opposite = m.resolve(box, name(box, 'Edge', lambda e: abs(e.Length - 30) < 1e-9
                                       and (e.CenterOfMass - V(10, 20, 15)).Length < 1e-9))
        lines = rows(m.between(edge, opposite))
        self.assertAlmostEqual(lines['Angle'], 0)
        self.assertGreater(lines['Distance between lines'], 0)
        top = m.resolve(box, name(box, 'Face', lambda f: abs(f.CenterOfMass.z - 30) < 1e-9))
        self.assertAlmostEqual(rows(m.between(corner, top))['Distance to the face plane'], 30)

    def test_a_point_to_a_hole_reports_its_distance_to_the_axis(self):
        shape = plate()
        corner = m.resolve(shape, name(shape, 'Vertex', lambda v: (v.Point - V(40, 20, 10)).Length < 1e-9))
        values = rows(m.between(corner, m.resolve(shape, wall(shape, 3))))
        self.assertAlmostEqual(values['Distance to the axis'], math.hypot(30, 10))


class MeasureCommandTests(unittest.TestCase):
    def test_the_ai_connection_measures_without_editing(self):
        doc = App.newDocument('Measure')
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        obj = doc.addObject('Part::Feature', 'Plate')
        obj.Shape = plate()
        before = obj.Shape
        undo = doc.UndoCount
        result = ModelAPI().execute('measure', doc, {'first': {'object': 'Plate', 'element': wall(obj.Shape, 3)},
                                                     'second': {'object': 'Plate', 'element': wall(obj.Shape, 2.5)}})
        values = {row['name']: row['value'] for row in result['measurements']}
        self.assertAlmostEqual(values['Center spacing'], 20)
        self.assertEqual(values['Delta'], [20.0, 0.0, 0.0])
        self.assertEqual(len(result['targets']), 2)
        self.assertTrue(obj.Shape.isSame(before))
        self.assertEqual(doc.UndoCount, undo)
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            ModelAPI().execute('measure', doc, {'first': {'object': 'Plate', 'element': 'Face999'}})


if __name__ == '__main__':
    unittest.main()


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from simplecad.gui.qt import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pick_pair_place_restart_and_clear(self):
        from types import SimpleNamespace as NS
        from pivy import coin
        from simplecad.gui.tools import measure as measure_ui
        root = coin.SoSeparator()
        view = NS(getSceneGraph=lambda: root, redraw=lambda: None, getViewDirection=lambda: V(0, 0, -1))
        messages = []
        controller = NS(view=view, doc=None, snapper=None, message=messages.append, cancel=lambda: None,
                        focus_view=lambda: None,
                        preview=NS(update=lambda *a, **k: None, show_endpoint=lambda *a, **k: None))
        shape = plate()
        owner = NS(Shape=shape)
        walls = [wall(shape, 3), wall(shape, 2.5)]
        hits = iter([(owner, None, V(), walls[0]), (owner, None, V(), walls[1]), (owner, None, V(), walls[0])])
        with patch.object(measure_ui, 'pick', side_effect=lambda *a, **k: next(hits)), \
             patch.object(measure_ui, 'ray', return_value=(V(20, 15, 100), V(0, 0, -1))), \
             patch.object(measure_ui.Gui, 'getMainWindow', return_value=None, create=True):
            session = measure_ui.MeasureSession(controller)
            self.addCleanup(measure_ui.clear_kept)
            session.click((0, 0))
            self.assertEqual(session.table.topLevelItem(0).text(0), 'Diameter')
            session.click((0, 0))
            values = {session.table.topLevelItem(i).text(0): session.table.topLevelItem(i).text(1)
                      for i in range(session.table.topLevelItemCount())}
            self.assertEqual(values['Center spacing'], '20.000 mm')
            self.assertTrue(session.place_button.isEnabled())
            nodes = root.getNumChildren()
            session.place()
            session.hover((0, 0))  # The dimension follows the pointer, 5 mm off the centers.
            session.click((0, 0))  # ...and stays there.
            self.assertEqual(len(measure_ui._kept), 1)
            kept = measure_ui._kept[0][1]
            coords, lines, _ = kept.groups['dimension']
            points = [V(*p.getValue()) for p in coords.point.getValues()]
            self.assertTrue(any((p - V(10, 15, 0)).Length < 1e-9 for p in points))
            self.assertTrue(any((p - V(30, 15, 0)).Length < 1e-9 for p in points))
            self.assertGreaterEqual(lines.numVertices.getNum(), 3)  # Dimension and extension lines.
            self.assertEqual(kept.text.string.getValues()[0], '20.000 mm')
            self.assertEqual(root.getNumChildren(), nodes + 1)  # The placed dimension and a fresh overlay.
            session.click((0, 0))
            self.assertEqual(len(session.targets), 1)  # A new measurement starts.
            session.copy()
            self.assertIn('Diameter: 6.000 mm', self.app.clipboard().text())
            session.close()
            self.assertEqual(root.getNumChildren(), nodes)  # Only the placed one stays.
            measure_ui.clear_kept()
            self.assertEqual(root.getNumChildren(), nodes - 1)
