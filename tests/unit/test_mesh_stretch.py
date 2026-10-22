"""Native mesh output, placement, open surfaces, and STL round trips."""
import tempfile
import unittest
from pathlib import Path
import FreeCAD as App
import Mesh
import Part
import numpy as np
from simplecad.mesh import stretch as s
from simplecad.mesh.conversion import fingerprint
from test_mesh_transform import box_with_collinear_facet


def volume(mesh):
    """Mesh volume summed in float64; Mesh.Volume sums in float32 and drifts by ~0.03 mm³ here."""
    points,triangles=mesh.Topology
    p=np.array([tuple(v) for v in points]); a,b,c=(p[np.array(triangles)[:,i]] for i in range(3))
    return float(np.einsum('ij,ij->i',a,np.cross(b,c)).sum()/6)


class MeshStretchTests(unittest.TestCase):
    def test_existing_degenerate_facets_keep_closed_native_mesh(self):
        points, triangles = box_with_collinear_facet()
        original=Mesh.Mesh(([App.Vector(*p) for p in points.tolist()],list(map(tuple,triangles.tolist()))))
        before=fingerprint(original)
        self.assertTrue(original.isSolid())
        result,report=s.stretch(original,(0,0,0),(0,0,1),3,7,(0,0,17))
        self.assertTrue(result.isSolid()); self.assertFalse(result.hasNonManifolds())
        self.assertFalse(result.hasNonUniformOrientedFacets())
        self.assertAlmostEqual(result.Volume,2700,places=3)
        self.assertEqual(report['degenerate_triangles_before'],1)
        self.assertGreater(report['degenerate_triangles'],1)
        self.assertTrue(report['warnings'])
        self.assertEqual(fingerprint(original),before)

    def test_rotated_plane_parameters_follow_placed_mesh(self):
        doc = App.newDocument('RotatedStretchTest'); doc.UndoMode=1
        try:
            owner=doc.addObject('Mesh::Feature','Source')
            owner.Mesh=Mesh.Mesh(Part.makeBox(20,30,40).tessellate(.1))
            owner.Placement=App.Placement(App.Vector(11,-25,31),App.Rotation(App.Vector(1,2,3),35))
            plane=s.control_plane(owner.Mesh,'LocalZ',(15,-25,30))
            base=s.control_plane(owner.Mesh,'LocalZ')
            self.assertLess((plane.center-base.center).Length,1e-9)
            params=s.parameters(owner,axis='LocalZ',rotation=(15,-25,30),lower=-5,upper=5,distance=3)
            self.assertLess((owner.Placement.multVec(App.Vector(*params['origin']))-plane.center).Length,1e-9)
            self.assertLess((owner.Placement.Rotation.multVec(App.Vector(*params['normal']))-plane.normal).Length,1e-9)
            self.assertLess((owner.Placement.Rotation.multVec(App.Vector(*params['delta']))-plane.normal*3).Length,1e-9)
            local=owner.Mesh.copy(); local.Placement=App.Placement()
            result,_=s.stretch(local,**params)
            self.assertTrue(result.isSolid()); self.assertGreater(result.Volume,local.Volume)
        finally:
            App.closeDocument(doc.Name)

    def test_mesh_stays_closed_and_exports(self):
        original=Mesh.Mesh(Part.makeBox(20,30,40).tessellate(.1)); before=fingerprint(original)
        result, report=s.stretch(original,(0,0,0),(0,0,1),10,30,(0,0,10))
        self.assertTrue(result.isSolid()); self.assertFalse(result.hasNonManifolds())
        self.assertAlmostEqual(result.Volume,20*30*50,places=2)
        self.assertEqual(fingerprint(original),before)
        self.assertTrue(report['closed'])
        with tempfile.TemporaryDirectory() as directory:
            file=str(Path(directory)/'stretched.stl'); result.write(file)
            exported=Mesh.Mesh(file)
            self.assertTrue(exported.isSolid()); self.assertEqual(exported.CountFacets,result.CountFacets)

    def test_holes_in_rigid_end_preserve_shape(self):
        shape=Part.makeBox(20,30,40).cut(Part.makeCylinder(2,20,App.Vector(0,15,35),App.Vector(1,0,0)))
        mesh=Mesh.Mesh(shape.tessellate(.1))
        result,_=s.stretch(mesh,(0,0,0),(0,0,1),10,25,(0,0,10))
        self.assertTrue(result.isSolid())
        self.assertAlmostEqual(volume(result)-volume(mesh),6000,places=6)

    def test_open_sheet_and_shortening_rejection(self):
        mesh=Mesh.Mesh(Part.makePlane(20,30).tessellate(.1))
        result,report=s.stretch(mesh,(0,0,0),(0,1,0),5,20,(0,10,0))
        self.assertFalse(result.isSolid()); self.assertTrue(report['warnings'])
        self.assertAlmostEqual(result.Area,800,places=3)
        with self.assertRaisesRegex(ValueError,'collapse'):
            s.stretch(mesh,(0,0,0),(0,1,0),5,20,(0,-15,0))


if __name__ == '__main__': unittest.main()
