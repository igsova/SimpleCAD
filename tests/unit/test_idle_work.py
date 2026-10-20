"""Unchanged state and repeated previews must not redo whole-model work.

These count the work done on dense inputs rather than timing it: a cache that
misses, or a search that scans everything, shows up as a count.
"""
from collections import Counter
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import FreeCAD as App
import Mesh
import Part

from simplecad.core import geometry as g
from simplecad.modeling import union
from simplecad.document import visibility
from simplecad.gui.previews import overlay as preview
from simplecad.mesh import curved as mesh_curved
from simplecad.gui import pull_snapping, face_browser
from simplecad.mesh import conversion as mc
from simplecad.mcp.api import ModelAPI
from simplecad.gui.pull_snapping import PullReferences
from simplecad.gui.surface_display import Surface
from test_dense_deletion import dense_box

V = App.Vector


class CountedFace:
    def __init__(self, counts):
        self.counts = counts

    def isSame(self, other):
        self.counts['isSame'] += 1
        return self is other


class PullCleanupTests(unittest.TestCase):
    def test_a_clean_solid_is_not_searched_for_loose_faces(self):
        counts = Counter()
        solid = NS(ShapeType='Solid', Volume=1000., Area=1000., Faces=[CountedFace(counts) for _ in range(2000)])
        solid.Solids = [solid]
        self.assertIs(g.drop_noise(solid, .1), solid)
        self.assertEqual(counts['isSame'], 0)

    def test_compounds_still_drop_thin_loose_faces_and_keep_real_ones(self):
        box = Part.makeBox(10, 10, 10)
        hairline = Part.makeCompound([box, Part.makePlane(.01, 5, V(20, 0, 0))])
        result = g.drop_noise(hairline, .1)
        self.assertEqual(result.ShapeType, 'Solid')
        self.assertAlmostEqual(result.Volume, 1000)
        sheet = Part.makeCompound([box, Part.makePlane(5, 5, V(20, 0, 0))])
        self.assertIs(g.drop_noise(sheet, .1), sheet)


class UnionNeighbourTests(unittest.TestCase):
    def test_only_faces_sharing_an_edge_are_compared(self):
        solid = dense_box(8)
        shared = sum(1 for edge in solid.Edges if len(solid.ancestorsOfType(edge, Part.Face)) == 2)
        with patch.object(g, 'coplanar', wraps=g.coplanar) as coplanar:
            result = union.merge_flat_neighbours(solid, .01)
        self.assertLessEqual(coplanar.call_count, shared)
        self.assertEqual(len(result.Faces), 6)
        self.assertAlmostEqual(result.Volume, 512, places=6)


def surface(n=2000):
    """A Surface over n faces whose color reads and writes are counted."""
    counts = Counter()

    class Color:
        def __init__(self, kind):
            self.kind = kind

        def getValue(self):
            counts[self.kind] += 1
            return (.5, .5, .5)
    parts = tuple([2] * n)
    native = NS(getField=lambda name: NS(getValues=lambda: parts))
    source = NS(diffuseColor=NS(getValues=lambda: [Color('source') for _ in range(n)]))
    colors = NS(getValues=lambda: [Color('display') for _ in range(n)], setNum=lambda count: None,
                setValues=lambda values: counts.update(['full']), set1Value=lambda i, c: counts.update(['single']))
    material = NS(diffuseColor=colors, transparency=NS(getValues=lambda: [0.]))
    mesh = NS(touch=lambda: None, materialIndex=NS(setNum=lambda count: None, setValues=lambda values: None))
    result = Surface.__new__(Surface)
    result.entries = [(None, native, source, None, None, None, material, mesh)]
    result.material_states, result.part_counts, result.applied_state, result.bases = {}, {}, {}, {}
    result.dirty, result.last = True, None
    return result, counts


class HighlightTests(unittest.TestCase):
    colors = ((0., 1., 0.), (0., 1., 1.))

    def test_unchanged_refresh_reads_nothing(self):
        shown, counts = surface()
        shown.update(set(), '', self.colors)
        counts.clear()
        for _ in range(20):
            shown.update(set(), '', self.colors)
        self.assertEqual(counts, Counter())

    def test_hover_rewrites_only_the_faces_it_leaves_and_enters(self):
        shown, counts = surface()
        shown.update(set(), '', self.colors)
        counts.clear()
        for i in range(60):
            shown.update(set(), 'Face%d' % (1 + i % 2), self.colors)
        self.assertEqual(counts['source'], 0)
        self.assertEqual(counts['display'], 0)
        self.assertLessEqual(counts['single'], 120)

    def test_a_material_change_is_read_again(self):
        shown, counts = surface()
        shown.update(set(), '', self.colors)
        counts.clear()
        shown.dirty = True  # As the source material's sensor reports.
        shown.update(set(), '', self.colors)
        self.assertEqual(counts['source'], 2000)


