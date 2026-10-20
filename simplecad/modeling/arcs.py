"""Analytic circular arcs and inexpensive viewport samples. Angles are degrees."""
import math
from dataclasses import dataclass
import Part
from ..core.geometry import V, EPS, unit


def finite_vector(value):
    if not all(math.isfinite(c) for c in (value.x, value.y, value.z)):
        raise ValueError('Arc coordinates must be finite.')
    return V(value)


@dataclass
class Arc:
    center: object
    radial: object
    normal: object
    sweep: float

    def point(self, fraction):
        angle = math.radians(self.sweep) * fraction
        return self.center + self.radial * math.cos(angle) + self.normal.cross(self.radial) * math.sin(angle)

    def points(self):
        count = max(8, int(abs(self.sweep) / 3) + 1)
        return [self.point(i / count) for i in range(count + 1)]

    def edge(self):
        edge = Part.Arc(self.point(0), self.point(.5), self.point(1)).toShape()
        if not edge.isValid():
            raise ValueError('This arc could not be created. Increase its size or sweep.')
        return edge


def centered(center, start, normal, sweep):
    center, start, normal = map(finite_vector, (center, start, normal))
    normal = unit(normal)
    radial = start - center
    if radial.Length < EPS:
        raise ValueError('Arc needs a positive radius.')
    if abs(radial.dot(normal)) > EPS:
        raise ValueError('Arc start must lie on its drawing plane.')
    if isinstance(sweep, bool) or not math.isfinite(sweep) or not 1e-5 < abs(sweep) < 359.99999:
        raise ValueError('Arc sweep must be between -360 and 360 degrees, excluding zero and full circles.')
    return Arc(center, radial, normal, sweep)


def two_point(start, end, normal, bulge):
    start, end, normal = map(finite_vector, (start, end, normal))
    normal = unit(normal)
    chord = end - start
    if chord.Length < EPS:
        raise ValueError('Choose two different arc endpoints.')
    if abs(chord.dot(normal)) > EPS:
        raise ValueError('Arc endpoints must lie on the same drawing plane.')
    if isinstance(bulge, bool) or not math.isfinite(bulge) or abs(bulge) < EPS:
        raise ValueError('Arc needs a nonzero bulge.')
    left = normal.cross(unit(chord))
    half = chord.Length / 2
    center = (start + end) * .5 + left * ((bulge * bulge - half * half) / (2 * bulge))
    # Positive bulge lies to the left of the chord; the arc travels clockwise.
    sweep = -math.degrees(4 * math.atan(bulge / half))
    return centered(center, start, normal, sweep)


def completions(shapes, newest, loose=None):
    """Close a simple planar arc/line loop using loose edges, without filling solids.

    Find the shortest endpoint-connected path back to the new edge's start.
    Face partitions and intersections are handled by the regular drawing path.
    """
    from collections import deque
    from ..core import coincident as coinc
    edges = list(loose) if loose is not None else [edge for shape in shapes for edge in coinc.loose_edges(shape)]
    # Collapsed surface edges (e.g. sphere poles) have no 3D Curve and cannot
    # take part in an endpoint-connected drawing loop.
    edges = [edge for edge in edges if not edge.Degenerated
             and len(edge.Vertexes) == 2 and edge.Length > EPS]
    if not isinstance(newest.Curve, Part.Circle) and not any(isinstance(e.Curve, Part.Circle) for e in edges):
        return []
    edges = coinc.unique([edge for edge in edges if not coinc.same(edge, newest)])
    start, end = [v.Point for v in newest.Vertexes]
    queue = deque([(end, [], isinstance(newest.Curve, Part.Circle))])
    visited = set()
    while queue:
        point, path, curved = queue.popleft()
        for index, edge in enumerate(edges):
            if index in path:
                continue
            a, b = [v.Point for v in edge.Vertexes]
            other = b if (a - point).Length < EPS else a if (b - point).Length < EPS else None
            if other is None:
                continue
            has_arc = curved or isinstance(edge.Curve, Part.Circle)
            route = path + [index]
            if has_arc and (other - start).Length < EPS:
                try:
                    face = Part.Face(Part.Wire([newest] + [edges[i] for i in route]))
                    if not isinstance(face.Surface, Part.Plane) or not face.isValid() or face.Area < EPS:
                        continue
                    if any(shape.Faces and shape.common(face).Area > EPS for shape in shapes):
                        continue
                    return [face]
                except (Part.OCCError, ValueError):
                    continue
            key = (index, (other - a).Length < EPS, has_arc)
            if key not in visited:
                visited.add(key)
                queue.append((other, route, has_arc))
    return []
