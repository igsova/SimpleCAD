import unittest
import tempfile
from pathlib import Path
import FreeCAD as App
import Part
from simplecad.modeling import vertex_edit as ve
from simplecad.document import operations as op, locking
from simplecad.core import geometry as g, coincident
V=App.Vector

class VertexEditTests(unittest.TestCase):
    def box(self): return Part.makeBox(10,10,10)

    def test_corner_deforms_adjacent_faces_only(self):
        shape=self.box();n=ve.Neighborhood(shape,'Vertex1');d=V(-2,-3,2)
        result,origins=n.build(d)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(result.ShapeType,'Solid');self.assertEqual(len(result.Faces),9)
        self.assertEqual(len(origins),9)
        self.assertTrue(any(ve.same(v.Point,n.point+d) for v in result.Vertexes))
        for i,f in enumerate(shape.Faces):
            if i not in n.faces:self.assertTrue(any(coincident.same(f,r) for r in result.Faces))
        self.assertAlmostEqual(shape.Volume,1000)

    def test_axis_move_keeps_flat_faces_whole(self):
        result,_=ve.Neighborhood(self.box(),'Vertex1').build(V(0,0,2))
        self.assertEqual(len(result.Faces),7)
        self.assertTrue(result.isClosed())

    def test_rotated_translated_world_displacement(self):
        shape=self.box();shape.Placement=App.Placement(V(100,200,-40),App.Rotation(V(1,2,3),40))
        n=ve.Neighborhood(shape,'Vertex1');delta=shape.Placement.Rotation.multVec(V(-2,-3,2))
        result,_=n.build(delta)
        self.assertTrue(result.isClosed())
        self.assertTrue(any(ve.same(v.Point,n.point+delta) for v in result.Vertexes))

    def test_triangle_and_open_quad(self):
        for points in ([V(),V(10,0,0),V(0,10,0)], [V(),V(10,0,0),V(10,10,0),V(0,10,0)]):
            face=Part.Face(Part.makePolygon(points+points[:1]))
            result,_=ve.Neighborhood(face,'Vertex1').build(V(0,0,3))
            self.assertEqual(len(result.Faces),len(points)-2)
            self.assertFalse(result.Solids)

    def test_face_hole_preserves_outline_for_planar_move(self):
        outer=Part.makePolygon([V(),V(20,0,0),V(20,20,0),V(0,20,0),V()])
        inner=Part.makePolygon([V(5,5,0),V(10,5,0),V(10,10,0),V(5,10,0),V(5,5,0)])
        face=Part.Face([outer,inner],'Part::FaceMakerBullseye')
        result,_=ve.Neighborhood(face,'Vertex1').build(V(-2,0,0))
        self.assertEqual(len(result.Faces),1);self.assertEqual(len(result.Wires),2)
        self.assertAlmostEqual(result.Area,395)

    def test_shared_grid_vertex_deforms_all_four_regions(self):
        shape=g.divide_face_with_line(self.box(),V(0,5,10),V(10,5,10))
        shape=g.divide_face_with_line(shape,V(5,0,10),V(5,10,10))
        name=next('Vertex'+str(i) for i,v in enumerate(shape.Vertexes,1) if ve.same(v.Point,V(5,5,10)))
        n=ve.Neighborhood(shape,name)
        self.assertEqual(len(n.faces),4)
        result,_=n.build(V(0,0,2))
        self.assertTrue(result.isClosed() and result.isValid())
        self.assertEqual(sum(ve.same(v.Point,V(5,5,12)) for v in result.Vertexes),1)
        self.assertGreater(result.Volume,shape.Volume)

    def test_wire_endpoint(self):
        shape=Part.makePolygon([V(),V(10,0,0),V(10,10,0)])
        n=ve.Neighborhood(shape,'Vertex1');result,_=n.build(V(0,0,2))
        self.assertEqual(len(result.Edges),2);self.assertFalse(result.Faces)

    def test_rejects_curved_neighborhood(self):
        for shape in (Part.makeSphere(10),Part.makeCylinder(10,20)):
            with self.assertRaises(ValueError):ve.Neighborhood(shape,'Vertex1')

    def test_unrelated_curved_surface_is_preserved(self):
        sphere=Part.makeSphere(2,V(5,5,10))
        shape=self.box().cut(sphere)
        name=next('Vertex'+str(i) for i,v in enumerate(shape.Vertexes,1) if ve.same(v.Point,V(0,0,0)))
        result,_=ve.Neighborhood(shape,name).build(V(-1,-1,-1))
        self.assertTrue(result.isClosed())
        curved=[f for f in shape.Faces if isinstance(f.Surface,Part.Sphere)]
        self.assertTrue(all(any(coincident.same(f,r) for r in result.Faces) for f in curved))

    def test_rejects_invalid_moves_and_names(self):
        shape=self.box();n=ve.Neighborhood(shape,'Vertex1')
        for d in (V(),V(float('nan'),0,0),V(10,10,-10),V(0,0,-30)):
            with self.assertRaises(ValueError):n.build(d)
        for name in ('Face1','Vertex0','Vertex999'):
            with self.assertRaises(ValueError):ve.Neighborhood(shape,name)

    def document(self):
        doc=App.newDocument('VertexTest');doc.UndoMode=1;name=doc.Name
        self.addCleanup(lambda:App.closeDocument(name) if name in App.listDocuments() else None)
        obj=op.new_shape(doc,self.box(),'Box')
        return doc,obj

    def test_document_atomic_undo_redo_save(self):
        doc,obj=self.document();before=doc.UndoCount
        op.move_vertex(obj,'Vertex1',V(-2,-3,2));volume=obj.Shape.Volume
        self.assertEqual(doc.UndoCount,before+1)
        doc.undo();self.assertAlmostEqual(obj.Shape.Volume,1000)
        doc.redo();self.assertAlmostEqual(obj.Shape.Volume,volume)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'vertex.FCStd');doc.saveAs(path);App.closeDocument(doc.Name)
            reopened=App.openDocument(path)
            try:self.assertTrue(reopened.Objects[0].Shape.isClosed());self.assertAlmostEqual(reopened.Objects[0].Shape.Volume,volume)
            finally:App.closeDocument(reopened.Name)

    def test_locks_on_touching_face_and_stale_capture(self):
        doc,obj=self.document();n=op.prepare_vertex(obj,'Vertex1')
        face=next(iter(n.faces))
        locking.set_locked([(obj,['Face'+str(face+1)])],True)
        with self.assertRaises(ValueError):op.move_vertex(obj,'Vertex1',V(0,0,2))
        locking.set_locked([(obj,['Face'+str(face+1)])],False)
        obj.Shape=Part.makeBox(12,10,10)
        with self.assertRaises(ValueError):op.move_vertex(obj,'Vertex1',V(0,0,2),n)

    def test_unrelated_locked_face_stays_protected(self):
        doc,obj=self.document();n=op.prepare_vertex(obj,'Vertex1')
        index=next(i for i in range(6) if i not in n.faces)
        locking.set_locked([(obj,['Face'+str(index+1)])],True)
        op.move_vertex(obj,'Vertex1',V(-2,-3,2))
        self.assertEqual(len(locking.state(obj)[0]),1)
