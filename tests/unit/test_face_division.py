"""Native OpenCascade regression cases for drawing a diagonal on a block."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.snapping import Snap, Snapper


def front_faces(shape):
    return [face for face in shape.Faces
            if abs(face.CenterOfMass.y) < 1e-6 and abs(g.face_normal(face).y) > .999]


class DivisionGeometryTests(unittest.TestCase):
    def setUp(self):
        self.box = Part.makeBox(40, 30, 10)
        self.first, self.second = g.V(0, 0, 10), g.V(40, 0, 0)

    def divided(self):
        return g.divide_face_with_line(self.box, self.first, self.second)

    def test_diagonal_creates_two_native_triangles_without_changing_solid(self):
        result = self.divided()
        self.assertTrue(result.isValid())
        self.assertEqual(result.ShapeType, "Solid")
        self.assertEqual(len(result.Faces), 7)
        self.assertAlmostEqual(result.Volume, 12000)
        self.assertAlmostEqual(result.Area, self.box.Area)
        triangles = front_faces(result)
        self.assertEqual(len(triangles), 2)
        for face in triangles:
            self.assertEqual(len(face.Edges), 3)
            self.assertAlmostEqual(face.Area, 200)

    def test_push_and_pull_each_triangle_only(self):
        divided = self.divided()
        for triangle in front_faces(divided):
            for distance in (-5, 5):
                with self.subTest(center=triangle.CenterOfMass, distance=distance):
                    result = g.push_pull(divided, triangle, distance)
                    self.assertTrue(result.isValid())
                    self.assertEqual(len(result.Solids), 1)
                    self.assertAlmostEqual(result.Volume, 12000 + 200 * distance)
                    remaining = front_faces(result)
                    self.assertEqual(len(remaining), 1)
                    self.assertAlmostEqual(remaining[0].Area, 200)

    def test_every_box_face_can_be_divided_and_pulled(self):
        for face in self.box.Faces:
            vertices = [vertex.Point for vertex in face.Vertexes]
            first = vertices[0]
            opposite = max(vertices, key=lambda point: (point - first).Length)
            result = g.divide_face_with_line(self.box, first, opposite)
            self.assertIsNotNone(result)
            self.assertEqual(len(result.Faces), 7)
            normal = g.face_normal(face)
            regions = [f for f in result.Faces if (g.face_normal(f) - normal).Length < 1e-6]
            self.assertEqual(len(regions), 2)
            for region in regions:
                self.assertAlmostEqual(region.Area, face.Area / 2)
                self.assertAlmostEqual(g.push_pull(result, region, 2).Volume,
                                       self.box.Volume + face.Area)

    def test_midpoints_and_crossing_diagonals(self):
        middle = g.divide_face_with_line(self.box, g.V(0, 0, 5), g.V(40, 0, 5))
        self.assertEqual(len(front_faces(middle)), 2)
        crossed = g.divide_face_with_line(self.divided(), g.V(), g.V(40, 0, 10))
        self.assertTrue(crossed.isValid())
        self.assertEqual(len(front_faces(crossed)), 4)
        self.assertAlmostEqual(crossed.Volume, 12000)
        for face in front_faces(crossed):
            self.assertAlmostEqual(face.Area, 100)
            self.assertAlmostEqual(g.push_pull(crossed, face, -2).Volume, 11800)

    def test_incomplete_boundary_outside_and_off_plane_lines_do_not_divide(self):
        for first, second in ((g.V(0, 0, 5), g.V(20, 0, 5)),
                              (g.V(10, 0, 5), g.V(20, 0, 5)),
                              (g.V(), g.V(40, 0, 0)),
                              (g.V(-1, 0, 5), g.V(41, 0, 5)),
                              (g.V(0, 0, 10), g.V(40, 30, 0))):
            with self.subTest(first=first, second=second):
                self.assertIsNone(g.divide_face_with_line(self.box, first, second))
        self.assertEqual(len(self.box.Faces), 6)
        self.assertAlmostEqual(self.box.Volume, 12000)

    def test_other_divisions_survive_push_pull(self):
        divided = self.divided()
        top = max(divided.Faces, key=lambda face: face.CenterOfMass.z)
        pulled = g.push_pull(divided, top, 5)
        old_triangles = [face for face in front_faces(pulled)
                         if len(face.Edges) == 3 and abs(face.Area - 200) < 1e-6]
        self.assertEqual(len(old_triangles), 2)
        self.assertTrue(g.has_face_divisions(pulled))
        self.assertAlmostEqual(g.push_pull(pulled, old_triangles[0], -2).Volume, 17600)


class DivisionDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADDivisionTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 30, 10), "Block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def divide(self):
        return op.draw_line(self.doc, g.V(0, 0, 10), g.V(40, 0, 0))

    def test_division_and_triangle_pull_are_separate_undo_steps(self):
        name = self.obj.Name
        count = self.doc.UndoCount
        result, divided = self.divide()
        self.assertTrue(divided)
        self.assertEqual(result, self.obj)
        self.assertEqual(result.Name, name)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(self.doc.UndoCount, count + 1)
        triangle = front_faces(result.Shape)[0]
        op.extrude(result, triangle, -5)
        self.assertAlmostEqual(result.Shape.Volume, 11000)
        self.doc.undo()
        self.assertEqual(len(result.Shape.Faces), 7)
        self.assertAlmostEqual(result.Shape.Volume, 12000)
        self.doc.undo()
        self.assertEqual(len(result.Shape.Faces), 6)
        self.doc.redo()
        self.assertEqual(len(result.Shape.Faces), 7)
        self.doc.redo()
        self.assertAlmostEqual(result.Shape.Volume, 11000)

    def test_incomplete_line_remains_a_free_edge(self):
        result, divided = op.draw_line(self.doc, g.V(0, 0, 5), g.V(20, 0, 5))
        self.assertFalse(divided)
        self.assertEqual(result.Shape.ShapeType, "Edge")
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 1)

    def test_rotated_and_translated_block(self):
        placement = App.Placement(g.V(60, 80, 100), App.Rotation(g.V(1, 2, 3), 37))
        self.obj.Placement = placement
        before = self.obj.Shape.copy()
        first, second = [placement.multVec(v) for v in (g.V(0, 0, 10), g.V(40, 0, 0))]
        result, divided = op.draw_line(self.doc, first, second, self.obj)
        self.assertTrue(divided)
        self.assertEqual(len(result.Shape.Faces), 7)
        self.assertLess((result.Shape.CenterOfMass - before.CenterOfMass).Length, 1e-6)
        self.assertAlmostEqual(result.Shape.common(before).Volume, before.Volume)
        normal = placement.Rotation.multVec(g.V(0, -1, 0))
        triangle = next(f for f in result.Shape.Faces if (g.face_normal(f) - normal).Length < 1e-6)
        op.extrude(result, triangle, 5)
        self.assertAlmostEqual(result.Shape.Volume, 13000)

    def test_parametric_shape_is_left_unchanged(self):
        self.doc.removeObject(self.obj.Name)
        parametric = self.doc.addObject("Part::Box", "Parametric")
        self.doc.recompute()
        result, divided = op.draw_line(self.doc, g.V(0, 0, 10), g.V(10, 0, 0), parametric)
        self.assertFalse(divided)
        self.assertEqual(result.Shape.ShapeType, "Edge")
        self.assertEqual(len(parametric.Shape.Faces), 6)

    def test_divisions_persist_and_copies_are_independent(self):
        self.divide()
        clone = op.transform([self.obj], g.V(60, 0, 0), copy=True)[0]
        op.extrude(clone, front_faces(clone.Shape)[0], 5)
        self.assertAlmostEqual(self.obj.Shape.Volume, 12000)
        self.assertAlmostEqual(clone.Shape.Volume, 13000)
        name = self.obj.Name
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "divided.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            result = self.doc.getObject(name)
            self.assertEqual(len(front_faces(result.Shape)), 2)
            op.extrude(result, front_faces(result.Shape)[0], -5)
            self.assertAlmostEqual(result.Shape.Volume, 11000)


class LineInferenceTests(unittest.TestCase):
    """Real face topology; only screen projection and native picking are replaced."""
    def setUp(self):
        self.snapper = Snapper.__new__(Snapper)
        from simplecad.core.preferences import Settings
        self.snapper.settings = Settings()
        self.snapper.doc = None
        self.snapper.view = SimpleNamespace(getPointOnScreen=lambda v: (v.x * 10, v.z * 10 + v.y * 2))
        self.snapper.faces = Part.makeBox(40, 30, 10).Faces
        self.snapper.points = []

    def test_first_corner_without_face_hit_chooses_a_face_plane(self):
        corner = g.V(0, 0, 10)
        self.snapper.points = [(corner, "Endpoint")]
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, plane = self.snapper.snap_start((0, 100), g.Plane.named())
        self.assertLess((snap.point - corner).Length, 1e-7)
        self.assertAlmostEqual((snap.point - plane.origin).dot(plane.normal), 0)
        self.assertEqual(len(self.snapper.faces_at(snap.point)), 3)

    def test_opposite_corner_resolves_side_instead_of_initial_top_plane(self):
        anchor, end = g.V(0, 0, 10), g.V(40, 0, 0)
        self.snapper.points = [(end, "Endpoint")]
        top = g.Plane.named("XY", anchor)
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, plane = self.snapper.snap_line((400, 0), top, anchor, self.snapper.faces_at(anchor))
        self.assertLess((snap.point - end).Length, 1e-7)
        self.assertAlmostEqual(abs(plane.normal.y), 1)
        self.assertAlmostEqual((anchor - plane.origin).dot(plane.normal), 0)

    def test_hover_chooses_a_face_containing_the_anchor(self):
        anchor = g.V(0, 0, 10)
        # Use the same topology held in the snapshot, as native picking does.
        side = next(f for f in self.snapper.faces if abs(f.CenterOfMass.y) < 1e-7)
        point = side.CenterOfMass
        with patch("simplecad.gui.snapping.pick", return_value=(None, side, point, "Face3")), \
                patch.object(self.snapper, "snap", return_value=Snap(point, "Face")) as fallback:
            _, plane = self.snapper.snap_line((200, 50), g.Plane.named("XY", anchor), anchor,
                                              self.snapper.faces_at(anchor), enabled=False)
        self.assertAlmostEqual(abs(plane.normal.y), 1)
        self.assertEqual(fallback.call_args.args[3], False)


if __name__ == "__main__":
    unittest.main()
