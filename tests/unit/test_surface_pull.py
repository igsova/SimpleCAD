"""Pull faces after surface cleanup/deletion, keeping all unpicked geometry."""
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as c
from simplecad.document import operations as op

V = App.Vector


def triangles():
    a, b = V(0, 0, 10), V(40, 0, 10)
    return [Part.Face(Part.makePolygon([a, b, V(20, 25, 10), a])),
            Part.Face(Part.makePolygon([b, a, V(20, -15, -10), b]))]


class SurfacePullGeometryTests(unittest.TestCase):
    def assert_preserved(self, remainder, expected):
        self.assertTrue(remainder.isValid())
        self.assertEqual(len(remainder.Faces), len(expected))
        self.assertAlmostEqual(remainder.Area, sum(face.Area for face in expected))
        for face in expected:
            self.assertTrue(any(c.same(face, other) for other in remainder.Faces))

    def test_both_joined_triangles_pull_in_both_directions(self):
        shape = c.assemble(triangles())
        self.assertEqual(shape.ShapeType, "Shell")
        for i, face in enumerate(shape.Faces):
            for distance in (-5, 5):
                with self.subTest(face=i, distance=distance):
                    result, remainder = g.plan_push_pull(shape, face, distance)
                    self.assertEqual(result.ShapeType, "Solid")
                    self.assertTrue(result.isValid())
                    self.assertAlmostEqual(result.Volume, face.Area * abs(distance))
                    cap = face.copy()
                    cap.translate(g.face_normal(face) * distance)
                    self.assertTrue(any(c.same(cap, other) for other in result.Faces))
                    self.assert_preserved(remainder, [shape.Faces[1 - i]])
        self.assertEqual(len(shape.Faces), 2)

    def test_unsewn_compound_and_face_duplicates_preserve_other_faces(self):
        first, second = triangles()
        shape = Part.makeCompound([first, second, first.copy()])
        result, remainder = g.plan_push_pull(shape, first, 3)
        self.assertAlmostEqual(result.Volume, first.Area * 3)
        self.assert_preserved(remainder, [second])

    def test_every_face_of_erased_block_can_pull(self):
        opened = g.erase_elements(Part.makeBox(40, 30, 10), ["Edge1"])
        for i, face in enumerate(opened.Faces):
            result, remainder = g.plan_push_pull(opened, face, 2)
            self.assertAlmostEqual(result.Volume, face.Area * 2)
            self.assert_preserved(remainder, [other for j, other in enumerate(opened.Faces) if i != j])

    def test_single_closed_shell_uses_existing_volume_instead_of_plucking_a_face(self):
        box = g.divide_face_with_line(Part.makeBox(40, 30, 10), V(0, 0, 10), V(40, 30, 10))
        shell = box.Shells[0].copy()
        shell.reverse()  # Outward orientation must be resolved for the preview too.
        self.assertTrue(shell.isClosed())
        self.assertFalse(shell.Solids)
        face = next(face for face in shell.Faces if len(face.Edges) == 3 and abs(face.CenterOfMass.z - 10) < 1e-6)
        base, selected, remainder = g.pull_source(shell, face)
        self.assertGreater(g.face_normal(selected).z, 0.99)
        self.assertAlmostEqual(base.Volume, 12000)
        for distance in (-2, 2):
            result, remainder = g.plan_push_pull(shell, face, distance)
            self.assertAlmostEqual(result.Volume, 12000 + face.Area * distance)
            self.assertIsNone(remainder)

    def test_moved_rotated_surface_and_reversed_face_preserve_world_coordinates(self):
        shape = c.assemble(triangles())
        shape.Placement = App.Placement(V(70, -30, 12), App.Rotation(V(1, 2, 3), 37))
        face = shape.Faces[1]
        result, remainder = g.plan_push_pull(shape, face, -4)
        expected = face.extrude(g.face_normal(face) * -4)
        self.assertAlmostEqual(result.common(expected).Volume, expected.Volume)
        self.assert_preserved(remainder, [shape.Faces[0]])

    def test_hole_and_loose_edges_are_retained(self):
        face = Part.makePlane(20, 20).cut(Part.makePlane(4, 4, V(6, 6, 0))).Faces[0]
        loose = Part.makeLine(V(30, 30, 0), V(35, 35, 10))
        result, remainder = g.plan_push_pull(Part.makeCompound([face, loose]), face, 5)
        self.assertAlmostEqual(result.Volume, 384 * 5)
        self.assertAlmostEqual(result.common(Part.makeBox(4, 4, 5, V(6, 6, 0))).Volume, 0)
        self.assertTrue(c.same(remainder, loose))

    def test_foreign_curved_or_degenerate_input_rejected(self):
        shape = c.assemble(triangles())
        for distance in (0, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                g.plan_push_pull(shape, shape.Faces[0], distance)
        with self.assertRaisesRegex(ValueError, "no longer"):
            g.plan_push_pull(shape, Part.makePlane(4, 4), 3)
        cylinder = Part.makeCylinder(5, 10)
        curved = next(face for face in cylinder.Faces if not isinstance(face.Surface, Part.Plane))
        with self.assertRaisesRegex(ValueError, "flat"):
            g.plan_push_pull(cylinder, curved, 3)

    def test_solid_with_loose_line_preserves_line_and_mixed_surface_rejected(self):
        box = Part.makeBox(10, 10, 10)
        edge = Part.makeLine(V(20, 20, 0), V(25, 20, 0))
        result, remainder = g.plan_push_pull(Part.makeCompound([box, edge]), box.Faces[0], 3)
        self.assertAlmostEqual(result.Volume, 1300)
        self.assertTrue(c.same(remainder, edge))
        mixed = Part.makeCompound([box, Part.makePlane(3, 3, V(20, 20, 0))])
        with self.assertRaisesRegex(ValueError, "Separate"):
            g.plan_push_pull(mixed, box.Faces[0], 3)


class SurfacePullDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADSurfacePullTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, c.assemble(triangles()), "Joined triangles")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_pull_undo_redo_preserves_identity_and_remaining_surface(self):
        face, untouched = self.obj.Shape.Faces
        before = self.doc.UndoCount
        name = self.obj.Name
        result = op.extrude(self.obj, face, 5)
        self.assertEqual(result, self.obj)
        self.assertEqual(result.Name, name)
        self.assertAlmostEqual(result.Shape.Volume, face.Area * 5)
        self.assertEqual(len(self.doc.Objects), 2)
        rest = next(obj for obj in self.doc.Objects if obj != result)
        self.assertTrue(c.same(rest.Shape, untouched))
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(self.obj.Shape.Faces), 2)
        self.assertFalse(self.obj.Shape.Solids)
        self.doc.redo()
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertAlmostEqual(self.obj.Shape.Volume, face.Area * 5)

    def test_remaining_face_and_new_solid_both_allow_another_pull(self):
        original = self.obj.Shape.Faces[0]
        op.extrude(self.obj, original, 5)
        cap = original.copy()
        cap.translate(g.face_normal(original) * 5)
        face = next(face for face in self.obj.Shape.Faces if c.same(cap, face))
        op.extrude(self.obj, face, 2)
        self.assertAlmostEqual(self.obj.Shape.Volume, original.Area * 7)
        rest = next(obj for obj in self.doc.Objects if obj != self.obj)
        area = rest.Shape.Area
        op.extrude(rest, rest.Shape.Faces[0], -3)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertTrue(all(len(obj.Shape.Solids) == 1 for obj in self.doc.Objects))
        self.assertAlmostEqual(rest.Shape.Volume, area * 3)

    def test_cleanup_then_pull_and_undo_both_operations(self):
        # Restore the exact workflow that introduced the user-facing restriction.
        self.doc.removeObject(self.obj.Name)
        for face in triangles():
            op.new_shape(self.doc, face, "Triangle")
        op.cleanup(self.doc)
        self.assertEqual(len(self.doc.Objects), 1)
        obj = self.doc.Objects[0]
        op.extrude(obj, obj.Shape.Faces[0], 3)
        self.assertEqual(len(self.doc.Objects), 2)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(self.doc.Objects[0].Shape.Faces), 2)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertTrue(all(obj.Shape.ShapeType == "Face" for obj in self.doc.Objects))

    def test_closed_shell_preview_normal_matches_outward_commit(self):
        shell = Part.makeBox(40, 30, 10).Shells[0]
        shell.reverse()
        self.obj.Shape = shell
        top = next(face for face in self.obj.Shape.Faces if abs(face.CenterOfMass.z - 10) < 1e-7)
        self.assertGreater(op.extrusion_normal(self.obj, top).z, 0.99)
        op.extrude(self.obj, top, 5)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertAlmostEqual(self.obj.Shape.Volume, 18000)
        self.doc.undo()
        self.assertEqual(self.obj.Shape.ShapeType, "Shell")

    def test_failed_pull_leaves_no_extra_object_or_undo_step(self):
        before = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.extrude(self.obj, self.obj.Shape.Faces[0], 0)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(self.obj.Shape.Faces), 2)
        self.assertEqual(self.doc.UndoCount, before)

    def test_save_reopen_and_continue_pulling(self):
        face = self.obj.Shape.Faces[0]
        op.extrude(self.obj, face, 5)
        name = self.obj.Name
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "pulled-surfaces.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.assertEqual(len(self.doc.Objects), 2)
            self.assertAlmostEqual(self.doc.getObject(name).Shape.Volume, face.Area * 5)
            rest = next(obj for obj in self.doc.Objects if obj.Name != name)
            op.extrude(rest, rest.Shape.Faces[0], 2)
            self.assertTrue(all(obj.Shape.isValid() and len(obj.Shape.Solids) == 1 for obj in self.doc.Objects))


if __name__ == "__main__":
    unittest.main()
