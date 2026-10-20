"""Periodic surface seams are topology, not erasable drawn dividers."""
import tempfile
from pathlib import Path
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op

V = App.Vector


def seam_names(shape):
    return ["Edge" + str(i + 1) for i, edge in enumerate(shape.Edges) if g.is_seam_edge(shape, edge)]


class SeamGeometryTests(unittest.TestCase):
    def test_incidence_lookup_matches_full_scan_with_placements(self):
        for shape in (Part.makeCylinder(5,10),Part.makeSphere(5),Part.makeTorus(10,3),Part.makeBox(5,6,7)):
            for moved in (False,True):
                if moved:shape.Placement=App.Placement(V(20,30,40),App.Rotation(V(1,2,3),37));shape.reverse()
                expected={i for i,e in enumerate(shape.Edges)
                          if any(e.isSeam(f) for f in shape.Faces)}
                self.assertEqual(g.seam_indices(shape),expected)
                self.assertEqual({i for i,e in enumerate(shape.Edges) if g.is_seam_edge(shape,e)}, expected)
                for i in range(len(shape.Edges)):
                    self.assertEqual(g.seam_indices(shape,{i}), expected.intersection({i}))

    def test_cylinder_cone_sphere_and_torus_seams_are_protected(self):
        for shape in (Part.makeCylinder(5, 10), Part.makeCone(5, 0, 10),
                      Part.makeSphere(5), Part.makeTorus(10, 3)):
            with self.subTest(shape=shape.Faces[0].Surface):
                names = seam_names(shape)
                self.assertTrue(names)
                result = g.erase_elements(shape, names)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                self.assertEqual(len(result.Faces), len(shape.Faces))
                self.assertEqual(len(result.Edges), len(shape.Edges))
                self.assertAlmostEqual(result.Volume, shape.Volume)
                self.assertAlmostEqual(result.Area, shape.Area)

    def test_rotated_and_reversed_seams(self):
        shape = Part.makeCylinder(5, 10)
        shape.Placement = App.Placement(V(20, 30, 40), App.Rotation(V(1, 2, 3), 37))
        shape.reverse()
        result = g.erase_elements(shape, seam_names(shape))
        self.assertAlmostEqual(result.Volume, shape.Volume)
        self.assertLess((result.CenterOfMass - shape.CenterOfMass).Length, 1e-7)
        self.assertEqual(result.Orientation, shape.Orientation)

    def test_open_cylindrical_wall_keeps_its_seam(self):
        wall = Part.makeCylinder(5, 10).Faces[0]
        result = g.erase_elements(wall, seam_names(wall))
        self.assertEqual(result.ShapeType, "Face")
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Area, wall.Area)

    def test_circle_rim_still_erases_its_adjoining_faces(self):
        shape = Part.makeCylinder(5, 10)
        rim = next("Edge" + str(i + 1) for i, edge in enumerate(shape.Edges)
                   if isinstance(edge.Curve, Part.Circle))
        self.assertNotIn(rim, seam_names(shape))
        result = g.erase_elements(shape, [rim] + seam_names(shape))
        self.assertFalse(result.Solids)
        self.assertEqual(len(result.Faces), 1)
        self.assertIsInstance(result.Faces[0].Surface, Part.Plane)
        self.assertAlmostEqual(result.Area, 25 * 3.141592653589793)

    def test_explicit_wall_face_deletion_is_allowed(self):
        shape = Part.makeCylinder(5, 10)
        result = g.erase_elements(shape, ["Face1"] + seam_names(shape))
        self.assertEqual(len(result.Faces), 2)
        self.assertTrue(all(isinstance(face.Surface, Part.Plane) for face in result.Faces))
        self.assertTrue(result.isValid())

    def test_straight_edges_and_planar_dividers_are_not_seams(self):
        box = Part.makeBox(10, 10, 10)
        divided = g.divide_face_with_line(box, V(0, 0, 10), V(10, 10, 10))
        self.assertFalse(seam_names(divided))
        edge = Part.makeLine(V(5, 0, 0), V(5, 0, 10))
        self.assertFalse(g.is_seam_edge(edge, edge))


class SeamDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADSeamTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, Part.makeCylinder(5, 10), "Cylinder")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_seam_only_no_document_change_or_undo_entry(self):
        count = self.doc.UndoCount
        before = self.obj.Shape.copy()
        changed, ignored = op.delete_selection([(self.obj, seam_names(self.obj.Shape))])
        self.assertEqual((changed, ignored), (0, 1))
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertAlmostEqual(self.obj.Shape.Volume, before.Volume)
        self.assertEqual(len(self.obj.Shape.Faces), 3)

    def test_seam_selection_does_not_expand_to_coincident_free_line(self):
        edge = self.obj.Shape.getElement(seam_names(self.obj.Shape)[0])
        line = op.new_shape(self.doc, edge.copy(), "Drawn line")
        count = self.doc.UndoCount
        self.assertEqual(op.delete_selection([(self.obj, seam_names(self.obj.Shape))]), (0, 1))
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(len(self.doc.Objects), 2)
        self.assertIsNotNone(self.doc.getObject(line.Name))

    def test_free_line_over_seam_deletes_without_removing_wall(self):
        edge = self.obj.Shape.getElement(seam_names(self.obj.Shape)[0])
        line = op.new_shape(self.doc, edge.copy(), "Drawn line")
        name = line.Name
        self.assertEqual(op.delete_selection([(line, ["Edge1"])]), (1, 0))
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(len(self.obj.Shape.Faces), 3)
        self.assertEqual(len(self.obj.Shape.Solids), 1)
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(name))

    def test_mixed_selection_deletes_real_geometry_in_one_undo(self):
        line = op.new_shape(self.doc, Part.makeLine(V(50, 0, 0), V(60, 0, 0)), "Line")
        name = line.Name
        count = self.doc.UndoCount
        self.assertEqual(op.delete_selection([(self.obj, seam_names(self.obj.Shape)), (line, ["Edge1"])]), (1, 1))
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(len(self.obj.Shape.Solids), 1)
        self.assertIsNone(self.doc.getObject(name))
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(name))

    def test_whole_object_selection_still_deletes_cylinder(self):
        name = self.obj.Name
        self.assertEqual(op.delete_selection([(self.obj, seam_names(self.obj.Shape)), (self.obj, ())]), (1, 0))
        self.assertIsNone(self.doc.getObject(name))
        self.doc.undo()
        self.assertEqual(len(self.doc.getObject(name).Shape.Solids), 1)

    def test_save_reopen_existing_cylinder_remains_protected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "cylinder.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.obj = self.doc.Objects[0]
            count = self.doc.UndoCount
            self.assertEqual(op.delete_selection([(self.obj, seam_names(self.obj.Shape))]), (0, 1))
            self.assertEqual(self.doc.UndoCount, count)
            self.assertEqual(len(self.obj.Shape.Faces), 3)


if __name__ == "__main__":
    unittest.main()
