"""Subdivide one surface without also splitting existing intersections."""
import unittest
import FreeCAD as App
import Part
from simplecad.modeling import subdivision as s
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
V = App.Vector


def polygon(points):
    points = [V(*p) for p in points]
    return Part.Face(Part.makePolygon(points + points[:1]))


class SurfaceSubdivisionTests(unittest.TestCase):
    def check_neighbors(self, source, index, result, regions, count):
        self.assertTrue(result.isValid())
        self.assertEqual(len(regions), count)
        self.assertEqual(len(result.Faces), len(source.Faces) + count - 1)
        self.assertAlmostEqual(result.Area, source.Area, places=5)
        self.assertAlmostEqual(sum(f.Area for f in regions), source.Faces[index].Area, places=5)
        self.assertTrue(all(any(f.isSame(native) for native in result.Faces) for f in regions))
        remaining = [f for f in result.Faces if not any(f.isSame(part) for part in regions)]
        for i, original in enumerate(source.Faces):
            if i != index:
                self.assertTrue(any(coinc.same(original, f) for f in remaining))

    def test_overlapping_and_crossing_faces_do_not_affect_selected_pattern(self):
        selected = polygon([(0, 0, 0), (80, 0, 0), (100, 15, 0), (20, 15, 0)])
        crossing = polygon([(45, -20, -5), (45, 35, -5), (45, 35, 5), (45, -20, 5)])
        overlap = Part.makePlane(30, 9, V(30, 3, 0))
        far_a = Part.makePlane(20, 20, V(150, 0, 0))
        far_b = Part.makePlane(20, 20, V(155, 5, 0))
        for others in ([crossing], [overlap], [far_a, far_b]):
            # Put the picked face after another face, as in the user's Face2.
            source = Part.makeCompound(others[:1] + [selected] + others[1:])
            for pattern, n in (("fan", 1), ("fan", 2), ("spaced", 1), ("equal_area", 1)):
                result, parts = s.divide(source, 1, 4, 1, pattern=pattern, divisions=n)
                self.check_neighbors(source, 1, result, parts, 4 * n * n if pattern == "fan" else 4)

    def test_shared_edges_remain_connected_after_boundary_vertex_propagation(self):
        selected = Part.makePlane(60, 30)
        neighbor = polygon([(0, 0, 0), (60, 0, 0), (60, 0, -15), (0, 0, -15)])
        source = Part.makeShell([selected, neighbor]); source.sewShape()
        result, parts = s.divide(source, 0, 1, 3, pattern="spaced")
        self.check_neighbors(source, 0, result, parts, 3)
        wall = next(f for f in result.Faces if coinc.same(f, neighbor))
        self.assertEqual(len(wall.Edges), 6)
        for part in parts:
            common = [e for e in part.Edges if all(abs(v.Point.y) < 1e-7 for v in e.Vertexes)]
            self.assertEqual(len(common), 1)
            self.assertTrue(any(common[0].isSame(e) for e in wall.Edges))
        # An edge shared by two noncoplanar faces still erases both surfaces.
        shared = next(e for e in result.Edges if any(e.isSame(w) for w in wall.Edges)
                      and any(any(e.isSame(p) for p in f.Edges) for f in parts))
        name = next('Edge%d' % (i + 1) for i, e in enumerate(result.Edges) if e.isSame(shared))
        erased = g.erase_elements(result, [name])
        self.assertEqual(len(erased.Faces), 2)

    def test_nonmanifold_neighbors_receive_matching_boundary_edges(self):
        selected = Part.makePlane(60, 30)
        upper = polygon([(0, 0, 0), (60, 0, 0), (60, 0, 15), (0, 0, 15)])
        lower = polygon([(0, 0, 0), (60, 0, 0), (60, 0, -15), (0, 0, -15)])
        source = Part.makeCompound([upper, selected, lower])
        result, parts = s.divide(source, 1, 1, 3, pattern="spaced")
        self.check_neighbors(source, 1, result, parts, 3)
        for original in (upper, lower):
            wall = next(f for f in result.Faces if coinc.same(original, f))
            for part in parts:
                border = next(e for e in part.Edges if all(abs(v.Point.y) < 1e-7 for v in e.Vertexes))
                self.assertTrue(any(coinc.same(border, e) for e in wall.Edges))

    def test_existing_duplicate_surfaces_are_retained_not_cleaned_up(self):
        selected = Part.makePlane(60, 30)
        other = Part.makePlane(20, 10, V(100, 0, 0))
        duplicate = other.copy(); duplicate.reverse()
        source = Part.makeCompound([selected, other, duplicate])
        result, parts = s.divide(source, 0, 1, 1, pattern="fan", divisions=1)
        self.check_neighbors(source, 0, result, parts, 4)
        self.assertEqual(sum(coinc.same(f, other) for f in result.Faces), 2)

    def test_transformed_surface_with_loose_geometry_and_another_division(self):
        selected = Part.makePlane(60, 30)
        crossing = polygon([(25, -20, -5), (25, 35, -5), (25, 35, 5), (25, -20, 5)])
        loose = Part.makeLine(V(150, 0, 0), V(160, 0, 0)); point = Part.Vertex(V(170, 0, 0))
        source = Part.makeCompound([selected, crossing, loose, point])
        source.Placement = App.Placement(V(10, 40, 80), App.Rotation(V(1, 2, 3), 31))
        result, parts = s.divide(source, 0, 1, 1, pattern="fan", divisions=2)
        self.check_neighbors(source, 0, result, parts, 16)
        self.assertTrue(any(coinc.same(e, source.Edges[-1]) for e in coinc.loose_edges(result)))
        self.assertTrue(any((v.Point - source.Vertexes[-1].Point).Length < 1e-7 for v in result.Vertexes))
        index = next(i for i, f in enumerate(result.Faces) if f.isSame(parts[0]))
        again, cells = s.divide(result, index, 1, 1, pattern="triangles", divisions=2)
        self.check_neighbors(result, index, again, cells, 4)

    def test_surface_preview_apply_undo_redo_preserves_other_faces(self):
        doc = App.newDocument("SurfaceSubdivision"); doc.UndoMode = 1
        try:
            selected = Part.makePlane(60, 30)
            crossing = polygon([(25, -20, -5), (25, 35, -5), (25, 35, 5), (25, -20, 5)])
            obj = op.new_shape(doc, Part.makeCompound([crossing, selected]), "Crossing surfaces")
            target = op.prepare_subdivision([(obj, ("Face2",))]); before = doc.UndoCount
            plan, parts = op.preview_subdivision(target, 1, 1, pattern="fan", divisions=1)
            self.assertTrue(obj.Shape.isSame(target[1])); self.assertEqual(doc.UndoCount, before)
            self.assertTrue(op.commit_subdivision(target, plan, 1, 1, region_count=4))
            # Document assignment copies topology; compare geometry to find the
            # committed faces, rather than requiring the preview's OCC handles.
            committed = [next(f for f in obj.Shape.Faces if coinc.same(f, part)) for part in parts]
            self.check_neighbors(target[1], 1, obj.Shape, committed, 4)
            self.assertEqual(doc.UndoCount, before + 1)
            doc.undo(); self.assertEqual(len(obj.Shape.Faces), 2)
            doc.redo(); self.assertEqual(len(obj.Shape.Faces), 5)
        finally:
            App.closeDocument(doc.Name)


if __name__ == '__main__':
    unittest.main()
