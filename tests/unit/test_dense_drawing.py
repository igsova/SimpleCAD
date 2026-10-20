"""Drawing a line on a dense converted solid touches only the faces under it.

A mesh-converted part has thousands of triangle faces. Splitting, validating
and snapping must work on the few faces a line meets, with the complete
boolean kept only as a fallback, while results stay exactly as checked.
"""
from collections import Counter
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import FreeCAD as App
import Part

from simplecad.core import geometry as g
from simplecad.modeling import drawing
from simplecad.gui import snapping
from simplecad.document import materials as material_mapping, operations as ops
from test_dense_deletion import dense_box

V = App.Vector


def top_triangles(shape, n):
    return [f for f in shape.Faces if abs(f.CenterOfMass.z - n) < 1e-9]


def quad(shape, n):
    """Two top triangles sharing a diagonal, and the quad's other diagonal."""
    first = next(f for f in top_triangles(shape, n) if 3 < f.CenterOfMass.x < 4 and 3 < f.CenterOfMass.y < 4)
    diagonal = max(first.Edges, key=lambda e: e.Length)
    second = next(f for f in top_triangles(shape, n) if not f.isSame(first)
                  and any(e.isSame(diagonal) for e in f.Edges))
    ends = [v.Point for v in diagonal.Vertexes]
    corners = [v.Point for f in (first, second) for v in f.Vertexes
               if all((v.Point - p).Length > 1e-9 for p in ends)]
    return first, second, diagonal, corners


class LocalSplitTests(unittest.TestCase):
    n = 10

    @classmethod
    def setUpClass(cls):
        cls.shape = dense_box(cls.n)

    def assert_local(self, result, added_faces):
        self.assertEqual(result.ShapeType, 'Solid')
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume, self.shape.Volume, places=6)
        self.assertAlmostEqual(result.Area, self.shape.Area, places=6)
        self.assertEqual(result.countElement('Face'), len(self.shape.Faces) + added_faces)
        kept = {hash(f) for f in result.Faces}
        unchanged = sum(1 for f in self.shape.Faces if hash(f) in kept)
        # Only the split faces and their rebuilt neighbours change identity.
        self.assertGreater(unchanged, len(self.shape.Faces) - 20)

    def test_a_line_across_two_faces_splits_only_them(self):
        _, _, _, (b, d) = quad(self.shape, self.n)
        with patch.object(g, 'split_whole', side_effect=AssertionError('Split the whole solid')):
            result, boundary = g.divide_face_with_edges(self.shape, g.line(b, d))
        self.assert_local(result, 2)
        self.assertAlmostEqual(boundary.Length, (d - b).Length)

    def test_a_line_ending_inside_an_edge_rebuilds_its_neighbour(self):
        first, _, diagonal, _ = quad(self.shape, self.n)
        corner = next(v.Point for v in first.Vertexes if not any(v.isSame(w) for w in diagonal.Vertexes))
        middle = diagonal.valueAt((diagonal.FirstParameter + diagonal.LastParameter) / 2)
        with patch.object(g, 'split_whole', side_effect=AssertionError('Split the whole solid')):
            result, _ = g.divide_face_with_edges(self.shape, g.line(corner, middle))
        self.assert_local(result, 1)

    def test_a_line_that_closes_nothing_skips_the_whole_boolean(self):
        first, _, _, _ = quad(self.shape, self.n)
        corner = first.Vertexes[0].Point
        with patch.object(g, 'split_whole', side_effect=AssertionError('Split the whole solid')):
            self.assertIsNone(g.divide_face_with_edges(self.shape, g.line(corner, first.CenterOfMass)))

    def test_a_rejected_local_split_falls_back_to_the_whole_boolean(self):
        _, _, _, (b, d) = quad(self.shape, self.n)
        with patch.object(g, 'check_local_split', side_effect=ValueError('Rejected')), \
             patch.object(g, 'split_whole', wraps=g.split_whole) as whole:
            result, _ = g.divide_face_with_edges(self.shape, g.line(b, d))
        self.assertEqual(whole.call_count, 1)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(result.countElement('Face'), len(self.shape.Faces) + 2)

    def test_a_flipped_piece_is_rejected(self):
        _, _, _, (b, d) = quad(self.shape, self.n)
        real = g.split_faces_locally

        def flipped(shape, faces, lines, index=None):
            result, history, pieces, removed, added = real(shape, faces, lines, index)
            # The first face's pieces face inward.
            inward = shape.replaceShape([(faces[0], Part.makeShell([p.reversed() for p in pieces[0]])),
                                         (faces[1], Part.makeShell(pieces[1]))])
            return inward, history, pieces, removed, added
        with patch.object(g, 'split_faces_locally', side_effect=flipped), \
             patch.object(g, 'split_whole', wraps=g.split_whole) as whole:
            result, _ = g.divide_face_with_edges(self.shape, g.line(b, d))
        self.assertEqual(whole.call_count, 1)  # The flip was caught; the whole boolean redid it.
        self.assertTrue(result.isValid() and result.isClosed())


