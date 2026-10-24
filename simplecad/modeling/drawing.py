"""Complete triangular loops and join patches to open native Part surfaces."""
import math

import numpy as np
from ..core import geometry as geo
from ..core import coincident as coinc
import FreeCAD as App
import Part

V = App.Vector
TOL = 1e-6


class EdgeIndex:
    """The edges of some shapes with their bounds, to find the few near a line.

    Completing a face from a new line only involves edges meeting it or its
    plane, but a converted part has tens of thousands. Reading each edge's
    vertices and curve takes seconds; comparing bounds takes milliseconds.
    """
    def __init__(self, shapes, measured=()):
        self.shapes = list(shapes)
        self.edges, self.owners = [], []
        self.parts = []
        lows, highs = [], []
        known = {}
        for part in measured:
            known.setdefault(hash(part[0]), []).append(part)
        for owner, shape in enumerate(self.shapes):
            # A shape unchanged since the last index keeps its edges and bounds.
            part = next((part for part in known.get(hash(shape), ()) if part[0].isSame(shape)), None) or measure(shape)
            self.parts.append(part)
            _, edges, low, high = part
            self.edges.extend(edges)
            self.owners.extend([owner] * len(edges))
            lows.append(low)
            highs.append(high)
        self.low = np.concatenate(lows) if lows else np.empty((0, 3))
        self.high = np.concatenate(highs) if highs else np.empty((0, 3))

    def containing(self, point, pad):
        """Indices, in order, of edges whose bounds come within pad of the point."""
        p = np.array((point.x, point.y, point.z))
        return [int(i) for i in np.nonzero(np.all((self.low - pad <= p) & (p <= self.high + pad), axis=1))[0]]

    def overlapping(self, box, pad):
        low = np.array((box.XMin, box.YMin, box.ZMin)) - pad
        high = np.array((box.XMax, box.YMax, box.ZMax)) + pad
        return [int(i) for i in np.nonzero(np.all((self.low <= high) & (low <= self.high), axis=1))[0]]

    def near_plane(self, origin, normal, pad):
        """Edges whose bounds reach within pad of the plane, as near() tests their corners."""
        n = np.array((normal.x, normal.y, normal.z))
        center, half = (self.low + self.high) / 2, (self.high - self.low) / 2
        distance = (center - np.array((origin.x, origin.y, origin.z))) @ n
        reach = half @ np.abs(n)
        return [int(i) for i in np.nonzero((distance - reach <= pad) & (distance + reach >= -pad))[0]]


def measure(shape):
    """(shape, edges, lower bounds, upper bounds) of one shape's edges."""
    edges = shape.Edges
    boxes = [edge.BoundBox for edge in edges]
    low = np.array([(b.XMin, b.YMin, b.ZMin) for b in boxes], dtype=float).reshape(-1, 3)
    high = np.array([(b.XMax, b.YMax, b.ZMax) for b in boxes], dtype=float).reshape(-1, 3)
    return shape, edges, low, high


_index = None


def edge_index(shapes):
    """One index per model state, shared by every completion search of a line.

    Each new line is a new object, so the model state changes on every
    segment. Only shapes that changed are measured again: re-reading every
    edge of a converted part took over a second per segment.
    """
    global _index
    shapes = list(shapes)
    if (_index is None or len(_index.shapes) != len(shapes)
            or not all(a.isSame(b) for a, b in zip(_index.shapes, shapes))):
        _index = EdgeIndex(shapes, _index.parts if _index is not None else ())
    return _index


def boundary_of(faces):
    return Part.makeCompound([edge for face in faces for edge in face.Edges])


