"""Run with FreeCAD's bundled Python, or from the supplied test macro."""
import math
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op


class GeometryTests(unittest.TestCase):
    def test_rectangle_all_planes_and_quadrants(self):
        for name in ("XY", "XZ", "YZ"):
            plane = g.Plane.named(name)
            for a, b in ((10, 20), (-10, 20), (10, -20), (-10, -20)):
                face = g.rectangle(plane, g.V(), plane.u * a + plane.v * b)
                self.assertAlmostEqual(face.Area, 200)
                self.assertGreater(g.face_normal(face).dot(plane.normal), .999)
                self.assertAlmostEqual(g.push_pull(face, face, 5).Volume, 1000)

    def test_oblique_rectangle(self):
        p = g.Plane.from_normal(g.V(4, 5, 6), g.V(1, 2, 3))
        face = g.rectangle(p, p.origin, p.origin + p.u * 20 + p.v * 10)
        self.assertAlmostEqual(face.Area, 200)
        self.assertAlmostEqual(g.push_pull(face, face, -3).Volume, 600)

    def test_push_pull_every_box_face(self):
        box = Part.makeBox(10, 10, 10)
        for face in box.Faces:
            self.assertAlmostEqual(g.push_pull(box, face, 3).Volume, 1300)
            self.assertAlmostEqual(g.push_pull(box, face, -3).Volume, 700)

    def test_pocket_boss_and_through_hole(self):
        box = Part.makeBox(10, 10, 10)
        p = g.Plane.named("XY", g.V(0, 0, 10))
        face = g.rectangle(p, g.V(2, 2, 10), g.V(6, 6, 10))
        for distance, volume in ((2, 1032), (-2, 968), (-10, 840)):
            self.assertAlmostEqual(g.push_pull(box, face, distance, True).Volume, volume)

    def test_reject_partial_support(self):
        box = Part.makeBox(10, 10, 10)
        face = g.rectangle(g.Plane.named(), g.V(9, 9, 0), g.V(12, 12, 0))
        with self.assertRaises(ValueError):
            g.push_pull(box, face, 5, True)

    def test_reject_empty_result(self):
        box = Part.makeBox(10, 10, 10)
        with self.assertRaises(ValueError):
            g.push_pull(box, box.Faces[-1], -10)

    def test_reject_curved_face(self):
        face = max(Part.makeCylinder(5, 10).Faces, key=lambda f: f.Area)
        with self.assertRaises(ValueError):
            g.face_normal(face)

    def test_degenerate_inputs(self):
        for a, b in ((g.V(), g.V()), (g.V(), g.V(10, 0, 0))):
            with self.assertRaises(ValueError):
                g.rectangle(g.Plane.named(), a, b)
        with self.assertRaises(ValueError):
            g.line(g.V(), g.V())

    def test_units(self):
        self.assertEqual(g.parse_length("25"), 25)
        self.assertEqual(g.parse_length("-2 cm"), -20)
        self.assertAlmostEqual(g.parse_length("1 in"), 25.4)
        with self.assertRaises(ValueError):
            g.parse_length("30 deg")

    def test_volume_cache_answers_only_for_the_identical_shape(self):
        box = Part.makeBox(1, 2, 3)

        def planted(shape):
            # A planted value shows when the cache answers instead of measuring.
            g._volumes[:] = [(Part.Shape(box), 7.0)]
            return g.volume(shape)

        self.assertEqual(planted(box), 7.0)
        self.assertEqual(planted(Part.Shape(box)), 7.0)  # another wrapper, as obj.Shape returns
        self.assertAlmostEqual(planted(box.reversed()), -6)  # isSame, but not isEqual
        self.assertAlmostEqual(planted(box.copy()), 6)
        moved = Part.Shape(box)
        moved.Placement = App.Placement(g.V(5, 0, 0), App.Rotation())
        self.assertAlmostEqual(planted(moved), 6)

    def test_volume_cache_keys_do_not_follow_later_edits_of_the_measured_wrapper(self):
        scale = App.Matrix()
        scale.scale(2, 1, 1)
        edits = (lambda s: s.reverse(), lambda s: s.complement(), lambda s: s.scale(2),
                 lambda s: s.transformShape(scale), lambda s: s.translate(g.V(1, 0, 0)),
                 lambda s: s.rotate(g.V(), g.V(0, 0, 1), 30))
        for edit in edits:
            g._volumes.clear()
            shape = Part.makeBox(1, 2, 3)
            g.volume(shape)
            edit(shape)
            self.assertEqual(g.volume(shape), shape.Volume)
        for height in range(1, 6):
            g.volume(Part.makeBox(1, 1, height))
        self.assertEqual(len(g._volumes), 4)

    def test_tolerance_changes_through_shared_faces_keep_a_measured_volume(self):
        spline = Part.BSplineSurface()
        spline.interpolate([[g.V(x, y, .1 * x * x + .065 * y * y) for y in (0, 5, 10, 15)] for x in (0, 5, 10, 15)])
        solid = spline.toShape().extrude(g.V(0, 0, -5))
        g._volumes.clear()
        value = g.volume(solid)
        Part.Shell(solid.Faces).fixTolerance(1e-3)
        self.assertEqual(solid.Vertexes[0].Tolerance, 1e-3)  # the edit reached the measured solid
        self.assertEqual(solid.Volume, value)
        self.assertEqual(g.volume(solid), value)

    def test_ray_plane(self):
        plane = g.Plane.named()
        self.assertLess(plane.intersect(g.V(1, 2, 10), g.V(0, 0, -1)).distanceToPoint(g.V(1, 2, 0)), 1e-7)
        with self.assertRaises(ValueError):
            plane.intersect(g.V(), g.V(1, 0, 0))


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADKernelTest")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self):
        return op.new_shape(self.doc, Part.makeBox(10, 10, 10), "Test box")

    def test_create_undo_redo(self):
        self.box()
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 0)
        self.doc.redo()
        self.assertEqual(len(self.doc.Objects), 1)

    def test_push_pull_undo(self):
        box = self.box()
        op.extrude(box, box.Shape.Faces[0], 5)
        self.assertAlmostEqual(box.Shape.Volume, 1500)
        self.doc.undo()
        self.assertAlmostEqual(box.Shape.Volume, 1000)

    def test_a_stored_result_reuses_its_measured_volume_until_it_changes(self):
        box = self.box()
        result = Part.makeBox(10, 10, 12)
        g.validate(result, solid=True)
        box.Shape = result
        g._volumes[0] = (g._volumes[0][0], 7.0)
        self.assertEqual(g.volume(box.Shape), 7.0)
        box.Placement = App.Placement(g.V(5, 0, 0), App.Rotation())
        self.assertAlmostEqual(g.volume(box.Shape), 1200)
        op.extrude(box, box.Shape.Faces[0], 5)
        self.assertAlmostEqual(g.volume(box.Shape), 1800)
        self.doc.undo()
        self.assertEqual(g.volume(box.Shape), box.Shape.Volume)

    def test_failed_operation_no_change(self):
        box = self.box()
        undo_count = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.extrude(box, box.Shape.Faces[0], -10)
        self.assertEqual(self.doc.UndoCount, undo_count)
        self.assertAlmostEqual(box.Shape.Volume, 1000)

    def test_move_copy_and_delete_undo(self):
        box = self.box()
        op.transform([box], g.V(20, 0, 0))
        self.assertAlmostEqual(box.Shape.BoundBox.XMin, 20)
        clone = op.transform([box], g.V(0, 30, 0), copy=True)[0]
        self.assertAlmostEqual(clone.Shape.BoundBox.XMin, 20)
        self.assertAlmostEqual(clone.Shape.BoundBox.YMin, 30)
        self.assertAlmostEqual(box.Shape.BoundBox.YMin, 0)
        name = clone.Name
        op.delete([clone])
        self.assertIsNone(self.doc.getObject(name))
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(name))

    def test_rotated_translated_solid(self):
        box = self.box()
        box.Placement = App.Placement(g.V(40, 50, 60), App.Rotation(g.V(1, 2, 3), 37))
        before = box.Shape.copy()
        face = before.Faces[0]
        expected = g.push_pull(before, face, 5)
        op.extrude(box, face, 5)
        self.assertAlmostEqual(box.Shape.Volume, expected.Volume)
        self.assertLess((box.Shape.CenterOfMass - expected.CenterOfMass).Length, 1e-6)
        self.doc.undo()
        self.assertLess((box.Shape.CenterOfMass - before.CenterOfMass).Length, 1e-6)

    def test_profile_consumed_and_restored_by_undo(self):
        box = self.box()
        face = g.rectangle(g.Plane.named(), g.V(2, 2, 0), g.V(6, 6, 0))
        profile = op.new_shape(self.doc, face, "Profile", box)
        name = profile.Name
        op.extrude(profile, profile.Shape, 2)
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(box.Shape.Volume, 1032)
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(name))
        self.assertAlmostEqual(box.Shape.Volume, 1000)

    def test_moving_profile_detaches_support(self):
        box = self.box()
        profile = op.new_shape(self.doc, Part.makePlane(2, 2), "Profile", box)
        op.transform([profile], g.V(0, 0, 20))
        self.assertNotIn("SC_Support", profile.PropertiesList)
        self.doc.undo()
        self.assertEqual(profile.SC_Support, box)

    def test_parametric_feature_rejected(self):
        box = self.doc.addObject("Part::Box", "ParametricBox")
        self.doc.recompute()
        with self.assertRaises(ValueError):
            op.transform([box], g.V(1, 0, 0))

    def test_transformed_container_rejected(self):
        box = self.box()
        parent = self.doc.addObject("App::Part", "Container")
        parent.addObject(box)
        parent.Placement.Base = g.V(30, 40, 50)
        with self.assertRaises(ValueError):
            op.transform([box], g.V(1, 0, 0))

    def test_transaction_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with op.transaction(self.doc, "Fail intentionally"):
                self.doc.addObject("Part::Feature", "Partial")
                raise RuntimeError("test")
        self.assertEqual(len(self.doc.Objects), 0)

    def test_save_and_reopen_native_shapes(self):
        box = self.box()
        op.new_shape(self.doc, Part.makePlane(2, 2), "Profile", box)
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "test.FCStd")
            self.doc.saveAs(path)
            name = self.doc.Name
            App.closeDocument(name)
            self.doc = App.openDocument(path)
            self.assertEqual(len(self.doc.Objects), 2)
            self.assertAlmostEqual(self.doc.Objects[0].Shape.Volume, 1000)
            self.assertEqual(self.doc.Objects[1].SC_Support, self.doc.Objects[0])

    def test_push_pull_through_hole_nominal_snaps_opposite_face(self):
        """A nominal distance (e.g. -10 on a 9.996 height) snaps to opposite exit face for through hole."""
        # Box of height 9.996 (simulating faceted tolerance)
        box = Part.makeBox(20, 20, 9.996)
        p = g.Plane.named("XY", g.V(0, 0, 9.996))
        face = g.rectangle(p, g.V(5, 5, 9.996), g.V(15, 15, 9.996))
        # User types -10.0 (nominal 10 mm)
        result = g.push_pull(box, face, -10.0, supported=True)
        self.assertEqual(result.ShapeType, "Solid")
        self.assertEqual(len(result.Solids), 1)
        expected_vol = 20 * 20 * 9.996 - 10 * 10 * 9.996
        self.assertAlmostEqual(result.Volume, expected_vol, places=2)

    def test_push_pull_cut_heals_adjacent_coplanar_wire_discrepancies(self):
        """push_pull cut succeeds even when adjacent coplanar face has wire tolerance discrepancies."""
        box = Part.makeBox(30, 30, 10)
        cyl = Part.makeCylinder(4, 10, g.V(15, 15, 0))
        solid = box.cut(cyl).Solids[0]
        # Draw a face on the top plate outside the hole
        p = g.Plane.named("XY", g.V(0, 0, 10))
        tool_face = g.rectangle(p, g.V(20, 15, 10), g.V(28, 25, 10))
        res = g.push_pull(solid, tool_face, -10.0, supported=True)
        self.assertEqual(res.ShapeType, "Solid")
        self.assertEqual(len(res.Solids), 1)
        self.assertLess(res.Volume, solid.Volume)



    def test_erase_internal_edge_on_solid_face(self):
        """Deleting an internal edge removes only the edge without deleting the host face or solid."""
        box = Part.makeBox(20, 20, 10)
        top_f = [f for f in box.Faces if abs(f.CenterOfMass.z - 10.0) < 1e-4][0]
        edge = Part.makeLine(g.V(5, 5, 10), g.V(15, 15, 10))
        edge.Orientation = "Internal"
        w_open = Part.Wire([edge])
        new_f = Part.Face(top_f.Surface, [top_f.Wires[0], w_open])
        solid_with_edge = box.replaceShape([(top_f, new_f)])
        internal_edges = [e for f in solid_with_edge.Faces for e in f.Edges if e.Orientation == "Internal"]
        self.assertEqual(len(internal_edges), 1)
        edge_to_delete = internal_edges[0]
        edge_idx = [i for i, e in enumerate(solid_with_edge.Edges) if e.isSame(edge_to_delete)][0]
        res = g.erase_elements(solid_with_edge, [f"Edge{edge_idx+1}"])
        self.assertEqual(res.ShapeType, "Solid")
        self.assertEqual(len(res.Solids), 1)
        self.assertAlmostEqual(res.Volume, box.Volume, places=4)
        res_internal = [e for f in res.Faces for e in f.Edges if e.Orientation == "Internal"]
        self.assertEqual(len(res_internal), 0)

    def test_clean_solid_faces_removes_internal_edges(self):
        """clean_solid_faces automatically strips internal edges and open wires from solids."""
        box = Part.makeBox(20, 20, 10)
        top_f = [f for f in box.Faces if abs(f.CenterOfMass.z - 10.0) < 1e-4][0]
        edge = Part.makeLine(g.V(5, 5, 10), g.V(15, 15, 10))
        edge.Orientation = "Internal"
        w_open = Part.Wire([edge])
        new_f = Part.Face(top_f.Surface, [top_f.Wires[0], w_open])
        solid_with_edge = box.replaceShape([(top_f, new_f)])
        cleaned = g.clean_solid_faces(solid_with_edge)
        self.assertEqual(len(cleaned.Edges), len(box.Edges))
        self.assertEqual(len([e for f in cleaned.Faces for e in f.Edges if e.Orientation == "Internal"]), 0)

    def test_on_face_boundary_ignores_loose_edges_and_interiors(self):
        box = Part.makeBox(20, 20, 10)
        self.assertTrue(g.on_face_boundary(box, g.V(20, 7, 10)))  # on an edge
        self.assertTrue(g.on_face_boundary(box, g.V(20, 20, 10)))  # a corner
        self.assertFalse(g.on_face_boundary(box, g.V(10, 10, 10)))  # inside the top face
        self.assertFalse(g.on_face_boundary(box, g.V(20, 7, 10.01)))
        self.assertTrue(g.on_face_boundary(box, g.V(20, 7, 10.01), .1))
        loose = Part.makeCompound([box, Part.makeLine(g.V(30, 0, 0), g.V(40, 0, 0))])
        self.assertFalse(g.on_face_boundary(loose, g.V(35, 0, 0)))

    def notched_boss(self, short):
        """A hexagonal boss on a box with one side notched down to `short` above the box."""
        def region(shape, z, points):
            profile = Part.Face(Part.makePolygon([g.V(p.x, p.y, z) for p in points + points[:1]]))
            shape = g.divide_face_with_profile(shape, profile)
            face = next(f for f in shape.Faces if abs(f.CenterOfMass.z - z) < 1e-6 and abs(f.Area - profile.Area) < 1e-6)
            return shape, face
        def corners(radius):
            return [g.V(20 + radius * math.cos(math.radians(a)), 20 + radius * math.sin(math.radians(a)), 0)
                    for a in range(0, 360, 60)]
        outer, inner = corners(10), corners(7)
        shape, face = region(Part.makeBox(40, 40, 40), 40, outer)
        shape = g.push_pull(shape, face, 10)
        # As in a slotted tube: the notch takes a whole side, so no wall beside
        # it is coplanar with a step left at its foot.
        shape, face = region(shape, 50, [outer[4], outer[5], inner[5], inner[4]])
        return g.push_pull(shape, face, -(10 - short))

    def notch_volume(self, short=0):
        hexagon, notch = 1.5 * math.sqrt(3) * 100, math.sqrt(3) / 4 * (100 - 49)
        return 64000 + 10 * hexagon - (10 - short) * notch

    def test_push_pull_ends_on_an_existing_level(self):
        # A distance from a picked point can miss the box top by nanometres.
        shape = self.notched_boss(1.9e-6)
        self.assertTrue(shape.isValid())
        self.assertFalse([f for f in shape.Faces if f.Area < 1e-3])  # no step walls
        # The notch floor lands exactly on the box top and merges into it.
        tops = [f for f in shape.Faces if abs(f.CenterOfMass.z - 40) < 1e-3 and f.normalAt(0, 0).z > .99]
        self.assertEqual(len(tops), 1)
        self.assertEqual({v.Point.z for v in tops[0].Vertexes}, {40.0})
        self.assertAlmostEqual(shape.Volume, self.notch_volume(), places=6)
        # A step beyond the contact tolerance is kept.
        stepped = self.notched_boss(.01)
        self.assertEqual(len([f for f in stepped.Faces if f.Area < 1]), 1)
        self.assertAlmostEqual(stepped.Volume, self.notch_volume(.01), places=6)

    def test_deleting_a_line_beside_a_step_sliver_merges_the_faces(self):
        # A model saved before Push/Pull snapped to levels keeps its step.
        with patch.object(g, "level_distance", lambda shape, face, normal, distance, tolerance=None: distance):
            shape = self.notched_boss(1.9e-6)
        self.assertEqual(len([f for f in shape.Faces if f.Area < 1e-3]), 1)
        foot = g.V(20, 20 - 10 * math.sin(math.radians(60)), 40)
        lines = [i for i, e in enumerate(shape.Edges)
                 if abs(e.Length - 10) < 1e-6 and e.CenterOfMass.distanceToPoint(foot) < 1e-5]
        self.assertEqual(len(lines), 2)  # the two sides of the step
        for line in lines:
            result = g.erase_elements(shape, ["Edge%d" % (line + 1)])
            self.assertEqual(result.ShapeType, "Solid")
            self.assertTrue(result.isValid() and result.isClosed())
            self.assertAlmostEqual(result.Volume, shape.Volume, places=3)
            tops = [f for f in result.Faces if abs(f.CenterOfMass.z - 40) < 1e-3 and f.normalAt(0, 0).z > .99]
            self.assertEqual(len(tops), 1)
            self.assertAlmostEqual(tops[0].Area, 1600 - 1.5 * math.sqrt(3) * 100 + math.sqrt(3) / 4 * 51, places=3)
            self.assertFalse([f for f in result.Faces if f.Area < 1e-3])

if __name__ == "__main__":
    unittest.main()

