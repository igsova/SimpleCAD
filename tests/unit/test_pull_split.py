"""Removing a connecting region keeps every resulting valid solid."""
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op, locking
V=App.Vector


def bridge():
    shape=Part.makeBox(10,10,10).fuse(Part.makeBox(10,4,4,V(10,3,3))).fuse(
        Part.makeBox(10,10,10,V(20,0,0)))
    face=next(f for f in shape.Faces if (f.CenterOfMass-V(15,5,7)).Length<1e-6)
    return shape,face


class PullSplitTests(unittest.TestCase):
    def test_exact_contact_separates_bridge_and_keeps_all_material(self):
        shape,face=bridge()
        self.assertAlmostEqual(g.opposite_face(shape,face).distance,-4)
        result=g.push_pull(shape,face,-4)
        self.assertEqual(len(result.Solids),2)
        self.assertAlmostEqual(result.Volume,2000)
        self.assertAlmostEqual(result.common(face).Area,0)
        end=face.copy();end.translate(V(0,0,-4))
        self.assertAlmostEqual(result.common(end).Area,0)
        for piece in result.Solids:
            self.assertTrue(piece.isValid() and piece.isClosed())
            self.assertAlmostEqual(piece.Volume,1000)

    def test_rotated_split(self):
        shape,face=bridge()
        rotation=App.Placement(V(50,-20,8),App.Rotation(V(1,2,3),47))
        center=rotation.multVec(face.CenterOfMass)
        shape.Placement=rotation
        face=next(f for f in shape.Faces if (f.CenterOfMass-center).Length<1e-6)
        result,_=g.plan_push_pull(shape,face,-4)
        self.assertEqual(len(result.Solids),2)
        self.assertAlmostEqual(result.Volume,2000)
        self.assertTrue(result.isValid())

    def document(self):
        doc=App.newDocument('PullSplitTest');doc.UndoMode=1
        name=doc.Name
        self.addCleanup(lambda:App.closeDocument(name) if name in App.listDocuments() else None)
        shape,face=bridge()
        obj=op.new_shape(doc,shape,'Bridge')
        return doc,obj,face

    def test_document_pieces_are_editable_with_atomic_undo_redo_and_persistence(self):
        doc,obj,face=self.document();before=doc.UndoCount
        results=op.extrude(obj,face,-4,return_pieces=True)
        self.assertEqual(results[0],obj)
        self.assertEqual(len(results),2)
        self.assertEqual(doc.UndoCount,before+1)
        for piece in results:
            self.assertEqual(piece.Shape.ShapeType,'Solid')
            self.assertEqual(op.editable(piece),piece)
        doc.undo();self.assertEqual(len(doc.Objects),1)
        self.assertAlmostEqual(obj.Shape.Volume,2160)
        doc.redo();self.assertEqual(len(doc.Objects),2)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'split.FCStd');doc.saveAs(path)
            App.closeDocument(doc.Name)
            restored=App.openDocument(path)
            try:
                self.assertEqual(len(restored.Objects),2)
                self.assertTrue(all(o.Shape.isValid() and o.Shape.isClosed() for o in restored.Objects))
                self.assertAlmostEqual(sum(o.Shape.Volume for o in restored.Objects),2000)
            finally:App.closeDocument(restored.Name)

    def test_locked_object_rejects_without_extra_piece(self):
        doc,obj,face=self.document()
        locking.set_locked([(obj,[])],True)
        with self.assertRaises(ValueError):op.extrude(obj,face,-4)
        self.assertEqual(len(doc.Objects),1)
        self.assertAlmostEqual(obj.Shape.Volume,2160)
