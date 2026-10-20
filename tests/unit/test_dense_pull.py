"""Dense open-shell Pull setup must not rebuild geometry just to preview it."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident as c
from simplecad.gui.pull_snapping import PullReferences
from simplecad.gui.snapping import Snapper
from test_dense_deletion import dense_box


class DensePullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shape = Part.makeShell(dense_box().Faces[2:])

    def test_preview_skips_remainder_and_ordinary_cap_height_search(self):
        shape = self.shape.copy()
        face = shape.Faces[0]
        original = shape.exportBrepToString()
        with patch.object(c, 'assemble', side_effect=AssertionError('Preview rebuilt the model')), \
             patch.object(g, 'prism_walls', wraps=g.prism_walls) as walls:
            base, selected, remainder, offset = g.pull_setup(shape, face, include_remainder=False)
        self.assertEqual(base.ShapeType, 'Face')
        self.assertTrue(selected.isSame(face))
        self.assertIsNone(remainder)
        self.assertEqual(offset, 0)
        self.assertLessEqual(walls.call_count, 1)
        self.assertEqual(original, shape.exportBrepToString())

    def test_committed_pull_preserves_native_remainder_and_source(self):
        shape = self.shape.copy()
        face = shape.Faces[0]
        shape.isValid()
        original = shape.exportBrepToString()
        solid, rest = g.plan_push_pull(shape, face, 2)
        self.assertTrue(solid.isValid() and solid.isClosed())
        self.assertAlmostEqual(solid.Volume, face.Area*2)
        self.assertTrue(rest.isValid())
        self.assertEqual(len(rest.Faces), len(shape.Faces)-1)
        self.assertAlmostEqual(rest.Area+face.Area, shape.Area)
        self.assertEqual(original, shape.exportBrepToString())
        native = {}
        for f in rest.Faces:
            native.setdefault(hash(f), []).append(f)
        for f in shape.Faces[1:]:
            self.assertTrue(any(f.isSame(other) for other in native.get(hash(f), ())))

    def test_reference_index_uses_one_seam_pass_on_dense_geometry(self):
        from simplecad.gui import pull_snapping
        obj = SimpleNamespace(Name='Dense', TypeId='Part::Feature', Shape=self.shape,
                              InList=[], ViewObject=SimpleNamespace(Visibility=True))
        with patch.object(pull_snapping, 'seam_indices', wraps=g.seam_indices) as seams:
            refs = PullReferences(SimpleNamespace(Objects=[obj]), None, App.Vector(0,0,20), App.Vector(0,0,1))
        self.assertEqual(seams.call_count, 1)
        self.assertGreater(len(refs.edges), 100)
        for distance, points in refs.edges:
            self.assertTrue(all(abs(point.z-20-distance)<g.EPS for point in points))

    def test_pull_does_not_build_unused_drawing_snap_index(self):
        class NoGeometry:
            @property
            def Objects(self):
                raise AssertionError('Unneeded drawing geometry scan')
        snapper = Snapper(NoGeometry(), None, collect=False)
        self.assertIsNotNone(snapper.settings)
        self.assertEqual((snapper.points, snapper.faces, snapper.edges), ([], [], []))
