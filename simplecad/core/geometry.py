"""Kernel operations. No GUI, document mutation, or saved Python proxies."""
import math
import re
from dataclasses import dataclass

import FreeCAD as App
import numpy as np
import Part
from . import coincident as coinc

V = App.Vector
EPS = 1e-7
# Imported meshes and the solids made by Pull can carry a few microns of
# numerical drift at a contact.  Keep this separate from EPS: it is only used
# to recognize a near-coincident Pull edge before imprinting it on a surface,
# to end a Push/Pull on a level the solid already has, and to fold the step
# faces an earlier near-miss left behind.
PULL_CONTACT_TOLERANCE = 5e-3
# Exact bounds are only a pre-filter before an exact distance within EPS;
# this margin keeps the filter generous.
BOUNDS_MARGIN = 1e-3
MAX_POLYGON_SIDES = 100


def unit(v):
    if v.Length < EPS:
        raise ValueError("Direction is too short.")
    return v / v.Length


@dataclass
class Plane:
    origin: object
    u: object
    v: object
    normal: object

    @classmethod
    def from_normal(cls, origin, normal):
        n = unit(normal)
        seed = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
        u = unit(seed - n * seed.dot(n))
        return cls(V(origin), u, n.cross(u), n)

    @classmethod
    def named(cls, name="XY", origin=None):
        n = {"XY": V(0, 0, 1), "XZ": V(0, -1, 0), "YZ": V(1, 0, 0)}[name]
        return cls.from_normal(origin or V(), n)

    @classmethod
    def from_face(cls, face):
        return cls.from_normal(face.CenterOfMass, face_normal(face))

    def project(self, point):
        return point - self.normal * (point - self.origin).dot(self.normal)

    def intersect(self, origin, direction):
        denominator = self.normal.dot(direction)
        if abs(denominator) < 1e-6:
            raise ValueError("Plane is edge-on. Orbit the view or choose another plane.")
        return origin + direction * (self.normal.dot(self.origin - origin) / denominator)


# SketchUp's arrow keys while drawing: Right faces the red X axis, Left the
# green Y axis and Up the blue Z axis (the ground). A Line's direction lock
# uses the same colours once its first point is placed.
ARROW_PLANES = {"Right": "YZ", "Left": "XZ", "Up": "XY"}
ARROW_AXES = {"Right": "X", "Left": "Y", "Up": "Z"}
# A view ray within about 6 degrees of the ground meets it far away.
GROUND_GRAZING = .1


def arrow_plane(arrow, locked=None):
    """The plane an arrow locks. Down, or the locked arrow again, is Auto (None)."""
    name = ARROW_PLANES.get(arrow)
    return None if name == locked else name


def same_plane(a, b, tolerance=1e-5):
    """Parallel workplanes through a common point, either way round."""
    return abs(a.normal.dot(b.normal)) > 1 - 1e-7 and abs((b.origin - a.origin).dot(a.normal)) <= tolerance


def locked_start(name, direction):
    """Where a locked plane starts in empty space: on the ground, as in Auto,
    unless the view looks along the ground; then on the world plane itself."""
    if name == "XY" or abs(unit(direction).z) >= GROUND_GRAZING:
        return Plane.named("XY")
    return Plane.named(name)


def face_normal(face):
    if face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane):
        raise ValueError("Choose a flat face. Curved faces are not supported yet.")
    a, b, c, d = face.ParameterRange
    return unit(face.normalAt((a + b) / 2, (c + d) / 2))


def rectangle_points(plane, first, second):
    delta = second - first
    u, v = plane.u * delta.dot(plane.u), plane.v * delta.dot(plane.v)
    return [first, first + u, first + u + v, first + v, first]


def rectangle(plane, first, second):
    points = rectangle_points(plane, plane.project(first), plane.project(second))
    if (points[1] - points[0]).Length < EPS or (points[3] - points[0]).Length < EPS:
        raise ValueError("Rectangle needs both width and height.")
    face = Part.Face(Part.makePolygon(points))
    if face_normal(face).dot(plane.normal) < 0:
        face.reverse()
    return face


def circle_points(plane, center, radius):
    """Sample the preview only; saved circles use an analytic OCC curve."""
    center = plane.project(center)
    points = [center + plane.u * (radius * math.cos(i * math.tau / 96))
              + plane.v * (radius * math.sin(i * math.tau / 96)) for i in range(96)]
    return points + [points[0]]


def circle(plane, center, radius):
    if not math.isfinite(radius) or radius < EPS:
        raise ValueError("Circle needs a positive radius.")
    edge = Part.makeCircle(radius, plane.project(center), plane.normal)
    face = Part.Face(Part.Wire([edge]))
    if face_normal(face).dot(plane.normal) < 0:
        face.reverse()
    return face


def sphere_points(center, radius):
    """Three great circles for a cheap preview; no kernel work while dragging."""
    return [circle_points(Plane.named(name, center), center, radius)
            for name in ("XY", "XZ", "YZ")]


def sphere(center, radius):
    """A complete analytic solid, centered at the exact world-space point."""
    if isinstance(radius, bool) or not math.isfinite(radius) or radius < EPS:
        raise ValueError("Sphere needs a positive radius.")
    center = V(center)
    if not all(math.isfinite(value) for value in (center.x, center.y, center.z)):
        raise ValueError("Sphere needs a finite center point.")
    return validate(Part.makeSphere(radius, center), solid=True)


def polygon_points(plane, center, vertex, sides):
    """Regular polygon with a cursor-defined first vertex and winding."""
    if isinstance(sides, bool) or not isinstance(sides, int) or not 3 <= sides <= MAX_POLYGON_SIDES:
        raise ValueError("Choose between 3 and %d polygon sides." % MAX_POLYGON_SIDES)
    center = plane.project(center)
    direction = plane.project(vertex) - center
    radius = direction.Length
    if not math.isfinite(radius) or radius < EPS:
        raise ValueError("Polygon needs a positive radius.")
    u = direction / radius
    v = plane.normal.cross(u)
    points = [center + radius * (u * math.cos(i * math.tau / sides) + v * math.sin(i * math.tau / sides))
              for i in range(sides)]
    return points + points[:1]


def polygon(plane, center, vertex, sides):
    face = Part.Face(Part.makePolygon(polygon_points(plane, center, vertex, sides)))
    if face_normal(face).dot(plane.normal) < 0:
        face.reverse()
    return validate(face)


def line(first, second):
    if (second - first).Length < EPS:
        raise ValueError("Line needs two different points.")
    return Part.makeLine(first, second)


def point_on_face(face, point, tolerance=1e-5):
    return face.distToShape(Part.Vertex(point))[0] <= tolerance


def on_face_boundary(shape, point, tolerance=1e-5):
    """Whether point lies on an edge of one of shape's faces."""
    vertex = Part.Vertex(point)
    region = vertex.BoundBox
    region.enlarge(tolerance)
    return any(face.BoundBox.intersect(region)
               and any(edge.BoundBox.intersect(region) and edge.distToShape(vertex)[0] <= tolerance
                       for edge in face.Edges)
               for face in shape.Faces)


def _boundary_nearest_point(face, point, tolerance=PULL_CONTACT_TOLERANCE):
    """Return a nearby point on a face boundary, without snapping interiors."""
    boundary = Part.makeCompound(face.Edges)
    distance, pairs, _ = boundary.distToShape(Part.Vertex(point))
    if distance > tolerance or not pairs:
        return None
    pair = pairs[0]
    try:
        candidate = pair[0]
    except (IndexError, TypeError):
        return None
    return V(candidate)


def project_pull_edge(edge, face, tolerance=PULL_CONTACT_TOLERANCE):
    """Project a nearly coplanar straight edge onto a target face.

    Pull creates its new solid independently from the remainder surface.  A
    native edge can therefore be a few microns away from the fitted plane and
    miss a later face split.  Only straight edges are projected; curves keep
    their exact geometry and are left for the ordinary modeling paths.
    Endpoints that are within the same tolerance of the face boundary are
    snapped to that boundary so a line that should cross the face actually
    reaches its native perimeter.
    """
    if (face.ShapeType != "Face" or not isinstance(face.Surface, Part.Plane)
            or edge.ShapeType != "Edge" or edge.Degenerated
            or len(edge.Vertexes) != 2 or not isinstance(edge.Curve, Part.Line)):
        return None
    plane = Plane.from_face(face)
    points = [vertex.Point for vertex in edge.Vertexes]
    if max(abs((point - plane.origin).dot(plane.normal)) for point in points) > tolerance:
        return None
    projected = [plane.project(point) for point in points]
    for index, point in enumerate(projected):
        nearest = _boundary_nearest_point(face, point, tolerance)
        if nearest is not None:
            projected[index] = nearest
    if (projected[1] - projected[0]).Length <= EPS:
        return None
    candidate = Part.makeLine(*projected)
    common = face.common(candidate).Length
    if abs(common - candidate.Length) > max(EPS, candidate.Length * 1e-8):
        return None
    return candidate


def imprint_pull_edges(surface, pulled, tolerance=PULL_CONTACT_TOLERANCE):
    """Imprint Pull edges that are nearly coincident with a remainder face.

    The result remains an open surface when ``surface`` is one.  Each split is
    performed through the existing strict divider, so area/volume/validity
    checks are unchanged.  Bounding boxes avoid testing every edge against
    every face when the pulled solid is small relative to a dense STL shell.
    """
    if surface is None or pulled is None or not surface.Faces or not pulled.Edges:
        return surface
    result = surface
    source_box = result.BoundBox
    pulled_edges = [edge for edge in pulled.Edges
                    if edge.ShapeType == "Edge" and not edge.Degenerated
                    and len(edge.Vertexes) == 2]
    seen = set()
    # A cap can contribute a complete closed wire inside a large face. Gather
    # all of its projected edges before dividing so the existing divider can
    # close that region in one operation instead of treating each edge as a
    # dangling line.
    for _ in range(len(pulled_edges) + 1):
        changed = False
        for face in result.Faces:
            tools = []
            for edge in pulled_edges:
                box = edge.BoundBox
                fbox = face.BoundBox
                if (box.XMax < source_box.XMin - tolerance or box.XMin > source_box.XMax + tolerance
                        or box.YMax < source_box.YMin - tolerance or box.YMin > source_box.YMax + tolerance
                        or box.ZMax < source_box.ZMin - tolerance or box.ZMin > source_box.ZMax + tolerance
                        or box.XMax < fbox.XMin - tolerance or box.XMin > fbox.XMax + tolerance
                        or box.YMax < fbox.YMin - tolerance or box.YMin > fbox.YMax + tolerance
                        or box.ZMax < fbox.ZMin - tolerance or box.ZMin > fbox.ZMax + tolerance):
                    continue
                projected = project_pull_edge(edge, face, tolerance)
                if projected is None:
                    continue
                endpoints = tuple(tuple(round(value, 6) for value in point)
                                  for point in (projected.Vertexes[0].Point, projected.Vertexes[1].Point))
                key = tuple(sorted(endpoints))
                if key in seen:
                    continue
                seen.add(key)
                tools.append(projected)
            if not tools:
                continue
            divided = divide_face_with_edges(result, tools[0], tools[1:])
            if divided is not None:
                result = divided[0]
                changed = True
                break
        if not changed:
            break
    return result


def divide_face_with_line(shape, first, second):
    """Divide native faces with one segment; incomplete lines return None."""
    divided = divide_face_with_edges(shape, line(first, second))
    return divided[0] if divided is not None else None


