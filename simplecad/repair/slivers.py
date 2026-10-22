"""Remove edges and faces smaller than the modeling precision.

Converted meshes and edits on them leave hairline details: edges a few
microns long, strips far narrower than the precision and needle triangles of
zero area. They carry no design, but they make booleans report
self-intersections and stop faces from being aligned or merged.

The shape is read as vertices, edges and face loops. Between flat faces,
straight edges shorter than the precision collapse to one vertex; straight
edges then joining the same two vertices become one edge, so a strip or lens
between them disappears; and a needle triangle is removed by routing its
neighbor's edge through the needle's tip. Curved faces and every vertex they
touch are kept exactly. The flat faces are then rebuilt from their loops.
"""

import FreeCAD as App
import Part

from ..core import geometry as geo

V = App.Vector


class _Sets:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, first, second):
        first, second = self.find(first), self.find(second)
        if first != second:
            self.parent[second] = first
        return first


def perimeter(face):
    """Sum of edge lengths; FreeCAD can crash measuring a face whose boundary
    holds a degenerate spline edge, so degenerate edges are skipped."""
    return sum(edge.Length for edge in face.Edges if not edge.Degenerated)


def _lookup(items):
    table = {}
    for index, item in enumerate(items):
        table.setdefault(hash(item), []).append((index, item))
    return lambda item: next(index for index, other in table.get(hash(item), ()) if other.isSame(item))


class _Open(ValueError):
    """The rebuilt surface has gaps; ``faces`` lists the original faces there."""

    def __init__(self, message, faces):
        super().__init__(message)
        self.faces = faces


def collapse(shape, tolerance, attempts=6):
    """Return (shape without sub-precision edges and faces, report).

    Where a local cleanup would leave a gap, the faces around it are kept
    exactly as they are and the rest is cleaned again.
    """
    protected = set()
    for _ in range(attempts):
        try:
            return _collapse(shape, tolerance, protected)
        except _Open as error:
            if not error.faces or error.faces <= protected:
                raise ValueError(str(error))
            protected |= error.faces
    raise ValueError("Removing slivers left gaps in the surface; the shape is unchanged.")


