"""Equal-area native regions, unchanged neighbors and reversible edits."""
import math
import tempfile
from pathlib import Path
import unittest

import FreeCAD as App
import Part
from simplecad.modeling import subdivision as s
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
V = App.Vector


def polygon(points):
    points = [V(*p) for p in points]
    return Part.Face(Part.makePolygon(points + points[:1]))


def regular(sides):
    return polygon([(20 * math.cos(i * 2 * math.pi / sides), 20 * math.sin(i * 2 * math.pi / sides), 0)
                    for i in range(sides)])


class SubdivisionGeometryTests(unittest.TestCase):
    def assert_parts(self, original, index, result, parts, count):
        self.assertTrue(result.isValid())
        self.assertEqual(len(parts), count)
        self.assertEqual(len(result.Faces), len(original.Faces) + count - 1)
        self.assertAlmostEqual(result.Area, original.Area, places=5)
        if original.Solids:
            self.assertEqual(len(result.Solids), len(original.Solids))
            self.assertTrue(result.isClosed())
            self.assertAlmostEqual(result.Volume, original.Volume, places=5)
        for face in parts:
            self.assertAlmostEqual(face.Area, original.Faces[index].Area / count, places=5)
            self.assertAlmostEqual(face.common(original.Faces[index]).Area, face.Area, places=5)
            self.assertGreater(g.face_normal(face).dot(g.face_normal(original.Faces[index])), .99999)

    def test_rectangle_nine_is_an_exact_three_by_three_grid(self):
        face = Part.makePlane(60, 30)
        result, parts = s.divide(face, 0, *s.dimensions(9))
        self.assert_parts(face, 0, result, parts, 9)
        for part in parts:
            self.assertEqual(len(part.Edges), 4)
            self.assertAlmostEqual(part.BoundBox.XLength, 20, places=5)
            self.assertAlmostEqual(part.BoundBox.YLength, 10, places=5)
        self.assertEqual(len(result.Edges), 24)  # Shared edges, no overlays.

    def test_triangles_pentagons_hexagons_and_irregular_convex_polygons(self):
        shapes = [regular(3), regular(5), regular(6),
                  polygon([(0, 0, 0), (60, 0, 0), (55, 25, 0), (30, 40, 0), (0, 15, 0)])]
        for shape in shapes:
            for rows, columns in ((3, 3), (2, 5), (1, 7)):
                result, parts = s.divide(shape, 0, rows, columns)
                self.assert_parts(shape, 0, result, parts, rows * columns)

    def test_every_rotated_solid_face_preserves_neighbors_and_volume(self):
        box = Part.makeBox(40, 30, 20)
        box.Placement = App.Placement(V(100, -50, 30), App.Rotation(V(1, 2, 3), 37))
        box.tessellate(.1)
        for index in range(6):
            result, parts = s.divide(box, index, 2, 3)
            self.assert_parts(box, index, result, parts, 6)
            for other, face in enumerate(box.Faces):
                if other != index:
                    self.assertTrue(any(coinc.same(face, candidate) for candidate in result.Faces))

    def test_changed_angle_rows_columns_and_single_part(self):
        face = Part.makePlane(60, 30)
        result, parts = s.divide(face, 0, 2, 4, 33)
        self.assert_parts(face, 0, result, parts, 8)
        for angle in (0, -90, 180):
            result, parts = s.divide(regular(5), 0, 2, 2, angle)
            self.assert_parts(regular(5), 0, result, parts, 4)
        result, parts = s.divide(face, 0, 1, 1)
        self.assert_parts(face, 0, result, parts, 1)

    def test_concave_faces_and_existing_holes_preserve_equal_area(self):
        concave = polygon([(0, 0, 0), (40, 0, 0), (40, 15, 0), (20, 15, 0), (20, 40, 0), (0, 40, 0)])
        result, parts = s.divide(concave, 0, 2, 2)
        self.assert_parts(concave, 0, result, parts, 4)
        face = Part.makePlane(60, 40)
        hole = g.circle(g.Plane.named(), V(30, 20, 0), 4)
        face = face.cut(hole).Faces[0]
        result, parts = s.divide(face, 0, 2, 2)
        self.assert_parts(face, 0, result, parts, 4)
        self.assertAlmostEqual(result.common(hole).Area, 0)

    def test_circular_face_retains_analytic_arcs(self):
        face = g.circle(g.Plane.from_normal(V(30, 40, 50), V(1, 2, 3)), V(30, 40, 50), 15)
        result, parts = s.divide(face, 0, 2, 2)
        self.assert_parts(face, 0, result, parts, 4)
        self.assertEqual(sum(isinstance(edge.Curve, Part.Circle) for edge in result.Edges), 4)

    def test_disconnected_cells_are_rejected_instead_of_unequal_fragments(self):
        # A thin top bridge joins two legs; horizontal bands can be disconnected.
        face = polygon([(0, 0, 0), (10, 0, 0), (10, 30, 0), (30, 30, 0),
                        (30, 0, 0), (40, 0, 0), (40, 40, 0), (0, 40, 0)])
        with self.assertRaisesRegex(ValueError, "disconnected"):
            s.divide(face, 0, 3, 1, 90)
        result, parts = s.divide(face, 0, 1, 3, 90)
        self.assert_parts(face, 0, result, parts, 3)

    def test_open_shell_reversed_face_and_loose_geometry(self):
        box = Part.makeBox(40, 30, 20)
        shell = Part.makeShell(box.Faces[1:])
        result, parts = s.divide(shell, 0, 3, 3)
        self.assert_parts(shell, 0, result, parts, 9)
        face = Part.makePlane(40, 30); face.reverse()
        result, parts = s.divide(face, 0, 3, 3)
        self.assert_parts(face, 0, result, parts, 9)
        loose = Part.makeLine(V(80, 0, 0), V(90, 0, 0))
        point = Part.Vertex(V(100, 0, 0))
        mixed = Part.makeCompound([box, loose, point])
        result, parts = s.divide(mixed, 5, 2, 2)
        self.assertTrue(result.isValid())
        self.assertTrue(any(coinc.same(loose, edge) for edge in coinc.loose_edges(result)))
        self.assertTrue(any((v.Point - point.Point).Length < 1e-7 for v in result.Vertexes))

    def test_each_new_region_can_push_pull_and_shared_edge_can_merge(self):
        prism = regular(3).extrude(V(0, 0, 12))
        index = max(range(len(prism.Faces)), key=lambda i: prism.Faces[i].CenterOfMass.z)
        divided, regions = s.divide(prism, index, 3, 3)
        for face in regions:
            for distance in (-2, 2):
                pulled = g.push_pull(divided, face, distance)
                self.assertTrue(pulled.isValid())
                self.assertAlmostEqual(pulled.Volume, prism.Volume + face.Area * distance, places=5)
        edge = next(edge for edge in divided.Edges
                    if sum(any(edge.isSame(e) for e in f.Edges) for f in regions) == 2)
        name = next("Edge%d" % (i + 1) for i, e in enumerate(divided.Edges) if e.isSame(edge))
        merged = g.erase_elements(divided, [name])
        self.assertEqual(len(merged.Faces), len(divided.Faces) - 1)
        self.assertAlmostEqual(merged.Volume, prism.Volume)
        name = next("Face%d" % (i + 1) for i, f in enumerate(divided.Faces) if f.isSame(regions[0]))
        opened = g.erase_elements(divided, [name])
        self.assertTrue(opened.isValid()); self.assertFalse(opened.Solids)
        self.assertAlmostEqual(opened.Area, divided.Area - regions[0].Area, places=5)

    def test_prior_divisions_and_subdividing_again_preserve_other_regions(self):
        box = Part.makeBox(40, 30, 20)
        divided = g.divide_face_with_line(box, V(20, 0, 20), V(20, 30, 20))
        index = next(i for i, f in enumerate(divided.Faces) if abs(f.CenterOfMass.z - 20) < 1e-7 and f.CenterOfMass.x < 20)
        result, parts = s.divide(divided, index, 2, 2)
        self.assert_parts(divided, index, result, parts, 4)
        index = next(i for i, f in enumerate(result.Faces) if f.isSame(parts[0]))
        again, cells = s.divide(result, index, 2, 2)
        self.assert_parts(result, index, again, cells, 4)

    def test_counts_limits_and_invalid_sources(self):
        self.assertEqual(s.dimensions(9), (3, 3)); self.assertEqual(s.dimensions(12), (3, 4))
        self.assertEqual(s.dimensions(7), (1, 7))
        for n in (0, -1, 101, 1.2, True):
            with self.assertRaises(ValueError): s.dimensions(n)
        face = Part.makePlane(40, 30)
        for rows, cols in ((0, 3), (-1, 2), (11, 10), (1.2, 3)):
            with self.assertRaises(ValueError): s.divide(face, 0, rows, cols)
        with self.assertRaises(ValueError): s.divide(face, 9, 2, 2)
        with self.assertRaises(ValueError): s.divide(face, 0, 2, 2, float("nan"))
        with self.assertRaisesRegex(ValueError, "Curved"): s.divide(Part.makeSphere(10), 0, 2, 2)
        multiple = Part.makeCompound([Part.makeBox(10, 20, 30), Part.makeBox(10, 20, 30, V(50, 0, 0))])
        with self.assertRaisesRegex(ValueError, "compound"): s.divide(multiple, 0, 2, 2)


class SubdivisionDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SubdivisionTest"); self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 30, 20), "Block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_preview_apply_undo_redo_and_noop(self):
        target = op.prepare_subdivision([(self.obj, ("Face6",))])
        original, count = self.obj.Shape, self.doc.UndoCount
        planned, regions = op.preview_subdivision(target, 3, 3)
        self.assertTrue(self.obj.Shape.isSame(original)); self.assertEqual(self.doc.UndoCount, count)
        self.assertTrue(op.commit_subdivision(target, planned, 3, 3))
        self.assertEqual(len(self.doc.Objects), 1); self.assertEqual(self.obj.Label, "Block")
        self.assertEqual(len(self.obj.Shape.Faces), 14); self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo(); self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.doc.redo(); self.assertEqual(len(self.obj.Shape.Faces), 14)
        target = op.prepare_subdivision([(self.obj, ("Face1",))]); count = self.doc.UndoCount
        planned, regions = op.preview_subdivision(target, 1, 1)
        self.assertFalse(op.commit_subdivision(target, planned, 1, 1))
        self.assertEqual(self.doc.UndoCount, count)

    def test_moved_rotated_save_reopen_and_copy_remain_native(self):
        self.obj.Placement = App.Placement(V(100, -30, 40), App.Rotation(V(1, 2, 3), 25))
        target = op.prepare_subdivision([(self.obj, ("Face6",))])
        planned, regions = op.preview_subdivision(target, 3, 3)
        op.commit_subdivision(target, planned, 3, 3)
        expected = sorted(tuple(f.CenterOfMass) for f in self.obj.Shape.Faces)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Divided.FCStd"; self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name); self.doc = App.openDocument(str(path)); self.doc.UndoMode = 1
            self.obj = self.doc.Objects[0]
            self.assertEqual(self.obj.TypeId, "Part::Feature"); self.assertNotIn("Proxy", self.obj.PropertiesList)
            for a, b in zip(expected, sorted(tuple(f.CenterOfMass) for f in self.obj.Shape.Faces)):
                self.assertLess((V(*a) - V(*b)).Length, 1e-6)
            copy = op.transform([self.obj], V(100, 0, 0), copy=True)[0]
            self.assertEqual(len(copy.Shape.Faces), 14)
            self.assertTrue(copy.Shape.isValid())

    def test_invalid_and_stale_operations_do_not_write(self):
        target = op.prepare_subdivision([(self.obj, ("Face6",))]); count = self.doc.UndoCount
        with self.assertRaises(ValueError): op.preview_subdivision(target, 20, 20)
        with self.assertRaises(ValueError): op.commit_subdivision(target, [(self.obj, Part.Shape())], 3, 3)
        self.assertEqual(count, self.doc.UndoCount)
        planned, _ = op.preview_subdivision(target, 3, 3)
        op.transform([self.obj], V(5, 0, 0))
        with self.assertRaisesRegex(ValueError, "changed"): op.commit_subdivision(target, planned, 3, 3)
        target = op.prepare_subdivision([(self.obj, ("Face6",))]); self.doc.removeObject(self.obj.Name)
        with self.assertRaises(ValueError): op.check_subdivision(target)

    def test_selection_requires_one_planar_face_and_rejects_links(self):
        for selection in ([], [(self.obj, ())], [(self.obj, ("Edge1",))], [(self.obj, ("Face1", "Face2"))]):
            with self.assertRaises(ValueError): op.prepare_subdivision(selection)
        target = op.prepare_subdivision([(self.obj, ("Face6",)), (self.obj, ("Face6",))])
        self.assertEqual(target[2], 5)
        face = op.new_shape(self.doc, regular(5), "Pentagon")
        self.assertEqual(op.prepare_subdivision([(face, ())])[2], 0)
        face.addProperty("App::PropertyLink", "SC_Support"); face.SC_Support = self.obj
        with self.assertRaisesRegex(ValueError, "links"): op.prepare_subdivision([(face, ())])
        param = self.doc.addObject("Part::Box", "Parametric"); self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "plain Part"): op.prepare_subdivision([(param, ("Face1",))])


if __name__ == "__main__":
    unittest.main()
