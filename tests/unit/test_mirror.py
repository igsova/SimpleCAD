"""Mirror whole objects along X, Y or Z, as a copy by default or in place."""
import unittest

import FreeCAD as App
import Part

from simplecad.document import operations as ops

V = App.Vector


def l_block():
    """An L-shaped solid, so a flip along X is visible: the tall arm moves sides."""
    return Part.makeBox(10, 4, 2, V(5, 0, 0)).fuse(Part.makeBox(2, 4, 8, V(5, 0, 0))).removeSplitter()


def tall_arm_x(shape):
    return next(f for f in shape.Faces if abs(f.CenterOfMass.z - 8) < 1e-9).CenterOfMass.x


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Mirror')
        self.doc.UndoMode = 1
        self.addCleanup(lambda: App.closeDocument(self.doc.Name))
        self.obj = ops.new_shape(self.doc, l_block(), 'Block')
        self.original = self.obj.Shape.copy()

    def objects(self):
        return [o for o in self.doc.Objects if o.TypeId == 'Part::Feature']

    def test_a_mirrored_copy_is_made_by_default(self):
        undo = self.doc.UndoCount
        [copy] = ops.mirror([self.obj], 'X')
        self.assertIsNot(copy, self.obj)
        self.assertEqual(len(self.objects()), 2)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(self.obj.Shape.isSame(self.original) or abs(self.obj.Shape.Volume - self.original.Volume) < 1e-9)
        shape = copy.Shape
        self.assertTrue(shape.isValid() and shape.isClosed())
        self.assertAlmostEqual(shape.Volume, self.original.Volume)
        # Through the center the copy fills the same box, with the arm flipped.
        self.assertTrue(shape.BoundBox.isInside(self.original.BoundBox.Center))
        self.assertAlmostEqual(tall_arm_x(self.original), 6)
        self.assertAlmostEqual(tall_arm_x(shape), 14)

    def test_the_original_can_be_mirrored_in_place(self):
        [result] = ops.mirror([self.obj], 'X', copy=False)
        self.assertIs(result, self.obj)
        self.assertEqual(len(self.objects()), 1)
        self.assertAlmostEqual(tall_arm_x(self.obj.Shape), 14)
        self.assertGreater(self.obj.Shape.Volume, 0)
        self.doc.undo()
        self.assertAlmostEqual(tall_arm_x(self.obj.Shape), 6)

    def test_a_copy_through_a_side_lands_beside_the_original(self):
        [beside] = ops.mirror([self.obj], 'X', through='Max')
        self.assertAlmostEqual(beside.Shape.BoundBox.XMin, self.original.BoundBox.XMax)
        [before] = ops.mirror([self.obj], 'X', through='Min')
        self.assertAlmostEqual(before.Shape.BoundBox.XMax, self.original.BoundBox.XMin)

    def test_mirroring_through_the_world_origin(self):
        [copy] = ops.mirror([self.obj], 'Y', through='Origin')
        box = copy.Shape.BoundBox
        self.assertAlmostEqual(box.YMin, -4)
        self.assertAlmostEqual(box.YMax, 0)

    def test_a_group_mirrors_as_one_unit(self):
        other = ops.new_shape(self.doc, Part.makeBox(2, 2, 2, V(30, 0, 0)), 'Cube')
        ops.mirror([self.obj, other], 'X', copy=False)
        # The combined box spans x 5..32, so its center is 18.5.
        self.assertAlmostEqual(other.Shape.BoundBox.XMin, 5)
        self.assertAlmostEqual(self.obj.Shape.BoundBox.XMax, 32)

    def test_face_order_is_kept(self):
        [copy] = ops.mirror([self.obj], 'Z')
        self.assertEqual(len(copy.Shape.Faces), len(self.original.Faces))
        for before, after in zip(self.original.Faces, copy.Shape.Faces):
            self.assertAlmostEqual(before.Area, after.Area)

    def test_invalid_axis_is_refused(self):
        with self.assertRaises(ValueError):
            ops.mirror([self.obj], 'W')
        with self.assertRaises(ValueError):
            ops.mirror([], 'X')


if __name__ == '__main__':
    unittest.main()