def drape(edge, faces, tolerance):
    """A straight line over nearly coplanar faces, as segments each on one face.

    Each face takes the part of the line over it, projected onto its plane;
    neighbouring parts meet at one point on the boundary edge they cross.
    None unless the parts cover the whole line without ambiguity.
    """
    first, second = [vertex.Point for vertex in edge.Vertexes]
    length = (second - first).Length
    if length <= EPS:
        return None
    direction = (second - first) * (1 / length)
    spans = []
    for face in faces:
        plane = Plane.from_face(face)
        line = Part.makeLine(plane.project(first), plane.project(second))
        for part in face.common(line).Edges:
            ends = sorted((vertex.Point - first).dot(direction) for vertex in part.Vertexes)
            if len(ends) == 2 and ends[1] - ends[0] > EPS:
                spans.append((ends[0], ends[1], face, plane))
    spans.sort(key=lambda span: span[0])
    chosen, reach = [], 0.0
    for span in spans:
        if span[1] <= reach + tolerance:
            continue  # Along a shared edge both faces hold the same part.
        if abs(span[0] - reach) > tolerance:
            return None  # A gap, or two faces claiming the same stretch.
        chosen.append(span)
        reach = span[1]
    if not chosen or abs(reach - length) > tolerance:
        return None
    points = [chosen[0][3].project(first)]
    for (_, end, face, _), _ in zip(chosen, chosen[1:]):
        boundary = Part.makeCompound(face.Edges)
        distance, pairs, _ = boundary.distToShape(Part.Vertex(first + direction * end))
        if distance > tolerance or not pairs:
            return None
        points.append(V(pairs[0][0]))
    points.append(chosen[-1][3].project(second))
    return [Part.makeLine(a, b) for a, b in zip(points, points[1:]) if (b - a).Length > EPS]


def remaining_lines(edges, boundary):
    """Keep unused portions of loose lines after they become face boundaries."""
    result = []
    flat = modeling_precision() * .01
    for edge in edges:
        if boundary.common(edge).Length <= EPS:
            # A line draped over nearly coplanar faces became boundaries a
            # hair off itself; it is used, not left over.
            if all(boundary.distToShape(Part.Vertex(edge.valueAt(
                    edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * t)))[0] <= flat
                   for t in (0, .25, .5, .75, 1)):
                continue
            result.append(edge)
        else:
            result.extend(part for part in edge.cut(boundary).Edges if part.Length > EPS)
    return result


def native_unique(shapes):
    """Drop repeated native subshapes, as shared edges of adjacent faces are."""
    seen, result = {}, []
    for item in shapes:
        bucket = seen.setdefault(hash(item), [])
        if not any(item.isSame(other) for other in bucket):
            bucket.append(item)
            result.append(item)
    return result


class FaceIndex:
    """A shape's faces with their bounds and flatness, kept across local edits.

    Listing the faces of a converted part of thousands of triangles takes a
    sizeable fraction of a second and reading their bounds as much again. A
    local split changes a handful, so the index of its result is derived
    from its source's rather than listed again.
    """
    def __init__(self, shape, faces, bounds, planar):
        self.shape, self.faces = shape, list(faces)
        self.bounds = np.asarray(bounds, dtype=float).reshape(-1, 6)
        self.planar = np.asarray(planar, dtype=bool).reshape(-1)
        self._compound = None

    @property
    def compound(self):
        """All the faces as one compound, made once per shape."""
        if self._compound is None:
            self._compound = Part.makeCompound(self.faces)
        return self._compound

    @classmethod
    def build(cls, shape):
        faces = shape.Faces
        boxes = [face.BoundBox for face in faces]
        return cls(shape, faces, [(b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax) for b in boxes],
                   [isinstance(face.Surface, Part.Plane) for face in faces])

    def near(self, box, pad=0.0):
        """Indices of faces whose bounds meet the box."""
        low = np.array((box.XMin, box.YMin, box.ZMin)) - pad
        high = np.array((box.XMax, box.YMax, box.ZMax)) + pad
        hit = np.all((self.bounds[:, :3] <= high) & (self.bounds[:, 3:] >= low), axis=1)
        return [int(i) for i in np.nonzero(hit)[0]]

    def derive(self, result, removed, added):
        gone = {hash(face) for face in removed}
        keep = [i for i, face in enumerate(self.faces) if hash(face) not in gone]
        added = list(added)
        boxes = [face.BoundBox for face in added]
        bounds = [(b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax) for b in boxes]
        return FaceIndex(result, [self.faces[i] for i in keep] + added,
                         np.vstack([self.bounds[keep], np.asarray(bounds, dtype=float).reshape(-1, 6)]),
                         np.concatenate([self.planar[keep], [isinstance(face.Surface, Part.Plane) for face in added]]))


@dataclass
class Change:
    """Which faces a local edit removed from a shape and added to its result."""
    source: object
    result: object
    removed: list
    added: list


_face_indexes, _changes = {}, {}


def _recent(cache, shape, value, limit=32):
    cache.setdefault(hash(shape), []).insert(0, (shape, value))
    while sum(len(bucket) for bucket in cache.values()) > limit:
        oldest = next(iter(cache))
        cache[oldest].pop()
        if not cache[oldest]:
            del cache[oldest]
    return value


def _lookup(cache, shape):
    return next((value for known, value in cache.get(hash(shape), ()) if known.isSame(shape)), None)


def face_index(shape, build=True):
    """The shape's face index, listed now only when none is known."""
    index = _lookup(_face_indexes, shape)
    if index is None and build:
        index = remember_face_index(FaceIndex.build(shape))
    return index


def remember_face_index(index):
    return _recent(_face_indexes, index.shape, index, limit=8)


def change_to(shape):
    """The recorded local edit whose result is this shape, if any."""
    return _lookup(_changes, shape)


def record_change(change):
    return _recent(_changes, change.result, change, limit=8)


def split_faces_locally(shape, faces, lines, index=None):
    """Split only ``faces`` of a solid or shell, keeping every other native face.

    A divider can end inside a boundary edge, and the fuse gives boundary
    edges and vertices new images. Faces outside the split that use a
    replaced edge or vertex are rebuilt together with those images, so the
    edges they share stay shared; then only faces are swapped into the
    shape. Returns the shape, the history of the lines, the pieces of each
    face and the faces removed and added.
    """
    boundaries = native_unique([e for f in faces for e in f.Edges] + [v for f in faces for v in f.Vertexes])
    output, mapping = faces[0].generalFuse(faces[1:] + boundaries + lines)
    replacements, pieces = [], []
    for face, images in zip(faces, mapping):
        parts = [piece for item in images for piece in item.Faces]
        if not parts:
            raise ValueError("The lines could not divide this face.")
        pieces.append(parts)
        replacements.append((face, parts[0] if len(parts) == 1 else Part.makeShell(parts)))
    changed = []
    for original, mapped in zip(boundaries, mapping[len(faces):]):
        replacement = None
        if original.ShapeType == 'Edge':
            parts = [edge for item in mapped for edge in item.Edges]
            if parts:
                replacement = parts[0] if len(parts) == 1 else Part.Wire(Part.__sortEdges__(parts))
        else:
            parts = [vertex for item in mapped for vertex in item.Vertexes]
            if len(parts) == 1:
                replacement = parts[0]
        if replacement is not None and not replacement.isSame(original):
            changed.append((original, replacement))
    neighbours, rebuilt = [], []
    if changed:
        replaced = {}
        for original, _ in changed:
            replaced.setdefault(hash(original), []).append(original)

        def uses(face):
            return any(sub.isSame(known) for sub in face.Edges + face.Vertexes
                       for known in replaced.get(hash(sub), ()))
        # Every replaced edge and vertex lies on the split faces, so a face
        # using one meets their bounds.
        region = Part.makeCompound(faces).BoundBox
        region.enlarge(max(1e-3, 2 * shape.getTolerance(1)))
        candidates = [index.faces[i] for i in index.near(region)] if index is not None else shape.Faces
        own = {hash(face) for face in faces}
        neighbours = [face for face in candidates
                      if not (hash(face) in own and any(face.isSame(other) for other in faces)) and uses(face)]
        if neighbours:
            rebuilt = Part.makeCompound(neighbours).replaceShape(changed).childShapes()
            if len(rebuilt) != len(neighbours):
                raise ValueError("The lines could not divide this face.")
            replacements.extend(zip(neighbours, rebuilt))
    result = shape.replaceShape(replacements)
    added = [piece for parts in pieces for piece in parts] + rebuilt
    return result, mapping[len(faces) + len(boundaries):], pieces, list(faces) + neighbours, added


def split_whole(shape, lines):
    """Split a shape's faces by lines with one boolean over the whole shape."""
    native_shell = shape.ShapeType == 'Shell'
    sources = list(shape.Solids) or ([shape] if native_shell else shape.Faces)
    output, mapping = sources[0].generalFuse(sources[1:] + lines)
    if shape.Solids:
        pieces = mapping[0]
        if len(pieces) != 1 or len(pieces[0].Solids) != 1:
            raise ValueError("The lines could not divide this face into a valid solid.")
        result = pieces[0].Solids[0]
    elif native_shell and len(output.Shells) == 1 and len(output.Shells[0].Faces) == len(output.Faces):
        # A shell has no entry in the boolean history, but its complete
        # split shell is present in the output. Keep that shared topology
        # instead of intersecting/resewing thousands of independent faces.
        result = output.Shells[0]
    else:
        # An untouched face sharing native edges can have an empty history
        # entry. All output faces belong to the source surface (the tools
        # contain only edges), so retain them directly instead of relying
        # on complete per-face history.
        result = coinc.assemble(output.Faces)
    return result, mapping[len(sources):]


def check_local_split(shape, result, faces, pieces, removed, added):
    """Validate what a local split changed, not the whole unchanged model.

    Checking every face of a dense converted part takes seconds. The split
    reports the faces it removed and added: the face count must follow from
    them, each added face must be valid and together they must cover exactly
    the area of the faces they replace. Every piece keeps its face's outward
    side, and the result must still close.
    """
    if result.isNull() or result.ShapeType != shape.ShapeType:
        raise ValueError("The operation would create invalid geometry.")
    if result.countElement('Face') != shape.countElement('Face') - len(removed) + len(added):
        raise ValueError("The operation would create invalid geometry.")
    if not added or not all(face.isValid() for face in added):
        raise ValueError("The operation would create invalid geometry.")
    area = sum(f.Area for f in removed)
    if abs(sum(f.Area for f in added) - area) > max(1e-6, area * 1e-8):
        from ..surfaces.line import preserves_area
        if all(isinstance(f.Surface, Part.Plane) for f in removed) or not preserves_area(
                Part.makeCompound(removed), Part.makeCompound(added)):
            raise ValueError("Dividing a face must preserve its surface area.")
    for face, parts in zip(faces, pieces):
        flat = isinstance(face.Surface, Part.Plane)
        normal = face_normal(face) if flat else None
        for part in parts:
            # Compare normals at the same point, including curved faces whose
            # normal changes across the new regions.
            # Look the piece up in the result's face map: an ancestor query
            # maps every edge of a dense part, six times slower.
            kind, number = result.findSubShape(part)
            if kind != 'Face':
                raise ValueError("The operation would create invalid geometry.")
            placed = [result.getElement('Face%d' % number)]
            if flat:
                agrees = face_normal(placed[0]).dot(normal) > 0
            else:
                u0, u1, v0, v1 = part.ParameterRange
                point = part.valueAt((u0+u1)/2, (v0+v1)/2)
                original = face.normalAt(*face.Surface.parameter(point))
                other = placed[0].normalAt(*placed[0].Surface.parameter(point))
                agrees = original.dot(other) > 0
            if not agrees:
                raise ValueError("The operation would create invalid geometry.")
    if shape.isClosed() and not result.isClosed():
        raise ValueError("The operation would create invalid geometry.")
    return result


