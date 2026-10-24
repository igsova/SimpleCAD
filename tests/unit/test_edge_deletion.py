"""Native topology and document tests for selection-aware Delete."""
import math
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op

V = App.Vector


def divided_box():
    return g.divide_face_with_line(Part.makeBox(40, 30, 10), V(0, 0, 10), V(40, 0, 0))


def dividers(shape):
    found = []
    for i, edge in enumerate(shape.Edges):
        adjacent = [face for face in shape.Faces if any(edge.isSame(e) for e in face.Edges)]
        if len(adjacent) == 2 and g.coplanar(*adjacent):
            found.append(("Edge" + str(i + 1), edge))
    return found


class EraseGeometryTests(unittest.TestCase):
    def test_coplanar_edge_merges_two_faces_into_valid_solid(self):
        shape = divided_box()
        result = g.erase_elements(shape, [dividers(shape)[0][0]])
        self.assertEqual(len(result.Faces), 6)
        self.assertEqual(result.ShapeType, "Solid")
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 12000)
        self.assertAlmostEqual(result.Area, shape.Area)
        self.assertEqual(len(dividers(result)), 0)
        for face in result.Faces:
            self.assertAlmostEqual(g.push_pull(result, face, 2).Volume, 12000 + face.Area * 2)

    def test_midpoint_boundary_is_sewn_without_erasing_other_divisions(self):
        shape = Part.makeBox(40, 30, 10)
        for height in (3, 7):
            shape = g.divide_face_with_line(shape, V(0, 0, height), V(40, 0, height))
        name, _ = min(dividers(shape), key=lambda item: item[1].CenterOfMass.z)
        result = g.erase_elements(shape, [name])
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 12000)
        self.assertEqual(len(result.Faces), 7)
        self.assertEqual(len(dividers(result)), 1)
        self.assertAlmostEqual(dividers(result)[0][1].CenterOfMass.z, 7)

    def test_crossing_divisions_can_be_erased_selectively_or_together(self):
        shape = g.divide_face_with_line(divided_box(), V(), V(40, 0, 10))
        selected = [name for name, _ in dividers(shape)]
        self.assertEqual(len(selected), 4)
        partial = g.erase_elements(shape, selected[:1])
        self.assertEqual(len(partial.Faces), 8)
        self.assertEqual(len(dividers(partial)), 3)
        complete = g.erase_elements(shape, selected)
        self.assertEqual(len(complete.Faces), 6)
        self.assertTrue(complete.isValid())
        self.assertAlmostEqual(complete.Volume, 12000)

    def test_coplanar_seams_left_by_push_pull_can_be_erased(self):
        # A second drawn division, across the top, keeps Push/Pull from
        # refining the solid, so the pulled triangle leaves seams beside it.
        shape = g.divide_face_with_line(divided_box(), V(0, 0, 10), V(40, 30, 10))
        triangle = next(f for f in shape.Faces if len(f.Edges) == 3 and abs(g.face_normal(f).y) > .999)
        pulled = g.push_pull(shape, triangle, 5)
        selected = [name for name, _ in dividers(pulled)]
        self.assertGreater(len(selected), 1)  # The seams and the top's division.
        result = g.erase_elements(pulled, selected)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 13000)
        self.assertEqual(len(dividers(result)), 0)

    def test_merge_preserves_cavity_shells_and_holes(self):
        shape = divided_box().cut(Part.makeBox(4, 4, 4, V(2, 2, 2))).Solids[0]
        result = g.erase_elements(shape, [dividers(shape)[0][0]])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Shells), 2)
        self.assertAlmostEqual(result.Volume, 11936)
        # A division across a face with an inner wire must not fill its hole.
        perforated = g.divide_face_with_line(Part.makeBox(40, 30, 10), V(0, 0, 8), V(40, 0, 8))
        perforated = perforated.cut(Part.makeBox(4, 40, 4, V(2, -5, 2))).Solids[0]
        result = g.erase_elements(perforated, [dividers(perforated)[0][0]])
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 11520)
        front = next(f for f in result.Faces if abs(f.CenterOfMass.y) < 1e-6)
        self.assertEqual(len(front.Wires), 2)

    def test_angled_edge_removes_exactly_its_incident_faces(self):
        shape = Part.makeBox(40, 30, 10)
        edge = shape.Edges[0]
        removed = [f for f in shape.Faces if any(edge.isSame(e) for e in f.Edges)]
        self.assertEqual(len(removed), 2)
        result = g.erase_elements(shape, ["Edge1"])
        self.assertTrue(result.isValid())
        self.assertFalse(result.isClosed())
        self.assertEqual(len(result.Solids), 0)
        self.assertEqual(len(result.Faces), 4)
        self.assertAlmostEqual(result.Area, shape.Area - sum(f.Area for f in removed))
        self.assertTrue(all(result.common(f).Area < 1e-6 for f in removed))
        with self.assertRaisesRegex(ValueError, "open"):
            g.push_pull(result, result.Faces[0], 5)

    def test_open_surfaces_allow_more_edge_deletion(self):
        surface = g.erase_elements(Part.makeBox(40, 30, 10), ["Edge1"])
        edge_name = next("Edge" + str(i + 1) for i, edge in enumerate(surface.Edges)
                         if sum(any(edge.isSame(e) for e in f.Edges) for f in surface.Faces) == 1)
        result = g.erase_elements(surface, [edge_name])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), 3)
        self.assertEqual(len(result.Solids), 0)

    def test_open_surface_divider_merges_without_closing_the_opening(self):
        shape = divided_box()
        back = next("Face" + str(i + 1) for i, face in enumerate(shape.Faces)
                    if abs(face.CenterOfMass.y - 30) < 1e-6)
        opened = g.erase_elements(shape, [back])
        result = g.erase_elements(opened, [dividers(opened)[0][0]])
        self.assertTrue(result.isValid())
        self.assertFalse(result.isClosed())
        self.assertEqual(len(result.Faces), 5)
        self.assertEqual(len(result.Solids), 0)

    def test_mixed_divider_and_angled_edge_selection_leaves_neither_edge(self):
        shape = divided_box()
        divider = dividers(shape)[0][0]
        corner = next("Edge" + str(i + 1) for i, edge in enumerate(shape.Edges)
                      if (edge.CenterOfMass - V(20, 0, 10)).Length < 1e-6)
        result = g.erase_elements(shape, [divider, corner])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), 4)
        self.assertEqual(len(result.Solids), 0)
        for name in (divider, corner):
            self.assertAlmostEqual(result.common(shape.getElement(name)).Length, 0)

    def test_face_deletion_disconnected_faces_and_empty_result(self):
        shape = Part.makeBox(40, 30, 10)
        result = g.erase_elements(shape, ["Face1"])
        self.assertEqual(len(result.Faces), 5)
        result = g.erase_elements(shape, ["Face1", "Face2", "Face3", "Face4"])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), 2)
        self.assertEqual(len(result.Solids), 0)
        self.assertIsNone(g.erase_elements(shape, ["Face" + str(i) for i in range(1, 7)]))
        self.assertIsNone(g.erase_elements(Part.makePlane(10, 10), ["Edge1"]))

    def test_loose_edge_deletion_preserves_other_edges_and_surfaces(self):
        first, second = Part.makeLine(V(), V(1, 0, 0)), Part.makeLine(V(2, 0, 0), V(3, 0, 0))
        result = g.erase_elements(Part.makeCompound([first, second]), ["Edge1"])
        self.assertEqual(result.ShapeType, "Edge")
        self.assertAlmostEqual(result.CenterOfMass.x, 2.5)
        shape = Part.makeCompound([Part.makePlane(10, 10), first])
        loose = next("Edge" + str(i + 1) for i, edge in enumerate(shape.Edges) if edge.isSame(first))
        result = g.erase_elements(shape, [loose])
        self.assertEqual(len(result.Faces), 1)
        self.assertAlmostEqual(result.Area, 100)

    def test_invalid_and_vertex_selections_fail_without_mutation(self):
        shape = divided_box()
        for names in ([], ["Vertex1"], ["Edge0"], ["Face99"], ["Child.Edge1"]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                g.erase_elements(shape, names)
        self.assertEqual(len(shape.Faces), 7)


class EraseDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SimpleCADEraseTest")
        self.doc.UndoMode = 1
        self.obj = op.new_shape(self.doc, divided_box(), "Divided block")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_merge_undo_redo_preserves_object_identity(self):
        name, count = self.obj.Name, self.doc.UndoCount
        op.delete_selection([(self.obj, [dividers(self.obj.Shape)[0][0]])])
        self.assertEqual(self.doc.getObject(name), self.obj)
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), 7)
        self.doc.redo()
        self.assertEqual(len(self.obj.Shape.Faces), 6)

    def test_angled_edge_undo_redo_and_native_save_reopen(self):
        self.obj.Shape = Part.makeBox(40, 30, 10)
        op.delete_selection([(self.obj, ["Edge1"])])
        self.assertEqual(len(self.obj.Shape.Faces), 4)
        self.assertEqual(len(self.obj.Shape.Solids), 0)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Solids), 1)
        self.doc.redo()
        name = self.obj.Name
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "open-surfaces.FCStd")
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            result = self.doc.getObject(name)
            self.assertEqual(len(result.Shape.Faces), 4)
            self.assertEqual(len(result.Shape.Solids), 0)
            self.assertTrue(result.Shape.isValid())

    def test_rotated_translated_merge_and_angled_edge_removal(self):
        self.obj.Placement = App.Placement(V(60, 80, 100), App.Rotation(V(1, 2, 3), 37))
        before = self.obj.Shape.copy()
        op.delete_selection([(self.obj, [dividers(before)[0][0]])])
        self.assertLess((self.obj.Shape.CenterOfMass - before.CenterOfMass).Length, 1e-6)
        self.assertAlmostEqual(self.obj.Shape.common(before).Volume, 12000)
        current = self.obj.Shape.copy()
        expected = g.erase_elements(current, ["Edge1"])
        op.delete_selection([(self.obj, ["Edge1"])])
        self.assertAlmostEqual(self.obj.Shape.common(expected).Area, expected.Area)

    def test_selection_batch_is_atomic_and_rejects_invalid_subselection(self):
        other = op.new_shape(self.doc, Part.makeBox(10, 10, 10, V(60, 0, 0)), "Other")
        count = self.doc.UndoCount
        with self.assertRaises(ValueError):
            op.delete_selection([(self.obj, [dividers(self.obj.Shape)[0][0]]), (other, ["Vertex1"])])
        self.assertEqual(len(self.obj.Shape.Faces), 7)
        self.assertEqual(len(other.Shape.Faces), 6)
        self.assertEqual(self.doc.UndoCount, count)
        op.delete_selection([(self.obj, [dividers(self.obj.Shape)[0][0]]), (other, ["Edge1"])])
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.assertEqual(len(other.Shape.Faces), 4)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), 7)
        self.assertEqual(len(other.Shape.Faces), 6)

    def test_whole_object_priority_and_standalone_edge_deletion(self):
        name = self.obj.Name
        op.delete_selection([(self.obj, ["Edge1"]), (self.obj, ())])
        self.assertIsNone(self.doc.getObject(name))
        self.doc.undo()
        edge = op.new_shape(self.doc, Part.makeLine(V(), V(1, 0, 0)), "Loose line")
        edge_name = edge.Name
        op.delete_selection([(edge, ["Edge1"])])
        self.assertIsNone(self.doc.getObject(edge_name))
        self.doc.undo()
        self.assertIsNotNone(self.doc.getObject(edge_name))

    def test_dependent_object_blocks_deleting_last_face(self):
        face = op.new_shape(self.doc, Part.makePlane(10, 10), "Surface")
        link = self.doc.addObject("App::FeaturePython", "Dependent")
        link.addProperty("App::PropertyLink", "Source")
        link.Source = face
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, "depends"):
            op.delete_selection([(face, ["Edge1"])])
        self.assertIsNotNone(self.doc.getObject(face.Name))
        self.assertEqual(self.doc.UndoCount, count)

    def test_delete_curved_ellipse_dividing_edge_on_partitioned_solid(self):
        from simplecad.modeling.offsetting import partition
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = self.doc.addObject("Part::Feature", "CurvedBody")
        obj.Shape = solid
        ellipse_curve = Part.Ellipse(V(20, 20, 10), 9.0, 7.0).toShape()
        plane = g.Plane.named("XY", V(20, 20, 10))
        part, _ = partition(obj.Shape, ellipse_curve, plane)
        obj.Shape = part
        initial_faces = len(obj.Shape.Faces)
        # Find ellipse edge
        ellipse_edge = next(f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1) if hasattr(e.Curve, "MajorRadius"))
        changed, seams = op.delete_selection([(obj, [ellipse_edge])])
        self.assertEqual(changed, 1)
        self.assertEqual(seams, 0)
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertEqual(obj.Shape.ShapeType, "Solid")
        self.assertLess(len(obj.Shape.Faces), initial_faces)

    def test_delete_internal_edge_on_solid_preserves_face_and_solid(self):
        from simplecad.modeling.offsetting import partition
        box = Part.makeBox(40, 40, 10)
        arc = Part.Arc(V(15, 20, 10), V(20, 25, 10), V(25, 20, 10)).toShape()
        plane = g.Plane.named("XY", V(20, 20, 10))
        part, _ = partition(box, arc, plane)
        obj = self.doc.addObject("Part::Feature", "InternalBody")
        obj.Shape = part
        initial_faces = len(obj.Shape.Faces)
        initial_edges = len(obj.Shape.Edges)
        # Find internal arc edge
        arc_edge = next(f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1) if hasattr(e.Curve, "Radius"))
        changed, seams = op.delete_selection([(obj, [arc_edge])])
        self.assertEqual(changed, 1)
        self.assertEqual(seams, 0)
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertEqual(obj.Shape.ShapeType, "Solid")
        self.assertEqual(len(obj.Shape.Faces), initial_faces)
        self.assertEqual(len(obj.Shape.Edges), initial_edges - 1)

    def test_delete_selection_performance_with_unrelated_dense_object(self):
        import time, math
        # Create dense object far away
        N = 300
        poly = Part.makePolygon([V(200 + 10*math.cos(i*6.28/N), 200 + 10*math.sin(i*6.28/N), 0) for i in range(N+1)])
        dense_prism = Part.Face(poly).extrude(V(0, 0, 10))
        dense_obj = self.doc.addObject("Part::Feature", "DenseObj")
        dense_obj.Shape = dense_prism
        t0 = time.perf_counter()
        changed, seams = op.delete_selection([(self.obj, [dividers(self.obj.Shape)[0][0]])])
        t1 = time.perf_counter()
        self.assertEqual(changed, 1)
        self.assertLess(t1 - t0, 0.2)  # Must complete quickly without lag

    def test_delete_dividing_arc_between_crescent_and_plate_merges_faces(self):
        """Deleting dividing arc between hole crescent and plate top merges faces and keeps closed solid."""
        from simplecad.modeling import rotation
        box = Part.makeBox(40, 40, 10)
        cyl = Part.makeCylinder(5, 10)
        cyl.translate(V(20, 20, 0))
        solid = box.cut(cyl).Solids[0]
        obj = op.new_shape(self.doc, solid, "PlateWithHole")

        rim_name = next(f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1)
                        if isinstance(getattr(e, "Curve", None), Part.Circle) and abs(e.CenterOfMass.z - 10.0) < 1e-4)
        op.elongate(obj, rim_name, 4.0, V(1, 1, 0), mode="ellipse")

        # Rotate half ellipse
        sel_names = [f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1)
                     if isinstance(getattr(e, "Curve", None), Part.Ellipse) and e.CenterOfMass.x > 20.0 and abs(e.CenterOfMass.z - 10.0) < 1e-4]
        targets = op.prepare_rotation([(obj, tuple(sel_names))])
        frames = rotation.frames([s for _, s in targets], axis="FaceNormal", pivot="CurveCenter", targets=targets)
        op.commit_rotation(targets, frames, -90.0, copy=True)

        # Pick the dividing arc between crescent and main plate face
        crescent_div_edge = next(
            f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1)
            if abs(e.CenterOfMass.z - 10.0) < 1e-4 and isinstance(getattr(e, "Curve", None), Part.Ellipse)
            and len([f for f in obj.Shape.Faces if any(e.isSame(fe) for fe in f.Edges)]) >= 2
        )
        vol_before = obj.Shape.Volume
        faces_before = len(obj.Shape.Faces)
        changed, seams = op.delete_selection([(obj, [crescent_div_edge])])
        self.assertEqual(changed, 1)
        self.assertEqual(obj.Shape.ShapeType, "Solid")
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertEqual(len(obj.Shape.Solids), 1)
        self.assertAlmostEqual(obj.Shape.Volume, vol_before, places=3)
        self.assertLess(len(obj.Shape.Faces), faces_before)

    def test_merge_coplanar_face_group_reversed_normal_and_tolerances(self):
        """merge_coplanar_face_group merges faces even when one is reversed and has small gap."""
        f1 = Part.Face(Part.makePolygon([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(0, 10, 0), V(0, 0, 0)]))
        f2 = Part.Face(Part.makePolygon([V(10.0001, 0, 0), V(20, 0, 0), V(20, 10, 0), V(10.0001, 10, 0), V(10.0001, 0, 0)]))
        f2.reverse()
        merged = g.merge_coplanar_face_group([f1, f2], expected_area=200.0)
        self.assertTrue(merged.isValid())
        self.assertAlmostEqual(merged.Area, 200.0, places=2)
        self.assertAlmostEqual(g.face_normal(merged).dot(V(0, 0, 1)), 1.0, places=4)

    def test_delete_dividing_arcs_across_multiple_crescents_maintains_solid(self):
        """Deleting multiple dividing arcs across rotated crescents preserves valid solid volume."""
        from simplecad.modeling import rotation
        box = Part.makeBox(60, 60, 10)
        cyl = Part.makeCylinder(5, 10, V(30, 30, 0))
        solid = box.cut(cyl).Solids[0]
        obj = op.new_shape(self.doc, solid, "MultiPlate")

        rim = next(f"Edge{i}" for i, e in enumerate(obj.Shape.Edges, 1)
                   if isinstance(getattr(e, "Curve", None), Part.Circle) and abs(e.CenterOfMass.z - 10.0) < 1e-4)
        op.elongate(obj, rim, 4.0, V(1, 1, 0).normalize(), mode="ellipse")

        # Rotate half ellipse
        candidates = [f"Edge{i}" for i, ed in enumerate(obj.Shape.Edges, 1)
                      if isinstance(getattr(ed, "Curve", None), Part.Ellipse) and ed.CenterOfMass.x > 30.0 and ed.CenterOfMass.y > 30.0 and abs(ed.CenterOfMass.z - 10.0) < 1e-4]
        targets = op.prepare_rotation([(obj, tuple(candidates))])
        frames = rotation.frames([s for _, s in targets], axis="FaceNormal", pivot="CurveCenter", targets=targets)
        op.commit_rotation(targets, frames, 90.0, copy=True)

        # Find all dividing ellipse edges on the top face
        dividing_edges = []
        for i, edge in enumerate(obj.Shape.Edges, 1):
            if abs(edge.CenterOfMass.z - 10.0) < 1e-4 and isinstance(getattr(edge, "Curve", None), Part.Ellipse):
                adj = [f for f in obj.Shape.Faces if any(edge.isSame(fe) for fe in f.Edges)]
                if len(adj) >= 2 and g.coplanar(*adj[:2]):
                    dividing_edges.append(f"Edge{i}")

        self.assertGreater(len(dividing_edges), 0)
        vol_before = obj.Shape.Volume
        # Delete first dividing edge
        changed, _ = op.delete_selection([(obj, [dividing_edges[0]])])
        self.assertEqual(changed, 1)
        self.assertEqual(obj.Shape.ShapeType, "Solid")
        self.assertTrue(obj.Shape.isValid())
        self.assertTrue(obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume, vol_before, places=2)

    def test_merge_coplanar_faces_with_differing_plane_surfaces(self):
        """merge_coplanar_face_group unifies underlying Geom_Plane surfaces that have micro-angle deviations."""
        # Face 1 on exact XY plane
        p1 = Part.Plane(V(0, 0, 4), V(0, 0, 1))
        w1 = Part.makePolygon([V(0, 0, 4), V(10, 0, 4), V(10, 10, 4), V(0, 10, 4), V(0, 0, 4)])
        f1 = Part.Face(p1, w1)

        # Face 2 on a plane with a 5e-6 radian tilt
        p2 = Part.Plane(V(0.1, -3.5, 4.00001), V(3e-6, -2.8e-6, 1.0).normalize())
        w2 = Part.makePolygon([V(10, 0, 4), V(20, 0, 4), V(20, 10, 4), V(10, 10, 4), V(10, 0, 4)])
        f2 = Part.Face(p2, w2)

        self.assertTrue(g.coplanar(f1, f2))
        merged = g.merge_coplanar_face_group([f1, f2], expected_area=200.0)
        self.assertTrue(merged.isValid())
        self.assertEqual(len(merged.Faces) if hasattr(merged, "Faces") else 1, 1)
        self.assertAlmostEqual(merged.Area, 200.0, places=2)


    def top_edge(self, obj, x0, x1, y0, y1, z):
        """The edge of obj lying along the given span at height z."""
        return next("Edge%d" % i for i, e in enumerate(obj.Shape.Edges, 1)
                    if all(abs(a - b) < 1e-6 for a, b in zip(
                        (e.BoundBox.XMin, e.BoundBox.XMax, e.BoundBox.YMin, e.BoundBox.YMax, e.BoundBox.ZMin, e.BoundBox.ZMax),
                        (x0, x1, y0, y1, z, z))))

    def test_line_between_flush_solids_joins_them_and_merges_their_tops(self):
        # It used to strip both tops and the wall under the line, leaving two
        # open shells.
        first = op.new_shape(self.doc, Part.makeBox(10, 10, 10), "First")
        second = op.new_shape(self.doc, Part.makeBox(10, 10, 10, V(10, 0, 0)), "Second")
        name, count = second.Name, self.doc.UndoCount
        op.delete_selection([(first, [self.top_edge(first, 10, 10, 0, 10, 10)])])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(first.Shape.ShapeType, "Solid")
        self.assertTrue(first.Shape.isValid())
        self.assertAlmostEqual(first.Shape.Volume, 2000)
        self.assertEqual([round(f.Area, 6) for f in first.Shape.Faces if abs(f.CenterOfMass.z - 10) < 1e-9], [200])
        self.doc.undo()
        self.assertEqual(sorted(round(o.Shape.Volume, 6) for o in self.doc.Objects if o.Shape.Solids), [1000, 1000, 12000])

    def test_line_on_regions_pulled_from_a_sheet_merges_the_top(self):
        # A rectangle drawn across a circle on a sheet, each region pulled up
        # alone: deleting a line on the cylinder's top merges it again.
        self.doc.removeObject(self.obj.Name)
        ground = g.Plane.named("XY")
        sheet = op.new_shape(self.doc, Part.makePlane(100, 80), "Sheet")
        op.draw_circle(self.doc, g.circle(ground, V(50, 40, 0), 20), sheet)
        op.draw_profile(self.doc, g.rectangle(ground, V(50, 40, 0), V(78, 55, 0)), sheet, "Rectangle")
        pulled = []
        for point in (V(35, 40, 0), V(55, 45, 0), V(75, 50, 0)):
            obj, face = next((obj, face) for obj in self.doc.Objects
                             for face in obj.Shape.Faces if face.isInside(point, 1e-6, True))
            op.extrude(obj, face, 20)
            pulled.append(next(o for o in self.doc.Objects if o.Shape.Solids and o.Shape.isInside(point + V(0, 0, 10), 1e-6, True)))
        cylinder, quarter, beside = pulled
        name, count = quarter.Name, self.doc.UndoCount
        line = self.top_edge(cylinder, 50, 50 + 175 ** .5, 55, 55, 20)
        op.delete_selection([(cylinder, [line])])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(cylinder.Shape.ShapeType, "Solid")
        self.assertTrue(cylinder.Shape.isValid())
        self.assertAlmostEqual(cylinder.Shape.Volume, math.pi * 400 * 20, places=3)
        top = [f.Area for f in cylinder.Shape.Faces if abs(f.CenterOfMass.z - 20) < 1e-9]
        self.assertEqual(len(top), 1)
        self.assertAlmostEqual(top[0], math.pi * 400, places=3)
        # The block pulled beside the cylinder is untouched.
        self.assertEqual(len(beside.Shape.Faces), 6)
        self.assertTrue(beside.Shape.isValid())

if __name__ == "__main__":
    unittest.main()


