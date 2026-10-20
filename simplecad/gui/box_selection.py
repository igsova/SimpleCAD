"""Directional box selection of native faces and edges in screen coordinates.

Face triangles keep holes and concave boundaries out of crossing selection.
No topology is changed, and a hit is never promoted to its entire Part object.
"""
import math

import FreeCAD as App
import Part
from pivy import coin

from ..core.geometry import EPS, seam_indices
from .snapping import screen
from ..document import visibility


def bounds(points):
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def inside(point, box):
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def overlaps(a, b):
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def segment_hits(a, b, box):
    """Clip a segment to the box, including exact edge/corner contact."""
    low, high = 0.0, 1.0
    for axis in (0, 1):
        delta = b[axis] - a[axis]
        if abs(delta) < 1e-12:
            if not box[axis] <= a[axis] <= box[axis + 2]:
                return False
        else:
            enter, leave = sorted(((box[axis] - a[axis]) / delta,
                                   (box[axis + 2] - a[axis]) / delta))
            low, high = max(low, enter), min(high, leave)
            if low > high:
                return False
    return True


def triangle_hits(points, box):
    if not overlaps(bounds(points), box):
        return False
    if any(segment_hits(points[i], points[(i + 1) % 3], box) for i in range(3)):
        return True
    # If the rectangle lies entirely inside a triangle, no edge crosses it.
    a, b, c = points
    cross = lambda p, q, r: (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    if abs(cross(a, b, c)) < 1e-12:
        return False
    p = (box[0], box[1])
    signs = (cross(a, b, p), cross(b, c, p), cross(c, a, p))
    return min(signs) >= 0 or max(signs) <= 0


def shape_hits(shape, project, box, crossing, deflection):
    """Use subpixel curve sampling, not the subshape's rectangular bounds."""
    if shape.ShapeType == "Face":
        vertices, triangles = shape.tessellate(deflection)
        points = [project(p) for p in vertices]
        if not points or any(p is None for p in points):
            return False
        if not crossing:
            return all(inside(p, box) for p in points)
        return any(triangle_hits([points[i] for i in triangle], box) for triangle in triangles)
    if shape.ShapeType == "Edge":
        vertices = shape.discretize(Deflection=deflection)
    else:
        vertices = [v.Point for v in shape.Vertexes]
    points = [project(p) for p in vertices]
    if not points or any(p is None for p in points):
        return False
    if not crossing:
        return all(inside(p, box) for p in points)
    return any(inside(p, box) for p in points) or any(
        segment_hits(a, b, box) for a, b in zip(points, points[1:]))


def box_selection(doc, view, start, end, show_seams=False, vertices=False):
    """Return (object, subelement) hits. Hidden objects are excluded.

    Like a selection volume, the box reaches through visible objects; it is
    not a pixel visibility test. Geometry behind a perspective camera is
    excluded. Sampling is rebuilt on release so no stale EdgeN/FaceN survives
    edits, zooms, or changed placements.
    """
    box, crossing = bounds((start, end)), end[0] < start[0]
    camera = view.getCameraNode()
    perspective = camera.isOfType(coin.SoPerspectiveCamera.getClassTypeId())
    eye = App.Vector(*camera.position.getValue())
    forward = view.getViewDirection()

    cache = {}

    def project(point):
        key = (round(point.x, 7), round(point.y, 7), round(point.z, 7))
        if key in cache:
            return cache[key]
        if perspective and (point - eye).dot(forward) <= EPS:
            cache[key] = None
            return None
        value = screen(view, point)
        res = value if all(math.isfinite(v) for v in value) else None
        cache[key] = res
        return res

    def box_2d_bounds(bb):
        corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax)
                   for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
        projected = [project(p) for p in corners]
        if any(p is None for p in projected):
            return None
        return bounds(projected)

    def edge_2d_bounds(edge):
        if len(edge.Vertexes) == 2 and isinstance(getattr(edge, 'Curve', None), Part.Line):
            p1, p2 = project(edge.Vertexes[0].Point), project(edge.Vertexes[1].Point)
            if p1 is None or p2 is None:
                return None
            return bounds((p1, p2))
        return box_2d_bounds(edge.BoundBox)

    result = []
    for obj in doc.Objects:
        if not obj.isDerivedFrom("Part::Feature") or not obj.ViewObject.Visibility:
            continue
        if not obj.ViewObject.Selectable or not obj.ViewObject.isVisible():
            continue
        shape = obj.Shape
        if shape.isNull():
            continue
        hidden = visibility.hidden_faces(obj)
        hidden_edges, hidden_vertices = visibility.hidden_elements(shape, hidden)
        placement = obj.getGlobalPlacement()
        if shape.Placement.Matrix.A != placement.Matrix.A:
            shape = shape.copy()
            shape.Placement = placement
        # Approximate half a display pixel at this object's depth. Perspective
        # uses its nearest bounding corner to avoid coarse foreground curves.
        bb = shape.BoundBox
        obj_bounds = box_2d_bounds(bb)
        if obj_bounds is not None and not overlaps(obj_bounds, box):
            continue
        corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax)
                   for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
        right = App.Vector(*camera.orientation.getValue().multVec(coin.SbVec3f(1, 0, 0)).getValue())
        scale = 0.0
        step = max(bb.DiagonalLength / 10, EPS * 10)
        for point in corners:
            a, b = project(point), project(point + right * step)
            if a is not None and b is not None:
                scale = max(scale, math.hypot(a[0] - b[0], a[1] - b[1]) / step)
        deflection = max(EPS * 10, min(.25 / max(scale, 1e-6), max(bb.DiagonalLength, 1) / 100))
        for index, face in enumerate(shape.Faces, 1):
            if index in hidden:
                continue
            fb = box_2d_bounds(face.BoundBox)
            if fb is not None:
                if not overlaps(fb, box):
                    continue
                if not crossing and fb[0] >= box[0] and fb[1] >= box[1] and fb[2] <= box[2] and fb[3] <= box[3]:
                    result.append((obj, "Face" + str(index)))
                    continue
            if shape_hits(face, project, box, crossing, deflection):
                result.append((obj, "Face" + str(index)))
        candidate_edges = []
        for index, edge in enumerate(shape.Edges, 1):
            if index in hidden_edges:
                continue
            eb = edge_2d_bounds(edge)
            if eb is not None:
                if not overlaps(eb, box):
                    continue
                if not crossing and eb[0] >= box[0] and eb[1] >= box[1] and eb[2] <= box[2] and eb[3] <= box[3]:
                    candidate_edges.append((index, edge))
                    continue
            if shape_hits(edge, project, box, crossing, deflection):
                candidate_edges.append((index, edge))
        if candidate_edges:
            seams = set() if show_seams else seam_indices(shape, [idx - 1 for idx, _ in candidate_edges])
            for index, edge in candidate_edges:
                if index - 1 not in seams:
                    result.append((obj, "Edge" + str(index)))
        if vertices or not shape.Edges:
            for index, vertex in enumerate(shape.Vertexes, 1):
                if index in hidden_vertices:
                    continue
                if shape_hits(vertex, project, box, crossing, deflection):
                    result.append((obj, "Vertex" + str(index)))
    return result