def _bridges(ends):
    """Bridges of a graph given each edge's two end keys, and each key's component.

    A bridge lies on no cycle. Iterative, so a face with many boundary edges
    cannot exhaust Python's recursion limit.
    """
    links = {}
    for number, (a, b) in enumerate(ends):
        links.setdefault(a, []).append((b, number))
        links.setdefault(b, []).append((a, number))
    order, low, root, bridges = {}, {}, {}, set()
    for start in links:
        if start in order:
            continue
        order[start] = low[start] = len(order)
        root[start] = start
        stack = [(start, -1, iter(links[start]))]
        while stack:
            node, via, rest = stack[-1]
            for other, number in rest:
                if number == via:
                    continue
                if other in order:
                    low[node] = min(low[node], order[other])
                else:
                    order[other] = low[other] = len(order)
                    root[other] = start
                    stack.append((other, number, iter(links[other])))
                    break
            else:
                stack.pop()
                if stack:
                    parent = stack[-1][0]
                    low[parent] = min(low[parent], low[node])
                    if low[node] > order[parent]:
                        bridges.add(via)
    return bridges, root


def bounds_no_region(edge, lines, faces):
    """Whether the segment, with the lines it meets, cannot close a region.

    A face gains a region only where lines, together with its boundaries,
    form a closed path. Fuse the edges alone (milliseconds, where splitting
    the faces of a fitted part takes tenths of a second): when every piece of
    the segment and of every line connected to it lies on no cycle of that
    graph, a free end remains and the split could only add a dangling edge.
    Boundaries of more faces than the split uses only add cycles, so the
    answer stays safe. Anything unexpected answers False: try the split.
    """
    drawn = list(edge.Edges)
    tools = drawn + [part for line in lines for part in line.Edges]
    boundaries = native_unique([e for face in faces for e in face.Edges])
    try:
        output, mapping = tools[0].generalFuse(tools[1:] + boundaries)
    except (RuntimeError, Part.OCCError):
        return False
    vertices, positions = {}, {}
    for number, vertex in enumerate(output.Vertexes):
        vertices.setdefault(hash(vertex), []).append((vertex, number))
    graph = output.Edges
    for number, item in enumerate(graph):
        positions.setdefault(hash(item), []).append((item, number))

    def find(table, shape):
        return next((number for known, number in table.get(hash(shape), ()) if known.isSame(shape)), None)

    ends = []
    for item in graph:
        if not item.Vertexes:
            return False
        ends.append(tuple(find(vertices, vertex) for vertex in (item.Vertexes[0], item.Vertexes[-1])))
    if any(key is None for pair in ends for key in pair):
        return False
    # A tool the fuse left untouched has no images; it is in the output itself.
    pieces = []
    for tool, images in zip(tools, mapping):
        found = [find(positions, part) for part in ([e for image in images for e in image.Edges] or tool.Edges)]
        if not found or None in found:
            return False
        pieces.append(found)
    bridges, root = _bridges(ends)
    reached = {root[ends[number][0]] for group in pieces[:len(drawn)] for number in group}
    return all(number in bridges for group in pieces for number in group if root[ends[number][0]] in reached)


def divide_face_with_edges(shape, edge, existing_edges=(), surface=False):
    """Close regions with a segment and connected loose lines on its support.

    Return (shape, consumed boundary), or None if no face gained a region.
    With surface=True, the segment is already an exact curve on the faces.
    Native solids and shells preserve their shared topology. Independent open
    surfaces are passed as individual faces and assembled after splitting.
    A second pass drops dangling internal wires: only real region boundaries
    become topology; incomplete branches stay ordinary editable loose lines.
    """
    count = shape.countElement('Face')
    solids = shape.Solids
    if not count or len(solids) > 1 or (solids and solids[0].countElement('Face') != count):
        return None
    loose = coinc.loose_edges(shape)
    # Only a face overlapping the new segment or a loose line can cover or
    # connect them. Reading every face's plane on a dense converted part
    # takes seconds; rejecting by bounds first is cheap.
    region = Part.makeCompound([edge] + list(existing_edges) + loose).BoundBox
    region.enlarge(max(1e-3, 2 * shape.getTolerance(1)))
    index = face_index(shape)
    if surface:
        # Exact surface curves may cross several already-divided faces. Bounds
        # reject unrelated faces before the local kernel intersection tests.
        drawing = Part.makeCompound([edge]+list(existing_edges)+loose)
        faces = [index.faces[i] for i in index.near(region)
                 if index.faces[i].common(drawing).Length > EPS]
        if not faces:
            return None
        # Most segments of a loop still have a free end. Their split attempt
        # cost a tenth of a second per click on a fitted part, only to find
        # no new face.
        if bounds_no_region(edge, list(existing_edges) + loose, faces):
            return None
        skin = Part.makeCompound(faces)

        def covered(line):
            return abs(skin.common(line).Length - line.Length) <= max(EPS, line.Length * 1e-8)

        if not covered(edge):
            return None
        seeds = edge.Edges
    else:
        first, second = [vertex.Point for vertex in edge.Vertexes]
        # Triangles a converted mesh left side by side lean against each other
        # by fractions of a micron. Within a hundredth of the modeling precision
        # they form one flat region that a line may cross.
        flat = modeling_precision() * .01
        faces, exact = [], []
        support = None
        for i in index.near(region):
            if not index.planar[i]:
                continue
            face = index.faces[i]
            plane = Plane.from_face(face)
            # A converted face can keep a few vertices microns off its plane,
            # within their own tolerance. A line snapped to one still lies on it.
            allowance = max(1e-7, face.getTolerance(1, Part.Vertex))
            offset = max(abs((p - plane.origin).dot(plane.normal)) for p in (first, second))
            if offset <= max(allowance, flat):
                faces.append(face)
            if offset <= allowance:
                exact.append(face)
                support = support or plane
        if not faces:
            return None
        skin = Part.makeCompound(faces)

        def covered(line):
            return abs(skin.common(line).Length - line.Length) <= max(EPS, line.Length * 1e-8)

        seeds = None
        if exact:
            projected = [support.project(p) for p in (first, second)]
            line = Part.makeLine(*projected) if any((p - q).Length > 1e-7 for p, q in zip(projected, (first, second))) else edge
            if covered(line):
                seeds = [line]
        if seeds is None:
            # Across nearly coplanar faces: one segment on each face, meeting on
            # the edges they share. Only a straight line drapes; an arc beside
            # a face is not its chord across it.
            seeds = drape(edge, faces, flat) if isinstance(edge.Curve, Part.Line) else None
            if not seeds or not all(covered(seed) for seed in seeds):
                return None
        edge = seeds[0] if len(seeds) == 1 else edge
    pending = [item for item in coinc.unique(list(existing_edges) + loose)
               if not coinc.same(item, edge) and covered(item)]
    # Two separate bridges across a ring close a region through its existing
    # inner/outer boundaries, even though the loose lines never touch each
    # other. Traverse those wires as connections, not as new cutting tools.
    # Disconnected interior loops must still stay out of this operation.
    wires = [wire for face in faces if len(face.Wires) > 1 for wire in face.Wires]
    # A plate with hundreds of holes has hundreds of wires. Exact bounds
    # farther apart than a margin cannot be within EPS; measure only the rest.
    # (A shape's BoundBox follows its display mesh and can be smaller than
    # its curves, so the exact, tolerance-inclusive bounds are used.)
    bounds = {}

    def may_touch(current, item):
        for shape in (current, item):
            if id(shape) not in bounds:
                box = shape.optimalBoundingBox(False, True)
                box.enlarge(BOUNDS_MARGIN)
                bounds[id(shape)] = (shape, box)
        first, second = bounds[id(current)][1], bounds[id(item)][1]
        return not (first.isValid() and second.isValid()) or first.intersect(second)

    tools, frontier = list(seeds), list(seeds)
    while frontier:
        current = frontier.pop()
        for item in pending[:]:
            if may_touch(current, item) and current.distToShape(item)[0] <= EPS:
                tools.append(item)
                frontier.append(item)
                pending.remove(item)
        for wire in wires[:]:
            if may_touch(current, wire) and current.distToShape(wire)[0] <= EPS:
                frontier.append(wire)
                wires.remove(wire)

    native_shell = shape.ShapeType == 'Shell'
    # A boolean often returns its solid inside a compound; the whole split
    # returns that solid alone, and so does the local one.
    target = shape
    if shape.ShapeType == 'Compound' and len(solids) == 1 and len(shape.childShapes()) == 1:
        target = solids[0]
    # Most edits split one or two faces. Keep every unrelated face of a solid
    # or shell out of the boolean and its validation, including the
    # thousands of triangles of a converted part.
    local_faces = []
    if native_shell or target.ShapeType == 'Solid':
        tool_shape = Part.makeCompound(tools)
        local_faces = [face for face in faces if face.common(tool_shape).Length > EPS]
    local_split = []  # pieces, removed and added faces of the latest local split

    def split(lines, local):
        if local:
            result, history, *local_split[:] = split_faces_locally(target, local_faces, lines, index)
            return result, history
        return split_whole(shape, lines)

    def divide(local):
        result, mapping = split(tools, local)
        if result is None or result.countElement('Face') <= count:
            return None
        # INTERNAL spur edges belong to one face, whereas a dividing edge belongs
        # to at least two. Geometric identity survives any sewing of open surfaces.
        parts = [part for group in mapping for item in group for part in item.Edges]
        used, unresolved = [], []
        for part in parts:
            if len(parts) <= 8 and len(result.ancestorsOfType(part, Part.Face)) >= 2:
                used.append(part)
            else:
                unresolved.append(part)
        if unresolved:
            used.extend(part for part, owners in zip(unresolved, coinc.face_owners(result.Faces, unresolved))
                        if len(owners) >= 2)
        if not used:
            return None
        if len(used) != len(parts):
            result, _ = split(coinc.unique(used), local)
        if local:
            check_local_split(target, result, local_faces, *local_split)
        else:
            validate(result, solid=bool(shape.Solids))
        if result.countElement('Face') <= count:
            return None
        if not local:
            if abs(result.Area - shape.Area) > max(1e-6, shape.Area * 1e-8):
                from ..surfaces.line import preserves_area
                if not surface or not preserves_area(shape, result):
                    raise ValueError("Dividing a face must preserve its surface area.")
            # Only an edge on a face is added, so the volume cannot really
            # change. Its numeric evaluation still drifts by about 1e-8 on
            # converted solids carrying mesh-era tolerances; a wrong split
            # changes far more. A local split keeps every other face and
            # checks the area of those it changes instead.
            if shape.Solids and abs(volume(result) - volume(shape)) > max(1e-6, volume(shape) * 1e-6):
                from ..surfaces.line import preserves_volume
                if not surface or not preserves_volume(shape,result,relative=1e-6):
                    raise ValueError("Dividing a face must not change the block's volume.")
        return result, used

    # The local faces carry every tool, so when they gain no region neither
    # would the whole shape. Only a failed local split needs the complete
    # boolean, which settles unusual topology.
    local = bool(local_faces)
    try:
        divided = divide(local) if local else divide(False)
    except (ValueError, RuntimeError, Part.OCCError):
        if not local:
            raise
        local, divided = False, divide(False)
    if divided is None:
        return None
    result, used = divided
    boundary = Part.makeCompound(coinc.unique(used))
    rest = remaining_lines(loose, boundary)
    if rest:
        result = Part.makeCompound([result] + rest)
        validate(result)
    elif local:
        # Later edits, snaps and seam checks start from what changed.
        _, removed, added = local_split
        remember_face_index(index.derive(result, removed, added))
        record_change(Change(shape, result, removed, added))
    return result, boundary


