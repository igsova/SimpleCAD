"""Native smooth-surface conversion: few faces, validity, closure and fallback."""
import unittest
from unittest import mock

import numpy as np
import FreeCAD as App
import Mesh
import Part

from simplecad.mesh import surfaces as mesh_surfaces
from simplecad.mesh.conversion import convert, fingerprint, indexed


def mesh(shape, deflection=.05):
    return Mesh.Mesh(shape.tessellate(deflection))


def filleted_box():
    box = Part.makeBox(40, 30, 20)
    return box.makeFillet(4, box.Edges)


def tessellated(shape, deflection=.01):
    points, triangles = shape.tessellate(deflection)
    return np.asarray([tuple(p) for p in points]), np.asarray(triangles)


def distance_to_mesh(points, source):
    """Largest distance from points to the nearest mesh vertex or facet centroid
    (an upper bound on the true distance to the mesh plus half a facet)."""
    p, f = indexed(source)
    samples = np.vstack((p, p[f].mean(axis=1)))
    from scipy.spatial import cKDTree
    return float(cKDTree(samples).query(points)[0].max())


class SmoothSurfaceTests(unittest.TestCase):
    def check_solid(self, shape, source, tolerance):
        self.assertTrue(shape.isValid())
        self.assertTrue(shape.isClosed())
        self.assertEqual(len(shape.Solids), 1)
        points, triangles = tessellated(shape)
        corners = points[triangles]
        volume = np.einsum('ij,ij->i', corners[:, 0], np.cross(corners[:, 1], corners[:, 2])).sum()/6
        self.assertLessEqual(abs(volume-source.Volume), tolerance*source.Area)
        # OCC's own volume, which FreeCAD shows, agrees too.
        self.assertAlmostEqual(shape.Volume, source.Volume, delta=.002*source.Volume)

    def test_filleted_box_becomes_a_few_smooth_faces(self):
        source = mesh(filleted_box(), .1)
        points, triangles = indexed(source)
        shape, detail = mesh_surfaces.reconstruct(points, triangles, True, .1)
        self.check_solid(shape, source, .1)
        self.assertLessEqual(len(shape.Faces), 10)
        self.assertEqual(detail['fitted_faces'], len(shape.Faces))
        self.assertLessEqual(detail['max_facet_deviation'], .1)
        self.assertLessEqual(detail['max_edge_gap'], .1)

    def test_sphere_and_cylinder_close_into_solids(self):
        for solid, limit in ((Part.makeSphere(10), 8), (Part.makeCylinder(8, 24, App.Vector(12, -4, 7), App.Vector(1, 2, 3)), 3)):
            source = mesh(solid)
            points, triangles = indexed(source)
            shape, _ = mesh_surfaces.reconstruct(points, triangles, True, .1)
            self.check_solid(shape, source, .1)
            self.assertLessEqual(len(shape.Faces), limit)
            boundary = np.asarray([tuple(v.Point) for v in shape.Vertexes])
            self.assertLess(distance_to_mesh(boundary, source), .5)

    def test_holes_become_analytic_cylinders_with_circular_rims(self):
        box = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        pipe = Part.makeCylinder(10, 20).cut(Part.makeCylinder(7, 20))
        pipe = pipe.cut(Part.makeCylinder(2, 30, App.Vector(-15, 0, 10), App.Vector(1, 0, 0)))
        for body, faces, cylinders, circles in ((box, 7, 1, 2), (pipe, 6, 4, 4)):
            source = mesh(body)
            points, triangles = indexed(source)
            shape, detail = mesh_surfaces.reconstruct(points, triangles, True, .1)
            self.check_solid(shape, source, .1)
            self.assertEqual(len(shape.Faces), faces)
            found = [face for face in shape.Faces if isinstance(face.Surface, Part.Cylinder)]
            self.assertEqual(len(found), cylinders)
            self.assertEqual(detail['fitted_cylinders'], cylinders)
            # A hole's rim on a flat face is one exact circle, not a chain
            # of segments, and the cylinder keeps the hole's radius.
            rims = [edge for edge in shape.Edges if isinstance(edge.Curve, Part.Circle)]
            self.assertEqual(len(rims), circles)
            self.assertTrue(all(edge.isClosed() for edge in rims))
        self.assertAlmostEqual(min(face.Surface.Radius for face in found), 2, delta=.05)

    def test_open_dome_becomes_an_open_shell(self):
        sphere = Part.makeSphere(10)
        dome = Part.makeShell([face for face in sphere.cut(Part.makeBox(30, 30, 30, App.Vector(-15, -15, -30))).Faces
                               if isinstance(face.Surface, Part.Sphere)])
        source = mesh(dome)
        points, triangles = indexed(source)
        shape, _ = mesh_surfaces.reconstruct(points, triangles, False, .1)
        self.assertTrue(shape.isValid())
        self.assertFalse(shape.Solids)
        self.assertLessEqual(len(shape.Faces), 6)
        self.assertAlmostEqual(shape.Area, source.Area, delta=.01*source.Area)

    def test_convert_with_surfaces_reports_fitted_faces_and_keeps_the_source(self):
        source = mesh(filleted_box(), .1)
        before = fingerprint(source)
        result, report = convert(source, tolerance=.1, surfaces=True)
        self.check_solid(result, source, .1)
        self.assertTrue(report['smooth_surfaces'])
        self.assertEqual(report['faces'], len(result.Faces))
        self.assertEqual(report['fitted_smooth']+report['fitted_planes'], len(result.Faces))
        self.assertEqual(report['fitted_cylinders'], 0)
        self.assertLessEqual(report['max_fit_deviation'], .1)
        self.assertEqual(report['warnings'], [])
        self.assertEqual(fingerprint(source), before)

    def test_failed_fit_falls_back_to_flat_faces_with_a_warning(self):
        body = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(6, 20, App.Vector(20, 15, 0)))
        source = mesh(body)
        with mock.patch.object(mesh_surfaces, 'reconstruct', side_effect=ValueError('no fit')):
            result, report = convert(source, tolerance=.01, surfaces=True)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertGreaterEqual(report['analytic_holes'], 1)
        self.assertEqual(report['fitted_smooth']+report['fitted_planes'], 0)
        self.assertTrue(any('Smooth surfaces could not be fitted' in warning for warning in report['warnings']))

    def test_surfaces_flag_must_be_boolean(self):
        with self.assertRaises(ValueError):
            convert(mesh(Part.makeBox(1, 1, 1)), surfaces='yes')


if __name__ == '__main__':
    unittest.main()
