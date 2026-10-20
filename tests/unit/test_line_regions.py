"""Connected lines must partition existing faces, never overlay a second face."""
import tempfile
from pathlib import Path
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op

V = App.Vector
A, C, B = V(0, 0, 10), V(20, 15, 10), V(40, 0, 10)


def polygon(points):
    return Part.Face(Part.makePolygon(points + [points[0]]))


def top_faces(shape):
    return [f for f in shape.Faces if all(abs(v.Point.z - 10) < 1e-6 for v in f.Vertexes)]


def rectangle():
    return polygon([A, B, V(40, 30, 10), V(0, 30, 10)])


class LineRegionGeometryTests(unittest.TestCase):
    def divide(self, shape, a=A, c=C, b=B, extra=()):
        return g.divide_face_with_edges(shape, Part.makeLine(c, b),
                                        [Part.makeLine(a, c)] + list(extra))

    def test_center_path_divides_all_six_solid_faces_and_regions_pull(self):
        box = Part.makeBox(40, 30, 10)
        for face in box.Faces:
            a, b = [v.Point for v in face.OuterWire.OrderedVertexes[:2]]
            with self.subTest(normal=g.face_normal(face)):
                result, boundary = self.divide(box, a, face.CenterOfMass, b)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Faces), 7)
                self.assertAlmostEqual(result.Volume, box.Volume)
                self.assertAlmostEqual(result.Area, box.Area)
                regions = [f for f in result.Faces if g.coplanar(face, f)]
                self.assertEqual(len(regions), 2)
                triangle = min(regions, key=lambda f: f.Area)
                self.assertAlmostEqual(triangle.Area, face.Area / 4)
                for distance in (-2, 2):
                    pulled = g.push_pull(result, triangle, distance)
                    self.assertAlmostEqual(pulled.Volume, box.Volume + triangle.Area * distance)

    def test_rectangle_triangle_and_reversed_sheet_partition_without_overlap(self):
        for face in (rectangle(), polygon([A, B, V(0, 30, 10)])):
            for reverse in (False, True):
                source = face.copy()
                if reverse:
                    source.reverse()
                with self.subTest(area=source.Area, reverse=reverse):
                    result, _ = self.divide(source, c=source.CenterOfMass)
                    self.assertEqual(len(result.Faces), 2)
                    self.assertFalse(result.Solids)
                    self.assertAlmostEqual(result.Area, source.Area)
                    self.assertAlmostEqual(result.Faces[0].common(result.Faces[1]).Area, 0)
                    for region in result.Faces:
                        self.assertGreater(g.face_normal(region).dot(g.face_normal(source)), .999)
                        pulled, rest = g.plan_push_pull(result, region, 3)
                        self.assertAlmostEqual(pulled.Volume, region.Area * 3)
                        self.assertAlmostEqual(rest.Area, source.Area - region.Area)

    def test_open_shell_and_unsewn_compound_keep_other_faces(self):
        faces = Part.makeBox(40, 30, 10).Faces[1:]
        for shape in (Part.makeShell(faces), Part.makeCompound([f.copy() for f in faces])):
            result, _ = self.divide(shape)
            self.assertTrue(result.isValid())
            self.assertFalse(result.Solids)
            self.assertEqual(len(result.Faces), len(shape.Faces) + 1)
            self.assertAlmostEqual(result.Area, shape.Area)
            for face in shape.Faces:
                self.assertAlmostEqual(result.common(face).Area, face.Area)

    def test_fully_interior_loop_creates_inner_face_and_outer_face_with_hole(self):
        a, c, b = V(8, 8, 10), V(30, 8, 10), V(20, 23, 10)
        for shape in (rectangle(), Part.makeBox(40, 30, 10)):
            result, _ = self.divide(shape, a, c, b, [Part.makeLine(b, a)])
            regions = top_faces(result)
            self.assertEqual(len(regions), 2)
            self.assertEqual(sorted(len(f.Wires) for f in regions), [1, 2])
            self.assertAlmostEqual(sum(f.Area for f in regions), 1200)
            self.assertAlmostEqual(min(f.Area for f in regions), 165)
            self.assertAlmostEqual(regions[0].common(regions[1]).Area, 0)

    def test_dangling_branches_are_not_embedded_as_internal_face_edges(self):
        branch = Part.makeLine(C, V(20, 25, 10))
        shape = Part.makeCompound([Part.makeBox(40, 30, 10), branch])
        result, boundary = self.divide(shape)
        self.assertEqual(len(result.Solids), 1)
        self.assertEqual(len(coinc.loose_edges(result)), 1)
        self.assertTrue(coinc.same(coinc.loose_edges(result)[0], branch))
        self.assertAlmostEqual(boundary.common(branch).Length, 0)
        self.assertFalse(any(e.Orientation == "Internal" for f in result.Faces for e in f.Edges))

    def test_incomplete_off_plane_and_disconnected_networks_do_not_divide(self):
        face = rectangle()
        loose = [Part.makeLine(A, C), Part.makeLine(C + V(0, 0, 1), B + V(0, 0, 1))]
        self.assertIsNone(g.divide_face_with_edges(face, Part.makeLine(C, V(20, 25, 10)), loose))
        loop = [V(3, 3, 10), V(8, 3, 10), V(5, 7, 10)]
        edges = [Part.makeLine(loop[i], loop[(i + 1) % 3]) for i in range(3)]
        self.assertIsNone(g.divide_face_with_edges(face, Part.makeLine(C, B), edges))

    def test_existing_divider_and_hole_are_preserved(self):
        original = g.divide_face_with_line(Part.makeBox(40, 30, 10), V(0, 0, 5), V(40, 0, 5))
        result, _ = self.divide(original)
        self.assertEqual(len(result.Faces), 8)
        self.assertAlmostEqual(result.Volume, original.Volume)
        hole = polygon([V(3, 20, 10), V(8, 20, 10), V(8, 25, 10), V(3, 25, 10)])
        sheet = rectangle().cut(hole)
        result, _ = self.divide(sheet)
        self.assertAlmostEqual(result.Area, 1175)
        self.assertAlmostEqual(result.common(hole).Area, 0)

    def test_erasing_a_center_path_divider_merges_the_regions_again(self):
        for base in (Part.makeBox(40, 30, 10), rectangle()):
            result, _ = self.divide(base)
            divider = Part.makeLine(A, C)
            name = next("Edge" + str(i + 1) for i, edge in enumerate(result.Edges)
                        if coinc.same(edge, divider))
            merged = g.erase_elements(result, [name])
            self.assertTrue(merged.isValid())
            self.assertEqual(len(merged.Faces), len(base.Faces))
            self.assertAlmostEqual(merged.Area, base.Area)
            if base.Solids:
                self.assertAlmostEqual(merged.Volume, base.Volume)

    def test_round_ring_bridges_preserve_curves_and_ignore_disconnected_loop(self):
        ring = Part.Face(Part.Wire(Part.makeCircle(20))).cut(
            Part.Face(Part.Wire(Part.makeCircle(10))))
        a, b = V(10, 0, 0), V(20, 0, 0)
        c, d = V(-10, 0, 0), V(-20, 0, 0)
        # A separate triangle lies inside the upper part of the ring. Drawing
        # the lower boundary must not opportunistically fill that older loop.
        loop = [V(-1, 14, 0), V(1, 14, 0), V(0, 16, 0)]
        loose = [Part.makeLine(loop[i], loop[(i+1) % 3]) for i in range(3)]
        first, second = Part.makeLine(a, b), Part.makeLine(c, d)
        for reverse in (False, True):
            source = ring.copy()
            if reverse:
                source.reverse()
            source.rotate(V(), V(1, 2, 3), 37)
            tools = [edge.copy() for edge in [first, second] + loose]
            for edge in tools:
                edge.rotate(V(), V(1, 2, 3), 37)
            self.assertIsNone(g.divide_face_with_edges(source, tools[0], tools[2:]))
            result, boundary = g.divide_face_with_edges(source, tools[1], tools[:1] + tools[2:])
            self.assertTrue(result.isValid())
            self.assertEqual(len(result.Faces), 2)
            self.assertAlmostEqual(result.Area, source.Area)
            self.assertAlmostEqual(boundary.Length, 20)
            for face in result.Faces:
                self.assertAlmostEqual(face.Area, source.Area / 2)
                self.assertTrue(any(isinstance(e.Curve, Part.Circle) for e in face.Edges))
            for edge in tools[2:]:
                self.assertAlmostEqual(boundary.common(edge).Length, 0)


class LineRegionDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADLineRegionTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeBox(40, 30, 10), "Block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def complete(self):
        line, changed = op.draw_line(self.doc, A, C)
        self.assertFalse(changed)
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        return op.draw_line(self.doc, C, B)

    def test_second_segment_consumes_first_and_is_one_undo_step(self):
        first, _ = op.draw_line(self.doc, A, C)
        name, before = first.Name, self.doc.UndoCount
        result, changed = op.draw_line(self.doc, C, B)
        self.assertTrue(changed)
        self.assertEqual(result, self.obj)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(len(result.Shape.Faces), 7)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.assertIsNotNone(self.doc.getObject(name))
        self.doc.redo()
        self.assertEqual(len(self.obj.Shape.Faces), 7)
        self.assertIsNone(self.doc.getObject(name))

    def test_retracing_either_old_segment_repairs_already_drawn_triangle(self):
        for a, b in ((A, C), (C, B)):
            with self.subTest(segment=(a, b)):
                first = op.new_shape(self.doc, Part.makeLine(A, C), "Old line")
                second = op.new_shape(self.doc, Part.makeLine(C, B), "Old line")
                result, changed = op.draw_line(self.doc, a, b)
                self.assertTrue(changed)
                self.assertEqual(len(self.doc.Objects), 1)
                self.assertEqual(len(result.Shape.Faces), 7)
                self.doc.undo()
                self.doc.removeObject(first.Name)
                self.doc.removeObject(second.Name)

    def test_partial_old_line_and_unrelated_line_survive(self):
        d = V(30, 22.5, 10)
        old, _ = op.draw_line(self.doc, A, d)
        unrelated = op.new_shape(self.doc, Part.makeLine(V(0, 0, 30), V(40, 0, 30)), "Other line")
        before = unrelated.Shape.copy()
        result, changed = op.draw_line(self.doc, C, B)
        self.assertTrue(changed)
        self.assertEqual(len(result.Shape.Faces), 7)
        self.assertTrue(coinc.same(old.Shape, Part.makeLine(C, d)))
        self.assertTrue(coinc.same(unrelated.Shape, before))
        self.assertEqual(len(self.doc.Objects), 3)

    def test_unused_part_of_new_line_is_preserved(self):
        op.draw_line(self.doc, C, B)
        d = V(30, 22.5, 10)
        _, changed = op.draw_line(self.doc, A, d)
        self.assertTrue(changed)
        lines = [o for o in self.doc.Objects if not o.Shape.Faces]
        self.assertEqual(len(lines), 1)
        self.assertTrue(coinc.same(lines[0].Shape, Part.makeLine(C, d)))

    def test_loose_lines_inside_same_object_are_consumed(self):
        for base in (Part.makeBox(40, 30, 10), rectangle()):
            with self.subTest(base=base.ShapeType):
                self.obj.Shape = Part.makeCompound([base, Part.makeLine(A, C)])
                _, changed = op.draw_line(self.doc, C, B)
                self.assertTrue(changed)
                self.assertFalse(coinc.loose_edges(self.obj.Shape))
                self.assertEqual(len(self.obj.Shape.Faces), len(base.Faces) + 1)
                self.assertEqual(len(self.doc.Objects), 1)

    def test_loose_line_in_other_surface_object_keeps_its_surface(self):
        other_face = polygon([V(60, 0, 10), V(80, 0, 10), V(60, 20, 10)])
        other = op.new_shape(self.doc, Part.makeCompound([other_face, Part.makeLine(A, C)]), "Other surface")
        _, changed = op.draw_line(self.doc, C, B)
        self.assertTrue(changed)
        self.assertTrue(coinc.same(other.Shape, other_face))
        self.assertEqual(len(self.doc.Objects), 2)

    def test_a_line_used_by_another_feature_is_not_consumed(self):
        first, _ = op.draw_line(self.doc, A, C)
        dependent = self.doc.addObject("App::FeaturePython", "Dependent")
        dependent.addProperty("App::PropertyLink", "Source")
        dependent.Source = first
        _, changed = op.draw_line(self.doc, C, B)
        self.assertFalse(changed)
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.assertEqual(dependent.Source, first)
        self.assertTrue(coinc.same(first.Shape, Part.makeLine(A, C)))

    def test_open_triangle_face_subdivides_and_only_selected_region_pulls(self):
        self.obj.Shape = polygon([A, B, V(0, 30, 10)])
        center = self.obj.Shape.CenterOfMass
        op.draw_line(self.doc, A, center)
        _, changed = op.draw_line(self.doc, center, B)
        self.assertTrue(changed)
        self.assertEqual(len(self.obj.Shape.Faces), 2)
        region = min(self.obj.Shape.Faces, key=lambda f: f.Area)
        self.assertAlmostEqual(region.Area, 200)
        op.extrude(self.obj, region, 5)
        self.assertAlmostEqual(self.obj.Shape.Volume, 1000)
        other = next(o for o in self.doc.Objects if o != self.obj)
        self.assertAlmostEqual(other.Shape.Area, 400)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), 2)
        self.assertEqual(len(self.doc.Objects), 1)

    def test_rotated_and_translated_face_region_survives_save_reopen(self):
        placement = App.Placement(V(60, 80, 100), App.Rotation(V(1, 2, 3), 37))
        self.obj.Placement = placement
        a, c, b = [placement.multVec(p) for p in (A, C, B)]
        op.draw_line(self.doc, a, c)
        _, changed = op.draw_line(self.doc, c, b)
        self.assertTrue(changed)
        self.assertEqual(len(self.doc.Objects), 1)
        name = self.obj.Name
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "regions.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            result = self.doc.getObject(name)
            triangle = next(f for f in result.Shape.Faces if len(f.Edges) == 3)
            self.assertAlmostEqual(triangle.Area, 300)
            self.assertLess((triangle.CenterOfMass - placement.multVec(V(20, 5, 10))).Length, 1e-6)
            op.extrude(result, triangle, 3)
            self.assertAlmostEqual(result.Shape.Volume, 12900)


if __name__ == "__main__":
    unittest.main()
