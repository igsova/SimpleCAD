"""Exercise the stretch/native-mesh handoff without loading FreeCAD's Qt runtime."""
from collections import Counter
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

import numpy as np
from test_mesh_transform import box_with_collinear_facet, volume


class Vector(tuple):
    """Distinct native-vector stand-in; ordinary lists/tuples are not accepted."""
    def __new__(cls, x, y, z):
        return super().__new__(cls,(float(x),float(y),float(z)))


class StrictMesh:
    """Enforce both native vectors and index tuples required by FreeCAD."""
    def __init__(self, topology):
        points, faces = topology
        if any(type(point) is not Vector for point in points):
            raise TypeError('Native indexed Mesh requires FreeCAD.Vector points.')
        for face in faces:
            if type(face) is not tuple or len(face) != 3 or any(type(i) is not int for i in face):
                raise TypeError('Native Mesh requires triangle tuples of Python integers.')
        self.Topology = points, faces
        self.CountFacets = len(faces)
        self.directed = Counter((a,b) for a,b,c in faces for a,b in ((a,b),(b,c),(c,a)))
        self.edges = Counter(tuple(sorted(e)) for e in self.directed.elements())

    def hasNonManifolds(self):
        return any(n > 2 for n in self.edges.values())

    def hasNonUniformOrientedFacets(self):
        return any(n > 1 for n in self.directed.values())

    def isSolid(self):
        return all(n == 2 for n in self.edges.values())


def adapter():
    modules = {
        'FreeCAD': NS(Vector=Vector), 'Mesh': NS(Mesh=StrictMesh),
        'simplecad.mesh.conversion': NS(is_mesh=lambda obj: True),
        'simplecad.document.locking': NS(), 'simplecad.mesh.slicing': NS(),
    }
    path = Path(__file__).resolve().parents[2]/'simplecad/mesh/stretch.py'
    spec = importlib.util.spec_from_file_location('simplecad.mesh._stretch_adapter_test',path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,modules):
        spec.loader.exec_module(module)
    return module


class StretchAdapterTests(unittest.TestCase):
    def test_40_mm_stretch_reaches_native_mesh_with_valid_index_types(self):
        points, faces = box_with_collinear_facet()
        source = StrictMesh(([Vector(*p) for p in points.tolist()],list(map(tuple,faces.tolist()))))
        original_points = points.copy()
        result,report = adapter().stretch(source,(0,0,0),(0,0,1),3,7,(0,0,40))
        xyz, triangles = map(np.asarray,result.Topology)
        self.assertAlmostEqual(volume(xyz,triangles),5000)
        self.assertEqual(np.ptp(xyz[:,2]),50)
        self.assertTrue(result.isSolid())
        self.assertFalse(result.hasNonManifolds())
        self.assertFalse(result.hasNonUniformOrientedFacets())
        self.assertEqual(report['triangles'],len(triangles))
        self.assertEqual(report['degenerate_triangles_before'],1)
        np.testing.assert_array_equal(np.asarray(source.Topology[0]),original_points)


if __name__ == '__main__': unittest.main()
