"""Native printable studs, blind sockets, fit allowance and atomic slice integration."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import FreeCAD as App
import Part
import MeshPart
from simplecad.modeling import joints as j, slicing as s
from simplecad.document import operations as op
from simplecad.core import geometry as g
V = App.Vector


class StudGeometryTests(unittest.TestCase):
    def setUp(self):
        self.shape = Part.makeBox(40, 30, 20)
        self.plane = s.cut_plane([self.shape], "X")
        self.pieces = s.split(self.shape, self.plane, 0)
        self.params = j.StudJoint()

    def joint(self, **changes):
        return j.add_studs(self.pieces, self.plane, 0, replace(self.params, **changes))

    def test_one_two_four_studs_are_fused_and_holes_are_real(self):
        volumes = []
        for count, grid in ((1, False), (2, False), (4, True)):
            parts = self.joint(count=count, grid=grid)
            self.assertEqual([side for side, _ in parts], [-1, 1])
            male, female = [p for _, p in parts]
            self.assertTrue(all(p.isValid() and p.ShapeType == "Solid" and p.isClosed() for _, p in parts))
            self.assertAlmostEqual(male.common(female).Volume, 0)
            self.assertGreater(male.Volume, 12000); self.assertLess(female.Volume, 12000)
            pins = [f for f in male.Faces if isinstance(f.Surface, Part.Cylinder)]
            sockets = [f for f in female.Faces if isinstance(f.Surface, Part.Cylinder)]
            self.assertEqual(len(pins), count); self.assertEqual(len(sockets), count)
            self.assertTrue(all(abs(f.Surface.Radius - 3) < 1e-7 for f in pins))
            self.assertTrue(all(abs(f.Surface.Radius - 3.1) < 1e-7 for f in sockets))
            volumes.append((male.Volume - 12000) / count)
        self.assertAlmostEqual(min(volumes), max(volumes))
        self.assertTrue(all(abs(p.Volume - 12000) < 1e-7 for _, p in self.pieces))

    def test_a_row_follows_the_cut_face_long_direction_and_spreads_evenly(self):
        # A tall, narrow cut face, as on a frame's upright: 10 mm wide, 17 mm tall.
        shape = Part.makeBox(40, 10, 17)
        plane = s.cut_plane([shape], "X")
        pieces = s.split(shape, plane, 0)
        params = j.StudJoint(diameter=2, length=3, count=3)
        male = dict(j.add_studs(pieces, plane, 0, params))[-1]
        centers = sorted((f.Surface.Center for f in male.Faces if isinstance(f.Surface, Part.Cylinder)), key=lambda c: c.z)
        self.assertEqual(len(centers), 3)
        self.assertTrue(all(abs(c.y - 5) < 1e-7 for c in centers))  # Stacked along Z, the long way.
        heights = sorted(c.z for c in centers)
        self.assertAlmostEqual(heights[1] - heights[0], heights[2] - heights[1])
        self.assertAlmostEqual(heights[1], 8.5)
        self.assertAlmostEqual(heights[1] - heights[0], 17 / 3)

    def test_too_many_studs_say_how_many_fit(self):
        shape = Part.makeBox(40, 10, 17)
        plane = s.cut_plane([shape], "X")
        pieces = s.split(shape, plane, 0)
        with self.assertRaisesRegex(ValueError, "Only 4 studs of this size fit along"):
            j.add_studs(pieces, plane, 0, j.StudJoint(diameter=2, length=3, count=5))
        with self.assertRaisesRegex(ValueError, "fit across"):
            j.add_studs(pieces, plane, 0, j.StudJoint(diameter=4, length=3, count=4, grid=True))

    def test_stud_length_taper_entry_chamfer_and_bottom_relief(self):
        parts = self.joint(count=1)
        male, female = [p for _, p in parts]
        pin = male.cut(self.pieces[0][1])
        cavity = self.pieces[1][1].cut(female)
        self.assertAlmostEqual(pin.BoundBox.XMin, 20)
        self.assertAlmostEqual(pin.BoundBox.XMax, 24)
        self.assertAlmostEqual(cavity.BoundBox.XMin, 20)
        self.assertAlmostEqual(cavity.BoundBox.XMax, 24.2)
        self.assertTrue(any(isinstance(f.Surface, Part.Cone) for f in pin.Faces))
        self.assertTrue(any(isinstance(f.Surface, Part.Cone) for f in cavity.Faces))
        # The rear outer wall remains a whole rectangular face, not a through-hole.
        back = next(f for f in female.Faces if abs(f.CenterOfMass.x - 40) < 1e-6)
        self.assertAlmostEqual(back.Area, 600)

    def test_fit_clearance_is_per_side_and_negative_means_interference(self):
        volumes = []
        for clearance in (-.05, 0, .1, .2):
            male, female = [p for _, p in self.joint(count=1, clearance=clearance)]
            socket = next(f for f in female.Faces if isinstance(f.Surface, Part.Cylinder))
            self.assertAlmostEqual(socket.Surface.Radius * 2, 6 + 2 * clearance)
            overlap = male.common(female).Volume
            self.assertGreater(overlap, 0) if clearance < 0 else self.assertAlmostEqual(overlap, 0)
            volumes.append(female.Volume)
        self.assertEqual(volumes, sorted(volumes, reverse=True))

    def test_flip_swaps_roles_and_offsets_keep_their_plane_directions(self):
        for flip in (False, True):
            params = replace(self.params, count=1, flip=flip, across=2, up=1)
            result = dict(j.add_studs(self.pieces, self.plane, 0, params))
            male_side = 1 if flip else -1
            self.assertGreater(result[male_side].Volume, 12000)
            self.assertLess(result[-male_side].Volume, 12000)
            section = j.interface(self.pieces[0][1], self.pieces[1][1], self.plane.center, self.plane.normal)
            center, along, across = j.row_frame(section, self.plane.normal)
            expected = center + along * 2 + across
            cylinder = next(f.Surface for f in result[male_side].Faces if isinstance(f.Surface, Part.Cylinder))
            self.assertLess((cylinder.Center - expected).cross(self.plane.normal).Length, 1e-7)

    def test_rotated_shapes_and_all_world_planes(self):
        shape = Part.makeBox(60, 50, 40)
        shape.Placement = App.Placement(V(100, -20, 30), App.Rotation(V(1, 2, 3), 27))
        for axis in ("Main", "X", "Y", "Z"):
            plane = s.cut_plane([shape], axis); pieces = s.split(shape, plane, 0)
            joined = j.add_studs(pieces, plane, 0, self.params)
            self.assertTrue(all(p.isValid() and p.isClosed() for _, p in joined))
            apart = s.separate(joined, plane.normal, 10)
            for (side, piece), moved in zip(joined, apart):
                self.assertLess((moved.CenterOfMass - piece.CenterOfMass - plane.normal * side * 5).Length, 1e-7)
            # The chamfered tip faces an empty socket opening, so the nearest
            # material can be farther away than the 6 mm tip-to-cut-plane gap.
            self.assertGreaterEqual(apart[0].distToShape(apart[1])[0], 6 - 1e-6)
            self.assertAlmostEqual(joined[0][1].common(joined[1][1]).Volume, 0, places=5)

    def test_rounded_cut_surfaces_keep_valid_studs(self):
        shape = self.shape.makeFillet(2, self.shape.Edges).Solids[0]
        plane = s.cut_plane([shape], "X")
        result = j.add_studs(s.split(shape, plane, 0), plane, 0, self.params)
        self.assertTrue(all(p.isValid() and p.isClosed() for _, p in result))

    def test_wall_depth_and_edge_guards_leave_sources_unchanged(self):
        originals = [p.copy() for _, p in self.pieces]
        for changes, message in (({"length": 19}, "does not fit"), ({"across": 20}, "does not fit"),
                                 ({"wall": 9}, "Only 1 stud"), ({"wall": 9, "spacing": 10}, "too close"), ({"count": 4, "grid": True, "spacing": 18}, "does not fit")):
            with self.assertRaisesRegex(ValueError, message): self.joint(**changes)
        for (_, shape), original in zip(self.pieces, originals):
            self.assertAlmostEqual(shape.common(original).Volume, original.Volume)

    def test_existing_hole_is_avoided_with_position_controls(self):
        shape = Part.makeBox(60, 60, 40).cut(Part.makeCylinder(5, 80, V(-10, 30, 20), V(1, 0, 0))).Solids[0]
        plane = s.cut_plane([shape], "X"); pieces = s.split(shape, plane, 0)
        with self.assertRaisesRegex(ValueError, "does not fit"):
            j.add_studs(pieces, plane, 0, replace(self.params, count=1))
        result = j.add_studs(pieces, plane, 0, replace(self.params, count=1, across=15))
        self.assertTrue(all(p.isValid() for _, p in result))

    def test_open_surfaces_extra_pieces_and_disconnected_halves_are_rejected(self):
        shell = Part.makeShell(self.shape.Faces[:-1])
        with self.assertRaisesRegex(ValueError, "closed solid"):
            j.add_studs(s.split(shell, self.plane, 0), self.plane, 0, self.params)
        with self.assertRaisesRegex(ValueError, "exactly two"):
            j.add_studs(self.pieces + self.pieces[:1], self.plane, 0, self.params)
        moved = self.pieces[1][1].copy(); moved.translate(V(4, 0, 0))
        with self.assertRaisesRegex(ValueError, "shared flat"):
            j.add_studs([self.pieces[0], (1, moved)], self.plane, 0, self.params)

    def test_parameter_validation_and_web_between_sockets(self):
        for changes in ({"diameter": 0}, {"length": -2}, {"wall": 0}, {"count": 9}, {"count": 3, "grid": True},
                        {"spacing": -1},
                        {"clearance": -4}, {"spacing": 5}, {"up": float("inf")}, {"clearance": float("nan")}):
            with self.assertRaises(ValueError): replace(self.params, **changes).validate()
        replace(self.params, count=1, spacing=0).validate()

    def test_fit_samples_have_three_clearances_flat_bases_and_printable_meshes(self):
        samples = j.fit_samples(self.params)
        self.assertEqual(len(samples), 6)
        self.assertEqual([round(c, 2) for _, _, c in samples], [0, 0, .1, .1, .2, .2])
        for name, shape, clearance in samples:
            self.assertTrue(shape.isValid() and shape.isClosed())
            self.assertAlmostEqual(shape.BoundBox.ZMin, 0)
            mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=.04, AngularDeflection=.15, Relative=False)
            self.assertTrue(mesh.isSolid(), name)
            self.assertGreater(mesh.Volume, 0)
            for other_name, other, _ in samples:
                if other_name != name: self.assertAlmostEqual(shape.common(other).Volume, 0)


class StudDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StudTest"); self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 30, 20), "Block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plan(self, params=None):
        targets = op.prepare_slicing([(self.obj, ())])
        plane = s.cut_plane([self.obj.Shape], "X")
        cuts = op.preview_slicing(targets, plane, 0)
        joined = op.preview_stud_joints(cuts, plane, 0, params or j.StudJoint())
        return targets, [(obj, s.separate(pieces, plane.normal, 10)) for obj, pieces in joined]

    def test_joint_and_slice_apply_in_one_undo_step(self):
        source, count = self.obj.Shape, self.doc.UndoCount
        targets, plan = self.plan()
        self.assertEqual(self.doc.UndoCount, count); self.assertTrue(self.obj.Shape.isSame(source))
        results = op.commit_slicing(targets, plan)
        self.assertEqual(len(results), 2); self.assertEqual(self.doc.UndoCount, count + 1)
        volumes = [obj.Shape.Volume for obj in results]
        self.doc.undo(); self.assertEqual(len(self.doc.Objects), 1); self.assertAlmostEqual(self.obj.Shape.Volume, 24000)
        self.doc.redo(); self.assertEqual([obj.Shape.Volume for obj in self.doc.Objects], volumes)

    def test_bad_joint_and_multiple_objects_never_write_partial_results(self):
        count = self.doc.UndoCount
        with self.assertRaises(ValueError): self.plan(j.StudJoint(length=30))
        self.assertEqual(len(self.doc.Objects), 1); self.assertEqual(self.doc.UndoCount, count)
        plane = s.cut_plane([self.obj.Shape], "X")
        cut = (self.obj, s.split(self.obj.Shape, plane, 0))
        with self.assertRaisesRegex(ValueError, "one object"):
            op.preview_stud_joints([cut, cut], plane, 0, j.StudJoint())

    def test_native_save_reopen_and_move_copy(self):
        targets, plan = self.plan()
        results = op.commit_slicing(targets, plan)
        volumes = [obj.Shape.Volume for obj in results]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "StudJoint.FCStd"
            self.doc.saveAs(str(path)); App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(str(path))
            for obj, volume in zip(self.doc.Objects, volumes):
                self.assertEqual(obj.TypeId, "Part::Feature"); self.assertNotIn("Proxy", obj.PropertiesList)
                self.assertTrue(obj.Shape.isValid()); self.assertAlmostEqual(obj.Shape.Volume, volume)
            copy = op.transform([self.doc.Objects[0]], V(60, 0, 0), copy=True)[0]
            self.assertAlmostEqual(copy.Shape.Volume, volumes[0])

    def test_fit_test_uses_separate_document_and_leaves_model_untouched(self):
        count = self.doc.UndoCount; original = self.obj.Shape
        sample = op.create_fit_test(j.StudJoint())
        try:
            self.assertEqual(len(sample.Objects), 6)
            self.assertTrue(all(obj.TypeId == "Part::Feature" and obj.Shape.isValid() for obj in sample.Objects))
            self.assertTrue(self.obj.Shape.isSame(original)); self.assertEqual(self.doc.UndoCount, count)
        finally:
            App.closeDocument(sample.Name); App.setActiveDocument(self.doc.Name)


if __name__ == "__main__":
    unittest.main()
