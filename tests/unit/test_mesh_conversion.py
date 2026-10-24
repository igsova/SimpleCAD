"""Native STL conversion: topology, cavities, validation and source preservation."""
import unittest
import math
import FreeCAD as App
import Mesh
import Part
from simplecad.mesh.conversion import convert, fingerprint, options


def mesh(shape):
    return Mesh.Mesh(shape.tessellate(.05))


class MeshConversionTests(unittest.TestCase):
    def test_closed_cylinder_rebuilds_as_an_analytic_cylinder(self):
        source = mesh(Part.makeCylinder(8, 24, App.Vector(12, -4, 7), App.Vector(1, 2, 3)))
        before = fingerprint(source)
        result, report = convert(source, tolerance=.01)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(report['cylinders'], 1)
        self.assertEqual(len(result.Faces), 3)
        curved = [face for face in result.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(curved[0].Surface.Radius, 8, places=5)
        self.assertAlmostEqual(result.Volume, math.pi * 8 * 8 * 24, delta=.05)
        self.assertEqual(fingerprint(source), before)

    def test_cylindrical_hole_inside_planar_body_becomes_analytic(self):
        body = Part.makeBox(40, 30, 20)
        body = body.cut(Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        source = mesh(body)
        result, report = convert(source, tolerance=.01)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertGreaterEqual(report['analytic_holes'], 1)
        curved = [face for face in result.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(curved), 1)
        self.assertAlmostEqual(curved[0].Surface.Radius, 6, places=5)
        self.assertAlmostEqual(result.Volume, body.Volume, delta=1e-2)

    def test_stepped_bore_keeps_its_narrow_middle(self):
        # Equal counterbores at both ends are not one through hole: the wall
        # between them is narrower, and that material must stay.
        body = Part.makeBox(60, 60, 40)
        for z in (0, 32):
            body = body.cut(Part.makeCylinder(15, 8, App.Vector(30, 30, z)))
        body = body.cut(Part.makeCylinder(11, 40, App.Vector(30, 30, 0)))
        result, report = convert(mesh(body), tolerance=.1)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertTrue(result.isInside(App.Vector(30, 43, 20), 1e-6, False))
        self.assertAlmostEqual(result.Volume, body.Volume, delta=body.Volume * 1e-3)
        radii = sorted(round(face.Surface.Radius, 3) for face in result.Faces
                       if isinstance(face.Surface, Part.Cylinder))
        self.assertEqual(radii, [11, 15, 15])
        self.assertEqual(report['analytic_holes'], 3)

    def test_noisy_flat_regions_rebuild_as_six_editable_faces(self):
        original = mesh(Part.makeBox(20,30,40))
        points, triangles = original.Topology
        points, triangles = list(points), list(triangles)
        for _ in range(2):
            midpoints, refined = {}, []
            def midpoint(a,b):
                key = tuple(sorted((a,b)))
                if key not in midpoints:
                    midpoints[key] = len(points)
                    points.append((points[a]+points[b])/2)
                return midpoints[key]
            for a,b,c in triangles:
                ab,bc,ca = midpoint(a,b),midpoint(b,c),midpoint(c,a)
                refined.extend(((a,ab,ca),(ab,b,bc),(ca,bc,c),(ab,bc,ca)))
            triangles = refined
        rotation = App.Rotation(App.Vector(1,2,3),27)
        points = [rotation.multVec(p)+App.Vector(14,-6,25)+App.Vector(math.sin(i)*.00005,math.cos(i)*.00005,math.sin(i*2)*.00005)
                  for i,p in enumerate(points)]
        source = Mesh.Mesh((points,triangles));before = fingerprint(source)
        result,report = convert(source,tolerance=.001)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Faces),6)
        self.assertLess(report['max_plane_deviation'],.001)
        self.assertAlmostEqual(result.Volume,24000,delta=.2)
        self.assertEqual(fingerprint(source),before)
        # The large reconstructed face is usable by the kernel, rather than
        # only a collection of hidden triangle dividers.
        face = max(result.Faces,key=lambda f:f.Area)
        self.assertTrue(face.extrude(face.normalAt(0,0)*2).isValid())
        from simplecad.document import operations
        doc = App.newDocument('ReconstructedMeshPull')
        try:
            doc.UndoMode = 1
            obj = doc.addObject('Part::Feature','Editable')
            obj.Shape = result
            picked = max(obj.Shape.Faces,key=lambda f:f.Area)
            operations.extrude(obj,picked,2)
            self.assertTrue(obj.Shape.isValid() and obj.Shape.isClosed())
            self.assertGreater(obj.Shape.Volume,result.Volume)
            doc.undo()
            self.assertAlmostEqual(obj.Shape.Volume,result.Volume)
        finally:
            App.closeDocument(doc.Name)

    def test_reconstructed_plate_keeps_two_through_holes(self):
        plate = Part.makeBox(60,20,5)
        for x in (15,45):
            plate = plate.cut(Part.makeCylinder(3,5,App.Vector(x,10,0)))
        source = mesh(plate)
        result,report = convert(source)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertTrue(result.isInside(App.Vector(30,10,2),1e-6,False))
        self.assertFalse(result.isInside(App.Vector(15,10,2),1e-6,False))
        self.assertFalse(result.isInside(App.Vector(45,10,2),1e-6,False))
        top = max((f for f in result.Faces if f.CenterOfMass.z>4.99),key=lambda f:f.Area)
        self.assertEqual(len(top.Wires),3)
        self.assertGreater(top.Area,1100)
        self.assertLess(report['faces'],source.CountFacets)

    def test_flat_triangles_merge_and_source_is_unchanged(self):
        source = mesh(Part.makeBox(20, 30, 40))
        before = fingerprint(source)
        result, report = convert(source)
        self.assertEqual(report['faces'], 6)
        self.assertEqual(report['solids'], 1)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 24000)
        self.assertEqual(before, fingerprint(source))

    def test_open_mesh_stays_open_and_reported(self):
        result, report = convert(mesh(Part.makePlane(20, 30)))
        self.assertFalse(result.Solids)
        self.assertEqual(len(result.Faces), 1)
        self.assertTrue(result.isValid())
        self.assertTrue(report['warnings'])

    def test_separate_solids_and_nested_cavity(self):
        outer = Part.makeBox(20, 20, 20)
        inner = Part.makeBox(10, 10, 10, App.Vector(5, 5, 5))
        other = Part.makeBox(5, 5, 5, App.Vector(40, 0, 0))
        result, report = convert(mesh(Part.makeCompound([outer, inner, other])))
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 2)
        self.assertAlmostEqual(result.Volume, 7125)

    def test_partial_overlap_rejected(self):
        a = Part.makeBox(10, 10, 10)
        b = Part.makeBox(10, 10, 10, App.Vector(5, 2, 1))
        with self.assertRaisesRegex(ValueError, 'overlap'):
            convert(mesh(Part.makeCompound([a, b])))

    def test_optional_simplification_preserves_valid_closed_shape(self):
        source = mesh(Part.makeSphere(10))
        result, report = convert(source, simplify=.01)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertTrue(report['simplified'])
        self.assertLess(report['faces'], source.CountFacets)
        self.assertLess(abs(result.Volume-source.Volume)/source.Volume, .02)

    def test_empty_and_invalid_options(self):
        with self.assertRaises(ValueError): convert(Mesh.Mesh())
        for value in [True, float('nan'), float('inf'), -1, 2, 'a']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): options(value)
                with self.assertRaises(ValueError): options(simplify=value)


if __name__ == '__main__':
    unittest.main()
