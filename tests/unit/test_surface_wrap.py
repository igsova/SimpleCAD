"""Wrapped drawings cross native creases/patches without editing the skin."""
import math
import unittest
from unittest import mock

import FreeCAD as App
import Mesh
import numpy as np
import Part

from simplecad.modeling import arcs
from simplecad.core import geometry as geo
from simplecad.document import locking, operations as ops
from simplecad.surfaces import wrap as surface_wrap
from simplecad.surfaces.line import changed_faces, changed_measure, comparison_cache, covered, preserves_area, preserves_volume, same_boundary
from simplecad.surfaces.skin import Skin, has_faces
from simplecad.surfaces.wrap import WrapFrame, WrapMesh, neighbors
from surface_fixtures import fitted_surface_loop

V=App.Vector
XY=geo.Plane.named('XY')


def patchwork():
    faces=[]
    for angle in range(0,360,90):
        face=Part.makeCylinder(10,30,V(),V(0,0,1),90).Faces[0].toNurbs()
        face.rotate(V(),V(0,0,1),angle)
        faces.append(face)
    shape=Part.makeShell(faces)
    shape.sewShape()
    return shape


class WrappedDrawingTests(unittest.TestCase):
    def setUp(self):
        self.doc=App.newDocument('WrappedDrawingTest')
        self.doc.UndoMode=1
        self.obj=self.doc.addObject('Part::Feature','Body')
        self.obj.Shape=Part.makeBox(20,20,20,V(-10,-10,-10))
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def frame(self, anchor=V(10,0,0)):
        face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(anchor))[0])
        return WrapFrame(Skin(self.obj.Shape,face),face,anchor)

    def preserved(self, source):
        result=self.obj.Shape
        self.assertTrue(result.isValid())
        self.assertTrue(preserves_area(source,result))
        self.assertEqual(len(result.Solids),len(source.Solids))
        if source.Solids:
            self.assertTrue(result.isClosed())
            self.assertTrue(preserves_volume(source,result))

    def test_only_a_document_with_a_face_offers_surface_drawing(self):
        self.assertTrue(has_faces(self.doc))
        other=App.newDocument('NoFacesTest')
        try:
            self.assertFalse(has_faces(other))
            line=other.addObject('Part::Feature','Line')
            line.Shape=Part.makePolygon([V(),V(10,0,0),V(10,10,0)])
            mesh=other.addObject('Mesh::Feature','ImportedSTL')
            mesh.Mesh=Mesh.Mesh(Part.makeBox(5,5,5).tessellate(.1))
            other.recompute()
            self.assertFalse(has_faces(other))
            plate=other.addObject('Part::Feature','Plate')
            plate.Shape=Part.makePlane(5,5)
            self.assertTrue(has_faces(other))
        finally:
            App.closeDocument(other.Name)

    def test_mouse_coordinates_reach_adjacent_and_opposite_faces(self):
        frame=self.frame()
        for q in (V(15,3),V(25,3),V(35,0)):
            point=frame.point(q)
            face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(point))[0])
            self.assertLess((frame.local(point,face)-q).Length,1e-4)
        self.assertAlmostEqual(frame.point(V(35,0)).x,-10,places=7)

    def test_preview_samples_follow_the_same_developed_crease(self):
        frame=self.frame()
        points=frame.points([V(),V(35,3)])
        self.assertLess((points[0]-V(10,0,0)).Length,1e-7)
        self.assertAlmostEqual(points[-1].x,-10,places=7)
        for point in points:
            self.assertLess(self.obj.Shape.distToShape(Part.Vertex(point))[0],1e-7)
        # The unfolded straight path has this length across all three walls.
        length=sum((b-a).Length for a,b in zip(points,points[1:]))
        self.assertAlmostEqual(length,math.hypot(35,3),delta=.15)

    def test_orbiting_past_half_a_cylinder_keeps_the_chosen_wrap_direction(self):
        self.obj.Shape=Part.makeCylinder(10,20)
        face=self.obj.Shape.Faces[0]
        frame=WrapFrame(Skin(self.obj.Shape,face),face,face.valueAt(0,10))
        distances=[]
        for angle in (1,2,3,4,5):
            q=frame.local(face.valueAt(angle,10),face)
            distances.append(q.Length)
        self.assertEqual([round(d) for d in distances],[10,20,30,40,50])
        curve=frame.edge(geo.line(V(),q))
        self.assertAlmostEqual(curve.Length,50,places=6)

    def test_closed_profiles_wrap_over_multiple_box_faces_with_one_undo(self):
        for profile in (geo.circle(XY,V(),12),geo.rectangle(XY,V(),V(15,5)),
                        geo.polygon(XY,V(),V(12,0),6)):
            source,count=self.obj.Shape.copy(),self.doc.UndoCount
            frame=self.frame()
            wire=frame.wire(profile)
            self.assertTrue(wire.isClosed() and wire.isValid())
            self.assertTrue(covered(source,wire))
            self.assertGreater(sum(f.common(wire).Length>geo.EPS for f in source.Faces),1)
            _,divided=ops.draw_surface_curve(self.doc,wire,self.obj,frame.face,'Wrapped outline',closed=True)
            self.assertTrue(divided)
            self.preserved(source)
            self.assertEqual(len(self.doc.Objects),1)
            self.assertEqual(self.doc.UndoCount,count+1)
            self.doc.undo()
            self.assertEqual(len(self.obj.Shape.Faces),6)
            self.doc.redo()
            self.preserved(source)
            self.doc.undo()

    def test_seam_crossings_of_different_outline_edges_are_never_paired(self):
        # CPython can give a later crossing point the id() of a freed one.
        # Pairing seams by id() then compared crossings of different edges
        # and failed some wraps at random; a constant id() made it certain.
        frame=self.frame()
        with mock.patch.object(surface_wrap,'id',lambda obj:0,create=True):
            for profile in (geo.rectangle(XY,V(),V(15,5)),geo.polygon(XY,V(),V(12,0),6)):
                wire=frame.wire(profile)
                self.assertTrue(wire.isClosed() and wire.isValid())
                self.assertGreater(sum(f.common(wire).Length>geo.EPS for f in self.obj.Shape.Faces),1)

    def test_both_arc_styles_cross_a_crease_as_native_surface_curves(self):
        frame=self.frame(V(10,8,0))
        for profile in (arcs.centered(V(),V(4,0),V(0,0,1),180),
                        arcs.two_point(V(),V(4,4),V(0,0,1),1)):
            curve=frame.edge(profile.edge())
            self.assertGreater(len(curve.Edges),1)
            self.assertTrue(covered(self.obj.Shape,curve))
            source=self.obj.Shape.copy()
            _,divided=ops.draw_surface_curve(self.doc,curve,self.obj,frame.face,'Wrapped arc')
            self.assertFalse(divided)
            self.assertEqual(len(self.doc.Objects),2)
            self.preserved(source)
            self.doc.undo()

    def test_loose_lines_can_close_a_loop_spanning_three_faces(self):
        source=self.obj.Shape.copy()
        frame=self.frame()
        points=[V(0,-3),V(35,-3),V(35,3),V(0,3),V(0,-3)]
        curves=[frame.edge(geo.line(a,b)) for a,b in zip(points,points[1:])]
        for curve in curves:
            face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(curve.Vertexes[0])[0])
            ops.draw_surface_curve(self.doc,curve,self.obj,face,'Wrapped line')
        self.assertEqual(len(self.doc.Objects),1)
        self.assertGreater(len(self.obj.Shape.Faces),6)
        self.preserved(source)

    def test_fitted_patch_line_loop_closes_without_false_added_skin(self):
        source,curves=fitted_surface_loop()
        self.obj.Shape=source
        count=self.doc.UndoCount
        for i,curve in enumerate(curves):
            face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(curve.Vertexes[0])[0])
            _,divided=ops.draw_surface_curve(self.doc,curve,self.obj,face,'Surface line')
            self.assertEqual(divided,i==2)
        result=self.obj.Shape
        self.assertEqual(len(result.Faces),4)
        self.assertEqual(len(self.doc.Objects),1)
        self.assertEqual(self.doc.UndoCount,count+3)
        # This case must exercise the geometric check, not its scalar shortcut.
        self.assertGreater(abs(source.Area-result.Area),max(1e-6,source.Area*1e-8))
        self.preserved(source)
        self.assertTrue(same_boundary(source,result))
        from simplecad.surfaces.line import same_surface
        for original in source.Faces:
            self.assertEqual(sum(same_surface(original,part) for part in result.Faces),2)
        # A lost region or a translated/reversed skin must still be refused.
        incomplete=Part.makeCompound(result.Faces[:-1])
        self.assertFalse(preserves_area(source,incomplete))
        self.assertFalse(same_boundary(source,incomplete))
        translated=result.copy();translated.translate(V(1,2,3))
        self.assertFalse(same_boundary(source,translated))
        reversed_shape=result.copy();reversed_shape.reverse()
        self.assertFalse(same_boundary(source,reversed_shape))
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces),2)
        self.assertEqual(len(self.doc.Objects),3)
        self.doc.redo()
        self.assertEqual(len(self.obj.Shape.Faces),4)
        self.assertEqual(len(self.doc.Objects),1)
        self.preserved(source)

    def test_independent_bspline_patches_share_a_closed_wrapped_region(self):
        self.obj.Shape=patchwork()
        source=self.obj.Shape.copy()
        frame=self.frame(V(10*math.cos(1.4),10*math.sin(1.4),15))
        wire=frame.wire(geo.circle(XY,V(),3))
        self.assertGreater(len(wire.Edges),1)
        self.assertTrue(wire.isClosed() and covered(source,wire))
        self.assertAlmostEqual(wire.Length,math.tau*3,delta=.01)
        ops.draw_surface_curve(self.doc,wire,self.obj,frame.face,'Wrapped circle',closed=True)
        self.preserved(source)
        self.assertGreater(len(self.obj.Shape.Faces),4)

    def test_disconnected_shells_do_not_join_the_wrap(self):
        first=self.obj.Shape
        second=Part.makeBox(20,20,20,V(40,-10,-10))
        shape=Part.makeCompound([first,second])
        skin=Skin(shape,shape.Faces[0])
        self.assertEqual(len(skin.faces),6)
        self.assertFalse(skin.contains(shape.Faces[-1]))

    def test_open_boundaries_refuse_wrapping_and_leave_document_unchanged(self):
        self.obj.Shape=Part.makePlane(10,10)
        frame=self.frame(V(5,5,0))
        source,count=self.obj.Shape,self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'opening|boundary'):
            frame.wire(geo.circle(XY,V(),8))
        self.assertEqual(self.doc.UndoCount,count)
        self.assertTrue(source.isSame(self.obj.Shape))

    def test_a_hole_is_not_bridged_by_the_development(self):
        plane=Part.makePlane(20,20)
        hole=Part.Face(Part.Wire([Part.makeCircle(2,V(10,10,0))]))
        self.obj.Shape=plane.cut(hole)
        frame=self.frame(V(5,10,0))
        with self.assertRaisesRegex(ValueError,'opening|boundary'):
            frame.edge(geo.line(V(),V(10,0,0)))

    def test_locks_on_the_next_face_refuse_before_writing(self):
        frame=self.frame()
        wire=frame.wire(geo.rectangle(XY,V(),V(15,5)))
        other=next(i for i,f in enumerate(self.obj.Shape.Faces,1)
                   if not f.isSame(frame.face) and f.common(wire).Length>geo.EPS)
        locking.set_locked([(self.obj,['Face%d'%other])],True)
        source,count=self.obj.Shape,self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'locked'):
            ops.draw_surface_curve(self.doc,wire,self.obj,frame.face,'Wrapped rectangle',closed=True)
        self.assertTrue(source.isSame(self.obj.Shape))
        self.assertEqual(self.doc.UndoCount,count)

    def test_rotated_placed_shape_keeps_its_geometry(self):
        self.obj.Placement=App.Placement(V(23,31,17),App.Rotation(V(1,2,3),47))
        anchor=self.obj.Placement.multVec(V(10,0,0))
        source=self.obj.Shape.copy()
        frame=self.frame(anchor)
        wire=frame.wire(geo.circle(XY,V(),12))
        ops.draw_surface_curve(self.doc,wire,self.obj,frame.face,'Wrapped circle',closed=True)
        self.preserved(source)

    def test_triangle_neighbours_match_a_side_by_side_listing(self):
        points,facets=Part.makeSphere(5).tessellate(.5)
        triangles=np.asarray(facets,dtype=np.int64)
        # A side used three times (a fin) and an open side have no neighbour.
        triangles=np.vstack([triangles,triangles[:1,[1,0,2]]+0,[[0,1,len(points)]]])
        expected=np.full((len(triangles),3),-1,dtype=np.int64)
        uses={}
        for i,tri in enumerate(triangles):
            for side in range(3):
                key=tuple(sorted((int(tri[(side+1)%3]),int(tri[(side+2)%3]))))
                uses.setdefault(key,[]).append((i,side))
        for found in uses.values():
            if len(found)==2:
                (i,a),(j,b)=found
                expected[i,a],expected[j,b]=j,i
        self.assertTrue((neighbors(triangles)==expected).all())
        self.assertEqual(neighbors(np.empty((0,3),dtype=np.int64)).shape,(0,3))

    def test_the_drawing_mesh_is_reused_until_the_surface_changes(self):
        first=self.frame()
        again=self.frame()
        self.assertIs(again.mesh,first.mesh)
        wire=first.wire(geo.rectangle(XY,V(),V(6,4)))
        ops.draw_surface_curve(self.doc,wire,self.obj,first.face,'Wrapped rectangle',closed=True)
        changed=self.frame()
        self.assertIsNot(changed.mesh,first.mesh)
        self.assertEqual(len(changed.mesh.owners),len(WrapMesh(changed.skin,changed._around()).owners))

    def test_plane_outlines_build_the_guide_only_when_they_leave_the_plane(self):
        with mock.patch.object(surface_wrap,'wrap_mesh',wraps=surface_wrap.wrap_mesh) as built:
            frame=self.frame()
            frame.points(geo.rectangle_points(XY,V(),V(6,4)))
            self.assertTrue(covered(frame.face,frame.wire(geo.rectangle(XY,V(),V(6,4)))))
            frame.local(frame.point(V(3,2)))
            self.assertEqual(built.call_count,0)
            self.assertAlmostEqual(frame.point(V(15,3)).y,10,places=7)
            self.assertEqual(built.call_count,1)
            self.obj.Shape=patchwork()
            self.assertFalse(self.frame(V(10*math.cos(1.4),10*math.sin(1.4),15)).analytic)
            self.assertEqual(built.call_count,2)  # Fitted faces trace from the first click.

    def test_a_deferred_fitted_frame_builds_its_guide_on_first_use_with_the_same_result(self):
        self.obj.Shape=patchwork()
        anchor=V(10*math.cos(1.4),10*math.sin(1.4),15)
        face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(anchor))[0])
        eager=self.frame(anchor)
        surface_wrap._last_mesh=None
        with mock.patch.object(surface_wrap,'wrap_mesh',wraps=surface_wrap.wrap_mesh) as built:
            frame=WrapFrame(Skin(self.obj.Shape,face),face,anchor,build=False)
            self.assertEqual(built.call_count,0)
            for q in (V(9,5),V(-12,3),V(2,-10)):
                self.assertEqual(frame.point(q),eager.point(q))
            self.assertEqual(built.call_count,1)
        self.assertEqual((frame.seed,tuple(frame.start)),(eager.seed,tuple(eager.start)))

    def test_the_guide_starts_around_the_start_face_and_answers_as_the_whole_one(self):
        self.obj.Shape=patchwork()
        anchor=V(10*math.cos(1.4),10*math.sin(1.4),15)
        face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(anchor))[0])
        skin=Skin(self.obj.Shape,face)
        whole=WrapFrame(skin,face,anchor,build=False)
        whole._use(WrapMesh(skin))
        self.assertIsNone(whole.mesh.subset)
        surface_wrap._last_mesh=None
        frame=WrapFrame(skin,face,anchor)
        # The opposite quarter of the tube shares no edge with the start.
        self.assertEqual(len(frame.mesh.subset),3)
        self.assertIn(frame.owner,frame.mesh.subset)
        self.assertTrue(set(frame.mesh.owners.tolist())<=frame.mesh.subset)
        for q in (V(9,5),V(-12,3),V(2,-10),V(20,0)):
            self.assertEqual(frame.point(q),whole.point(q))
            self.assertEqual(frame.point(q,exact=False),whole.point(q,exact=False))
            self.assertEqual(frame.face_at(q).hashCode(),whole.face_at(q).hashCode())
        end=frame.point(V(9,5))
        target=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(end))[0])
        self.assertEqual(frame.local(end,target),whole.local(end,target))
        self.assertIsNotNone(frame.mesh.subset)
        # Reaching the opposite quarter repeats the answer on the whole guide.
        self.assertEqual(frame.point(V(-20,0)),whole.point(V(-20,0)))
        self.assertIsNone(frame.mesh.subset)
        self.assertEqual(frame.edge(geo.line(V(),V(-20,0))).Length,whole.edge(geo.line(V(),V(-20,0))).Length)

    def test_refusals_beyond_the_start_faces_come_from_the_whole_guide(self):
        self.obj.Shape=patchwork()
        anchor=V(10*math.cos(1.4),10*math.sin(1.4),15)
        face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(Part.Vertex(anchor))[0])
        surface_wrap._last_mesh=None
        frame=WrapFrame(Skin(self.obj.Shape,face),face,anchor)
        with self.assertRaisesRegex(ValueError,'opening'):
            frame.point(V(0,20))  # Past the end of the open tube.
        self.assertIsNone(frame.mesh.subset)
        opposite=self.obj.Shape.Faces[next(i for i in range(4) if i not in WrapFrame(
            Skin(self.obj.Shape,face),face,anchor,build=False)._around())]
        surface_wrap._last_mesh=None
        frame=WrapFrame(Skin(self.obj.Shape,face),face,anchor)
        point=opposite.valueAt(*[(a+b)/2 for a,b in zip(opposite.ParameterRange[::2],opposite.ParameterRange[1::2])])
        q=frame.local(point,opposite)
        self.assertIsNone(frame.mesh.subset)
        self.assertLess((frame.point(q)-point).Length,1e-6)

    def test_a_partial_guide_is_reused_while_it_holds_the_faces_and_grows_otherwise(self):
        self.obj.Shape=patchwork()
        skin=Skin(self.obj.Shape,self.obj.Shape.Faces[0])
        surface_wrap._last_mesh=None
        first=surface_wrap.wrap_mesh(skin,{0,1})
        self.assertEqual(first.subset,{0,1})
        self.assertEqual(set(first.owners.tolist()),{0,1})
        self.assertIs(surface_wrap.wrap_mesh(skin,{1}),first)
        grown=surface_wrap.wrap_mesh(skin,{2})
        self.assertEqual(grown.subset,{0,1,2})
        whole=surface_wrap.wrap_mesh(skin)
        self.assertIsNone(whole.subset)
        self.assertIs(surface_wrap.wrap_mesh(skin,{3}),whole)
        self.assertIsNone(surface_wrap.wrap_mesh(skin,{0,1,2,3}).subset)
        self.assertEqual(len(whole.triangles),len(WrapMesh(skin).triangles))

    def test_volume_check_repeats_no_result_validity_the_caller_just_found(self):
        from simplecad.surfaces import line as surface_line
        checked=[]

        class Shape:
            Solids=[1]

            def __init__(self, name):
                self.name=name

            def isClosed(self):
                return True

            def isValid(self):
                checked.append(self.name)
                return True

        with mock.patch.object(surface_line,'changed_faces',return_value=([],[])), \
                mock.patch.object(surface_line,'changed_measure',return_value=1.0), \
                mock.patch.object(geo,'volume',return_value=1.0), \
                mock.patch.object(surface_line,'same_boundary',return_value=True):
            for valid,expected in ((False,['source','result']),(True,['source'])):
                checked.clear()
                self.assertTrue(preserves_volume(Shape('source'),Shape('result'),valid=valid))
                self.assertEqual(checked,expected)

    def test_fitted_previews_draw_guide_points_and_keep_picked_points_exact(self):
        self.obj.Shape=patchwork()
        shape=self.obj.Shape
        frame=self.frame(V(10*math.cos(1.4),10*math.sin(1.4),15))
        end=frame.point(V(9,5))
        face=min(shape.Faces,key=lambda f:f.distToShape(Part.Vertex(end))[0])
        q=frame.local(end,face)
        shown=frame.points([V(),q])
        self.assertGreater(len(shown),10)
        self.assertLess((shown[0]-frame.anchor).Length,1e-9)
        self.assertLess((shown[-1]-end).Length,1e-9)
        guide=0
        for i,point in enumerate(shown[1:-1],1):
            self.assertLess(shape.distToShape(Part.Vertex(point))[0],5*surface_wrap.DEFLECTION)
            guide+=shape.distToShape(Part.Vertex(point))[0]>1e-6
        self.assertGreater(guide,0)  # Moving previews do not invert the surface per sample.
        # Exact points and saved curves stay on the native faces.
        for t in (.25,.5,.75):
            self.assertLess(shape.distToShape(Part.Vertex(frame.point(q*t)))[0],1e-7)
        self.assertTrue(covered(shape,frame.edge(geo.line(V(),q))))

    def test_cross_face_corridors_match_a_python_shortest_path_walk(self):
        import heapq
        for shape in (self.obj.Shape,Part.makeSphere(5),patchwork()):
            mesh=WrapMesh(Skin(shape,shape.Faces[0]))
            for seed in (0,len(mesh.triangles)//2):
                costs,expected,queue={seed:0.},np.full(len(mesh.triangles),-1),[(0.,seed)]
                while queue:
                    cost,i=heapq.heappop(queue)
                    if cost!=costs[i]:
                        continue
                    for j in mesh.neighbors[i]:
                        j=int(j)
                        if j<0:
                            continue
                        value=cost+float(np.linalg.norm(mesh.centers[j]-mesh.centers[i]))
                        if value<costs.get(j,math.inf):
                            costs[j],expected[j]=value,i
                            heapq.heappush(queue,(value,j))
                found=mesh.paths(seed)
                self.assertEqual(found[seed],-1)
                # Equal-length corridors are ties; both walks keep the same one.
                np.testing.assert_array_equal(found,expected)

    def test_changed_faces_measure_the_whole_change_of_area_and_volume(self):
        source=self.obj.Shape
        frame=self.frame()
        ops.draw_surface_curve(self.doc,frame.wire(geo.circle(XY,V(),4)),self.obj,frame.face,
                               'Wrapped circle',closed=True)
        result=self.obj.Shape
        cut=result.cut(Part.makeBox(2,2,2,V(9,0,0)))
        for after in (result,cut,Part.makeCompound(result.Faces[:-1])):
            removed,added=changed_faces(source,after)
            self.assertLess(len(removed),len(source.Faces))
            self.assertAlmostEqual(changed_measure(removed,added,'Area'),abs(after.Area-source.Area),places=7)
            if after.Solids:
                self.assertAlmostEqual(changed_measure(removed,added,'Volume'),abs(after.Volume-source.Volume),places=7)
        # A missing flat face holds no volume about its own plane. The open
        # result must still be refused, as the whole integrals refuse it.
        box=Part.makeBox(10,20,30)
        try:
            accepted=preserves_volume(box,Part.makeShell(box.Faces[:-1]))
        except ValueError:
            accepted=False
        self.assertFalse(accepted)
        fitted,curves=fitted_surface_loop()
        self.obj.Shape=fitted
        for curve in curves:
            face=min(self.obj.Shape.Faces,key=lambda f:f.distToShape(curve.Vertexes[0])[0])
            ops.draw_surface_curve(self.doc,curve,self.obj,face,'Surface line')
        removed,added=changed_faces(fitted,self.obj.Shape)
        # The fitted patches' trims drift their integrals well past the
        # scalar tolerance; the changed faces carry all of that drift.
        self.assertAlmostEqual(changed_measure(removed,added,'Area'),abs(self.obj.Shape.Area-fitted.Area),places=7)
        self.assertGreater(changed_measure(removed,added,'Area'),max(1e-6,fitted.Area*1e-8))

    def test_area_check_integrates_the_whole_source_only_when_the_bound_cannot_decide(self):
        from simplecad.surfaces import line as surface_line
        source=self.obj.Shape
        removed=[max(source.Faces,key=lambda f:f.Area)]
        reads=[]

        class Source:
            Faces=source.Faces

            @property
            def Area(self):
                reads.append(1)
                return source.Area

        bound=removed[0].Area*1e-8
        tolerance=source.Area*1e-8
        with mock.patch.object(surface_line,'changed_faces',return_value=(removed,[])), \
                mock.patch.object(surface_line,'skin_differences') as differences:
            for change,accepted,integrated in ((bound*.9,True,0),(bound*1.1,True,1),(tolerance*1.1,False,1)):
                reads.clear()
                with mock.patch.object(surface_line,'changed_measure',return_value=max(change,1.01e-6)):
                    self.assertEqual(preserves_area(Source(),source),accepted,change)
                self.assertEqual(len(reads),integrated,change)
            differences.assert_not_called()  # Nothing added: the sum of removed area decides.

    def test_guide_inverses_match_numpys_pseudo_inverse(self):
        self.obj.Shape=patchwork()
        frame=self.frame(V(10*math.cos(1.4),10*math.sin(1.4),15))
        for mesh in (frame.mesh,WrapMesh(frame.skin)):
            expected=np.linalg.pinv(np.stack((mesh.a,mesh.b),axis=2))
            np.testing.assert_allclose(mesh.dual,expected,rtol=0,atol=1e-9*np.abs(expected).max())
            self.assertEqual(len(mesh.owners),len(mesh.triangles))
            self.assertEqual(set(mesh.owners.tolist()),mesh.subset or set(range(len(mesh.skin.faces))))

    def test_reused_comparisons_still_reject_cuts_and_reversed_skin(self):
        source=self.obj.Shape
        frame=self.frame()
        wire=frame.wire(geo.circle(XY,V(),12))
        ops.draw_surface_curve(self.doc,wire,self.obj,frame.face,'Wrapped circle',closed=True)
        result=self.obj.Shape
        with comparison_cache():
            self.assertTrue(preserves_area(source,result))
            self.assertTrue(preserves_volume(source,result))
            cut=result.cut(Part.makeBox(2,2,2,V(9,0,0)))
            self.assertFalse(preserves_volume(source,cut))
            reversed_shape=result.copy(); reversed_shape.reverse()
            self.assertFalse(same_boundary(source,reversed_shape))


if __name__=='__main__':
    unittest.main()
