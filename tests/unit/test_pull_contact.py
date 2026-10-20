"""Exact opposing-face contact for Push/Pull, using native OCC topology."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
from simplecad.gui.snapping import pull_drag, snap_pull
from test_line_axes import Camera

V = App.Vector


class PullContactTests(unittest.TestCase):
    def test_pull_contact_projects_and_imprints_micron_drift(self):
        face = Part.Face(Part.makePolygon([
            V(0, 0, 0), V(40, 0, 0), V(40, 40, 0), V(0, 40, 0), V(0, 0, 0)
        ]))
        # The source edge is 0.004 mm off the plane and ends 0.003 mm beyond
        # the perimeter, matching the fitted/imported Pull contact drift.
        edge = Part.makeLine(V(20, -0.003, 0.004), V(20, 40.003, -0.004))
        projected = g.project_pull_edge(edge, face)
        self.assertIsNotNone(projected)
        self.assertAlmostEqual(projected.Vertexes[0].Point.z, 0, places=9)
        self.assertAlmostEqual(projected.Vertexes[1].Point.z, 0, places=9)
        self.assertAlmostEqual(projected.Vertexes[0].Point.y, 0, places=9)
        self.assertAlmostEqual(projected.Vertexes[1].Point.y, 40, places=9)
        result = g.imprint_pull_edges(face, Part.makeCompound([edge]))
        self.assertEqual(len(result.Faces), 2)
        self.assertAlmostEqual(result.Area, face.Area)

    def test_pull_contact_does_not_project_real_gap(self):
        face = Part.Face(Part.makePolygon([
            V(0, 0, 0), V(40, 0, 0), V(40, 40, 0), V(0, 40, 0), V(0, 0, 0)
        ]))
        edge = Part.makeLine(V(20, 0, 0.006), V(20, 40, 0.006))
        self.assertIsNone(g.project_pull_edge(edge, face))

    def test_parallel_exit_on_all_rotated_box_faces(self):
        box = Part.makeBox(40, 40, 20)
        box.Placement = App.Placement(V(70, -30, 11), App.Rotation(V(1, 2, 3), 37))
        for index, face in enumerate(box.Faces):
            with self.subTest(index=index):
                circle = g.circle(g.Plane.from_face(face), face.CenterOfMass, 3)
                stop = g.opposite_face(box, circle)
                self.assertIsNotNone(stop)
                self.assertAlmostEqual(stop.distance, -40 if index < 4 else -20)

    def test_divided_opposite_face_still_accepts_full_circle(self):
        box = Part.makeBox(40, 40, 20)
        box = g.divide_face_with_line(box, V(0, 0, 0), V(40, 40, 0))
        circle = g.circle(g.Plane.named("XY", V(20, 20, 20)), V(20, 20, 20), 5)
        stop = g.opposite_face(box, circle)
        self.assertAlmostEqual(stop.distance, -20)
        self.assertEqual(len(stop.faces), 2)

    def test_cap_of_boss_reaches_opposite_face_through_both_boss_and_block(self):
        shape = Part.makeBox(40, 40, 20).fuse(Part.makeCylinder(5, 12, V(20, 20, 20)))
        cap = max(shape.Faces, key=lambda face: face.CenterOfMass.z)
        self.assertAlmostEqual(g.opposite_face(shape, cap).distance, -32)

    def test_partial_footprint_and_open_surface_do_not_offer_a_stop(self):
        shape = Part.makeBox(40, 40, 20).cut(Part.makeBox(10, 40, 10, V(0, 0, 0)))
        circle = g.circle(g.Plane.named("XY", V(10, 20, 20)), V(10, 20, 20), 5)
        self.assertIsNone(g.opposite_face(shape, circle))
        self.assertIsNone(g.opposite_face(Part.makeShell(shape.Faces[:-1]), circle))

    def test_existing_tunnel_does_not_offer_far_face_or_bridge_a_void(self):
        box = Part.makeBox(40, 40, 20).cut(Part.makeCylinder(2, 20, V(20, 20, 0)))
        circle = g.circle(g.Plane.named("XY", V(20, 20, 20)), V(20, 20, 20), 5)
        self.assertIsNone(g.opposite_face(box, circle))


class ThroughSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.box = Part.makeBox(40, 40, 20)
        self.profile = g.circle(g.Plane.named("XY", V(20, 20, 20)), V(20, 20, 20), 5)

    def cap(self, shape, expected):
        return next(face for face in shape.Faces if coinc.same(face, expected))

    def test_short_exact_and_beyond_have_distinct_topology(self):
        for distance in (-10, -20, -30):
            with self.subTest(distance=distance):
                result = g.push_pull(self.box, self.profile, distance, True)
                self.assertTrue(result.isValid())
                if distance >= -20:
                    self.assertEqual(len(result.Solids), 1)
                    self.assertAlmostEqual(result.Volume, self.box.Volume + self.profile.Area * distance)
                else:
                    self.assertFalse(result.Solids)
                    far_face = self.box.Faces[4]
                    self.assertTrue(any(coinc.same(face, far_face) for face in result.Faces))
                    moved = self.profile.copy(); moved.translate(V(0, 0, distance))
                    self.cap(result, moved)
                    self.assertAlmostEqual(result.BoundBox.ZMin, -10)
        self.assertEqual(len(self.box.Faces), 6)

    def test_beyond_all_rotated_faces_preserves_entire_opposite_surface(self):
        self.box.Placement = App.Placement(V(30, 40, -20), App.Rotation(V(1, 2, 3), 37))
        for face in self.box.Faces:
            normal = g.face_normal(face)
            profile = g.circle(g.Plane.from_face(face), face.CenterOfMass, 3)
            stop = g.opposite_face(self.box, profile)
            result = g.push_pull(self.box, profile, stop.distance - 7, True)
            self.assertFalse(result.Solids)
            self.assertTrue(result.isValid())
            for far in stop.faces:
                self.assertTrue(any(coinc.same(far, current) for current in result.Faces))
            moved = profile.copy(); moved.translate(normal * (stop.distance - 7))
            cap = self.cap(result, moved)
            hole, rest = g.plan_push_pull(result, cap, 7)
            self.assertIsNone(rest)
            self.assertEqual(len(hole.Solids), 1)
            self.assertAlmostEqual(hole.Volume, self.box.Volume + stop.distance * profile.Area, places=5)

    def test_rectangular_triangular_and_reversed_profiles_continue_past_face(self):
        p = g.Plane.named("XY", V(0, 0, 20))
        rectangle = g.rectangle(p, V(10, 10, 20), V(20, 25, 20))
        triangle = Part.Face(Part.makePolygon([V(10, 10, 20), V(25, 10, 20), V(10, 25, 20), V(10, 10, 20)]))
        reversed_profile = self.profile.copy(); reversed_profile.reverse()
        for profile in (rectangle, triangle, reversed_profile):
            result = g.push_pull(self.box, profile, -30, True)
            self.assertFalse(result.Solids)
            self.assertTrue(result.isValid())
            moved = profile.copy(); moved.translate(V(0, 0, -30))
            cap = self.cap(result, moved)
            hole, rest = g.plan_push_pull(result, cap, 10)
            self.assertIsNone(rest)
            self.assertAlmostEqual(hole.Volume, self.box.Volume - profile.Area * 20, places=5)

    def test_extended_cap_can_grow_return_to_hole_pocket_original_or_boss(self):
        extended = g.push_pull(self.box, self.profile, -30, True)
        moved = self.profile.copy(); moved.translate(V(0, 0, -30))
        cap = self.cap(extended, moved)
        for travel, depth in ((-5, -35), (10, -20), (15, -15), (30, 0), (35, 5)):
            result, rest = g.plan_push_pull(extended, cap, travel)
            self.assertIsNone(rest)
            self.assertTrue(result.isValid())
            if depth < -20:
                self.assertFalse(result.Solids)
                self.assertAlmostEqual(result.BoundBox.ZMin, 20 + depth)
            else:
                self.assertEqual(len(result.Solids), 1)
                self.assertAlmostEqual(result.Volume, self.box.Volume + self.profile.Area * depth, places=5)
        with self.assertRaises(ValueError):
            g.plan_push_pull(extended, cap, 0)

    def test_cylinder_boss_can_push_through_and_then_return_to_a_hole(self):
        boss = g.push_pull(self.box, self.profile, 12, True)
        cap = max(boss.Faces, key=lambda face: face.CenterOfMass.z)
        extended, _ = g.plan_push_pull(boss, cap, -42)
        self.assertAlmostEqual(extended.BoundBox.ZMin, -10)
        self.assertAlmostEqual(extended.BoundBox.ZMax, 20)
        cap = next(face for face in extended.Faces if abs(face.CenterOfMass.z + 10) < 1e-7)
        hole, _ = g.plan_push_pull(extended, cap, 10)
        self.assertAlmostEqual(hole.Volume, self.box.Volume - self.profile.Area * 20)

    def test_whole_prism_can_continue_on_other_side_but_zero_thickness_is_rejected(self):
        face = self.box.Faces[-1]
        result = g.push_pull(self.box, face, -25)
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.BoundBox.ZMin, -5)
        self.assertAlmostEqual(result.BoundBox.ZMax, 0)
        with self.assertRaises(ValueError):
            g.push_pull(self.box, face, -20)

    def test_divisions_and_loose_edges_survive_extension_and_return(self):
        box = g.divide_face_with_line(self.box, V(0, 0, 0), V(40, 40, 0))
        divided = g.divide_face_with_profile(box, self.profile)
        line = Part.makeLine(V(50, 0, 0), V(50, 10, 0))
        shape = Part.makeCompound([divided, line])
        face = self.cap(shape, self.profile)
        extended, rest = g.plan_push_pull(shape, face, -30)
        self.assertTrue(coinc.same(rest, line))
        self.assertEqual(len([f for f in extended.Faces if abs(f.CenterOfMass.z) < 1e-7]), 2)


class PullDistanceTests(unittest.TestCase):
    def test_native_ray_distance_and_snap_release_in_both_camera_types(self):
        anchor, normal = V(13, 27, 9), V(0, 0, 1)
        for perspective in (False, True):
            camera = Camera(perspective=perspective)
            down = camera.getPointOnScreen(anchor)
            with patch("simplecad.gui.snapping.ray", side_effect=camera.ray):
                for depth in (-60, -20, 30):
                    pos = camera.getPointOnScreen(anchor + normal * depth)
                    distance, scale = pull_drag(camera, pos, anchor, normal, down, 10)
                    self.assertAlmostEqual(distance, depth, places=5)
                    captured = snap_pull(camera, distance, -20, anchor, normal, scale, 12)
                    self.assertAlmostEqual(captured, depth, places=5)
                self.assertEqual(snap_pull(camera, -19, -20, anchor, normal, None, 12), -20)

    def test_face_on_drag_uses_vertical_motion_and_releases_snap(self):
        camera = Camera(top=True)
        anchor, normal = V(), V(0, 0, 1)
        down = camera.getPointOnScreen(anchor)
        with patch("simplecad.gui.snapping.ray", side_effect=camera.ray):
            distance, scale = pull_drag(camera, (down[0], down[1] - 152), anchor, normal, down, 10)
            self.assertAlmostEqual(distance, -19)
            self.assertEqual(snap_pull(camera, distance, -20, anchor, normal, scale, 12), -20)
            self.assertEqual(snap_pull(camera, -24, -20, anchor, normal, scale, 12), -24)


class ThroughSurfaceDocumentTests(unittest.TestCase):
    def test_native_save_reopen_move_copy_and_undo_with_no_saved_history_proxy(self):
        doc = App.newDocument("SimpleCADThroughSurfaceTest")
        doc.UndoMode = 1
        try:
            obj = op.new_shape(doc, Part.makeBox(40, 40, 20), "Block")
            profile = g.circle(g.Plane.named("XY", V(20, 20, 20)), V(20, 20, 20), 5)
            op.draw_circle(doc, profile, obj)
            face = next(face for face in obj.Shape.Faces if coinc.same(face, profile))
            before = obj.Shape.copy(); count = doc.UndoCount
            op.extrude(obj, face, -30)
            self.assertEqual(doc.UndoCount, count + 1)
            self.assertEqual(len(doc.Objects), 1)
            self.assertFalse(obj.Shape.Solids)
            doc.undo(); self.assertAlmostEqual(obj.Shape.Volume, before.Volume)
            doc.redo(); self.assertFalse(obj.Shape.Solids)
            op.transform([obj], V(10, 20, 30))
            name = obj.Name
            with tempfile.TemporaryDirectory() as directory:
                filename = str(Path(directory) / "surface.FCStd")
                doc.saveAs(filename); App.closeDocument(doc.Name)
                doc = App.openDocument(filename)
                obj = doc.getObject(name)
                self.assertEqual(obj.TypeId, "Part::Feature")
                self.assertNotIn("Proxy", obj.PropertiesList)
                clone = op.transform([obj], V(50, 0, 0), copy=True)[0]
                for target in (obj, clone):
                    cap = next(face for face in target.Shape.Faces if abs(face.CenterOfMass.z - 20) < 1e-6)
                    stop = op.extrusion_contact(target, cap)
                    self.assertAlmostEqual(stop.distance, 10)
                    op.extrude(target, cap, stop.distance)
                    self.assertEqual(len(target.Shape.Solids), 1)
                    self.assertAlmostEqual(target.Shape.Volume, 32000 - profile.Area * 20)
        finally:
            App.closeDocument(doc.Name)
