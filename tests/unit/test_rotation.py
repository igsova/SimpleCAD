"""Rigid world/local rotations preserve geometry and commit in one Undo step."""
import math
import tempfile
from contextlib import contextmanager
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.modeling import rotation as r
from simplecad.document import operations as op

V = App.Vector


class RotationGeometryTests(unittest.TestCase):
    def setUp(self):
        self.shape = Part.makeBox(40, 20, 10)
        self.shape.Placement = App.Placement(V(80, -20, 30), App.Rotation(V(1, 2, 3), 27))

    def near(self, actual, expected):
        self.assertLess((actual - expected).Length, 1e-6)

    def test_world_quarter_turns_map_every_vertex_without_changing_the_source(self):
        source = self.shape.copy()
        # Explicit coordinate permutations also check sign and composition order.
        mappings = {"X": lambda p: V(p.x, -p.z, p.y),
                    "Y": lambda p: V(p.z, p.y, -p.x),
                    "Z": lambda p: V(-p.y, p.x, p.z)}
        for axis, mapping in mappings.items():
            frames = r.frames([self.shape], axis, "Origin")
            result = r.rotated([self.shape], frames, 90)[0]
            for before, after in zip(self.shape.Vertexes, result.Vertexes):
                self.near(after.Point, mapping(before.Point))
            self.assertTrue(result.isValid() and result.isClosed())
            self.assertAlmostEqual(result.Volume, self.shape.Volume)
            self.assertEqual(len(result.Faces), len(self.shape.Faces))
        for a, b in zip(source.Vertexes, self.shape.Vertexes): self.near(a.Point, b.Point)

    def test_own_center_stays_fixed_and_preview_never_accumulates(self):
        frames = r.frames([self.shape], "Y")
        original = self.shape.copy()
        for angle in (37.5, -50, 180, 90, 0, 360, -720):
            result = r.rotated([self.shape], frames, angle)[0]
            self.near(result.CenterOfMass, original.CenterOfMass)
            if angle % 360 == 0:
                for a, b in zip(result.Vertexes, original.Vertexes): self.near(a.Point, b.Point)
        first = r.rotated([self.shape], frames, 37.5)[0]
        again = r.rotated([self.shape], frames, 37.5)[0]
        for a, b in zip(first.Vertexes, again.Vertexes): self.near(a.Point, b.Point)

    def test_local_axes_follow_object_orientation_and_main_axis_follows_geometry(self):
        for axis, vector in r.AXES.items():
            self.near(r.direction(self.shape, "Local" + axis), self.shape.Placement.Rotation.multVec(vector))
        self.assertAlmostEqual(abs(r.direction(self.shape, "Main").dot(r.direction(self.shape, "LocalX"))), 1)
        # A baked-in, tilted cylinder has an intrinsic axis despite identity Placement.
        normal = V(1, 2, 3); normal.normalize()
        cylinder = Part.makeCylinder(3, 40, V(20, 30, 10), normal)
        self.assertAlmostEqual(abs(r.direction(cylinder, "Main").dot(normal)), 1)
        result = r.rotated([cylinder], r.frames([cylinder], "Main", "Each"), 64)[0]
        self.assertAlmostEqual(cylinder.common(result).Volume, cylinder.Volume, places=5)

    def test_local_rotation_is_distinct_from_world_rotation(self):
        local = r.rotated([self.shape], r.frames([self.shape], "LocalX"), 90)[0]
        world = r.rotated([self.shape], r.frames([self.shape], "X"), 90)[0]
        self.assertGreater((local.Vertexes[0].Point - world.Vertexes[0].Point).Length, 1)
        # Rotate in the original object's coordinates, then place in the world.
        native = Part.makeBox(40, 20, 10)
        point = native.Vertexes[0].Point - native.CenterOfMass
        expected = self.shape.Placement.multVec(native.CenterOfMass + V(point.x, -point.z, point.y))
        self.near(local.Vertexes[0].Point, expected)

    def test_multiple_objects_rotate_together_or_spin_individually(self):
        a = Part.makeBox(10, 20, 8, V(-30, 0, 0))
        b = Part.makeBox(10, 20, 8, V(20, 0, 0))
        together = r.rotated([a, b], r.frames([a, b], "Z", "Selection"), 90)
        each = r.rotated([a, b], r.frames([a, b], "Z", "Each"), 90)
        self.near(together[1].CenterOfMass - together[0].CenterOfMass, V(0, 50, 0))
        self.assertAlmostEqual(a.distToShape(b)[0], together[0].distToShape(together[1])[0])
        for original, result in zip((a, b), each): self.near(result.CenterOfMass, original.CenterOfMass)
        b.Placement = App.Placement(V(20, 0, 0), App.Rotation(V(0, 1, 0), 40))
        for pivot in ("Selection", "Origin"):
            frames = r.frames([a, b], "LocalX", pivot)
            self.near(frames[0].axis, frames[1].axis)
            result = r.rotated([a, b], frames, 33)
            self.assertAlmostEqual((a.CenterOfMass - b.CenterOfMass).Length,
                                   (result[0].CenterOfMass - result[1].CenterOfMass).Length)
        frames = r.frames([a, b], "LocalX", "Each")
        self.assertGreater((frames[0].axis - frames[1].axis).Length, .1)

    def test_open_faces_edges_points_compounds_and_round_surfaces(self):
        cube = Part.makeBox(15, 15, 15)
        shapes = [cube.makeFillet(2, cube.Edges), Part.makeShell(cube.Faces[:-1]),
                  cube.Faces[0], Part.makeLine(V(10, 20, 30), V(40, 10, 10)),
                  Part.Vertex(V(10, 20, 30)), Part.makeCompound([cube, self.shape])]
        for shape in shapes:
            for axis in ("Z", "Main", "LocalY"):
                result = r.rotated([shape], r.frames([shape], axis), -33)[0]
                self.assertTrue(result.isValid())
                self.assertEqual((len(result.Faces), len(result.Edges), len(result.Vertexes)),
                                 (len(shape.Faces), len(shape.Edges), len(shape.Vertexes)))
                self.assertAlmostEqual(result.Area, shape.Area, places=5)
                self.assertAlmostEqual(result.Length, shape.Length, places=5)

    def test_symmetric_main_axis_is_deterministic(self):
        cube = Part.makeBox(10, 10, 10)
        cube.Placement = self.shape.Placement
        self.assertAlmostEqual(abs(r.direction(cube, "Main").dot(r.direction(cube, "LocalX"))), 1)
        self.near(r.direction(cube, "Main"), r.direction(cube, "Main"))

    def test_angles_units_turns_and_invalid_input(self):
        for text, expected in (("45", 45), ("-90°", -90), ("12.5 deg", 12.5),
                               ("1.5707963267948966 rad", 90), ("450°", 450)):
            self.assertAlmostEqual(r.parse_angle(text), expected)
        for text in ("", " ", "banana", "nan", "inf", "1e999", "20 mm", "5 s"):
            with self.subTest(text=text), self.assertRaises(ValueError): r.parse_angle(text)
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError): r.rotated([self.shape], r.frames([self.shape]), value)
        with self.assertRaises(ValueError): r.frames([], "Z")
        with self.assertRaises(ValueError): r.frames([self.shape], "Wrong")
        with self.assertRaises(ValueError): r.frames([self.shape], "Z", "Wrong")
        with self.assertRaises(ValueError): r.rotated([self.shape], [], 45)
        self.assertEqual(r.angle_degrees(450), 90)


class RotationDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("RotateTest"); self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 20, 10), "Block")
        self.obj.Placement = App.Placement(V(70, 30, 40), App.Rotation(V(1, 2, 3), 27))

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_preview_commit_undo_redo_and_native_topology(self):
        targets = op.prepare_rotation([(self.obj, ("Face1",)), (self.obj, ("Edge1",))])
        self.assertEqual(len(targets), 1)
        original, count = self.obj.Shape, self.doc.UndoCount
        frames = r.frames([original], "Z")
        planned = op.preview_rotation(targets, frames, 45)
        self.assertTrue(self.obj.Shape.isSame(original)); self.assertEqual(self.doc.UndoCount, count)
        op.commit_rotation(targets, frames, 45)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(self.obj.Label, "Block")
        self.assertTrue(self.obj.Shape.isPartner(original))
        for a, b in zip(self.obj.Shape.Vertexes, planned[0][1].Vertexes):
            self.assertLess((a.Point - b.Point).Length, 1e-6)
        self.doc.undo(); self.assertTrue(self.obj.Shape.isSame(original))
        self.doc.redo()
        for a, b in zip(self.obj.Shape.Vertexes, planned[0][1].Vertexes):
            self.assertLess((a.Point - b.Point).Length, 1e-6)

    def test_zero_and_whole_turns_do_not_create_undo_edits(self):
        targets = op.prepare_rotation([(self.obj, ())]); original = self.obj.Shape
        count = self.doc.UndoCount; frames = r.frames([original])
        for angle in (0, 360, -720): self.assertFalse(op.commit_rotation(targets, frames, angle))
        self.assertEqual(count, self.doc.UndoCount); self.assertTrue(self.obj.Shape.isSame(original))

    def test_multiple_changes_are_atomic_even_if_commit_fails(self):
        other = op.new_shape(self.doc, Part.makeBox(10, 20, 30), "Other")
        targets = op.prepare_rotation([(self.obj, ()), (other, ())])
        frames = r.frames([s for _, s in targets], "X"); count = self.doc.UndoCount
        original_transaction = op.transaction

        @contextmanager
        def fail_after_writes(doc, title):
            with original_transaction(doc, title):
                yield
                raise RuntimeError("Simulated document failure")

        with patch.object(op, "transaction", fail_after_writes):
            with self.assertRaises(RuntimeError): op.commit_rotation(targets, frames, 37)
        self.assertEqual(count, self.doc.UndoCount)
        for obj, shape in targets: self.assertTrue(obj.Shape.isSame(shape))
        op.commit_rotation(targets, frames, 37)
        self.assertEqual(count + 1, self.doc.UndoCount)
        self.doc.undo()
        for obj, shape in targets: self.assertTrue(obj.Shape.isSame(shape))

    def test_stale_shape_placement_and_deleted_objects_cannot_commit(self):
        targets = op.prepare_rotation([(self.obj, ())]); frames = r.frames([self.obj.Shape])
        op.transform([self.obj], V(1, 0, 0))
        with self.assertRaisesRegex(ValueError, "changed"): op.commit_rotation(targets, frames, 30)
        targets = op.prepare_rotation([(self.obj, ())])
        self.obj.Shape = Part.makeBox(1, 2, 3)
        with self.assertRaisesRegex(ValueError, "changed"): op.commit_rotation(targets, frames, 30)
        targets = op.prepare_rotation([(self.obj, ())]); self.doc.removeObject(self.obj.Name)
        with self.assertRaises((ValueError, ReferenceError, RuntimeError)): op.check_rotation(targets)

    def test_invalid_selection_and_links_fail_before_writing(self):
        with self.assertRaises(ValueError): op.prepare_rotation([])
        param = self.doc.addObject("Part::Box", "Parametric"); self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "plain Part"): op.prepare_rotation([(param, ())])
        self.obj.addProperty("App::PropertyLink", "SC_Support"); self.obj.SC_Support = param
        with self.assertRaisesRegex(ValueError, "links"): op.prepare_rotation([(self.obj, ())])
        self.obj.removeProperty("SC_Support")
        self.obj.setExpression("Placement.Base.x", "10")
        with self.assertRaisesRegex(ValueError, "expressions"): op.prepare_rotation([(self.obj, ())])
        self.obj.setExpression("Placement.Base.x", None)
        other_doc = App.newDocument("RotateOther")
        try:
            other = op.new_shape(other_doc, Part.makeBox(1, 2, 3), "Other")
            with self.assertRaisesRegex(ValueError, "one document"): op.prepare_rotation([(self.obj, ()), (other, ())])
        finally: App.closeDocument(other_doc.Name)

    def test_save_reopen_copy_and_repeat_rotation(self):
        targets = op.prepare_rotation([(self.obj, ())]); frames = r.frames([self.obj.Shape], "LocalY")
        op.commit_rotation(targets, frames, 37.25)
        vertices = [v.Point for v in self.obj.Shape.Vertexes]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Rotated.FCStd"; self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name); self.doc = App.openDocument(str(path)); self.doc.UndoMode = 1
            self.obj = self.doc.Objects[0]
            self.assertEqual(self.obj.TypeId, "Part::Feature")
            self.assertNotIn("Proxy", self.obj.PropertiesList)
            for v, p in zip(self.obj.Shape.Vertexes, vertices): self.assertLess((v.Point - p).Length, 1e-6)
            copy = op.transform([self.obj], V(100, 0, 0), copy=True)[0]
            targets = op.prepare_rotation([(copy, ())])
            before = copy.Shape.CenterOfMass
            op.commit_rotation(targets, r.frames([copy.Shape], "Main", "Each"), 45)
            self.assertLess((copy.Shape.CenterOfMass - before).Length, 1e-6)
            self.assertTrue(copy.Shape.isValid() and copy.Shape.isClosed())


if __name__ == "__main__":
    unittest.main()
