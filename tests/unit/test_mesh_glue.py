"""Matching mesh glue surfaces, openings, clearance, collisions and precision."""
import math
import struct
import tempfile
import unittest
import FreeCAD as App
import Mesh
import Part
from simplecad.mesh import slicing, glue as mesh_glue
from simplecad.mesh.conversion import fingerprint
V=App.Vector


def mesh(shape):return Mesh.Mesh(shape.tessellate(.15))


def volume(value):
    # Native Mesh.Volume accumulates float32 and loses precision on dense caps.
    points,faces=value.Topology;origin=value.BoundBox.Center
    return abs(math.fsum((points[a]-origin).dot((points[b]-origin).cross(points[c]-origin)) for a,b,c in faces)/6)


def triangle_keys(faces):
    return {tuple(sorted(struct.pack('<fff',*p) for p in face.Points)) for face in faces}


class MeshGlueTests(unittest.TestCase):
    def assert_closed_stl(self, pieces):
        with tempfile.TemporaryDirectory() as folder:
            for i,piece in enumerate(pieces):
                path=folder+'/side%d.stl'%i;piece.write(path);restored=Mesh.Mesh(path)
                self.assertTrue(restored.isSolid())
                self.assertFalse(restored.hasNonManifolds())
                self.assertEqual(restored.CountFacets,piece.CountFacets)

    def test_exact_match_closed_volume_and_unchanged_source(self):
        source=mesh(Part.makeBox(10,12,14));before=fingerprint(source)
        for flip in (False,True):
            pieces,report=slicing.split(source,(0,0,7),(0,0,1),glue={'depth':1,'clearance':0,'flip':flip})
            self.assertTrue(all(p.isSolid() and not p.hasSelfIntersections() for p in pieces))
            self.assertAlmostEqual(sum(volume(p) for p in pieces),volume(source),places=4)
            interfaces=[triangle_keys([f for f in p.Facets if f.Normal.z*sign>.01]) for p,sign in zip(pieces,(1,-1))]
            self.assertEqual(interfaces[0],interfaces[1])
            self.assertEqual(fingerprint(source),before)
            self.assertEqual(report['glue']['removed_volume'],0)
            self.assertGreater(pieces[0 if not flip else 1].Volume,source.Volume/2)
            self.assert_closed_stl(pieces)

    def test_clearance_removes_only_reported_glue_space(self):
        source=mesh(Part.makeBox(10,12,14));pieces,report=slicing.split(source,(0,0,7),(0,0,1),glue={'depth':1,'clearance':.15})
        removed=report['glue']['removed_volume']
        self.assertGreater(removed,0)
        self.assertAlmostEqual(volume(source)-sum(volume(p) for p in pieces),removed,delta=.001)
        self.assertAlmostEqual(report['glue']['max_ridge_height'],.85,places=5)
        original_uncut=[f for f in source.Facets if all(p[2]<7 for p in f.Points) or all(p[2]>7 for p in f.Points)]
        self.assertTrue(triangle_keys(original_uncut)<=triangle_keys(pieces[0].Facets+pieces[1].Facets))
        self.assert_closed_stl(pieces)

    def test_thin_wall_triangle_profile_and_existing_hole(self):
        source=mesh(Part.makeBox(20,3,10))
        pieces,report=slicing.split(source,(0,0,5),(0,0,1),glue={'depth':2,'clearance':0})
        cap=[f for f in pieces[0].Facets if f.Normal.z>0]
        self.assertTrue(cap)
        # Every sampled profile vertex follows two 45-degree slopes across the
        # 3 mm wall, with a 1.5 mm crest, except where the end walls taper it.
        for f in cap:
            for x,y,z in f.Points:
                self.assertAlmostEqual(z-5,min(x,20-x,y,3-y),delta=.026)
        self.assertAlmostEqual(report['glue']['max_ridge_height'],1.5,delta=.026)
        tube=mesh(Part.makeCylinder(8,10).cut(Part.makeCylinder(6,10)))
        pieces,report=slicing.split(tube,(0,0,5),(0,0,1),glue={'depth':2,'clearance':.1})
        self.assertTrue(all(p.isSolid() for p in pieces))
        self.assertTrue(all(math.hypot(p.x,p.y)>5.98 for m in pieces for p in m.Topology[0]))
        self.assertLess(report['glue']['max_ridge_height'],1)
        self.assert_closed_stl(pieces)

    def test_rotated_cut_disconnected_islands_and_repeated_split(self):
        source=mesh(Part.makeCompound([Part.makeBox(8,8,12),Part.makeBox(8,8,12,V(12,0,0))]))
        rotation=App.Rotation(V(1,2,3),31);source.Placement=App.Placement(V(20,-9,40),rotation)
        plane=slicing.plane(source,'LocalZ')
        pieces,report=slicing.split(source,tuple(plane.center),tuple(plane.normal),glue={'depth':.5,'clearance':.05})
        self.assertTrue(all(p.isSolid() for p in pieces))
        self.assertEqual([p.countComponents() for p in pieces],[2,2])
        # An existing seam remains intact when a later ordinary cut is made.
        p=slicing.plane(pieces[0],'X');again,_=slicing.split(pieces[0],tuple(p.center),tuple(p.normal))
        self.assertTrue(all(m.isSolid() for m in again))
        self.assert_closed_stl(pieces)

    def test_precision_crack_and_subdivided_edge_stitch(self):
        original=Mesh.createBox(10,10,10);points,faces=original.Topology;points=list(points);faces=list(faces)
        a,b,c=faces.pop(0)
        mid=len(points);points.append((points[a]+points[b])*.5)
        near=len(points);points.append(points[a]+V(1e-6,0,0))
        count=len(faces);faces.extend(((near,mid,c),(mid,b,c)))
        faces,_=mesh_glue.stitch_precision(points,faces,count,2e-6)
        repaired=Mesh.Mesh((points,faces))
        self.assertTrue(repaired.isSolid())
        self.assertAlmostEqual(volume(repaired),volume(original),places=4)
        self.assert_closed_stl([repaired])
        # Neighboring float32 samples can leave a tiny extra flap with two
        # edges already shared by legitimate facets. Keep those neighbors.
        direction=(points[b]-points[a]).cross(V(1,1,1));direction.normalize()
        points[mid]+=direction*1e-6
        expected=len(faces);faces.append((a,mid,b))
        faces,_=mesh_glue.stitch_precision(points,faces,count,2e-6)
        self.assertEqual(len(faces),expected)
        self.assert_closed_stl([Mesh.Mesh((points,faces))])

    def test_invalid_settings_open_input_and_breakthrough_rejected(self):
        for value in (True,[],{'unknown':1},{'depth':0},{'depth':math.nan},{'depth':1,'clearance':.8},{'clearance':-.1},{'flip':1}):
            with self.assertRaises(ValueError):mesh_glue.options(value)
        source=mesh(Part.makeBox(10,10,1))
        with self.assertRaisesRegex(ValueError,'wall'):
            slicing.split(source,(0,0,.5),(0,0,1),glue={'depth':2,'clearance':.1})
        with self.assertRaises(ValueError):slicing.split(source,(0,0,.5),(0,0,1),cap=False,glue={})
        open_mesh=mesh(Part.makePlane(10,10))
        with self.assertRaises(ValueError):slicing.split(open_mesh,(5,0,0),(1,0,0),glue={})
        thin=mesh(Part.makeBox(10,.2,10))
        with self.assertRaisesRegex(ValueError,'thin'):
            slicing.split(thin,(0,0,5),(0,0,1),glue={'depth':2,'clearance':.15})


if __name__=='__main__':unittest.main()