def covers_surface(shapes, face):
    """Whether a new flat face would lie over an existing one a hair off its plane.

    Triangles of a converted mesh lean against each other by fractions of a
    micron, so an exact common() finds no overlap and a duplicate face
    would be drawn over them.
    """
    if not face.Edges or not all(isinstance(edge.Curve, Part.Line) for edge in face.Edges):
        return False
    try:
        normal = geo.face_normal(face)
    except ValueError:
        return False
    flat = geo.modeling_precision() * .01
    corners = [vertex.Point for vertex in face.OuterWire.OrderedVertexes]
    for shape in shapes:
        if not shape.countElement('Face'):
            continue
        index = geo.face_index(shape)
        for i in index.near(face.BoundBox, flat):
            if not index.planar[i]:
                continue
            other = index.faces[i]
            plane = geo.Plane.from_face(other)
            if abs(plane.normal.dot(normal)) < 1 - 1e-6:
                continue
            if any(abs((point - plane.origin).dot(plane.normal)) > flat for point in corners):
                continue
            projected = [plane.project(point) for point in corners]
            try:
                flattened = Part.Face(Part.makePolygon(projected + projected[:1]))
            except (Part.OCCError, RuntimeError, ValueError):
                continue
            if other.common(flattened).Area > TOL:
                return True
    return False


# Index bounds follow display meshes, which can sit inside curved geometry by
# their deflection, a small fraction of the model's size. Faces whose index
# bounds come this close to a new loop are measured with exact bounds.
NEAR_FRACTION = .05


def interior_point(face):
    """A point of a face away from its boundary, or None."""
    work = face.copy()  # Keep any triangulation off the face itself.
    points, triangles = work.tessellate(max(1e-3, face.BoundBox.DiagonalLength / 50))
    boundary = Part.makeCompound(face.Edges)

    def area(triangle):
        a, b, c = (points[i] for i in triangle)
        return (b - a).cross(c - a).Length

    for triangle in sorted(triangles, key=area, reverse=True)[:8]:
        point = sum((points[i] for i in triangle), V()) * (1 / 3)
        u, v = face.Surface.parameter(point)
        if face.isPartOfDomain(u, v) and boundary.distToShape(Part.Vertex(point))[0] > 1e-3:
            return face.Surface.value(u, v)
    return None


def overlaps(shape, face):
    """Whether a new face overlaps a shape: its common() has area.

    That Boolean re-intersects every face of the shape, seconds per loop on a
    converted part. Only faces that come within a tolerance margin of the loop
    can share area with it, and area a loop shares with a solid's boundary is
    part of its common() too, so those few faces decide a loop drawn on the
    shape's skin. When no face comes that close, the boundary can neither
    cross nor touch the loop: it lies wholly inside or wholly outside each
    solid, and one interior point decides. A loop that crosses into a solid
    is still measured by the whole Boolean, as before.
    """
    index = geo.face_index(shape)
    reach = max(1e-3, 2 * shape.getTolerance(1), 2 * face.getTolerance(1))
    box = face.optimalBoundingBox(False, True)
    box.enlarge(reach)
    extent = float((index.bounds[:, 3:].max(axis=0) - index.bounds[:, :3].min(axis=0)).sum()) if index.faces else 0.0
    touching = []
    for i in index.near(box, NEAR_FRACTION * extent):
        other = index.faces[i]
        bounds = other.optimalBoundingBox(False, True)
        if bounds.isValid() and not bounds.intersect(box):
            continue
        if other.distToShape(face)[0] <= reach:
            touching.append(other)
    solids = shape.Solids
    if touching:
        if Part.makeCompound(touching).common(face).Area > TOL:
            return True
        return bool(solids) and shape.common(face).Area > TOL
    if not solids:
        return False
    point = interior_point(face)
    if point is None:
        return shape.common(face).Area > TOL
    return any(solid.isInside(point, TOL, True) for solid in solids)


