"""Indexed regional edits: selection, connectivity, holes and exact rigid motion."""
from collections import Counter
import unittest
import numpy as np
from simplecad.mesh.region import Topology, RegionPlan, resolve
from test_mesh_transform import box, box_with_collinear_facet, volume


def cylinder(n=48):
    theta=np.arange(n)*2*np.pi/n
    ring=np.column_stack((5*np.cos(theta),5*np.sin(theta)))
    p=np.vstack((np.column_stack((ring,np.zeros(n))),np.column_stack((ring,np.full(n,10))),
                 [[0,0,0],[0,0,10]]))
    f=[]
    for a in range(n):
        b=(a+1)%n
        f += [(a,b,b+n),(a,b+n,a+n),(2*n,b,a),(2*n+1,a+n,b+n)]
    return p,np.asarray(f)


def grid(n=8):
    p=np.asarray([(x,y,0.) for y in range(n+1) for x in range(n+1)])
    f=[]
    for y in range(n):
        for x in range(n):
            a=y*(n+1)+x; b=a+1; c=a+n+1; d=c+1
            f.extend(((a,b,d),(a,d,c)))
    return p,np.asarray(f)


def closed(test,p,f):
    edges=Counter((a,b) for a,b,c in f.tolist() for a,b in ((a,b),(b,c),(c,a)))
    test.assertTrue(all(n==1 and edges[b,a]==1 for (a,b),n in edges.items()))


def reference_connectivity(f):
    """The original per-half-edge loop, kept as the specification."""
    adjacent=[set() for _ in f]; neighbors={}; edges={}; border=set()
    for i,(a,b,c) in enumerate(f.tolist()):
        for a,b in ((a,b),(b,c),(c,a)):
            edges.setdefault((min(a,b),max(a,b)),[]).append((i,a,b))
            neighbors.setdefault(a,set()).add(b); neighbors.setdefault(b,set()).add(a)
    for entries in edges.values():
        if len(entries)!=2: border.update(entry[0] for entry in entries)
        else:
            a,b=entries[0][0],entries[1][0]; adjacent[a].add(b); adjacent[b].add(a)
    return adjacent,neighbors,edges,border


