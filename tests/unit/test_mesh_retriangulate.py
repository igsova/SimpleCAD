"""Face moves on a triangulated plate must preserve its circular hole."""
import unittest
import numpy as np
from simplecad.mesh.region import Topology, RegionPlan
from test_mesh_region import closed
from test_mesh_transform import volume


def perforated_plate():
    # A valid but uneven fan, typical of STL exports around circular holes.
    n = 32
    theta = np.arange(n)*2*np.pi/n-np.pi/8
    p = np.vstack(([(10,10,0),(0,10,0),(0,0,0),(10,0,0)],
        np.column_stack((5+2*np.cos(theta),5+2*np.sin(theta),np.zeros(n)))))
    cap = []
    for k in range(4):
        for j in range(k*n//4,(k+1)*n//4):
            cap.append((k,4+(j+1)%n,4+j))
        cap.append((k,(k+1)%4,4+((k+1)*n//4)%n))
    cap = np.asarray(cap); count = len(p)
    points = np.vstack((p,p+(0,0,2)))
    faces = [*cap[:,::-1],*(cap+count)]
    boundary = [(k,(k+1)%4) for k in range(4)]
    boundary += [(4+(k+1)%n,4+k) for k in range(n)]
    for a,b in boundary:
        faces.extend(((a,b,b+count),(a,b+count,a+count)))
    return points,np.asarray(faces,dtype=np.int64)


class RetriangulationTests(unittest.TestCase):
    def setUp(self):
        self.t = Topology(*perforated_plate())
        self.selected = set(np.flatnonzero(self.t.normals[:,0]>.999))

    def test_outward_face_move_fixes_fans_preserving_hole_and_volume(self):
        t = self.t; plan = RegionPlan(t,self.selected)
        expected = t.points+plan.weights[:,None]*(5,0,0)
        old_tri = expected[t.triangles]
        old_cross = np.cross(old_tri[:,1]-old_tri[:,0],old_tri[:,2]-old_tri[:,0])
        self.assertEqual(np.count_nonzero(np.einsum('ij,ij->i',old_cross,t.normals)<0),2)
        moved,faces = plan.transform(delta=(5,0,0))
        after = Topology(moved,faces)
        self.assertTrue(np.all(np.einsum('ij,ij->i',after.cross,t.normals)>0))
        plan.validate(moved,faces,'Move'); plan.validate_shell_orientation(moved,faces,'Move')
        closed(self,moved,faces)
        np.testing.assert_array_equal(moved,expected)
        np.testing.assert_array_equal(faces[plan.selected],t.triangles[plan.selected])
        # The 32-sided hole is unchanged; only the outer edge moved 5 mm.
        np.testing.assert_array_equal(moved[plan.weights==0],t.points[plan.weights==0])
        self.assertIsNone(after.pick((5,5,10),(0,0,-1)))
        self.assertAlmostEqual(volume(moved,faces)-volume(t.points,t.triangles),100)
        self.assertEqual(len(faces),len(t.triangles))
        p,f = perforated_plate()
        np.testing.assert_array_equal(t.points,p); np.testing.assert_array_equal(t.triangles,f)
        # A numeric edit back to zero must discard the previous diagonal flips.
        self.assertIs(plan.transform(delta=(0,0,0))[1],t.triangles)

    def test_rigid_translation_and_extrusion_leave_original_diagonals(self):
        t = self.t
        _,faces = RegionPlan(t,set(range(len(t.triangles)))).transform(delta=(20,-8,0))
        self.assertIs(faces,t.triangles)
        plan = RegionPlan(t,self.selected)
        moved,faces = plan.transform('Extrude',axis=(1,0,0),distance=5)
        closed(self,moved,faces)
        np.testing.assert_array_equal(faces[:len(t.triangles)-2],
            t.triangles[[i for i in range(len(t.triangles)) if i not in self.selected]])

    def test_nonplanar_neighbors_are_never_retriangulated(self):
        plan = RegionPlan(self.t,self.selected)
        _,faces = plan.transform(delta=(5,0,3))
        self.assertIs(faces,self.t.triangles)

    def test_disconnected_component_and_open_boundaries_are_preserved(self):
        p,f = perforated_plate(); n=len(p); m=len(f)
        t = Topology(np.vstack((p,p+(40,0,0))),np.vstack((f,f+n)))
        moved,faces = RegionPlan(t,self.selected).transform(delta=(5,0,0))
        np.testing.assert_array_equal(moved[n:],p+(40,0,0))
        np.testing.assert_array_equal(faces[m:],f+n)
        # Removing the bottom leaves an open shell; its outline must persist.
        t = Topology(p,f[36:]); selected=set(np.flatnonzero(t.normals[:,0]>.999))
        moved,faces = RegionPlan(t,selected).transform(delta=(5,0,0))
        boundary=lambda topo:{e for e,entries in topo.edges.items() if len(entries)==1}
        self.assertEqual(boundary(t),boundary(Topology(moved,faces)))

    def test_retriangulation_is_equivariant_under_placement(self):
        t=self.t; plan=RegionPlan(t,self.selected)
        angle=.713; c,s=np.cos(angle),np.sin(angle)
        rotation=np.asarray(((c,-s,0),(s,c,0),(0,0,1)))
        offset=np.asarray((35.,-47,100.))
        placed=RegionPlan(Topology(t.points@rotation.T+offset,t.triangles),self.selected)
        p,f=plan.transform(delta=(5,0,0)); world,wf=placed.transform(delta=rotation@(5,0,0))
        np.testing.assert_allclose(world,p@rotation.T+offset,atol=1e-12)
        np.testing.assert_array_equal(wf,f)

    def test_stl_coordinate_noise_uses_stable_neighbor_plane(self):
        from simplecad.mesh.retriangulate import planar_diagonals
        # One float32-scale discrepancy at a distant corner makes the larger
        # triangle's plane more reliable than the short sliver's normal.
        p=np.asarray([[3.4,48,32.4796],[3.4,43.5706,25.829],
                      [3.4,43.4722,25.6296],[3.400004,48,4.3579]])
        t=Topology(p,[(0,1,2),(2,3,0)]); moved=p.copy(); moved[0,2]+=5
        result=planar_diagonals(t,moved,np.array([],dtype=int))
        self.assertIsNot(result,t.triangles)
        after=Topology(moved,result)
        self.assertTrue(np.all(after.normals[:,0]>.999))
        # Protect a genuine crease rather than flattening it into this patch.
        p[3,0]+=.01; t=Topology(p,t.triangles); moved=p.copy(); moved[0,2]+=5
        self.assertIs(planar_diagonals(t,moved,np.array([],dtype=int)),t.triangles)

    def test_successive_flips_use_the_current_neighbor_geometry(self):
        from simplecad.mesh.retriangulate import planar_diagonals
        # A small fan beside a hole after a prior end-face extension. Repairing
        # its first folded sliver changes the neighbor used by the next flip.
        p=np.asarray([[0,0,32.06409],[0,4.3,23.06409],
                      [0,4.314545,22.842194],[0,4.357925,22.624084],
                      [0,4.429405,22.413514],[.000003814697,0,0]])
        t=Topology(p,[(4,5,0),(3,4,0),(2,3,0),(1,2,0)])
        moved=p.copy(); moved[0,1]+=3
        faces=planar_diagonals(t,moved,np.array([],dtype=int))
        after=Topology(moved,faces)
        self.assertTrue(np.all(after.normals[:,0]<-.999))
        self.assertEqual(np.count_nonzero(np.any(faces!=t.triangles,axis=1)),3)
        boundary=lambda topo:{(a,b) for entries in topo.edges.values()
                              if len(entries)==1 for _,a,b in entries}
        self.assertEqual(boundary(t),boundary(after))
        np.testing.assert_array_equal(t.points,p)


if __name__=='__main__': unittest.main()