def triangle_completions(shapes, first, second):
    """Find missing triangles whose two other sides already exist.

    Endpoints can belong to different objects/faces. Existing surfaces and solid
    interiors are excluded, so drawing a connection never adds a duplicate face
    or a face through a solid. Larger polygon loops are a later feature.
    """
    index = edge_index(shapes)
    known = {}

    def segment(i):
        if i not in known:
            edge, known[i] = index.edges[i], None
            # Sphere poles are valid degenerate edges without a 3D Curve. They
            # are topology, not drawable segments; filter them before Curve.
            if (not edge.Degenerated and len(edge.Vertexes) == 2
                    and edge.Length > TOL and isinstance(edge.Curve, Part.Line)):
                start, end = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
                # A converted mesh can leave a tiny edge whose two ends are
                # one vertex. It has length but no direction and bounds no
                # triangle.
                if (end - start).Length > TOL:
                    known[i] = start, end
        return known[i]

    def segments(point):
        """The segments that can pass within TOL of a point, in edge order."""
        return [item for item in (segment(i) for i in index.containing(point, 2 * TOL)) if item is not None]

    def neighbors(point):
        candidates = []

        def add(other):
            if (other - point).Length > TOL and not any((other - p).Length < TOL for p in candidates):
                candidates.append(other)

        for start, end in segments(point):
            direction = end - start
            t = (point - start).dot(direction) / direction.dot(direction)
            nearest = start + direction * max(0, min(1, t))
            if (nearest - point).Length > TOL:
                continue
            add(start)
            add(end)
        # Native faces can have collinear boundary segments after earlier edits.
        # Follow those segments so an extra vertex does not prevent a triangle.
        for current in candidates:
            direction = geo.unit(current - point)
            for start, end in segments(current):
                if (start - current).Length < TOL:
                    other = end
                elif (end - current).Length < TOL:
                    other = start
                else:
                    continue
                if direction.cross(other - point).Length < TOL:
                    add(other)
        return candidates

    starts, ends = neighbors(first), neighbors(second)
    result = []
    for third in starts:
        if not any((third - point).Length < TOL for point in ends):
            continue
        if (second - first).cross(third - first).Length < TOL:
            continue
        face = Part.Face(Part.makePolygon([first, second, third, first]))
        if not face.isValid():
            continue
        # common() with a solid includes portions lying inside its volume.
        if covers_surface(shapes, face) or any(overlaps(shape, face) for shape in shapes if shape.Faces):
            continue
        if any(existing.common(face).Area > TOL for existing in result):
            continue
        result.append(face)
    return result


MAX_LOOP_EDGES = 200


def open_boundary(shape):
    """Edges of an open surface that bound only one face."""
    if shape.Solids or not shape.Faces:
        return []
    owners = {}
    for face in shape.Faces:
        for edge in face.Edges:
            owners.setdefault(hash(edge), []).append(edge)
    return [edge for edge in shape.Edges
            if sum(1 for other in owners.get(hash(edge), ()) if edge.isSame(other)) == 1]


def split_at(item, points, tolerance):
    """Split an edge where given points lie inside it (not at its ends)."""
    parameters = []
    for point in points:
        if any((vertex.Point - point).Length <= tolerance for vertex in item.Vertexes):
            continue
        box = item.BoundBox
        box.enlarge(tolerance)
        if not box.isInside(point) or item.distToShape(Part.Vertex(point))[0] > tolerance:
            continue
        try:
            parameter = item.Curve.parameter(point)
        except (Part.OCCError, RuntimeError, ValueError, TypeError):
            continue
        if item.FirstParameter + 1e-9 < parameter < item.LastParameter - 1e-9:
            parameters.append(parameter)
    if not parameters:
        return [item]
    # Build pieces from the world-space curve: Edge.split() drops the
    # placement of an edge shared from a moved or copied sub-shape.
    bounds = [item.FirstParameter] + sorted(parameters) + [item.LastParameter]
    try:
        return [item.Curve.toShape(low, high) for low, high in zip(bounds, bounds[1:]) if high - low > 1e-9]
    except (Part.OCCError, RuntimeError, ValueError):
        return [item]


def loop_plane(edges, flatness):
    """The plane a new face across a loop should lie on.

    Fit all the loop's points, not just the new edge and a neighbor, and use
    an exact world axis when every point stays within the precision of that
    plane. A face tilted by micro-radians would later push or cut off-axis
    and leave skins where it should meet parallel faces.
    """
    points = []
    for item in edges:
        points.extend(vertex.Point for vertex in item.Vertexes)
        points.extend(item.valueAt(item.FirstParameter + t * (item.LastParameter - item.FirstParameter))
                      for t in (.25, .5, .75))
    center = sum(points, V()) * (1.0 / len(points))
    spread = [[(point - center)[i] for i in range(3)] for point in points]
    import numpy as np
    normal = V(*np.linalg.svd(np.asarray(spread), full_matrices=False)[2][-1])
    for axis in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
        if abs(abs(normal.dot(axis)) - 1) < 1e-2 and all(abs((point - center).dot(axis)) <= flatness for point in points):
            normal = axis * (1 if normal.dot(axis) > 0 else -1)
            break
    return Part.Plane(center, normal)


