"""Native topology, placement, source preservation and atomic modelling writes."""
import math
import unittest
import FreeCAD as App
import Part
from simplecad.modeling import forming as f
from simplecad.document import operations as ops, locking
V=App.Vector


def circle(radius,z=0):return Part.Wire([Part.makeCircle(radius,V(0,0,z))])


class FormingGeometry(unittest.TestCase):
    def test_stretch_box_preserves_planes_edges_bounds_and_material_lineage(self):
        source=Part.makeBox(10,20,30)
        result,origins=f.scaled(source,f.scale_frames([source])[0],(2,.5,3))
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume,source.Volume*3)
        self.assertEqual(sorted(origins),list(range(6)))
        self.assertTrue(all(isinstance(a.Surface,Part.Plane) for a in result.Faces))
        self.assertTrue(all(isinstance(e.Curve,Part.Line) for e in result.Edges))
        self.assertEqual((result.BoundBox.XLength,result.BoundBox.YLength,result.BoundBox.ZLength),(20,10,90))
        self.assertLess((result.CenterOfMass-source.CenterOfMass).Length,1e-6)
        self.assertAlmostEqual(source.Volume,6000)

    def test_stretched_loose_line_remains_a_line_for_offset(self):
        edge=Part.makeLine(V(10,20,30),V(20,30,40))
        result,origins=f.scaled(edge,(V(),App.Rotation()),(2,3,4))
        self.assertIsInstance(result.Curve,Part.Line)
        self.assertLess((result.Vertexes[0].Point-V(20,60,120)).Length,1e-7)
        self.assertLess((result.Vertexes[1].Point-V(40,90,160)).Length,1e-7)
        self.assertFalse(origins)

    def test_uniform_sphere_stays_analytic_and_scales_about_origin(self):
        source=Part.makeSphere(3,V(10,0,0))
        result,origins=f.scaled(source,f.scale_frames([source],pivot='Origin')[0],(2,2,2))
        self.assertIsInstance(result.Faces[0].Surface,Part.Sphere)
        self.assertAlmostEqual(result.Volume,source.Volume*8)
        self.assertLess((result.CenterOfMass-V(20,0,0)).Length,1e-6)

    def test_stretch_sphere_cylinder_and_cavity_remain_closed(self):
        for source in [Part.makeSphere(3),Part.makeCylinder(3,10),Part.makeBox(10,10,10).cut(Part.makeSphere(2,V(5,5,5)))]:
            result,origins=f.scaled(source,f.scale_frames([source])[0],(2,1,.5))
            self.assertTrue(result.isValid() and result.isClosed())
            self.assertEqual(len(result.Solids),1)
            self.assertEqual(len(result.Shells),len(source.Shells))
            # OCC spline surface mass integration is approximate; affine geometry
            # and closure, rather than that integration, establish the transform.
            self.assertLess(abs(result.Volume/source.Volume-1),.015)
            self.assertEqual(sorted(origins),list(range(len(source.Faces))))

    def test_world_and_local_axes_on_rotated_object(self):
        source=Part.makeBox(10,20,30)
        source.Placement=App.Placement(V(50,30,10),App.Rotation(V(1,2,3),37))
        for axes in ('World','Local'):
            frame=f.scale_frames([source],axes)[0];matrix=f.scale_matrix(frame,(2,1,.5))
            result,_=f.scaled(source,frame,(2,1,.5))
            self.assertAlmostEqual(result.Placement.Rotation.Angle,source.Placement.Rotation.Angle)
            for v in source.Vertexes:
                expected=matrix.multVec(v.Point)
                self.assertLess(min((w.Point-expected).Length for w in result.Vertexes),1e-6)
        self.assertAlmostEqual(source.Volume,6000)

    def test_shared_and_each_center(self):
        shapes=[Part.makeBox(10,10,10),Part.makeBox(10,10,10,V(30,0,0))]
        together=[f.scaled(s,frame,(2,2,2))[0] for s,frame in zip(shapes,f.scale_frames(shapes))]
        each=[f.scaled(s,frame,(2,2,2))[0] for s,frame in zip(shapes,f.scale_frames(shapes,pivot='Each'))]
        self.assertAlmostEqual((together[1].CenterOfMass-together[0].CenterOfMass).Length,60)
        self.assertAlmostEqual((each[1].CenterOfMass-each[0].CenterOfMass).Length,30)

    def test_invalid_scale_rejected(self):
        for values in [(0,1,1),(-1,1,1),(1,math.nan,1),(True,1,1),(1,2)]:
            with self.assertRaises(ValueError):f.factors(values)

    def test_loft_two_circles_forms_conical_frustum(self):
        a,b=circle(3),circle(1,10)
        for ruled in (False,True):
            result=f.loft([a,b],ruled=ruled)
            self.assertTrue(result.isValid() and result.isClosed())
            self.assertAlmostEqual(result.Volume,math.pi*10*(9+3+1)/3,places=4)
        self.assertEqual(a.BoundBox.ZMin,0);self.assertEqual(b.BoundBox.ZMin,10)

    def test_loft_multiple_profiles_and_surface(self):
        result=f.loft([circle(2),circle(4,5),circle(1,12)])
        self.assertTrue(result.isValid() and result.isClosed())
        surface=f.loft([Part.makeLine(V(),V(5,0,0)),Part.makeLine(V(0,0,10),V(3,0,10))],solid=False)
        self.assertTrue(surface.isValid());self.assertFalse(surface.Solids)

    def test_invalid_loft_profiles(self):
        for shapes in [[circle(2)],[circle(2),circle(2)], [Part.makeBox(1,1,1),circle(2,5)]]:
            with self.assertRaises(ValueError):f.loft(shapes)
        annulus=Part.Face([circle(3),circle(1)],'Part::FaceMakerBullseye')
        with self.assertRaises(ValueError):f.loft([annulus,circle(2,10)])
        with self.assertRaises(ValueError):f.loft([Part.makeLine(V(),V(2,0,0)),circle(2,10)])

    def test_sweep_alignment_on_displaced_path_preserves_profile(self):
        section=Part.Face(circle(2));source=section.copy()
        path=Part.makeLine(V(20,30,10),V(30,30,10))
        result=f.sweep(section,path)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertAlmostEqual(result.Volume,math.pi*40,places=5)
        self.assertLess((result.CenterOfMass-V(25,30,10)).Length,1e-6)
        self.assertLess((section.CenterOfMass-source.CenterOfMass).Length,1e-8)

    def test_curved_and_reversed_sweep(self):
        arc=Part.Arc(V(0,0,0),V(5,5,0),V(10,0,0)).toShape()
        for path in (arc,arc.reversed()):
            result=f.sweep(circle(.5),path)
            self.assertTrue(result.isValid() and result.isClosed())
            self.assertAlmostEqual(result.Volume,math.pi*.25*path.Length,places=4)

    def test_disconnected_path_rejected(self):
        path=Part.makeCompound([Part.makeLine(V(),V(10,0,0)),Part.makeLine(V(20,0,0),V(30,0,0))])
        with self.assertRaises(ValueError):f.sweep(circle(1),path)


