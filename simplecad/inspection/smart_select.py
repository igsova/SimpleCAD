"""Grow a picked face or edge into a whole hole, loop, flat region or smooth surface.

Nothing here changes a shape; each function returns FaceN/EdgeN names for
the selection. A converted part is made of thousands of triangles, so the
growth runs on an edge-to-face adjacency listed once per shape.
"""
import math

import Part

from ..core import geometry as geo

FLAT_ANGLE = .5      # degrees between normals within one flat region
SMOOTH_ANGLE = 30.0  # degrees between neighbours across a smooth surface's edges

_adjacencies = []


class Adjacency:
    """A shape's faces and which faces share each edge."""
    def __init__(self, shape):
        self.shape = shape
        self.faces = shape.Faces
        self.face_edges = [face.Edges for face in self.faces]
        self.owners = {}
        for i, edges in enumerate(self.face_edges):
            for edge in edges:
                self.owners.setdefault(hash(edge), []).append(i)
        self.positions = {}
        for i, face in enumerate(self.faces):
            self.positions.setdefault(hash(face), []).append(i)
        self._edges = None

    def neighbours(self, i):
        """(face index, shared edge) of every face sharing an edge with face i."""
        for edge in self.face_edges[i]:
            for j in self.owners.get(hash(edge), ()):
                if j != i and any(edge.isSame(other) for other in self.face_edges[j]):
                    yield j, edge

    def index_of(self, face):
        return next((i for i in self.positions.get(hash(face), ()) if self.faces[i].isSame(face)), None)

    def faces_of(self, edge):
        return [i for i in self.owners.get(hash(edge), ()) if any(edge.isSame(e) for e in self.face_edges[i])]

    def edge_name(self, edge):
        if self._edges is None:
            self._edges = {}
            for i, known in enumerate(self.shape.Edges, 1):
                self._edges.setdefault(hash(known), []).append((i, known))
        return next(('Edge%d' % i for i, known in self._edges.get(hash(edge), ()) if known.isSame(edge)), None)


def adjacency(shape):
    """The shape's adjacency, listed once and reused while the shape is unchanged."""
    for known in _adjacencies:
        if known.shape.isSame(shape):
            return known
    known = Adjacency(shape)
    _adjacencies.insert(0, known)
    del _adjacencies[4:]
    return known


def normal_at(face, point):
    """The face's outward normal at a point on it."""
    if isinstance(face.Surface, Part.Plane):
        return geo.face_normal(face)
    u, v = face.Surface.parameter(point)
    return geo.unit(face.normalAt(u, v))


def grow(adj, seed, accept):
    """Faces reachable from the seed across edges that accept(face, neighbour, edge)."""
    region, queue = {seed}, [seed]
    while queue:
        current = queue.pop()
        for j, edge in adj.neighbours(current):
            if j not in region and accept(current, j, edge):
                region.add(j)
                queue.append(j)
    return sorted(region)


def flat_region(adj, seed, tolerance):
    """Connected faces on the seed's plane, such as a flat area of mesh triangles."""
    face = adj.faces[seed]
    if not isinstance(face.Surface, Part.Plane):
        return [seed]
    normal, origin = geo.face_normal(face), face.CenterOfMass
    limit = math.cos(math.radians(FLAT_ANGLE))

    def accept(_, j, __):
        other = adj.faces[j]
        return (isinstance(other.Surface, Part.Plane) and geo.face_normal(other).dot(normal) >= limit
                and abs((other.CenterOfMass - origin).dot(normal)) <= tolerance)
    return grow(adj, seed, accept)


def smooth_surface(adj, seed, angle=SMOOTH_ANGLE):
    """Connected faces meeting at gentle creases: a faceted fillet or a tangent chain."""
    limit = math.cos(math.radians(angle))

    def accept(i, j, edge):
        middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
        try:
            return normal_at(adj.faces[i], middle).dot(normal_at(adj.faces[j], middle)) >= limit
        except (Part.OCCError, RuntimeError, ValueError):
            return False
    return grow(adj, seed, accept)


def cylinder_wall(adj, seed):
    """The connected faces of one analytic cylinder: a hole or a boss."""
    surface = adj.faces[seed].Surface
    axis, center, radius = geo.unit(surface.Axis), surface.Center, surface.Radius

    def accept(_, j, __):
        other = adj.faces[j].Surface
        if not isinstance(other, Part.Cylinder) or abs(other.Radius - radius) > 1e-6:
            return False
        offset = other.Center - center
        return (abs(abs(geo.unit(other.Axis).dot(axis)) - 1) < 1e-9
                and (offset - axis * offset.dot(axis)).Length < 1e-6)
    return grow(adj, seed, accept)


