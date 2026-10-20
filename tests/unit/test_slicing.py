"""Plane cuts conserve geometry and produce independent, undoable native pieces."""
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
from simplecad.modeling import slicing as s
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op

V = App.Vector


class SliceGeometryTests(unittest.TestCase):
    def setUp(self):
        self.box = Part.makeBox(40, 30, 20)

    def assertSolids(self, pieces, count, volume):
        self.assertEqual(len(pieces), count)
        self.assertTrue(all(p.isValid() and p.ShapeType == "Solid" and p.isClosed() for _, p in pieces))
        self.assertAlmostEqual(sum(p.Volume for _, p in pieces), volume, places=5)

    def test_world_planes_offsets_closed_caps_and_no_material_loss(self):
        for axis, length in (("X", 40), ("Y", 30), ("Z", 20)):
            plane = s.cut_plane([self.box], axis)
            pieces = s.split(self.box, plane, 3)
            self.assertSolids(pieces, 2, self.box.Volume)
            self.assertAlmostEqual(pieces[0][1].Volume, self.box.Volume * (.5 + 3 / length))
            restored = pieces[0][1].fuse(pieces[1][1])
            self.assertAlmostEqual(restored.cut(self.box).Volume, 0)
            self.assertAlmostEqual(self.box.cut(restored).Volume, 0)

    def test_rotated_main_axis_and_gap_are_world_coordinates(self):
        rotation = App.Rotation(V(1, 2, 3), 37)
        self.box.Placement = App.Placement(V(120, -35, 42), rotation)
        original = self.box.copy()
        plane = s.cut_plane([self.box])
        self.assertAlmostEqual(abs(plane.normal.dot(rotation.multVec(V(1, 0, 0)))), 1)
        pieces = s.split(self.box, plane, 5)
        self.assertSolids(pieces, 2, self.box.Volume)
        separated = s.separate(pieces, plane.normal, 12)
        for (side, piece), moved in zip(pieces, separated):
            self.assertLess((moved.CenterOfMass - piece.CenterOfMass - plane.normal * side * 6).Length, 1e-7)
        self.assertAlmostEqual(separated[0].distToShape(separated[1])[0], 12, places=6)
        self.assertAlmostEqual(self.box.common(original).Volume, self.box.Volume)

    def test_rounded_block_and_cylinder_stay_closed(self):
        rounded = self.box.makeFillet(2, self.box.Edges).Solids[0]
        rounded.Placement = App.Placement(V(10, 20, 5), App.Rotation(V(1, 2, 3), 27))
        cylinder = Part.makeCylinder(6, 60, V(15, 20, 30), g.unit(V(1, 1, 1)))
        for shape in (rounded, cylinder):
            for axis in ("Main", "X", "Y", "Z"):
                plane = s.cut_plane([shape], axis)
                self.assertSolids(s.split(shape, plane, 0), 2, shape.Volume)
        self.assertAlmostEqual(abs(s.main_axis(cylinder).dot(g.unit(V(1, 1, 1)))), 1)

    def test_equal_main_dimensions_have_deterministic_axis(self):
        cube = Part.makeBox(20, 20, 20)
        cube.Placement = App.Placement(V(4, 5, 6), App.Rotation(V(0, 0, 1), 25))
        self.assertAlmostEqual(abs(s.main_axis(cube).dot(cube.Placement.Rotation.multVec(V(1, 0, 0)))), 1)
        sphere = Part.makeSphere(10)
        self.assertSolids(s.split(sphere, s.cut_plane([sphere]), 0), 2, sphere.Volume)

    def test_closed_shells_and_reversed_solids_preserve_enclosed_volume(self):
        reversed_box = self.box.copy(); reversed_box.reverse()
        shell = self.box.Shells[0]
        for shape in (shell, reversed_box):
            plane = s.cut_plane([shape])
            self.assertAlmostEqual(abs(plane.normal.x), 1)
            pieces = s.split(shape, plane, 0)
            self.assertSolids(pieces, 2, self.box.Volume)

    def test_holes_are_preserved(self):
        hole = Part.makeCylinder(4, 40, V(20, 15, -10))
        bored = self.box.cut(hole).Solids[0]
        pieces = s.split(bored, s.cut_plane([bored], "X"), 0)
        self.assertSolids(pieces, 2, bored.Volume)
        self.assertTrue(all(abs(piece.common(hole).Volume) < 1e-6 for _, piece in pieces))

    def test_concave_cut_can_make_more_than_two_solid_pieces(self):
        block = Part.makeBox(40, 30, 20).cut(Part.makeBox(20, 40, 20, V(10, -5, 5))).Solids[0]
        pieces = s.split(block, s.cut_plane([block], "Z"), 0)
        self.assertSolids(pieces, 3, block.Volume)
        self.assertEqual([side for side, _ in pieces].count(1), 2)

    def test_open_shell_and_face_are_split_without_caps(self):
        for shape in (Part.makeShell(self.box.Faces[:-1]), self.box.Faces[2]):
            pieces = s.split(shape, s.cut_plane([shape], "X"), 0)
            self.assertEqual(len(pieces), 2)
            self.assertTrue(all(not part.Solids and part.isValid() for _, part in pieces))
            self.assertAlmostEqual(sum(part.Area for _, part in pieces), shape.Area)
            for _, part in pieces:
                self.assertFalse(any(isinstance(f.Surface, Part.Plane) and abs(g.face_normal(f).x) > .99
                                     and abs(f.CenterOfMass.x - 20) < 1e-6 for f in part.Faces))

    def test_mixed_surfaces_and_loose_lines_are_retained(self):
        face = Part.makePlane(40, 30, V(0, 0, 30))
        line = Part.makeLine(V(0, 40, 30), V(40, 40, 30))
        shape = Part.makeCompound([self.box, face, line])
        pieces = s.split(shape, s.cut_plane([shape], "X"), 0)
        self.assertEqual(len(pieces), 4)
        self.assertAlmostEqual(sum(solid.Volume for _, p in pieces for solid in p.Solids), self.box.Volume)
        self.assertAlmostEqual(sum(p.Area for _, p in pieces if not p.Solids), face.Area)
        self.assertAlmostEqual(sum(e.Length for _, p in pieces for e in coinc.loose_edges(p)), line.Length)

    def test_plane_on_existing_face_or_outside_does_not_make_slivers(self):
        plane = s.cut_plane([self.box], "X")
        for offset in (-100, -20, 20, 100):
            pieces = s.split(self.box, plane, offset)
            self.assertSolids(pieces, 1, self.box.Volume)
        face = self.box.Faces[0]
        self.assertEqual(len(s.split(face, s.cut_plane([face], "X"), 0)), 1)

    def test_unsewn_nonmanifold_surfaces_and_isolated_points_survive(self):
        shape = Part.makeCompound(self.box.Faces[:-1] + [Part.makePlane(40, 30, V(0, 0, 10)), Part.Vertex(V(5, 50, 60))])
        pieces = s.split(shape, s.cut_plane([shape], "X"), 0)
        self.assertAlmostEqual(sum(part.Area for _, part in pieces), shape.Area)
        self.assertTrue(all(part.isValid() and not part.Solids for _, part in pieces))
        self.assertTrue(any(part.ShapeType == "Vertex" and (part.Point - V(5, 50, 60)).Length < 1e-7
                            for _, part in pieces))

    def test_cut_exactly_on_a_face_square_to_an_axis(self):
        # An L block: cut where the arm meets the base, at its step face.
        block = Part.makeBox(40, 30, 5).fuse(Part.makeBox(10, 30, 20)).removeSplitter()
        step = next(f for f in block.Faces if abs(f.CenterOfMass.z - 5) < 1e-9)
        plane = s.cut_plane([block], "Z")
        offset = s.face_offset(plane, step)
        pieces = s.split(block, plane, offset)
        self.assertSolids(pieces, 2, block.Volume)
        below = next(p for side, p in pieces if side < 0)
        self.assertAlmostEqual(below.BoundBox.ZMax, 5)
        self.assertAlmostEqual(below.Volume, 40 * 30 * 5)

    def test_cut_along_a_tilted_face(self):
        wedge = Part.makeBox(20, 20, 20).cut(Part.makeBox(40, 40, 40).rotated(V(), V(0, 1, 0), 45).translated(V(10, -10, 0)))
        tilted = next(f for f in wedge.Faces if abs(abs(f.normalAt(0, 0).x) - abs(f.normalAt(0, 0).z)) < 1e-9
                      and abs(f.normalAt(0, 0).x) > .5)
        normal = s.face_normal(tilted)
        plane = s.cut_plane([wedge], "Face", normal)
        self.assertAlmostEqual(abs(plane.normal.dot(tilted.normalAt(0, 0))), 1)
        # Offset back from the face by 2 mm to cut a parallel slab off.
        pieces = s.split(wedge, plane, s.face_offset(plane, tilted) - 2 * (1 if plane.normal.dot(tilted.normalAt(0, 0)) > 0 else -1))
        self.assertSolids(pieces, 2, wedge.Volume)

    def test_face_cut_needs_a_flat_parallel_face(self):
        with self.assertRaises(ValueError):
            s.face_normal(Part.makeCylinder(2, 5).Faces[0])
        plane = s.cut_plane([self.box], "Z")
        side = next(f for f in self.box.Faces if abs(f.normalAt(0, 0).x) == 1)
        with self.assertRaises(ValueError):
            s.face_offset(plane, side)

    def test_invalid_inputs_and_zero_gap(self):
        plane = s.cut_plane([self.box])
        pieces = s.split(self.box, plane, 0)
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError): s.split(self.box, plane, value)
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): s.separate(pieces, plane.normal, value)
        touching = s.separate(pieces, plane.normal, 0)
        self.assertAlmostEqual(touching[0].distToShape(touching[1])[0], 0)
        with self.assertRaises(ValueError): s.cut_plane([self.box], "Bad")


class SliceDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SliceTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 30, 20), "Block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def plan(self, selection=None, offset=0, gap=0):
        targets = op.prepare_slicing(selection or [(self.obj, ())])
        plane = s.cut_plane([shape for _, shape in targets], "X")
        cut = op.preview_slicing(targets, plane, offset)
        planned = [(obj, s.separate(pieces, plane.normal, gap)) for obj, pieces in cut]
        return targets, planned

    def test_preview_is_read_only_apply_undo_redo_and_zero_gap(self):
        original, count = self.obj.Shape, self.doc.UndoCount
        targets, planned = self.plan()
        self.assertTrue(self.obj.Shape.isSame(original))
        self.assertEqual(self.doc.UndoCount, count)
        results = op.commit_slicing(targets, planned)
        self.assertEqual(results[0], self.obj)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual([obj.Label for obj in results], ["Block · 1", "Block · 2"])
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(self.obj.Label, "Block")
        self.assertAlmostEqual(self.obj.Shape.Volume, 24000)
        self.doc.redo()
        self.assertEqual(len(self.doc.Objects), 2)

    def test_multiple_selected_objects_move_with_their_side(self):
        other = op.new_shape(self.doc, Part.makeBox(4, 4, 4, V(45, 0, 0)), "Small")
        targets, planned = self.plan([(self.obj, ("Face1",)), (self.obj, ()), (other, ())], gap=10)
        self.assertEqual(len(targets), 2)
        self.assertEqual(len(planned[1][1]), 1)
        self.assertLess((planned[1][1][0].CenterOfMass - other.Shape.CenterOfMass - V(5, 0, 0)).Length, 1e-7)
        count = self.doc.UndoCount
        results = op.commit_slicing(targets, planned)
        self.assertEqual(len(results), 3)
        self.assertEqual(self.doc.UndoCount, count + 1)

    def test_invalid_cut_or_stale_source_cannot_commit_partial_changes(self):
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, "both sides"): self.plan(offset=100)
        self.assertEqual(self.doc.UndoCount, count)
        targets, planned = self.plan()
        bad = [(self.obj, [planned[0][1][0], Part.Shape()])]
        with self.assertRaises(ValueError): op.commit_slicing(targets, bad)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(self.doc.UndoCount, count)
        op.transform([self.obj], V(5, 0, 0))
        with self.assertRaisesRegex(ValueError, "changed"): op.commit_slicing(targets, planned)

    def test_native_save_move_copy_and_edit_cut_cap(self):
        self.obj.Placement = App.Placement(V(100, 30, 50), App.Rotation(V(0, 0, 1), 20))
        targets, planned = self.plan(gap=8)
        results = op.commit_slicing(targets, planned)
        centers = [obj.Shape.CenterOfMass for obj in results]
        for obj, shape in zip(results, planned[0][1]):
            self.assertLess((obj.Shape.CenterOfMass - shape.CenterOfMass).Length, 1e-7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Slice.FCStd"
            self.doc.saveAs(str(path)); App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(str(path)); self.doc.UndoMode = 1
            self.assertEqual(len(self.doc.Objects), 2)
            for obj, center in zip(self.doc.Objects, centers):
                self.assertEqual(obj.TypeId, "Part::Feature")
                self.assertNotIn("Proxy", obj.PropertiesList)
                self.assertTrue(obj.Shape.isValid())
                self.assertLess((obj.Shape.CenterOfMass - center).Length, 1e-7)
            obj = self.doc.Objects[0]
            copied = op.transform([obj], V(70, 0, 0), copy=True)[0]
            face = next(f for f in copied.Shape.Faces if abs(g.face_normal(f).x) > .999)
            op.extrude(copied, face, 1)
            self.assertTrue(copied.Shape.isValid())

    def test_selection_and_link_guards(self):
        with self.assertRaises(ValueError): op.prepare_slicing([])
        param = self.doc.addObject("Part::Box", "Parametric"); self.doc.recompute()
        with self.assertRaisesRegex(ValueError, "plain Part"): op.prepare_slicing([(param, ())])
        parent = self.doc.addObject("App::DocumentObjectGroup", "Group"); parent.addObject(self.obj)
        with self.assertRaisesRegex(ValueError, "links"): op.prepare_slicing([(self.obj, ())])


if __name__ == "__main__":
    unittest.main()