def has_face_divisions(shape, pushed=None):
    """Detect coplanar neighboring faces whose boundary must survive Push/Pull.

    The outline of the face being pushed does not count: the pull moves that
    face off its plane, so a region drawn flush with an edge still leaves one
    merged side face, as a separate profile on the solid did.
    """
    adjacent = {}
    for face in shape.Faces:
        if not isinstance(face.Surface, Part.Plane) or (pushed is not None and face.isSame(pushed)):
            continue
        normal = face_normal(face)
        center = face.CenterOfMass
        for edge in face.Edges:
            neighbors = adjacent.setdefault(hash(edge), [])
            for shared, other_normal, other_center in neighbors:
                if (edge.isSame(shared) and abs(normal.dot(other_normal)) >= 1 - 1e-7
                        and abs((center-other_center).dot(normal)) <= 1e-7):
                    return True
            neighbors.append((edge, normal, center))
    return False


def divide_face_with_profile(shape, profile):
    """Imprint a contained closed profile as native faces, preserving the base.

    Unlike an overlay disk, the inner region and its surrounding face share a
    boundary, so native selection and face deletion work without pick priority.
    A profile across regions drawn earlier on the same flat face divides each
    of them where it crosses. Return None when the profile is already an
    entire existing face, or only retraces existing edges.
    """
    validate(profile)
    face_normal(profile)
    if (len(shape.Solids) > 1
            or (shape.Solids and len(shape.Faces) != len(shape.Solids[0].Faces))):
        raise ValueError("Separate compound solids or mixed solid/surface objects before drawing a profile.")
    supports, region = profile_support_faces(shape, profile)
    outline = Part.makeCompound(profile.Edges)
    tolerance = max(1e-6, outline.Length * 1e-7)
    if region is None and outline.cut(Part.makeCompound(shape.Edges)).Length <= tolerance:
        return None  # The outline retraces existing edges only.
    if region is not None and coinc.same(supports[0], region):
        return None
    if shape.Solids:
        _, mapping = shape.Solids[0].generalFuse(profile.Edges)
        pieces = mapping[0]
        if len(pieces) != 1 or len(pieces[0].Solids) != 1:
            raise ValueError("The profile could not divide this face into a valid solid.")
        result = pieces[0].Solids[0]
    else:
        # Profile drawing must preserve pre-existing intersections elsewhere in
        # an open surface collection, just like Subdivide Face.
        from ..modeling.subdivision import replace_surface_face
        result = shape
        for support in supports:
            # Each replacement rebuilds the faces: find the support again.
            index = next(i for i, face in enumerate(result.Faces)
                         if face.isSame(support) or coinc.same(face, support))
            output, _ = result.Faces[index].generalFuse(profile.Edges)
            result, _ = replace_surface_face(result, index, output.Faces)
    validate(result, solid=bool(shape.Solids))
    if (len(result.Faces) <= len(shape.Faces)
            or (not any(coinc.same(face, region) for face in result.Faces) if region is not None
                else outline.cut(Part.makeCompound(result.Edges)).Length > tolerance)):
        raise ValueError("The profile could not form a separate region on this face.")
    if abs(result.Area - shape.Area) > max(1e-4, shape.Area * 1e-5):
        raise ValueError("Drawing a profile must preserve the surface area.")
    if shape.Solids and abs(result.Volume - shape.Volume) > max(1e-4, shape.Volume * 1e-5):
        raise ValueError("Drawing a profile must preserve the block's volume.")
    loose = remaining_lines(coinc.loose_edges(shape), Part.makeCompound(profile.Edges))
    boundary_vertices = {}
    for edge in shape.Edges:
        for vertex in edge.Vertexes:
            boundary_vertices.setdefault(hash(vertex), []).append(vertex)
    isolated = [v for v in shape.Vertexes
                if not any(v.isSame(other) for other in boundary_vertices.get(hash(v), ()))]
    if loose or isolated:
        result = Part.makeCompound([result] + loose + isolated)
        validate(result)
    return result


def coplanar(first, second, tol=0.05):
    if not all(isinstance(face.Surface, Part.Plane) for face in (first, second)):
        try:
            n1 = face_normal(first)
            n2 = face_normal(second)
        except Exception:
            return False
    else:
        n1 = face_normal(first)
        n2 = face_normal(second)
    if abs(abs(n1.dot(n2)) - 1.0) > 1e-4:
        return False
    # Check distance between faces along normal
    dist1 = abs((second.CenterOfMass - first.CenterOfMass).dot(n1))
    dist2 = abs((first.CenterOfMass - second.CenterOfMass).dot(n2))
    if max(dist1, dist2) <= max(tol, 1e-4):
        return True
    if isinstance(first.Surface, Part.Plane) and isinstance(second.Surface, Part.Plane):
        surf_dist = abs((second.Surface.Position - first.Surface.Position).dot(n1))
        if surf_dist <= max(tol, 1e-4):
            return True
    return False


def seam_indices(shape, indices=None):
    """Zero-based seam IDs; small selections only visit their native ancestors."""
    if indices is not None and len(indices) <= 8:
        return {i for i in indices if is_seam_edge(shape, shape.getElement('Edge%d' % (i+1)))}
    lookup=None
    result=set()
    # A known face index already tells which faces are curved; a converted
    # part of flat triangles then needs no pass over its faces at all.
    index = face_index(shape, build=False)
    curved = shape.Faces if index is None else [f for f, flat in zip(index.faces, index.planar) if not flat]
    for face in curved:
        # A plane has no periodic parameter seam. Imported triangulated solids
        # are mostly planar; do not materialize all their boundary wrappers.
        if isinstance(face.Surface, Part.Plane):continue
        for edge in face.Edges:
            if not edge.isSeam(face):continue
            if lookup is None:
                lookup={}
                for index,original in enumerate(shape.Edges):
                    lookup.setdefault(hash(original),[]).append((index,original))
            result.update(i for i,original in lookup.get(hash(edge),()) if original.isSame(edge))
    return result if indices is None else result.intersection(indices)


def is_seam_edge(shape, edge):
    """A periodic surface uses this edge to join to itself, not another face."""
    return any(edge.isSeam(face) for face in shape.ancestorsOfType(edge, Part.Face))


def merge_coplanar_face_group(flist, expected_area=None, ref_face=None):
    """Merge a list of coplanar faces into a single face, preserving area and orientation."""
    if not flist:
        raise ValueError("No faces to merge.")
    if len(flist) == 1:
        return flist[0]

    if ref_face is None:
        ref_face = max(flist, key=lambda f: f.Area)
    ref_norm = face_normal(ref_face)
    ref_surf = getattr(ref_face, "Surface", None)

    area_tol = max(0.01, expected_area * 1e-4) if expected_area is not None else 0.05

    def check_face(candidate):
        if candidate is None or len(candidate.Faces) != 1:
            return None
        res_f = candidate.Faces[0]
        if face_normal(res_f).dot(ref_norm) < 0:
            res_f.reverse()
        if expected_area is not None and abs(res_f.Area - expected_area) > area_tol:
            return None
        return res_f

    # Tier 1: Try direct makeShell without copy so original OCC edge topology is preserved for replaceShape
    for sew_tol in (None, 0.001, 0.01, 0.05):
        try:
            shell = Part.makeShell(flist)
            if sew_tol is not None:
                shell.sewShape(sew_tol)
            else:
                shell.sewShape()
            res = check_face(shell.removeSplitter())
            if res is not None:
                return res
        except Exception:
            pass

    # Tier 2: Unify planar surfaces onto ref_surf and align normal vectors
    aligned = []
    for f in flist:
        fc = None
        if isinstance(ref_surf, Part.Plane) and isinstance(getattr(f, "Surface", None), Part.Plane):
            try:
                cand_f = Part.Face(ref_surf, f.Wires)
                if abs(cand_f.Area - f.Area) <= max(1e-3, f.Area * 1e-4):
                    fc = cand_f
            except Exception:
                fc = None
        if fc is None:
            fc = f.copy()
        if face_normal(fc).dot(ref_norm) < 0:
            fc.reverse()
        aligned.append(fc)

    for sew_tol in (None, 0.001, 0.01, 0.05, 0.1):
        try:
            shell = Part.makeShell(aligned)
            if sew_tol is not None:
                shell.sewShape(sew_tol)
            else:
                shell.sewShape()
            res = check_face(shell.removeSplitter())
            if res is not None:
                return res
        except Exception:
            pass

    # Tier 2: fuse + removeSplitter (with tolerances)
    for fuse_tol in (None, 0.001, 0.01, 0.05, 0.1):
        try:
            fused = aligned[0]
            for other_f in aligned[1:]:
                if fuse_tol is not None:
                    fused = fused.fuse(other_f, fuse_tol).removeSplitter()
                else:
                    fused = fused.fuse(other_f).removeSplitter()
            res = check_face(fused)
            if res is not None:
                return res
        except Exception:
            pass

    # Tier 3: generalFuse + removeSplitter
    for gf_tol in (0.0, 0.001, 0.01, 0.05, 0.1):
        try:
            gf, _ = aligned[0].generalFuse(aligned[1:], gf_tol)
            res = check_face(gf.removeSplitter())
            if res is not None:
                return res
        except Exception:
            pass

    # Tier 4: Reconstruct planar face from boundary wires of the sewn shell
    for sew_tol in (0.05, 0.01, 0.1, 0.001):
        try:
            shell = Part.makeShell(aligned)
            shell.sewShape(sew_tol)
            b_edges = [e for e in shell.Edges if len(shell.ancestorsOfType(e, Part.Face)) == 1]
            if b_edges:
                compound = Part.makeCompound(b_edges)
                wires = list(compound.connectEdgesToWires(True).Wires)
                if wires:
                    def wire_area(w):
                        try:
                            return Part.Face(w).Area
                        except Exception:
                            return w.BoundBox.XLength * w.BoundBox.YLength
                    wires.sort(key=wire_area, reverse=True)
                    rebuilt = Part.Face(wires)
                    res = check_face(rebuilt)
                    if res is not None:
                        return res
        except Exception:
            pass

    # Tier 5: A boundary twisted by less than the modeling precision, such as
    # a converted wall split into two triangles. Keep its own edges, so the
    # neighbors stay connected, on the boundary's best-fit plane.
    try:
        boundary = [edge for face in flist for edge in face.Edges
                    if sum(1 for other in flist for mine in other.Edges if mine.isSame(edge)) == 1]
        wires = list(Part.makeCompound(boundary).connectEdgesToWires(False).Wires) if boundary else []
        points = [vertex.Point for wire in wires for vertex in wire.Vertexes]
        if wires and len(points) >= 3:
            import numpy as np
            xyz = np.asarray([tuple(point) for point in points])
            center = xyz.mean(axis=0)
            normal = np.linalg.svd(xyz - center)[2][-1]
            precision = modeling_precision()
            if float(np.max(np.abs((xyz - center) @ normal))) <= precision:
                plane = Part.Plane(V(*center), V(*normal))
                wires.sort(key=lambda wire: wire.BoundBox.DiagonalLength, reverse=True)
                rebuilt = Part.Face(plane, wires)
                rebuilt.fix(1e-7, 1e-7, precision)
                if rebuilt.isValid():
                    res = check_face(rebuilt)
                    if res is not None:
                        return res
    except Exception:
        pass

    raise ValueError("Those faces could not be merged into one face.")


