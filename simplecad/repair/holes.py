"""Rebuild holes whose wall fell apart into strips and slivers.

Cutting an analytic cylinder into a faceted hole whose axis is off by
micro-radians leaves the wall as many cylinder strips joined by zero-width
facet remnants, and the rims as chains of ellipse arcs and zero-length
edges. The carrying faces become invalid and FreeCAD draws them straight
across the hole. Such a hole is rebuilt as the single cylinder it was meant
to be: one wall face between two exact circles on its flat rim faces.
"""
import math

import FreeCAD as App
import Part

V = App.Vector


def _basis(axis):
    helper = V(1, 0, 0) if abs(axis.x) < .9 else V(0, 1, 0)
    u = axis.cross(helper)
    u.normalize()
    return u, axis.cross(u)


def _snap(axis, extent, tolerance):
    """The nearest world axis when tilting to it moves no point by more than the tolerance."""
    index = max(range(3), key=lambda i: abs(axis[i]))
    world = V(*[(1.0 if axis[index] > 0 else -1.0) if i == index else 0.0 for i in range(3)])
    return world if math.acos(min(1.0, abs(axis.dot(world)))) * max(extent, tolerance) <= tolerance else axis


def _groups(shape, tolerance):
    """Cylinder faces grouped by the hole they belong to."""
    groups = []
    for index, face in enumerate(shape.Faces):
        surface = face.Surface
        if not isinstance(surface, Part.Cylinder):
            continue
        axis = V(surface.Axis)
        for group in groups:
            offset = surface.Center - group['center']
            if (abs(abs(axis.dot(group['axis'])) - 1) < 1e-6
                    and abs(surface.Radius - group['radius']) <= tolerance * .1
                    and (offset - group['axis'] * offset.dot(group['axis'])).Length <= tolerance * .1):
                group['faces'].append(index)
                break
        else:
            groups.append({'axis': axis, 'center': V(surface.Center), 'radius': surface.Radius, 'faces': [index]})
    return groups


def rebuild_fragmented(shape, tolerance):
    """Return (shape, rebuilt hole count); holes that cannot be rebuilt are kept."""
    count = 0
    for _ in range(64):
        for group in _groups(shape, tolerance):
            try:
                candidate = _rebuild(shape, group, tolerance)
            except (ValueError, RuntimeError, Part.OCCError):
                continue
            if candidate is not None:
                shape, count = candidate, count + 1
                break
        else:
            return shape, count
    return shape, count


