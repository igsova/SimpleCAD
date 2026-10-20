"""A coplanar strip merge must not disconnect an unrelated spherical seam."""
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g, coincident
from simplecad.modeling import subdivision
V=App.Vector


def recessed_grid():
    shape=Part.makeBox(60,60,60)
    for original in list(shape.Faces):
        index=next(i for i,f in enumerate(shape.Faces) if (f.CenterOfMass-original.CenterOfMass).Length<1e-6 and abs(f.Area-3600)<1e-6)
        shape,_=subdivision.divide(shape,index,3,3,pattern='spaced')
    for tool in (Part.makeBox(100,20,20,V(-20,20,20)),Part.makeBox(20,100,20,V(20,-20,20)),Part.makeBox(20,20,100,V(20,20,-20))):
        shape=shape.cut(tool)
    shape=shape.cut(Part.makeSphere(5.43857577625718,V(30,50,60)))
    face=next(f for f in shape.Faces if (f.CenterOfMass-V(50,10,60)).Length<1e-6)
    shape=g.push_pull(shape,face,-20)
    return g.divide_face_with_line(shape,V(40.84737421439397,0,40),V(40.84737421439397,20,40))


class EdgeMergeSeamTests(unittest.TestCase):
    def test_strip_merge_retains_spherical_recess_and_other_divisions(self):
        shape=recessed_grid()
        name=next('Edge'+str(i) for i,e in enumerate(shape.Edges,1) if (e.CenterOfMass-V(40.84737421439397,10,40)).Length<1e-6)
        edge=shape.getElement(name)
        unchanged=[f for f in shape.Faces if not any(edge.isSame(e) for e in f.Edges)]
        result=g.erase_elements(shape.copy(),[name])
        self.assertTrue(result.isValid() and result.isClosed())
        result.check(True)
        self.assertEqual(len(result.Faces),len(shape.Faces)-1)
        self.assertAlmostEqual(result.Volume,shape.Volume,places=6)
        self.assertAlmostEqual(result.Area,shape.Area,places=6)
        self.assertTrue(all(any(coincident.same(f,other) for other in result.Faces) for f in unchanged))
        self.assertFalse(any(coincident.same(edge,e) for e in result.Edges))
        restored=Part.Shape()
        restored.importBrepFromString(result.exportBrepToString())
        self.assertTrue(restored.isValid() and restored.isClosed())
        self.assertAlmostEqual(restored.Volume,shape.Volume,places=6)

    def test_rotated_placed_strip_merges_without_moving_any_surface(self):
        shape=recessed_grid()
        edge=next(e for e in shape.Edges if (e.CenterOfMass-V(40.84737421439397,10,40)).Length<1e-6)
        name=next('Edge'+str(i) for i,e in enumerate(shape.Edges,1) if e.isSame(edge))
        shape.Placement=App.Placement(V(-23,51,14),App.Rotation(V(1,2,3),37))
        result=g.erase_elements(shape.copy(),[name])
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Faces),len(shape.Faces)-1)
        self.assertAlmostEqual(result.Volume,shape.Volume,places=6)
        self.assertAlmostEqual(result.Area,shape.Area,places=6)
        self.assertLess((result.CenterOfMass-shape.CenterOfMass).Length,1e-7)