def close_holes(shape, removed, selected_edges=()):
    """Delete a solid's hole walls and fill the space they bounded.

    Every loop left open by the removed faces is closed so the part stays a
    solid, as when deleting a hole's wall in SketchUp closes the hole:

    - a hole loop in a remaining flat face: that face covers the opening;
    - the outline of a remaining flat face, such as the step of a counterbore
      or the bottom of a blind hole: the face is filled in, and any holes it
      had become the caps of what continues beyond it;
    - any other flat loop, such as where the rest of a bore carries on: a new
      flat cap closes it, so that rest becomes a blind hole.

    The removed faces must leave the faces around them at an angle; a region
    drawn on a face, such as a disk, still opens the face. Selected edges may
    only be rims or seams of the removed faces. Return None when the removed
    faces cannot be closed this way, so the caller's plain erase applies.
    """
    faces, edges = shape.Faces, shape.Edges
    removed = set(removed)
    owners = {}
    for i, face in enumerate(faces):
        for edge in face.Edges:
            owners.setdefault(hash(edge), []).append((edge, i))

    def faces_of(edge):
        return {i for other, i in owners.get(hash(edge), ()) if other.isSame(edge)}
    for index in selected_edges:
        if not faces_of(edges[index]) & removed:
            return None
    boundary = []
    for i in removed:
        for edge in faces[i].Edges:
            outside = faces_of(edge) - removed
            if not outside or any(edge.isSame(known) for known in boundary):
                continue
            # A region drawn on the face itself, such as a disk, is not a
            # wall: deleting it opens the face as before.
            if any(coplanar(faces[a], faces[b]) for a in faces_of(edge) & removed for b in outside):
                return None
            boundary.append(edge)
    if not boundary:
        return None

    def same_loop(wire, loop):
        return len(wire.Edges) == len(loop) and all(any(e.isSame(x) for x in loop) for e in wire.Edges)
    dropped, filled, caps = {}, set(), []
    for loop in Part.sortEdges(boundary):
        wire = Part.Wire(loop)
        if not wire.isClosed():
            return None
        neighbours = {j for edge in loop for j in faces_of(edge) - removed}
        handled = False
        if len(neighbours) == 1:
            j = next(iter(neighbours))
            face = faces[j]
            if isinstance(face.Surface, Part.Plane):
                natural = face.reversed() if face.Orientation == 'Reversed' else face
                match = next((w for w in natural.Wires if same_loop(w, loop)), None)
                if match is not None and match.isSame(natural.OuterWire):
                    filled.add(j)
                    handled = True
                elif match is not None:
                    dropped.setdefault(j, []).append(match)
                    handled = True
        if not handled:
            # The loop runs along curved or several faces: close it with a
            # new flat cap, facing away from the removed wall.
            try:
                cap = Part.Face(wire)
            except Part.OCCError:
                return None
            if not isinstance(cap.Surface, Part.Plane) or not cap.isValid():
                return None
            caps.append((cap, loop))

    def away_from_wall(face, loop):
        wall = [faces[i] for i in removed if any(faces_of(edge) & {i} for edge in loop)]
        inside = sum((f.CenterOfMass for f in wall), V()) * (1.0 / max(1, len(wall)))
        if (inside - face.CenterOfMass).dot(face.normalAt(0, 0)) > 0:
            face.reverse()
        return face

    replacements, added = [], [away_from_wall(cap, loop) for cap, loop in caps]
    for j in filled:
        face = faces[j]
        natural = face.reversed() if face.Orientation == 'Reversed' else face
        # The face's own holes now open onto the filled space: cap each one.
        for inner in natural.Wires:
            if inner.isSame(natural.OuterWire) or any(inner.isSame(w) for w in dropped.get(j, ())):
                continue
            try:
                cap = Part.Face(Part.Wire(inner.Edges))
            except Part.OCCError:
                return None
            added.append(away_from_wall(cap, natural.OuterWire.Edges))
    for j, holes in dropped.items():
        if j in filled:
            continue
        face = faces[j]
        # Rebuild on the surface's own orientation, then give the cover the
        # orientation the solid uses for this face.
        natural = face.reversed() if face.Orientation == 'Reversed' else face
        kept = [wire for wire in natural.Wires if not any(wire.isSame(hole) for hole in holes)]
        try:
            covered = Part.Face(natural.Surface, kept)
        except Part.OCCError:
            return None
        patches = sum(Part.Face(Part.Wire(wire.Edges)).Area for wire in holes)
        if not covered.isValid() or abs(covered.Area - face.Area - patches) > max(1e-6, face.Area * 1e-6):
            return None
        if face.Orientation == 'Reversed':
            covered.reverse()
        replacements.append((face, covered))

    def solid_of(candidate):
        solids = candidate.Solids if candidate.ShapeType != 'Shell' else [Part.makeSolid(candidate)]
        if len(solids) != 1 or not solids[0].isClosed():
            return None
        solid = solids[0]
        if solid.Volume < 0:
            solid.reverse()
        return solid if solid.isValid() else None
    gone = [faces[i] for i in removed | filled]
    rest = [next((c for f, c in replacements if f.isSame(face)), face)
            for i, face in enumerate(faces) if i not in removed and i not in filled]
    if not rest:
        # The removed faces were the whole outside, not a hole's wall.
        return None
    solid = None
    if not added:
        try:
            solid = solid_of(shape.replaceShape(replacements).removeShape(gone))
        except Exception:  # OCC reports a failed rebuild in several types
            pass
    if solid is None:
        try:
            shell = Part.makeShell(rest + added)
            shell.fix(1e-7, 1e-7, 1e-7)
            solid = solid_of(shell)
        except Exception:
            return None
    # Closing holes only ever adds material.
    if solid is None or solid.Volume <= shape.Volume - max(1e-6, shape.Volume * 1e-7):
        return None
    return solid


def fold_step_slivers(shape, chosen, tolerance=PULL_CONTACT_TOLERANCE):
    """Fold hairline step faces beside chosen edges; return (shape, names) or None.

    A Push/Pull that stopped a few nanometres short of an existing level left
    a wall narrower than the tolerance between two faces that look like one
    line apart. Deleting that line should merge the faces, as it does where
    no step was left; erasing the wall instead opens the solid.
    """
    def sliver(face):
        lengths = [edge.Length for edge in face.Edges]
        return (isinstance(face.Surface, Part.Plane) and max(lengths) > tolerance
                and face.Area < tolerance * max(lengths))
    if not any(sliver(face) for edge in chosen for face in shape.ancestorsOfType(edge, Part.Face)):
        return None
    from ..repair.slivers import collapse
    try:
        folded, report = collapse(shape, tolerance)
    except ValueError:
        return None
    if not report.get('removed_faces') or not folded.isValid():
        return None
    names = []
    for edge in chosen:
        points = [Part.Vertex(edge.valueAt(edge.FirstParameter + t * (edge.LastParameter - edge.FirstParameter)))
                  for t in (0, .5, 1)]
        matches = [i for i, other in enumerate(folded.Edges)
                   if all(other.distToShape(point)[0] <= tolerance for point in points)
                   and abs(other.Length - edge.Length) <= 2 * tolerance]
        if len(matches) != 1:
            return None
        names.append("Edge%d" % (matches[0] + 1))
    return folded, names


