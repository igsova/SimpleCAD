"""Shape-following symmetry and fixed spacing on native planar geometry."""
import math
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


def regular(sides):
    return polygon([(20 * math.cos(i * 2 * math.pi / sides), 20 * math.sin(i * 2 * math.pi / sides), 0)
                    for i in range(sides)])


class SubdivisionPatternTests(unittest.TestCase):
    def check(self, source, index, result, parts, count=None):
        self.assertTrue(result.isValid())
        if count is not None:
            self.assertEqual(len(parts), count)
        self.assertEqual(len(result.Faces), len(source.Faces) + len(parts) - 1)
        self.assertAlmostEqual(result.Area, source.Area, places=5)
        self.assertAlmostEqual(sum(f.Area for f in parts), source.Faces[index].Area, places=5)
        if source.Solids:
            self.assertEqual(len(result.Solids), 1)
            self.assertTrue(result.isClosed())
            self.assertAlmostEqual(result.Volume, source.Volume, places=5)
        for f in parts:
            self.assertAlmostEqual(f.common(source.Faces[index]).Area, f.Area, places=5)

    def test_triangle_grid_makes_similar_small_triangles(self):
        for source in (regular(3), polygon([(0, 0, 0), (60, 0, 0), (15, 40, 0)])):
            lengths = sorted(e.Length for e in source.Edges)
            for n in (1, 2, 3, 5, 10):
                result, parts = s.divide(source, 0, 1, 1, pattern="triangles", divisions=n)
                self.check(source, 0, result, parts, n * n)
                for f in parts:
                    self.assertEqual(len(f.Edges), 3)
                    self.assertAlmostEqual(f.Area, source.Area / (n * n), places=5)
                    for actual, expected in zip(sorted(e.Length for e in f.Edges), lengths):
                        self.assertAlmostEqual(actual * n, expected, places=5)

    def test_regular_polygon_fan_and_triangle_preserve_rotational_symmetry(self):
        for sides in (3, 5, 6):
            source = regular(sides)
            pattern = "triangles" if sides == 3 else "fan"
            result, parts = s.divide(source, 0, 1, 1, pattern=pattern, divisions=2)
            self.check(source, 0, result, parts, 4 if sides == 3 else sides * 4)
            for part in parts:
                self.assertEqual(len(part.Edges), 3)
                rotated = part.copy(); rotated.rotate(V(), V(0, 0, 1), 360 / sides)
                self.assertTrue(any(coinc.same(rotated, other) for other in parts))
                self.assertAlmostEqual(part.Area, source.Area / len(parts), places=5)

    def test_irregular_convex_fan_follows_corners_without_area_rebalancing(self):
        source = polygon([(0, 0, 0), (60, 0, 0), (55, 25, 0), (30, 40, 0), (0, 15, 0)])
        result, parts = s.divide(source, 0, 1, 1, pattern="fan", divisions=1)
        self.check(source, 0, result, parts, 5)
        self.assertGreater(max(f.Area for f in parts) - min(f.Area for f in parts), 1)
        for f in parts:
            self.assertTrue(any((v.Point - source.CenterOfMass).Length < 1e-7 for v in f.Vertexes))

    def test_disk_fan_preserves_arcs_and_equal_angles(self):
        source = g.circle(g.Plane.named(), V(), 20)
        for n in (1, 2, 3, 8):
            result, parts = s.divide(source, 0, 1, 1, 23, pattern="fan", divisions=n)
            self.check(source, 0, result, parts, n)
            for f in parts:
                self.assertAlmostEqual(f.Area, source.Area / n, places=5)
            if n > 1:
                # The original periodic seam may divide one analytic arc in two.
                arcs = [e for e in result.Edges if isinstance(e.Curve, Part.Circle)]
                self.assertAlmostEqual(sum(e.Length for e in arcs), 40 * math.pi, places=5)

    def test_spaced_triangle_rows_and_columns_have_equal_width_not_area(self):
        source = polygon([(0, 0, 0), (60, 0, 0), (30, 40, 0)])
        for rows, cols, axis, width in ((4, 1, 1, 10), (1, 5, 0, 12)):
            result, parts = s.divide(source, 0, rows, cols, pattern="spaced")
            self.check(source, 0, result, parts, rows * cols)
            for f in parts:
                self.assertAlmostEqual(f.BoundBox.YLength if axis else f.BoundBox.XLength, width, places=5)
            self.assertGreater(max(f.Area for f in parts) - min(f.Area for f in parts), 1)

    def test_spaced_grid_clips_empty_and_disconnected_cells_without_shifting(self):
        source = polygon([(0, 0, 0), (60, 0, 0), (30, 40, 0)])
        result, parts = s.divide(source, 0, 3, 3, pattern="spaced")
        self.check(source, 0, result, parts, 7)
        # Unlike area balancing, a column stays at x=20/40 across every row.
        for e in result.Edges:
            if len(e.Vertexes) == 2:
                a, b = [v.Point for v in e.Vertexes]
                if abs(a.x - b.x) < 1e-7:
                    self.assertTrue(any(abs(a.x - x) < 1e-6 for x in (20, 40)))
        notch = polygon([(0, 0, 0), (10, 0, 0), (10, 30, 0), (30, 30, 0),
                         (30, 0, 0), (40, 0, 0), (40, 40, 0), (0, 40, 0)])
        result, parts = s.divide(notch, 0, 4, 1, 90, pattern="spaced")
        self.check(notch, 0, result, parts, 7)

    def test_spaced_curved_outline_and_hole_keep_analytic_boundaries(self):
        disk = g.circle(g.Plane.named(), V(), 20)
        ring = disk.cut(g.circle(g.Plane.named(), V(), 5)).Faces[0]
        for source in (disk, ring):
            result, parts = s.divide(source, 0, 1, 4, 31, pattern="spaced")
            self.check(source, 0, result, parts, 4)
            self.assertTrue(any(isinstance(e.Curve, Part.Circle) for e in result.Edges))

    def test_rotated_reversed_triangle_solid_and_existing_neighbors(self):
        prism = regular(3).extrude(V(0, 0, 12))
        prism.Placement = App.Placement(V(70, -30, 20), App.Rotation(V(1, 2, 3), 39))
        index = next(i for i, f in enumerate(prism.Faces) if len(f.Edges) == 3)
        result, parts = s.divide(prism, index, 1, 1, pattern="triangles", divisions=3)
        self.check(prism, index, result, parts, 9)
        for i, other in enumerate(prism.Faces):
            if i != index:
                self.assertTrue(any(coinc.same(other, f) for f in result.Faces))
        for f in parts:
            for d in (-1, 1):
                pulled = g.push_pull(result, f, d)
                self.assertTrue(pulled.isValid())
                self.assertAlmostEqual(pulled.Volume, prism.Volume + f.Area * d, places=5)
        reversed_face = regular(3); reversed_face.reverse()
        result, parts = s.divide(reversed_face, 0, 1, 1, pattern="triangles", divisions=2)
        self.check(reversed_face, 0, result, parts, 4)
        self.assertTrue(all(g.face_normal(f).dot(g.face_normal(reversed_face)) > .99999 for f in parts))

    def test_defaults_recognize_outline_including_collinear_splits(self):
        rectangle = polygon([(0, 0, 0), (30, 0, 0), (60, 0, 0), (60, 40, 0), (0, 40, 0)])
        for face, expected in ((rectangle, "spaced"), (regular(3), "triangles"),
                               (regular(5), "fan"), (regular(6), "fan"),
                               (g.circle(g.Plane.named(), V(), 20), "fan")):
            face.Placement = App.Placement(V(30, 20, 10), App.Rotation(V(1, 2, 3), 27))
            self.assertEqual(s.Profile(face).default_pattern(), expected)
        triangle = polygon([(0, 0, 0), (30, 0, 0), (60, 0, 0), (0, 40, 0)])
        result, parts = s.divide(triangle, 0, 1, 1, pattern="triangles", divisions=3)
        self.check(triangle, 0, result, parts, 9)

    def test_invalid_patterns_limits_and_unsupported_fans_do_not_change_source(self):
        source = regular(5)
        for pattern, steps in (("triangles", 3), ("unknown", 3), ("fan", 5), ("fan", 0), ("fan", True)):
            with self.assertRaises(ValueError): s.divide(source, 0, 1, 1, pattern=pattern, divisions=steps)
        notch = polygon([(0, 0, 0), (40, 0, 0), (40, 10, 0), (10, 10, 0), (10, 40, 0), (0, 40, 0)])
        self.assertEqual(s.Profile(notch).default_pattern(), "spaced")
        with self.assertRaisesRegex(ValueError, "convex"):
            s.divide(notch, 0, 1, 1, pattern="fan", divisions=1)
        ring = g.circle(g.Plane.named(), V(), 20).cut(g.circle(g.Plane.named(), V(), 5)).Faces[0]
        self.assertEqual(s.Profile(ring).default_pattern(), "spaced")
        with self.assertRaisesRegex(ValueError, "convex"):
            s.divide(ring, 0, 1, 1, pattern="fan", divisions=3)

    def test_actual_clipped_count_commits_in_one_undo_step(self):
        doc = App.newDocument("SpacedSubdivisionTest"); doc.UndoMode = 1
        try:
            source = polygon([(0, 0, 0), (60, 0, 0), (30, 40, 0)])
            obj = op.new_shape(doc, source, "Triangle")
            target = op.prepare_subdivision([(obj, ())]); count = doc.UndoCount
            planned, parts = op.preview_subdivision(target, 3, 3, pattern="spaced")
            self.assertEqual(len(parts), 7); self.assertTrue(obj.Shape.isSame(target[1]))
            self.assertEqual(doc.UndoCount, count)
            self.assertTrue(op.commit_subdivision(target, planned, 3, 3, region_count=len(parts)))
            self.assertEqual(len(obj.Shape.Faces), 7); self.assertEqual(doc.UndoCount, count + 1)
            doc.undo(); self.assertEqual(len(obj.Shape.Faces), 1)
            doc.redo(); self.assertEqual(len(obj.Shape.Faces), 7)
        finally:
            App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
