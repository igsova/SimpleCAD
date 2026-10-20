"""Cross-face endpoint snaps and creation of missing triangular faces."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.modeling import drawing
from simplecad.document import operations as op
from simplecad.gui.snapping import Snapper

V = App.Vector
A, B, C = V(0, 0, 0), V(30, 20, 15), V(30, 0, 0)


def folded_sides():
    left = Part.Face(Part.makePolygon([A, C, V(0, -20, -10), A]))
    right = Part.Face(Part.makePolygon([C, B, V(50, 20, -5), C]))
    return Part.makeCompound([left, right])


class SpatialSnapTests(unittest.TestCase):
    def setUp(self):
        self.snapper = Snapper.__new__(Snapper)
        from simplecad.core.preferences import Settings
        self.snapper.settings = Settings()
        self.snapper.doc = None
        self.snapper.view = SimpleNamespace(getPointOnScreen=lambda v: (v.x * 10, v.y * 10 + v.z * 3))
        self.snapper.faces = folded_sides().Faces
        self.snapper.points = [(A, "Endpoint"), (B, "Endpoint"), (C, "Endpoint")]

    def test_snap_to_vertex_on_different_face_without_projecting(self):
        faces = self.snapper.faces_at(A)
        self.assertFalse(any(g.point_on_face(face, B) for face in faces))
        plane = g.Plane.from_face(faces[0])
        self.assertGreater((plane.project(B) - B).Length, 1)
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, _ = self.snapper.snap_line((300, 245), plane, A, faces)
        self.assertLess((snap.point - B).Length, 1e-7)
        self.assertEqual(snap.label, "Endpoint")

    def test_first_and_second_loose_vertices_work_without_adjacent_faces(self):
        self.snapper.faces = []
        raised = V(0, 0, 25)
        self.snapper.points = [(raised, "Endpoint"), (B, "Endpoint")]
        with patch("simplecad.gui.snapping.pick", return_value=None):
            snap, plane = self.snapper.snap_start((0, 75), g.Plane.named())
            end, _ = self.snapper.snap_line((300, 245), plane, snap.point, [])
        self.assertLess((snap.point - raised).Length, 1e-7)
        self.assertLess((end.point - B).Length, 1e-7)

    def test_explicit_plane_does_not_offer_off_plane_vertex(self):
        plane = g.Plane.named()
        with patch("simplecad.gui.snapping.ray", return_value=(V(30, 24.5, 100), V(0, 0, -1))), \
                patch("simplecad.gui.snapping.pick", return_value=None):
            snap = self.snapper.snap((300, 245), plane, A)
        self.assertAlmostEqual(snap.point.z, 0)
        self.assertGreater((snap.point - B).Length, 1)


class TriangleGeometryTests(unittest.TestCase):
    def test_different_faces_form_a_triangle_and_join_an_open_shape(self):
        shape = folded_sides()
        faces = drawing.triangle_completions([shape], A, B)
        self.assertEqual(len(faces), 1)
        self.assertEqual(len(faces[0].Edges), 3)
        self.assertAlmostEqual(faces[0].Area, 375)
        result = drawing.attach_triangles(shape, faces)
        self.assertIsNotNone(result)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), 3)
        self.assertEqual(len(result.Solids), 0)
        self.assertAlmostEqual(result.Area, shape.Area + 375)
        self.assertEqual(len(result.Shells), 1)

    def test_closing_a_triangular_hole_restores_a_push_pullable_solid(self):
        box = g.divide_face_with_line(Part.makeBox(40, 30, 10), V(0, 0, 10), V(40, 30, 10))
        i = next(i for i, f in enumerate(box.Faces) if len(f.Edges) == 3 and abs(f.CenterOfMass.z - 10) < 1e-6)
        face = box.Faces[i]
        opened = g.erase_elements(box, ["Face" + str(i + 1)])
        first, second = [v.Point for v in face.Edges[0].Vertexes]
        patches = drawing.triangle_completions([opened], first, second)
        self.assertEqual(len(patches), 1)
        result = drawing.attach_triangles(opened, patches)
        self.assertEqual(result.ShapeType, "Solid")
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 12000)
        top = next(f for f in result.Faces if len(f.Edges) == 3 and abs(f.CenterOfMass.z - 10) < 1e-6)
        self.assertAlmostEqual(g.push_pull(result, top, 2).Volume, 13200)

    def test_reversed_click_direction_and_oblique_placement(self):
        shape = folded_sides()
        placement = App.Placement(V(60, 80, 100), App.Rotation(V(1, 2, 3), 37))
        shape.Placement = placement
        first, second = placement.multVec(B), placement.multVec(A)
        patches = drawing.triangle_completions([shape], first, second)
        self.assertEqual(len(patches), 1)
        self.assertAlmostEqual(patches[0].Area, 375)
        result = drawing.attach_triangles(shape, patches)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Area, shape.Area + 375)

    def test_no_duplicate_face_or_face_inside_a_solid(self):
        triangle = Part.Face(Part.makePolygon([A, B, C, A]))
        self.assertEqual(drawing.triangle_completions([triangle], A, B), [])
        interior = Part.makeBox(100, 100, 100, V(-20, -30, -40))
        wires = Part.makeCompound([Part.makeLine(A, C), Part.makeLine(C, B)])
        self.assertEqual(drawing.triangle_completions([wires, interior], A, B), [])

    def test_open_or_collinear_paths_stay_lines(self):
        self.assertEqual(drawing.triangle_completions([Part.makeLine(A, C)], A, B), [])
        straight = Part.makeCompound([Part.makeLine(V(), V(10, 0, 0)),
                                      Part.makeLine(V(10, 0, 0), V(20, 0, 0))])
        self.assertEqual(drawing.triangle_completions([straight], V(), V(20, 0, 0)), [])

    def test_triangle_side_can_contain_extra_collinear_vertices(self):
        split_side = [Part.makeLine(A, C / 2), Part.makeLine(C / 2, C), Part.makeLine(C, B)]
        patches = drawing.triangle_completions(split_side, A, B)
        self.assertEqual(len(patches), 1)
        self.assertAlmostEqual(patches[0].Area, 375)

    def test_bridge_above_a_solid_stays_an_independent_face(self):
        solid = Part.makeBox(40, 30, 20).cut(Part.makeBox(20, 30, 10, V(0, 0, 10))).Solids[0]
        patches = drawing.triangle_completions([solid], V(0, 0, 10), V(20, 0, 20))
        self.assertEqual(len(patches), 1)
        self.assertAlmostEqual(patches[0].Area, 100)
        self.assertIsNone(drawing.attach_triangles(solid, patches))

    def test_patches_cannot_create_three_faces_on_one_existing_edge(self):
        existing = Part.Face(Part.makePolygon([A, B, V(-10, -20, -10), A]))
        patches = [Part.Face(Part.makePolygon([A, B, third, A]))
                   for third in (C, V(0, 20, 30))]
        self.assertIsNone(drawing.attach_triangles(existing, patches))


class TriangleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADTriangleTest")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_three_lines_become_a_face_and_extrude(self):
        op.draw_line(self.doc, A, C)
        op.draw_line(self.doc, C, B)
        count = self.doc.UndoCount
        result, changed = op.draw_line(self.doc, A, B)
        self.assertTrue(changed)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(result.Shape.ShapeType, "Face")
        self.assertAlmostEqual(result.Shape.Area, 375)
        self.assertEqual(self.doc.UndoCount, count + 1)
        op.extrude(result, result.Shape, 4)
        self.assertAlmostEqual(result.Shape.Volume, 1500)
        self.doc.undo()
        self.assertEqual(self.doc.Objects[0].Shape.ShapeType, "Face")
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertTrue(all(obj.Shape.ShapeType == "Edge" for obj in self.doc.Objects))
        self.doc.redo()
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertAlmostEqual(self.doc.Objects[0].Shape.Area, 375)

    def test_cross_face_connection_updates_same_open_object_and_saves(self):
        obj = op.new_shape(self.doc, folded_sides(), "Folded sides")
        name = obj.Name
        result, changed = op.draw_line(self.doc, A, B, obj)
        self.assertTrue(changed)
        self.assertEqual(result, obj)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(obj.Shape.Faces), 3)
        self.doc.undo()
        self.assertEqual(len(obj.Shape.Faces), 2)
        self.doc.redo()
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "triangle.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.assertEqual(len(self.doc.getObject(name).Shape.Faces), 3)
            self.assertTrue(self.doc.getObject(name).Shape.isValid())

    def test_unconnected_vertices_create_an_exact_3d_line(self):
        op.new_shape(self.doc, Part.makeLine(A, V(-5, 0, 0)), "First")
        op.new_shape(self.doc, Part.makeLine(B, V(40, 20, 15)), "Second")
        result, changed = op.draw_line(self.doc, A, B)
        self.assertFalse(changed)
        self.assertEqual(len(self.doc.Objects), 3)
        self.assertAlmostEqual(result.Shape.Length, (B - A).Length)
        for endpoint in (A, B):
            self.assertTrue(any((v.Point - endpoint).Length < 1e-6 for v in result.Shape.Vertexes))


if __name__ == "__main__":
    unittest.main()