class FaceBrowserSelectionTests(unittest.TestCase):
    def browser(self, keys, n=2000):
        reads = Counter()

        class Child:
            def __init__(self, i):
                self.i = i

            def data(self, *args):
                reads['rows'] += 1
                return ('Doc', 'Part', 'Face%d' % self.i)
        children = [Child(i) for i in range(1, n + 1)]
        item = NS(childCount=lambda: len(children), child=lambda i: children[i], setExpanded=lambda value: None)
        ranges = []
        model = NS(select=lambda selection, flags: None)
        tree = NS(selectedItems=lambda: [], indexFromItem=lambda child: child.i, selectionModel=lambda: model)
        browser = NS(selection_keys=lambda: set(keys), chosen=None, doc_name='Doc',
                     records={'Part': {'item': item}}, tree=tree, populate=lambda name: None)
        qt = NS(QItemSelection=lambda: NS(select=lambda a, b: ranges.append((a, b))),
                QItemSelectionModel=NS(ClearAndSelect=1, Rows=2))
        return browser, reads, ranges, qt

    def test_polling_reads_no_rows_and_selects_runs(self):
        keys = {('Doc', 'Part', 'Face%d' % i) for i in (3, 4, 5, 9, 2001)}
        browser, reads, ranges, qt = self.browser(keys)
        with patch.object(face_browser, 'QtCore', qt):
            for _ in range(20):
                face_browser.FaceBrowser.sync_selection(browser)
        self.assertEqual(reads['rows'], 0)
        self.assertEqual(ranges[:2], [(3, 5), (9, 9)])  # Face 2001 has no row.

    def test_runs(self):
        self.assertEqual(face_browser.runs([]), [])
        self.assertEqual(face_browser.runs([1, 2, 3, 7, 9, 10]), [(1, 3), (7, 7), (9, 10)])
        self.assertEqual(face_browser.runs([1, 1, 2]), [(1, 2)])


class HiddenElementTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(visibility.forget_document, 'Hidden')

    def test_edge_queries_share_one_hidden_element_pass(self):
        obj = NS(Document=NS(Name='Hidden'), Name='Box', Shape=Part.makeBox(1, 1, 1),
                 ViewObject=NS(Visibility=True))
        hidden_edges = visibility.hidden_elements(obj.Shape, {1})[0]
        with patch.object(visibility, 'hidden_faces', return_value={1}), \
             patch.object(visibility, 'hidden_elements', wraps=visibility.hidden_elements) as rebuilt:
            for _ in range(20):
                answers = [visibility.element_visible(obj, 'Edge%d' % i) for i in range(1, 13)]
            self.assertEqual(rebuilt.call_count, 1)
            self.assertEqual(answers, [i not in hidden_edges for i in range(1, 13)])
            visibility.object_hidden_elements(obj, {1, 2})
            self.assertEqual(rebuilt.call_count, 2)  # Other hidden faces.
            moved = obj.Shape.copy()
            moved.translate(V(1, 0, 0))
            obj.Shape = moved
            visibility.object_hidden_elements(obj, {1, 2})
            self.assertEqual(rebuilt.call_count, 3)  # Another shape.


class MeshFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Fingerprints')
        self.doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(self.doc.Name))
        self.obj = self.doc.addObject('Mesh::Feature', 'Scan')
        self.obj.Mesh = Mesh.Mesh(Part.makeBox(10, 10, 10).tessellate(.1))

    def test_hashed_again_only_after_a_change(self):
        cache = mc.Fingerprints()
        self.addCleanup(App.removeDocumentObserver, cache)
        with patch.object(mc, 'fingerprint', wraps=mc.fingerprint) as hashed:
            first = cache.get(self.obj)
            for _ in range(20):
                self.assertEqual(cache.get(self.obj), first)
            self.assertEqual(hashed.call_count, 1)
            self.doc.openTransaction('Change')
            self.obj.Mesh = Mesh.Mesh(Part.makeBox(10, 10, 12).tessellate(.1))
            self.doc.commitTransaction()
            changed = cache.get(self.obj)
            self.assertNotEqual(changed, first)
            self.assertEqual(changed, mc.fingerprint(self.obj.Mesh))
            self.doc.undo()
            self.assertEqual(cache.get(self.obj), first)
            count = hashed.call_count
            self.obj.Placement = App.Placement(V(1, 0, 0), App.Rotation())
            cache.get(self.obj)
            self.assertEqual(hashed.call_count, count + 1)

    def test_revision_requests_do_not_rehash_an_unchanged_mesh(self):
        api = ModelAPI()
        with patch.object(mc, 'fingerprint', wraps=mc.fingerprint) as hashed:
            stamps = {api.revisions.get(self.doc) for _ in range(20)}
        self.assertEqual(len(stamps), 1)
        self.assertLessEqual(hashed.call_count, 1)