def _rebuild(shape, group, tolerance):
    faces = shape.Faces
    near = max(tolerance * .2, 1e-3)
    extent = shape.BoundBox.DiagonalLength
    axis = _snap(group['axis'], extent, tolerance)
    radius = group['radius']
    center = group['center']
    u, v = _basis(axis)

    def polar(point):
        offset = point - center
        return math.hypot(offset.dot(u), offset.dot(v)), offset.dot(axis)

    heights = [polar(vertex.Point)[1] for i in group['faces'] for vertex in faces[i].Vertexes]
    low, high = min(heights) - near, max(heights) + near

    def on_rim(point):
        rho, height = polar(point)
        return abs(rho - radius) <= near and low <= height <= high

    wall = {i for i, face in enumerate(faces)
            if face.Vertexes and all(on_rim(vertex.Point) for vertex in face.Vertexes)}
    if not set(group['faces']) <= wall:
        return None
    # Only a wall that fell apart is rebuilt; one clean cylinder face is left
    # alone. A rim split by a hairline arc counts as fallen apart: meshed, the
    # hairline collapses and leaves non-manifold edges a slicer reports.
    if (len(group['faces']) < 2 and not any(faces[i].Area < tolerance ** 2 for i in wall)
            and not any(edge.Length < tolerance * .01 for i in wall for edge in faces[i].Edges)):
        return None
    wall_edges = [edge for i in wall for edge in faces[i].Edges]
    rims = [i for i, face in enumerate(faces) if i not in wall
            and any(edge.isSame(other) for edge in face.Edges for other in wall_edges)]
    levels = {}
    for i in rims:
        face = faces[i]
        if not isinstance(face.Surface, Part.Plane) or abs(abs(V(face.Surface.Axis).dot(axis)) - 1) > 1e-6 * extent:
            raise ValueError('A hole rim is not on a flat face square to the hole.')
        level = (face.Surface.Position - center).dot(axis)
        side = 'low' if abs(level - low) <= abs(level - high) else 'high'
        if side in levels:
            raise ValueError('A hole rim is split across several faces.')
        levels[side] = (i, level)
    if set(levels) != {'low', 'high'}:
        raise ValueError('Only through-holes between two flat faces are rebuilt.')
    (low_face, low_level), (high_face, high_level) = levels['low'], levels['high']
    base = center + axis * low_level
    height = high_level - low_level
    if height <= near:
        raise ValueError('The hole has no length.')
    cylinder = Part.makeCylinder(radius, height, base, axis)
    wall_face = next(face for face in cylinder.Faces if isinstance(face.Surface, Part.Cylinder))
    circles = {}
    for edge in wall_face.Edges:
        if isinstance(edge.Curve, Part.Circle):
            circles['low' if abs((edge.Curve.Center - base).dot(axis)) < near else 'high'] = edge

    def rebuild_rim(index, circle):
        face = faces[index]
        plane_level = (face.Surface.Position - center).dot(axis)
        keep, dropped = [], 0
        for wire in face.Wires:
            points = [vertex.Point for vertex in wire.Vertexes]
            inside = [on_rim(point) and abs(polar(point)[1] - plane_level) <= near for point in points]
            if all(inside):
                if wire.isSame(face.OuterWire):
                    raise ValueError('The rim is the outline of its face.')
                dropped += 1
            elif any(inside):
                raise ValueError('The hole breaks through the edge of its face.')
            else:
                keep.append(wire)
        if not dropped:
            raise ValueError('The rim loop was not found on its face.')
        ring = Part.Wire([circle])
        best = None
        for candidate_ring in (ring, ring.reversed()):
            try:
                rebuilt = Part.Face(face.Surface, keep + [candidate_ring])
            except Part.OCCError:
                continue
            rebuilt.validate()
            if rebuilt.isValid() and len(rebuilt.Wires) == len(keep) + 1:
                best = rebuilt if best is None or abs(rebuilt.Area - face.Area) < abs(best.Area - face.Area) else best
        if best is None:
            raise ValueError('A rim face could not be rebuilt around the circle.')
        # Only the slivers between the old rim loop and the circle may change.
        if abs(best.Area - face.Area) > near * math.tau * radius * 2 + 1e-6:
            raise ValueError('Rebuilding the rim would change its face.')
        if best.normalAt(0, 0).dot(face.normalAt(0, 0)) < 0:  # Flat faces: one normal.
            best.reverse()
        return best

    replaced = {low_face: rebuild_rim(low_face, circles['low']), high_face: rebuild_rim(high_face, circles['high'])}
    first = min(wall)
    for flip in (False, True):
        tube = wall_face.copy()
        if flip:
            tube.reverse()
        ordered = []
        for i, face in enumerate(faces):
            if i in replaced:
                ordered.append(replaced[i])
            elif i == first:
                ordered.append(tube)
            elif i not in wall:
                ordered.append(face)
        shell = Part.makeShell(ordered)
        shell.fix(1e-7, 1e-7, near)
        if shape.Solids:
            if shell.ShapeType != 'Shell' or not shell.isClosed():
                continue
            candidate = Part.makeSolid(shell)
            if candidate.Volume < 0:
                candidate.reverse()
        else:
            candidate = shell
        if not candidate.isValid():
            continue
        if shape.Solids:
            bound = near * math.tau * radius * height * 2 + 1e-6
            if abs(candidate.Volume - shape.Volume) > bound:
                continue
        return candidate
    raise ValueError('The rebuilt hole did not close the solid.')