class RegionTests(unittest.TestCase):
    def test_vectorized_connectivity_matches_reference(self):
        p,f=grid(4); n=len(p)
        # Two components, an open boundary and a three-sheet edge.
        meshes=[cylinder(),grid(),(np.vstack((p,p+5,[[1,1,4]])),
                np.vstack((f[3:],f+n,[[n+6,n+7,2*n]])))]
        for p,f in meshes:
            t=Topology(p,f); adjacent,neighbors,edges,border=reference_connectivity(f)
            self.assertEqual([set(s) for s in t.adjacent],adjacent)
            self.assertEqual({i:set(t.neighbors[i]) for i in neighbors},neighbors)
            self.assertEqual(t.edges,edges); self.assertEqual(list(t.edges),list(edges))
            self.assertEqual(t.border_faces,border)
            for (a,b),entries in edges.items():
                self.assertEqual(sorted(t.edge_faces(b,a)),sorted(e[0] for e in entries))
            labels,closed=t.components()
            for i,near in enumerate(adjacent):
                self.assertTrue(all(labels[j]==labels[i] for j in near))
            self.assertEqual(len(closed),len({int(x) for x in labels}))
        labels,closed=Topology(*meshes[2]).components()
        self.assertEqual(len(closed),3); self.assertFalse(closed.any())
        self.assertTrue(Topology(*cylinder()).components()[1].all())
        self.assertEqual(Topology(*cylinder()).edge_faces(0,99),[])


    def test_flat_selection_respects_sharp_edges(self):
        t=Topology(*box())
        self.assertEqual(t.region(3),{2,3})
        self.assertEqual(t.region(3,'Triangle'),{2})
        self.assertEqual(t.region(3,'Smooth',15),{2,3})
        self.assertGreater(len(t.region(3,grow=1)),2)
        self.assertEqual(t.grow({2,3},-1),set())

    def test_smooth_selects_cylinder_wall_but_not_caps(self):
        t=Topology(*cylinder())
        selected=t.region(1,'Smooth',10)
        self.assertEqual(selected,{i for i in range(192) if i%4<2})
        self.assertEqual(len(t.region(1,'Flat')),2)
        self.assertEqual(len(t.region(3,'Flat')),48)

    def test_shrink_erodes_open_mesh_boundary(self):
        t=Topology(*grid(3)); all_faces=set(range(len(t.triangles)))
        smaller=t.grow(all_faces,-1)
        self.assertTrue(smaller and smaller<all_faces)
        self.assertFalse(smaller & t.border_faces)

    def test_click_picks_frontmost_triangle_and_preview_position(self):
        t=Topology(*box())
        self.assertIn(t.pick((2,3,20),(0,0,-1)),{2,3})
        self.assertIsNone(t.pick((30,30,20),(0,0,-1)))
        self.assertIn(t.pick((2,3,-10),(0,0,1)),{0,1})
        moved,faces=RegionPlan(t,{2,3}).transform(delta=(0,0,5))
        self.assertIn(t.pick((2,3,20),(0,0,-1),moved,faces),{2,3})
        with self.assertRaises(ValueError): t.pick((0,0,0),(0,0,0))

    def test_selected_patch_moves_rigidly_and_other_component_stays_fixed(self):
        p,f=grid(); second=p+[0,0,.01]
        t=Topology(np.vstack((p,second)),np.vstack((f,f+len(p))))
        selected={2*(3*8+3),2*(3*8+3)+1}; plan=RegionPlan(t,selected,3)
        moved,faces=plan.transform(delta=(1,2,3)); plan.validate(moved,faces,'Move')
        np.testing.assert_allclose(moved[plan.vertices],t.points[plan.vertices]+(1,2,3))
        np.testing.assert_array_equal(moved[len(p):],second)
        np.testing.assert_array_equal(moved[plan.weights==0],t.points[plan.weights==0])
        self.assertGreater(plan.summary()['transition_vertices'],0)
        self.assertTrue(np.any(np.isclose(plan.weights,1/3)))
        self.assertIs(faces,t.triangles)

    def test_rotation_about_area_center_and_explicit_pivot(self):
        t=Topology(*box()); plan=RegionPlan(t,{2,3})
        moved,f=plan.transform('Rotate',angle=90)
        expected=np.column_stack((10-t.points[4:,1],t.points[4:,0],t.points[4:,2]))
        np.testing.assert_allclose(moved[4:],expected,atol=1e-12)
        np.testing.assert_array_equal(moved[:4],t.points[:4])
        moved,_=plan.transform('Rotate',axis=(0,0,2),angle=90,pivot=(0,0,0))
        np.testing.assert_allclose(moved[4:],np.column_stack((-t.points[4:,1],t.points[4:,0],t.points[4:,2])),atol=1e-12)

    def test_extrude_adds_only_boundary_walls_and_preserves_closed_winding(self):
        t=Topology(*box()); plan=RegionPlan(t,{2,3})
        points,faces=plan.transform('Extrude',distance=4)
        plan.validate(points,faces,'Extrude'); closed(self,points,faces)
        self.assertEqual(len(faces),20); self.assertEqual(len(plan.boundary),4)
        self.assertAlmostEqual(volume(points,faces),1400)
        self.assertIs(plan.transform('Extrude',distance=5)[1],faces)
        np.testing.assert_array_equal(points[:len(t.points)],t.points)

    def test_extrusion_preserves_holes_in_annular_patch(self):
        # Four quads between square rims, with top orientation +Z.
        p=np.asarray([(0,0,0),(10,0,0),(10,10,0),(0,10,0),
                      (3,3,0),(7,3,0),(7,7,0),(3,7,0)],dtype=float)
        f=np.asarray([(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)])
        t=Topology(p,f); plan=RegionPlan(t,set(range(8)))
        moved,faces=plan.transform('Extrude',distance=3); plan.validate(moved,faces,'Extrude')
        self.assertEqual(len(plan.boundary),8); self.assertEqual(len(faces),24)
        # An open patch stays open at its original rim, including its hole.
        edges=Counter(tuple(sorted((a,b))) for a,b,c in faces.tolist() for a,b in ((a,b),(b,c),(c,a)))
        self.assertEqual(sum(n==1 for n in edges.values()),8)
        self.assertTrue(all(n in (1,2) for n in edges.values()))
        cap=moved[faces[:8]]
        self.assertAlmostEqual(np.linalg.norm(np.cross(cap[:,1]-cap[:,0],cap[:,2]-cap[:,0]),axis=1).sum()/2,84)
        self.assertIsNone(Topology(moved,faces).pick((5,5,10),(0,0,-1)))

    def test_rejects_invalid_regions_parameters_and_new_collapses(self):
        t=Topology(*box())
        for args in ({},{'triangles':[1],'seed_triangle':1},{'triangles':[0]}, {'triangles':[True]}, {'seed_triangle':30}, {'seed_triangle':1,'grow':31}):
            with self.subTest(args=args), self.assertRaises(ValueError): resolve(t,**args)
        for rings in (0,31,True):
            with self.assertRaises(ValueError): RegionPlan(t,{2,3},rings)
        plan=RegionPlan(t,{2,3})
        for args in ({'mode':'Extrude','distance':0},{'mode':'Rotate','axis':(0,0,0),'angle':10},
                     {'delta':(float('nan'),0,0)},{'mode':'Rotate','angle':181}):
            with self.subTest(args=args),self.assertRaises(ValueError): plan.transform(**args)
        moved,f=plan.transform(delta=(0,0,-10))
        with self.assertRaisesRegex(ValueError,'collapses'): plan.validate(moved,f,'Move')
        with self.assertRaisesRegex(ValueError,'entire closed'):
            RegionPlan(t,set(range(12))).transform('Extrude',axis=(0,0,1),distance=2)
        with self.assertRaisesRegex(ValueError,'branches'):
            RegionPlan(Topology(*grid(2)),{0,6}).transform('Extrude',distance=2)

    def test_existing_collinear_facets_retained_and_input_unchanged(self):
        p,f=box_with_collinear_facet(); oldp,oldf=p.copy(),f.copy()
        t=Topology(p,f); plan=RegionPlan(t,{2,3}); moved,faces=plan.transform(delta=(0,0,2))
        plan.validate(moved,faces,'Move'); closed(self,moved,faces)
        self.assertAlmostEqual(volume(moved,faces),1200)
        np.testing.assert_array_equal(p,oldp); np.testing.assert_array_equal(f,oldf)

    def test_apply_rejects_one_inverted_shell_in_multipart_mesh(self):
        p,f=box(); t=Topology(np.vstack((p,p+(20,0,0))),np.vstack((f,f+len(p))))
        plan=RegionPlan(t,{2,3})
        moved,faces=plan.transform(delta=(0,0,-15))
        # Triangle areas are nonzero and overall volume is still positive.
        plan.validate(moved,faces,'Move'); self.assertGreater(volume(moved,faces),0)
        with self.assertRaisesRegex(ValueError,'inside out'):
            plan.validate_shell_orientation(moved,faces,'Move')
        for mode,args in [('Move',{'delta':(0,0,3)}),('Extrude',{'distance':3}),('Rotate',{'angle':5})]:
            moved,faces=plan.transform(mode,**args)
            plan.validate_shell_orientation(moved,faces,mode)

    def test_transforms_are_equivariant_under_placement(self):
        p,f=box(); rotation=np.asarray([[0,0,1],[0,1,0],[-1,0,0.]])
        offset=np.asarray([53.,-17,29]); original=RegionPlan(Topology(p,f),{2,3})
        placed=RegionPlan(Topology(p@rotation.T+offset,f),{2,3})
        for mode,values,local in [('Move',{'delta':rotation@(0,1,2)},{'delta':(0,1,2)}),
                                 ('Rotate',{'angle':15},{'angle':15}),('Extrude',{'distance':3},{'distance':3})]:
            result,faces=placed.transform(mode,**values); baseline,bfaces=original.transform(mode,**local)
            np.testing.assert_allclose(result,baseline@rotation.T+offset,atol=1e-12)
            np.testing.assert_array_equal(faces,bfaces)


if __name__=='__main__': unittest.main()
