"""Fillet geometry, unchanged previews, atomic writes and ordinary saved solids."""
import math
from pathlib import Path
import tempfile
import unittest
import FreeCAD as App
import Part
from simplecad.modeling import rounding as r
from simplecad.core import geometry as g, coincident as coinc
from simplecad.document import operations as op
V=App.Vector

class RoundGeometryTests(unittest.TestCase):
    def setUp(self):self.box=Part.makeBox(40,30,20)

    def test_one_edge_has_expected_radius_and_volume(self):
        original=self.box.copy()
        indices=r.selected_edges(self.box,['Edge1'])
        result=r.round_edges(self.box,indices,2)
        self.assertEqual(result.ShapeType,'Solid');self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume,24000-(1-math.pi/4)*4*self.box.Edges[0].Length,places=6)
        cylinders=[f for f in result.Faces if isinstance(f.Surface,Part.Cylinder)]
        self.assertEqual(len(cylinders),1);self.assertAlmostEqual(cylinders[0].Surface.Radius,2)
        self.assertAlmostEqual(self.box.Volume,original.Volume)
        untouched=next(f for f in self.box.Faces if abs(f.CenterOfMass.x-40)<1e-6)
        self.assertTrue(any(coinc.same(f,untouched) for f in result.Faces))

    def test_face_and_whole_box_selection_round_multi_edge_corners(self):
        face=r.selected_edges(self.box,['Face6'])
        self.assertEqual(len(face),4)
        self.assertEqual(r.selected_edges(self.box,['Face6','Face6','Edge1']),tuple(sorted(set(face+(0,)))))
        result=r.round_edges(self.box,r.selected_edges(self.box),2)
        self.assertEqual(len(result.Faces),26);self.assertTrue(result.isValid())
        self.assertTrue(any(isinstance(f.Surface,Part.Sphere) for f in result.Faces))
        self.assertAlmostEqual(result.BoundBox.XLength,40)
        self.assertAlmostEqual(result.BoundBox.YLength,30)
        self.assertAlmostEqual(result.BoundBox.ZLength,20)
        self.assertTrue(r.round_edges(self.box,face,2).isValid())

    def test_zero_cancel_equivalent_invalid_values_and_impossible_radius(self):
        indices=r.selected_edges(self.box)
        result=r.round_edges(self.box,indices,0)
        self.assertEqual(len(result.Faces),6);self.assertAlmostEqual(result.Volume,24000)
        for radius in (-1,float('nan'),float('inf'),1e-8,100):
            with self.subTest(radius=radius),self.assertRaises(ValueError):
                r.round_edges(self.box,indices,radius)
        self.assertAlmostEqual(self.box.Volume,24000)

    def test_cylinder_seam_flat_divider_and_tangent_edges_skipped(self):
        cylinder=Part.makeCylinder(8,20)
        self.assertEqual(len(r.selected_edges(cylinder)),2)
        seam=next('Edge'+str(i+1) for i,e in enumerate(cylinder.Edges) if g.is_seam_edge(cylinder,e))
        with self.assertRaisesRegex(ValueError,'No sharp'):
            r.selected_edges(cylinder,[seam])
        self.assertTrue(r.round_edges(cylinder,r.selected_edges(cylinder),1).isValid())
        divided=g.divide_face_with_line(self.box,V(0,0,20),V(40,0,0))
        dividers=[i for i,e in enumerate(divided.Edges) if not r.sharp(divided,e)]
        self.assertEqual(len(dividers),1)
        self.assertNotIn(dividers[0],r.selected_edges(divided))
        rounded=r.round_edges(self.box,r.selected_edges(self.box),2)
        with self.assertRaisesRegex(ValueError,'No sharp'):
            r.selected_edges(rounded)

    def test_open_mixed_and_multiple_solids_fail_before_rounding(self):
        samples=[self.box.Faces[0],Part.makeLine(V(),V(1,0,0)),
                 Part.makeCompound([self.box,Part.makeBox(3,3,3,V(50,0,0))]),
                 Part.makeCompound([self.box,Part.makeLine(V(50,0,0),V(60,0,0))]),
                 g.erase_elements(self.box,['Face1'])]
        for shape in samples:
            with self.subTest(type=shape.ShapeType),self.assertRaises(ValueError):r.selected_edges(shape)
        for names in (['Vertex1'],['Face999'],['Edge0'],['Other.Edge1']):
            with self.assertRaises(ValueError):r.selected_edges(self.box,names)

    def test_rotated_reversed_closed_shell_and_compound(self):
        placement=App.Placement(V(50,-20,30),App.Rotation(V(1,2,3),37))
        self.box.Placement=placement
        for shape in (self.box,Part.makeShell(self.box.Faces),Part.makeCompound([self.box])):
            result=r.round_edges(shape,r.selected_edges(shape),2)
            self.assertEqual(result.ShapeType,'Solid');self.assertTrue(result.isValid())
            self.assertLess((result.CenterOfMass-self.box.CenterOfMass).Length,1e-6)
        reverse=self.box.copy();reverse.reverse()
        result=r.round_edges(reverse,r.selected_edges(reverse),2)
        self.assertTrue(result.isValid());self.assertGreater(result.Volume,0)

    def test_concave_pocket_rim_rounds_without_filling_hole(self):
        shape=self.box.cut(Part.makeCylinder(5,30,V(20,15,-5))).Solids[0]
        rims=[i for i,e in enumerate(shape.Edges) if isinstance(e.Curve,Part.Circle)]
        result=r.round_edges(shape,rims,1)
        self.assertTrue(result.isValid());self.assertEqual(len(result.Solids),1)
        self.assertAlmostEqual(result.common(Part.makeCylinder(4,40,V(20,15,-10))).Volume,0,places=6)

class RoundDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc=App.newDocument('RoundTest');self.doc.UndoMode=1
        self.obj=op.new_shape(self.doc,Part.makeBox(40,30,20),'Block')
    def tearDown(self):App.closeDocument(self.doc.Name)

    def test_preview_apply_undo_redo_and_zero_noop(self):
        obj=self.obj;count=self.doc.UndoCount;source=obj.Shape
        targets=op.prepare_rounding([(obj,['Face6'])])
        for radius in (1,2,3,0):
            planned=op.preview_rounding(targets,radius)
            self.assertEqual(self.doc.UndoCount,count);self.assertTrue(obj.Shape.isSame(source))
        self.assertFalse(op.commit_rounding(targets,planned,0));self.assertEqual(self.doc.UndoCount,count)
        planned=op.preview_rounding(targets,2)
        self.assertTrue(op.commit_rounding(targets,planned,2))
        volume=obj.Shape.Volume
        self.assertEqual(self.doc.UndoCount,count+1);self.assertEqual(len(self.doc.Objects),1)
        self.doc.undo();self.assertAlmostEqual(obj.Shape.Volume,24000)
        self.doc.redo();self.assertAlmostEqual(obj.Shape.Volume,volume)

    def test_multiple_objects_failure_is_atomic_and_changes_invalidate_preview(self):
        small=op.new_shape(self.doc,Part.makeBox(2,2,2,V(60,0,0)),'Small')
        targets=op.prepare_rounding([(self.obj,()),(small,())]);count=self.doc.UndoCount
        with self.assertRaises(ValueError):op.preview_rounding(targets,3)
        self.assertEqual(self.doc.UndoCount,count);self.assertAlmostEqual(self.obj.Shape.Volume,24000)
        planned=op.preview_rounding(targets,.2)
        op.commit_rounding(targets,planned,.2)
        self.assertEqual(self.doc.UndoCount,count+1)
        self.doc.undo();self.assertAlmostEqual(small.Shape.Volume,8)
        targets=op.prepare_rounding([(self.obj,['Edge1'])]);planned=op.preview_rounding(targets,1)
        op.transform([self.obj],V(5,0,0))
        with self.assertRaisesRegex(ValueError,'changed'):op.commit_rounding(targets,planned,1)

    def test_native_save_reopen_move_copy_and_further_editing(self):
        self.obj.Placement=App.Placement(V(100,20,30),App.Rotation(V(0,0,1),25))
        targets=op.prepare_rounding([(self.obj,())]);op.commit_rounding(targets,op.preview_rounding(targets,2),2)
        center=self.obj.Shape.CenterOfMass;volume=self.obj.Shape.Volume
        copy=op.transform([self.obj],V(50,0,0),copy=True)[0]
        self.assertLess((copy.Shape.CenterOfMass-center-V(50,0,0)).Length,1e-6)
        self.assertAlmostEqual(copy.Shape.Volume,volume)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Rounded.FCStd';self.doc.saveAs(str(path))
            name=self.obj.Name
            App.closeDocument(self.doc.Name)
            self.doc=App.openDocument(str(path))
            obj=self.doc.getObject(name)
            self.assertEqual(obj.TypeId,'Part::Feature');self.assertNotIn('Proxy',obj.PropertiesList)
            self.assertTrue(obj.Shape.isValid());self.assertAlmostEqual(obj.Shape.Volume,volume)
            face=next(f for f in obj.Shape.Faces if isinstance(f.Surface,Part.Plane))
            op.extrude(obj,face,1)
            self.assertTrue(obj.Shape.isValid())

    def test_selection_validation_and_whole_object_precedence(self):
        with self.assertRaisesRegex(ValueError,'Select'):op.prepare_rounding([])
        param=self.doc.addObject('Part::Box','Parametric');self.doc.recompute()
        with self.assertRaisesRegex(ValueError,'plain Part'):op.prepare_rounding([(param,())])
        targets=op.prepare_rounding([(self.obj,['Edge1']),(self.obj,()),(self.obj,['Edge2'])])
        self.assertEqual(len(targets),1);self.assertEqual(len(targets[0][2]),12)

if __name__=='__main__':unittest.main()