def split_at_face_edges(edge, shapes):
    """Pieces of a new edge, split where it crosses onto or off a flat face.

    A line that starts on a face and runs past its edge, as SketchUp has it,
    divides the face with the part on it and can close a face beside it with
    the rest. Returns [(piece, on_face)], the pieces on faces first: dividing
    the face gives its boundary the vertices that a loop beside it passes
    through. An edge wholly on faces or wholly off them stays whole.
    """
    if edge.Degenerated or not edge.Vertexes:
        return [(edge, False)]
    flat = geo.modeling_precision() * .01
    samples = [edge.valueAt(edge.FirstParameter + t * (edge.LastParameter - edge.FirstParameter))
               for t in (0, .25, .5, .75, 1)]
    faces = []
    for shape in shapes:
        if not shape.countElement('Face'):
            continue
        index = geo.face_index(shape)
        for i in index.near(edge.BoundBox, flat):
            if not index.planar[i]:
                continue
            face = index.faces[i]
            plane = geo.Plane.from_face(face)
            # Within what divide_face_with_edges counts as on the face.
            allowance = max(1e-7, face.getTolerance(1, Part.Vertex), flat)
            if all(abs((point - plane.origin).dot(plane.normal)) <= allowance for point in samples):
                faces.append(face)
    on = Part.makeCompound(faces).common(edge).Edges if faces else []
    if not on:
        return [(edge, False)]
    # Where faces meet, the covered pieces share an end; only an end no other
    # piece shares is where the edge crosses onto or off the faces.
    ends = [vertex.Point for item in on for vertex in item.Vertexes]
    crossings = [point for point in ends if sum((other - point).Length <= TOL for other in ends) == 1]
    if edge.isClosed() and edge.Curve.isPeriodic():
        # A circle runs on past its seam: one arc between each two crossings.
        start = edge.FirstParameter
        period = edge.LastParameter - start
        found = sorted({round(start + (edge.Curve.parameter(point) - start) % period, 12) for point in crossings})
        bounds = found + [found[0] + period] if len(found) > 1 else []
        pieces = [edge.Curve.toShape(low, high) for low, high in zip(bounds, bounds[1:])] or [edge]
    else:
        pieces = split_at(edge, crossings, TOL)
    covered = Part.makeCompound(on)

    def lies_on(piece):
        middle = piece.valueAt((piece.FirstParameter + piece.LastParameter) / 2)
        return covered.distToShape(Part.Vertex(middle))[0] <= TOL
    return sorted(((piece, lies_on(piece)) for piece in pieces), key=lambda item: not item[1])