class ChangeRecordTests(unittest.TestCase):
    def setUp(self):
        g._face_indexes.clear(), g._changes.clear()
        self.addCleanup(g._face_indexes.clear)
        self.addCleanup(g._changes.clear)

    def test_the_result_index_matches_a_fresh_listing(self):
        shape = dense_box(8)
        _, _, _, (b, d) = quad(shape, 8)
        result, _ = g.divide_face_with_edges(shape, g.line(b, d))
        derived = g.face_index(result, build=False)
        self.assertIsNotNone(derived)
        fresh = g.FaceIndex.build(result)
        rows = lambda index: sorted((hash(f), tuple(round(v, 9) for v in box), bool(flat))
                                    for f, box, flat in zip(index.faces, index.bounds, index.planar))
        self.assertEqual(rows(derived), rows(fresh))
        change = g.change_to(result)
        self.assertTrue(change.source.isSame(shape))
        self.assertEqual(len(change.added) - len(change.removed), 2)

    def test_seams_through_a_derived_index_match_a_full_pass(self):
        shape = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(2, 20, V(3, 5, -5)))
        result, _ = g.divide_face_with_edges(shape, g.line(V(6, 0, 10), V(10, 4, 10)))
        self.assertIsNotNone(g.face_index(result, build=False))
        indexed = g.seam_indices(result)
        g._face_indexes.clear()
        self.assertEqual(indexed, g.seam_indices(result))
        self.assertEqual(len(indexed), 1)

    def test_snaps_after_a_line_are_patched_without_listing_the_part(self):
        snapping._objects.clear()
        self.addCleanup(snapping._objects.clear)
        shape = dense_box(8)
        obj = source(shape)
        doc = NS(Name='Snaps', Objects=[obj])
        snapping.Snapper(doc, None)
        _, _, _, (b, d) = quad(shape, 8)
        obj.Shape = g.divide_face_with_edges(shape, g.line(b, d))[0]
        with patch.object(snapping.ObjectSnaps, 'collect', side_effect=AssertionError('Listed every face')):
            snapping.Snapper(doc, None)


def leaning_quad():
    """Two triangles of a converted quad; the far corner is lifted 0.2 microns."""
    a, b, c, d = V(0, 0, 0), V(10, 0, 0), V(10, 10, .0002), V(0, 10, 0)
    shell = Part.makeShell([Part.Face(Part.makePolygon([a, b, d, a])), Part.Face(Part.makePolygon([b, c, d, b]))])
    return shell, a, c


class NearlyCoplanarTests(unittest.TestCase):
    def test_a_line_across_leaning_triangles_divides_both(self):
        shell, a, c = leaning_quad()
        result, boundary = g.divide_face_with_edges(shell, g.line(a, c))
        self.assertEqual(len(result.Faces), 4)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Area, shell.Area, places=9)
        self.assertAlmostEqual(boundary.Length, (c - a).Length, places=6)
        middle = V(5, 5, .0001)
        self.assertEqual(sum(1 for f in result.Faces if f.distToShape(Part.Vertex(middle))[0] < 1e-3), 4)

    def test_drawing_it_leaves_no_duplicate_face_or_loose_line(self):
        doc = App.newDocument('Leaning')
        doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        shell, a, c = leaning_quad()
        obj = ops.new_shape(doc, shell, 'Quad')
        result, changed = ops.draw_line(doc, a, c, obj)
        self.assertIs(result, obj)
        self.assertTrue(changed)
        self.assertEqual(len(obj.Shape.Faces), 4)
        self.assertEqual([o.Name for o in doc.Objects], [obj.Name])

    def test_completion_does_not_draw_over_leaning_triangles(self):
        shell, a, c = leaning_quad()
        self.assertEqual(drawing.triangle_completions([shell], a, c), [])
        self.assertEqual(drawing.loop_completions([shell], g.line(a, c)), [])


