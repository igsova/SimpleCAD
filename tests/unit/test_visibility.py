"""Visibility metadata identifies topology without modifying its geometry."""
from pathlib import Path
import tempfile
import unittest
import FreeCAD as App
import Part
from simplecad.document import visibility as v


class VisibilityGeometryTests(unittest.TestCase):
    def test_shared_box_boundaries_remain_until_all_owners_are_hidden(self):
        box = Part.makeBox(10, 10, 10)
        self.assertEqual(v.hidden_elements(box, {6}), (set(), set()))
        edges, vertices = v.hidden_elements(box, {1, 2, 3, 4, 5, 6})
        self.assertEqual(edges, set(range(1, 13)))
        self.assertEqual(vertices, set(range(1, 9)))
        self.assertAlmostEqual(box.Volume, 1000)

    def test_disjoint_surfaces_and_loose_geometry_keep_independent_visibility(self):
        a = Part.makePlane(10, 10)
        b = Part.makePlane(10, 10, App.Vector(20, 0, 0))
        line = Part.makeLine(App.Vector(0, 20, 0), App.Vector(10, 20, 0))
        shape = Part.makeCompound([a, b, line])
        edges, vertices = v.hidden_elements(shape, {1})
        self.assertEqual(len(edges), 4); self.assertEqual(len(vertices), 4)
        self.assertTrue(all(any(shape.Edges[i-1].isSame(e) for e in a.Edges) for i in edges))
        self.assertEqual(len(shape.Edges), 9)

    def test_curved_wall_seam_is_hidden_but_shared_rims_remain(self):
        cylinder = Part.makeCylinder(5, 10)
        edges, vertices = v.hidden_elements(cylinder, {1})
        self.assertEqual(len(edges), 1)
        self.assertFalse(vertices)
        self.assertAlmostEqual(cylinder.Edges[next(iter(edges))-1].Length, 10)

    def test_signature_ignores_placement_and_tessellation(self):
        shape = Part.makeCylinder(5, 10)
        original = v.signature(shape)
        shape.tessellate(.1)
        self.assertEqual(v.signature(shape), original)
        shape.Placement = App.Placement(App.Vector(50, 20, 10), App.Rotation(App.Vector(1, 2, 3), 37))
        self.assertEqual(v.signature(shape), original)
        self.assertNotEqual(v.signature(Part.makeCylinder(6, 10)), original)

    def test_signature_survives_native_save_reopen(self):
        doc = App.newDocument('VisibilitySignature')
        try:
            obj = doc.addObject('Part::Feature', 'Solid')
            obj.Shape = Part.makeBox(20, 20, 20).cut(Part.makeCylinder(3, 30, App.Vector(10, 10, -5)))
            doc.recompute(); before = v.signature(obj.Shape)
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder)/'View.FCStd'); doc.saveAs(path)
                App.closeDocument(doc.Name); doc = App.openDocument(path)
                self.assertEqual(v.signature(doc.Objects[0].Shape), before)
        finally: App.closeDocument(doc.Name)


if __name__ == '__main__': unittest.main()
