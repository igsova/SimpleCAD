"""Surface outlines use native curves, real regions and atomic document edits."""
import math
from pathlib import Path
import tempfile
import unittest

import FreeCAD as App
import Part

from simplecad.modeling import arcs
from simplecad.core import geometry as geo
from simplecad.document import operations as ops, locking
from simplecad.surfaces.drawing import SurfaceFrame
from simplecad.surfaces.line import covered, preserves_area, preserves_volume, same_boundary

V = App.Vector
XY = geo.Plane.named('XY')


def profiles():
    return (('Rectangle', geo.rectangle(XY, V(), V(3,4,0))),
            ('Circle', geo.circle(XY, V(), 2)),
            ('Polygon', geo.polygon(XY, V(), V(2,1,0), 6)))


def fitted():
    surface = Part.BSplineSurface()
    surface.interpolate([[V(x,y,.1*x*x+.065*y*y) for y in (0,5,10,15)] for x in (0,5,10,15)])
    skin = surface.toShape()
    shape = skin.extrude(V(0,0,-5))
    face = max(shape.Faces, key=lambda f: f.common(skin).Area)
    u0,u1,v0,v1 = face.ParameterRange
    return shape, face, face.valueAt((u0+u1)/2,(v0+v1)/2)


class SurfaceFrameTests(unittest.TestCase):
    def test_cylinder_coordinates_unroll_exactly_and_cross_the_seam(self):
        face = Part.makeCylinder(10,30).Faces[0]
        frame = SurfaceFrame(face, face.valueAt(.05,15))
        for point in (V(3,4,0), V(-3,-4,0)):
            self.assertLess((frame.local(frame.point(point))-point).Length, 1e-8)
        wire = frame.wire(geo.rectangle(XY,V(),V(3,4,0)))
        self.assertTrue(wire.isValid() and wire.isClosed())
        self.assertAlmostEqual(wire.Length, 14, places=7)
        self.assertEqual(sorted(round(e.Length,6) for e in wire.Edges), [3,3,4,4])

    def test_circle_is_an_exact_surface_curve_with_the_unrolled_radius(self):
        face = Part.makeCylinder(10,30).Faces[0]
        frame = SurfaceFrame(face,face.valueAt(1,15))
        wire = frame.wire(geo.circle(XY,V(),2))
        self.assertAlmostEqual(wire.Length,math.tau*2,places=6)
        for p in wire.Edges[0].discretize(40):
            self.assertAlmostEqual(math.hypot(p.x,p.y),10,places=7)
            self.assertAlmostEqual(frame.local(p).Length,2,places=6)

    def test_freeform_frame_has_mm_scale_and_orthogonal_axes_at_anchor(self):
        _,face,anchor = fitted()
        frame = SurfaceFrame(face,anchor)
        dx,dy = frame.point(V(.0001,0,0))-anchor, frame.point(V(0,.0001,0))-anchor
        self.assertAlmostEqual(dx.Length,.0001,places=8)
        self.assertAlmostEqual(dy.Length,.0001,places=8)
        self.assertLess(abs(geo.unit(dx).dot(geo.unit(dy))), 1e-4)
        for _,profile in profiles():
            wire = frame.wire(profile)
            self.assertTrue(covered(face,wire))
            for edge in wire.Edges:
                for point in edge.discretize(12):
                    self.assertLess(face.distToShape(Part.Vertex(point))[0], 1e-6)

    def test_placed_and_reversed_surfaces_and_custom_tangent_x(self):
        face = Part.makeCylinder(10,30).Faces[0]
        face.Placement = App.Placement(V(7,8,9),App.Rotation(V(1,2,3),47))
        face.reverse()
        anchor = face.valueAt(1,15)
        frame = SurfaceFrame(face,anchor,face.derivative1At(1,15)[1])
        self.assertGreater(frame.plane.u.dot(geo.unit(face.derivative1At(1,15)[1])),.999999)
        self.assertLess((frame.local(frame.point(V(2,3,0)))-V(2,3,0)).Length,1e-8)
        self.assertTrue(covered(face,frame.wire(geo.circle(XY,V(),2))))

    def test_full_wraps_poles_and_off_surface_starts_are_refused(self):
        face = Part.makeCylinder(10,30).Faces[0]
        frame = SurfaceFrame(face,face.valueAt(1,15))
        with self.assertRaisesRegex(ValueError,'wraps'):
            frame.wire(geo.circle(XY,V(),40))
        with self.assertRaisesRegex(ValueError,'wraps'):
            frame.wire(geo.rectangle(XY,V(),V(65,4,0)))
        with self.assertRaises(ValueError):
            SurfaceFrame(face,V())
        sphere = Part.makeSphere(10).Faces[0]
        with self.assertRaisesRegex(ValueError,'pole'):
            SurfaceFrame(sphere,V(0,0,10))
        frame = SurfaceFrame(sphere,sphere.valueAt(1,1.4))
        with self.assertRaisesRegex(ValueError,'leaves'):
            frame.wire(geo.circle(XY,V(),3))

    def test_boundary_proof_rejects_real_changes_and_reversed_orientation(self):
        source = Part.makeBox(10,10,10)
        self.assertTrue(same_boundary(source,source.copy()))
        self.assertFalse(same_boundary(source,source.cut(Part.makeBox(1,1,1))))
        self.assertFalse(same_boundary(source,source.fuse(Part.makeBox(2,2,2,V(9,0,0)))))
        reversed_shape = source.copy()
        reversed_shape.reverse()
        self.assertFalse(same_boundary(source,reversed_shape))


class SurfaceDrawingDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('SurfaceDrawingTest')
        self.doc.UndoMode = 1
        self.obj = self.doc.addObject('Part::Feature','Cylinder')
        self.obj.Shape = Part.makeCylinder(10,30)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def draw(self, profile, angle=1, z=15):
        face = next(f for f in self.obj.Shape.Faces
                    if isinstance(f.Surface,Part.Cylinder) and abs(f.Surface.Radius-10)<1e-8)
        frame = SurfaceFrame(face,face.valueAt(angle,z))
        return ops.draw_surface_curve(self.doc,frame.wire(profile),self.obj,face,'Surface test',closed=True)

    def assert_preserved(self, source):
        result = self.obj.Shape
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Solids),1)
        self.assertTrue(preserves_area(source,result))
        self.assertTrue(preserves_volume(source,result))

    def test_closed_tools_make_regions_with_one_undo_and_no_overlays(self):
        for name,profile in profiles():
            with self.subTest(tool=name):
                source,count = self.obj.Shape.copy(),self.doc.UndoCount
                _,divided = self.draw(profile)
                self.assertTrue(divided)
                self.assertGreater(len(self.obj.Shape.Faces),len(source.Faces))
                self.assert_preserved(source)
                self.assertEqual(len(self.doc.Objects),1)
                self.assertEqual(self.doc.UndoCount,count+1)
                self.doc.undo()
                self.assertEqual(len(self.obj.Shape.Faces),len(source.Faces))
                self.doc.redo()
                self.assertGreater(len(self.obj.Shape.Faces),len(source.Faces))
                self.doc.undo()

    def test_seam_crossing_circle_and_rectangle_keep_the_solid(self):
        source = self.obj.Shape.copy()
        for profile in (geo.circle(XY,V(),2),geo.rectangle(XY,V(),V(-3,4,0))):
            self.draw(profile,angle=.05)
            self.assert_preserved(source)
            self.doc.undo()

    def test_closed_profiles_cross_existing_divisions(self):
        face = self.obj.Shape.Faces[0]
        ops.draw_surface_line(self.doc,face.valueAt(1,0),face.valueAt(1,30),self.obj,face)
        source = self.obj.Shape.copy()
        self.draw(geo.circle(XY,V(),3),angle=.9)
        self.assert_preserved(source)
        self.assertGreater(len(self.obj.Shape.Faces),len(source.Faces))

    def test_freeform_solid_outlines_preserve_geometry(self):
        for name,profile in profiles():
            with self.subTest(tool=name):
                source,face,anchor = fitted()
                self.obj.Shape = source
                face = next(f for f in self.obj.Shape.Faces if f.isSame(face))
                frame = SurfaceFrame(face,anchor)
                ops.draw_surface_curve(self.doc,frame.wire(profile),self.obj,face,'Surface test',closed=True)
                self.assertEqual(len(self.obj.Shape.Faces),7)
                self.assert_preserved(source)

    def test_open_spherical_surface_gets_selectable_regions(self):
        self.obj.Shape = Part.makeSphere(10).Faces[0]
        face = self.obj.Shape.Faces[0]
        frame = SurfaceFrame(face,face.valueAt(1,0))
        source = self.obj.Shape.copy()
        ops.draw_surface_curve(self.doc,frame.wire(geo.circle(XY,V(),2)),self.obj,face,'Surface circle',closed=True)
        self.assertEqual(len(self.obj.Shape.Faces),2)
        self.assertTrue(self.obj.Shape.isValid())
        self.assertTrue(preserves_area(source,self.obj.Shape))
        self.assertFalse(self.obj.Shape.Solids)

    def test_crossing_an_opening_or_leaving_a_trim_cannot_write(self):
        source,count = self.obj.Shape,self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'opening'):
            self.draw(geo.circle(XY,V(),4),z=1)
        self.assertEqual(self.doc.UndoCount,count)
        self.assertTrue(self.obj.Shape.isSame(source))
        self.obj.Shape = source.cut(Part.makeCylinder(3,30,V(0,0,15),V(1,0,0)))
        source,count = self.obj.Shape,self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'opening'):
            self.draw(geo.circle(XY,V(),4),angle=0,z=10)
        self.assertTrue(self.obj.Shape.isSame(source))
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),1)

    def test_locks_and_stale_faces_refuse_the_edit(self):
        face = self.obj.Shape.Faces[0]
        frame = SurfaceFrame(face,face.valueAt(1,15))
        wire = frame.wire(geo.circle(XY,V(),2))
        locking.set_locked([(self.obj,['Face1'])],True)
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.draw_surface_curve(self.doc,wire,self.obj,face,'Surface circle',closed=True)
        self.assertEqual(self.doc.UndoCount,count)
        locking.set_locked([(self.obj,['Face1'])],False)
        self.obj.Shape = Part.makeCylinder(11,30)
        with self.assertRaisesRegex(ValueError,'changed'):
            ops.draw_surface_curve(self.doc,wire,self.obj,face,'Surface circle',closed=True)

    def test_retracing_a_closed_region_is_a_noop(self):
        profile = geo.circle(XY,V(),2)
        self.draw(profile)
        faces,count = len(self.obj.Shape.Faces),self.doc.UndoCount
        self.draw(profile)
        self.assertEqual(len(self.obj.Shape.Faces),faces)
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),1)

    def test_both_arc_styles_close_with_surface_line_and_consume_the_arc(self):
        for two_point in (False,True):
            with self.subTest(two_point=two_point):
                face = self.obj.Shape.Faces[0]
                frame = SurfaceFrame(face,face.valueAt(1,15))
                curve = (arcs.two_point(V(),V(0,4,0),V(0,0,1),1) if two_point
                         else arcs.centered(V(),V(2,0,0),V(0,0,1),180))
                edge = frame.edge(curve.edge())
                source = self.obj.Shape.copy()
                _,divided = ops.draw_surface_curve(self.doc,edge,self.obj,face,'Surface arc')
                self.assertFalse(divided)
                self.assertEqual(len(self.doc.Objects),2)
                _,divided = ops.draw_surface_line(self.doc,frame.point(curve.point(1)),frame.point(curve.point(0)),self.obj,face)
                self.assertTrue(divided)
                self.assertEqual(len(self.doc.Objects),1)
                self.assert_preserved(source)
                self.doc.undo()
                self.doc.undo()

    def test_surface_outline_survives_native_save_and_reopen(self):
        self.draw(geo.circle(XY,V(),2))
        count = len(self.obj.Shape.Faces)
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'outline.FCStd')
            self.doc.saveAs(path)
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            self.obj = self.doc.getObject('Cylinder')
            self.assertEqual(len(self.obj.Shape.Faces),count)
            self.assertTrue(self.obj.Shape.isValid())

    def test_mcp_surface_options_use_the_same_operations(self):
        from simplecad.mcp.api import ModelAPI
        api = ModelAPI()
        anchor = self.obj.Shape.Faces[0].valueAt(1,15)
        common = dict(support=self.obj.Name,surface_face='Face1')
        for operation,args in (
                ('create_rectangle',dict(origin=list(anchor),width=3,height=4)),
                ('create_circle',dict(origin=list(anchor),radius=2)),
                ('create_polygon',dict(origin=list(anchor),radius=2,sides=5,angle=20))):
            with self.subTest(operation=operation):
                result = api.execute(operation,self.doc,dict(common,**args))
                self.assertTrue(result['divided_face'])
                self.assertEqual(result['object']['name'],self.obj.Name)
                self.doc.undo()
        face = self.obj.Shape.Faces[0]
        frame = SurfaceFrame(face,anchor)
        for operation,args in (
                ('create_arc',dict(origin=list(anchor),start=list(frame.point(V(2,0,0))),sweep=90)),
                ('create_2_point_arc',dict(start=list(anchor),end=list(frame.point(V(0,4,0))),bulge=1))):
            result = api.execute(operation,self.doc,dict(common,**args))
            self.assertFalse(result['divided_face'])
            self.assertTrue(covered(face,self.doc.getObject(result['object']['name']).Shape))
            self.doc.undo()
        count = self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'support'):
            api.execute('create_circle',self.doc,dict(origin=list(anchor),radius=2,surface_face='Face1'))
        self.assertEqual(self.doc.UndoCount,count)


if __name__ == '__main__':
    unittest.main()
