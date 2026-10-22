"""Crossing surface regions and the sphere-to-bowl editing workflow."""
import math
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
import MeshPart
from simplecad.document import operations as op, locking
from simplecad.core import geometry as g
V = App.Vector


def face_name(obj, predicate):
    return next('Face'+str(i) for i,face in enumerate(obj.Shape.Faces,1) if predicate(face))


class IntersectionTests(unittest.TestCase):
    def setUp(self):
        self.doc=App.newDocument('IntersectionTest'); self.doc.UndoMode=1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pair(self, rotated=False):
        block=op.new_shape(self.doc,Part.makeBox(20,20,10),'Block')
        ball=op.new_shape(self.doc,g.sphere(V(10,10,10),4),'Sphere')
        if rotated:
            placement=App.Placement(V(23,-19,42),App.Rotation(V(1,2,3),37))
            block.Placement=placement; ball.Placement=placement
        return block,ball

    def test_selected_faces_split_both_and_delete_to_closed_bowl(self):
        for rotated in (False,True):
            for reverse in (False,True):
                with self.subTest(rotated=rotated,reverse=reverse):
                    block,ball=self.pair(rotated)
                    inverse=block.Placement.inverse()
                    local=lambda face: inverse.multVec(face.CenterOfMass)
                    top=face_name(block,lambda f: local(f).z>9.99)
                    original_volume=block.Shape.Volume
                    names=[block.Name,ball.Name]; count=self.doc.UndoCount
                    targets=[(block,(top,)),(ball,('Face1',))]
                    result=op.intersect(targets[::-1] if reverse else targets)
                    self.assertEqual(len(result.Shape.Faces),9)
                    self.assertEqual(self.doc.UndoCount,count+1)
                    self.assertEqual(len([n for n in names if self.doc.getObject(n)]),1)
                    upper=face_name(result,lambda f:isinstance(f.Surface,Part.Sphere) and local(f).z>10)
                    op.delete_selection([(result,(upper,))])
                    self.assertEqual(len(result.Shape.Faces),8)
                    disk=face_name(result,lambda f:isinstance(f.Surface,Part.Plane) and abs(f.Area-math.pi*16)<1e-5)
                    op.delete_selection([(result,(disk,))])
                    self.assertEqual(len(result.Shape.Faces),7)
                    self.assertEqual(result.Shape.ShapeType,'Solid')
                    self.assertTrue(result.Shape.isClosed() and result.Shape.isValid())
                    self.assertAlmostEqual(result.Shape.Volume,original_volume-2*math.pi*64/3,places=5)
                    self.assertTrue(MeshPart.meshFromShape(Shape=result.Shape,LinearDeflection=.1,AngularDeflection=.2,Relative=False).isSolid())
                    self.doc.undo(); self.assertEqual(len(result.Shape.Faces),8)
                    self.doc.undo(); self.assertEqual(len(result.Shape.Faces),9)
                    self.doc.undo(); self.assertTrue(all(self.doc.getObject(n) for n in names))
                    for _ in range(3): self.doc.redo()
                    self.assertEqual(result.Shape.ShapeType,'Solid')

    def test_whole_objects_and_simultaneous_deletion_save_reopen(self):
        block,ball=self.pair(); result=op.intersect([(block,()),(ball,())])
        unwanted=[face_name(result,lambda f:isinstance(f.Surface,Part.Sphere) and f.CenterOfMass.z>10),
                  face_name(result,lambda f:isinstance(f.Surface,Part.Plane) and abs(f.Area-math.pi*16)<1e-5)]
        op.delete_selection([(result,unwanted)])
        name=result.Name; volume=result.Shape.Volume
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'bowl.FCStd'); self.doc.saveAs(path)
            App.closeDocument(self.doc.Name); self.doc=App.openDocument(path)
            saved=self.doc.getObject(name)
            self.assertEqual(saved.TypeId,'Part::Feature')
            self.assertEqual(saved.Shape.ShapeType,'Solid')
            self.assertAlmostEqual(saved.Shape.Volume,volume,places=6)

    def test_single_object_with_two_crossing_surfaces(self):
        a=Part.makePlane(20,20)
        b=Part.Face(Part.makePolygon([V(10,0,-10),V(10,20,-10),V(10,20,10),V(10,0,10),V(10,0,-10)]))
        obj=op.new_shape(self.doc,Part.makeCompound([a,b]),'Surfaces')
        result=op.intersect([(obj,('Face1','Face2'))])
        self.assertGreater(len(result.Shape.Faces),2)
        self.assertAlmostEqual(result.Shape.Area,800)

    def test_sheet_and_sphere_keep_open_bowl_surface(self):
        sheet=op.new_shape(self.doc,Part.makePlane(20,20),'Sheet')
        sphere=op.new_shape(self.doc,g.sphere(V(10,10,0),4),'Sphere')
        result=op.intersect([(sheet,()),(sphere,())])
        upper=face_name(result,lambda f:isinstance(f.Surface,Part.Sphere) and f.CenterOfMass.z>0)
        disk=face_name(result,lambda f:isinstance(f.Surface,Part.Plane) and abs(f.Area-math.pi*16)<1e-5)
        op.delete_selection([(result,(upper,disk))])
        self.assertFalse(result.Shape.Solids)
        self.assertEqual(len(result.Shape.Faces),2)
        self.assertAlmostEqual(result.Shape.Area,400+math.pi*16,places=5)

    def test_no_crossing_invalid_targets_and_locked_owner_do_not_edit(self):
        block,ball=self.pair(); count=self.doc.UndoCount
        for targets in ([],[(ball,())],[(block,('Edge1',)),(ball,())],[(block,('Face999',)),(ball,())],[(block,('Face1',)),(ball,())]):
            with self.assertRaises(ValueError): op.intersect(targets)
            self.assertEqual(self.doc.UndoCount,count)
            self.assertEqual(len(self.doc.Objects),2)
        locking.set_locked([(ball,('Face1',))],True); count=self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'locked'): op.intersect([(block,()),(ball,())])
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),2)

    def test_tangent_contact_rejected_and_loose_line_preserved(self):
        block,ball=self.pair()
        ball.Shape=g.sphere(V(10,10,14),4)
        count=self.doc.UndoCount
        with self.assertRaises(ValueError): op.intersect([(block,()),(ball,())])
        self.assertEqual(self.doc.UndoCount,count)
        ball.Shape=g.sphere(V(10,10,10),4)
        block.Shape=Part.makeCompound([block.Shape,Part.makeLine(V(30,0,0),V(40,0,0))])
        result=op.intersect([(block,()),(ball,())])
        self.assertTrue(any(abs(e.Length-10)<1e-6 and e.CenterOfMass.x>29 for e in result.Shape.Edges))