def hole(adj, seed):
    """The wall faces of the hole or cylinder a face belongs to, or None."""
    face = adj.faces[seed]
    if isinstance(face.Surface, Part.Cylinder):
        return cylinder_wall(adj, seed)
    if isinstance(face.Surface, Part.Plane):
        from .measuring import faceted_wall
        found = faceted_wall(adj.shape, face)
        if found is not None:
            indices = [adj.index_of(wall) for wall in found[1]]
            return sorted(i for i in indices if i is not None)
    return None


def hole_of_edge(adj, edge):
    """The wall of the hole whose rim an edge is part of, or None."""
    from .measuring import _faceted_loop
    try:
        curve = edge.Curve
    except (TypeError, RuntimeError, Part.OCCError):
        return None
    for i in adj.faces_of(edge):
        face = adj.faces[i]
        if isinstance(curve, (Part.Circle, Part.ArcOfCircle)) and isinstance(face.Surface, Part.Cylinder):
            return cylinder_wall(adj, i)
    if isinstance(curve, Part.Line):
        fit, wall = _faceted_loop(adj.shape, edge)
        if fit is not None and wall is not None:
            index = adj.index_of(wall)
            if index is not None:
                return hole(adj, index)
    return None


def loop(adj, edge, view_direction=None):
    """The edges of the loop an edge lies on.

    Of the loops through the edge, one on a flat face with a round loop wins,
    then the face turned most toward the viewer.
    """
    candidates = []
    for i in adj.faces_of(edge):
        face = adj.faces[i]
        for wire in face.Wires:
            if any(edge.isSame(e) for e in wire.Edges):
                flat = isinstance(face.Surface, Part.Plane)
                facing = abs(geo.face_normal(face).dot(view_direction)) if flat and view_direction is not None else 0
                candidates.append((flat and len(wire.Edges) >= 8, facing, -len(wire.Edges), wire))
    if not candidates:
        return [edge]
    return max(candidates, key=lambda item: item[:3])[3].Edges


def names(adj, faces=(), edges=()):
    result = ['Face%d' % (i + 1) for i in faces]
    result += [name for name in (adj.edge_name(e) for e in edges) if name]
    return result


def expand(shape, name, mode='smart', view_direction=None, tolerance=None):
    """Names the picked element grows into, and what it grew into.

    Modes: 'hole', 'loop', 'flat', 'smooth', or 'smart', which picks the
    likely one: a hole wall or rim selects the hole, another edge its loop,
    a flat face its flat region and a curved face its smooth surface.
    """
    if tolerance is None:
        from ..core.preferences import precision
        tolerance = precision() * .1
    element = shape.getElement(name)
    adj = adjacency(shape)
    if element.ShapeType == 'Edge':
        if mode in ('hole', 'smart'):
            wall = hole_of_edge(adj, element)
            if wall:
                return names(adj, wall), 'hole'
            if mode == 'hole':
                raise ValueError('That edge is not the rim of a hole or cylinder.')
        if mode in ('loop', 'smart'):
            return names(adj, edges=loop(adj, element, view_direction)), 'loop'
        seeds = adj.faces_of(element)
        if not seeds:
            raise ValueError('That edge belongs to no face.')
        element, seed = adj.faces[seeds[0]], seeds[0]
    elif element.ShapeType == 'Face':
        seed = adj.index_of(element)
        if seed is None:
            raise ValueError('That face is not part of this shape.')
    else:
        raise ValueError('Pick a face or an edge.')
    if mode == 'loop':
        return names(adj, edges=[e for wire in element.Wires for e in wire.Edges]), 'loop'
    if mode in ('hole', 'smart'):
        wall = hole(adj, seed)
        if wall:
            return names(adj, wall), 'hole'
        if mode == 'hole':
            raise ValueError('That face is not part of a hole or cylinder wall.')
    if mode == 'flat' or (mode == 'smart' and isinstance(element.Surface, Part.Plane)):
        return names(adj, flat_region(adj, seed, tolerance)), 'flat'
    return names(adj, smooth_surface(adj, seed)), 'smooth'
