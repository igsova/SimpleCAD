"""Native surface Line: exact curves, chained splits, trims and Undo."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import FreeCAD as App
import Part

from simplecad.core import geometry as geo
from simplecad.document import locking, operations as ops
from simplecad.surfaces.line import SurfacePath, covered
from simplecad.gui.snapping import Snapper

V = App.Vector


def cylinder():
    shape = Part.makeCylinder(10, 20)
    return shape, next(f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder))


def fitted_boundary_face():
    """Valid fitted face with native 3D boundary points off its exact surface."""
    surface=Part.BSplineSurface()
    surface.interpolate([[V(x,y,.0005*x*x+.0003*y*y) for y in (-1,5,11)] for x in (-1,5,11)])
    points=[]
    for x,y in ((0,0),(10,0),(10,10),(0,10)):
        uv=surface.parameter(V(x,y,.0005*x*x+.0003*y*y))
        points.append(surface.value(*uv)+V(.02,.02,.02))
    face=Part.Face(surface,Part.Wire(Part.makePolygon(points+points[:1])))
    face.fix(1e-7,1e-7,.1)
    return face


class SurfacePathTests(unittest.TestCase):
    def test_diagonal_and_preview_stay_on_the_surface_instead_of_cutting_a_chord(self):
        _, face = cylinder()
        a, b = face.valueAt(.5, 2), face.valueAt(2, 15)
        path = SurfacePath(face, a, b)
        edge = path.edge()
        self.assertTrue(covered(face, edge))
        self.assertGreater(edge.Length, (b-a).Length + .1)
        for point in path.preview():
            self.assertAlmostEqual(math.hypot(point.x, point.y), 10, places=8)
            self.assertLess(edge.distToShape(Part.Vertex(point))[0], 1e-5)

    def test_cylinder_seam_takes_the_short_route(self):
        _, face = cylinder()
        path = SurfacePath(face, face.valueAt(math.tau-.2, 10), face.valueAt(.2, 10))
        self.assertAlmostEqual(path.edge().Length, 4, places=7)
        self.assertTrue(all(p.x > 9 for p in path.preview()))

    def test_sphere_and_bspline_are_exact_surface_curves(self):
        sphere = Part.makeSphere(10).Faces[0]
        spline = Part.BSplineSurface()
        spline.interpolate([[V(x, y, .03*x*x + .02*y*y) for y in (0, 5, 10, 15)]
                            for x in (0, 5, 10, 15)])
        for face in (sphere, spline.toShape()):
            u0,u1,v0,v1 = face.ParameterRange
            a = face.valueAt(u0+.2*(u1-u0), v0+.3*(v1-v0))
            b = face.valueAt(u0+.4*(u1-u0), v0+.7*(v1-v0))
            with self.subTest(surface=type(face.Surface)):
                self.assertTrue(covered(face, SurfacePath(face, a, b).edge()))

    def test_numeric_size_is_surface_length_and_preserves_the_surface(self):
        _, face = cylinder()
        a,b = face.valueAt(.5, 3),face.valueAt(1, 8)
        path = SurfacePath(face,a,b)
        for length in (3, 12, -3):
            point = path.at_length(length)
            self.assertAlmostEqual(SurfacePath(face,a,point).edge().Length, abs(length), places=6)

    def test_degenerate_and_off_surface_points_are_refused(self):
        _, face = cylinder()
        a = face.valueAt(1, 5)
        with self.assertRaises(ValueError):
            SurfacePath(face, a, a).edge()
        with self.assertRaises(ValueError):
            SurfacePath(face, a, V())
        with self.assertRaises(ValueError):
            SurfacePath(face, a, V(float('nan'),0,0))

    def test_numeric_input_cannot_silently_become_the_complementary_arc(self):
        _,face=cylinder()
        path=SurfacePath(face,face.valueAt(1,10),face.valueAt(1.5,10))
        with self.assertRaisesRegex(ValueError,'wrap'):
            path.at_length(40)

    def test_volume_guard_still_rejects_real_removed_or_added_material(self):
        from simplecad.surfaces.line import preserves_volume
        source=Part.makeBox(10,10,10)
        self.assertFalse(preserves_volume(source,source.cut(Part.makeBox(1,1,1))))
        self.assertFalse(preserves_volume(source,source.fuse(Part.makeBox(2,2,2,V(9,0,0)))))


class FreeEndTests(unittest.TestCase):
    """A segment with a free end skips the split; nothing else does."""
    def test_only_lines_closing_a_path_skip_nothing_and_every_answer_matches_the_split(self):
        def lateral(shape):
            return max((f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder)), key=lambda f: f.Area)

        def path(face, a, b):
            return SurfacePath(face, face.valueAt(*a), face.valueAt(*b)).edge()

        plain = Part.makeCylinder(10, 20)
        # The hole faces the seam, so lines through it divide the face only around the seam.
        holed = plain.cut(Part.makeCylinder(2, 30, V(0, 0, 10), V(-1, 0, 0)))
        spline = Part.BSplineSurface()
        spline.interpolate([[V(x, y, .1*x*x+.065*y*y) for y in (0, 5, 10, 15)] for x in (0, 5, 10, 15)])
        skin = spline.toShape()
        fitted = skin.extrude(V(0, 0, -5))
        top = max(fitted.Faces, key=lambda f: f.common(skin).Area)
        u0, u1, v0, v1 = top.ParameterRange
        triangle = [(u0+u*(u1-u0), v0+v*(v1-v0)) for u, v in ((.2, .3), (.4, .7), (.2, .7), (.2, .3))]
        f, h = lateral(plain), lateral(holed)
        chain = [path(f, (1, 5), (2, 5)), path(f, (2, 5), (2, 15)), path(f, (2, 15), (1, 15))]
        loop = chain + [path(f, (1, 15), (1, 5))]
        sides = [path(top, a, b) for a, b in zip(triangle, triangle[1:])]
        # name: (shape, face, segment, earlier lines, free end, faces after the split)
        cases = {
            'one interior segment': (plain, f, chain[0], [], True, None),
            'open chain': (plain, f, chain[2], chain[:2], True, None),
            'closing segment': (plain, f, loop[3], chain, False, 4),
            'rim to rim': (plain, f, path(f, (1, 0), (1, 20)), [], False, 4),
            'from the rim': (plain, f, path(f, (1, 0), (1.5, 10)), [], True, None),
            'back to the rim': (plain, f, path(f, (1.5, 10), (2, 0)), [path(f, (1, 0), (1.5, 10))], False, 4),
            'across its own chain': (plain, f, path(f, (2, 15), (1.5, 2)), chain[:2], False, 4),
            'across the seam': (plain, f, path(f, (-.2, 5), (.2, 5)), [], True, None),
            # After Undo or an import, lines can already close a region.
            'touching a closed loop': (plain, f, path(f, (2, 15), (3, 17)), loop, False, 4),
            'beside a closed loop': (plain, f, path(f, (3, 5), (3, 15)), loop, True, None),
            'hole to rim': (holed, h, path(h, (math.pi, 12), (math.pi, 20)), [], True, None),
            'hole to both rims': (holed, h, path(h, (math.pi, 8), (math.pi, 0)),
                                  [path(h, (math.pi, 12), (math.pi, 20))], False, len(holed.Faces)+1),
            'fitted open': (fitted, top, sides[1], sides[:1], True, None),
            'fitted closing': (fitted, top, sides[2], sides[:2], False, len(fitted.Faces)+1),
        }

        def split(shape, edge, lines):
            result = geo.divide_face_with_edges(shape, edge, lines, surface=True)
            return None if result is None else len(result[0].Faces)

        for name, (shape, face, edge, lines, free, faces) in cases.items():
            with self.subTest(name):
                self.assertEqual(geo.bounds_no_region(edge, lines, [face]), free)
                self.assertEqual(split(shape, edge, lines), faces)
                # The full split, as before the check, gives the same answer.
                with patch.object(geo, 'bounds_no_region', return_value=False):
                    self.assertEqual(split(shape, edge, lines), faces)

    def test_coverage_reuses_the_indexed_faces_of_an_unchanged_part(self):
        shape, face = cylinder()
        edge = SurfacePath(face, face.valueAt(1,5), face.valueAt(2,5)).edge()
        index = geo.face_index(shape)
        self.assertTrue(covered(shape, edge))
        compound = index.compound
        with patch.object(Part, 'makeCompound', side_effect=AssertionError('faces listed again')):
            self.assertTrue(covered(shape, edge))
            self.assertTrue(covered(Part.Shape(shape), edge))
        self.assertIs(index.compound, compound)
        self.assertFalse(covered(shape, Part.makeLine(V(10,0,5), V(20,0,5))))

    def test_a_failed_edge_fuse_leaves_the_decision_to_the_split(self):
        _, face = cylinder()
        broken = SimpleNamespace(generalFuse=Mock(side_effect=Part.OCCError('fuse failed')))
        self.assertFalse(geo.bounds_no_region(SimpleNamespace(Edges=[broken]), [], [face]))

    def test_bridges_ignore_self_loops_and_parallel_edges(self):
        bridges, root = geo._bridges([(0, 1), (1, 2), (2, 2), (2, 3), (3, 4), (3, 4), (5, 6)])
        self.assertEqual(bridges, {0, 1, 3, 6})
        self.assertEqual(len({root[k] for k in range(5)}), 1)
        self.assertNotEqual(root[5], root[0])


class SurfaceLineDocumentTests(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument('SurfaceLineTest')
        self.doc.UndoMode = 1
        self.obj = self.doc.addObject('Part::Feature', 'Cylinder')
        self.obj.Shape, _ = cylinder()
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def draw(self, a, b):
        face = next(f for f in self.obj.Shape.Faces if isinstance(f.Surface, Part.Cylinder))
        return ops.draw_surface_line(self.doc, face.valueAt(*a), face.valueAt(*b), self.obj, face)

    def test_boundary_to_boundary_splits_keeps_volume_and_undoes(self):
        before, count = self.obj.Shape, self.doc.UndoCount
        result, divided = self.draw((1,0), (1,20))
        self.assertTrue(divided)
        self.assertEqual(result, self.obj)
        self.assertTrue(self.obj.Shape.isValid())
        self.assertTrue(self.obj.Shape.isClosed())
        self.assertEqual(len(self.obj.Shape.Faces), 4)
        self.assertAlmostEqual(self.obj.Shape.Area, before.Area, places=6)
        self.assertAlmostEqual(self.obj.Shape.Volume, before.Volume, places=6)
        self.assertEqual(self.doc.UndoCount, count+1)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces), 3)
        self.doc.redo()
        self.assertEqual(len(self.obj.Shape.Faces), 4)

    def test_connected_interior_loop_consumes_loose_lines(self):
        corners = [(1,5), (2,5), (2,15), (1,15), (1,5)]
        for i,(a,b) in enumerate(zip(corners,corners[1:])):
            _, divided = self.draw(a,b)
            self.assertEqual(divided, i==3)
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(self.obj.Shape.Faces), 4)
        self.assertTrue(self.obj.Shape.isValid())
        self.assertAlmostEqual(self.obj.Shape.Volume, math.pi*100*20, places=6)
        self.doc.undo()
        self.assertEqual(len(self.doc.Objects), 4)
        self.assertEqual(len(self.obj.Shape.Faces), 3)

    def test_open_segments_skip_the_split_and_the_closing_one_still_divides(self):
        splits = []
        real = geo.split_faces_locally, geo.split_whole

        def spy(kind, function):
            def call(*args, **kwargs):
                splits.append(kind)
                return function(*args, **kwargs)
            return call

        with patch.object(geo, 'split_faces_locally', spy('local', real[0])), \
                patch.object(geo, 'split_whole', spy('whole', real[1])):
            corners = [(1,5), (2,5), (2,15), (1,15), (1,5)]
            for i,(a,b) in enumerate(zip(corners,corners[1:])):
                splits.clear()
                _, divided = self.draw(a,b)
                self.assertEqual(divided, i==3)
                self.assertEqual(splits, ['local'] if i==3 else [])
        self.assertEqual(len(self.doc.Objects), 1)
        self.assertEqual(len(self.obj.Shape.Faces), 4)
        self.assertTrue(self.obj.Shape.isValid())

    def test_a_segment_with_a_free_end_still_closes_a_loop_it_touches(self):
        face = next(f for f in self.obj.Shape.Faces if isinstance(f.Surface, Part.Cylinder))
        corners = [(1,5), (2,5), (2,15), (1,15), (1,5)]
        loop = self.doc.addObject('Part::Feature', 'Loop')
        loop.Shape = Part.makeCompound([SurfacePath(face, face.valueAt(*a), face.valueAt(*b)).edge()
                                        for a,b in zip(corners,corners[1:])])
        self.doc.recompute()
        name = loop.Name
        self.assertEqual(len(self.obj.Shape.Faces), 3)
        _, divided = self.draw((2,15), (3,17))
        self.assertTrue(divided)
        self.assertEqual(len(self.obj.Shape.Faces), 4)
        self.assertTrue(self.obj.Shape.isValid())
        self.assertIsNone(self.doc.getObject(name))

    def test_partial_chain_closes_against_the_rim(self):
        self.assertFalse(self.draw((1,0),(1.5,10))[1])
        self.assertTrue(self.draw((1.5,10),(2,0))[1])
        self.assertEqual(len(self.doc.Objects),1)
        self.assertEqual(len(self.obj.Shape.Faces),4)

    def test_a_segment_crosses_existing_face_divisions(self):
        self.draw((1,0),(1,20))
        self.assertFalse(self.draw((.5,5),(1.5,5))[1])
        self.draw((1.5,5),(1.5,15))
        self.draw((1.5,15),(.5,15))
        self.assertTrue(self.draw((.5,15),(.5,5))[1])
        self.assertEqual(len(self.doc.Objects),1)
        self.assertTrue(self.obj.Shape.isValid())
        self.assertGreaterEqual(len(self.obj.Shape.Faces),6)

    def test_seam_crossing_loop(self):
        corners=[(-.2,5),(.2,5),(.2,15),(-.2,15),(-.2,5)]
        for a,b in zip(corners,corners[1:]):
            result,divided=self.draw(a,b)
        self.assertTrue(divided)
        self.assertEqual(len(self.doc.Objects),1)
        self.assertTrue(self.obj.Shape.isValid())

    def test_moved_rotated_object_keeps_placement_and_survives_save_reopen(self):
        placement=App.Placement(V(35,45,55),App.Rotation(V(1,2,3),40))
        self.obj.Placement=placement
        self.doc.recompute()
        self.draw((1,0),(1,20))
        self.assertTrue(self.obj.Placement.isSame(placement,1e-9))
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'surface-line.FCStd')
            self.doc.saveAs(path)
            name=self.doc.Name
            App.closeDocument(name)
            self.doc=App.openDocument(path)
            result=self.doc.getObject('Cylinder')
            self.assertEqual(len(result.Shape.Faces),4)
            self.assertTrue(result.Shape.isValid())
            self.assertTrue(result.Placement.isSame(placement,1e-9))

    def test_open_surface_remains_open(self):
        self.obj.Shape=cylinder()[1]
        self.assertTrue(self.draw((1,0),(1,20))[1])
        self.assertFalse(self.obj.Shape.Solids)
        self.assertTrue(self.obj.Shape.isValid())

    def test_spherical_and_freeform_faces_gain_selectable_regions(self):
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.03*x*x+.02*y*y) for y in (0,5,10,15)] for x in (0,5,10,15)])
        for source in (Part.makeSphere(10),spline.toShape()):
            with self.subTest(surface=type(source.Faces[0].Surface)):
                self.obj.Shape=source
                face=source.Faces[0]
                u0,u1,v0,v1=face.ParameterRange
                a,b=u0+.2*(u1-u0),u0+.4*(u1-u0)
                c,d=v0+.3*(v1-v0),v0+.7*(v1-v0)
                points=[face.valueAt(u,v) for u,v in ((a,c),(b,c),(b,d),(a,d),(a,c))]
                for first,second in zip(points,points[1:]):
                    _,divided=ops.draw_surface_line(self.doc,first,second,self.obj,self.obj.Shape.Faces[0])
                self.assertTrue(divided)
                self.assertTrue(self.obj.Shape.isValid())
                self.assertEqual(len(self.doc.Objects),1)
                self.assertEqual(len(self.obj.Shape.Faces),len(source.Faces)+1)
                self.assertAlmostEqual(self.obj.Shape.Area,source.Area,places=5)
                from simplecad.surfaces.line import preserves_area
                self.assertFalse(preserves_area(source, min(self.obj.Shape.Faces,key=lambda f:f.Area)))

    def test_trimmed_face_cannot_be_extended_by_the_line(self):
        partial=Part.makeCylinder(10,20,V(),V(0,0,1),90)
        self.obj.Shape=next(f for f in partial.Faces if isinstance(f.Surface,Part.Cylinder))
        face=self.obj.Shape
        count=self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'surface'):
            ops.draw_surface_line(self.doc,face.valueAt(.5,10),face.valueAt(2,10),self.obj,face)
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),1)

    def test_triangle_on_a_fitted_solid_closes_despite_volume_integration_drift(self):
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.1*x*x+.065*y*y) for y in (0,5,10,15)] for x in (0,5,10,15)])
        skin=spline.toShape()
        source=skin.extrude(V(0,0,-5))
        self.obj.Shape=source
        face=max(source.Faces,key=lambda f:f.common(skin).Area)
        u0,u1,v0,v1=face.ParameterRange
        points=[face.valueAt(u0+u*(u1-u0),v0+v*(v1-v0))
                for u,v in ((.2,.3),(.4,.7),(.2,.7),(.2,.3))]
        count=self.doc.UndoCount
        for a,b in zip(points,points[1:]):
            _,divided=ops.draw_surface_line(self.doc,a,b,self.obj,face)
        self.assertTrue(divided)
        result=self.obj.Shape
        self.assertTrue(result.isValid())
        self.assertTrue(result.isClosed())
        self.assertEqual(len(result.Solids),1)
        self.assertEqual(len(result.Faces),len(source.Faces)+1)
        self.assertEqual(len(self.doc.Objects),1)
        self.assertEqual(self.doc.UndoCount,count+3)
        self.assertLess(source.cut(result).Volume,1e-6)
        self.assertLess(result.cut(source).Volume,1e-6)
        self.doc.undo()
        self.assertEqual(len(self.obj.Shape.Faces),len(source.Faces))
        self.assertEqual(len(self.doc.Objects),3)

    def test_the_next_split_reuses_the_volume_measured_for_the_last_result(self):
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.1*x*x+.065*y*y) for y in (0,5,10,15)] for x in (0,5,10,15)])
        skin=spline.toShape()
        self.obj.Shape=skin.extrude(V(0,0,-5))
        real,reads=geo.volume,[]

        def spy(shape):
            reads.append((shape,any(kept.isEqual(shape) for kept,_ in geo._volumes)))
            return real(shape)

        with patch.object(geo,'volume',side_effect=spy):
            for offset,cached in ((0,False),(.4,True)):
                source,face=self.obj.Shape,max(self.obj.Shape.Faces,key=lambda f:f.common(skin).Area)
                u0,u1,v0,v1=face.ParameterRange
                points=[face.valueAt(u0+(u+offset)*(u1-u0),v0+v*(v1-v0))
                        for u,v in ((.2,.3),(.4,.7),(.2,.7),(.2,.3))]
                reads.clear()
                for a,b in zip(points,points[1:]):
                    _,divided=ops.draw_surface_line(self.doc,a,b,self.obj,face)
                self.assertTrue(divided)
                self.assertEqual([hit for shape,hit in reads if shape.isEqual(source)],[cached])
                self.assertTrue(self.obj.Shape.isValid())

    def test_path_through_a_hole_is_refused_without_document_changes(self):
        self.obj.Shape=self.obj.Shape.cut(Part.makeCylinder(2,30,V(0,0,10),V(1,0,0)))
        source,count=self.obj.Shape,self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'opening'):
            self.draw((-.5,10),(.5,10))
        self.assertTrue(self.obj.Shape.isSame(source))
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),1)

    def test_locked_source_is_refused_even_for_an_incomplete_line(self):
        locking.set_locked([(self.obj,[])],True)
        count=self.doc.UndoCount
        with self.assertRaisesRegex(ValueError,'locked'):
            self.draw((1,5),(2,5))
        self.assertEqual(self.doc.UndoCount,count)
        self.assertEqual(len(self.doc.Objects),1)

    def test_mcp_surface_route_uses_the_same_geometry_and_requires_support(self):
        from simplecad.mcp.api import ModelAPI
        api=ModelAPI()
        api.summary=lambda obj,full:dict(name=obj.Name)
        api.stamp=lambda doc,**data:data
        face=self.obj.Shape.Faces[0]
        args=dict(start=list(face.valueAt(1,0)),end=list(face.valueAt(1,20)),surface_face='Face1')
        with self.assertRaisesRegex(ValueError,'support'):
            api.execute('create_line',self.doc,args)
        reply=api.execute('create_line',self.doc,dict(args,support=self.obj.Name))
        self.assertTrue(reply['divided_face'])
        self.assertEqual(reply['object']['name'],self.obj.Name)
        self.assertEqual(len(self.obj.Shape.Faces),4)


class SurfaceSnapTests(unittest.TestCase):
    def test_shared_corner_does_not_make_two_surfaces_the_same(self):
        from simplecad.surfaces.line import same_surface
        shape,face=cylinder()
        self.assertTrue(same_surface(face,face.copy()))
        self.assertFalse(same_surface(face,shape.Faces[1]))
        self.assertFalse(same_surface(face,Part.makeCylinder(11,20).Faces[0]))
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.01*x*x) for y in (0,5,10)] for x in (0,5,10)])
        a=spline.toShape()
        spline=Part.BSplineSurface()
        spline.interpolate([[V(x,y,.02*x*x) for y in (0,5,10)] for x in (0,5,10)])
        self.assertFalse(same_surface(a,spline.toShape()))

    def test_native_fitted_boundary_vertices_snap_in_surface_coordinates(self):
        from simplecad.surfaces.line import on_surface, project
        face=fitted_boundary_face()
        self.assertTrue(face.isValid())
        snapper=Snapper(SimpleNamespace(Objects=[]),None)
        for vertex in face.Vertexes:
            point=vertex.Point
            self.assertFalse(on_surface(face,point))
            hit=(None,face,project(face,point),'Face1')
            with patch.object(snapper,'nearby_points',return_value=[(point,'Endpoint')]), \
                    patch.object(snapper,'on_edge',return_value=None):
                snapped=snapper.snap_surface((0,0),face,hit)
                self.assertEqual(snapped.label,'Endpoint')
                self.assertTrue(on_surface(face,snapped.point))
                self.assertGreater((snapped.point-point).Length,.001)

    def test_adjacent_face_hit_can_capture_boundary_but_cannot_project_onto_it(self):
        _,face=cylinder()
        actual=face.valueAt(0,0)
        snapper=Snapper(SimpleNamespace(Objects=[]),None)
        hit=(None,Part.makePlane(30,30),V(0,0,0),'Face2')
        with patch.object(snapper,'nearby_points',return_value=[(actual,'Endpoint')]), \
                patch.object(snapper,'on_edge',return_value=None):
            snapped=snapper.snap_surface((0,0),face,hit,project_hit=False)
            self.assertEqual(snapped.label,'Endpoint')
            self.assertLess((snapped.point-actual).Length,1e-8)
            self.assertIsNone(snapper.snap_surface((0,0),face,hit,False,project_hit=False))

    def test_filters_floating_centres_and_projects_face_hit_even_with_snap_off(self):
        _,face=cylinder()
        actual=face.valueAt(1,10)
        hit=(None,face,actual*1.0001,'Face1')
        snapper=Snapper(SimpleNamespace(Objects=[]),None)
        with patch.object(snapper,'nearby_points',return_value=[(V(0,0,10),'Face center'),(actual,'Endpoint')]), \
                patch.object(snapper,'on_edge',return_value=None):
            snapped=snapper.snap_surface((0,0),face,hit)
            self.assertEqual(snapped.label,'Endpoint')
            self.assertLess((snapped.point-actual).Length,1e-8)
            free=snapper.snap_surface((0,0),face,hit,False)
            self.assertEqual(free.label,'On surface')
            self.assertAlmostEqual(math.hypot(free.point.x,free.point.y),10,places=8)
