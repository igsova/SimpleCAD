"""Analytic circles, profile booleans, native persistence and existing edits."""
import math
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

import FreeCAD as App
import Part
from pivy import coin
from simplecad.core import geometry as g
from simplecad.document import operations as op
from simplecad.gui.snapping import ray


class CircleGeometryTests(unittest.TestCase):
    def test_empty_orthographic_view_still_intersects_drawing_plane(self):
        camera = coin.SoOrthographicCamera()
        rotation = App.Rotation(g.V(1, 1, 0), g.V(-1, 1, 2), g.V(1, -1, 1), "ZXY")
        camera.orientation.setValue(rotation.Q)
        camera.position.setValue(tuple(rotation.multVec(g.V(0, 0, 100))))
        camera.height = 100
        camera.nearDistance = 100
        camera.farDistance = 100.0000001  # Indistinguishable in Coin's floats.
        view = SimpleNamespace(getSize=lambda: (800, 600), getCameraNode=lambda: camera,
                               getViewDirection=lambda: rotation.multVec(g.V(0, 0, -1)))
        origin, direction = ray(view, (400, 300))
        for name in ("XY", "XZ", "YZ"):
            point = g.Plane.named(name).intersect(origin, direction)
            self.assertLess(point.Length, 1e-4)

    def test_exact_circle_on_each_plane(self):
        for name in ("XY", "XZ", "YZ"):
            plane = g.Plane.named(name, g.V(20, -30, 40))
            for radius in (.1, 5, 100):
                with self.subTest(plane=name, radius=radius):
                    face = g.circle(plane, plane.origin, radius)
                    self.assertTrue(face.isValid())
                    self.assertEqual(len(face.Edges), 1)
                    self.assertIsInstance(face.Edges[0].Curve, Part.Circle)
                    self.assertAlmostEqual(face.Edges[0].Curve.Radius, radius)
                    self.assertAlmostEqual(face.Area, math.pi * radius ** 2)
                    self.assertAlmostEqual(face.Length, math.tau * radius)
                    self.assertLess((face.CenterOfMass - plane.origin).Length, 1e-7)
                    self.assertGreater(g.face_normal(face).dot(plane.normal), .999999)

    def test_oblique_circle_projects_center_and_preserves_normal(self):
        plane = g.Plane.from_normal(g.V(30, 40, 50), g.V(-1, 2, -3))
        center = plane.origin + plane.u * 7 + plane.v * 3
        face = g.circle(plane, center + plane.normal * 9, 12)
        self.assertLess((face.CenterOfMass - center).Length, 1e-7)
        self.assertGreater(g.face_normal(face).dot(plane.normal), .999999)
        for point in face.Edges[0].discretize(17):
            self.assertAlmostEqual((point - center).Length, 12)
            self.assertAlmostEqual((point - center).dot(plane.normal), 0)

    def test_invalid_radii(self):
        for radius in (0, -1, 1e-10, math.nan, math.inf, -math.inf):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                g.circle(g.Plane.named(), g.V(), radius)

    def test_standalone_circle_pulls_into_cylinder_both_directions(self):
        plane = g.Plane.from_normal(g.V(20, 30, 40), g.V(1, -2, 3))
        face = g.circle(plane, plane.origin, 5)
        for distance in (7, -7):
            solid = g.push_pull(face, face, distance)
            self.assertTrue(solid.isValid())
            self.assertEqual(len(solid.Solids), 1)
            self.assertEqual(len(solid.Faces), 3)
            self.assertAlmostEqual(solid.Volume, math.pi * 25 * 7)
            self.assertLess((solid.CenterOfMass - (plane.origin + plane.normal * distance / 2)).Length, 1e-6)

    def test_boss_pocket_and_through_hole_on_every_box_face(self):
        box = Part.makeBox(20, 20, 20)
        box.Placement = App.Placement(g.V(20, 40, 60), App.Rotation(g.V(1, 2, 3), 37))
        for support in box.Faces:
            plane = g.Plane.from_face(support)
            profile = g.circle(plane, support.CenterOfMass, 3)
            for distance, depth in ((4, 4), (-4, -4), (-20, -20)):
                result = g.push_pull(box, profile, distance, supported=True)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                self.assertAlmostEqual(result.Volume, 8000 + math.pi * 9 * depth, places=5)

    def test_circle_can_be_divided_and_semicircle_pulled(self):
        face = g.circle(g.Plane.named(), g.V(), 10)
        result = g.divide_face_with_line(face, g.V(-10, 0, 0), g.V(10, 0, 0))
        self.assertEqual(len(result.Faces), 2)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Area, face.Area)
        for half in result.Faces:
            self.assertAlmostEqual(half.Area, face.Area / 2)
            solid, rest = g.plan_push_pull(result, half, 3)
            self.assertAlmostEqual(solid.Volume, face.Area * 1.5)
            self.assertAlmostEqual(rest.Area, face.Area / 2)


class CircleDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADCircleTest")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def profile(self):
        box = op.new_shape(self.doc, Part.makeBox(20, 20, 20), "Block")
        center = g.V(10, 10, 20)
        profile = op.new_shape(self.doc, g.circle(g.Plane.named("XY", center), center, 3), "Circle", box)
        return box, profile

    def test_create_undo_redo(self):
        obj = op.new_shape(self.doc, g.circle(g.Plane.named(), g.V(), 5), "Circle")
        name = obj.Name
        self.assertEqual(self.doc.UndoCount, 1)
        self.doc.undo()
        self.assertFalse(self.doc.Objects)
        self.doc.redo()
        obj = self.doc.getObject(name)
        self.assertIsInstance(obj.Shape.Edges[0].Curve, Part.Circle)
        self.assertAlmostEqual(obj.Shape.Area, math.pi * 25)

    def test_profile_consumed_and_restored_in_one_undo(self):
        box, profile = self.profile()
        name = profile.Name
        count = self.doc.UndoCount
        op.extrude(profile, profile.Shape, -4)
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(box.Shape.Volume, 8000 - math.pi * 36)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(self.doc.getObject(name).SC_Support, box)
        self.assertAlmostEqual(box.Shape.Volume, 8000)
        self.doc.redo()
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(box.Shape.Volume, 8000 - math.pi * 36)

    def test_partial_support_rejected_without_changes(self):
        box = op.new_shape(self.doc, Part.makeBox(20, 20, 20), "Block")
        center = g.V(19, 10, 20)
        count = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.new_shape(self.doc, g.circle(g.Plane.named("XY", center), center, 3), "Circle", box)
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertAlmostEqual(box.Shape.Volume, 8000)

    def test_redrawing_circle_reuses_profile(self):
        box, profile = self.profile()
        count = self.doc.UndoCount
        same = op.new_shape(self.doc, profile.Shape.copy(), "Circle", box)
        self.assertEqual(same, profile)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertEqual(self.doc.UndoCount, count)

    def test_copy_is_independent_and_detaches_support(self):
        box, profile = self.profile()
        copy = op.transform([profile], g.V(30, 0, 0), copy=True)[0]
        self.assertNotIn("SC_Support", copy.PropertiesList)
        self.assertAlmostEqual(copy.Shape.Edges[0].Curve.Radius, 3)
        self.assertLess((copy.Shape.CenterOfMass - profile.Shape.CenterOfMass - g.V(30, 0, 0)).Length, 1e-7)
        op.extrude(copy, copy.Shape, 4)
        self.assertAlmostEqual(copy.Shape.Volume, math.pi * 36)
        self.assertAlmostEqual(box.Shape.Volume, 8000)
        self.assertEqual(profile.Shape.ShapeType, "Face")

    def test_save_reopen_native_circle_and_support(self):
        box, profile = self.profile()
        names = box.Name, profile.Name
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "circle.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            box, profile = [self.doc.getObject(name) for name in names]
            self.assertEqual(profile.TypeId, "Part::Feature")
            self.assertNotIn("Proxy", profile.PropertiesList)
            self.assertEqual(profile.SC_Support, box)
            self.assertIsInstance(profile.Shape.Edges[0].Curve, Part.Circle)
            op.extrude(profile, profile.Shape, 4)
            self.assertAlmostEqual(box.Shape.Volume, 8000 + math.pi * 36)


if __name__ == "__main__":
    unittest.main()
