import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import FreeCAD as App
import Part
from simplecad.gui.pull_snapping import PullReferences

V = App.Vector


class PullReferenceTests(unittest.TestCase):
    def obj(self, shape, visible=True):
        return SimpleNamespace(Name='Reference', TypeId='Part::Feature', Shape=shape,
                               InList=[], ViewObject=SimpleNamespace(Visibility=visible))

    def refs(self, shape, anchor=V(0, 0, 20), normal=V(0, 0, 1), visible=True):
        obj = self.obj(shape, visible)
        result = PullReferences(SimpleNamespace(Objects=[obj]), None, anchor, normal)
        return obj, result

    def snap(self, refs, pos, hit=None, radius=24):
        with patch('simplecad.gui.pull_snapping.screen', side_effect=lambda view,p:(p.x*10,p.y*10)), \
             patch('simplecad.gui.pull_snapping.ray', return_value=(V(0,0,100),V(0,0,-1))), \
             patch('simplecad.gui.pull_snapping.pick', return_value=hit):
            return refs.snap(pos,radius)

    def test_anywhere_along_edge_and_larger_capture_band(self):
        _, refs = self.refs(Part.makeLine(V(20,0,5), V(80,0,5)))
        for x in (210,340,670,790):
            snap = self.snap(refs, (x,20))
            self.assertEqual(snap.distance,-15)
            self.assertEqual(snap.label,'Edge level')
        self.assertIsNone(self.snap(refs,(400,25)))
        self.assertIsNone(self.snap(refs,(400,20),radius=12))

    def test_level_is_measured_from_the_pulled_face_not_the_picked_point(self):
        # A picked point is single precision: 2e-6 mm off a face 300 mm up.
        top, base = 299.3590717632093, 163.80483690877227
        pulled = Part.makePlane(10, 10, V(0, 0, top))
        picked = V(5, 5, struct.unpack('f', struct.pack('f', top))[0])
        self.assertGreater(abs(picked.z - top), 1e-6)
        reference = Part.makePlane(40, 40, V(20, 20, base))
        obj = self.obj(reference)
        refs = PullReferences(SimpleNamespace(Objects=[obj]), None, picked, V(0, 0, 1), pulled)
        snap = self.snap(refs, (400, 400), (obj, reference, V(40, 40, base), 'Face1'))
        self.assertAlmostEqual(snap.distance, base - top, places=12)

    def test_hovered_parallel_face_uses_exact_level(self):
        face = Part.makePlane(40,40,V(20,20,5))
        obj, refs = self.refs(face)
        snap = self.snap(refs,(400,400),(obj,face,V(40,40,5),'Face1'))
        self.assertEqual(snap.distance,-15)
        self.assertEqual(snap.label,'Face level')

    def test_source_level_and_hidden_object_are_ignored(self):
        for z, visible in ((20,True),(5,False)):
            _, refs = self.refs(Part.makeLine(V(0,0,z),V(10,0,z)),visible=visible)
            self.assertIsNone(self.snap(refs,(50,0)))

    def test_sloping_edges_are_not_false_height_references(self):
        _, refs = self.refs(Part.makeLine(V(),V(10,0,10)))
        self.assertFalse(refs.edges)

    def test_circular_edge_keeps_exact_height_and_sphere_poles_are_safe(self):
        _, refs = self.refs(Part.makeCompound([Part.makeCircle(10,V(0,0,5)),Part.makeSphere(2,V(100,100,100))]))
        snap = self.snap(refs,(100,0))
        self.assertEqual(snap.distance,-15)

    def test_oblique_normal_and_positive_distance(self):
        rotation = App.Rotation(V(1,2,3),51)
        edge=Part.makeLine(V(20,0,30),V(40,0,30))
        edge.rotate(V(),V(1,2,3),51)
        _, refs=self.refs(edge,rotation.multVec(V(0,0,20)),rotation.multVec(V(0,0,1)))
        self.assertEqual(len(refs.edges),1)
        self.assertAlmostEqual(refs.edges[0][0],10)

    def test_hidden_face_edges_are_excluded(self):
        with patch('simplecad.gui.pull_snapping.visibility.hidden_faces',return_value={1}):
            _,refs=self.refs(Part.makePlane(40,40,V(20,20,5)))
        self.assertFalse(refs.faces)
        self.assertFalse(refs.edges)

    def test_edge_behind_visible_surface_does_not_attract(self):
        obj, refs = self.refs(Part.makeLine(V(0,0,5),V(10,0,5)))
        front = self.obj(Part.makePlane(20,20,V(0,0,10)))
        hit = (front,front.Shape,V(5,0,10),'Face1')
        self.assertIsNone(self.snap(refs,(50,0),hit))

    def test_overlapping_references_share_pick_only_within_one_motion(self):
        _, refs = self.refs(Part.makeLine(V(0,0,5),V(10,0,5)))
        refs.edges *= 100
        front = self.obj(Part.makePlane(20,20,V(0,0,10)))
        hit = (front,front.Shape,V(5,0,10),'Face1')
        with patch('simplecad.gui.pull_snapping.screen', side_effect=lambda view,p:(p.x*10,p.y*10)), \
             patch('simplecad.gui.pull_snapping.ray', return_value=(V(0,0,100),V(0,0,-1))), \
             patch('simplecad.gui.pull_snapping.pick', return_value=hit) as picking:
            self.assertIsNone(refs.snap((50,0),24))
            self.assertEqual(picking.call_count,2)  # One occlusion query and the face fallback.
            picking.reset_mock()
            picking.return_value = None  # Scene/view changed before the next motion.
            self.assertEqual(refs.snap((50,0),24).distance,-15)
            picking.assert_called_once()