def erase_elements(shape, names):
    """Erase selected native edges/faces; return None when nothing remains.

    Shared planar edges merge only their adjoining regions. Surface seams are
    kept; other face edges remove their incident faces, producing open surfaces.
    All selections are resolved against the original topology before rebuilding.
    """
    # Validate the completed edit, not both the entire input and output. The
    # input topology is read-only; a full native check can cost a second on an
    # imported shell before any work has started.
    if shape.isNull():
        raise ValueError("The operation would create invalid geometry.")
    solids = shape.Solids
    original_faces, edges = shape.Faces, shape.Edges
    if len(solids) > 1 or (solids and len(original_faces) != len(solids[0].Faces)):
        raise ValueError("Separate compound solids or mixed solid/surface objects before deleting edges.")
    native_solid = shape.ShapeType == 'Solid' or (len(solids) == 1 and len(original_faces) == len(solids[0].Faces))
    faces = original_faces if native_solid else coinc.unique(original_faces)
    face_lookup = None
    selected_edges, removed_faces = set(), set()
    for name in names:
        match = re.fullmatch(r"(Edge|Face)([1-9][0-9]*)", name)
        if not match:
            raise ValueError("Select an edge, a face, or a whole object in the Model tree.")
        kind, number = match.groups()
        index = int(number) - 1
        if index >= len(edges if kind == "Edge" else original_faces):
            raise ValueError("The selection is no longer current. Select the edge or face again.")
        if kind == "Face" and not native_solid:
            if face_lookup is None:
                face_lookup = coinc.Index(faces)
            index = next(face_lookup.matches(original_faces[index]))
        (selected_edges if kind == "Edge" else removed_faces).add(index)
    if not selected_edges and not removed_faces:
        raise ValueError("Select an edge or face to delete.")
    selected_edges.difference_update(seam_indices(shape, selected_edges))
    if not selected_edges and not removed_faces:
        return shape.copy()
    if not removed_faces:
        folded = fold_step_slivers(shape, [edges[i] for i in sorted(selected_edges)])
        if folded is not None and len(folded[0].Faces) < len(original_faces):
            return erase_elements(*folded)
    if native_solid and removed_faces:
        filled = close_holes(shape, removed_faces, selected_edges)
        if filled is not None:
            return filled

    # Union only across selected coplanar boundaries. Unselected divisions stay.
    parents = list(range(len(faces)))

    def root(index):
        while parents[index] != index:
            index = parents[index]
        return index

    native = {}
    local = native_solid and len(selected_edges) <= 8
    if local:
        face_ids = {}
        for i, face in enumerate(faces):
            face_ids.setdefault(hash(face), []).append(i)
    elif native_solid:
        for i, face in enumerate(faces):
            for edge in face.Edges:
                native.setdefault(hash(edge), []).append((edge, i))
    else:
        selected = sorted(selected_edges)
        owners = dict(zip(selected, coinc.face_owners(faces, [edges[i] for i in selected])))
    internal_replacements = {}
    internal_edges = {}
    for index in selected_edges:
        if local:
            adjacent = sorted({i for face in shape.ancestorsOfType(edges[index], Part.Face)
                               for i in face_ids.get(hash(face), ()) if faces[i].isSame(face)})
        elif native_solid:
            adjacent = sorted({i for edge, i in native.get(hash(edges[index]), ())
                               if edge.isSame(edges[index])})
        else:
            adjacent = sorted(owners[index])

        if len(adjacent) == 1:
            edge_to_match = edges[index]
            face = faces[adjacent[0]]
            is_internal = any(fe.isSame(edge_to_match) and fe.Orientation in ('Internal', 'External') for fe in face.Edges)
            if not is_internal:
                for other_i, other_face in enumerate(faces):
                    if other_i == adjacent[0]:
                        continue
                    if any(edge_to_match.isSame(fe) or coinc.same(edge_to_match, fe) for fe in other_face.Edges):
                        adjacent.append(other_i)
                        break

        merged_any = False
        if len(adjacent) == 2 and coplanar(faces[adjacent[0]], faces[adjacent[1]]):
            parents[root(adjacent[1])] = root(adjacent[0])
            merged_any = True
        elif len(adjacent) > 2:
            # As in SketchUp, coplanar faces on the edge merge and every other
            # face that loses the edge is erased with it.
            paired = set()
            for i_idx in range(len(adjacent)):
                for j_idx in range(i_idx + 1, len(adjacent)):
                    f1_idx, f2_idx = adjacent[i_idx], adjacent[j_idx]
                    if coplanar(faces[f1_idx], faces[f2_idx]):
                        parents[root(f2_idx)] = root(f1_idx)
                        paired.update((f1_idx, f2_idx))
                        merged_any = True
            if merged_any and not (native_solid or solids):
                removed_faces.update(set(adjacent) - paired)
        if not merged_any:
            if len(adjacent) == 1 and (native_solid or solids or shape.ShapeType in ('Shell', 'Face')):
                internal_edges.setdefault(adjacent[0], []).append(edges[index])
            else:
                removed_faces.update(adjacent)

    for face_idx, to_remove in internal_edges.items():
        if face_idx in removed_faces:
            continue
        face = faces[face_idx]
        try:
            modified = face.removeShape(to_remove)
            valid_ok = modified.isValid() if face.isValid() else bool(modified.Wires)
            if valid_ok and abs(modified.Area - face.Area) <= max(1e-4, face.Area * 1e-5):
                internal_replacements[face_idx] = modified
                continue
        except Exception:
            pass
        removed_faces.add(face_idx)

    groups = {}
    for index in range(len(faces)):
        groups.setdefault(root(index), []).append(index)
    remaining_faces, replacements, redundant = [], [], []
    for indices in groups.values():
        # If another selected edge/face removes part of a merged region, erase
        # that region as a whole so no explicitly selected edge survives.
        if removed_faces.intersection(indices):
            removed_faces.update(indices)
            continue
        if len(indices) == 1:
            idx = indices[0]
            if idx in internal_replacements:
                mod_face = internal_replacements[idx]
                remaining_faces.append(mod_face)
                replacements.append((faces[idx], mod_face))
            else:
                remaining_faces.append(faces[idx])
            continue
        flist = [internal_replacements.get(index, faces[index]) for index in indices]
        expected_area = sum(faces[index].Area for index in indices)
        face = merge_coplanar_face_group(flist, expected_area, faces[indices[0]])
        remaining_faces.append(face)
        replacements.append((faces[indices[0]], face))
        redundant.extend(faces[i] for i in indices[1:])

    # Preserve pre-existing loose edges, excluding those explicitly selected.
    loose_edges = [edge for edge in ([] if shape.ShapeType in ('Solid', 'Shell', 'Face') else coinc.loose_edges(shape))
                   if not any(coinc.same(edge, edges[i]) for i in selected_edges)]
    parts = []
    verified_solid = False
    verified_surface = False
    if remaining_faces:
        if solids and not removed_faces:
            # Replace only the merged regions of a native solid. This retains
            # the existing shells, cavities and untouched native subshapes.
            # Both operations return new topology without mutating the source.
            was_valid = shape.isValid()
            was_closed = shape.isClosed() or (shape.Solids and shape.Solids[0].isClosed())
            candidate = None
            if native_solid:
                try:
                    candidate = shape.replaceShape(replacements).removeShape(redundant)
                except Exception:
                    candidate = None
            if candidate is None or (was_closed and not candidate.isClosed()) or (was_valid and not candidate.isValid()):
                for sew_tol in (0.05, 0.01, None):
                    try:
                        sh = Part.makeShell(remaining_faces)
                        if sew_tol is not None:
                            sh.sewShape(sew_tol)
                        cand = Part.makeSolid(sh)
                        if (not was_closed or cand.isClosed()) and (not was_valid or cand.isValid()):
                            candidate = cand
                            break
                    except Exception:
                        pass
            # A merged face can have different boundary subdivisions from its
            # neighbors. Sewing the entire shell can disconnect unrelated
            # periodic seams and tiny valid edges. A native boolean rebuild
            # reconciles those boundaries while retaining every face region.
            if candidate is None or (was_closed and not candidate.isClosed()) or (was_valid and not candidate.isValid()):
                for gf_tol in (0.0, 0.01, 0.05):
                    try:
                        unified, _ = remaining_faces[0].generalFuse(remaining_faces[1:], gf_tol)
                        if len(unified.Faces) == len(remaining_faces):
                            surface = Part.makeShell(unified.Faces)
                            cand = Part.makeSolid(surface)
                            if (not was_closed or cand.isClosed()) and (not was_valid or cand.isValid()):
                                candidate = cand
                                break
                    except Exception:
                        pass
            if candidate is None:
                raise ValueError("Could not rebuild solid after deleting edge.")
            volume = candidate.Volume
            if len(candidate.Solids) != 1 or volume < EPS:
                raise ValueError("Merging faces must preserve one non-empty solid.")
            surface = candidate
            if was_closed and not surface.isClosed():
                raise ValueError("Merging faces must preserve a closed solid.")
            original_volume = shape.Volume
            if abs(volume - original_volume) > max(0.01, abs(original_volume) * 1e-4):
                raise ValueError("Merging faces must preserve the solid's volume.")
            verified_solid = True
        else:
            surface = None
            if shape.ShapeType == 'Shell' and len(faces) == len(original_faces):
                # Preserve untouched shell boundaries, just as for a solid.
                # Independent/duplicate surfaces keep the assembly fallback.
                erased = redundant + [faces[i] for i in removed_faces]
                candidate = shape.replaceShape(replacements) if replacements else shape
                if erased:
                    candidate = candidate.removeShape(erased)
                if (len(candidate.Faces) == len(remaining_faces) and candidate.isValid()
                        and abs(candidate.Area - sum(f.Area for f in remaining_faces))
                        <= max(1e-4, shape.Area * 1e-5)):
                    surface = candidate
                    verified_surface = True
            if surface is None:
                surface = Part.makeShell(remaining_faces)
                surface.sewShape()
        if removed_faces and surface.ShapeType == "Shell" and surface.isClosed():
            # Deleting unwanted intersection regions can close the remaining
            # surface into a cavity. Promote only a valid manifold shell.
            solid = Part.makeSolid(surface)
            if solid.Volume < 0: solid.reverse()
            if solid.isValid() and solid.isClosed() and solid.Volume > EPS:
                # Faces carried over may bring their own check findings, such
                # as hairline edges elsewhere on a converted part. Refuse only
                # findings the deletion itself adds.
                from ..repair.healing import check_errors
                if check_errors(solid) > check_errors(shape):
                    solid.check(True)
                surface = solid
        parts.append(surface)
    parts.extend(loose_edges)
    if not parts:
        return None
    if all(getattr(p, "ShapeType", "") == "Edge" for p in parts) and len(parts) > 1:
        try:
            result = Part.Wire(parts)
        except Exception:
            result = Part.makeCompound(parts)
    else:
        result = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
    # The native replacement branches already validated this result. Do not run
    # the complete native check again when no loose geometry was appended.
    return result if (verified_solid or verified_surface) and len(parts) == 1 else validate(result)


_volumes = []


def volume(shape):
    """shape.Volume, remembered for the last few exact shapes.

    A divide measures its result, and the next divide of the same part
    measures that stored shape again as its source: 0.3 s each on a fitted
    part. isEqual requires the same TShape, Location and Orientation, so a
    moved, reversed (negative) or rebuilt shape is measured afresh. The key
    is a new wrapper: moving or reversing the caller's own shape later does
    not move the key with it. Volume integrates the faces' surfaces within
    their trims; tolerance changes made in place through a shared sub-shape
    leave it unchanged.
    """
    for kept, value in _volumes:
        if kept.isEqual(shape):
            return value
    value = shape.Volume
    _volumes[:] = [(Part.Shape(shape), value)] + _volumes[:3]
    return value


def validate(shape, solid=False):
    if shape.isNull() or not shape.isValid():
        raise ValueError("The operation would create invalid geometry.")
    if solid and (len(shape.Solids) != 1 or volume(shape) < EPS):
        raise ValueError("The result must be one non-empty solid. Try a shorter distance.")
    return shape


def matching_support_face(solid, profile):
    """Resolve by geometry on every commit, never by a stale FaceN index."""
    n = face_normal(profile)
    p_box = profile.BoundBox
    for face in solid.Faces:
        try:
            fn = face_normal(face)
        except ValueError:
            continue
        if abs(fn.dot(n)) < 1 - 1e-6:
            continue
        if abs((face.CenterOfMass - profile.CenterOfMass).dot(n)) > 1e-5:
            continue
        f_box = face.BoundBox
        if not (f_box.XMin - 1e-4 <= p_box.XMax and f_box.XMax + 1e-4 >= p_box.XMin and
                f_box.YMin - 1e-4 <= p_box.YMax and f_box.YMax + 1e-4 >= p_box.YMin and
                f_box.ZMin - 1e-4 <= p_box.ZMax and f_box.ZMax + 1e-4 >= p_box.ZMin):
            continue
        overlap = face.common(profile)
        if abs(overlap.Area - profile.Area) <= max(1e-6, profile.Area * 1e-7):
            return face
    raise ValueError("The profile must lie completely on one current flat face of its support.")


def profile_support_faces(solid, profile):
    """The faces a drawn profile imprints on, and the region it encloses there.

    As in SketchUp, only the outline must lie on the face: a profile drawn
    around a hole imprints the face, and the hole inside stays a hole. The
    region is the part of the profile on the face. An outline may also cross
    regions drawn earlier on the same flat face; it then imprints every
    coplanar face it covers, and the region is None. Returns (faces, region).
    """
    try:
        return [matching_support_face(solid, profile)], profile
    except ValueError:
        pass
    n = face_normal(profile)
    outline = Part.makeCompound(profile.Edges)
    tolerance = max(1e-6, outline.Length * 1e-7)
    level = []
    for face in solid.Faces:
        try:
            fn = face_normal(face)
        except ValueError:
            continue
        if abs(fn.dot(n)) < 1 - 1e-6 or abs((face.CenterOfMass - profile.CenterOfMass).dot(n)) > 1e-5:
            continue
        if not face.BoundBox.intersect(profile.BoundBox):
            continue
        level.append(face)
        if abs(face.common(outline).Length - outline.Length) > tolerance:
            continue
        region = face.common(profile)
        if len(region.Faces) == 1 and region.Area > EPS:
            return [face], region.Faces[0]
    # Across earlier divisions: the outline lies on the faces together, and
    # each face it imprints shares some of the area it encloses.
    faces = [face for face in level if face.common(profile).Area > EPS]
    if len(faces) > 1 and outline.cut(Part.makeCompound(faces)).Length <= tolerance:
        return faces, None
    raise ValueError("The profile must lie completely on the current flat faces of its support.")


def pull_source(shape, face, include_remainder=True):
    """Resolve a picked face and separate geometry outside its extrusion.

    A closed, single-shell surface represents a volume even if cleanup stored
    it as a Shell. An open collection supplies only its picked face; the other
    faces and pre-existing loose edges must be retained by the document writer.
    """
    # For an open native shell, validate the extracted face and remainder
    # below. Checking the entire source as well repeats the expensive check.
    if include_remainder and shape.ShapeType != 'Shell':
        if shape.isValid():
            validate(shape)
        elif not shape.Solids or len(shape.Solids) != 1 or shape.Volume < EPS:
            validate(shape)
    face_normal(face)
    # A native solid already has unique faces. Comparing every pair is
    # quadratic on converted meshes and discards their reliable topology IDs.
    original_faces = shape.Faces
    faces = original_faces if shape.ShapeType == 'Solid' or not include_remainder else coinc.unique(original_faces)
    selected = next((current for current in faces if current.isSame(face)), None)
    if selected is None:
        selected = next((current for current in faces if coinc.same(current, face)), None)
    if selected is None:
        raise ValueError("This face is no longer part of the shape. Select it again.")
    if shape.Solids:
        if len(shape.Solids) != 1 or len(shape.Faces) != len(shape.Solids[0].Faces):
            raise ValueError("Separate compound solids or mixed solid/surface objects before Push/Pull.")
        base = shape.Solids[0].copy() if include_remainder else shape.Solids[0]
        selected_in_base = next((c for c in base.Faces if c.isSame(selected) or coinc.same(c, selected)), selected)
        remainder = coinc.assemble([], coinc.loose_edges(shape)) if include_remainder else None
        return base, selected_in_base, remainder


    base = selected.copy() if include_remainder else selected
    if include_remainder:
        validate(base)
    shells = shape.Shells
    if len(shells) == 1 and shells[0].isClosed() and len(shells[0].Faces) == len(faces):
        base = Part.makeSolid(shells[0].copy())
        base.fix(1e-7, 1e-7, 1e-7)
        if base.Volume < 0:
            base.reverse()
        validate(base, solid=True)
        selected = next(current for current in base.Faces if coinc.same(current, selected))
        remainder = coinc.assemble([], coinc.loose_edges(shape)) if include_remainder else None
        return base, selected, remainder
    if not include_remainder:
        return base, selected, None
    if shape.ShapeType == 'Shell' and len(faces) == len(original_faces) and len(faces) > 1:
        remainder = shape.removeShape([selected])
        if len(remainder.Faces) == len(faces)-1 and remainder.isValid():
            return base, selected, remainder.Faces[0] if len(remainder.Faces) == 1 else remainder
    remaining = [current for current in faces if not coinc.same(current, selected)]
    return base, selected, coinc.assemble(remaining, coinc.loose_edges(shape))


