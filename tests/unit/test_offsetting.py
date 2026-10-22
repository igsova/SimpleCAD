"""Offset dimensions, native topology, open curves and atomic editing."""
import math
import tempfile
from pathlib import Path
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.document import operations as op, locking
from simplecad.modeling import arcs
from simplecad.modeling.offsetting import Profile
V=App.Vector


def rect(): return g.rectangle(g.Plane.named(),V(),V(20,10,0))


class OffsetTests(unittest.TestCase):
    def doc(self):
        doc=App.newDocument('OffsetTest'); doc.UndoMode=1; name=doc.Name
        self.addCleanup(lambda:App.closeDocument(name) if name in App.listDocuments() else None)
        return doc

    def test_rectangle_dimensions_and_cursor_side(self):
        profile=Profile(rect())
        self.assertAlmostEqual(profile.distance_at(V(10,2,0)),-2)
        self.assertAlmostEqual(profile.distance_at(V(10,-2,0)),2)
        for distance,width,height in ((-2,16,6),(2,24,14)):
            result=profile.offset(distance)
            self.assertTrue(result.isValid()); self.assertEqual(len(result.Edges),4)
            self.assertAlmostEqual(result.BoundBox.XLength,width)
            self.assertAlmostEqual(result.BoundBox.YLength,height)
            self.assertAlmostEqual(result.Area,width*height)

    def test_oblique_reversed_face_and_polygon(self):
        face=g.polygon(g.Plane.named(),V(),V(10,0,0),6)
        face.rotate(V(),V(1,2,3),47); face.translate(V(3,8,11)); face.reverse()
        smaller=Profile(face).offset(-1); larger=Profile(face).offset(1)
        self.assertTrue(smaller.isValid() and larger.isValid())
        self.assertLess(smaller.Area,face.Area); self.assertGreater(larger.Area,face.Area)
        self.assertEqual(len(smaller.Edges),6)
        self.assertAlmostEqual(smaller.common(face).Area,smaller.Area,places=6)

    def test_face_with_hole_offsets_all_boundaries(self):
        face=Part.Face(Part.Wire([Part.makeCircle(10)])).cut(Part.Face(Part.Wire([Part.makeCircle(3)]))).Faces[0]
        for distance in (-1,1):
            result=Profile(face).offset(distance)
            self.assertEqual(len(result.Wires),2)
            radii=sorted(edge.Curve.Radius for edge in result.Edges)
            self.assertAlmostEqual(radii[0],3-distance); self.assertAlmostEqual(radii[1],10+distance)
        self.assertAlmostEqual(Profile(face).distance_at(V(0,0,0)),3)

    def test_holed_face_regions_and_disappearing_hole(self):
        for distance in (-1,1,4):
            doc=self.doc()
            ring=Part.Face(Part.Wire([Part.makeCircle(10)])).cut(Part.Face(Part.Wire([Part.makeCircle(3)]))).Faces[0]
            obj=op.new_shape(doc,ring,'Ring')
            results=op.offset(obj,'Face1',distance)
            self.assertEqual(results,[obj]);self.assertTrue(obj.Shape.isValid())
            self.assertGreater(len(obj.Shape.Faces),1)
            if distance<0:self.assertAlmostEqual(obj.Shape.Area,ring.Area,places=5)
            else:
                expected=math.pi*((10+distance)**2-max(0,3-distance)**2)
                self.assertAlmostEqual(obj.Shape.Area,expected,places=5)

    def test_inset_collapse_and_bad_dimensions_leave_source(self):
        p=Profile(rect())
        for distance in (0,True,math.nan,math.inf,-5,-6):
            with self.assertRaises(ValueError): p.offset(distance)
        self.assertAlmostEqual(p.source.Area,200)
        with self.assertRaises(ValueError): Profile(Part.makeSphere(3).Faces[0])

    def test_line_offset_plane_side_length_and_no_caps(self):
        edge=Part.makeLine(V(2,0,0),V(2,0,10)); p=Profile(edge,V(1,0,0))
        for distance in (-3,3):
            result=p.offset(distance)
            self.assertEqual(len(result.Edges),1); self.assertFalse(result.Faces)
            self.assertAlmostEqual(result.Length,10)
            self.assertAlmostEqual(result.CenterOfMass.y,-distance)
            self.assertAlmostEqual(p.distance_at(result.CenterOfMass),distance)
        with self.assertRaises(ValueError): Profile(edge)
        with self.assertRaises(ValueError): Profile(edge,V(0,0,1))

    def test_arc_preserves_sweep_and_plane_circle_stays_wire(self):
        for sweep in (90,-270):
            edge=arcs.centered(V(5,2,3),V(5,7,3),V(1,0,0),sweep).edge()
            edge.reverse()
            for distance in (-2,2):
                result=Profile(edge).offset(distance)
                self.assertIsInstance(result.Curve,Part.Circle)
                self.assertAlmostEqual(result.Curve.Radius,5+distance)
                self.assertAlmostEqual(result.Length,(5+distance)*abs(math.radians(sweep)))
                self.assertFalse(result.isClosed()); self.assertFalse(result.Faces)
                self.assertEqual(result.Orientation,edge.Orientation)
            with self.assertRaises(ValueError): Profile(edge).offset(-5)
        circle=Profile(Part.makeCircle(5)).offset(-1)
        self.assertTrue(circle.isClosed()); self.assertFalse(circle.Faces)

    def test_inset_face_is_selectable_and_pullable_with_undo(self):
        doc=self.doc(); obj=op.new_shape(doc,Part.makeBox(20,10,5),'Box'); count=doc.UndoCount
        op.offset(obj,'Face6',-2)
        self.assertEqual(len(obj.Shape.Faces),7); self.assertTrue(obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume,1000)
        self.assertEqual(doc.UndoCount,count+1)
        region=next(f for f in obj.Shape.Faces if abs(f.Area-96)<1e-6)
        op.extrude(obj,region,2); self.assertAlmostEqual(obj.Shape.Volume,1192)
        doc.undo();doc.undo();self.assertEqual(len(obj.Shape.Faces),6)
        doc.redo();self.assertEqual(len(obj.Shape.Faces),7)

    def test_outward_standalone_face_has_inner_face_and_border(self):
        doc=self.doc();obj=op.new_shape(doc,rect(),'Sheet')
        result=op.offset(obj,'Face1',2)
        self.assertEqual(result,[obj]); self.assertEqual(len(doc.Objects),1)
        self.assertEqual(len(obj.Shape.Faces),2); self.assertAlmostEqual(obj.Shape.Area,336)
        self.assertTrue(any(abs(f.Area-200)<1e-6 for f in obj.Shape.Faces))
        self.assertTrue(obj.Shape.isValid())

    def test_outward_solid_keeps_solid_and_creates_only_border(self):
        doc=self.doc();obj=op.new_shape(doc,Part.makeBox(20,10,5),'Box');count=doc.UndoCount
        result=op.offset(obj,'Face6',2)
        self.assertEqual(len(result),2); self.assertEqual(len(doc.Objects),2)
        self.assertTrue(obj.Shape.isValid() and obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume,1000)
        self.assertAlmostEqual(result[1].Shape.Area,136)
        self.assertAlmostEqual(result[1].Shape.common(obj.Shape.Faces[5]).Area,0)
        self.assertEqual(doc.UndoCount,count+1)
        doc.undo();self.assertEqual(len(doc.Objects),1)

    def test_outward_subface_partitions_neighboring_faces_without_overlay(self):
        doc=self.doc();obj=op.new_shape(doc,Part.makeBox(20,20,5),'Box')
        profile=g.rectangle(g.Plane.named('XY',V(0,0,5)),V(5,5,5),V(15,15,5))
        op.draw_profile(doc,profile,obj,'Inner')
        index=next(i for i,f in enumerate(obj.Shape.Faces) if abs(f.Area-100)<1e-6 and abs(f.CenterOfMass.z-5)<1e-6)
        results=op.offset(obj,'Face'+str(index+1),2)
        self.assertEqual(results,[obj]); self.assertEqual(len(obj.Shape.Faces),8)
        self.assertAlmostEqual(obj.Shape.Volume,2000); self.assertTrue(obj.Shape.isValid())

    def test_edge_copy_never_completes_a_face_or_partitions_support(self):
        doc=self.doc();obj=op.new_shape(doc,Part.makeBox(20,10,5),'Box')
        edgeindex=next(i for i,e in enumerate(obj.Shape.Edges) if all(abs(v.Point.y)<1e-6 and abs(v.Point.z-5)<1e-6 for v in e.Vertexes))
        results=op.offset(obj,'Edge'+str(edgeindex+1),2,V(0,0,1))
        self.assertEqual(len(obj.Shape.Faces),6);self.assertFalse(results[0].Shape.Faces)
        self.assertEqual(len(doc.Objects),2)
        # Even three pre-existing sides plus the new fourth offset edge stay wires.
        doc2=self.doc();source=op.new_shape(doc2,Part.makeLine(V(),V(10,0,0)),'Line')
        for a,b in ((V(0,0,0),V(0,5,0)),(V(10,0,0),V(10,5,0))): op.new_shape(doc2,Part.makeLine(a,b),'Line')
        op.offset(source,'Edge1',5,V(0,0,1))
        self.assertTrue(all(not obj.Shape.Faces for obj in doc2.Objects))

    def test_face_locks_invalid_names_and_failures_are_atomic(self):
        doc=self.doc();obj=op.new_shape(doc,Part.makeBox(20,10,5),'Box')
        locking.set_locked([(obj,['Face6'])],True);count=doc.UndoCount
        for name,d in (('Face6',-1),('Vertex1',1),('Face999',1)):
            with self.assertRaises(ValueError):op.offset(obj,name,d)
            self.assertEqual(doc.UndoCount,count);self.assertEqual(len(obj.Shape.Faces),6)
        locking.set_locked([(obj,['Face6'])],False);count=doc.UndoCount
        with self.assertRaises(ValueError):op.offset(obj,'Face6',-10)
        self.assertEqual(doc.UndoCount,count)

    def test_concave_face_and_saved_native_result(self):
        doc=self.doc();points=[V(0,0,0),V(12,0,0),V(12,4,0),V(4,4,0),V(4,12,0),V(0,12,0),V()]
        obj=op.new_shape(doc,Part.Face(Part.makePolygon(points)),'L face')
        op.offset(obj,'Face1',-1)
        self.assertTrue(obj.Shape.isValid());self.assertEqual(len(obj.Shape.Faces),2)
        self.assertAlmostEqual(obj.Shape.Area,80)
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'offset.FCStd');name=doc.Name;doc.saveAs(path);App.closeDocument(name)
            reopened=App.openDocument(path)
            self.assertTrue(reopened.Objects[0].Shape.isValid());self.assertEqual(len(reopened.Objects[0].Shape.Faces),2)
            App.closeDocument(reopened.Name)

    def test_closed_circle_edge_offset_partitions_face_and_is_extrudable(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10).cut(Part.makeCylinder(5, 10, App.Vector(20, 20, 0)))
        obj = op.new_shape(doc, box, 'BoxWithHole')
        c_edge = next(e for e in obj.Shape.Edges if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Center.z - 10) < 1e-5)
        c_name = next('Edge%d' % i for i, e in enumerate(obj.Shape.Edges, 1) if e.isSame(c_edge))
        results = op.offset(obj, c_name, 3.0)
        self.assertEqual(results, [obj])
        self.assertEqual(len(obj.Shape.Faces), 8)
        self.assertTrue(obj.Shape.isValid() and obj.Shape.isClosed())
        expected_annular = math.pi * (8**2 - 5**2)
        annular = next(f for f in obj.Shape.Faces if abs(f.Area - expected_annular) < 0.01)
        self.assertIsNotNone(annular)
        op.extrude(obj, annular, 4.0)
        self.assertTrue(obj.Shape.isValid() and obj.Shape.isClosed())
        self.assertAlmostEqual(obj.Shape.Volume, (40*40*10 - math.pi*25*10 + expected_annular*4), places=3)

    def test_offset_cylindrical_face_on_solid(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10).cut(Part.makeCylinder(5, 10, App.Vector(20, 20, 0)))
        obj = op.new_shape(doc, box, 'BoxWithHole')
        cyl_face_name = next('Face%d' % i for i, f in enumerate(obj.Shape.Faces, 1) if isinstance(f.Surface, Part.Cylinder))
        results = op.offset(obj, cyl_face_name, 2.5)
        self.assertEqual(results, [obj])
        self.assertEqual(len(obj.Shape.Faces), 8)
        self.assertTrue(obj.Shape.isValid() and obj.Shape.isClosed())
        expected_annular = math.pi * (7.5**2 - 5**2)
        annular = next(f for f in obj.Shape.Faces if abs(f.Area - expected_annular) < 0.01)
        self.assertIsNotNone(annular)

    def test_heal_dangling_offset_edge(self):
        doc = self.doc()
        box = Part.makeBox(40, 40, 10).cut(Part.makeCylinder(5, 10, App.Vector(20, 20, 0)))
        solid_obj = op.new_shape(doc, box, 'BoxWithHole')
        # Create a standalone offset edge object at z=10
        circle_edge = Part.makeCircle(8.0, App.Vector(20, 20, 10), App.Vector(0, 0, 1))
        op.new_shape(doc, circle_edge, 'Offset edge')
        self.assertEqual(len(doc.Objects), 2)
        self.assertEqual(len(solid_obj.Shape.Faces), 7)
        # Running cleanup should heal the wire into the solid
        healed_count = op.heal_dangling_wires(doc)
        self.assertEqual(healed_count, 1)
        self.assertEqual(len(doc.Objects), 1)
        self.assertEqual(len(solid_obj.Shape.Faces), 8)
        self.assertTrue(solid_obj.Shape.isValid())