class CompletionTests(unittest.TestCase):
    def test_an_open_line_reads_only_nearby_edges(self):
        shape = dense_box(10)
        first, _, _, _ = quad(shape, 10)
        corner, inside = first.Vertexes[0].Point, first.CenterOfMass
        with patch.object(drawing, 'split_at', wraps=drawing.split_at) as split, \
             patch.object(drawing.coinc, 'same', wraps=drawing.coinc.same) as same:
            self.assertEqual(drawing.triangle_completions([shape], corner, inside), [])
            self.assertEqual(drawing.loop_completions([shape], g.line(corner, inside)), [])
        self.assertLess(split.call_count, 20)
        self.assertLess(same.call_count, 20)

    def test_a_closing_line_still_completes_its_triangle(self):
        # Two sides of a triangle as one open wire: the third closes it.
        a, b, c = V(0, 0, 0), V(10, 0, 0), V(0, 10, 0)
        sides = Part.Wire([Part.makeLine(a, b), Part.makeLine(b, c)])
        faces = drawing.triangle_completions([sides], c, a)
        self.assertEqual(len(faces), 1)
        self.assertAlmostEqual(faces[0].Area, 50)
        loops = drawing.loop_completions([sides], g.line(c, a))
        self.assertEqual(len(loops), 1)
        self.assertAlmostEqual(loops[0].Area, 50)

    def test_the_local_overlap_test_agrees_with_the_whole_boolean(self):
        def square(x, y, z, size, normal=V(0, 0, 1)):
            plane = g.Plane.from_normal(V(x, y, z), normal)
            corners = [V(x, y, z) + plane.u * a + plane.v * b
                       for a, b in ((0, 0), (size, 0), (size, size), (0, size), (0, 0))]
            return Part.Face(Part.makePolygon(corners))

        notched = Part.makeBox(30, 30, 10).cut(Part.makeBox(20, 20, 12, V(10, 10, -1)))
        drum = Part.makeCylinder(10, 10, V(50, 0, 0))
        drum.tessellate(1)  # Display meshes sit inside the round wall.
        shapes = {'dense': dense_box(6), 'notched': notched, 'drum': drum,
                  'shell': Part.makeShell(dense_box(6).Faces[:20]),
                  'faces': Part.makeCompound(Part.makeBox(5, 5, 5, V(0, 0, 40)).Faces)}
        loops = [square(100, 100, 100, 3),          # far from everything
                 square(1, 1, 3, 2),                # inside the dense box
                 square(1, 1, 6, 2),                # on its top
                 square(-2, 1, 3, 4),               # through its side
                 square(15, 15, 5, 3),              # in the notch, inside the bounds
                 square(2, 2, 5, 3),                # inside the notched solid
                 square(48, -2, 5, 4),              # inside the drum
                 square(50, -1, 10.0005, 2),        # just above the drum
                 square(60.0004, -1, 5, 2, V(1, 0, 0)),  # just outside its round wall
                 square(1, 1, 40, 2),               # on a loose face
                 square(1, 1, 42, 2),               # between loose faces
                 square(4, 1, 6, 4),                # half on the dense top, half beyond
                 square(6, 4, .2, 1.5, V(1, 0, 0)),  # on the dense box's far side, partly on the shell
                 square(0, 1, 1, 2, V(1, 0, 0)),    # on its near side
                 square(2, 2, 6, 2, V(1, 0, 0)),    # upright, touching the top along a line
                 square(10, 12, 2, 3, V(1, 0, 0)),  # on the notch's inner wall
                 square(48, -1, 10, 2),             # on the drum's top
                 square(1, 1, 45, 2)]               # on the top loose face
        for name, shape in shapes.items():
            for i, face in enumerate(loops):
                with self.subTest(shape=name, loop=i):
                    self.assertEqual(drawing.overlaps(shape, face),
                                     shape.common(face).Area > drawing.TOL)

    def test_new_lines_reuse_the_edges_of_unchanged_shapes(self):
        shape = dense_box(6)
        first = drawing.edge_index([shape])
        line = g.line(V(-5, 0, 0), V(-5, 3, 0))
        second = drawing.edge_index([shape, line])
        self.assertIsNot(second, first)
        self.assertIs(second.parts[0], first.parts[0])
        fresh = drawing.EdgeIndex([shape, line])
        self.assertEqual(second.owners, fresh.owners)
        self.assertTrue(all(a.isSame(b) for a, b in zip(second.edges, fresh.edges)))
        self.assertTrue((second.low == fresh.low).all() and (second.high == fresh.high).all())
        changed = g.line(V(-5, 0, 0), V(-5, 4, 0))
        third = drawing.edge_index([shape, changed])
        self.assertIs(third.parts[0], first.parts[0])
        self.assertAlmostEqual(third.high[-1][1], 4)

    def test_a_line_between_holes_reaches_them_where_their_display_mesh_falls_short(self):
        holes = Part.makeCompound([Part.makeCylinder(10, 5, V(25, 15, 0)), Part.makeCylinder(10, 5, V(25, 50, 0))])
        plate = Part.makeBox(50, 65, 5).cut(holes)
        plate.tessellate(1)
        top = next(f for f in plate.Faces if abs(f.CenterOfMass.z - 5) < 1e-9)
        lower, upper = sorted((w for w in top.Wires if not w.isSame(top.OuterWire)), key=lambda w: w.CenterOfMass.y)
        # Mesh-based bounds stop short of the rims' facing points, where the
        # new line touches them; the region closes only through both rims.
        self.assertGreater(25 - lower.BoundBox.YMax, 2 * g.BOUNDS_MARGIN)
        self.assertGreater(upper.BoundBox.YMin - 40, 2 * g.BOUNDS_MARGIN)
        loose = [g.line(V(0, 15, 5), V(15, 15, 5)), g.line(V(0, 50, 5), V(15, 50, 5))]
        result, _ = g.divide_face_with_edges(plate, g.line(V(25, 25, 5), V(25, 40, 5)), loose)
        self.assertEqual(len(result.Faces), len(plate.Faces) + 1)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume, plate.Volume, places=6)


