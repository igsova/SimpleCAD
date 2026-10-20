"""Shape-following patterns and spaced/area-balanced grids as native faces."""
import math

import FreeCAD as App
import Part
from ..core import geometry as geo, coincident as coinc

V = App.Vector
MAX_PARTS = 100


def dimensions(total):
    if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= MAX_PARTS:
        raise ValueError("Choose between 1 and %d divisions." % MAX_PARTS)
    rows = math.isqrt(total)
    while total % rows:
        rows -= 1
    return rows, total // rows


def clip(points, axis, value, keep_less):
    """Half-plane polygon clipping. Signed area also handles concave contours."""
    result = []
    if not points:
        return result
    previous = points[-1]
    before = previous[axis] <= value if keep_less else previous[axis] >= value
    for current in points:
        inside = current[axis] <= value if keep_less else current[axis] >= value
        if inside != before:
            fraction = (value - previous[axis]) / (current[axis] - previous[axis])
            result.append(tuple(previous[i] + fraction * (current[i] - previous[i]) for i in range(2)))
        if inside:
            result.append(current)
        previous, before = current, inside
    return result


def polygon_area(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


class Profile:
    def __init__(self, face, angle=0):
        normal = geo.face_normal(face)
        if not math.isfinite(angle):
            raise ValueError("Enter a finite grid angle.")
        # Follow an actual boundary rather than the global XY axes; a rotated
        # rectangle still gets a rectangular grid at angle zero.
        straight = [edge for edge in face.OuterWire.Edges
                    if isinstance(edge.Curve, Part.Line) and len(edge.Vertexes) == 2]
        if straight:
            edge = max(straight, key=lambda e: e.Length)
            u = geo.unit(edge.Vertexes[-1].Point - edge.Vertexes[0].Point)
        else:
            u = geo.Plane.from_face(face).u
        u = App.Rotation(normal, math.remainder(angle, 360)).multVec(u)
        self.placement = App.Placement(face.CenterOfMass, App.Rotation(u, normal.cross(u), normal, "ZXY"))
        self.face = face.copy()
        self.face.Placement = self.placement.inverse().multiply(self.face.Placement)
        box = self.face.optimalBoundingBox(False, False)
        self.extents = (box.XMin, box.XMax, box.YMin, box.YMax)
        margin = max(box.DiagonalLength * .01, geo.EPS * 100)
        self.bounds = (box.XMin - margin, box.XMax + margin, box.YMin - margin, box.YMax + margin)
        self.contours = None
        if all(isinstance(edge.Curve, Part.Line) for edge in self.face.Edges):
            self.contours = [(1 if wire.isSame(self.face.OuterWire) else -1,
                              [(vertex.Point.x, vertex.Point.y) for vertex in wire.OrderedVertexes])
                             for wire in self.face.Wires]

    def corners(self):
        """Ignore collinear boundary splits when recognizing a polygon."""
        if self.contours is None or len(self.contours) != 1:
            return []
        points = [V(x, y) for x, y in self.contours[0][1]]
        changed = True
        while changed and len(points) > 3:
            changed = False
            for i, point in enumerate(points):
                before, after = point - points[i - 1], points[(i + 1) % len(points)] - point
                if before.dot(after) >= 0 and before.cross(after).Length <= geo.EPS * (before.Length + after.Length):
                    points.pop(i); changed = True; break
        return points

    def convex_corners(self):
        points = self.corners()
        if len(points) < 3:
            return []
        turns = [(b - a).cross(c - b).z for a, b, c in
                 zip(points, points[1:] + points[:1], points[2:] + points[:2])]
        return points if all(t > 0 for t in turns) or all(t < 0 for t in turns) else []

    def is_disk(self):
        return (len(self.face.Wires) == 1 and len(self.face.Edges) == 1
                and isinstance(self.face.Edges[0].Curve, Part.Circle) and self.face.Edges[0].isClosed())

    def default_pattern(self):
        points = self.convex_corners()
        if len(points) == 3:
            return "triangles"
        if len(points) == 4 and all(abs((points[i - 1] - p).dot(points[(i + 1) % 4] - p))
                                    <= 1e-8 * (points[i - 1] - p).Length * (points[(i + 1) % 4] - p).Length
                                    for i, p in enumerate(points)):
            return "spaced"
        return "fan" if points or self.is_disk() else "spaced"

    def area(self, bounds):
        x0, x1, y0, y1 = bounds
        if self.contours is None:
            # Circular rims/holes use exact native area, never sampled polygons.
            rectangle = Part.Face(Part.makePolygon([V(x0, y0), V(x1, y0), V(x1, y1), V(x0, y1), V(x0, y0)]))
            return self.face.common(rectangle).Area
        area = 0.0
        for sign, contour in self.contours:
            points = contour
            for axis, value, less in ((0, x0, False), (0, x1, True), (1, y0, False), (1, y1, True)):
                points = clip(points, axis, value, less)
            area += sign * polygon_area(points)
        return max(area, 0.0)

    def positions(self, bounds, axis, count):
        start, end = bounds[axis * 2:axis * 2 + 2]
        area = self.area(bounds)
        tolerance = max(1e-12, area * 1e-10)
        positions = [start]
        for index in range(1, count):
            target = area * index / count
            low, high = positions[-1], end
            for _ in range(48):
                middle = (low + high) / 2
                clipped = list(bounds); clipped[axis * 2 + 1] = middle
                actual = self.area(clipped)
                if abs(actual - target) <= tolerance:
                    break
                if actual < target:
                    low = middle
                else:
                    high = middle
            positions.append(middle)
        return positions + [end]

    def tools(self, rows, columns, spaced=False):
        x0, x1, y0, y1 = self.bounds
        if spaced:
            # Use the actual extents, without the clipping margin. Every line
            # spans the face; columns never shift sideways between rows.
            left, right, bottom, top = self.extents
            segments = [(V(x0, bottom + (top - bottom) * i / rows), V(x1, bottom + (top - bottom) * i / rows))
                        for i in range(1, rows)]
            segments += [(V(left + (right - left) * i / columns, y0), V(left + (right - left) * i / columns, y1))
                         for i in range(1, columns)]
            return self.clip_tools(segments)
        ys = self.positions(self.bounds, 1, rows)
        segments = [(V(x0, y), V(x1, y)) for y in ys[1:-1]]
        for low, high in zip(ys, ys[1:]):
            xs = self.positions((x0, x1, low, high), 0, columns)
            segments.extend((V(x, low), V(x, high)) for x in xs[1:-1])
        return self.clip_tools(segments)

    @staticmethod
    def triangle_segments(points, steps):
        segments = []
        for i, a in enumerate(points):
            b, c = points[(i + 1) % 3], points[(i + 2) % 3]
            segments.extend((a + (b - a) * (j / steps), a + (c - a) * (j / steps))
                            for j in range(1, steps))
        return segments

    def shaped_tools(self, pattern, steps):
        if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= MAX_PARTS:
            raise ValueError("Use a positive whole division count, up to %d." % MAX_PARTS)
        points = self.convex_corners()
        if pattern == "triangles":
            if len(points) != 3:
                raise ValueError("The triangle pattern needs a triangular face without holes.")
            count = steps * steps
            segments = self.triangle_segments(points, steps)
        elif self.is_disk():
            count = steps
            center = self.face.CenterOfMass
            radius = self.face.Edges[0].Curve.Radius * 1.01
            segments = [] if steps == 1 else [(center, center + V(math.cos(i * 2 * math.pi / steps),
                                                                  math.sin(i * 2 * math.pi / steps)) * radius)
                                             for i in range(steps)]
        else:
            if not points:
                raise ValueError("Center fan needs a convex polygon or a circular disk without holes. Use an evenly spaced grid for this face.")
            count = len(points) * steps * steps
            center = self.face.CenterOfMass
            segments = [(center, p) for p in points]
            for a, b in zip(points, points[1:] + points[:1]):
                segments.extend(self.triangle_segments([center, a, b], steps))
        if count > MAX_PARTS:
            raise ValueError("This pattern would create %d faces. Use fewer divisions (maximum %d)." % (count, MAX_PARTS))
        return self.clip_tools(segments), count

    def clip_tools(self, segments):
        edges = []
        for first, second in segments:
            edges.extend(e for e in self.face.common(Part.makeLine(first, second)).Edges if e.Length > geo.EPS)
        result = []
        for edge in coinc.unique(edges):
            edge.Placement = self.placement.multiply(edge.Placement)
            result.append(edge)
        return result


def regions_on(shape, face):
    tolerance = max(1e-7, face.Area * 1e-9)
    return [part for part in shape.Faces if geo.coplanar(part, face)
            and part.common(face).Area > tolerance]


def replace_surface_face(shape, face_index, regions):
    """Replace one open-surface face without intersecting the other faces.

    General-fusing a collection also splits pre-existing intersections between
    unrelated faces. Only propagate new boundary vertices to neighbors, so
    their surfaces stay intact and shared divider endpoints remain connected.
    """
    boundary = Part.makeCompound(shape.Faces[face_index].Edges)
    points = []
    for region in regions:
        for vertex in region.Vertexes:
            if (not any((vertex.Point - old.Point).Length <= geo.EPS for old in points)
                    and boundary.distToShape(vertex)[0] <= geo.EPS):
                points.append(vertex)
    faces = list(regions)
    for index, other in enumerate(shape.Faces):
        if index == face_index:
            continue
        rim = Part.makeCompound(other.Edges)
        splits = [v for v in points
                  if not any((v.Point - old.Point).Length <= geo.EPS for old in other.Vertexes)
                  and rim.distToShape(v)[0] <= geo.EPS]
        if splits:
            output, _ = other.generalFuse(splits)
            if len(output.Faces) != 1 or not coinc.same(output.Faces[0], other):
                raise ValueError("The neighboring surface could not keep its shape while connecting the new divider endpoints.")
            other = output.Faces[0]
        faces.append(other)
    result = coinc.assemble(faces)
    # Coincident old surfaces can be intentional (for example, an extension
    # passing through a face). This operation must not clean them up globally.
    if (len(result.Faces) != len(faces)
            or abs(result.Area - sum(f.Area for f in faces)) > max(1e-6, shape.Area * 1e-8)):
        result = Part.makeCompound(faces)
    native = []
    candidates = list(result.Faces)
    for region in regions:
        match = next((f for f in candidates if f.isSame(region)), None)
        if match is None:
            match = next((f for f in candidates if coinc.same(f, region)), None)
        if match is None:
            raise ValueError("The new face regions could not be reconnected to their neighbors.")
        native.append(match)
        candidates = [f for f in candidates if not f.isSame(match)]
    return result, native


def divide(shape, face_index, rows, columns, angle=0, pattern="equal_area", divisions=3):
    geo.validate(shape)
    if any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in (rows, columns)) or rows * columns > MAX_PARTS:
        raise ValueError("Use positive whole rows/columns, with at most %d parts." % MAX_PARTS)
    if not isinstance(face_index, int) or not 0 <= face_index < len(shape.Faces):
        raise ValueError("Select a face to subdivide.")
    face = shape.Faces[face_index]
    profile = Profile(face, angle)
    if pattern not in ("equal_area", "spaced", "triangles", "fan"):
        raise ValueError("Choose a subdivision pattern.")
    if len(shape.Solids) > 1 or (shape.Solids and len(shape.Faces) != len(shape.Solids[0].Faces)):
        raise ValueError("Separate compound solids or mixed solid/surface objects before subdividing.")
    if pattern in ("triangles", "fan"):
        tools, count = profile.shaped_tools(pattern, divisions)
    else:
        count = rows * columns
        tools = profile.tools(rows, columns, spaced=pattern == "spaced")
    if count == 1:
        return shape.copy(), [face]
    if not tools:
        raise ValueError("The divisions do not cross the face. Try fewer parts or a different grid angle.")
    if shape.Solids:
        _, mapping = shape.Solids[0].generalFuse(tools)
        if len(mapping[0]) != 1 or len(mapping[0][0].Solids) != 1:
            raise ValueError("The face could not be divided while preserving the solid.")
        result = mapping[0][0].Solids[0]
        regions = regions_on(result, face)
    else:
        output, _ = face.generalFuse(tools)
        regions = output.Faces
        result, regions = replace_surface_face(shape, face_index, regions)
    geo.validate(result, solid=bool(shape.Solids))
    if pattern == "spaced":
        # Clipping can leave empty cells, or several pieces in a notched cell.
        # Report actual faces instead of stretching spacing to force a count.
        count = len(regions)
        if not 1 <= count <= MAX_PARTS:
            raise ValueError("This grid creates too many separate faces. Use fewer rows/columns.")
    if len(regions) != count:
        if pattern == "equal_area":
            raise ValueError("This equal-area grid creates disconnected pieces near a notch or hole. Change the grid angle or rows/columns.")
        title = "Center fan" if pattern == "fan" else "Triangle subdivision"
        raise ValueError("%s could not form %d connected faces. Try fewer divisions or choose Evenly spaced grid." % (title, count))
    if len(result.Faces) != len(shape.Faces) + count - 1:
        raise ValueError("The selected face was divided, but its neighboring surfaces could not be preserved.")
    expected = face.Area / count
    if pattern in ("equal_area", "triangles") and any(abs(part.Area - expected) > max(1e-7, expected * 1e-7) for part in regions):
        raise ValueError("The divisions could not form equal-area faces. Try fewer parts or another grid angle.")
    if abs(result.Area - shape.Area) > max(1e-6, shape.Area * 1e-8):
        raise ValueError("Subdividing must preserve the object's surface area.")
    if shape.Solids and abs(result.Volume - shape.Volume) > max(1e-6, abs(shape.Volume) * 1e-8):
        raise ValueError("Subdividing must preserve the object's volume.")
    rest = geo.remaining_lines(coinc.loose_edges(shape), Part.makeCompound(tools))
    boundary_vertices = [v for edge in shape.Edges for v in edge.Vertexes]
    isolated = [v for v in shape.Vertexes if not any(v.isSame(other) for other in boundary_vertices)]
    if rest or isolated:
        result = geo.validate(Part.makeCompound([result] + rest + isolated))
    return result, regions
