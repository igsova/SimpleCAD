"""Plane manipulation math and pointer lifecycle, independent of native Qt."""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch
import numpy as np
from simplecad.mesh import handles as h
from simplecad.mesh.transform import Plan


class GeometryTests(unittest.TestCase):
    def test_euler_order_and_effective_drag_axes(self):
        rotation, _ = h.rotations((90,0,0))
        np.testing.assert_allclose(rotation @ (0,0,1), (0,-1,0), atol=1e-12)
        angles = np.array((31.,-24.,57.)); normal = np.array((.2,.3,.8)); normal /= np.linalg.norm(normal)
        rotation, axes = h.rotations(angles)
        np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-12)
        for i in range(3):
            moved = angles.copy(); moved[i] += .0001
            actual = (h.rotations(moved)[0] @ normal - rotation @ normal)/math.radians(.0001)
            np.testing.assert_allclose(actual, np.cross(axes[i], rotation @ normal), atol=1e-6)

    def test_plane_rotation_preserves_spacing_and_parallelism(self):
        origin = np.array((23,-17,9)); lower, upper = -4., 8.
        normal = h.rotations((22,34,-71))[0] @ (0,0,1)
        a, b = origin+normal*lower, origin+normal*upper
        self.assertAlmostEqual(np.linalg.norm(b-a), upper-lower)
        np.testing.assert_allclose(np.cross(b-a,normal), 0, atol=1e-12)

    def test_ring_projection_and_edge_on_hit(self):
        points = h.ring((0,0,0),(0,0,1),20)
        np.testing.assert_allclose(np.linalg.norm(points,axis=1),20)
        self.assertLess(h.nearest_segment((20,0),points[:,:2])[0], 1e-9)
        # A ring seen edge-on may contain zero-length projected segments.
        distance, index = h.nearest_segment((0,7),np.array(((0,0),(0,0),(0,10))))
        self.assertEqual(distance,0); self.assertAlmostEqual(index,1.7)

    def test_rotation_angle_wrap_and_edge_on_fallback(self):
        first=h.plane_angle((5,0,10),(0,0,-1),(0,0,0),(0,0,1))
        second=h.plane_angle((0,5,10),(0,0,-1),(0,0,0),(0,0,1))
        self.assertAlmostEqual(h.angle_step(first,second),math.pi/2)
        self.assertIsNone(h.plane_angle((0,0,10),(0,0,-1),(0,0,0),(1,0,0)))
        self.assertIsNone(h.plane_angle((0,0,10),(0,0,-1),(0,0,0),(0,0,1)))
        self.assertAlmostEqual(math.degrees(h.angle_step(math.radians(179),math.radians(-179))),2)
        self.assertAlmostEqual(h.tangent_rotation((10,10),(10,60),(0,100)),.5)

    def test_planes_cannot_cross_or_round_outside_mesh(self):
        self.assertAlmostEqual(h.drag_level(100,2,8,0,(0,10)),7.9999)
        self.assertAlmostEqual(h.drag_level(-100,2,8,1,(0,10)),2.0001)
        self.assertEqual(h.drag_level(-100,2,8,0,(.00006,9.99994)),.0001)
        self.assertEqual(h.drag_level(100,2,8,1,(.00006,9.99994)),9.9999)
        self.assertEqual(h.drag_level(1,-20,-10,0,(0,10)),-20)  # Move the other plane inside first.

    def test_angled_stretch_has_rigid_ends_and_closed_topology(self):
        from collections import Counter
        points=np.array([(x,y,z) for z in (0.,10.) for y in (0.,10.) for x in (0.,10.)])
        triangles=[(0,2,3),(0,3,1),(4,5,7),(4,7,6),(0,1,5),(0,5,4),
                   (2,6,7),(2,7,3),(0,4,6),(0,6,2),(1,3,7),(1,7,5)]
        normal=h.rotations((15,32,-24))[0] @ (0,0,1)
        plan=Plan(points,triangles,(5,5,5),normal,-2,2)
        delta=normal*3; moved=plan.transform(delta)
        np.testing.assert_allclose(moved[plan.weights==0],plan.points[plan.weights==0])
        np.testing.assert_allclose(moved[plan.weights==1],plan.points[plan.weights==1]+delta)
        edges=Counter(tuple(sorted((a,b))) for t in plan.triangles.tolist() for a,b in zip(t,t[1:]+t[:1]))
        self.assertTrue(all(n==2 for n in edges.values()))

    def test_invalid_angles_rejected(self):
        for angles in ((0,0),(0,0,181),(0,True,0),(0,float('nan'),0)):
            with self.assertRaises(ValueError): h.rotations(angles)


class Spin:
    def __init__(self, value): self.number=value
    def value(self): return self.number
    def setValue(self, value): self.number=value
    def blockSignals(self, value): pass


