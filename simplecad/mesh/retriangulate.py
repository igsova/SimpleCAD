"""Repair folded diagonals on flat mesh surfaces without moving vertices.

An STL's fan around a hole need not stay a valid triangulation when an outer
corner moves. Flip only internal diagonals whose two replacement triangles
both have positive area. Boundaries (including holes), selected faces, sharp
edges, nonplanar surfaces and pre-existing degenerate facets are protected.
This is not a collision repair: the native checks still validate the result.
"""
from collections import deque
import numpy as np
from .transform import MIN_DOUBLE_AREA

# Eligibility for a local planar diagonal change, in mm. This does not change
# the area, solid, or self-intersection validation tolerances. Allow the small
# coordinate noise of STL float32 vertices on otherwise flat surfaces.
PLANE_TOLERANCE = 1e-6


class _EdgeFaces:
    """Mutable edge -> triangles lookup, copied from the topology on first use.

    Only edges near folded triangles are touched, so the whole-mesh edge map
    is never rebuilt for a preview.
    """
    def __init__(self, topology):
        self.topology, self.changed = topology, {}

    def __getitem__(self, edge):
        a,b = int(edge[0]),int(edge[1]); key = (min(a,b),max(a,b))
        found = self.changed.get(key)
        if found is None:
            found = self.changed[key] = set(self.topology.edge_faces(a,b))
        return found


def planar_diagonals(topology, moved, selected):
    original = topology.triangles
    samples = moved[original]
    crosses = np.cross(samples[:,1]-samples[:,0], samples[:,2]-samples[:,0])
    signed = np.einsum('ij,ij->i', crosses, topology.normals)
    bad = (signed <= MIN_DOUBLE_AREA) & (topology.areas > MIN_DOUBLE_AREA)
    bad[selected] = False
    if not bad.any():
        return original
    planar = np.max(abs(np.einsum('ijk,ik->ij',
        samples-topology.centers[:,None,:], topology.normals)), axis=1) <= PLANE_TOLERANCE
    planar &= topology.areas > MIN_DOUBLE_AREA
    planar[selected] = False
    queue = deque(np.flatnonzero(bad & planar).tolist())
    if not queue:
        return original
    faces = original.copy()
    edges = _EdgeFaces(topology)
    flips = 0
    while queue and flips < 1000:
        i = queue.popleft()
        if signed[i] > MIN_DOUBLE_AREA:
            continue
        normal = topology.normals[i]
        for e in range(3):
            a,b,c = map(int, faces[i][[e,(e+1)%3,(e+2)%3]])
            neighbors = edges[a,b] - {i}
            if len(neighbors) != 1:
                continue
            j = next(iter(neighbors))
            if not planar[j] or normal @ topology.normals[j] < 1-1e-10:
                continue
            # The common edge must be consistently oriented in both facets.
            other = faces[j].tolist()
            if (b not in other or other[(other.index(b)+1)%3] != a):
                continue
            d = next(v for v in other if v not in (a,b))
            if edges[c,d]:
                continue
            vertices = [a,b,c,d]
            # Use current connectivity with the original vertex coordinates:
            # an earlier flip may have replaced this neighbor with a much
            # larger triangle. Its old cached normal can miss STL coordinate
            # noise over the new span and block the next necessary flip.
            source = topology.points[faces[[i,j]]]
            source_cross = np.cross(source[:,1]-source[:,0],source[:,2]-source[:,0])
            source_area = np.linalg.norm(source_cross,axis=1)
            reference = int(np.argmax(source_area))
            if source_area[reference] <= MIN_DOUBLE_AREA:
                continue
            plane_normal = source_cross[reference]/source_area[reference]
            center = source[reference].mean(axis=0)
            if (np.max(abs((topology.points[vertices]-center) @ plane_normal)) > PLANE_TOLERANCE
                    or np.max(abs((moved[vertices]-center) @ plane_normal)) > PLANE_TOLERANCE):
                continue
            replacement = np.asarray(((c,d,b),(d,c,a)), dtype=np.int64)
            p = moved[replacement]
            area = np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]) @ normal
            if np.min(area) <= MIN_DOUBLE_AREA:
                continue
            for k in (i,j):
                for u,v in zip(faces[k],np.roll(faces[k],-1)):
                    edges[u,v].remove(k)
            for k,face in zip((i,j),replacement):
                faces[k] = face
                for u,v in zip(face,np.roll(face,-1)):
                    edges[u,v].add(k)
            signed[[i,j]] = area
            flips += 1
            # A previously blocked folded triangle may now have a usable
            # adjacent diagonal. Each accepted flip removes at least one fold.
            for face in replacement:
                for u,v in zip(face,np.roll(face,-1)):
                    queue.extend(k for k in edges[u,v]
                                 if planar[k] and signed[k] <= MIN_DOUBLE_AREA)
            break
    return faces if flips else original
