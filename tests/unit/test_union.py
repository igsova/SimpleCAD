"""Native union geometry, volume preservation, document atomicity and STL export."""
from contextlib import contextmanager
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part
import Mesh
import MeshPart
from simplecad.modeling import union
from simplecad.document import operations as ops
from simplecad.core import geometry as g
V = App.Vector


class UnionGeometryTests(unittest.TestCase):
    def assert_solid(self, shape):
        self.assertEqual(shape.ShapeType, 'Solid')
        self.assertEqual(len(shape.Solids), 1)
        self.assertTrue(shape.isValid())
        self.assertTrue(shape.isClosed())
        self.assertGreater(shape.Volume, 0)
        shape.check(True)

    def test_overlapping_boxes_remove_internal_wall_and_flat_dividers(self):
        a, b = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(5, 0, 0))
        result = union.combine([a, b])
        self.assert_solid(result)
        self.assertAlmostEqual(result.Volume, 1500)
        self.assertEqual(len(result.Faces), 6)
        self.assertEqual(len(result.Edges), 12)
        self.assertAlmostEqual(a.Volume, 1000)
        self.assertAlmostEqual(b.BoundBox.XMin, 5)

    def test_face_contact_joins_but_disjoint_edge_and_point_contacts_fail(self):
        a = Part.makeBox(10, 10, 10)
        result = union.combine([a, Part.makeBox(10, 10, 10, V(10, 0, 0))])
        self.assert_solid(result)
        self.assertAlmostEqual(result.Volume, 2000)
        self.assertEqual(len(result.Faces), 6)
        for p in (V(11, 0, 0), V(10, 10, 0), V(10, 10, 10), V(10.05, 0, 0)):
            with self.subTest(position=p), self.assertRaisesRegex(ValueError, 'connected'):
                union.combine([a, Part.makeBox(10, 10, 10, p)])
        # A gap far below the modeling precision is noise, as when a part
        # placed on another ends a micron short: the pieces join as touching.
        joined = union.combine([a, Part.makeBox(10, 10, 10, V(10.001, 0, 0))])
        self.assert_solid(joined)
        self.assertAlmostEqual(joined.Volume, 2000, delta=.1)

    def test_bridge_last_combines_three_initially_disconnected_pieces(self):
        parts = [Part.makeBox(10, 10, 10, V(x, 0, 0)) for x in (0, 15, 7)]
        result = union.combine(parts)
        self.assert_solid(result)
        self.assertAlmostEqual(result.Volume, 2500)
        self.assertEqual(len(result.Faces), 6)

    def test_contained_and_duplicate_objects_do_not_leave_inner_faces(self):
        a = Part.makeBox(10, 10, 10)
        for b in (a.copy(), Part.makeBox(2, 2, 2, V(3, 3, 3))):
            result = union.combine([a, b])
            self.assert_solid(result)
            self.assertAlmostEqual(result.Volume, 1000)
            self.assertEqual(len(result.Faces), 6)

    def test_subdivided_polygon_and_stem_join_box_without_losing_volume(self):
        points = [V(10*math.cos(i*math.pi/3), 10*math.sin(i*math.pi/3), 0) for i in range(6)]
        prism = Part.Face(Part.makePolygon(points + points[:1])).extrude(V(0, 0, 15))
        stem = Part.makeBox(4, 4, 25, V(-2, -2, -20))
        shape = union.combine([prism, stem])
        box = Part.makeBox(20, 15, 8, V(-10, -7.5, 10))
        box = g.divide_face_with_line(box, V(-10, -7.5, 18), V(10, 7.5, 18))
        expected = shape.Volume + box.Volume - shape.common(box).Volume
        result = union.combine([shape, box])
        self.assert_solid(result)
        self.assertAlmostEqual(result.Volume, expected, places=6)
        self.assertAlmostEqual(result.BoundBox.ZMin, -20)
        self.assertEqual(sum(abs(f.CenterOfMass.z-18) < 1e-6 for f in result.Faces), 1)

    def test_rod_a_hair_off_its_bore_fills_it_cleanly(self):
        # A converted faceted rod sits in a plate's round bore: its facets
        # cross the wall by microns and its end stops 0.008 mm below the top.
        plate = Part.makeBox(20, 20, 10).cut(Part.makeCylinder(1.7, 12, V(10, 10, -1)))
        corners = [V(10 + 1.7045 * math.cos(math.tau * i / 48), 10 + 1.7045 * math.sin(math.tau * i / 48), 4)
                   for i in range(48)]
        rod = Part.Face(Part.makePolygon(corners + corners[:1])).extrude(V(0, 0, 5.992))
        result = union.combine([plate, rod])
        self.assertTrue(result.isValid() and result.isClosed())
        result.check(True)
        top = [f for f in result.Faces if abs(f.CenterOfMass.z - 10) < .02]
        self.assertEqual([len(f.Wires) for f in top], [1])  # The top is one closed face.
        bores = [f for f in result.Faces if isinstance(f.Surface, Part.Cylinder) and f.Surface.Radius < 2]
        self.assertEqual(len(bores), 1)
        self.assertAlmostEqual(bores[0].BoundBox.ZMax, 4, delta=.01)  # The bore stays below the rod.
        self.assertLess(len(result.Faces), 12)  # No slivers of the rod or the wall remain.
        self.assertAlmostEqual(result.Volume, 4000 - math.pi * 1.7 ** 2 * 4, delta=.5)

    def test_curves_and_through_holes_survive(self):
        hole = Part.makeCylinder(2, 20, V(5, 5, -5))
        a = Part.makeBox(10, 10, 10).cut(hole)
        b = Part.makeCylinder(3, 10, V(11, 5, 0))
        result = union.combine([a, b])
        self.assert_solid(result)
        self.assertAlmostEqual(result.common(hole).Volume, 0, places=6)
        radii = [f.Surface.Radius for f in result.Faces if isinstance(f.Surface, Part.Cylinder)]
        self.assertTrue(any(abs(r-2) < 1e-6 for r in radii))
        self.assertTrue(any(abs(r-3) < 1e-6 for r in radii))

    def test_rotated_reversed_closed_shell_and_nested_compound(self):
        transform = App.Placement(V(30, -20, 7), App.Rotation(V(1, 2, 3), 38))
        a, b = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(5, 0, 0))
        for shape in (a, b): shape.Placement = transform.multiply(shape.Placement)
        a.reverse()
        for inputs in ([a, b], [Part.makeShell(a.Faces), b],
                       [Part.makeCompound([Part.makeCompound([a]), b])]):
            result = union.combine(inputs)
            self.assert_solid(result)
            self.assertAlmostEqual(result.Volume, 1500)
            self.assertLess((result.CenterOfMass-transform.multVec(V(7.5, 5, 5))).Length, 1e-6)

    def test_open_and_mixed_geometry_rejected_without_discarding_parts(self):
        a, b = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(5, 0, 0))
        invalid = [Part.Shape(), a.Faces[0], Part.makeShell(a.Faces[:-1]),
                   Part.makeCompound([a, Part.makeLine(V(), V(20, 0, 0))]),
                   Part.makeCompound([a, Part.Vertex(V(20, 0, 0))])]
        for shape in invalid:
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                union.combine([shape, b])
        for inputs in ([], [a]):
            with self.assertRaisesRegex(ValueError, 'at least two'): union.combine(inputs)

    def test_stl_roundtrip_is_one_closed_mesh(self):
        shape = union.combine([Part.makeBox(10, 10, 10), Part.makeCylinder(4, 15, V(8, 5, -2))])
        mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=.03, AngularDeflection=.12, Relative=False)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'Union.stl')
            mesh.write(path)
            restored = Mesh.Mesh(path)
            self.assertTrue(restored.isSolid())
            self.assertEqual(restored.countComponents(), 1)
            self.assertGreater(restored.Volume, 0)
            self.assertLess(abs(restored.Volume-shape.Volume)/shape.Volume, .002)


class UnionDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('UnionTest'); self.doc.UndoMode = 1
        self.a = ops.new_shape(self.doc, Part.makeBox(10, 10, 10), 'First')
        self.b = ops.new_shape(self.doc, Part.makeBox(10, 10, 10, V(5, 0, 0)), 'Second')

    def tearDown(self): App.closeDocument(self.doc.Name)

    def test_one_undo_restores_both_objects_and_unrelated_shape_is_unchanged(self):
        other = ops.new_shape(self.doc, Part.makeBox(1, 1, 1, V(50, 0, 0)), 'Other')
        snapshot = other.Shape; name = self.b.Name; count = self.doc.UndoCount
        result = ops.unite([self.a, self.b, self.a])
        self.assertEqual(result, self.a)
        self.assertEqual(result.Label, 'Union')
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertEqual(self.doc.UndoCount, count+1)
        self.assertAlmostEqual(result.Shape.Volume, 1500)
        self.assertTrue(other.Shape.isSame(snapshot))
        self.doc.undo()
        self.assertEqual(self.a.Label, 'First')
        self.assertAlmostEqual(self.a.Shape.Volume, 1000)
        self.assertEqual(self.doc.getObject(name).Label, 'Second')
        self.assertAlmostEqual(self.doc.getObject(name).Shape.BoundBox.XMin, 5)
        self.doc.redo()
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(self.a.Shape.Volume, 1500)

    def test_placements_save_reopen_copy_and_push_pull(self):
        transform = App.Placement(V(100, 30, 20), App.Rotation(V(1, 2, 3), 29))
        for obj in (self.a, self.b): obj.Placement = transform.multiply(obj.Placement)
        result = ops.unite([self.a, self.b])
        center = transform.multVec(V(7.5, 5, 5))
        self.assertLess((result.Shape.CenterOfMass-center).Length, 1e-6)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'Union.FCStd'); name = result.Name
            self.doc.saveAs(path); App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            result = self.doc.getObject(name)
            self.assertEqual(result.TypeId, 'Part::Feature')
            self.assertLess((result.Shape.CenterOfMass-center).Length, 1e-6)
            copied = ops.transform([result], V(0, 50, 0), copy=True)[0]
            self.assertLess((copied.Shape.CenterOfMass-center-V(0, 50, 0)).Length, 1e-6)
            ops.extrude(result, result.Shape.Faces[0], 1)
            self.assertTrue(result.Shape.isValid())
            self.assertEqual(len(result.Shape.Solids), 1)

    def test_bad_selection_and_geometry_leave_no_history_or_partial_merge(self):
        self.b.Placement.Base = V(20, 0, 0)
        count = self.doc.UndoCount; original = self.a.Shape
        for objects in ([], [self.a], [self.a, self.b]):
            with self.assertRaises(ValueError): ops.unite(objects)
            self.assertEqual(self.doc.UndoCount, count)
            self.assertTrue(self.a.Shape.isSame(original))
            self.assertEqual(len(self.doc.Objects), 2)

    def test_links_expressions_support_and_cross_document_are_rejected(self):
        link = self.doc.addObject('App::Link', 'Link'); link.setLink(self.b)
        with self.assertRaises(ValueError): ops.unite([self.a, self.b])
        self.doc.removeObject(link.Name)
        self.b.addProperty('App::PropertyFloat', 'Size'); self.b.setExpression('Size', '1 + 2')
        with self.assertRaises(ValueError): ops.unite([self.a, self.b])
        self.b.setExpression('Size', None)
        self.b.addProperty('App::PropertyLink', 'SC_Support')
        with self.assertRaises(ValueError): ops.unite([self.a, self.b])
        self.b.removeProperty('SC_Support')
        doc2 = App.newDocument('OtherUnion')
        try:
            other = ops.new_shape(doc2, self.b.Shape, 'Other')
            with self.assertRaises(ValueError): ops.unite([self.a, other])
        finally: App.closeDocument(doc2.Name)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertAlmostEqual(self.a.Shape.Volume, 1000)

    def test_late_write_failure_aborts_all_changes(self):
        real_transaction = ops.transaction
        @contextmanager
        def failed_transaction(doc, title):
            with real_transaction(doc, title):
                yield
                raise RuntimeError('simulated late failure')
        count = self.doc.UndoCount; b_name = self.b.Name
        with patch.object(ops, 'transaction', failed_transaction), self.assertRaises(RuntimeError):
            ops.unite([self.a, self.b])
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(self.a.Label, 'First')
        self.assertAlmostEqual(self.a.Shape.Volume, 1000)
        self.assertAlmostEqual(self.doc.getObject(b_name).Shape.Volume, 1000)

    def test_single_compound_with_overlapping_solids_can_be_cleaned(self):
        self.a.Shape = Part.makeCompound([self.a.Shape, self.b.Shape])
        result = ops.unite([self.a])
        self.assertEqual(result.Shape.ShapeType, 'Solid')
        self.assertAlmostEqual(result.Shape.Volume, 1500)


if __name__ == '__main__': unittest.main()