def loop_completions(shapes, edge, loose=()):
    """Faces for flat loops that a new edge closes, as SketchUp does.

    Any edge may take part: the open boundary of a surface (for example the
    opening left by deleted faces), loose lines, and the edges of existing
    faces, such as the circular rim of a hole a line is drawn across. Edges
    are split where the new edge ends inside them. From each end of the new
    edge the walk keeps turning as tightly as possible to one side, which
    traces the smallest region bounded there. Loops that overlap an existing
    face or pass through a solid are rejected.
    """
    if edge.Degenerated or len(edge.Vertexes) != 2:
        return []
    flatness = geo.modeling_precision()
    first, second = (vertex.Point for vertex in edge.Vertexes)
    lookup = edge_index(shapes)
    count = len(lookup.edges)
    everything = lookup.edges + list(loose)
    # Only an edge whose bounds meet the new edge's can coincide with it.
    reach = set(lookup.overlapping(edge.BoundBox, 10 * TOL)) | set(range(count, len(everything)))
    usable = {}

    def pool_item(i):
        """Whether an edge can join a loop; tested only for edges near it."""
        if i not in usable:
            item = everything[i]
            usable[i] = (not item.Degenerated and item.Length > TOL
                         and (i not in reach or not coinc.same(item, edge)))
        return usable[i]

    def nearby(point):
        found = lookup.containing(point, flatness)
        for i in range(count, len(everything)):
            box = everything[i].BoundBox
            box.enlarge(flatness)
            if box.isInside(point):
                found.append(i)
        return found
    touching, touched = [], set()
    for i in sorted(set(nearby(first)) | set(nearby(second))):
        item = everything[i]
        if pool_item(i) and min(item.distToShape(Part.Vertex(point))[0] for point in (first, second)) <= flatness:
            touching.append(item)
            touched.add(i)
    planes = []
    for item in touching:
        samples = [vertex.Point for vertex in item.Vertexes] + [
            item.valueAt(item.FirstParameter + t * (item.LastParameter - item.FirstParameter)) for t in (.25, .5, .75)]
        for end in samples:
            normal = (second - first).cross(end - first)
            if normal.Length < 1e-6 * max(1.0, (second - first).Length * (end - first).Length):
                continue
            normal = geo.unit(normal)
            if not any(abs(abs(normal.dot(other)) - 1) < 1e-9 for other in planes):
                planes.append(normal)
    # A loose line drawn earlier from a point inside an edge meets the edge
    # there, as the new one does at its ends.
    ends = {}
    for point in {(v.x, v.y, v.z) for item in everything[count:] for v in (item.Vertexes[0].Point, item.Vertexes[-1].Point)}:
        for i in nearby(V(*point)):
            ends.setdefault(i, []).append(V(*point))
    pieces = {}

    def graph_pieces(i):
        """The edge's usable pieces, split only where a new or loose line ends."""
        if i not in pieces:
            item = everything[i]
            points = ([first, second] if i in touched else []) + ends.get(i, [])
            parts = split_at(item, points, flatness) if points else [item]
            pieces[i] = [piece for piece in parts if len(piece.Vertexes) == 2 and piece.Length > TOL]
        return pieces[i]
    # Edges within the modeling precision of one plane close a flat loop;
    # converted walls often lean by a few microns.
    result = []
    for normal in planes:
        plane = geo.Plane.from_normal(first, normal)
        # Only edges whose bounds reach the plane can hold one of its pieces.
        candidates = lookup.near_plane(plane.origin, plane.normal, 2 * flatness) + list(range(count, len(everything)))
        graph = [piece for i in candidates if pool_item(i) for piece in graph_pieces(i)]

        def flat(item):
            samples = [v.Point for v in item.Vertexes] + [item.valueAt(item.FirstParameter + t * (item.LastParameter - item.FirstParameter)) for t in (.25, .5, .75)]
            return all(abs((point - plane.origin).dot(plane.normal)) <= flatness for point in samples)

        def near(item):
            box = item.BoundBox
            corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
            sides = [(corner - plane.origin).dot(plane.normal) for corner in corners]
            return min(sides) <= flatness and max(sides) >= -flatness

        edges = [edge] + [item for item in graph if near(item) and flat(item)]
        nodes, cells = [], {}

        def node(point):
            # The first node within the precision, found through a grid of
            # precision-sized cells rather than a scan of every node.
            key = tuple(math.floor(value / flatness) for value in (point.x, point.y, point.z))
            matches = [i for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                       for i in cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ())
                       if (nodes[i] - point).Length <= flatness]
            if matches:
                return min(matches)
            nodes.append(point)
            cells.setdefault(key, []).append(len(nodes) - 1)
            return len(nodes) - 1

        links = []
        for index, item in enumerate(edges):
            start, end = node(item.Vertexes[0].Point), node(item.Vertexes[-1].Point)
            if start != end:
                links.append((start, end, index))

        def heading(item, at_start):
            parameter = item.FirstParameter if at_start else item.LastParameter
            tangent = item.tangentAt(parameter)
            if not at_start:
                tangent = tangent * -1
            return math.atan2(tangent.dot(plane.v), tangent.dot(plane.u))

        outgoing = {}
        for start, end, index in links:
            item = edges[index]
            outgoing.setdefault(start, []).append((heading(item, True), end, index, True))
            outgoing.setdefault(end, []).append((heading(item, False), start, index, False))
        start_node, end_node = node(first), node(second)
        for begin, finish, forward in ((start_node, end_node, True), (end_node, start_node, False)):
            path, used, current = [(0, forward)], {0}, finish
            # Direction back along the edge just traversed, at its far end.
            back = heading(edge, not forward)
            closed = False
            for _ in range(MAX_LOOP_EDGES):
                if current == begin:
                    closed = True
                    break
                options = [option for option in outgoing.get(current, ()) if option[2] not in used]
                if not options:
                    break
                # The first edge clockwise from the way back turns most
                # tightly left, keeping the traced region on the left.
                choice = min(options, key=lambda option: (back - option[0]) % math.tau or math.tau)
                path.append((choice[2], choice[3]))
                used.add(choice[2])
                back = heading(edges[choice[2]], not choice[3])
                current = choice[1]
            # A line and one arc can enclose a region; two lines cannot, and
            # the zero-area check below rejects them.
            if not closed or len(path) < 2:
                continue
            try:
                loop = [edges[index] for index, _ in path]
                wire = Part.Wire(Part.__sortEdges__(loop))
                face = Part.Face(loop_plane(loop, flatness), wire)
                face.fix(TOL, TOL, flatness)
            except (Part.OCCError, RuntimeError, ValueError):
                continue
            if not face.isValid() or face.Area <= TOL or len(face.Wires) != 1:
                continue
            # Both reject the loop; the indexed test is the cheaper one.
            if covers_surface(shapes, face) or any(overlaps(shape, face) for shape in shapes if shape.Faces):
                continue
            if any(existing.common(face).Area > TOL for existing in result):
                continue
            result.append(face)
    return result