def plan_push_pull(shape, face, distance):
    """Return the edited shape and untouched remainder, without document writes."""
    if not math.isfinite(distance) or abs(distance) < EPS:
        raise ValueError("Enter a non-zero distance.")
    source_valid = shape.isValid()
    base, selected, remainder, offset = pull_setup(shape, face)
    if offset and abs(distance + offset) <= EPS:
        return base, remainder
    return push_pull(base, selected, distance + offset, was_valid=source_valid), remainder


def pull_setup(shape, face, include_remainder=True):
    """Resolve normal modeling or a cap on a through-surface extension."""
    if not shape.Solids and len(shape.Faces) > 1:
        recovered = recover_extended_cap(shape, face)
        if recovered is not None:
            base, selected, offset = recovered
            return base, selected, (coinc.assemble([], coinc.loose_edges(shape)) if include_remainder else None), offset
    base, selected, remainder = pull_source(shape, face, include_remainder)
    return base, selected, remainder, 0.0


@dataclass
class OppositeFace:
    distance: float
    faces: tuple


def opposite_face(shape, profile, normal=None):
    """First fully covered, parallel exit reached through continuous material.

    Coplanar face divisions can collectively cover the footprint. A bounding
    box or a center ray alone cannot prove that an entire profile meets a face.
    Open surfaces and partially covered/oblique exits have no exact stop.
    An exit tilted by less than the modeling precision across the profile
    still counts: faces made from converted meshes are rarely exactly parallel.
    """
    if len(shape.Solids) != 1:
        return None
    normal = unit(normal if normal is not None else face_normal(profile))
    precision = modeling_precision()
    size = max(profile.BoundBox.DiagonalLength, EPS)
    parallel = math.cos(min(1e-2, precision / size))
    groups = []
    for face in shape.Faces:
        try:
            if face_normal(face).dot(normal) > -parallel:
                continue
        except ValueError:
            continue
        distance = (face.CenterOfMass - profile.CenterOfMass).dot(normal)
        if distance >= -EPS:
            continue
        group = next((group for group in groups if abs(group[0] - distance) <= EPS), None)
        if group is None:
            groups.append((distance, [face]))
        else:
            group[1].append(face)
    for distance, faces in sorted(groups, key=lambda group: group[0], reverse=True):
        moved = profile.copy()
        moved.translate(normal * distance)
        # How far the moved profile lies off the exit plane because of tilt.
        exit_plane = Plane.from_face(faces[0])
        samples = [vertex.Point for vertex in moved.Vertexes] + [
            edge.valueAt(edge.FirstParameter + t * (edge.LastParameter - edge.FirstParameter))
            for edge in moved.Edges for t in (.25, .5, .75)]
        gap = max(abs((point - exit_plane.origin).dot(exit_plane.normal)) for point in samples)
        if gap > precision:
            continue
        cover = Part.makeCompound(faces)
        tolerance = max(1e-7, profile.Area * 1e-8)
        fuzzy = 2 * gap + 1e-7
        covered = moved.common(cover, fuzzy) if gap > 1e-7 else moved.common(cover)
        if abs(covered.Area - profile.Area) > tolerance + profile.Area * gap:
            continue
        swept = profile.extrude(normal * distance)
        if abs(swept.common(shape).Volume - swept.Volume) > max(1e-7, swept.Volume * 1e-8) + profile.Area * gap:
            continue
        return OppositeFace(distance, tuple(faces))
    return None


def level_distance(shape, face, normal, distance, tolerance=PULL_CONTACT_TOLERANCE):
    """The distance that ends face on the nearest level shape already has.

    A distance taken from a picked point can stop a few nanometres short of
    an existing face's plane. The step left behind is a sliver wall that
    later keeps the two faces from merging, so a level within the tolerance
    wins. Only faces parallel across their whole extent count, and the face's
    own plane never does.
    """
    start = face.CenterOfMass.dot(normal)
    target, best, gap = start + distance, distance, tolerance
    for other in shape.Faces:
        if not isinstance(other.Surface, Part.Plane) or abs(other.Surface.Axis.dot(normal)) < 1 - 1e-9:
            continue
        levels = [vertex.Point.dot(normal) for vertex in other.Vertexes]
        if not levels or max(levels) - min(levels) > 1e-6:
            continue
        level = (max(levels) + min(levels)) / 2
        if abs(level - target) <= gap and abs(level - start) > tolerance:
            best, gap = level - start, abs(level - target)
    return best


def prism_walls(profile, delta):
    moved = profile.copy()
    moved.translate(delta)
    return [face for face in profile.extrude(delta).Faces
            if not coinc.same(face, profile) and not coinc.same(face, moved)]


def extend_past_face(shape, profile, normal, distance, stop):
    """Keep the far face while continuing the cavity walls and moving cap.

    The far face intersects the extended walls, just as in face modeling.
    Store native faces instead of pretending that this is a manifold solid.
    No original shape or face-number metadata is saved with the object.
    """
    at_stop = profile.copy()
    at_stop.translate(normal * stop.distance)
    outside = at_stop.extrude(normal * (distance - stop.distance))
    cut = shape.cut(profile.extrude(normal * stop.distance))
    if not cut.Faces:
        # Pushing an entire prism past its base turns it into a prism on the
        # other side. There is no surrounding material to preserve here.
        return validate(outside, solid=True).Solids[0]
    faces = []
    exit_cover = Part.makeCompound(stop.faces)
    for face in cut.Faces:
        try:
            on_exit = (abs(abs(face_normal(face).dot(normal)) - 1) < 1e-7 and
                       abs((face.CenterOfMass - at_stop.CenterOfMass).dot(normal)) <= EPS and
                       abs(face.common(exit_cover).Area - face.Area) <= max(1e-7, face.Area * 1e-8))
        except ValueError:
            on_exit = False
        if not on_exit:
            faces.append(face)
    faces.extend(face.copy() for face in stop.faces)
    for wall in prism_walls(at_stop, normal * (distance - stop.distance)):
        wall.reverse()  # Continue the cavity's inward-facing wall orientation.
        faces.append(wall)
    cap = profile.copy()
    cap.translate(normal * distance)
    if face_normal(cap).dot(normal) < 0:
        cap.reverse()
    faces.append(cap)
    return validate(Part.makeCompound(faces))


def recover_extended_cap(shape, cap):
    """Recognize a complete prism wall from a cap back to a planar opening.

    Reconstruct its closed base from current geometry so an extended cap can
    be pushed back to a hole/pocket, even after save/reopen or Move/Copy. Only
    a complete wall and a valid closed base qualify; ordinary open faces keep
    their existing independent extrusion behavior.
    """
    normal = face_normal(cap)
    faces = shape.Faces
    if not any(face.isSame(cap) for face in faces) and not any(coinc.same(face, cap) for face in faces):
        return None
    candidates = []
    for face in faces:
        try:
            if face_normal(face).dot(normal) < 1 - 1e-7:
                continue
        except ValueError:
            continue
        height = (face.CenterOfMass - cap.CenterOfMass).dot(normal)
        if height > EPS and not any(abs(height - value) <= EPS for value in candidates):
            candidates.append(height)
    if not candidates:
        return None
    # A complete extension must have existing geometry on every wall surface.
    # Those surfaces do not depend on height. Reject ordinary imported faces
    # before trying thousands of face/height boolean intersections.
    possible = []
    for face in faces:
        if coinc.same(face, cap):
            continue
        plane = isinstance(face.Surface, Part.Plane)
        possible.append((face, face_normal(face) if plane else None, face.CenterOfMass if plane else None))
    wall_ids = set()
    for wall in prism_walls(cap, normal):
        plane = isinstance(wall.Surface, Part.Plane)
        wn, center = (face_normal(wall), wall.CenterOfMass) if plane else (None, None)
        if plane:
            matching = [i for i, (face, fn, point) in enumerate(possible)
                        if fn is not None and abs(fn.dot(wn)) > 1-1e-7
                        and abs((point-center).dot(wn)) < EPS]
        else:
            matching = [i for i, (face, _, _) in enumerate(possible) if type(face.Surface) is type(wall.Surface)]
        if not matching:
            return None
        wall_ids.update(matching)
    # Only faces fully contained in the prism-wall bounds can be consumed.
    # Imported shells contain thousands of unrelated faces; do not boolean
    # intersect each one at every possible cap height.
    bounded = [(face, face.BoundBox) for i, (face, _, _) in enumerate(possible) if i in wall_ids]
    untouched = [face for i, (face, _, _) in enumerate(possible) if i not in wall_ids]
    for height in sorted(candidates):
        start = cap.copy()
        start.translate(normal * height)
        walls = Part.makeCompound(prism_walls(cap, normal * height))
        wall_box = walls.BoundBox
        consumed, rest = [], list(untouched)
        for face, box in bounded:
            if any(getattr(box, axis+'Min') < getattr(wall_box, axis+'Min')-EPS
                   or getattr(box, axis+'Max') > getattr(wall_box, axis+'Max')+EPS for axis in 'XYZ'):
                rest.append(face)
                continue
            tolerance = max(1e-7, face.Area * 1e-8)
            if abs(face.common(walls).Area - face.Area) <= tolerance:
                consumed.append(face)
            else:
                rest.append(face)
        if abs(sum(face.Area for face in consumed) - walls.Area) > max(1e-7, walls.Area * 1e-8):
            continue
        # Its opening must be empty and bounded by the remaining geometry.
        if start.common(Part.makeCompound(rest)).Area > max(1e-7, start.Area * 1e-8):
            continue
        try:
            surface = Part.makeShell(rest + [start])
            surface.sewShape()
        except Part.OCCError:
            continue
        if not surface.isValid() or not surface.isClosed():
            continue
        base = Part.makeSolid(surface)
        base.fix(EPS, EPS, EPS)
        if base.Volume < 0:
            base.reverse()
        if not base.isValid() or len(base.Solids) != 1 or base.Volume < EPS:
            continue
        # Prove this was a past-face extension, not an ordinary open pocket.
        stop = opposite_face(base, start, normal)
        if stop is not None and -height < stop.distance - EPS:
            return base, start, -height
def clean_solid_faces(shape):
    """Remove leftover internal edges and open/degenerate wires from solid faces."""
    if not shape.Solids:
        return shape
    to_remove = []
    for f in shape.Faces:
        for e in f.Edges:
            if e.Orientation in ('Internal', 'External'):
                to_remove.append(e)
        for w in f.Wires:
            if not w.isClosed() or (len(w.Edges) == 1 and w.Length < 0.01):
                for we in w.Edges:
                    if not any(we.isSame(re) for re in to_remove):
                        to_remove.append(we)
    if to_remove:
        try:
            cand = shape.removeShape(to_remove)
            if cand.Solids and len(cand.Solids) == len(shape.Solids) and abs(cand.Volume - shape.Volume) <= max(0.1, shape.Volume * 1e-4):
                return cand
        except Exception:
            pass
    return shape