class FormingWrites(unittest.TestCase):
    def setUp(self):
        self.doc=App.newDocument('FormingTest');self.doc.UndoMode=1
    def tearDown(self):App.closeDocument(self.doc.Name)
    def add(self,shape):
        obj=self.doc.addObject('Part::Feature','Shape');obj.Shape=shape;self.doc.recompute();return obj

    def test_scale_is_one_undo_and_stale_capture_rejected(self):
        a=self.add(Part.makeBox(10,10,10));b=self.add(Part.makeSphere(3))
        targets=ops.prepare_scaling([(a,()),(b,())]);count=self.doc.UndoCount
        ops.scale_objects(targets,(2,2,2))
        self.assertEqual(self.doc.UndoCount,count+1);self.assertAlmostEqual(a.Shape.Volume,8000)
        with self.assertRaises(ValueError):ops.scale_objects(targets,(2,2,2))
        self.doc.undo();self.assertAlmostEqual(a.Shape.Volume,1000)

    def test_lock_blocks_whole_object_scaling(self):
        a=self.add(Part.makeBox(10,10,10));locking.set_locked([(a,('Face1',))],True)
        with self.assertRaises(ValueError):ops.prepare_scaling([(a,())])

    def test_loft_commit_keeps_sources_and_undo_removes_result(self):
        a=self.add(Part.Face(circle(2)));b=self.add(Part.Face(circle(1,10)))
        targets=ops.prepare_profiles([(a,()),(b,())]);before=a.Shape.copy()
        result=ops.form_preview(targets,'Loft');obj=ops.commit_form(targets,'Loft',result)
        self.assertEqual(len(self.doc.Objects),3);self.assertTrue(obj.Shape.isClosed())
        self.assertAlmostEqual(a.Shape.Area,before.Area)
        self.doc.undo();self.assertEqual(len(self.doc.Objects),2)

    def test_changed_profile_rejects_preview_and_commit(self):
        a=self.add(Part.Face(circle(2)));b=self.add(Part.Face(circle(1,10)))
        targets=ops.prepare_profiles([(a,()),(b,())]);result=ops.form_preview(targets,'Loft')
        b.Shape=Part.Face(circle(3,10));self.doc.recompute()
        with self.assertRaises(ValueError):ops.commit_form(targets,'Loft',result)
        self.assertEqual(len(self.doc.Objects),2)
