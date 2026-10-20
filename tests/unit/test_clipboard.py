"""Copy, cut and paste of whole objects as plain geometry, one Undo step each."""
import unittest
import FreeCAD as App
import Mesh
import Part
from simplecad.document import clipboard, locking, operations as ops

V = App.Vector


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Clipboard'); self.doc.UndoMode = 1
        self.box = ops.new_shape(self.doc, Part.makeBox(10, 20, 30, V(5, 0, 0)), 'Block')

    def tearDown(self):
        locking.forget_document(self.doc.Name)
        App.closeDocument(self.doc.Name)

    def test_paste_adds_an_independent_copy_in_place_in_one_step(self):
        items = clipboard.snapshot([self.box])
        # Later edits to the original do not reach the clipboard.
        ops.transform([self.box], V(0, 50, 0))
        count = self.doc.UndoCount
        pasted, = clipboard.paste(self.doc, items)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(self.doc.UndoNames[0], 'SimpleCAD: Paste')
        self.assertEqual(pasted.TypeId, 'Part::Feature')
        self.assertNotEqual(pasted.Name, self.box.Name)
        self.assertTrue(pasted.Name.startswith(self.box.Name))
        self.assertTrue(pasted.Label.startswith('Block'))
        self.assertAlmostEqual(pasted.Shape.Volume, 6000)
        self.assertTrue(pasted.Shape.BoundBox.isInside(V(10, 10, 15)))
        self.assertAlmostEqual(pasted.Shape.BoundBox.XMin, 5)
        self.assertAlmostEqual(self.box.Shape.BoundBox.YMin, 50)
        # Pasting twice makes two copies.
        again, = clipboard.paste(self.doc, items)
        self.assertNotEqual(again.Name, pasted.Name)
        self.doc.undo(); self.doc.undo()
        self.assertEqual([obj.Name for obj in self.doc.Objects], [self.box.Name])

    def test_cut_removes_the_objects_in_one_step_and_paste_restores_them(self):
        other = ops.new_shape(self.doc, Part.makeCylinder(4, 8), 'Peg')
        volume = other.Shape.Volume
        count = self.doc.UndoCount
        items = clipboard.cut([self.box, other])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(self.doc.UndoNames[0], 'SimpleCAD: Cut')
        self.assertEqual(self.doc.Objects, [])
        pasted = clipboard.paste(self.doc, items)
        self.assertEqual([obj.Label for obj in pasted], ['Block', 'Peg'])
        self.assertAlmostEqual(pasted[0].Shape.BoundBox.XMin, 5)
        self.assertAlmostEqual(pasted[1].Shape.Volume, volume)
        self.doc.undo(); self.doc.undo()
        self.assertEqual(sorted(obj.Label for obj in self.doc.Objects), ['Block', 'Peg'])
        self.assertAlmostEqual(self.doc.getObjectsByLabel('Peg')[0].Shape.Volume, volume)

    def test_cut_leaves_locked_and_depended_on_objects_in_place(self):
        locking.set_locked([(self.box, ())], True)
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError, 'locked'):
            clipboard.cut([self.box])
        self.assertEqual(self.doc.UndoCount, count)
        self.assertEqual(self.doc.Objects, [self.box])
        locking.set_locked([(self.box, ())], False)
        count = self.doc.UndoCount
        top = Part.makePlane(4, 4, V(8, 2, 30))
        profile = ops.new_shape(self.doc, top, 'Rectangle', support=self.box)
        with self.assertRaisesRegex(ValueError, 'depends'):
            clipboard.cut([self.box])
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(len(self.doc.Objects), 2)
        # The profile alone can go, and comes back without its support link.
        items = clipboard.cut([profile])
        pasted, = clipboard.paste(self.doc, items)
        self.assertNotIn('SC_Support', pasted.PropertiesList)
        self.assertAlmostEqual(pasted.Shape.Area, 16)

    def test_raw_mesh_stays_a_mesh_with_its_placement(self):
        points, faces = Part.makeBox(10, 10, 10).tessellate(0.1)
        source = self.doc.addObject('Mesh::Feature', 'Scan')
        source.Mesh = Mesh.Mesh((list(points), [tuple(map(int, f)) for f in faces]))
        source.Placement = App.Placement(V(0, 0, 40), App.Rotation(V(0, 0, 1), 30))
        self.doc.recompute()
        box = source.Mesh.BoundBox
        pasted, = clipboard.paste(self.doc, clipboard.cut([source]))
        self.assertEqual(pasted.TypeId, 'Mesh::Feature')
        self.assertEqual(pasted.Mesh.CountFacets, len(faces))
        self.assertTrue(pasted.Placement.isSame(App.Placement(V(0, 0, 40), App.Rotation(V(0, 0, 1), 30)), 1e-9))
        for a, b in ((pasted.Mesh.BoundBox.XMin, box.XMin), (pasted.Mesh.BoundBox.ZMax, box.ZMax)):
            self.assertAlmostEqual(a, b)

    def test_only_plain_shapes_and_meshes_are_copied(self):
        feature = self.doc.addObject('Part::Box', 'Parametric')
        self.doc.recompute()
        self.assertFalse(clipboard.copyable(feature))
        with self.assertRaisesRegex(ValueError, 'plain shape'):
            clipboard.snapshot([self.box, feature])
        with self.assertRaisesRegex(ValueError, 'Select objects'):
            clipboard.snapshot([])
        with self.assertRaisesRegex(ValueError, 'Nothing to paste'):
            clipboard.paste(self.doc, [])
        self.assertEqual(len(self.doc.Objects), 2)


if __name__ == '__main__':
    unittest.main()
