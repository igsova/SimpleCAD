import math
import unittest
import FreeCAD as App
import Part
from simplecad.modeling import deformation as d
from simplecad.document import operations as ops, locking
V=App.Vector


class DeformationGeometry(unittest.TestCase):
    def test_smooth_falloff_has_fixed_boundary_and_full_center(self):
        self.assertEqual(d.smooth_weight(0,10),1)
        self.assertEqual(d.smooth_weight(10,10),0)
        self.assertEqual(d.smooth_weight(11,10),0)
        weights=[d.smooth_weight(i,10) for i in range(11)]
        self.assertEqual(weights,sorted(weights,reverse=True))
        self.assertLess(d.smooth_weight(9.999,10),1e-9)

    def test_soft_region_moves_locally_and_preserves_closed_box(self):
        source=Part.makeBox(10,10,30);region=d.Region(source)
        points,weights=region.move(V(5,5,30),20,V(3,0,0))
        for p,q,w in zip(region.points,points,weights):
            self.assertLess((q-p-V(3*w,0,0)).Length,1e-8)
            if p.z<10:self.assertLess((p-q).Length,1e-9)
        result,origins=region.build(points)
        self.assertTrue(result.isValid() and result.isClosed());self.assertEqual(len(result.Solids),1)
        self.assertEqual(len(origins),len(result.Faces));self.assertEqual(set(origins),set(range(6)))
        self.assertAlmostEqual(source.Volume,3000)

    def test_shared_refinement_is_conforming_and_bounded(self):
        for shape in (Part.makeBox(10,10,30),Part.makeSphere(10),Part.makeCylinder(4,30)):
            region=d.Region(shape);counts={}
            for tri in region.triangles:
                for i in range(3):
                    edge=tuple(sorted((tri[i],tri[(i+1)%3])));counts[edge]=counts.get(edge,0)+1
            self.assertTrue(all(count==2 for count in counts.values()))
            self.assertLessEqual(len(region.triangles),d.MAX_FACES)
            self.assertEqual(len(region.origins),len(region.triangles))

    def test_bend_base_fixed_and_beyond_length_follows_tangent(self):
        region=d.Region(Part.makeBox(4,4,30,V(-2,-2,-5)))
        points,_=region.bend(V(),V(0,0,1),V(1,0,0),20,90)
        for p,q in zip(region.points,points):
            if p.z<=0:self.assertLess((p-q).Length,1e-8)
            if abs(p.z-25)<1e-8:
                radius=20/(math.pi/2)
                self.assertAlmostEqual(q.x,radius+5,places=6)
                self.assertAlmostEqual(q.z,radius-p.x,places=6)
        result,_=region.build(points);self.assertTrue(result.isClosed() and result.isValid())

    def test_bend_curved_objects_and_local_placement(self):
        for shape in [Part.makeSphere(10),Part.makeCylinder(3,25)]:
            shape.Placement=App.Placement(V(20,-10,3),App.Rotation(V(1,2,3),27))
            region=d.Region(shape,4)
            frame=d.bend_frame(shape,'LocalZ');points,_=region.bend(*frame,30)
            result,ids=region.build(points)
            self.assertTrue(result.isClosed() and result.isValid())
            self.assertAlmostEqual(result.Placement.Rotation.Angle,shape.Placement.Rotation.Angle)
            self.assertLess((result.Placement.Base-shape.Placement.Base).Length,1e-6)
            self.assertEqual(len(result.Faces),len(ids))
            for vertex in result.Vertexes:
                self.assertLess(min((vertex.Point-p).Length for p in points),1e-6)

    def test_zero_strength_keeps_exact_original_geometry(self):
        source=Part.makeSphere(5);region=d.Region(source)
        for points in (region.move(V(),20,V())[0],region.bend(*d.bend_frame(source),0)[0]):
            result,_=region.build(points);self.assertTrue(result.isSame(source))
            self.assertIsInstance(result.Faces[0].Surface,Part.Sphere)

    def test_unsafe_inputs_and_compressed_bend_rejected(self):
        region=d.Region(Part.makeBox(20,20,20))
        for radius in (0,-1,float('nan')):
            with self.assertRaises(ValueError):region.move(V(),radius,V(1,0,0))
        with self.assertRaises(ValueError):region.move(V(100,0,0),1,V(1,0,0))
        with self.assertRaises(ValueError):region.move(V(),10,V(float('nan'),0,0))
        with self.assertRaises(ValueError):region.bend(V(),V(0,0,1),V(1,0,0),5,150)
        with self.assertRaises(ValueError):region.bend(V(),V(0,0,1),V(0,0,1),20,20)
        for detail in (0,17,True):
            with self.assertRaises(ValueError):d.Region(region.shape,detail)

    def test_folded_soft_move_rejected(self):
        region=d.Region(Part.makeBox(10,10,10))
        points,_=region.move(V(5,5,10),9,V(0,0,-25))
        with self.assertRaises(ValueError):region.build(points)

    def test_open_face_and_invalid_payload(self):
        face=Part.makePlane(20,20);region=d.Region(face)
        points,_=region.move(V(10,10,0),15,V(0,0,4));result,_=region.build(points)
        self.assertTrue(result.isValid());self.assertFalse(result.Solids)
        for shape in (Part.makeLine(V(),V(10,0,0)),Part.makeBox(10,10,10).cut(Part.makeSphere(2,V(5,5,5)))):
            with self.assertRaises(ValueError):d.Region(shape)


class DeformationWrites(unittest.TestCase):
    def setUp(self):
        self.doc=App.newDocument('DeformTest');self.doc.UndoMode=1
        self.obj=self.doc.addObject('Part::Feature','Box');self.obj.Shape=Part.makeBox(10,10,30);self.doc.recompute()
    def tearDown(self):App.closeDocument(self.doc.Name)
    def test_atomic_undo_redo_and_stale_source(self):
        target=ops.prepare_deformation([(self.obj,('Face1',))]);before=self.doc.UndoCount
        points,_=target[1].bend(*d.bend_frame(self.obj.Shape,'Z'),35)
        self.assertTrue(ops.commit_deformation(target,points));self.assertEqual(self.doc.UndoCount,before+1)
        with self.assertRaises(ValueError):ops.commit_deformation(target,points)
        self.doc.undo();self.assertEqual(len(self.obj.Shape.Faces),6);self.assertAlmostEqual(self.obj.Shape.Volume,3000)
        self.doc.redo();self.assertGreater(len(self.obj.Shape.Faces),6)
    def test_locks_reject_geometry_and_failures_make_no_edit(self):
        locking.set_locked([(self.obj,('Face1',))],True)
        with self.assertRaises(ValueError):ops.prepare_deformation([(self.obj,())])
        locking.set_locked([(self.obj,('Face1',))],False)
        target=ops.prepare_deformation([(self.obj,())]);before=self.doc.UndoCount
        points,_=target[1].move(V(5,5,30),20,V(0,0,-80))
        with self.assertRaises(ValueError):ops.commit_deformation(target,points)
        self.assertEqual(self.doc.UndoCount,before);self.assertAlmostEqual(self.obj.Shape.Volume,3000)