def source(shape, name='Dense'):
    return NS(Name=name, Shape=shape, TypeId='Part::Feature', InList=[], ViewObject=NS(Visibility=True))


class SnapIndexTests(unittest.TestCase):
    def setUp(self):
        snapping._objects.clear()
        self.addCleanup(snapping._objects.clear)

    @staticmethod
    def contents(snapper):
        points = Counter((tuple(round(c, 9) for c in point), label) for point, label in snapper.points)
        segments = Counter(tuple(sorted((tuple(round(c, 9) for c in a), tuple(round(c, 9) for c in b))))
                           for a, b in zip(snapper.segment_starts, snapper.segment_ends))
        return points, segments, len(snapper.faces)

    def test_reopening_an_unchanged_model_reads_nothing(self):
        doc = NS(Name='Snaps', Objects=[source(dense_box(8))])
        snapping.Snapper(doc, None)
        with patch.object(snapping.ObjectSnaps, 'face', side_effect=AssertionError('Read a face')), \
             patch.object(snapping.ObjectSnaps, 'edge', side_effect=AssertionError('Read an edge')):
            snapping.Snapper(doc, None)

    def test_after_a_line_only_new_pieces_are_read_and_the_index_is_exact(self):
        shape = dense_box(8)
        obj = source(shape)
        doc = NS(Name='Snaps', Objects=[obj])
        snapping.Snapper(doc, None)
        _, _, _, (b, d) = quad(shape, 8)
        obj.Shape = g.divide_face_with_edges(shape, g.line(b, d))[0]
        with patch.object(snapping.ObjectSnaps, 'face', wraps=snapping.ObjectSnaps.face) as faces, \
             patch.object(snapping.ObjectSnaps, 'edge', wraps=snapping.ObjectSnaps.edge) as edges:
            updated = snapping.Snapper(doc, None)
        self.assertLess(faces.call_count, 30)
        self.assertLess(edges.call_count, 60)
        snapping._objects.clear()
        self.assertEqual(self.contents(updated), self.contents(snapping.Snapper(doc, None)))

    def test_warm_up_leaves_nothing_for_the_tool_to_read(self):
        doc = NS(Name='Snaps', Objects=[source(dense_box(8))])
        options = snapping.snap_options(snapping.preferences.Settings())
        slices = sum(1 for _ in snapping.warm(doc, options))
        self.assertGreater(slices, 5)  # Spread over idle time, not one long call.
        with patch.object(snapping.ObjectSnaps, 'face', side_effect=AssertionError('Read a face')), \
             patch.object(snapping.ObjectSnaps, 'edge', side_effect=AssertionError('Read an edge')):
            snapping.Snapper(doc, None, settings=snapping.preferences.Settings())

    def test_a_tool_finishes_an_interrupted_warm_up_exactly(self):
        doc = NS(Name='Snaps', Objects=[source(dense_box(8))])
        settings = snapping.preferences.Settings()
        work = snapping.warm(doc, snapping.snap_options(settings))
        for _ in range(3):
            next(work)
        finished = snapping.Snapper(doc, None, settings=settings)
        snapping._objects.clear()
        self.assertEqual(self.contents(finished), self.contents(snapping.Snapper(doc, None, settings=settings)))

    def test_warm_up_drops_a_collection_replaced_by_an_edit(self):
        shape = dense_box(8)
        obj = source(shape)
        doc = NS(Name='Snaps', Objects=[obj])
        options = snapping.snap_options(snapping.preferences.Settings())
        work = snapping.warm(doc, options)
        next(work)
        stale = snapping._objects[(None, 'Dense')]  # Stand-in objects have no document.
        _, _, _, (b, d) = quad(shape, 8)
        obj.Shape = g.divide_face_with_edges(shape, g.line(b, d))[0]
        snapping.object_snaps(obj, options)
        list(work)
        self.assertFalse(stale.done)  # Abandoned rather than finished for the old shape.

    def test_faces_at_a_point_measure_only_nearby_faces(self):
        shape = dense_box(8)
        snapper = snapping.Snapper(NS(Name='Snaps', Objects=[source(shape)]), None)
        for point in (shape.Vertexes[40].Point, shape.Faces[100].CenterOfMass, V(4, 4, 8)):
            expected = [f for f in snapper.faces if g.point_on_face(f, point)
                        or (f.CenterOfMass - point).Length < g.EPS]
            with patch.object(snapping, 'point_on_face', wraps=snapping.point_on_face) as measured:
                found = snapper.faces_at(point)
            self.assertEqual([hash(f) for f in found], [hash(f) for f in expected])
            self.assertLess(measured.call_count, 20)
        self.assertTrue(snapper.has_face(shape.Faces[7]))
        self.assertFalse(snapper.has_face(Part.makePlane(1, 1)))

    def test_the_index_matches_every_vertex_edge_and_face(self):
        # Off center, so the rims' centers are not also their faces' centers.
        shape = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(2, 20, V(3, 5, -5)))
        snapper = snapping.Snapper(NS(Name='Snaps', Objects=[source(shape)]), None)
        labels = Counter(label for _, label in snapper.points)
        self.assertEqual(labels['Endpoint'], len(shape.Vertexes))
        self.assertEqual(labels['Face center'], sum(isinstance(f.Surface, Part.Plane) for f in shape.Faces))
        seams = g.seam_indices(shape)
        self.assertEqual(labels['Midpoint'], len(shape.Edges) - len(seams))
        self.assertEqual(labels['Circle center'], 2)  # The hole's two rims.