class PointerTests(unittest.TestCase):
    def setUp(self):
        qt=NS(AltModifier=1,ControlModifier=2,MetaModifier=4,ShiftModifier=8,
              OpenHandCursor=0,ClosedHandCursor=1,MouseFocusReason=0,LeftButton=1)
        event_types=NS(MouseButtonPress=1,MouseMove=2,MouseButtonRelease=3,Leave=4,UngrabMouse=5,Wheel=6)
        self.event_types, self.qt = event_types, qt
        self.view=NS(getSize=lambda:(600,600))
        modules={
            'FreeCAD':NS(Vector=lambda *xyz:np.asarray(xyz)), 'pivy':NS(coin=NS()),
            'simplecad.gui.previews.overlay':NS(AXIS_COLORS={},label_font=Mock(),pixel_ratio=lambda:1),
            'simplecad.gui.snapping':NS(camera_state=lambda view:('camera',),
                screen=lambda view,p:tuple(p)[:2],ray=lambda view,p:(np.array((*p,100)),np.array((0,0,-1))),
                pull_drag=lambda view,pos,anchor,normal,down,step:(float(pos[0])+123,None)),
            'simplecad.gui.qt':NS(QtCore=NS(Qt=qt,QEvent=event_types)),
        }
        path=Path(__file__).resolve().parents[2]/'simplecad/gui/tools/mesh_handles.py'
        spec=importlib.util.spec_from_file_location('simplecad.gui.tools._handles_test',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,modules): spec.loader.exec_module(module)
        self.widget=NS(width=lambda:600,height=lambda:600,cursor=lambda:'arrow',setCursor=Mock(),
                       setFocus=Mock(),grabMouse=Mock(),releaseMouse=Mock())
        self.s=NS(controller=NS(view=self.view,selection=NS(is_viewport=lambda w:w is self.widget)),
                  check=Mock(),closed=False,lower=Spin(2),upper=Spin(8),rotation=[Spin(0) for _ in range(3)],
                  apply_button=Mock(),update_preview=Mock(),orientation_changed=Mock(),
                  plane=NS(center=np.array((100,100,0)),normal=np.array((1,0,0)),size=100,lower=0,upper=10))
        self.s.angles=lambda:[w.value() for w in self.s.rotation]
        self.handles=module.PlaneHandles(self.s); self.handles.render=Mock()

    def event(self, kind, pos, modifiers=0):
        return NS(type=lambda:kind,localPos=lambda:NS(x=lambda:pos[0],y=lambda:600-pos[1]),
                  button=lambda:1,modifiers=lambda:modifiers)

    def test_mouse_drag_updates_numeric_plane_and_refines_on_release(self):
        handles=self.handles
        handles.markers={('plane',0):np.array((100,100,0))}
        self.assertTrue(handles.handle_event(self.widget,self.event(1,(100,100))))
        self.widget.grabMouse.assert_called_once()
        self.assertTrue(handles.handle_event(self.widget,self.event(2,(103,100))))
        self.assertEqual(self.s.lower.value(),5)  # Relative movement, no jump from the handle offset.
        self.assertTrue(handles.handle_event(self.widget,self.event(3,(104,100))))
        self.assertEqual(self.s.lower.value(),6)
        self.assertIsNone(handles.drag)
        self.widget.releaseMouse.assert_called_once()
        self.s.update_preview.assert_called_once()

    def test_rotation_ring_updates_angle_and_preserves_plane_offsets(self):
        handles=self.handles
        handles.lines={('rotate',2):h.ring((100,100,0),(0,0,1),28)}
        self.assertTrue(handles.handle_event(self.widget,self.event(1,(128,100))))
        handles.handle_event(self.widget,self.event(2,(100,128)))
        self.assertAlmostEqual(self.s.rotation[2].value(),90)
        self.assertEqual((self.s.lower.value(),self.s.upper.value()),(2,8))
        handles.finish(restore=True)
        self.assertEqual(self.s.angles(),[0,0,0])
        self.s.orientation_changed.assert_called_once()

    def test_navigation_and_dialog_events_are_not_consumed(self):
        self.handles.markers={('plane',0):np.array((100,100,0))}
        self.assertFalse(self.handles.handle_event(self.widget,self.event(1,(100,100),self.qt.AltModifier)))
        self.assertFalse(self.handles.handle_event(object(),self.event(1,(100,100))))
        self.assertFalse(self.handles.handle_event(self.widget,self.event(1,(300,300))))

    def test_closing_while_dragging_releases_mouse_and_cursor(self):
        self.handles.markers={('plane',0):np.array((100,100,0))}
        self.handles.handle_event(self.widget,self.event(1,(100,100)))
        self.handles.close()
        self.assertIsNone(self.handles.drag)
        self.widget.releaseMouse.assert_called_once()
        self.widget.setCursor.assert_called_with('arrow')


if __name__ == '__main__': unittest.main()
