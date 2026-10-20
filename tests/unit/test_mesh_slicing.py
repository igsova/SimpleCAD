"""Mesh clipping preserves source triangles, holes, placements and enclosed volume."""
import math
import struct
import unittest
import FreeCAD as App
import Mesh
import Part
from simplecad.mesh import slicing as s
from simplecad.mesh.conversion import fingerprint
V=App.Vector


def mesh(shape): return Mesh.Mesh(shape.tessellate(.1))


def facets(m):
    points, triangles=m.Topology
    def key(face):
        vertices=[struct.pack('<fff',*points[i]) for i in face]
        return min(tuple(vertices[i:]+vertices[:i]) for i in range(3))
    return {key(face) for face in triangles}


class MeshSliceTests(unittest.TestCase):
    def test_axis_splits_preserve_closed_mesh_and_untouched_triangles(self):
        original=mesh(Part.makeBox(20,30,40));before=fingerprint(original)
        for axis in ('X','Y','Z','Main'):
            with self.subTest(axis=axis):
                plane=s.plane(original,axis)
                pieces,report=s.split(original,tuple(plane.center),tuple(plane.normal))
                self.assertTrue(all(p.isSolid() for p in pieces))
                self.assertAlmostEqual(sum(p.Volume for p in pieces),original.Volume,places=2)
                self.assertEqual(fingerprint(original),before)
                uncut=Mesh.Mesh([f.Points for f in original.Facets if all((V(*p)-plane.center).dot(plane.normal)>1e-6 for p in f.Points) or all((V(*p)-plane.center).dot(plane.normal)<-1e-6 for p in f.Points)])
                self.assertTrue(facets(uncut) <= facets(pieces[0])|facets(pieces[1]))

    def test_tube_and_nested_cavity_are_not_filled(self):
        shapes=[Part.makeCylinder(15,30).cut(Part.makeCylinder(8,30)),
                Part.makeBox(30,30,30).cut(Part.makeBox(20,20,20,V(5,5,5)))]
        for shape in shapes:
            original=mesh(shape)
            for axis in ('X','Z'):
                p=s.plane(original,axis);pieces,_=s.split(original,tuple(p.center),tuple(p.normal))
                self.assertTrue(all(piece.isSolid() for piece in pieces))
                self.assertLess(abs(sum(m.Volume for m in pieces)-original.Volume),max(.2,original.Volume*1e-4))

    def test_oblique_cut_through_vertices_and_edges(self):
        original=Mesh.createBox(20,20,20)
        for n in ((1,1,0),(1,1,1),(1,2,3)):
            pieces,_=s.split(original,(0,0,0),n)
            self.assertTrue(all(m.isSolid() for m in pieces))
            self.assertAlmostEqual(sum(p.Volume for p in pieces),8000,places=2)

    def test_main_axis_follows_rotated_elongated_mesh(self):
        original=mesh(Part.makeBox(10,20,80))
        rotation=App.Rotation(V(1,2,3),37)
        original.Placement=App.Placement(V(40,20,-9),rotation)
        self.assertGreater(abs(s.plane(original,'Main').normal.dot(rotation.multVec(V(0,0,1)))),.9999)
        self.assertGreater(s.plane(original,'LocalZ').normal.dot(rotation.multVec(V(0,0,1))),.9999)
        p=s.plane(original,'Y');pieces,_=s.split(original,tuple(p.center),tuple(p.normal))
        self.assertTrue(all(m.isSolid() for m in pieces))

    def test_disconnected_components_and_open_splits(self):
        original=mesh(Part.makeCompound([Part.makeBox(10,10,10),Part.makeBox(10,10,10,V(0,20,0))]))
        p=s.plane(original,'Z');pieces,_=s.split(original,tuple(p.center),tuple(p.normal))
        self.assertTrue(all(m.isSolid() for m in pieces))
        self.assertEqual([m.countComponents() for m in pieces],[2,2])
        pieces,r=s.split(original,tuple(p.center),tuple(p.normal),cap=False)
        self.assertFalse(any(m.isSolid() for m in pieces));self.assertTrue(r['warnings'])
        surface=mesh(Part.makePlane(10,10));pieces,r=s.split(surface,(5,0,0),(1,0,0),cap=False)
        self.assertAlmostEqual(sum(p.Area for p in pieces),surface.Area,places=4)

    def test_reject_nonintersection_and_invalid_inputs(self):
        original=Mesh.createBox(10,10,10)
        for origin,normal in [((10,0,0),(1,0,0)),((5,0,0),(1,0,0)),((0,0,0),(0,0,0)),((math.nan,0,0),(1,0,0))]:
            with self.assertRaises(ValueError):s.split(original,origin,normal)
        with self.assertRaises(ValueError):s.split(original,(0,0,0),(1,0,0),cap=1)
        with self.assertRaises(ValueError):s.plane(original,'garbage')

    def test_existing_opening_in_cut_plane_is_not_capped(self):
        box=Part.makeBox(10,10,10,V(30,0,-10))
        open_faces=[f for f in box.Faces if abs(f.CenterOfMass.z)>1e-6]
        original=mesh(Part.makeCompound(open_faces+[Part.makeBox(10,10,10,V(0,0,-5))]))
        self.assertFalse(original.isSolid())
        pieces,report=s.split(original,(0,0,0),(0,0,1))
        self.assertFalse(pieces[0].isSolid())
        self.assertTrue(pieces[1].isSolid())
        # Two 10 x 10 caps belong to the bisected box; the separate original
        # 10 x 10 opening, coincident with the cut plane, must add no cap.
        self.assertAlmostEqual(sum(p.Area for p in pieces),original.Area+200,places=4)
        self.assertTrue(report['warnings'])


if __name__=='__main__':unittest.main()