class OutlineTests(unittest.TestCase):
    def tearDown(self):
        preview._outlines.clear()

    def test_the_same_face_is_sampled_once(self):
        face = Part.makeCylinder(3, 5).Faces[0]
        with patch.object(preview, 'edges', wraps=preview.edges) as sampled:
            first = preview.outline(face)
            for _ in range(60):
                self.assertIs(preview.outline(face), first)
            self.assertEqual(sampled.call_count, 1)
            moved = face.copy()
            moved.translate(V(0, 0, 1))
            self.assertIsNot(preview.outline(moved), first)
            self.assertEqual(sampled.call_count, 2)


class PullReferenceProjectionTests(unittest.TestCase):
    def test_references_are_projected_once_per_camera(self):
        obj = NS(Name='Dense', TypeId='Part::Feature', Shape=dense_box(8), InList=[],
                 ViewObject=NS(Visibility=True))
        refs = PullReferences(NS(Objects=[obj]), None, V(0, 0, 20), V(0, 0, 1))
        points = sum(len(p) for _, p in refs.edges)
        calls = Counter()

        def screen(view, point):
            calls['screen'] += 1
            return point.x * 10, point.y * 10
        with patch.object(pull_snapping, 'screen', side_effect=screen), \
             patch.object(pull_snapping, 'ray', return_value=(V(0, 0, 100), V(0, 0, -1))), \
             patch.object(pull_snapping, 'pick', return_value=None):
            for _ in range(60):
                self.assertIsNone(refs.snap((-500, -500), 10))
            self.assertEqual(calls['screen'], points)
            with patch.object(pull_snapping, 'camera_state', return_value='orbited'):
                refs.snap((-500, -500), 10)
            self.assertEqual(calls['screen'], 2 * points)
            # A pointer on a reference still snaps to it.
            distance, line = refs.edges[0]
            self.assertIsNotNone(refs.snap((line[0].x * 10, line[0].y * 10), 10))


class ElementInspectionTests(unittest.TestCase):
    def test_adjacency_matches_a_full_search(self):
        doc = App.newDocument('Inspect')
        self.addCleanup(lambda: App.closeDocument(doc.Name))
        owner = doc.addObject('Part::Feature', 'Holed')
        owner.Shape = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(2, 20, V(5, 5, -5)))
        shape = owner.Shape
        api = ModelAPI()
        maps = api.element_maps(owner)
        with patch('simplecad.mcp.api.visibility.element_visible', return_value=True):
            for i, face in enumerate(shape.Faces, 1):
                expected = ['Edge%d' % j for j, e in enumerate(shape.Edges, 1) if any(e.isSame(x) for x in face.Edges)]
                self.assertEqual(api.describe_element(owner, 'Face', i, face, maps)['edges'], expected)
            for i, edge in enumerate(shape.Edges, 1):
                expected = ['Face%d' % j for j, f in enumerate(shape.Faces, 1) if any(edge.isSame(e) for e in f.Edges)]
                described = api.describe_element(owner, 'Edge', i, edge, maps)
                self.assertEqual(described['faces'], expected)
                self.assertEqual(described['seam'], g.is_seam_edge(shape, edge))
            self.assertEqual(api.describe_element(owner, 'Vertex', 1, shape.Vertexes[0])['point'],
                             [shape.Vertexes[0].Point.x, shape.Vertexes[0].Point.y, shape.Vertexes[0].Point.z])


class HolePairingTests(unittest.TestCase):
    def pairs_scanned(self, second_center):
        loops = [{'center': V(0, 0, 0), 'normal': V(0, 0, 1), 'radius': 1.},
                 {'center': second_center, 'normal': V(0, 0, -1), 'radius': 1.}]
        with patch.object(mesh_curved, '_triangle_data', return_value=object()), \
             patch.object(mesh_curved, '_has_cylindrical_wall', return_value=False) as scanned:
            mesh_curved.imprint_circular_holes(None, Part.makeBox(10, 10, 10), loops, .01, lambda text: None)
        return scanned.call_count

    def test_only_rims_on_one_axis_reach_the_triangle_scan(self):
        self.assertEqual(self.pairs_scanned(V(0, 0, 10)), 1)
        self.assertEqual(self.pairs_scanned(V(3, 0, 10)), 0)
        self.assertEqual(self.pairs_scanned(V(0, 0, 0)), 0)


if __name__ == '__main__':
    unittest.main()
