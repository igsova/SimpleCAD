"""Coincident geometry from old models, independent objects and new drawings."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import FreeCAD as App
import Part
from simplecad.core import coincident as c, geometry as g
from simplecad.document import operations as op

V = App.Vector
A, B = V(0, 0, 0), V(20, 0, 0)


def triangle(third):
    return Part.Face(Part.makePolygon([A, B, third, A]))


def edge_name(shape, edge=None):
    edge = edge if edge is not None else Part.makeLine(A, B)
    return next("Edge" + str(i + 1) for i, candidate in enumerate(shape.Edges) if c.same(candidate, edge))


class CoincidentGeometryTests(unittest.TestCase):
    def test_index_matches_across_bucket_boundaries_and_hash_collisions(self):
        center = c.Index.cell - c.TOL*.01
        edge = Part.makeLine(V(center-1,0,0),V(center+1,0,0))
        shifted = edge.copy(); shifted.translate(V(c.TOL*.05,0,0))
        self.assertTrue(c.same(edge,shifted))
        reversed_edge = edge.copy(); reversed_edge.reverse()
        shapes = [edge,reversed_edge,Part.makeLine(V(8,0,0),V(9,0,0))]
        # A hash collision cannot turn different geometry into a match.
        # Exercise both the small-index path and spatial buckets.
        for extra in ([], [Part.makeLine(V(i,10,0),V(i+1,10,0)) for i in range(9)]):
            with mock.patch.object(c,'hash',return_value=7,create=True):
                index = c.Index(shapes + extra)
                self.assertEqual(set(index.matches(shifted)),{0,1})
                self.assertEqual(set(index.matches(shapes[2])),{2})

    def test_index_distinguishes_equal_area_faces_with_different_holes(self):
        outer = Part.makePlane(20,20)
        a = outer.cut(Part.makePlane(2,2,V(2,2,0))).Faces[0]
        b = outer.cut(Part.makePlane(2,2,V(12,12,0))).Faces[0]
        duplicate = a.copy(); duplicate.reverse()
        index = c.Index([a,b,duplicate])
        self.assertEqual(set(index.matches(a.copy())),{0,2})
        self.assertEqual(set(index.matches(b.copy())),{1})

    def test_dense_unique_regions_do_not_compare_every_pair(self):
        shapes = [Part.makePlane(1,1,V(x*2,y*2,0)) for x in range(32) for y in range(32)]
        duplicates = [face.copy() for face in shapes[::64]]
        with mock.patch.object(c,'same',wraps=c.same) as compare:
            result = c.unique(shapes+duplicates)
        self.assertEqual(len(result),1024)
        self.assertLess(compare.call_count,len(shapes)*2)
        self.assertTrue(all(a.isSame(b) for a,b in zip(result,shapes)))

    def test_full_edge_match_reversed_but_not_partial_or_nearby(self):
        original = Part.makeLine(A, B)
        self.assertTrue(c.same(original, Part.makeLine(B, A)))
        for other in (Part.makeLine(A, B / 2), Part.makeLine(B, B * 2),
                      Part.makeLine(A + V(0, 1e-4, 0), B + V(0, 1e-4, 0))):
            self.assertFalse(c.same(original, other))
        # Equal endpoints do not make an arc the same as a straight edge.
        self.assertFalse(c.same(original, Part.Arc(A, V(10, 10, 0), B).toShape()))

    def test_full_face_match_ignores_orientation_and_retains_different_holes(self):
        face = triangle(V(0, 10, 0))
        other = triangle(V(0, 10, 0))
        other.reverse()
        self.assertTrue(c.same(face, other))
        outer = Part.makePlane(20, 20)
        first = outer.cut(Part.makePlane(2, 2, V(2, 2, 0))).Faces[0]
        second = outer.cut(Part.makePlane(2, 2, V(12, 12, 0))).Faces[0]
        self.assertAlmostEqual(first.Area, second.Area)
        self.assertFalse(c.same(first, second))
        self.assertFalse(c.same(outer, Part.makePlane(10, 20)))

    def test_independent_edges_in_one_compound_erase_both_angled_faces(self):
        shape = Part.makeCompound([triangle(V(0, 10, 0)), triangle(V(0, 0, 10))])
        self.assertEqual(len(shape.Edges), 6)
        self.assertIsNone(g.erase_elements(shape, [edge_name(shape)]))

    def test_duplicate_faces_do_not_change_adjacency_or_selected_face_index(self):
        face = triangle(V(0, 10, 0))
        second = triangle(V(20, -10, 0))
        shape = Part.makeCompound([face, second, triangle(V(0, 10, 0))])
        merged = g.erase_elements(shape, [edge_name(shape)])
        self.assertEqual(len(merged.Faces), 1)
        self.assertAlmostEqual(merged.Area, 200)
        remaining = g.erase_elements(shape, ["Face3"])
        self.assertEqual(len(remaining.Faces), 1)
        self.assertTrue(c.same(remaining.Faces[0], second))

    def test_duplicate_loose_line_on_face_edge_is_erased_with_face(self):
        face = triangle(V(0, 10, 0))
        shape = Part.makeCompound([face, Part.makeLine(A, B), Part.makeLine(B, A)])
        self.assertIsNone(g.erase_elements(shape, [edge_name(shape)]))

    def test_coplanar_faces_on_a_shared_edge_merge_and_the_rest_are_erased(self):
        # As in SketchUp: the two flat triangles become one face, and the
        # upright one that loses its edge is erased.
        shape = Part.makeCompound([triangle(V(0, 10, 0)), triangle(V(0, 0, 10)), triangle(V(0, -10, 0))])
        result = g.erase_elements(shape, [edge_name(shape)])
        self.assertEqual(len(result.Faces), 1)
        self.assertAlmostEqual(result.Faces[0].Area, 2 * triangle(V(0, 10, 0)).Area)
        self.assertAlmostEqual(result.BoundBox.ZLength, 0)

    def test_three_faces_at_angles_are_all_erased(self):
        shape = Part.makeCompound([triangle(V(0, 10, 0)), triangle(V(0, 0, 10)), triangle(V(0, -10, 10))])
        self.assertIsNone(g.erase_elements(shape, [edge_name(shape)]))


class CoincidentDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADCoincidentTest")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def raw(self, shape, name="Legacy"):
        # Bypass drawing deduplication to reproduce models saved by old versions.
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = shape
        self.doc.recompute()
        return obj

    def test_face_beside_a_solid_merges_with_its_coplanar_face(self):
        block = self.raw(Part.makeBox(10, 10, 10), "Block")
        flap = self.raw(Part.Face(Part.makePolygon([V(10, 0, 0), V(20, 0, 0), V(20, 10, 0), V(10, 10, 0), V(10, 0, 0)])), "Flap")
        shared = next("Edge" + str(i + 1) for i, e in enumerate(flap.Shape.Edges) if abs(e.CenterOfMass.x - 10) < 1e-9)
        op.delete_selection([(flap, [shared])])
        remaining = [o for o in self.doc.Objects if hasattr(o, "Shape")]
        self.assertEqual(len(remaining), 1)
        shape = remaining[0].Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Faces), 5)  # The block's side at x = 10 lost its edge.
        bottom = [f for f in shape.Faces if abs(f.CenterOfMass.z) < 1e-9]
        self.assertEqual(len(bottom), 1)
        self.assertAlmostEqual(bottom[0].Area, 200)
        self.doc.undo()
        self.assertEqual(len(self.doc.getObject("Block").Shape.Solids), 1)
        self.assertIsNotNone(self.doc.getObject("Flap"))

    def test_surface_on_a_pulled_block_joins_into_one_solid(self):
        # Pulling a face of an open surface makes a block and leaves the rest
        # as surfaces. Deleting a side line between them joins them.
        top = Part.makeBox(10, 10, 10)
        surface = self.raw(Part.makeShell([f for f in top.Faces if f.CenterOfMass.z > 1e-9]), "Rest")
        block = self.raw(Part.makeBox(10, 10, 5, V(0, 0, -5)), "Block")
        line = next("Edge" + str(i + 1) for i, e in enumerate(block.Shape.Edges)
                    if abs(e.CenterOfMass.x) < 1e-9 and abs(e.CenterOfMass.z) < 1e-9)
        op.delete_selection([(block, [line])])
        self.assertIsNone(self.doc.getObject("Rest"))  # The solid's object is kept.
        shape = self.doc.getObject("Block").Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertTrue(shape.isValid() and shape.isClosed())
        self.assertAlmostEqual(shape.Volume, 1500)
        side = [f for f in shape.Faces if abs(f.CenterOfMass.x) < 1e-9]
        self.assertEqual([round(f.Area, 6) for f in side], [150])

    def test_angled_faces_in_different_objects_delete_once_undo_redo(self):
        first = self.raw(triangle(V(0, 10, 0)))
        second = self.raw(triangle(V(0, 0, 10)))
        third = self.raw(Part.makePlane(5, 5, V(40, 40, 0)))
        names = first.Name, second.Name, third.Name
        count = self.doc.UndoCount
        op.delete_selection([(first, [edge_name(first.Shape)])])
        self.assertEqual([obj.Name for obj in self.doc.Objects], [names[2]])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 3)
        self.doc.redo()
        self.assertEqual([obj.Name for obj in self.doc.Objects], [names[2]])

    def test_flat_faces_in_different_objects_merge_instead_of_disappearing(self):
        first = self.raw(triangle(V(0, 10, 0)))
        self.raw(triangle(V(20, -10, 0)))
        op.delete_selection([(first, [edge_name(first.Shape)])])
        self.assertEqual(len(self.doc.Objects), 1)
        result = self.doc.Objects[0].Shape
        self.assertEqual(len(result.Faces), 1)
        self.assertAlmostEqual(result.Area, 200)
        self.assertFalse(any(c.same(edge, Part.makeLine(A, B)) for edge in result.Edges))

    def test_solid_and_extra_triangle_both_lose_incident_faces(self):
        block = self.raw(Part.makeBox(20, 20, 10))
        patch = self.raw(triangle(V(0, -10, 10)))
        patch_name = patch.Name
        op.delete_selection([(patch, [edge_name(patch.Shape)])])
        self.assertIsNone(self.doc.getObject(patch_name))
        self.assertEqual(len(block.Shape.Faces), 4)
        self.assertEqual(len(block.Shape.Solids), 0)
        self.assertTrue(block.Shape.isValid())
        self.doc.undo()
        self.assertEqual(len(block.Shape.Faces), 6)
        self.assertIsNotNone(self.doc.getObject(patch_name))

    def test_duplicate_face_selection_reaches_other_objects(self):
        face = self.raw(triangle(V(0, 10, 0)))
        self.raw(triangle(V(0, 10, 0)))
        op.delete_selection([(face, ["Face1"])])
        self.assertEqual(len(self.doc.Objects), 0)

    def test_whole_object_selection_does_not_expand_to_matching_objects(self):
        face = self.raw(triangle(V(0, 10, 0)))
        other = self.raw(triangle(V(0, 10, 0)))
        name = other.Name
        op.delete_selection([(face, ())])
        self.assertEqual([obj.Name for obj in self.doc.Objects], [name])

    def test_rotated_and_translated_objects_match_in_world_coordinates(self):
        first = self.raw(triangle(V(0, 10, 0)))
        second = self.raw(triangle(V(0, 0, 10)))
        placement = App.Placement(V(70, -30, 12), App.Rotation(V(1, 2, 3), 37))
        first.Placement = placement
        second.Shape = second.Shape.transformGeometry(placement.toMatrix())
        op.delete_selection([(first, [edge_name(first.Shape, first.Shape.Edges[0])])])
        self.assertFalse(self.doc.Objects)

    def test_nearby_and_partial_lines_survive(self):
        line = self.raw(Part.makeLine(A, B))
        other = self.raw(Part.makeLine(A + V(0, 1e-4, 0), B + V(0, 1e-4, 0)))
        partial = self.raw(Part.makeLine(A, B / 2))
        names = [other.Name, partial.Name]
        op.delete_selection([(line, ["Edge1"])])
        self.assertEqual([obj.Name for obj in self.doc.Objects], names)

    def test_dependency_failure_keeps_all_originals(self):
        first = self.raw(triangle(V(0, 10, 0)))
        second = self.raw(triangle(V(0, 0, 10)))
        dependent = self.doc.addObject("App::FeaturePython", "Dependent")
        dependent.addProperty("App::PropertyLink", "Source")
        dependent.Source = second
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, "depends"):
            op.delete_selection([(first, [edge_name(first.Shape)])])
        self.assertEqual(len(self.doc.Objects), 3)
        self.assertEqual(len(first.Shape.Faces), 1)
        self.assertEqual(self.doc.UndoCount, count)

    def test_cleanup_sews_faces_removes_duplicates_and_saves_with_undo(self):
        first = self.raw(triangle(V(0, 10, 0)))
        self.raw(triangle(V(0, 0, 10)))
        self.raw(triangle(V(0, 10, 0)))
        self.raw(Part.makeLine(A, B))
        count = self.doc.UndoCount
        self.assertGreater(op.cleanup(self.doc), 0)
        self.assertEqual(len(self.doc.Objects), 1)
        shape = self.doc.Objects[0].Shape
        self.assertEqual((len(shape.Faces), len(shape.Edges)), (2, 5))
        self.assertEqual(sum(any(edge.isSame(e) for e in face.Edges) for face in shape.Faces
                             for edge in [shape.getElement(edge_name(shape))]), 2)
        self.assertAlmostEqual(shape.Area, 200)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(op.cleanup(self.doc), 0)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 4)
        self.doc.redo()
        self.assertEqual(len(self.doc.Objects), 1)
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "cleaned.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.assertEqual((len(self.doc.Objects[0].Shape.Faces), len(self.doc.Objects[0].Shape.Edges)), (2, 5))
            self.assertTrue(self.doc.Objects[0].Shape.isValid())

    def test_cleanup_inside_one_compound_preserves_other_divisions(self):
        shape = Part.makeCompound([triangle(V(0, 10, 0)), triangle(V(20, -10, 0)), triangle(V(0, 10, 0))])
        obj = self.raw(shape)
        op.cleanup(self.doc)
        self.assertEqual((len(obj.Shape.Faces), len(obj.Shape.Edges)), (2, 5))
        self.assertAlmostEqual(obj.Shape.Area, 200)
        op.delete_selection([(obj, [edge_name(obj.Shape)])])
        self.assertEqual(len(obj.Shape.Faces), 1)

    def test_cleanup_keeps_solid_and_removes_exact_overlays(self):
        solid = self.raw(g.divide_face_with_line(Part.makeBox(20, 20, 10), V(0, 0, 10), V(20, 20, 10)))
        self.raw(solid.Shape.Faces[0].copy())
        self.raw(solid.Shape.copy())
        self.raw(solid.Shape.Edges[0].copy())
        op.cleanup(self.doc)
        self.assertEqual(self.doc.Objects, [solid])
        self.assertEqual(len(solid.Shape.Faces), 7)
        self.assertAlmostEqual(solid.Shape.Volume, 4000)

    def test_cleanup_only_selected_objects_and_lines_before_faces(self):
        unrelated = self.raw(Part.makePlane(5, 5, V(40, 40, 0)))
        line = self.raw(Part.makeLine(A, B))
        face = self.raw(triangle(V(0, 10, 0)))
        second = self.raw(triangle(V(0, 10, 0)))
        op.cleanup(self.doc, [line, face])
        self.assertEqual(self.doc.Objects, [unrelated, face, second])

    def test_cleanup_does_not_sew_nearby_noncoincident_surfaces(self):
        shape = Part.makeCompound([triangle(V(0, 10, 0)),
                                  Part.Face(Part.makePolygon([p + V(0, 0, 5e-7) for p in (A, B, V(0, 10, 0), A)]))])
        obj = self.raw(shape)
        count = self.doc.UndoCount
        self.assertEqual(op.cleanup(self.doc), 0)
        self.assertEqual((len(obj.Shape.Faces), len(obj.Shape.Edges)), (2, 6))
        self.assertEqual(self.doc.UndoCount, count)

    def test_cleanup_duplicate_with_dependent_fails_atomically(self):
        self.raw(triangle(V(0, 10, 0)))
        second = self.raw(triangle(V(0, 10, 0)))
        dependent = self.doc.addObject("App::FeaturePython", "Dependent")
        dependent.addProperty("App::PropertyLink", "Source")
        dependent.Source = second
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, "depends"):
            op.cleanup(self.doc)
        self.assertEqual(len(self.doc.Objects), 3)
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(len(second.Shape.Faces), 1)

    def test_cleanup_does_not_discard_loose_edges_from_duplicate_mixed_compound(self):
        solid = Part.makeBox(10, 10, 10)
        self.raw(solid)
        self.raw(Part.makeCompound([solid.copy(), Part.makeLine(V(30, 0, 0), V(40, 0, 0))]))
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, "Separate"):
            op.cleanup(self.doc)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertEqual(self.doc.UndoCount, count)

    def test_new_line_and_rectangle_do_not_stack(self):
        first, _ = op.draw_line(self.doc, A, B)
        count = self.doc.UndoCount
        second, _ = op.draw_line(self.doc, B, A)
        self.assertEqual(first, second)
        self.assertEqual(self.doc.UndoCount, count)
        face = op.new_shape(self.doc, Part.makePlane(10, 10), "Rectangle")
        count = self.doc.UndoCount
        duplicate = op.new_shape(self.doc, Part.makePlane(10, 10), "Rectangle")
        self.assertEqual(face, duplicate)
        self.assertEqual(self.doc.UndoCount, count)
        result, changed = op.draw_line(self.doc, V(0, 0, 0), V(0, 10, 0))
        self.assertEqual(result, face)
        self.assertTrue(changed)
        self.assertEqual(self.doc.UndoCount, count)


if __name__ == "__main__":
    unittest.main()