def attach_triangles(shape, faces):
    """Join patches to an open surface when the result remains manifold.

    A triangle bridging a closed solid stays a separate face object; adding it
    to that solid's existing boundary would create edges with three faces.
    """
    if shape.Solids or not shape.Faces or len(faces) > 2:
        return None
    # Build native incidence once. Scanning every face for every edge made a
    # small patch on an imported shell take millions of wrapper comparisons.
    owners = {}
    for i, face in enumerate(shape.Faces):
        for edge in face.Edges:
            owners.setdefault(hash(edge), []).append((edge, i))
    boundary, interior = [], []
    for edge in shape.Edges:
        count = len({i for other, i in owners.get(hash(edge), ()) if edge.isSame(other)})
        if count == 1:
            boundary.append(edge)
        elif count > 1:
            interior.append(edge)
    if not boundary:
        return None
    wires = [boundary_of([face]) for face in faces]
    # Only edges near the new patches can touch them; skip booleans on the
    # rest of a large imported shell.
    reach = faces[0].BoundBox
    for face in faces[1:]:
        reach.add(face.BoundBox)
    reach.enlarge(10 * TOL)
    boundary = [edge for edge in boundary if reach.intersect(edge.BoundBox)]
    interior = [edge for edge in interior if reach.intersect(edge.BoundBox)]
    # Each free boundary already has one face. Attaching two patches to that
    # same boundary would give it three, even if sewing leaves duplicate edges.
    if any(sum(wire.common(edge).Length > TOL for wire in wires) > 1 for edge in boundary):
        return None
    for wire in wires:
        if not any(wire.common(edge).Length > TOL for edge in boundary):
            return None
        if any(wire.common(edge).Length > TOL for edge in interior):
            return None
    # fix() can mutate shared underlying edges; keep the source/Undo snapshot
    # independent from the shell being repaired.
    surface = Part.makeShell(shape.Faces + faces).copy()
    surface.sewShape()
    if not surface.isValid():
        surface.fix(TOL, TOL, TOL)
    if not surface.isValid() or len(surface.Faces) != len(shape.Faces) + len(faces):
        return None
    if abs(surface.Area - shape.Area - sum(face.Area for face in faces)) > TOL:
        return None
    if surface.isClosed():
        solid = Part.makeSolid(surface)
        if not solid.isValid():
            solid.fix(TOL, TOL, TOL)
        if solid.Volume < 0:
            solid.reverse()
        surface = geo.validate(solid, solid=True)
    added_boundary = boundary_of(faces)
    loose = [edge for edge in coinc.loose_edges(shape)
             if added_boundary.common(edge).Length < edge.Length - TOL]
    return geo.validate(Part.makeCompound([surface] + loose) if loose else surface)
