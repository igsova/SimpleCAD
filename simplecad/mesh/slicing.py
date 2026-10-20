"""Clip indexed STL triangles; triangulate only the newly exposed cut boundary."""
from dataclasses import dataclass
import math
import struct

import FreeCAD as App
import Mesh
import Part
import numpy as np

V = App.Vector
MAX_FACETS = 500000
AXES = {'X': V(1, 0, 0), 'Y': V(0, 1, 0), 'Z': V(0, 0, 1)}


def finite(value, name, low=-1e7, high=1e7):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('%s must be a finite number between %g and %g.' % (name, low, high))
    return float(value)


def normal_vector(value):
    try:
        if len(value) != 3:
            raise ValueError()
        vector = V(*(finite(v, 'Normal') for v in value))
    except (TypeError, ValueError):
        raise ValueError('Choose a nonzero three-component plane normal.')
    if vector.Length < 1e-10:
        raise ValueError('Choose a nonzero plane normal.')
    return vector / vector.Length


def main_axis(mesh):
    # Area-weighted surface covariance avoids bias from dense triangulation.
    points, faces = mesh.Topology
    triangles = np.asarray([tuple(p) for p in points], dtype=float)[np.asarray(faces)]
    triangles -= np.asarray(tuple(mesh.BoundBox.Center))
    areas = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)
    total = float(areas.sum())
    if total < 1e-12:
        raise ValueError('The mesh has no usable surface area.')
    sums = triangles.sum(axis=1)
    center = (areas[:, None]*sums/3).sum(axis=0)/total
    second = (np.einsum('n,nki,nkj->ij', areas, triangles, triangles)
              + np.einsum('n,ni,nj->ij', areas, sums, sums))/(12*total)
    values, vectors = np.linalg.eigh(second - np.outer(center, center))
    if values[-1] - values[-2] <= max(1e-10, abs(values[-1])*1e-8):
        local = mesh.copy(); local.Placement = App.Placement()
        box = local.BoundBox
        i = max(range(3), key=lambda k: (box.XLength, box.YLength, box.ZLength)[k])
        axis = mesh.Placement.Rotation.multVec(tuple(AXES.values())[i])
    else:
        axis = V(*map(float, vectors[:, -1]))
    index = max(range(3), key=lambda i: abs(tuple(axis)[i]))
    return axis if tuple(axis)[index] >= 0 else -axis


@dataclass
class Plane:
    normal: object
    center: object
    lower: float
    upper: float
    size: float

    def corners(self, offset):
        rotation = App.Rotation(V(0, 0, 1), self.normal)
        origin = self.center + self.normal * offset
        return [origin + rotation.multVec(V(x, y, 0)*(.6*self.size))
                for x, y in ((-1,-1), (1,-1), (1,1), (-1,1))]


def plane(mesh, axis='Main'):
    if not 0 < mesh.CountFacets <= MAX_FACETS:
        raise ValueError('Select a mesh with 1 to %d triangles.' % MAX_FACETS)
    if axis == 'Main':
        normal = main_axis(mesh)
    elif axis in AXES:
        normal = AXES[axis]
    elif axis in ('LocalX', 'LocalY', 'LocalZ'):
        normal = mesh.Placement.Rotation.multVec(AXES[axis[-1]])
    else:
        raise ValueError('Choose X, Y, Z, an object local axis, or its main axis.')
    center = mesh.BoundBox.Center
    levels = [(p-center).dot(normal) for p in mesh.Topology[0]]
    midpoint = (min(levels)+max(levels))/2
    center += normal * midpoint
    return Plane(normal, center, min(levels)-midpoint, max(levels)-midpoint, mesh.BoundBox.DiagonalLength)


def edge_counts(triangles):
    counts = {}
    for face in triangles:
        for a, b in zip(face, face[1:]+face[:1]):
            key = tuple(sorted((a, b)))
            counts[key] = counts.get(key, 0) + 1
    return counts


