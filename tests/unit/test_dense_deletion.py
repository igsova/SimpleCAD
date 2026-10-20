"""Local deletion on a reproducible triangulated solid with over 2,000 faces."""
import unittest
import FreeCAD as App
import Part
from simplecad.core import geometry as g
from simplecad.modeling import drawing


def dense_box(n=14):
    faces = []
    for side in Part.makeBox(n, n, n).Faces:
        u0, u1, v0, v1 = side.ParameterRange
        for i in range(n):
            for j in range(n):
                a, b, c, d = [side.valueAt(u0+(u1-u0)*x/n, v0+(v1-v0)*y/n)
                              for x, y in ((i,j), (i+1,j), (i+1,j+1), (i,j+1))]
                for points in ((a,b,c,a), (a,c,d,a)):
                    face = Part.Face(Part.makePolygon(points))
                    if g.face_normal(face).dot(g.face_normal(side)) < 0:
                        face.reverse()
                    faces.append(face)
    shell = Part.makeShell(faces)
    shell.sewShape()
    return Part.makeSolid(shell)


def diagonal(shape):
    return next('Edge%d' % i for i, edge in enumerate(shape.Edges, 1)
                if abs(edge.Length - 2**.5) < 1e-7)


class DenseDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = dense_box()

    def test_merge_preserves_source_and_unedited_native_faces(self):
        shape = self.box.copy()
        shape.Placement = App.Placement(App.Vector(30,40,50), App.Rotation(App.Vector(1,2,3), 37))
        self.assertTrue(shape.isValid())
        source = shape.exportBrepToString()
        old_faces = shape.Faces
        name = diagonal(shape)
        adjacent = shape.ancestorsOfType(shape.getElement(name), Part.Face)
        result = g.erase_elements(shape, [name])
        self.assertEqual(shape.exportBrepToString(), source)
        self.assertEqual(len(result.Faces), 2351)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, shape.Volume)
        self.assertAlmostEqual(result.Area, shape.Area)
        self.assertLess((result.CenterOfMass-shape.CenterOfMass).Length, 1e-7)
        retained = {}
        for face in result.Faces:
            retained.setdefault(hash(face), []).append(face)
        for face in old_faces:
            if not any(face.isSame(other) for other in adjacent):
                self.assertTrue(any(face.isSame(other) for other in retained.get(hash(face), ())))

    def test_open_shell_merge_and_redraw_keep_hole_and_other_divisions(self):
        shape = Part.makeShell(self.box.Faces[2:])
        name = diagonal(shape)
        edge = shape.getElement(name)
        source = shape.exportBrepToString()
        merged = g.erase_elements(shape, [name])
        self.assertEqual(len(merged.Faces), len(shape.Faces)-1)
        self.assertAlmostEqual(merged.Area, shape.Area)
        result, _ = g.divide_face_with_edges(merged, edge)
        self.assertEqual(len(result.Faces), len(shape.Faces))
        self.assertTrue(result.isValid())
        self.assertFalse(result.isClosed())
        self.assertEqual(len(result.Solids), 0)
        self.assertAlmostEqual(result.Area, shape.Area)
        self.assertEqual(source, shape.exportBrepToString())
        self.assertLess((result.CenterOfMass-shape.CenterOfMass).Length, 1e-7)

    def test_patch_closes_dense_shell_without_changing_other_regions(self):
        shape = Part.makeShell(self.box.Faces[1:])
        source = shape.exportBrepToString()
        result = drawing.attach_triangles(shape, [self.box.Faces[0]])
        self.assertIsNotNone(result)
        self.assertTrue(result.isValid() and result.isClosed())
        self.assertEqual(len(result.Faces), len(self.box.Faces))
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, self.box.Volume)
        self.assertAlmostEqual(result.Area, self.box.Area)
        self.assertEqual(source, shape.exportBrepToString())

    def test_mid_edge_divider_reconnects_neighboring_shell_faces(self):
        for reverse in (False, True):
            shape = Part.makeShell(Part.makeBox(10, 12, 8).Faces[1:])
            if reverse:
                shape.reverse()
            shape.Placement = App.Placement(App.Vector(30,40,50), App.Rotation(App.Vector(1,2,3), 37))
            face = shape.Faces[0]
            points = [e.CenterOfMass for e in face.OuterWire.OrderedEdges[::2]]
            original = shape.exportBrepToString()
            result, boundary = g.divide_face_with_edges(shape, Part.makeLine(*points))
            self.assertEqual(len(result.Faces), len(shape.Faces)+1)
            self.assertTrue(result.isValid())
            self.assertFalse(result.isClosed())
            self.assertAlmostEqual(result.Area, shape.Area)
            self.assertEqual(original, shape.exportBrepToString())
            for edge in boundary.Edges:
                self.assertEqual(len(result.ancestorsOfType(edge, Part.Face)), 2)
