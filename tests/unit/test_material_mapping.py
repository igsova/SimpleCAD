"""Materials follow surface regions, never their changing FaceN positions."""
import unittest
from unittest.mock import patch
import FreeCAD as App
import Part
from simplecad.document import materials as mapping
from simplecad.core import coincident
V=App.Vector


def material(color, transparency=0):
    value=App.Material(); value.DiffuseColor=color; value.Transparency=transparency
    return value


def style(value):
    return tuple(value.DiffuseColor[:3]), round(value.Transparency,5)


class MaterialMappingTests(unittest.TestCase):
    def setUp(self):
        self.gray=material((.4,.5,.6)); self.red=material((1,0,0),.43)

    def test_reordered_split_preserves_unrelated_red_face(self):
        left=Part.makePlane(10,10); red=Part.makePlane(10,10,V(10,0,0)); right=Part.makePlane(10,10,V(20,0,0))
        source=Part.makeCompound([left,red,right])
        changed=Part.makeCompound([right,Part.makePlane(5,10),red,Part.makePlane(5,10,V(5,0,0))])
        values=mapping.mapped(source,changed,[self.gray,self.red,self.gray])
        self.assertEqual([style(v) for v in values],[style(self.gray),style(self.gray),style(self.red),style(self.gray)])

    def test_children_of_styled_face_inherit_all_material_fields(self):
        source=Part.makeCompound([Part.makePlane(10,10),Part.makePlane(10,10,V(20,0,0)),Part.makePlane(10,10,V(40,0,0))])
        self.red.Shininess=.75
        changed=Part.makeCompound([Part.makePlane(5,10),Part.makePlane(5,10,V(5,0,0)),source.Faces[1],source.Faces[2]])
        values=mapping.mapped(source,changed,[self.red,self.gray,self.gray])
        for value in values[:2]:
            self.assertEqual(style(value),style(self.red)); self.assertAlmostEqual(value.Shininess,.75)
        self.assertEqual(style(values[2]),style(self.gray))

    def test_trimmed_circular_face_and_annulus_inherit(self):
        disk=Part.Face(Part.Wire(Part.makeCircle(5)))
        inner=Part.Face(Part.Wire(Part.makeCircle(2)))
        source=Part.makeCompound([disk,Part.makePlane(10,10,V(20,0,0)),Part.makePlane(10,10,V(40,0,0))])
        changed=Part.makeCompound([disk.cut(inner),inner,source.Faces[1],source.Faces[2]])
        values=mapping.mapped(source,changed,[self.red,self.gray,self.gray])
        self.assertEqual([style(v) for v in values[:2]],[style(self.red)]*2)

    def test_merge_uses_largest_contributing_face(self):
        source=Part.makeCompound([Part.makePlane(2,10),Part.makePlane(8,10,V(2,0,0)),Part.makePlane(10,10,V(30,0,0))])
        changed=Part.makeCompound([Part.makePlane(10,10),source.Faces[2]])
        values=mapping.mapped(source,changed,[self.red,self.gray,self.gray])
        self.assertTrue(all(style(v)==style(self.gray) for v in values))

    def test_same_bounds_do_not_transfer_style_through_a_hole(self):
        outer=Part.Face(Part.Wire(Part.makeCircle(5)))
        inner=Part.Face(Part.Wire(Part.makeCircle(2)))
        ring=outer.cut(inner)
        source=Part.makeCompound([ring,Part.makePlane(10,10,V(20,0,0)),Part.makePlane(10,10,V(40,0,0))])
        changed=Part.makeCompound([inner,ring,source.Faces[1],source.Faces[2]])
        values=mapping.mapped(source,changed,[self.red,self.gray,self.gray])
        self.assertEqual(style(values[0]),style(self.gray));self.assertEqual(style(values[1]),style(self.red))

    def test_rigid_placement_and_uniform_materials_keep_styles(self):
        source=Part.makeBox(10,10,10); moved=Part.Shape(source)
        moved.Placement=App.Placement(V(12,25,37),App.Rotation(V(1,2,3),41))
        values=[self.red]+[self.gray]*5
        self.assertEqual([style(v) for v in mapping.mapped(source,moved,values)],[style(v) for v in values])
        self.assertEqual(style(mapping.mapped(source,Part.makeCylinder(5,10),[self.red])[0]),style(self.red))

    def test_native_owned_edges_need_no_geometric_comparisons(self):
        # Regression for the line tool's quadratic scan over all solid edges.
        shape=Part.makeCompound([Part.makeBox(10,10,10,V(i*20,0,0)) for i in range(12)])
        with patch.object(coincident,'same',side_effect=AssertionError('Unnecessary geometric comparison')):
            self.assertEqual(coincident.loose_edges(shape),[])

    def test_loose_edge_filter_keeps_partial_and_nearby_lines(self):
        face=Part.makePlane(10,10)
        duplicate=Part.makeLine(V(0,0,0),V(10,0,0))
        loose=Part.makeLine(V(0,0,1),V(10,0,1))
        partial=Part.makeLine(V(0,0,0),V(5,0,0))
        result=coincident.loose_edges(Part.makeCompound([face,duplicate,loose,partial]))
        self.assertEqual(len(result),2)
        self.assertTrue(any(coincident.same(e,loose) for e in result))
        self.assertTrue(any(coincident.same(e,partial) for e in result))