def cap_boundary(points, triangles, origin, normal, epsilon, original_open_edges=()):
    boundary = {edge for edge, count in edge_counts(triangles).items() if count == 1
                and all(abs((points[i]-origin).dot(normal)) <= epsilon for i in edge)}
    # An existing opening can itself lie in the cutting plane. It is not a new
    # cut and must remain open, even when another component crosses this plane.
    boundary.difference_update(original_open_edges)
    if not boundary:
        return []
    neighbors = {}
    for a, b in boundary:
        neighbors.setdefault(a, []).append(b); neighbors.setdefault(b, []).append(a)
    if any(len(adjacent) != 2 for adjacent in neighbors.values()):
        raise ValueError('The cut boundary branches or is open. Move the plane slightly, or disable Close cut surfaces for an open mesh split.')
    unused = set(boundary); loops = []
    while unused:
        first, current = next(iter(unused)); loop = [first, current]
        unused.remove(tuple(sorted((first, current))))
        while current != first:
            following = next((j for j in neighbors[current] if tuple(sorted((current, j))) in unused), None)
            if following is None:
                raise ValueError('The cut boundary could not be closed. Move the plane slightly.')
            unused.remove(tuple(sorted((current, following)))); loop.append(following); current = following
        loops.append(loop)
    # Only a temporary planar cap is triangulated in OCC. The STL body never
    # becomes Part geometry, and its untouched triangles are never remeshed.
    wires = [Part.makePolygon([points[i] - normal*((points[i]-origin).dot(normal)) for i in loop]) for loop in loops]
    surface = Part.makeFace(wires, 'Part::FaceMakerBullseye')
    if not surface.isValid():
        raise ValueError('The cut outline is self-intersecting. Move the plane slightly.')
    boundary_ids = set(neighbors)
    exact = {tuple(points[i] - normal*((points[i]-origin).dot(normal))):i for i in boundary_ids}
    caps = []
    for face in surface.Faces:
        if face.normalAt(0, 0).dot(normal) < 0:
            face.reverse()
        vertices, faces = face.tessellate(.01)
        indices = []
        for point in vertices:
            key = tuple(point)
            if key not in exact:
                # Prefer the nearest boundary point, never the first close one.
                nearest = min(boundary_ids, key=lambda i: (points[i]-point).Length)
                if (points[nearest]-point).Length <= epsilon:
                    exact[key] = nearest
                else:
                    exact[key] = len(points); points.append(point)
            indices.append(exact[key])
        caps.extend(tuple(indices[i] for i in face) for face in faces)
    # OCC can omit tiny collinear contour vertices. Reinsert them by splitting
    # cap triangles, retaining exactly the same edges as the clipped mesh.
    for _ in range(len(boundary)+1):
        cap_edges = edge_counts(caps)
        extra = [edge for edge, count in cap_edges.items() if count == 1 and edge not in boundary]
        if not extra:
            if {e for e,c in cap_edges.items() if c == 1} != boundary:
                raise ValueError('The cap did not preserve its boundary. Move the plane slightly.')
            return caps
        a, b = extra[0]
        chain = None
        direction = points[b]-points[a]
        length = direction.Length
        if length > 0:
            for following in neighbors.get(a, ()):
                trial = [a, following]; previous, current = a, following
                while current != b and len(trial) <= len(boundary):
                    if (points[current]-points[a]).cross(direction).Length/length > max(epsilon, max(abs(v) for v in points[current])*2e-7):
                        break
                    candidates = [i for i in neighbors[current] if i != previous]
                    if not candidates: break
                    previous, current = current, candidates[0]; trial.append(current)
                    if current == a: break
                if current == b:
                    chain = trial; break
        if chain is None:
            raise ValueError('The cap could not preserve tiny boundary edges. Move the plane slightly.')
        index = next(i for i, f in enumerate(caps) if a in f and b in f)
        face = caps.pop(index)
        other = next(i for i in face if i not in (a, b))
        if not any(x == a and y == b for x, y in zip(face, face[1:]+face[:1])):
            chain.reverse()
        caps.extend((x, y, other) for x, y in zip(chain, chain[1:]))
    raise ValueError('The cap triangulation did not converge.')