def _collapse(shape, tolerance, protected):
    faces, edges, vertices = shape.Faces, shape.Edges, shape.Vertexes
    edge_of, vertex_of = _lookup(edges), _lookup(vertices)
    ends = []
    for edge in edges:
        ordered = [vertex_of(vertex) for vertex in edge.Vertexes]
        ends.append((ordered[0], ordered[-1]))
    straight = []
    for edge in edges:
        try:
            straight.append(not edge.Degenerated and isinstance(edge.Curve, Part.Line))
        except (TypeError, ValueError, AttributeError):
            straight.append(False)
    # A protected face is treated like a curved one: kept exactly.
    flat = [isinstance(face.Surface, Part.Plane) and i not in protected for i, face in enumerate(faces)]
    pinned = set()
    for index, face in enumerate(faces):
        if not flat[index]:
            pinned.update(vertex_of(vertex) for vertex in face.Vertexes)
    for index, edge in enumerate(edges):
        if not straight[index]:
            try:
                is_circle = not edge.Degenerated and isinstance(edge.Curve, Part.Circle)
            except (TypeError, ValueError, AttributeError):
                is_circle = False
            if not is_circle:
                pinned.update(ends[index])

    # Each face loop as oriented edge uses: (edge id, forward).
    loops = []
    edge_faces = {}
    for index, face in enumerate(faces):
        face_loops = []
        for wire in [face.OuterWire] + [w for w in face.Wires if not w.isSame(face.OuterWire)]:
            uses = []
            for edge in wire.OrderedEdges:
                e = edge_of(edge)
                edge_faces.setdefault(e, set()).add(index)
                start = vertex_of(edge.Vertexes[0] if edge.Orientation == 'Forward' else edge.Vertexes[-1])
                uses.append((e, start == ends[e][0]))
            face_loops.append(uses)
        loops.append(face_loops)

    # Only edges whose faces are all flat may merge or be rerouted.
    beside_flat = [all(flat[i] for i in edge_faces.get(e, ())) for e in range(len(edges))]
    free = [straight[e] and beside_flat[e] for e in range(len(edges))]

    def close(first, second):
        """Edges within the tolerance of each other along their length."""
        for edge, other in ((edges[first], edges[second]), (edges[second], edges[first])):
            for t in (.25, .5, .75):
                point = edge.valueAt(edge.FirstParameter + t * (edge.LastParameter - edge.FirstParameter))
                if other.distToShape(Part.Vertex(point))[0] > tolerance:
                    return False
        return True
    points = [vertex.Point for vertex in vertices]
    joined = _Sets(len(vertices))
    same_edge = _Sets(len(edges))
    removed_faces = set()
    collapsed = 0

    def endpoints(e):
        return joined.find(ends[e][0]), joined.find(ends[e][1])

    groups = {}

    def position(v):
        members = groups.get(joined.find(v), [v])
        anchors = [i for i in members if i in pinned]
        chosen = anchors or members
        return sum((points[i] for i in chosen), V()) * (1.0 / len(chosen))

    # 1. Collapse short straight edges between flat faces. A group may hold
    # at most one pinned vertex, which then stays exactly where it is; a
    # chain of short edges must not drag two pinned vertices together.
    anchored = {v: v in pinned for v in range(len(vertices))}
    for e, edge in enumerate(edges):
        if not free[e] or edge.Length >= tolerance:
            continue
        a, b = joined.find(ends[e][0]), joined.find(ends[e][1])
        if a == b or (anchored[a] and anchored[b]):
            continue
        root = joined.union(a, b)
        anchored[root] = anchored[a] or anchored[b]
        collapsed += 1
    for v in range(len(vertices)):
        groups.setdefault(joined.find(v), []).append(v)

    def live(uses):
        kept = []
        for e, forward in uses:
            a, b = endpoints(e)
            if a == b and (straight[e] or edges[e].Length < tolerance):
                continue
            kept.append((same_edge.find(e), forward if same_edge.find(e) == e else None, e))
        return kept

    needles = 0
    for _ in range(len(faces)):
        changed = False
        # 2. Edges joining the same two vertices within the tolerance of
        # each other are one edge; a straight one represents the pair.
        by_pair = {}
        for e in range(len(edges)):
            if same_edge.find(e) != e:
                continue
            a, b = endpoints(e)
            if a == b:
                continue
            by_pair.setdefault((min(a, b), max(a, b)), []).append(e)
        for group in by_pair.values():
            # An edge of a curved face is kept as it is; otherwise straight.
            group.sort(key=lambda e: (beside_flat[e], not straight[e]))
            for e in group[1:]:
                keep = group[0]
                if not beside_flat[e]:
                    continue
                if same_edge.find(e) != same_edge.find(keep) and close(keep, e):
                    same_edge.parent[same_edge.find(e)] = same_edge.find(keep)
                    changed = True
        # A flat face left with at most two distinct straight edges has no area.
        for index in range(len(faces)):
            if index in removed_faces or not flat[index]:
                continue
            outer = live(loops[index][0])
            distinct = {root for root, _, _ in outer}
            # A face down to one straight edge, or a thin lens of two, has no
            # area; a disk bounded by one closed circle of course does.
            thin = 2 * faces[index].Area / max(perimeter(faces[index]), 1e-12) < tolerance
            if (len(distinct) <= 1 and (len(outer) != 1 or all(straight[e] for _, _, e in outer))) or (
                    len(distinct) == 2 and len(loops[index]) == 1 and thin):
                if len(distinct) == 2:
                    # The lens's two sides become one edge for its neighbors.
                    # An edge of a curved face must stay, so it is the one kept;
                    # otherwise a straight one wins. The other must be free.
                    pair = sorted(distinct, key=lambda root: (beside_flat[root], not straight[root]))
                    if not beside_flat[pair[1]]:
                        continue
                    same_edge.parent[same_edge.find(pair[1])] = same_edge.find(pair[0])
                removed_faces.add(index)
                changed = True
        # 3. A needle triangle: its tip lies on its longest edge. Route every
        # other use of that edge through the tip and drop the needle.
        for index in range(len(faces)):
            if index in removed_faces or not flat[index] or len(loops[index]) != 1:
                continue
            outer = live(loops[index][0])
            if len(outer) != 3 or not all(straight[e] for _, _, e in outer):
                continue
            face = faces[index]
            if 2 * face.Area / max(perimeter(face), 1e-12) >= tolerance:
                continue
            lengths = []
            for root, _, e in outer:
                a, b = endpoints(e)
                lengths.append(((position(a) - position(b)).Length, root, e))
            longest = max(lengths)
            base = longest[1]
            if not free[longest[2]]:
                continue
            others = [item for item in lengths if item[1] != base]
            a, b = endpoints(longest[2])
            tip = next(v for _, _, e in others for v in endpoints(e) if v not in (a, b))
            if tip in pinned:
                continue
            replacement = {}
            for _, root, e in others:
                p, q = endpoints(e)
                replacement[p if p != tip else q] = e
            for other in range(len(faces)):
                if other == index or other in removed_faces:
                    continue
                for loop_index, uses in enumerate(loops[other]):
                    rebuilt, touched = [], False
                    for e, forward in uses:
                        if same_edge.find(e) != base:
                            rebuilt.append((e, forward))
                            continue
                        touched = True
                        p, q = endpoints(e)
                        start, finish = (p, q) if forward else (q, p)
                        for from_, to in ((start, tip), (tip, finish)):
                            piece = replacement[from_ if from_ != tip else to]
                            pa, pb = endpoints(piece)
                            rebuilt.append((piece, pa == from_))
                    if touched:
                        loops[other][loop_index] = rebuilt
            removed_faces.add(index)
            needles += 1
            changed = True
        if not changed:
            break

    if not collapsed and not removed_faces:
        return shape, {'collapsed_edges': 0, 'removed_faces': 0, 'needles': 0}

    moved = {}
    for v in range(len(vertices)):
        root = joined.find(v)
        if root not in moved:
            moved[root] = position(v)

    def vertex_at(v):
        return moved[joined.find(v)]

    rebuilt_edges = {}

    def new_edge(e):
        root = same_edge.find(e)
        if root in rebuilt_edges:
            return rebuilt_edges[root]
        edge = edges[root]
        a, b = endpoints(root)
        if straight[root]:
            result = Part.makeLine(vertex_at(ends[root][0]), vertex_at(ends[root][1]))
        elif all((vertex_at(v) - points[v]).Length == 0 for v in ends[root]):
            result = edge.copy()
        else:
            middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
            result = Part.Arc(vertex_at(ends[root][0]), middle, vertex_at(ends[root][1])).toShape()
        rebuilt_edges[root] = result
        return result

    def changed_face(index):
        for uses in loops[index]:
            for e, _ in uses:
                if same_edge.find(e) != e or any((vertex_at(v) - points[v]).Length > 0 for v in ends[e]):
                    return True
            if len(live(uses)) != len(uses):
                return True
        return False

    new_faces, kept_order = [], []
    for index, face in enumerate(faces):
        if index in removed_faces:
            continue
        if not changed_face(index):
            new_faces.append(face.copy())
            kept_order.append(index)
            continue
        if not flat[index]:
            raise ValueError("A curved face would change; its slivers are kept.")
        wires = []
        for uses in loops[index]:
            pieces = [new_edge(e) for root, _, e in live(uses)]
            if not pieces:
                continue
            wires.append(Part.Wire(Part.__sortEdges__(pieces)))
        plane = geo.Plane.from_face(face)
        rebuilt = Part.Face(Part.Plane(plane.origin, plane.normal), wires)
        rebuilt.fix(1e-7, 1e-7, tolerance)
        if rebuilt.ShapeType != 'Face':
            if len(rebuilt.Faces) != 1:
                raise ValueError("A face could not be rebuilt without its slivers.")
            rebuilt = rebuilt.Faces[0]
        if geo.face_normal(rebuilt).dot(geo.face_normal(face)) < 0:
            rebuilt.reverse()
        new_faces.append(rebuilt)
        kept_order.append(index)

    sewn = Part.Compound(new_faces)
    sewn.sewShape(max(1e-6, tolerance * 1e-3))
    if len(sewn.Shells) != 1 or len(sewn.Shells[0].Faces) != len(new_faces):
        main = sewn.Shells[0] if sewn.Shells else None
        loose = [kept_order[k] for k, face in enumerate(new_faces)
                 if main is None or not any(face.distToShape(other)[0] < 1e-9 and abs(face.Area - other.Area) < 1e-6
                                            for other in main.Faces)]
        raise _Open("Removing slivers would disconnect the surface.", set(loose))
    pool = list(sewn.Shells[0].Faces)
    ordered = []
    for face in new_faces:
        best = min(range(len(pool)), key=lambda k: ((pool[k].CenterOfMass - face.CenterOfMass).Length,
                                                      abs(pool[k].Area - face.Area)))
        ordered.append(pool.pop(best))
    result = Part.Shell(ordered)
    if shape.Solids:
        if not result.isClosed():
            gaps = result.getFreeEdges().Edges
            culprits = {i for i in removed_faces if any(faces[i].distToShape(gap)[0] < tolerance for gap in gaps)}
            culprits |= {kept_order[k] for k, face in enumerate(new_faces)
                         if changed_face(kept_order[k]) and any(face.distToShape(gap)[0] < 1e-6 for gap in gaps)}
            raise _Open("Removing slivers would open the solid.", culprits)
        result = Part.makeSolid(result)
        if result.Volume < 0:
            result.reverse()
    if not result.isValid():
        result.fix(1e-7, 1e-7, tolerance)
        if not result.isValid():
            raise ValueError("Removing slivers produced invalid geometry.")
    # Repairs can leave OCC's in-memory structures fragile; a round trip
    # through BREP text gives the document a clean, independent shape.
    clean = Part.Shape()
    clean.importBrepFromString(result.exportBrepToString())
    result = clean.Solids[0] if shape.Solids and clean.Solids else clean
    change = tolerance * sum(perimeter(face) for i, face in enumerate(faces) if i in removed_faces) + tolerance ** 2 * collapsed
    if shape.Solids and abs(result.Volume - shape.Volume) > change + 1e-6:
        raise ValueError("Removing slivers would change the volume by more than the precision allows.")
    return result, {'collapsed_edges': collapsed, 'removed_faces': len(removed_faces), 'needles': needles,
                    'kept_faces': kept_order}
