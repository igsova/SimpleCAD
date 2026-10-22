"""Geometric identity for independently built edges/faces, in world coordinates.

OCC isSame only recognizes shared topology. These comparisons require full
coincidence, not a shared endpoint, partial overlap, or equal dimensions alone.
"""
import FreeCAD  # noqa: F401  Load the application before its Part extension.
import Part
import math
from itertools import product

TOL = 1e-7


def same(first, second):
    if first.ShapeType != second.ShapeType:
        return False
    if first.isSame(second):
        return True
    if first.ShapeType not in ("Edge", "Face"):
        return False
    # Display triangulation approximates curves and can change BoundBox after
    # rendering. Compare exact geometry so a visible disk matches a fresh one.
    a = first.optimalBoundingBox(False, False)
    b = second.optimalBoundingBox(False, False)
    # OCC pads optimal spline bounds by its precision tolerance even when
    # shape tolerances are disabled; allow floating-point roundoff at TOL.
    if any(abs(getattr(a, key) - getattr(b, key)) > TOL + 1e-12
           for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")):
        return False
    measure = "Length" if first.ShapeType == "Edge" else "Area"
    x, y = getattr(first, measure), getattr(second, measure)
    tolerance = max(TOL, max(x, y) * 1e-9)
    if abs(x - y) > tolerance:
        return False
    overlap = getattr(first.common(second), measure)
    return abs(overlap - x) <= tolerance and abs(overlap - y) <= tolerance


class Index:
    """Operation-local lookup; exact coincidence still decides every match.

    Cache optimal bounds once and bucket their centers. Neighboring buckets
    preserve tolerance-boundary matches; topology hashes are never trusted
    without isSame. No index survives a geometry edit.
    """
    cell = TOL * 8

    def __init__(self, shapes=()):
        self.shapes, self.boxes = [], []
        self.native, self.spatial = {}, {}
        for shape in shapes:
            self.add(shape)

    @staticmethod
    def bounds(shape):
        if shape.ShapeType not in ('Edge', 'Face'):
            return None
        box = shape.optimalBoundingBox(False, False)
        return tuple(getattr(box, key) for key in ('XMin', 'YMin', 'ZMin', 'XMax', 'YMax', 'ZMax'))

    @classmethod
    def key(cls, box):
        return tuple(math.floor((box[i]/2 + box[i+3]/2)/cls.cell) for i in range(3))

    def add(self, shape):
        index = len(self.shapes)
        self.shapes.append(shape)
        self.native.setdefault(hash(shape), []).append(index)
        box = self.bounds(shape)
        self.boxes.append(box)
        if box is not None:
            self.spatial.setdefault((shape.ShapeType, self.key(box)), []).append(index)
        return index

    def matches(self, shape):
        matched = set()
        for index in self.native.get(hash(shape), ()):
            if shape.isSame(self.shapes[index]):
                matched.add(index)
                yield index
        box = self.bounds(shape)
        if box is None:
            return
        # Delete typically looks for just one or two selected elements among
        # thousands. Checking a few cached boxes is cheaper than visiting all
        # 27 neighboring spatial buckets for every unrelated element.
        if len(self.shapes) <= 8:
            for index, other in enumerate(self.boxes):
                if (index not in matched and other is not None
                        and all(abs(a-b) <= TOL+1e-12 for a, b in zip(box, other))
                        and same(shape, self.shapes[index])):
                    yield index
            return
        center, kind = self.key(box), shape.ShapeType
        for offset in product((-1, 0, 1), repeat=3):
            key = tuple(a+b for a, b in zip(center, offset))
            for index in self.spatial.get((kind, key), ()):
                if (index not in matched
                        and all(abs(a-b) <= TOL+1e-12 for a, b in zip(box, self.boxes[index]))
                        and same(shape, self.shapes[index])):
                    yield index


def unique(shapes):
    index = Index()
    for shape in shapes:
        if next(index.matches(shape), None) is None:
            index.add(shape)
    return index.shapes


def face_owners(faces, edges):
    """Incident face IDs for a small set of edges, including independent copies.

    Index the queried boundaries rather than every boundary of the model.
    Repeated/seam edges count once per face; geometric matches still use same().
    """
    if not edges:
        return []
    lookup = Index(edges)
    owners = [set() for _ in edges]
    for i, face in enumerate(faces):
        for boundary in face.Edges:
            for j in lookup.matches(boundary):
                owners[j].add(i)
    return owners


def loose_edges(shape):
    if shape.ShapeType in ('Solid', 'Shell', 'Face'):
        return []  # Every edge in these native containers belongs to a face.
    boundaries = [edge for face in shape.Faces for edge in face.Edges]
    # The native edge already belongs to a face in almost every solid. Resolve
    # that identity in buckets before asking OCC for geometric coincidence.
    # Keep isSame checks: native hashes may collide and ignore orientation.
    owned = {}
    for edge in boundaries:
        owned.setdefault(hash(edge), []).append(edge)
    candidates = [edge for edge in shape.Edges
                  if not any(edge.isSame(other) for other in owned.get(hash(edge), ()))]
    return [edge for edge in unique(candidates)
            if not any(same(edge, boundary) for boundary in boundaries)]


def assemble(faces, edges=()):
    """Deduplicate and sew surfaces, preserving all deliberate face divisions.

    A nonmanifold junction remains a compound of surfaces; its coincident edges
    still share erase behavior. Never convert open geometry into a solid here.
    """
    faces = unique(faces)
    boundaries = [edge for face in faces for edge in face.Edges]
    edges = [edge for edge in unique(edges)
             if not any(same(edge, boundary) for boundary in boundaries)]
    parts = []
    if faces:
        surface = faces[0].copy() if len(faces) == 1 else Part.makeShell(faces)
        expected_edges = len(unique(boundaries))
        if len(faces) > 1 and len(surface.Edges) > expected_edges:
            surface.sewShape()
        expected_area = sum(face.Area for face in faces)
        if (not surface.isValid() or len(surface.Faces) != len(faces)
                or len(surface.Edges) != expected_edges
                or abs(surface.Area - expected_area) > max(TOL, expected_area * 1e-9)):
            # Nonmanifold surfaces cannot always be represented by one shell.
            # Sewing must not also merge nearby or partly overlapping edges.
            surface = Part.makeCompound(faces)
        if not surface.isValid():
            raise ValueError("The coincident surfaces could not be joined safely.")
        parts.append(surface)
    parts.extend(edges)
    if not parts:
        return None
    result = parts[0] if len(parts) == 1 else Part.makeCompound(parts)
    if not result.isValid():
        raise ValueError("The cleanup would create invalid geometry.")
    return result


def shares_edge(first, second):
    return any(same(a, b) for a in first.Edges for b in second.Edges)
