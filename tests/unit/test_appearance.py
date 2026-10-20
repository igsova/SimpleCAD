"""Material edits preserve other properties and reject malformed/stale targets."""
import unittest
from types import SimpleNamespace
import FreeCAD as App
import Part
from simplecad.document import appearance as a
from simplecad.mcp.catalog import BY_NAME, validate


class AppearanceTests(unittest.TestCase):
    def target(self):
        material=App.Material();material.DiffuseColor=(.2,.4,.6);material.Transparency=.25
        obj=SimpleNamespace(Shape=Part.makeBox(10,10,10),ViewObject=SimpleNamespace(ShapeAppearance=(material,)),isValid=lambda:True)
        return obj,[(obj,obj.Shape,{2},(material,))]

    def test_face_edit_does_not_mutate_original_or_other_materials(self):
        obj,targets=self.target();original=a.fingerprint(obj.ViewObject.ShapeAppearance)
        values=a.plan(targets,color=[1,0,0],opacity=35)[0][1]
        self.assertEqual(a.fingerprint(obj.ViewObject.ShapeAppearance),original)
        self.assertEqual(tuple(values[2].DiffuseColor[:3]),(1.,0.,0.))
        self.assertAlmostEqual(values[2].Transparency,.65)
        for i in (0,1,3,4,5):self.assertEqual(a.fingerprint([values[i]]),original)

    def test_whole_opacity_retains_face_colors_and_uniform_compression(self):
        obj,targets=self.target();values=a.plan(targets,color=[1,0,0])[0][1]
        original=a.fingerprint(values)
        result=a.plan([(obj,obj.Shape,None,values)],opacity=0)[0][1]
        self.assertTrue(all(m.Transparency==1 for m in result))
        self.assertEqual([m.DiffuseColor for m in result],[m.DiffuseColor for m in values])
        self.assertEqual(a.fingerprint(values),original)
        self.assertEqual(len(a.plan([(obj,obj.Shape,None,values)],color=[0,1,0],opacity=100)[0][1]),1)

    def test_invalid_values_and_stale_topology_are_rejected(self):
        obj,targets=self.target()
        for color,opacity in (([2,0,0],None),([True,0,0],None),([0,0],None),(None,True),
                              (None,-1),(None,101),(None,float('nan')),([float('inf'),0,0],None)):
            with self.assertRaises(ValueError):a.plan(targets,color,opacity)
        obj.Shape=Part.makeCylinder(5,10)
        with self.assertRaisesRegex(ValueError,'shape changed'):a.plan(targets,opacity=50)

    def test_mcp_appearance_schema_bounds(self):
        schema=BY_NAME['simplecad_set_appearance']['inputSchema']
        args={'document':'Doc','expected_revision':'r','targets':[{'object':'Box','elements':['Face1']}],
              'color':[1,0,.5],'opacity':50}
        validate(args,schema)
        for update in ({'opacity':101},{'color':[0,0,-.1]},{'opacity':True},{'targets':[]}):
            with self.assertRaises(ValueError):validate({**args,**update},schema)
        self.assertFalse(BY_NAME['simplecad_set_appearance']['annotations']['readOnlyHint'])

    def test_revision_fingerprint_ignores_native_redraw_rounding(self):
        original=App.Material();original.DiffuseColor=(114/255,121/255,128/255)
        redrawn=a.clone(original)
        redrawn.DiffuseColor=tuple(round(c,6) for c in original.DiffuseColor[:3])
        self.assertEqual(a.fingerprint([original],6),a.fingerprint([redrawn],6))
        redrawn.DiffuseColor=(115/255,121/255,128/255)
        self.assertNotEqual(a.fingerprint([original],6),a.fingerprint([redrawn],6))

    def test_tree_materials_are_read_once_for_all_rows(self):
        obj, targets = self.target()
        materials = a.plan(targets, color=[1,0,0], opacity=57)[0][1]
        class View:
            reads = 0
            @property
            def ShapeAppearance(self):
                self.reads += 1
                return materials
        obj.ViewObject = View()
        whole, faces = a.describe_all(obj)
        self.assertEqual(obj.ViewObject.reads, 1)
        self.assertEqual(len(faces), 6)
        self.assertEqual(whole, {'color':None, 'opacity':None})
        self.assertEqual(faces[2], {'color':[1.,0.,0.], 'opacity':57})
        self.assertEqual(faces[0]['opacity'], 75)

    def test_uniform_tree_material_expands_without_more_native_reads(self):
        obj, _ = self.target()
        whole, faces = a.describe_all(obj)
        self.assertEqual(len(faces), 6)
        self.assertTrue(all(face == whole for face in faces))
        self.assertEqual(whole['opacity'], 75)


if __name__=='__main__':unittest.main()
