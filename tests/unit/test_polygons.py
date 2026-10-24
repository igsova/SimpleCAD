"""Regular native polygons, oriented drawing, face regions and existing edits."""
import math
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
from simplecad.modeling import subdivision
V = App.Vector


def profile(face, sides=6, radius=3):
    plane = g.Plane.from_face(face)
    return g.polygon(plane, plane.origin, plane.origin + plane.u * radius, sides)


class PolygonGeometryTests(unittest.TestCase):
    def test_equal_sides_angles_area_and_orientation_on_each_plane(self):
        planes = [g.Plane.named(name, V(20, -30, 40)) for name in ("XY", "XZ", "YZ")]
        planes.append(g.Plane.from_normal(V(30, 40, 50), V(-1, 2, -3)))
        for plane in planes:
            for sides in (3, 4, 5, 6, 12, 100):
                center = plane.origin + plane.u * 7
                vertex = center + plane.u * 3 + plane.v * 4
                face = g.polygon(plane, center + plane.normal * 2, vertex + plane.normal * 5, sides)
                self.assertTrue(face.isValid()); self.assertEqual(len(face.Edges), sides)
                self.assertAlmostEqual(face.Area, sides * 25 / 2 * math.sin(math.tau / sides), places=6)
                self.assertLess((face.CenterOfMass - center).Length, 1e-7)
                self.assertGreater(g.face_normal(face).dot(plane.normal), .99999)
                self.assertTrue(any((v.Point - vertex).Length < 1e-7 for v in face.Vertexes))
                for edge in face.Edges:
                    self.assertIsInstance(edge.Curve, Part.Line)
                    self.assertAlmostEqual(edge.Length, 10 * math.sin(math.pi / sides), places=6)
                for v in face.Vertexes:
                    self.assertAlmostEqual((v.Point - center).Length, 5, places=6)
                    self.assertAlmostEqual((v.Point - center).dot(plane.normal), 0, places=6)

    def test_invalid_sides_and_zero_nonfinite_radius(self):
        plane = g.Plane.named()
        for sides in (0, 2, 101, True, 3.5, "6"):
            with self.assertRaises(ValueError): g.polygon(plane, V(), V(5, 0, 0), sides)
        for vertex in (V(), V(0, 0, 20), V(1e-10, 0, 0), V(math.nan, 0, 0), V(math.inf, 0, 0)):
            with self.assertRaises(ValueError): g.polygon(plane, V(), vertex, 6)

    def test_standalone_prisms_and_subdivision_patterns(self):
        plane = g.Plane.from_normal(V(30, 20, 40), V(1, 2, 3))
        for n, pattern in ((3, "triangles"), (4, "spaced"), (5, "fan"), (6, "fan")):
            face = g.polygon(plane, plane.origin, plane.origin + plane.u * 5, n)
            self.assertEqual(subdivision.Profile(face).default_pattern(), pattern)
            for distance in (-7, 7):
                solid = g.push_pull(face, face, distance)
                self.assertTrue(solid.isValid()); self.assertEqual(len(solid.Faces), n + 2)
                self.assertAlmostEqual(solid.Volume, face.Area * 7, places=5)

    def test_all_rotated_solid_faces_form_regions_for_push_pull_and_delete(self):
        box = Part.makeBox(40, 30, 20)
        box.Placement = App.Placement(V(20, 30, 40), App.Rotation(V(1, 2, 3), 37))
        for face in box.Faces:
            poly = profile(face, 5)
            result = g.divide_face_with_profile(box, poly)
            self.assertEqual(len(result.Faces), 7); self.assertAlmostEqual(result.Volume, box.Volume)
            region = next(f for f in result.Faces if coinc.same(f, poly))
            for distance in (-2, 2):
                solid = g.push_pull(result, region, distance)
                self.assertAlmostEqual(solid.Volume, box.Volume + poly.Area * distance, places=5)
            name = next('Face%d' % (i + 1) for i, f in enumerate(result.Faces) if f.isSame(region))
            opened = g.erase_elements(result, [name])
            self.assertFalse(opened.Solids); self.assertAlmostEqual(opened.Area, box.Area - poly.Area)

    def test_polygon_and_circle_keep_intersecting_neighbor_surfaces(self):
        selected = Part.makePlane(60, 30)
        wall = Part.Face(Part.makePolygon([V(30, -10, -10), V(30, 40, -10), V(30, 40, 10), V(30, -10, 10), V(30, -10, -10)]))
        loose = Part.makeLine(V(100, 0, 0), V(110, 0, 0)); point = Part.Vertex(V(120, 0, 0))
        source = Part.makeCompound([selected, wall, loose, point])
        for poly in (profile(selected), g.circle(g.Plane.from_face(selected), selected.CenterOfMass, 3)):
            result = g.divide_face_with_profile(source, poly)
            self.assertTrue(result.isValid()); self.assertEqual(len(result.Faces), 3)
            self.assertTrue(any(coinc.same(f, wall) for f in result.Faces))
            self.assertTrue(any(coinc.same(f, poly) for f in result.Faces))
            self.assertAlmostEqual(result.Area, source.Area)
            self.assertTrue(any(coinc.same(e, loose) for e in coinc.loose_edges(result)))
            self.assertTrue(any((v.Point - point.Point).Length < 1e-7 for v in result.Vertexes))


class PolygonDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PolygonTest"); self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_face_region_retrace_delete_and_atomic_undo(self):
        host = op.new_shape(self.doc, Part.makePlane(40, 30), "Sheet")
        poly = profile(host.Shape)
        count = self.doc.UndoCount
        self.assertEqual(op.draw_polygon(self.doc, poly, host), (host, True))
        self.assertEqual(len(self.doc.Objects), 1); self.assertEqual(len(host.Shape.Faces), 2)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo(); self.assertEqual(len(host.Shape.Faces), 1)
        self.doc.redo(); self.assertEqual(len(host.Shape.Faces), 2)
        count = self.doc.UndoCount
        self.assertEqual(op.draw_polygon(self.doc, poly, host), (host, True))
        self.assertEqual(self.doc.UndoCount, count)
        name = next('Face%d' % (i + 1) for i, f in enumerate(host.Shape.Faces) if coinc.same(f, poly))
        op.delete_selection([(host, [name])])
        self.assertAlmostEqual(host.Shape.Area, 1200 - poly.Area)
        self.assertEqual(len(host.Shape.Wires), 2)
        self.doc.undo(); self.assertEqual(len(host.Shape.Faces), 2)

    def test_partial_polygon_divides_the_sheet_and_existing_hole_is_rejected(self):
        host = op.new_shape(self.doc, Part.makePlane(40, 30), "Sheet")
        partial = g.polygon(g.Plane.named(), V(39, 15, 0), V(44, 15, 0), 5)
        count = self.doc.UndoCount
        self.assertEqual(op.draw_polygon(self.doc, partial, host), (host, True))
        self.assertEqual(self.doc.UndoCount, count + 1); self.assertEqual(len(self.doc.Objects), 1)
        # The part on the sheet divides it; the part off it joins the sheet.
        inside = partial.common(Part.makePlane(40, 30)).Area
        areas = sorted(f.Area for f in host.Shape.Faces)
        for area, expected in zip(areas, sorted([1200 - inside, inside, partial.Area - inside]), strict=True):
            self.assertAlmostEqual(area, expected, places=5)
        self.doc.undo(); self.assertEqual(len(host.Shape.Faces), 1)
        hole = profile(host.Shape)
        host.Shape = host.Shape.cut(hole)
        with self.assertRaises(ValueError): op.draw_polygon(self.doc, hole, host)
        self.assertEqual(len(self.doc.Objects), 1)

    def test_free_polygon_save_reopen_copy_and_pull_are_native(self):
        plane = g.Plane.from_normal(V(20, 30, 40), V(-1, 2, 3))
        poly = g.polygon(plane, plane.origin, plane.origin + plane.u * 3 + plane.v * 4, 7)
        obj, changed = op.draw_polygon(self.doc, poly)
        self.assertFalse(changed); self.assertEqual(obj.Label, "Polygon")
        self.assertEqual(op.draw_polygon(self.doc, poly), (obj, False))
        self.assertEqual(self.doc.UndoCount, 1)
        self.doc.undo(); self.assertFalse(self.doc.Objects)
        self.doc.redo(); obj = self.doc.Objects[0]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'polygon.FCStd'); self.doc.saveAs(path)
            App.closeDocument(self.doc.Name); self.doc = App.openDocument(path); self.doc.UndoMode = 1
            obj = self.doc.Objects[0]
            self.assertEqual(obj.TypeId, 'Part::Feature'); self.assertNotIn('Proxy', obj.PropertiesList)
            self.assertNotIn('SC_Support', obj.PropertiesList); self.assertTrue(coinc.same(obj.Shape, poly))
            copy = op.transform([obj], V(50, 0, 0), copy=True)[0]
            op.extrude(copy, copy.Shape, 8)
            self.assertAlmostEqual(copy.Shape.Volume, poly.Area * 8, places=5)
            self.assertEqual(obj.Shape.ShapeType, 'Face')


if __name__ == '__main__':
    unittest.main()
