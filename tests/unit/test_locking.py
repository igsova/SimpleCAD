"""Native saved locks and atomic protection of direct/indirect geometry edits."""
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
from simplecad.document import operations as ops, locking


class LockTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('Locks'); self.doc.UndoMode = 1
        self.obj = ops.new_shape(self.doc, Part.makeBox(10, 10, 10), 'Box')

    def tearDown(self):
        locking.forget_document(self.doc.Name)
        App.closeDocument(self.doc.Name)

    def lock(self, names=(), locked=True):
        locking.set_locked([(self.obj, names)], locked)

    def test_object_move_delete_and_union_are_atomic(self):
        other = ops.new_shape(self.doc, Part.makeBox(10,10,10,App.Vector(5,0,0)), 'Other')
        self.lock(); original = self.obj.Shape
        for action in (lambda: ops.transform([other,self.obj], App.Vector(3,0,0)),
                       lambda: ops.delete_selection([(self.obj,[])]),
                       lambda: ops.unite([other,self.obj])):
            with self.assertRaisesRegex(ValueError, 'locked'): action()
            self.obj = self.doc.getObject(self.obj.Name)
            self.assertIsNotNone(self.obj)
            self.assertEqual(len(self.doc.Objects), 2)
            self.assertAlmostEqual(other.Shape.BoundBox.XMin, 5)
            self.assertAlmostEqual(self.obj.Shape.Volume, original.Volume)
            self.assertTrue(locking.whole(self.obj))
        self.lock(locked=False)
        ops.transform([self.obj], App.Vector(3,0,0))
        self.assertAlmostEqual(self.obj.Shape.BoundBox.XMin, 3)

    def test_face_lock_rejects_move_and_indirect_deletion(self):
        self.lock(['Face1'])
        edge = next(i for i,e in enumerate(self.obj.Shape.Edges,1) if e.isSame(self.obj.Shape.Faces[0].Edges[0]))
        with self.assertRaisesRegex(ValueError, 'locked'):
            ops.delete_selection([(self.obj,['Edge'+str(edge)])])
        with self.assertRaisesRegex(ValueError, 'locked'):
            ops.transform([self.obj], App.Vector(1,0,0))
        self.assertEqual(len(self.obj.Shape.Faces), 6)
        self.assertEqual(locking.state(self.obj), ({1},False))

    def test_unrelated_face_edit_and_reordering_preserve_reference(self):
        self.obj.Shape = Part.makeCompound([Part.makePlane(10,10),Part.makePlane(10,10,App.Vector(0,0,10))])
        self.doc.recompute(); self.lock(['Face1'])
        first = self.obj.Shape.Faces[0]
        with ops.transaction(self.doc,'Reorder and change unlocked face'):
            self.obj.Shape = Part.makeCompound([Part.makePlane(20,10,App.Vector(0,0,10)),first])
        self.assertEqual(locking.state(self.obj), ({2},False))
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.apply_plan(self.doc,[(self.obj, Part.makePlane(20,10,App.Vector(0,0,10)))],'Remove locked face')
        self.assertEqual(locking.state(self.obj), ({2},False))

    def test_copy_is_allowed_and_unlocked(self):
        self.lock(['Face1']); self.lock()
        copies = ops.transform([self.obj],App.Vector(20,0,0),copy=True)
        self.assertFalse(locking.whole(copies[0]))
        self.assertEqual(locking.state(copies[0]), (set(),False))
        self.assertAlmostEqual(self.obj.Shape.BoundBox.XMin,0)

    def test_inheritance_undo_redo_and_persistence(self):
        self.lock(['Face2']); self.lock()
        with self.assertRaisesRegex(ValueError,'Unlock the object'):
            self.lock(['Face2'],False)
        self.lock(locked=False)
        self.assertFalse(locking.whole(self.obj)); self.assertEqual(locking.state(self.obj)[0],{2})
        self.doc.undo(); self.assertTrue(locking.whole(self.obj))
        self.doc.redo(); self.assertFalse(locking.whole(self.obj))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'Locks.FCStd'); name = self.obj.Name
            self.doc.saveAs(path); App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path); self.doc.UndoMode=1; self.obj=self.doc.getObject(name)
            self.assertEqual(locking.state(self.obj),({2},False))
            self.lock(['Face2'],False)
            self.assertEqual(locking.state(self.obj),(set(),False))

    def test_stale_native_edits_fail_closed_until_explicit_reset(self):
        self.lock(['Face1'])
        self.obj.Shape = Part.makeCylinder(2,8); self.doc.recompute()
        self.assertTrue(locking.state(self.obj)[1])
        with self.assertRaisesRegex(ValueError,'locked'): ops.transform([self.obj],App.Vector(1,0,0))
        self.lock(locked=False)
        self.assertEqual(locking.state(self.obj),(set(),False))
        ops.transform([self.obj],App.Vector(1,0,0))

    def test_parent_precedence_and_invalid_batch(self):
        locking.set_locked([(self.obj,['Face1']),(self.obj,[])],True)
        self.assertTrue(locking.whole(self.obj)); self.assertEqual(locking.state(self.obj)[0],set())
        with self.assertRaises(ValueError): locking.set_locked([(self.obj,[]),(self.obj,['Edge1'])],False)
        self.assertTrue(locking.whole(self.obj))

    def test_subdivision_rotation_and_preview_race(self):
        target = ops.prepare_subdivision([(self.obj,['Face6'])])
        planned, regions = ops.preview_subdivision(target, 2, 2, pattern='spaced')
        self.lock(['Face6'])
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.prepare_subdivision([(self.obj,['Face6'])])
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.prepare_rotation([(self.obj,[])])
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.commit_subdivision(target,planned,2,2,len(regions))
        self.assertEqual(len(self.obj.Shape.Faces),6)

    def test_supported_profile_and_slice_cannot_change_locked_host(self):
        self.lock()
        profile=ops.new_shape(self.doc,Part.Face(Part.Wire(Part.makeCircle(2,App.Vector(5,5,10)))), 'Circle', support=self.obj)
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.extrude(profile,profile.Shape,3)
        self.assertEqual(len(self.doc.Objects),2)
        self.assertAlmostEqual(self.obj.Shape.Volume,1000)
        with self.assertRaisesRegex(ValueError,'locked'):
            with ops.transaction(self.doc,'Slice into pieces'):
                self.obj.Shape=Part.makeBox(5,10,10)
                piece=self.doc.addObject('Part::Feature','Piece')
                piece.Shape=Part.makeBox(5,10,10,App.Vector(5,0,0))
        self.assertEqual(len(self.doc.Objects),2)

    def test_disabled_undo_cannot_leave_partial_edit(self):
        self.lock()
        self.doc.UndoMode = 0
        with self.assertRaisesRegex(ValueError, 'locked|Undo'):
            ops.transform([self.obj], App.Vector(2,0,0))
        self.assertAlmostEqual(self.obj.Shape.BoundBox.XMin,0)

    def test_appearance_metadata_transaction_allowed(self):
        self.lock()
        with ops.transaction(self.doc,'Rename'):
            self.obj.Label='Locked box'
        self.assertEqual(self.obj.Label,'Locked box')
