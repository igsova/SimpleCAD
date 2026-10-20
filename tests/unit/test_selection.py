"""Selection uses real face interiors and curves, not only bounding boxes."""
import unittest
from types import SimpleNamespace
import FreeCAD as App
import Part
from pivy import coin
from simplecad.gui import box_selection as s
from simplecad.core import geometry as g

V = App.Vector

class View:
    def __init__(self, perspective=False):
        self.camera = coin.SoPerspectiveCamera() if perspective else coin.SoOrthographicCamera()
        self.camera.position.setValue(0, 0, 100)
        self.perspective = perspective
    def getCameraNode(self):return self.camera
    def getViewDirection(self):return V(0, 0, -1)
    def getPointOnScreen(self, p):
        scale = 100 / (100-p.z) if self.perspective else 1
        return p.x*scale, p.y*scale

def obj(shape, name='Shape', visible=True, selectable=True, placement=None):
    return SimpleNamespace(Name=name, Shape=shape, isDerivedFrom=lambda _: True,
        getGlobalPlacement=lambda: placement or shape.Placement,
        ViewObject=SimpleNamespace(Visibility=visible, Selectable=selectable, isVisible=lambda: visible))

class SelectionTests(unittest.TestCase):
    def test_window_vs_crossing_same_rectangle_and_inclusive_contact(self):
        shape=Part.makeCompound([Part.makePlane(10,10), Part.makePlane(20,10,V(10,0,0))])
        doc=SimpleNamespace(Objects=[obj(shape)])
        names=lambda a,b:{name for _,name in s.box_selection(doc,View(),a,b)}
        window=names((-1,-1),(11,11));crossing=names((11,11),(-1,-1))
        self.assertIn('Face1',window);self.assertNotIn('Face2',window)
        self.assertTrue({'Face1','Face2'} <= crossing)
        self.assertTrue(window <= crossing)
        self.assertIn('Face2',names((10,11),(-1,-1)))
        self.assertNotIn('Face2',names((-1,-1),(9.9,11)))

    def test_crossing_edge_without_endpoints_and_no_false_bounds_hit(self):
        edge=Part.makeLine(V(-10,0,0),V(10,0,0))
        hit=lambda box,c=True:s.shape_hits(edge,lambda p:(p.x,p.y),box,c,.01)
        self.assertTrue(hit((-1,-1,1,1)))
        self.assertFalse(hit((-1,-1,1,1),False))
        diagonal=Part.makeLine(V(0,0,0),V(10,10,0))
        self.assertFalse(s.shape_hits(diagonal,lambda p:(p.x,p.y),(0,8,2,10),True,.01))
        self.assertTrue(s.segment_hits((0,0),(5,5),(5,5,8,8)))

    def test_rectangle_inside_face_without_any_boundary_hits(self):
        face=Part.makePlane(100,100)
        self.assertTrue(s.shape_hits(face,lambda p:(p.x,p.y),(20,20,21,21),True,.01))
        self.assertFalse(s.shape_hits(face,lambda p:(p.x,p.y),(20,20,21,21),False,.01))

    def test_hole_and_concavity_do_not_select_empty_space(self):
        disk=g.circle(g.Plane.named('XY'),V(5,5,0),2)
        ring=Part.makePlane(10,10).cut(disk).Faces[0]
        self.assertFalse(s.shape_hits(ring,lambda p:(p.x,p.y),(4.5,4.5,5.5,5.5),True,.005))
        self.assertTrue(s.shape_hits(ring,lambda p:(p.x,p.y),(2.5,4.5,3.5,5.5),True,.005))
        concave=Part.makePlane(10,10).cut(Part.makePlane(5,5,V(5,5,0))).Faces[0]
        self.assertFalse(s.shape_hits(concave,lambda p:(p.x,p.y),(6,6,9,9),True,.005))

    def test_circle_curved_extents_not_just_seam_vertex(self):
        disk=g.circle(g.Plane.named('XY'),V(0,0,0),10)
        for shape in (disk,disk.Edges[0]):
            self.assertFalse(s.shape_hits(shape,lambda p:(p.x,p.y),(9,-1,11,1),False,.001))
            self.assertTrue(s.shape_hits(shape,lambda p:(p.x,p.y),(-11,-11,11,11),False,.001))
            self.assertTrue(s.shape_hits(shape,lambda p:(p.x,p.y),(-11,-1,-9,1),True,.001))
        self.assertFalse(s.shape_hits(disk,lambda p:(p.x,p.y),(8,8,10,10),True,.001))

    def test_hidden_unselectable_objects_and_seams(self):
        cylinder=Part.makeCylinder(2,5)
        objects=[obj(cylinder),obj(cylinder,'Hidden',False),obj(cylinder,'Locked',selectable=False)]
        doc=SimpleNamespace(Objects=objects)
        hidden=s.box_selection(doc,View(),(-10,-10),(10,10))
        shown=s.box_selection(doc,View(),(-10,-10),(10,10),True)
        self.assertTrue(all(o.Name=='Shape' for o,n in shown))
        self.assertEqual(len(shown),len(hidden)+1)

    def test_parent_placement_and_perspective(self):
        face=Part.makePlane(10,10)
        moved=obj(face,placement=App.Placement(V(30,20,50),App.Rotation()))
        doc=SimpleNamespace(Objects=[moved])
        self.assertFalse(s.box_selection(doc,View(),(-1,-1),(11,11)))
        self.assertTrue(s.box_selection(doc,View(),(29,19),(41,31)))
        self.assertTrue(s.box_selection(doc,View(True),(59,39),(81,61)))
        self.assertFalse(s.box_selection(doc,View(True),(29,19),(41,31)))
        moved.getGlobalPlacement=lambda: App.Placement(V(0,0,110),App.Rotation())
        self.assertFalse(s.box_selection(doc,View(True),(-100,-100),(100,100)))

if __name__=='__main__':unittest.main()