def split(mesh, origin, normal, cap=True, progress=lambda text: None, glue=None):
    if not 0 < mesh.CountFacets <= MAX_FACETS:
        raise ValueError('Select a mesh with 1 to %d triangles.' % MAX_FACETS)
    if not isinstance(cap, bool): raise ValueError('Close cut surfaces must be true or false.')
    origin = V(*(finite(v, 'Plane origin') for v in origin))
    normal = normal_vector(normal)
    if mesh.hasNonManifolds() or mesh.hasNonUniformOrientedFacets():
        raise ValueError('The mesh has non-manifold edges or inconsistent triangle directions. Repair it in Mesh Design first.')
    points, faces = mesh.Topology; points = list(points)
    delta = [(p-origin).dot(normal) for p in points]
    epsilon = max(1e-7, mesh.BoundBox.DiagonalLength*1e-9)
    if min(delta) >= -epsilon or max(delta) <= epsilon:
        raise ValueError('Place the cut plane inside the mesh so there is geometry on both sides.')
    closed = mesh.isSolid()
    if glue is not None:
        from . import glue as mesh_glue
        glue = mesh_glue.options(glue)
        if not closed or not cap:
            raise ValueError('A triangular glue seam needs a closed mesh and Close cut surfaces enabled.')
    original_open_edges = () if closed else {edge for edge, count in edge_counts(faces).items() if count == 1}
    sides = [[], []]; intersections = {}
    positions = {struct.pack('<fff', *p):i for i,p in enumerate(points)}
    def crossing(a, b):
        if abs(delta[a]) <= epsilon: return a
        if abs(delta[b]) <= epsilon: return b
        key = tuple(sorted((a, b)))
        if key not in intersections:
            point = points[a] + (points[b]-points[a]) * (delta[a]/(delta[a]-delta[b]))
            # Native meshes/STL use float32. Shared intersections that round to
            # the same stored point must share an index, avoiding zero edges.
            stored = struct.pack('<fff', *point)
            if stored not in positions:
                positions[stored] = len(points); points.append(point)
            intersections[key] = positions[stored]
        return intersections[key]
    progress('Splitting intersected triangles')
    for face in faces:
        if all(abs(delta[i]) <= epsilon for i in face):
            outward = (points[face[1]]-points[face[0]]).cross(points[face[2]]-points[face[0]])
            sides[0 if outward.dot(normal) >= 0 else 1].append(tuple(face))
            continue
        for index, sign in enumerate((-1, 1)):
            polygon = []
            for a, b in zip(face, face[1:]+face[:1]):
                inside_a, inside_b = sign*delta[a] >= -epsilon, sign*delta[b] >= -epsilon
                if inside_a: polygon.append(a)
                if inside_a != inside_b: polygon.append(crossing(a, b))
            polygon = list(dict.fromkeys(polygon))
            sides[index].extend((polygon[0], polygon[i], polygon[i+1]) for i in range(1,len(polygon)-1))
    results, glue_report = [], None
    if glue is not None:
        results, glue_report = mesh_glue.build(points, sides, origin, normal, epsilon, glue, progress)
    for side, triangles in (() if glue is not None else zip((-1,1), sides)):
        if not triangles: raise ValueError('The plane did not create two usable mesh sides.')
        if cap:
            progress('Closing new cut surfaces')
            triangles.extend(cap_boundary(points, triangles, origin, normal * -side, epsilon, original_open_edges))
        used = sorted({i for face in triangles for i in face})
        remap = {i:j for j,i in enumerate(used)}
        result = Mesh.Mesh(([points[i] for i in used], [tuple(remap[i] for i in face) for face in triangles]))
        if result.hasNonManifolds() or result.hasNonUniformOrientedFacets() or (cap and closed and not result.isSolid()):
            raise ValueError('The cut could not preserve a closed, consistent boundary. Move the plane slightly.')
        results.append(result)
    # Native mesh.Volume accumulates float32. Use translated double precision
    # tetrahedra for a meaningful conservation check, even far from the origin.
    def volume(value):
        ps, fs = value.Topology
        xyz = np.asarray([tuple(p-origin) for p in ps]); tri = xyz[np.asarray(fs)]
        return float(np.einsum('ij,ij->i', tri[:,0], np.cross(tri[:,1],tri[:,2])).sum()/6)
    if cap and closed:
        original_volume = abs(volume(mesh))
        removed = glue_report['removed_volume'] if glue_report else 0
        if abs(sum(abs(volume(m)) for m in results)-(original_volume-removed)) > max(.001, original_volume*1e-5):
            raise ValueError('The split did not preserve the enclosed volume. Move the plane slightly.')
    return results, {'triangles': mesh.CountFacets, 'pieces': [{'side': s, 'triangles': m.CountFacets, 'closed': m.isSolid()} for s,m in zip((-1,1),results)],
                     'capped': cap, 'glue': glue_report, 'warnings': [] if closed and cap else ['Open surfaces remain in the result.' if not closed else 'Cut surfaces are open because closing was disabled.']}
