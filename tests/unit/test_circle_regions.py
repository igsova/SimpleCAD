"""Circles must partition the host, with native selection and hole deletion."""
import math
import tempfile
from pathlib import Path
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op

V = App.Vector


def disk(face, radius=3, center=None):
    return g.circle(g.Plane.from_face(face), center or face.CenterOfMass, radius)


def region_name(shape, profile, kind="Face"):
    return next(kind + str(i + 1) for i, part in enumerate(getattr(shape, kind + "s"))
                if coinc.same(part, profile))


class CircleRegionGeometryTests(unittest.TestCase):
    def test_all_solid_faces_partition_and_pull_both_directions(self):
        box = Part.makeBox(40, 30, 20)
        box.Placement = App.Placement(V(20, 30, 40), App.Rotation(V(1, 2, 3), 37))
        for face in box.Faces:
            profile = disk(face)
            result = g.divide_face_with_profile(box, profile)
            self.assertTrue(result.isValid())
            self.assertEqual(len(result.Faces), 7)
            self.assertAlmostEqual(result.Area, box.Area)
            self.assertAlmostEqual(result.Volume, box.Volume)
            region = result.getElement(region_name(result, profile))
            self.assertEqual(len(region.Edges), 1)
            self.assertIsInstance(region.Edges[0].Curve, Part.Circle)
            for distance in (-2, 2):
                pulled = g.push_pull(result, region, distance)
                self.assertAlmostEqual(pulled.Volume, box.Volume + math.pi * 9 * distance, places=5)

    def test_open_rectangular_triangular_and_reversed_faces(self):
        triangle = Part.Face(Part.makePolygon([V(), V(40, 0, 0), V(0, 30, 0), V()]))
        for face in (Part.makePlane(40, 30), triangle):
            for reverse in (False, True):
                base = face.copy()
                if reverse:
                    base.reverse()
                profile = disk(base)
                result = g.divide_face_with_profile(base, profile)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Faces), 2)
                self.assertAlmostEqual(result.Area, base.Area)
                self.assertAlmostEqual(result.Faces[0].common(result.Faces[1]).Area, 0)
                for part in result.Faces:
                    self.assertGreater(g.face_normal(part).dot(g.face_normal(base)), .99999)
                region = result.getElement(region_name(result, profile))
                for distance in (-4, 4):
                    solid, rest = g.plan_push_pull(result, region, distance)
                    self.assertAlmostEqual(solid.Volume, math.pi * 36)
                    self.assertAlmostEqual(rest.Area, base.Area - profile.Area)

    def test_open_shell_and_unsewn_faces_keep_neighbors(self):
        faces = Part.makeBox(40, 30, 20).Faces[1:]
        profile = disk(faces[-1])
        for base in (Part.makeShell(faces), Part.makeCompound(faces)):
            result = g.divide_face_with_profile(base, profile)
            self.assertTrue(result.isValid())
            self.assertEqual(len(result.Faces), len(faces) + 1)
            self.assertAlmostEqual(result.Area, base.Area)
            for face in faces[:-1]:
                self.assertTrue(any(coinc.same(face, part) for part in result.Faces))

    def test_delete_disk_leaves_a_real_hole_in_sheet_and_solid(self):
        for base in (Part.makePlane(40, 30), Part.makeBox(40, 30, 20)):
            face = base.Faces[-1]
            profile = disk(face)
            result = g.divide_face_with_profile(base, profile)
            opened = g.erase_elements(result, [region_name(result, profile)])
            self.assertTrue(opened.isValid())
            self.assertFalse(opened.Solids)
            self.assertAlmostEqual(opened.Area, base.Area - profile.Area)
            self.assertTrue(all(part.distToShape(Part.Vertex(profile.CenterOfMass))[0] > 1
                                for part in opened.Faces))
            remainder = next(part for part in opened.Faces if g.coplanar(face, part))
            self.assertEqual(len(remainder.Wires), 2)

    def test_delete_circle_edge_merges_regions_without_area_loss(self):
        for base in (Part.makePlane(40, 30), Part.makeBox(40, 30, 20)):
            profile = disk(base.Faces[-1])
            result = g.divide_face_with_profile(base, profile)
            merged = g.erase_elements(result, [region_name(result, profile.Edges[0], "Edge")])
            self.assertTrue(merged.isValid())
            self.assertEqual(len(merged.Faces), len(base.Faces))
            self.assertAlmostEqual(merged.Area, base.Area)
            if base.Solids:
                self.assertAlmostEqual(merged.Volume, base.Volume)

    def test_prior_divisions_and_loose_edges_survive(self):
        base = Part.makeBox(40, 30, 20)
        base = g.divide_face_with_line(base, V(20, 0, 20), V(20, 30, 20))
        profile = g.circle(g.Plane.named("XY", V(0, 0, 20)), V(10, 15, 20), 3)
        loose = Part.makeLine(V(2, 2, 20), V(4, 4, 20))
        result = g.divide_face_with_profile(Part.makeCompound([base, loose]), profile)
        self.assertEqual(len(result.Faces), 8)
        self.assertEqual(len(result.Solids), 1)
        self.assertTrue(any(coinc.same(edge, loose) for edge in coinc.loose_edges(result)))
        self.assertAlmostEqual(result.Volume, base.Volume)

    def test_existing_holes_and_repeated_circle(self):
        face = Part.makePlane(40, 30)
        hole = disk(face, center=V(10, 15, 0))
        base = face.cut(hole).Faces[0]
        profile = disk(face, center=V(30, 15, 0))
        result = g.divide_face_with_profile(base, profile)
        self.assertEqual(len(result.Faces), 2)
        self.assertAlmostEqual(result.Area, base.Area)
        self.assertIsNone(g.divide_face_with_profile(result, profile))
        with self.assertRaises(ValueError):
            g.divide_face_with_profile(base, hole)


class CircleRegionDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADCircleRegions")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def source(self, solid=False):
        return op.new_shape(self.doc, Part.makeBox(40, 30, 20) if solid else Part.makePlane(40, 30), "Host")

    def test_draw_updates_original_object_and_undo_redo(self):
        obj = self.source()
        profile = disk(obj.Shape)
        count = self.doc.UndoCount
        result, changed = op.draw_circle(self.doc, profile, obj)
        self.assertEqual(result, obj)
        self.assertTrue(changed)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(obj.Shape.Faces), 2)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(len(obj.Shape.Faces), 1)
        self.doc.redo()
        self.assertEqual(len(obj.Shape.Faces), 2)
        count = self.doc.UndoCount
        self.assertEqual(op.draw_circle(self.doc, profile), (obj, True))
        self.assertEqual(self.doc.UndoCount, count)

    def test_retrace_repairs_legacy_disks_and_edges_atomically(self):
        for solid in (False, True):
            with self.subTest(solid=solid):
                obj = self.source(solid)
                profile = disk(obj.Shape.Faces[-1])
                legacy = op.new_shape(self.doc, profile, "Old Circle", obj if solid else None)
                edge = op.new_shape(self.doc, profile.Edges[0], "Old circle edge")
                names = legacy.Name, edge.Name
                count = self.doc.UndoCount
                result, changed = op.draw_circle(self.doc, profile, legacy)
                self.assertEqual(result, obj)
                self.assertTrue(changed)
                self.assertTrue(all(self.doc.getObject(name) is None for name in names))
                self.assertEqual(self.doc.UndoCount, count + 1)
                self.doc.undo()
                self.assertTrue(all(self.doc.getObject(name) is not None for name in names))
                if solid:
                    self.assertEqual(self.doc.getObject(names[0]).SC_Support, obj)
                # Reset only this test's fixtures before testing the other host.
                for other in list(self.doc.Objects):
                    self.doc.removeObject(other.Name)

    def test_rendered_tilted_circle_still_matches_fresh_geometry(self):
        face = Part.makePlane(40, 30)
        face.Placement = App.Placement(V(10, 20, 30), App.Rotation(V(1, 2, 0), 24))
        obj = op.new_shape(self.doc, face, "Tilted sheet")
        old = op.new_shape(self.doc, disk(face, 4), "Old Circle")
        shown = old.Shape
        shown.tessellate(.5)
        profile = disk(face, 4)
        self.assertTrue(coinc.same(shown, profile))
        self.assertTrue(coinc.same(shown.Edges[0], profile.Edges[0]))
        old.Shape = shown
        result, changed = op.draw_circle(self.doc, profile, old)
        self.assertEqual(result, obj)
        self.assertTrue(changed)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(obj.Shape.Faces), 2)
        self.assertAlmostEqual(obj.Shape.Area, face.Area)

    def test_legacy_dependency_blocks_before_changing_host(self):
        obj = self.source()
        profile = disk(obj.Shape)
        legacy = op.new_shape(self.doc, profile, "Old Circle")
        dependent = self.doc.addObject("App::FeaturePython", "Dependent")
        dependent.addProperty("App::PropertyLink", "Source")
        dependent.Source = legacy
        count = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.draw_circle(self.doc, profile, legacy)
        self.assertEqual(len(obj.Shape.Faces), 1)
        self.assertEqual(dependent.Source, legacy)
        self.assertEqual(self.doc.UndoCount, count)

    def test_partial_circle_on_picked_face_fails_without_overlay(self):
        obj = self.source()
        profile = disk(obj.Shape, center=V(39, 15, 0))
        count = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.draw_circle(self.doc, profile, obj)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(obj.Shape.Faces), 1)
        self.assertEqual(self.doc.UndoCount, count)

    def test_free_circle_remains_native_disk(self):
        profile = g.circle(g.Plane.named(), V(), 3)
        obj, changed = op.draw_circle(self.doc, profile)
        self.assertFalse(changed)
        self.assertEqual(obj.Shape.ShapeType, "Face")
        self.assertNotIn("SC_Support", obj.PropertiesList)
        self.assertEqual(op.draw_circle(self.doc, profile), (obj, False))
        self.assertEqual(self.doc.UndoCount, 1)

    def test_region_delete_and_undo_preserve_surrounding_face(self):
        obj = self.source()
        profile = disk(obj.Shape)
        op.draw_circle(self.doc, profile, obj)
        op.delete_selection([(obj, [region_name(obj.Shape, profile)])])
        self.assertEqual(len(obj.Shape.Faces), 1)
        self.assertAlmostEqual(obj.Shape.Area, 1200 - math.pi * 9)
        self.doc.undo()
        self.assertEqual(len(obj.Shape.Faces), 2)
        self.assertAlmostEqual(obj.Shape.Area, 1200)

    def test_save_reopen_regions_without_custom_support_link(self):
        obj = self.source()
        profile = disk(obj.Shape)
        op.draw_circle(self.doc, profile, obj)
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "regions.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.assertEqual(len(self.doc.Objects), 1)
            obj = self.doc.Objects[0]
            self.assertEqual(len(obj.Shape.Faces), 2)
            self.assertNotIn("SC_Support", obj.PropertiesList)
            op.delete_selection([(obj, [region_name(obj.Shape, profile)])])
            self.assertEqual(len(obj.Shape.Wires), 2)


if __name__ == "__main__":
    unittest.main()