def modeling_precision():
    """Details smaller than this many mm are noise, not geometry."""
    from . import preferences
    return preferences.precision()


def thickness(shape):
    """Mean thickness of a solid (2V/A) or width of a face (2A/perimeter)."""
    if shape.ShapeType == "Face":
        # Skip degenerate edges: measuring them can crash FreeCAD.
        perimeter = sum(edge.Length for edge in shape.Edges if not edge.Degenerated)
        return 2 * shape.Area / perimeter if perimeter > EPS else 0.0
    return 2 * abs(shape.Volume) / shape.Area if shape.Area > EPS else 0.0


def drop_noise(result, precision):
    """Discard sliver solids and stray faces thinner than the precision.

    A profile touching a hole along a tiny arc can leave a zero-volume solid
    or a hairline face between the new opening and the hole. Such remnants
    are below what the model represents and must not fail the edit or
    become separate objects. Anything at least ``precision`` thick is kept,
    so a genuinely detached piece still is.
    """
    solids = [s for s in result.Solids if s.Volume > EPS and thickness(s) >= precision]
    if result.ShapeType == 'Solid':
        loose = []  # A solid owns every one of its faces.
    else:
        # Index by native identity: a dense compound would otherwise compare
        # every face with every solid face.
        owned = {}
        for solid in result.Solids:
            for face in solid.Faces:
                owned.setdefault(hash(face), []).append(face)
        loose = [f for f in result.Faces if not any(f.isSame(o) for o in owned.get(hash(f), ()))]
    if not solids or any(thickness(f) >= precision for f in loose):
        return result
    if len(solids) == len(result.Solids) and not loose:
        return result
    return solids[0] if len(solids) == 1 else Part.makeCompound(solids)


def trim_overlapping_walls(shape, face, walls):
    """Cancel prism faces against existing faces lying on the same surface.

    Pushing a ring into a hole sweeps its inner wall along the existing hole
    wall. Keeping both leaves a doubled, zero-thickness wall, so the existing
    face loses the swept span and the prism face keeps only what extends past
    it. Pushing to the far side likewise cancels the moved cap against the
    exit face, opening it. Mesh-converted solids are only nearly planar, so
    faces within the shape's own vertex tolerance count as coincident. One
    inflated vertex must not swallow real strips, so the allowance never
    exceeds the modeling precision.
    """
    fuzzy = min(modeling_precision(), max(1e-6, 2 * max((v.Tolerance for v in shape.Vertexes), default=0)))
    trimmed = {}
    kept = []
    for wall in walls:
        for i, existing in enumerate(shape.Faces):
            if existing.isSame(face) or not wall.Faces:
                continue
            bounds = wall.BoundBox
            bounds.enlarge(fuzzy)
            if not bounds.intersect(existing.BoundBox):
                continue
            current = trimmed.get(i, existing)
            try:
                if current.common(wall, fuzzy).Area <= max(1e-6, wall.Area * 1e-6):
                    continue
                trimmed[i], wall = current.cut(wall, fuzzy), wall.cut(current, fuzzy)
            except Exception:
                continue
        kept.extend(f for f in wall.Faces if f.Area > EPS)
    return kept, [(shape.Faces[i], new) for i, new in trimmed.items()]


def push_pull(shape, face, distance, supported=False, was_valid=None):
    """Extrude one face or edit one solid; plan_push_pull handles collections."""
    if not math.isfinite(distance) or abs(distance) < EPS:
        raise ValueError("Enter a non-zero distance.")
    normal = face_normal(face)
    if was_valid is None:
        was_valid = shape.isValid()
    if shape.Solids:
        if was_valid:
            validate(shape, solid=True)
        else:
            if len(shape.Solids) != 1 or shape.Volume < EPS:
                raise ValueError("The result must be one non-empty solid. Try a shorter distance.")
        if supported:
            normal = face_normal(matching_support_face(shape, face))
        through = False
        if distance < 0:
            stop = opposite_face(shape, face, normal)
            if stop is not None:
                snap_tol = max(modeling_precision(), abs(stop.distance) * 1e-3)
                if abs(distance - stop.distance) <= snap_tol:
                    distance = stop.distance
                    through = True
                elif distance < stop.distance:
                    return extend_past_face(shape, face, normal, distance, stop)
        if not through:
            distance = level_distance(shape, face, normal, distance)
        prism = face.extrude(normal * distance)
        # A through cut ends a hair past the exit, so an exit tilted within
        # the precision cannot leave a skin across the hole. Only air lies
        # beyond the exit face there.
        tool = face.extrude(normal * (distance - modeling_precision())) if through else prism
        # A failed boolean on a damaged solid can return a fragment. The edit
        # never changes more volume than the swept outer profile.
        swept = Part.Face(face.OuterWire).Area * abs(distance)
        swept_tol = swept + max(0.5, swept * 0.05)
        try:
            result = shape.fuse(prism) if distance > 0 else shape.cut(tool)
            if not result.Solids or result.Volume < EPS or abs(result.Volume - shape.Volume) > swept_tol:
                raise ValueError()
        except Exception:
            result = None
            prism_face = next((f for f in prism.Faces if coinc.same(f, face)), None)
            if prism_face is not None:
                rep_faces = [f for f in prism.Faces if not f.isSame(prism_face)] if distance > 0 else [f.reversed() for f in prism.Faces if not f.isSame(prism_face)]
                expected_vol = (shape.Volume + prism.Volume) if distance > 0 else (shape.Volume - prism.Volume)
                vol_tol = max(0.5, min(shape.Volume * 0.05, 50.0))
                rep_faces, substitutions = trim_overlapping_walls(shape, face, rep_faces)
                if substitutions:
                    try:
                        replaced = [face] + [old for old, _ in substitutions]
                        faces = [f for f in shape.Faces if not any(f.isSame(r) for r in replaced)]
                        faces += [f for _, new in substitutions for f in new.Faces if f.Area > EPS] + rep_faces
                        sewn = Part.Compound(faces)
                        sewn.sewShape()
                        if len(sewn.Shells) == 1 and sewn.Shells[0].isClosed():
                            cand = Part.Solid(sewn.Shells[0])
                            if cand.Volume < 0:
                                cand.reverse()
                            if cand.isValid() and abs(cand.Volume - expected_vol) <= vol_tol:
                                result = cand
                    except Exception:
                        pass
                if result is None and not substitutions:
                    try:
                        cand = shape.replaceShape([(face, Part.Compound(rep_faces))])
                        if cand.isValid() and cand.Solids and abs(cand.Volume - expected_vol) <= vol_tol:
                            result = cand
                    except Exception:
                        pass
                if (result is None or not result.Solids or result.Volume < EPS) and not substitutions:
                    try:
                        outer_faces = [f for f in shape.Faces if not f.isSame(face) and not coinc.same(f, face)] + rep_faces
                        shell = Part.makeShell(outer_faces)
                        cand = Part.Solid(shell)
                        if not cand.isValid():
                            cand.fix(1e-6, 1e-6, 1e-6)
                        if cand.isValid() and abs(cand.Volume - expected_vol) <= vol_tol:
                            result = cand
                    except Exception:
                        pass
            if result is None or not result.Solids or result.Volume < EPS:
                adj = [f for f in shape.Faces if not f.isSame(face) and coplanar(f, face) and f.distToShape(face)[0] < 1e-4]
                replacements = []
                for f in adj:
                    fc = f.copy()
                    fc.fix(1e-7, 1e-7, 1e-7)
                    replacements.append((f, fc))
                try:
                    healed = shape.replaceShape(replacements) if replacements else shape
                    if not healed.isValid():
                        healed = shape
                except Exception:
                    healed = shape
                if distance > 0:
                    try:
                        result = healed.fuse(prism)
                        if not result.Solids or result.Volume < EPS:
                            raise ValueError()
                    except Exception:
                        ft = face.copy()
                        ft.translate(-normal * 0.01)
                        tool = ft.extrude(normal * (distance + 0.01))
                        result = shape.fuse(tool) if not healed.isValid() else healed.fuse(tool)
                else:
                    try:
                        result = healed.cut(prism)
                        if not result.Solids or result.Volume < EPS:
                            raise ValueError()
                    except Exception:
                        tool_face = Part.Face(face.OuterWire) if len(face.Wires) > 1 else face
                        ft = tool_face.copy()
                        ft.translate(normal * 0.01)
                        tool = ft.extrude(normal * (distance - 0.02))
                        result = shape.cut(tool) if not healed.isValid() else healed.cut(tool)
                if not result.Solids or result.Volume < EPS:
                    raise ValueError("The operation would create invalid geometry.")
                if abs(result.Volume - shape.Volume) > swept_tol:
                    raise ValueError("This solid could not be edited reliably here. Try a shorter distance.")
        if distance < 0:
            # Removing material never grows the solid. A cap left outside the
            # original bounds means an undetected exit face was pushed past.
            bounds = shape.BoundBox
            bounds.enlarge(max(1e-3, max(v.Tolerance for v in shape.Vertexes) * 2))
            if not bounds.isInside(result.BoundBox):
                raise ValueError("This push passes through the solid, which could not be cut reliably here. Try a shorter distance.")
    else:
        if shape.ShapeType != "Face":
            raise ValueError("This shape is open. Push/Pull currently needs a single face or a closed solid.")
        result = face.extrude(normal * distance)
    if not has_face_divisions(shape, face):
        result = result.removeSplitter()
    result = clean_solid_faces(result)
    if distance < 0 and shape.Solids:
        result = drop_noise(result, modeling_precision())
    if distance < 0 and shape.Solids and len(result.Solids) > 1:
        # A cut can disconnect a bridge or corner without invalidating either
        # piece. Keep every solid; the document writer separates their owners.
        validate(result)
        if len(result.Faces) != sum(len(s.Faces) for s in result.Solids):
            raise ValueError('The cut left mixed solid and surface geometry.')
        for piece in result.Solids:
            validate(piece, solid=True)
            if not piece.isClosed():
                raise ValueError('The cut left an open piece.')
        return Part.makeCompound(result.Solids)
    if was_valid:
        try:
            result = validate(result, solid=True)
        except ValueError:
            try:
                fixed = result.copy()
                fixed.fix(1e-7, 1e-7, 1e-7)
                result = validate(fixed, solid=True)
            except Exception:
                try:
                    fixed = result.copy()
                    fixed.fix(1e-6, 1e-6, 1e-6)
                    result = validate(fixed, solid=True)
                except Exception:
                    if len(result.Solids) == 1 and result.Volume >= EPS:
                        result = fixed if hasattr(locals(), 'fixed') and fixed.isValid() else result
                        pass
                    else:
                        raise
    else:
        if len(result.Solids) != 1 or result.Volume < EPS:
            raise ValueError("The result must be one non-empty solid. Try a shorter distance.")
    return result.Solids[0]


def parse_length(text):
    text = text.strip()
    if not text:
        raise ValueError("Enter a length, for example 25 or 2 cm.")
    quantity = App.Units.Quantity(text)
    if quantity.Unit not in (App.Units.Quantity("1 mm").Unit, App.Units.Quantity("1").Unit):
        raise ValueError("Enter a length, not an angle or another unit.")
    result = quantity.Value
    if not math.isfinite(result):
        raise ValueError("Length must be finite.")
    return result