class MaterialMappingTests(unittest.TestCase):
    def test_unchanged_faces_are_not_measured(self):
        shape = dense_box(8)
        values = []
        for i, face in enumerate(shape.Faces):
            material = App.Material()
            material.DiffuseColor = (1., 0., 0., 0.) if i == 5 else (.5, .5, .5, 0.)
            values.append(material)
        _, _, _, (b, d) = quad(shape, 8)
        result = g.divide_face_with_edges(shape, g.line(b, d))[0]
        with patch.object(material_mapping, 'bounds', wraps=material_mapping.bounds) as bounds:
            mapped = material_mapping.mapped(shape, result, values)
        self.assertEqual(len(mapped), result.countElement('Face'))
        self.assertLess(bounds.call_count, 60)
        red = [i for i, m in enumerate(mapped) if m.DiffuseColor[0] > .9]
        self.assertEqual(len(red), 1)
        self.assertTrue(result.Faces[red[0]].isSame(shape.Faces[5]))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Settle')
        self.doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(self.doc.Name))

    def test_an_edited_plain_shape_keeps_its_native_identity(self):
        obj = ops.new_shape(self.doc, dense_box(6), 'Dense')
        _, _, _, (b, d) = quad(obj.Shape, 6)
        before = {hash(f) for f in obj.Shape.Faces}
        ops.draw_line(self.doc, b, d, obj)
        after = {hash(f) for f in obj.Shape.Faces}
        # Only the split faces and their rebuilt neighbours are new.
        self.assertGreater(len(before & after), len(before) - 20)
        self.assertNotIn('Touched', obj.State)
        self.doc.undo()
        self.assertEqual(obj.Shape.countElement('Face'), len(before))

    def test_objects_with_dependents_are_still_recomputed(self):
        base = ops.new_shape(self.doc, Part.makeBox(4, 4, 4), 'Base')
        other = self.doc.addObject('Part::Feature', 'Profile')
        other.addProperty('App::PropertyLink', 'SC_Support')
        other.SC_Support = base
        self.doc.recompute()
        with ops.transaction(self.doc, 'Edit'):
            base.Shape = Part.makeBox(4, 4, 6)
        self.assertNotIn('Touched', base.State)
        self.assertAlmostEqual(base.Shape.Volume, 96)


class FaceRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from simplecad.gui.qt import QtWidgets
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_rows_are_kept_and_only_changed_rows_restyled(self):
        from simplecad.gui.face_browser import FaceBrowser, ROLE
        from simplecad.gui.qt import QtWidgets
        browser = FaceBrowser(None)
        browser.tree = QtWidgets.QTreeWidget()
        browser.doc_name = 'Doc'
        item = QtWidgets.QTreeWidgetItem(browser.tree, ['Part'])
        shape = Part.makeBox(1, 1, 1)
        materials = [App.Material()]
        obj = NS(Name='Part', Shape=shape, isDerivedFrom=lambda kind: False,
                 ViewObject=NS(Visibility=True, ShapeAppearance=materials))
        browser.records = {'Part': {'item': item, 'shape': shape, 'face_count': 6}}
        with patch('simplecad.gui.face_browser.App.ActiveDocument', NS(getObject=lambda name: obj)), \
             patch.object(FaceBrowser, 'update_swatch', autospec=True) as swatch:
            browser.populate('Part')
            self.assertEqual(item.childCount(), 6)
            self.assertEqual(swatch.call_count, 7)  # The object and each face row.
            first = item.child(0)
            browser.records['Part']['face_count'] = 7
            browser.resize_rows('Part')
            self.assertIs(item.child(0), first)
            self.assertEqual([item.child(i).data(0, ROLE)[2] for i in range(7)], ['Face%d' % i for i in range(1, 8)])
            swatch.reset_mock()
            browser.records['Part'].pop('style')
            browser.update_eyes(obj, item)
            self.assertEqual(swatch.call_count, 2)  # The object and the one new row.
            browser.records['Part']['face_count'] = 3
            browser.resize_rows('Part')
            self.assertEqual(item.childCount(), 3)
            self.assertEqual(len(browser.records['Part']['rows']), 3)
        browser.tree.deleteLater()


if __name__ == '__main__':
    unittest.main()
